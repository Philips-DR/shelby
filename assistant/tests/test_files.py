"""Tests for the file store's records and for the one-time move of the old uploads folder into it.

The index tests run against index.json here, and against a real PostgreSQL when TEST_DATABASE_URL names a
throwaway server (see test_database.py)."""

import asyncio
import hashlib
import os
import time

import pytest

from assistant import files
from assistant import uploads as up
from assistant.db import Database
from assistant.files import JsonFileIndex, PgFileIndex, StoredFile
from tests.test_database import needs_postgres, scratch_database
from tests.test_server import AUTH, app_for, run, with_client


def record(file_id, kind="book", name="a.pdf", created=1.0, made_by="user"):
    return StoredFile(file_id, kind, name, 3, "x", made_by, created)


CV_TEXTS = {"b.md": "# Experience — 4 years\n", "a.md": "# Ama\n"}


async def behaves_like_an_index(index):
    """The same rules whichever store keeps the records."""
    first, second, third, fourth = "1" * 32, "2" * 32, "3" * 32, "5" * 32
    await index.add(record(first, created=100.0))
    await index.add(record(second, kind="audio", name="m.m4a", created=300.0))
    await index.add(record(third, kind="docs", name="cv", created=200.0, made_by="assistant"), CV_TEXTS)
    await index.add(record(fourth, kind="docs", name="letter", created=50.0), {"letter.md": "Dear\n"})
    newest_first = [r.id for r in await index.all()]
    books = [r.id for r in await index.all("book")]
    got = await index.get(third)
    missing = await index.get("4" * 32)
    texts = await index.texts(third), await index.texts(first)
    names = await index.text_names()
    await index.remove(second)
    await index.remove(third)
    after = [r.id for r in await index.all()], await index.texts(third), await index.text_names()
    return newest_first, books, got, missing, texts, names, after


def check_index(newest_first, books, got, missing, texts, names, after):
    assert newest_first == ["2" * 32, "3" * 32, "1" * 32, "5" * 32]
    assert books == ["1" * 32]
    assert got == record("3" * 32, kind="docs", name="cv", created=200.0, made_by="assistant")
    assert missing is None
    assert texts == (CV_TEXTS, {})
    assert names == {"3" * 32: ["a.md", "b.md"], "5" * 32: ["letter.md"]}
    # A document's texts go with its record.
    assert after == (["1" * 32, "5" * 32], {}, {"5" * 32: ["letter.md"]})


def test_the_index_file_keeps_records_newest_first_and_forgets_on_remove(tmp_path):
    check_index(*run(behaves_like_an_index(JsonFileIndex(tmp_path / "index.json"))))


@needs_postgres
def test_the_files_table_keeps_records_as_the_index_file_does():
    async def body():
        async with scratch_database() as url:
            async with Database(url) as database:
                return await behaves_like_an_index(PgFileIndex(database))
    check_index(*run(body()))


@needs_postgres
def test_a_document_whose_text_cannot_be_kept_leaves_no_record_either():
    """The record and its texts are one transaction: a record with no text would be listed and lend nothing."""
    async def body():
        async with scratch_database() as url:
            async with Database(url) as database:
                index = PgFileIndex(database)
                refused = None
                try:
                    await index.add(record("7" * 32, kind="docs", name="cv"), {"cv.md": "# CV\x00"})
                except Exception as error:  # PostgreSQL's text holds no NUL; uploads refuse one before this
                    refused = type(error).__name__
                return refused, await index.get("7" * 32), await index.text_names()
    refused, got, names = run(body())
    assert refused and got is None and names == {}


@needs_postgres
def test_the_files_table_refuses_what_the_store_never_makes():
    import asyncpg

    async def body():
        refused = []
        async with scratch_database() as url:
            async with Database(url) as database:
                index = PgFileIndex(database)
                # "tool" and "made" are allowed since 004_records.sql; anything else still is not.
                for bad in (record("not-an-id"), record("5" * 32, kind="video"), record("6" * 32, made_by="someone")):
                    try:
                        await index.add(bad)
                    except asyncpg.CheckViolationError:
                        refused.append(bad.id)
        return refused
    assert run(body()) == ["not-an-id", "5" * 32, "6" * 32]


def test_a_slot_is_new_every_time_and_only_an_empty_one_is_discarded(tmp_path):
    first, a = files.new_slot(tmp_path)
    second, b = files.new_slot(tmp_path)
    assert first != second and files.is_id(first) and a.parent == tmp_path
    (b / "kept.txt").write_text("x")
    files.discard_slot(tmp_path, first)
    files.discard_slot(tmp_path, second)
    files.discard_slot(tmp_path, "..")  # never anything but an id
    assert not a.exists() and (b / "kept.txt").exists()


# ---------------------------------------------------------------------------
# The old uploads folder, copied in once
# ---------------------------------------------------------------------------

def old_uploads(tmp_path):
    old = tmp_path / "uploads"
    for folder, name, data in (("audio", "meeting.webm", b"audio"), ("books", "Novel.pdf", b"%PDF"),
                               ("voices", "me.wav", b"RIFF")):
        (old / folder).mkdir(parents=True)
        (old / folder / name).write_bytes(data)
    (old / "books" / "Novel.corrections.txt").write_text("teh -> the\n")
    (old / "audio" / "notes.txt").write_text("not audio")  # not an upload: not copied, but not lost either
    (old / "audio" / "half.webm.part").write_bytes(b"a")
    (old / "docs" / "CV - Role").mkdir(parents=True)
    (old / "docs" / "CV - Role" / "CV - Role.md").write_text("# CV — Ama\n", encoding="utf-8")
    (old / "docs" / "CV - Role" / ".draft").write_text("written by the assistant\n")
    (old / "docs" / "Letter").mkdir()
    (old / "docs" / "Letter" / "Letter.md").write_text("# Dear\n")
    (old / "exports").mkdir()
    (old / "exports" / "CV.pdf").write_bytes(b"%PDF")  # docu-ai's and mail-ai's: left where it is
    then = time.time() - 86400
    os.utime(old / "books" / "Novel.pdf", (then, then))
    return old


def test_the_old_uploads_are_copied_in_intact_with_their_dates_and_the_old_folders_renamed(tmp_path):
    old = old_uploads(tmp_path)
    root = tmp_path / "files"
    index = JsonFileIndex(root / "index.json")
    when = (old / "books" / "Novel.pdf").stat().st_mtime
    counts = run(up.import_old_uploads(index, root, old))
    listed = run(up.listing(index, root, tmp_path / "texts"))

    assert counts == {"audio": 1, "books": 1, "voices": 1, "docs": 2}
    book = listed["books"][0]
    assert book["name"] == "Novel.pdf" and open(book["path"], "rb").read() == b"%PDF" and book["at"] == when
    # audiobook looks for a book's corrections beside its PDF, so they travel together.
    assert (root / book["id"] / "Novel.corrections.txt").read_text() == "teh -> the\n"
    assert [a["name"] for a in listed["audio"]] == ["meeting.webm"]
    assert [v["name"] for v in listed["voices"]] == ["me.wav"]
    assert {d["name"]: d["draft"] for d in listed["docs"]} == {"CV - Role": True, "Letter": False}
    # Markdown goes into the database, byte for byte, and into no folder of the store.
    cv = next(d for d in listed["docs"] if d["name"] == "CV - Role")
    assert run(index.texts(cv["id"])) == {"CV - Role.md": "# CV — Ama\n"}
    assert not (root / cv["id"]).exists() and cv["path"] == str(tmp_path / "texts" / cv["id"] / "CV - Role" / "CV - Role.md")
    record = run(index.get(book["id"]))
    assert record.sha256 == hashlib.sha256(b"%PDF").hexdigest() and record.made_by == "user"
    # Nothing deleted: the old folders are renamed, with what was not copied still in them.
    assert sorted(p.name for p in old.iterdir()) == [
        "audio.imported", "books.imported", "docs.imported", "exports", "voices.imported"]
    assert (old / "audio.imported" / "notes.txt").exists() and (old / "exports" / "CV.pdf").exists()


def test_copying_in_again_copies_nothing_twice(tmp_path):
    old = old_uploads(tmp_path)
    root = tmp_path / "files"
    index = JsonFileIndex(root / "index.json")
    run(up.import_old_uploads(index, root, old))
    # A folder that could not be renamed last time, say: the same files must not come in twice.
    (old / "books.imported").rename(old / "books")
    assert run(up.import_old_uploads(index, root, old)) == {"books": 0}
    assert len(run(index.all("book"))) == 1


def test_markdown_that_is_not_text_is_left_behind_and_said_so(tmp_path):
    old = tmp_path / "uploads"
    (old / "docs" / "Scan").mkdir(parents=True)
    (old / "docs" / "Scan" / "Scan.md").write_bytes(b"\xff\xd8\xff not text")
    (old / "docs" / "Notes").mkdir()
    (old / "docs" / "Notes" / "Notes.md").write_text("# Notes\n")
    root = tmp_path / "files"
    index = JsonFileIndex(root / "index.json")
    assert run(up.import_old_uploads(index, root, old)) == {"docs": 1, "docs_unreadable": 1}
    assert [r.name for r in run(index.all())] == ["Notes"]
    assert (old / "docs.imported" / "Scan" / "Scan.md").read_bytes() == b"\xff\xd8\xff not text"


def test_a_link_in_the_old_folder_is_not_followed(tmp_path):
    old = tmp_path / "uploads"
    (old / "books").mkdir(parents=True)
    (tmp_path / "secret.pdf").write_bytes(b"%PDF secret")
    (old / "books" / "link.pdf").symlink_to(tmp_path / "secret.pdf")
    root = tmp_path / "files"
    assert run(up.import_old_uploads(JsonFileIndex(root / "index.json"), root, old)) == {"books": 0}
    assert not root.exists() or not any(files.is_id(p.name) for p in root.iterdir())  # no slot was made for it


def test_the_server_copies_the_old_folder_in_on_start_only_when_told_to(tmp_path):
    old = old_uploads(tmp_path)

    async def body(client):
        return (await client.get("/api/uploads", headers=AUTH)).json()

    untold = run(with_client(app_for(tmp_path), body))
    assert untold["books"] == [] and (old / "books").is_dir()
    app = app_for(tmp_path, legacy_uploads=old)
    told = run(with_client(app, body))
    assert [b["name"] for b in told["books"]] == ["Novel.pdf"]
    assert app.state.files_imported == {"audio": 1, "books": 1, "voices": 1, "docs": 2}
