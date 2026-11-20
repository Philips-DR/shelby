"""Tests for attaching a document: a PDF, a Word file or plain text turned into text kept as markdown is.

Real files, read by the real libraries in a real child process: a PDF written out here object by object, a Word
file made with python-docx. What can go wrong in the child (a crash, a hang) is a child that crashes or hangs.
No network, no model.
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

from assistant import convert
from assistant.convert import ConversionError
from tests.test_server import AUTH, run
from tests.test_uploads import client_for, index_at, slots


def make_pdf(*pages: str) -> bytes:
    """A PDF with a page for each string, each line of it a line of Helvetica text. Built by hand so the test needs
    nothing that writes PDFs."""
    count = len(pages)
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{' '.join(f'{4 + 2 * i} 0 R' for i in range(count))}] /Count {count} >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for i, text in enumerate(pages):
        lines = [line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for line in text.split("\n")]
        stream = "BT /F1 12 Tf 72 720 Td 14 TL " + " ".join(f"({line}) Tj T*" for line in lines if line) + " ET"
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                       f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>")
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1")
    start = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()
    return out


def make_docx(path: Path) -> Path:
    import docx

    document = docx.Document()
    document.add_paragraph("Ama Mensah", style="Title")
    document.add_heading("Experience", level=1)
    document.add_paragraph("Built a speech model for Twi.")
    document.add_paragraph("")
    document.add_paragraph("Python", style="List Bullet")
    document.add_paragraph("PyTorch", style="List Bullet")
    document.add_heading("Education", level=2)
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "Degree", "Year"
    table.cell(1, 0).text, table.cell(1, 1).text = "BSc Computer Science", "2021"
    merged = document.add_table(rows=1, cols=3)
    merged.cell(0, 0).merge(merged.cell(0, 1)).text = "Wide"
    merged.cell(0, 2).text = "Narrow"
    document.save(str(path))
    return path


def text_of(path, name, **kwargs):
    return run(convert.text_of(path, name, **kwargs))


# ---------------------------------------------------------------------------
# What is read
# ---------------------------------------------------------------------------

def test_a_pdf_is_read_page_by_page_in_a_child(tmp_path):
    pdf = tmp_path / "posting.pdf"
    pdf.write_bytes(make_pdf("Machine Learning Engineer\nAccra, Ghana", "Requirements\nPython (3 years)"))
    assert text_of(pdf, "posting.pdf") == "Machine Learning Engineer\nAccra, Ghana\n\nRequirements\nPython (3 years)\n"


def test_a_hyphen_at_a_line_end_is_kept_not_dropped(tmp_path):
    # PDFium joins the two lines and marks the hyphen; "RoleBased" would be a word nobody wrote.
    pdf = tmp_path / "cv.pdf"
    pdf.write_bytes(make_pdf("Robust Role-\nBased access, high-\nthroughput"))
    assert text_of(pdf, "cv.pdf") == "Robust Role-Based access, high-throughput\n"


def test_a_pdf_with_no_text_layer_is_refused_and_says_why(tmp_path):
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(make_pdf("", ""))
    with pytest.raises(ConversionError, match="no text in it to read: it may be scanned"):
        text_of(pdf, "scan.pdf")


@pytest.mark.parametrize("data", [b"hello, not a PDF", b"%PDF-1.4\n1 0 obj\n<<", make_pdf("x")[:60]])
def test_something_that_is_not_a_readable_pdf_is_refused(tmp_path, data):
    pdf = tmp_path / "bad.pdf"
    pdf.write_bytes(data)
    with pytest.raises(ConversionError, match="bad.pdf"):
        text_of(pdf, "bad.pdf")


def test_a_word_file_keeps_its_headings_lists_and_tables_in_order(tmp_path):
    path = make_docx(tmp_path / "cv.docx")
    assert text_of(path, "cv.docx") == (
        "# Ama Mensah\n\n"
        "# Experience\n\n"
        "Built a speech model for Twi.\n\n"
        "- Python\n- PyTorch\n\n"
        "## Education\n\n"
        "Degree | Year\nBSc Computer Science | 2021\n\n"
        "Wide | Narrow\n"
    )


@pytest.mark.parametrize("data", [b"not a zip at all", b"PK\x03\x04broken"])
def test_something_that_is_not_a_readable_word_file_is_refused(tmp_path, data):
    path = tmp_path / "cv.docx"
    path.write_bytes(data)
    with pytest.raises(ConversionError, match="cv.docx"):
        text_of(path, "cv.docx")


def test_a_zip_that_is_not_a_word_file_is_refused(tmp_path):
    import zipfile

    path = tmp_path / "cv.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("hello.txt", "hi")
    with pytest.raises(ConversionError, match="not a Word"):
        text_of(path, "cv.docx")


@pytest.mark.parametrize("data, text", [
    ("Café notes\r\nline two\r\n".encode("utf-8"), "Café notes\nline two\n"),
    (b"\xef\xbb\xbfWith a mark\n", "With a mark\n"),
    ("Two bytes a letter".encode("utf-16"), "Two bytes a letter\n"),
])
def test_plain_text_is_read_whatever_way_windows_saved_it(tmp_path, data, text):
    path = tmp_path / "notes.txt"
    path.write_bytes(data)
    assert text_of(path, "notes.txt") == text


def test_text_that_is_not_utf8_is_refused_never_guessed(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_bytes("Café".encode("latin-1"))
    with pytest.raises(ConversionError, match="not UTF-8"):
        text_of(path, "notes.txt")


def test_text_is_tidied_and_holds_nothing_the_database_refuses():
    assert convert.tidy("a\x00b\x02c  \r\n\r\n\r\n\r\nd￾\t1\n") == "abc\n\nd\t1\n"


# ---------------------------------------------------------------------------
# The child: whatever happens in it is one refusal, and it is given no secrets
# ---------------------------------------------------------------------------

def child_running(monkeypatch, code):
    monkeypatch.setattr(convert, "command", lambda path, name: [sys.executable, "-c", code])


def test_a_child_that_hangs_is_stopped_and_the_upload_refused(tmp_path, monkeypatch):
    child_running(monkeypatch, "import time; time.sleep(60)")
    started = time.monotonic()
    with pytest.raises(ConversionError, match="took too long"):
        text_of(tmp_path / "x.pdf", "x.pdf", timeout=0.5)
    assert time.monotonic() - started < 10


@pytest.mark.parametrize("code", ["import os; os.abort()", "import sys; sys.exit(3)", "print('not json')",
                                  "print('[1, 2]')", "print('')"])
def test_a_child_that_crashes_or_answers_nonsense_is_a_refusal(tmp_path, monkeypatch, code):
    child_running(monkeypatch, code)
    with pytest.raises(ConversionError, match="could not be read"):
        text_of(tmp_path / "x.pdf", "x.pdf")


def test_the_child_is_given_no_token_database_or_model_key(tmp_path, monkeypatch):
    for key in ("ASSISTANT_TOKEN", "DATABASE_URL", "ANTHROPIC_API_KEY", "AWS_PROFILE", "GOOGLE_CLIENT_SECRET"):
        monkeypatch.setenv(key, "secret")
    child_running(monkeypatch, "import json, os; print(json.dumps({'text': ' '.join(sorted(os.environ))}))")
    seen = text_of(tmp_path / "x.pdf", "x.pdf").split()
    assert not {"ASSISTANT_TOKEN", "DATABASE_URL", "ANTHROPIC_API_KEY", "AWS_PROFILE", "GOOGLE_CLIENT_SECRET"} & set(seen)


def test_the_child_command_runs_this_module(tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(make_pdf("Hello"))
    command = convert.command(pdf, "a.pdf")
    assert command[:3] == [sys.executable, "-m", "assistant.convert"]


# ---------------------------------------------------------------------------
# Through the API
# ---------------------------------------------------------------------------

def put_document(client, name, data):
    return client.put(f"/api/uploads/document?name={name}", headers=AUTH, content=data)


def test_an_attached_pdf_is_kept_as_text_and_the_model_is_told(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()

    async def body(client):
        saved = (await put_document(client, "Job posting.pdf", make_pdf("AI/ML Engineer", "Python"))).json()
        state = (await client.get("/api/state", headers=AUTH)).json()
        listed = (await client.get("/api/uploads", headers=AUTH)).json()
        return saved, state, listed

    saved, state, listed = client_for(tmp_path, body)
    assert (saved["name"], saved["files"], saved["source"]) == ("Job posting", ["Job posting.md"], "Job posting.pdf")
    index = index_at(tmp_path / "files")
    assert run(index.texts(saved["id"])) == {"Job posting.md": "AI/ML Engineer\n\nPython\n"}
    record = run(index.get(saved["id"]))
    assert (record.kind, record.name, record.made_by) == ("docs", "Job posting", "user")
    assert [d["id"] for d in listed["docs"]] == [saved["id"]] and listed["docs"][0]["draft"] is False
    assert any("Job posting.pdf" in n and saved["path"] in n and "not kept" in n for n in state["notes"])
    # Nothing of the PDF is left anywhere: not in the store, not in the folder it was read from.
    assert slots(tmp_path / "files") == [] and list((tmp_path / "tmp").iterdir()) == []


def test_an_attached_word_file_and_text_file_are_kept_the_same_way(tmp_path):
    word = make_docx(tmp_path / "cv.docx").read_bytes()

    async def body(client):
        return [(await put_document(client, name, data)).json()
                for name, data in [("CV.docx", word), ("notes.txt", b"Plain notes\n")]]

    cv, notes = client_for(tmp_path, body)
    index = index_at(tmp_path / "files")
    assert run(index.texts(cv["id"]))["CV.md"].startswith("# Ama Mensah\n\n# Experience\n")
    assert run(index.texts(notes["id"])) == {"notes.md": "Plain notes\n"}


@pytest.mark.parametrize("name, data, said", [
    ("old.doc", b"\xd0\xcf\x11\xe0", "save it as .docx"),
    ("tool.exe", b"MZ", "not a document this can read"),
    ("../cv.pdf", make_pdf("x"), None),
    (".hidden.pdf", make_pdf("x"), "not an acceptable"),
    ("scan.pdf", make_pdf(""), "may be scanned"),
    ("broken.pdf", b"garbage", "broken.pdf"),
    ("empty.txt", b"", "empty"),
])
def test_a_document_that_cannot_be_read_is_refused_and_leaves_nothing(tmp_path, monkeypatch, name, data, said):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()

    async def body(client):
        response = await put_document(client, name, data)
        listed = (await client.get("/api/uploads", headers=AUTH)).json()
        return response, listed

    response, listed = client_for(tmp_path, body)
    if said is None:  # a path as a name is its last part only, never somewhere else
        assert response.status_code == 200 and response.json()["name"] == "cv"
        return
    assert response.status_code == 400 and said in response.json()["error"]
    assert listed["docs"] == [] and list((tmp_path / "tmp").iterdir()) == []


def test_a_document_over_the_limit_is_refused_before_it_is_read(tmp_path, monkeypatch):
    monkeypatch.setattr(convert, "MAX_DOCUMENT_BYTES", 100)

    async def body(client):
        return await put_document(client, "big.pdf", make_pdf("x" * 200))

    response = client_for(tmp_path, body)
    assert response.status_code == 400 and "limit" in response.json()["error"]


def test_the_module_runs_as_a_child_from_the_command_line(tmp_path):
    """What the backend runs, run as it runs it: one line of JSON out."""
    import subprocess

    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(make_pdf("Hello there"))
    result = subprocess.run(convert.command(pdf, "a.pdf"), cwd=Path(convert.__file__).resolve().parents[1],
                            env=convert.child_env(), capture_output=True, timeout=60, check=True)
    assert json.loads(result.stdout) == {"text": "Hello there\n"}
    assert os.environ.get("ASSISTANT_TOKEN") is None or b"ASSISTANT_TOKEN" not in result.stdout
