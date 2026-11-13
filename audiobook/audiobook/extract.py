"""PDF → DoclingDocument. The only module that imports Docling's converter."""

import hashlib
import json
import threading
import unicodedata
from functools import reduce
from pathlib import Path

from docling_core.types.doc import DoclingDocument

from .dashes import Dashes
from .dashes import read as read_dashes
from .dashes import restore as restore_text
from .names import is_placeholder_title

CACHE_DIR = Path(".cache/docling")

# PDFium is not thread-safe, and the MCP door runs every call on a worker thread of its own. Two calls opening a PDF at
# once failed ("Data format error") and, on 2026-11-13, took the whole tool server down with a segmentation fault. Every
# use of it here is behind this lock, and what it opens is closed inside it, so a garbage collection on another thread
# cannot free it in the middle of someone else's call.
_PDFIUM = threading.Lock()


def pdf_hash(pdf: Path) -> str:
    return hashlib.sha256(pdf.read_bytes()).hexdigest()


def pdf_metadata(pdf: Path) -> tuple[str | None, str | None]:
    """(title, author) from the PDF's document info, when set to something that names the book: a title the
    program that made the PDF filled in by itself ("about:blank", "Microsoft Word - draft.docx") is not one."""
    import pypdfium2  # installed with Docling

    with _PDFIUM:
        document = pypdfium2.PdfDocument(str(pdf))
        try:
            info = document.get_metadata_dict()
        finally:
            document.close()
    title = (info.get("Title") or "").strip()
    return (None if is_placeholder_title(title) else title) or None, (info.get("Author") or "").strip() or None


def is_extracted(pdf: Path) -> bool:
    """Whether Docling has already analysed this PDF (so planning is instant)."""
    return (CACHE_DIR / f"{pdf_hash(pdf)}.json").exists()


# Fewer characters than this per page after a normal pass means the pages are images (a scan).
MIN_CHARS_PER_PAGE = 200


def extract(pdf: Path, on_status=lambda _: None) -> DoclingDocument:
    """Run Docling layout analysis on a PDF, cached by the PDF's content hash. Scanned PDFs (no
    text layer) are detected and re-run with OCR, which is much slower."""
    key = pdf_hash(pdf)
    cached = CACHE_DIR / f"{key}.json"
    if cached.exists():
        return restore_dashes(DoclingDocument.load_from_json(cached), _dashes_by_page(pdf, key))

    doc = _convert(pdf, ocr=False)
    pages = max(len(doc.pages), 1)
    if len(doc.export_to_text()) / pages < MIN_CHARS_PER_PAGE:
        on_status(f"No text layer found: reading {pages} pages with OCR (slow)...")
        doc = _convert(pdf, ocr=True)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    doc.save_as_json(cached)        # Docling's own output, as it came: the dashes are put back each time it is read
    return restore_dashes(doc, _dashes_by_page(pdf, key))


# ---- dashes (dashes.py): Docling writes every em and en dash as "-" and closes up a word split across a line ------------

DASHES_VERSION = 1


def _page_texts(pdf: Path) -> list[str]:
    """The PDF's own text layer, a string per page (ligatures spelled out, as Docling spells them)."""
    import pypdfium2  # installed with Docling

    with _PDFIUM:
        document = pypdfium2.PdfDocument(str(pdf))
        try:
            texts = []
            for n in range(len(document)):
                page = document[n]
                textpage = page.get_textpage()
                try:
                    texts.append(unicodedata.normalize("NFKC", textpage.get_text_range()))
                finally:
                    textpage.close()
                    page.close()
            return texts
        finally:
            document.close()


def _dashes_by_page(pdf: Path, key: str) -> dict[int, Dashes]:
    """Each page's dashes, read from the PDF's text layer once and kept beside Docling's cache. A PDF whose text layer
    cannot be read goes through as Docling gave it, as it always did."""
    path = CACHE_DIR / f"{key}.dashes.json"
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        if saved.get("v") == DASHES_VERSION:
            return {int(n): Dashes.from_json(d) for n, d in saved["pages"].items()}
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        pages = {n: read_dashes(text) for n, text in enumerate(_page_texts(pdf), 1)}
    except Exception:  # noqa: BLE001 -- anything pdfium cannot do must not stop the book being read
        return {}
    pages = {n: d for n, d in pages.items() if d}
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"v": DASHES_VERSION, "pages": {str(n): d.to_json() for n, d in pages.items()}}), encoding="utf-8")
    except OSError:
        pass
    return pages


def restore_dashes(doc: DoclingDocument, by_page: dict[int, Dashes]) -> DoclingDocument:
    """Put the dashes back in the document's text, each item from the pages it sits on (an item that runs over a page
    break gets both)."""
    if not by_page:
        return doc
    merged: dict[tuple[int, ...], Dashes] = {}
    for item in doc.texts:
        pages = tuple(sorted({p.page_no for p in item.prov if p.page_no in by_page}))
        if not pages:
            continue
        if pages not in merged:
            merged[pages] = reduce(lambda a, b: a.merge(b), (by_page[n] for n in pages))
        fixed = restore_text(item.text, merged[pages])
        if fixed != item.text:
            item.text = fixed
    return doc


def _convert(pdf: Path, ocr: bool) -> DoclingDocument:
    # Imported lazily: loading the layout models takes several seconds.
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    # Tables are skipped when reading aloud, so their cell structure isn't needed.
    options = PdfPipelineOptions(do_ocr=ocr, do_table_structure=False)
    if ocr:
        # RapidOCR ships with Docling; its torch backend reuses our PyTorch (no onnxruntime needed).
        # Forced on whole pages, since there is no text layer to keep.
        options.ocr_options = RapidOcrOptions(force_full_page_ocr=True, lang=["english"], backend="torch")
    converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})
    return converter.convert(str(pdf)).document
