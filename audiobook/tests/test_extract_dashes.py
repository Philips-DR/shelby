"""Putting the dashes back in a Docling document, page by page, and keeping what was read from the PDF.

The PDF reader itself is not run here: its answer (the PDF's text, a string a page) is made up, and what is checked is
what this code decides: which pages an item is repaired from, and when the PDF is read again."""

import json

import pytest
from docling_core.types.doc import BoundingBox, DocItemLabel, DoclingDocument, ProvenanceItem, Size

from audiobook import extract
from audiobook.dashes import read

PAGE_1 = "an unspeakable inspiration—\r\nespecially at times and overcome—particularly"
PAGE_2 = "then came the evangelist—\r\nto the angels"


def prov(page: int) -> ProvenanceItem:
    return ProvenanceItem(page_no=page, bbox=BoundingBox(l=0, t=0, r=1, b=1), charspan=(0, 1))


def book(*pages: list[str]) -> DoclingDocument:
    doc = DoclingDocument(name="book")
    for number, texts in enumerate(pages, 1):
        doc.add_page(page_no=number, size=Size(width=100, height=100))
        for text in texts:
            doc.add_text(label=DocItemLabel.TEXT, text=text, prov=prov(number))
    return doc


def texts(doc: DoclingDocument) -> list[str]:
    return [t.text for t in doc.texts]


def test_each_item_is_repaired_from_the_pages_it_sits_on_and_no_others():
    doc = book(["an unspeakable inspirationespecially at times and overcome-particularly"],
               ["the evangelisttoo and inspirationespecially again", "then came the evangelistto the angels"])
    by_page = {1: read(PAGE_1), 2: read(PAGE_2)}
    extract.restore_dashes(doc, by_page)
    assert texts(doc) == [
        "an unspeakable inspiration—especially at times and overcome—particularly",
        "the evangelisttoo and inspirationespecially again",          # page 2 has no such pair: left as it came
        "then came the evangelist—to the angels",
    ]


def test_an_item_over_a_page_break_gets_the_dashes_of_both_pages():
    doc = book(["one"], ["two"])
    doc.add_text(label=DocItemLabel.TEXT, text="inspirationespecially and evangelistto", prov=prov(1))
    doc.texts[-1].prov.append(prov(2))
    extract.restore_dashes(doc, {1: read(PAGE_1), 2: read(PAGE_2)})
    assert doc.texts[-1].text == "inspiration—especially and evangelist—to"


def test_nothing_to_repair_changes_nothing():
    doc = book(["plain text here"])
    assert extract.restore_dashes(doc, {}) is doc and texts(doc) == ["plain text here"]
    extract.restore_dashes(doc, {5: read(PAGE_1)})                  # a page the document does not have
    assert texts(doc) == ["plain text here"]


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(extract, "CACHE_DIR", tmp_path / "cache")
    reads = []

    def pages(pdf):
        reads.append(pdf)
        return [PAGE_1, "no dashes on this page", PAGE_2]

    monkeypatch.setattr(extract, "_page_texts", pages)
    return reads


def test_the_pdf_is_read_once_and_the_answer_kept(cache):
    first = extract._dashes_by_page("book.pdf", "abc")
    second = extract._dashes_by_page("book.pdf", "abc")
    assert len(cache) == 1
    assert sorted(first) == sorted(second) == [1, 3]                # the page with no dash is not kept
    assert second[1].inline == {("overcome", "particularly")}
    assert (extract.CACHE_DIR / "abc.dashes.json").exists()


def test_a_cache_from_another_version_or_a_broken_one_is_read_again(cache):
    extract._dashes_by_page("book.pdf", "abc")
    path = extract.CACHE_DIR / "abc.dashes.json"
    path.write_text(json.dumps({"v": 0, "pages": {}}))
    extract._dashes_by_page("book.pdf", "abc")
    path.write_text("{ not json")
    assert sorted(extract._dashes_by_page("book.pdf", "abc")) == [1, 3]
    assert len(cache) == 3


def test_a_pdf_that_cannot_be_read_goes_through_as_it_came(monkeypatch, tmp_path):
    monkeypatch.setattr(extract, "CACHE_DIR", tmp_path)

    def broken(pdf):
        raise RuntimeError("pdfium could not open it")

    monkeypatch.setattr(extract, "_page_texts", broken)
    assert extract._dashes_by_page("book.pdf", "abc") == {}
