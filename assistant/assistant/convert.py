"""A document a person attaches -- a PDF, a Word file, plain text -- turned into text the assistant can keep, the
way it keeps markdown (texts.py), so the model reads it with `read_document` and the tools that take documents
(docu-ai, apply-ai) take it too.

This is intake, like checking that markdown is UTF-8: it changes a file's format and knows nothing of what a
document means. Pictures, fonts and layout are not kept.

**A PDF or Word file is read in a child process of its own, never in the backend.** Both are someone else's file
format read by a native library (PDFium, libxml2): PDFium has crashed the audiobook tool before
(`reference-pdfium-thread-safety`), and in the backend a crash would end every page's connection and every tool with
it. The child runs `python -m assistant.convert <file>` with no secrets in its environment, a memory limit and a
time limit, and answers one line of JSON. Whatever goes wrong in it -- a crash, a hang, a library's exception -- is
this one upload refused, said plainly.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

# What can be attached as a document, beside markdown (which is stored as it came).
CONVERTIBLE = {".pdf", ".docx", ".txt"}
# Read in a child process: someone else's binary format, read by native code.
IN_CHILD = {".pdf", ".docx"}
# A scanned book is a photograph of every page; a long report with figures is tens of MB.
MAX_DOCUMENT_BYTES = 100 * 1024**2
# Reading a 300-page PDF's text layer takes a few seconds; a minute means something is wrong with the file.
TIMEOUT = 90
# The child's address space. Well above what a large PDF needs, well below what would starve the machine.
MEMORY_LIMIT = 3 * 1024**3
# What the child may print: the text, as JSON, of a document that is at most the database's 20 MB (uploads.py).
MAX_ANSWER_BYTES = 64 * 1024**2
# What the child inherits. Not the token, the database's address or a model key: it reads a stranger's file.
CHILD_ENV = ("PATH", "LANG", "LC_ALL", "TMPDIR")

#: How PDFium marks a hyphen at the end of a line (pdf_text).
HYPHEN_MARK = "￾"
# Control characters, and NUL, which no text holds and PostgreSQL's text type cannot. Newlines and tabs stay.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f￾￿]")
_BLANK_RUN = re.compile(r"\n{3,}")


class ConversionError(Exception):
    """A file that cannot be turned into text, phrased for the person who attached it."""


def tidy(text: str) -> str:
    """One text, whatever it came from: Unix line ends, no control characters, no trailing spaces, at most one
    blank line in a row, ending in one newline."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL.sub("", text)
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return _BLANK_RUN.sub("\n\n", text).strip() + "\n"


def plain_text(name: str, data: bytes) -> str:
    """A .txt file: UTF-8 (with or without the mark Windows puts at the start), or UTF-16 with its mark."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError:
            raise ConversionError(f"{name} is not text this can read") from None
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ConversionError(f"{name} is not UTF-8 text: save it as UTF-8 and attach it again") from None


def pdf_text(path: Path, name: str) -> str:
    """The PDF's own text layer, page by page, with ligatures spelled out (as audiobook reads it)."""
    import pypdfium2
    from pypdfium2 import PdfiumError

    try:
        document = pypdfium2.PdfDocument(str(path))
    except PdfiumError as error:
        if "password" in str(error).lower():
            raise ConversionError(f"{name} is locked with a password: remove it and attach it again") from None
        raise ConversionError(f"{name} is not a PDF this can read") from None
    try:
        pages = []
        for n in range(len(document)):
            page = document[n]
            textpage = page.get_textpage()
            try:
                pages.append(unicodedata.normalize("NFKC", textpage.get_text_range()))
            finally:
                textpage.close()
                page.close()
    finally:
        document.close()
    # PDFium joins a word that runs over a line end at a hyphen, and marks the hyphen with U+FFFE: "Role-Based",
    # "multi-agent" and "distin-guishes" alike (2026-11-20: 21 of them in a 36-page paper, about half real
    # compounds; both in a real CV were). The hyphen is kept: a split word with a hyphen in it still reads, where a
    # compound without one ("RoleBased", "selfsacrifice") is a word nobody wrote, and the CV checks match words.
    return "\n\n".join(page.strip().replace(HYPHEN_MARK, "-") for page in pages if page.strip())


def docx_text(path: Path, name: str) -> str:
    """A Word file's paragraphs and tables in order, as markdown: headings as headings, list items as items, a
    table a row to a line. Headers, footers, comments and pictures are not read."""
    import docx
    from docx.opc.exceptions import PackageNotFoundError
    from docx.table import Table

    try:
        document = docx.Document(str(path))
    except (PackageNotFoundError, KeyError, ValueError, OSError) as error:
        raise ConversionError(f"{name} is not a Word (.docx) file this can read") from error

    blocks: list[str] = []
    for block in document.iter_inner_content():
        if isinstance(block, Table):
            rows = []
            for row in block.rows:
                cells: list[str] = []
                for cell in row.cells:  # a merged cell is listed once for every column it spans
                    words = " ".join(cell.text.split())
                    if words and (not cells or cells[-1] != words):
                        cells.append(words)
                if cells:
                    rows.append(" | ".join(cells))
            if rows:
                blocks.append("\n".join(rows))
            continue
        words = block.text.strip()
        if not words:
            continue
        style = (block.style.name if block.style is not None else "") or ""
        heading = re.fullmatch(r"Heading ([1-6])", style)
        if style == "Title":
            blocks.append(f"# {words}")
        elif heading:
            blocks.append(f"{'#' * int(heading.group(1))} {words}")
        elif style.startswith("List") or _numbered(block):
            # Items of one list stay together: markdown ends a list at a blank line.
            if blocks and blocks[-1].startswith("- ") and blocks[-1].count("\n\n") == 0:
                blocks[-1] += f"\n- {words}"
            else:
                blocks.append(f"- {words}")
        else:
            blocks.append(words)
    return "\n\n".join(blocks)


def _numbered(paragraph) -> bool:
    """Word marks an item of a bulleted or numbered list by numbering it, whatever its style is called."""
    properties = paragraph._p.pPr
    return properties is not None and properties.numPr is not None


def read(path: Path, name: str) -> str:
    """The text of one document, tidied. Refused when there is none to read."""
    suffix = Path(name).suffix.lower()
    if suffix == ".pdf":
        text = pdf_text(path, name)
    elif suffix == ".docx":
        text = docx_text(path, name)
    elif suffix == ".txt":
        text = plain_text(name, path.read_bytes())
    else:
        raise ConversionError(f"{name} is not a kind of document this can read")
    text = tidy(text)
    if not text.strip():
        if suffix == ".pdf":
            raise ConversionError(f"{name} has no text in it to read: it may be scanned pages, which this cannot read")
        raise ConversionError(f"{name} has no text in it")
    return text


# ---------------------------------------------------------------------------
# The parent's side: run the child, and turn every way it can fail into a refusal.
# ---------------------------------------------------------------------------

# The folder `python -m assistant.server` runs from, so the child imports this same package.
_PACKAGE_HOME = Path(__file__).resolve().parents[1]


def child_env() -> dict[str, str]:
    return {key: os.environ[key] for key in CHILD_ENV if key in os.environ}


def command(path: Path, name: str) -> list[str]:
    return [sys.executable, "-m", "assistant.convert", str(path), name]


async def text_of(path: Path, name: str, timeout: float = TIMEOUT) -> str:
    """The text of the document at `path` (attached as `name`). Plain text is read here; anything else in a child.
    Raises ConversionError, phrased for the person, for every way it can fail."""
    if Path(name).suffix.lower() not in IN_CHILD:
        return read(path, name)
    process = await asyncio.create_subprocess_exec(
        *command(path, name), cwd=_PACKAGE_HOME, env=child_env(),
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(process.communicate(), timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise ConversionError(f"{name} took too long to read (over {timeout:g} seconds)") from None
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise
    if process.returncode != 0 or not out or len(out) > MAX_ANSWER_BYTES:
        detail = err.decode("utf-8", "replace").strip().splitlines()[-1:] or [f"exit {process.returncode}"]
        print(f"[assistant] reading {name} failed: {detail[0][:300]}", file=sys.stderr)
        raise ConversionError(f"{name} could not be read: the file may be damaged")
    try:
        answer = json.loads(out)
    except ValueError:
        raise ConversionError(f"{name} could not be read: the file may be damaged") from None
    if isinstance(answer, dict) and isinstance(answer.get("error"), str):
        raise ConversionError(answer["error"])
    if not isinstance(answer, dict) or not isinstance(answer.get("text"), str):
        raise ConversionError(f"{name} could not be read: the file may be damaged")
    return answer["text"]


def _limit_memory() -> None:
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT, MEMORY_LIMIT))
    except (ImportError, ValueError, OSError):
        pass  # not on this system: the time limit still stands


def main(argv: list[str]) -> int:
    """The child: read one document, print {"text"} or {"error"} as one line of JSON."""
    if len(argv) != 2:
        print(json.dumps({"error": "usage: python -m assistant.convert FILE NAME"}))
        return 2
    _limit_memory()
    path, name = Path(argv[0]), argv[1]
    try:
        answer = {"text": read(path, name)}
    except ConversionError as error:
        answer = {"error": str(error)}
    except MemoryError:
        answer = {"error": f"{name} is too large to read"}
    sys.stdout.write(json.dumps(answer, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
