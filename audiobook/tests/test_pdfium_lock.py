"""PDFium is not thread-safe, and the tool server runs every call on a thread of its own.

Opening a PDF from several threads at once made PDFium fail ("Data format error") and, on 2026-11-13, once crashed the
whole audiobook tool server with a segmentation fault while a render was running. Everything that uses PDFium is
behind one lock now; these hit it from many threads at once, on a small real PDF made here."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from audiobook import extract

BODY = b"BT /F1 12 Tf 20 100 Td (Hello world) Tj ET"
PDF = (b"%PDF-1.4\n1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
       b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj\n"
       b"4 0 obj << /Length " + str(len(BODY)).encode() + b" >> stream\n" + BODY + b"\nendstream endobj\n"
       b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n"
       b"6 0 obj << /Title (A Test Book) /Author (Someone Real) >> endobj\n"
       b"trailer << /Root 1 0 R /Info 6 0 R /Size 7 >>\n%%EOF\n")


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "small.pdf"
    path.write_bytes(PDF)
    return path


def test_the_small_pdf_is_read_as_a_book_would_be(pdf):
    assert extract.pdf_metadata(pdf) == ("A Test Book", "Someone Real")
    assert [t.strip() for t in extract._page_texts(pdf)] == ["Hello world"]


def test_many_threads_reading_pdfs_at_once_all_get_their_answer(pdf):
    def both(_):
        return extract.pdf_metadata(pdf), [t.strip() for t in extract._page_texts(pdf)]

    with ThreadPoolExecutor(12) as pool:
        answers = list(pool.map(both, range(240)))
    assert all(a == (("A Test Book", "Someone Real"), ["Hello world"]) for a in answers)
