"""Tests for uploads. Security first: this endpoint writes to disk whatever a browser sends,
so every name is hostile until checked. Each upload lands in the file store (files.py) in a
folder of its own, under its own name, and is deleted by the id the listing gave it. Markdown
goes into the database instead, and nothing of it is written to disk."""

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from assistant import files
from assistant import uploads as up
from assistant.files import JsonFileIndex, StoredFile
from assistant.server import create_app
from assistant.tools import ToolRegistry
from tests.test_server import AUTH, TOKEN, app_for, run, with_client


def client_for(tmp_path, body):
    return run(with_client(app_for(tmp_path, files_path=tmp_path / "files"), body))


def index_at(root):
    return JsonFileIndex(root / "index.json")


def slots(root):
    return sorted(p.name for p in root.iterdir() if files.is_id(p.name)) if root.is_dir() else []


def store(root, kind, name, data=b"x" * 10):
    """A file as an upload would have left it: in a slot of its own, with its record."""
    file_id, slot = files.new_slot(root)
    path = slot / name
    path.write_bytes(data)
    run(index_at(root).add(StoredFile(file_id, kind, name, len(data), hashlib.sha256(data).hexdigest(), "user", 1.0)))
    return file_id, path


def store_docs(root, name, *names, draft=False):
    """Markdown as an upload or a draft leaves it: a record and its texts, nothing on disk."""
    texts = {n: "# T\n" for n in names}
    sha, size = files.texts_digest(texts)
    file_id = files.new_id()
    run(index_at(root).add(StoredFile(file_id, "docs", name, size, sha, "assistant" if draft else "user", 1.0), texts))
    return file_id


async def chunks_of(*parts):
    for part in parts:
        yield part


def receive(batches, batch, name, *parts):
    return run(batches.receive(batch, name, chunks_of(*parts)))


async def upload_docs(client, name, files_and_bodies):
    batch = (await client.post("/api/uploads/docs", headers=AUTH, json={"name": name})).json()["batch"]
    sent = [(await client.put(f"/api/uploads/docs/{batch}?name={f}", headers=AUTH, content=body)).json()
            for f, body in files_and_bodies]
    return sent, (await client.post(f"/api/uploads/docs/{batch}/done", headers=AUTH)).json()


# ---------------------------------------------------------------------------
# Hostile names
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["../escape.m4a", "..", ".hidden.m4a", "a/b.m4a", "a\\b.m4a", "x\x00.m4a", ""])
def test_a_hostile_audio_name_is_refused_or_reduced_to_a_plain_file_name(tmp_path, name):
    root = tmp_path / "files"
    try:
        file_id, target = up.audio_target(root, name)
    except up.UploadError:
        assert slots(root) == []  # refused before a folder was made for it
        return
    # Path(name).name keeps only the last component; whatever survives lands in a new folder of its own.
    assert target.parent == (root / file_id).resolve() and files.is_id(file_id)


@pytest.mark.parametrize("name", ["../x.md", "sub/x.md", "..", ".x.md", "x\x00.md", "notes.txt"])
def test_a_markdown_file_must_be_a_plain_md_name_at_the_top_of_its_batch(name):
    batches = up.DocBatches()
    batch = batches.start("book")
    with pytest.raises(up.UploadError):
        receive(batches, batch, name, b"# T\n")


@pytest.mark.parametrize("batch", ["..", "../x", "", "a" * 32, "0" * 31, "0" * 32])
def test_a_batch_must_be_one_this_server_started(batch):
    batches = up.DocBatches()
    batches.start("real")
    with pytest.raises(up.UploadError, match="no upload batch"):
        receive(batches, batch, "x.md", b"# T\n")


@pytest.mark.parametrize("body,error", [(b"", "is empty"), (b"\xff\xfe# CV", "not UTF-8 text"),
                                        (b"# CV\x00", "not a text file")])
def test_markdown_must_be_text_the_database_can_keep(body, error):
    batches = up.DocBatches()
    with pytest.raises(up.UploadError, match=error):
        receive(batches, batches.start("cv"), "cv.md", body)


def test_a_batch_over_the_limit_is_refused_as_a_whole(monkeypatch):
    monkeypatch.setattr(up, "MAX_DOC_BYTES", 10)
    batches = up.DocBatches()
    batch = batches.start("book")
    assert receive(batches, batch, "a.md", b"# " + b"a" * 6) == ("a.md", 8)
    with pytest.raises(up.UploadError, match="over the 0 MB limit"):
        receive(batches, batch, "b.md", b"# b")  # 3 bytes, but 8 + 3: the batch is over, not the file


def test_the_same_name_twice_in_one_batch_is_refused():
    batches = up.DocBatches()
    batch = batches.start("book")
    receive(batches, batch, "a.md", b"# one\n")
    with pytest.raises(up.UploadError, match="already in this upload"):
        receive(batches, batch, "a.md", b"# two\n")


def test_only_a_few_batches_are_held_open_and_the_oldest_goes_first():
    batches = up.DocBatches()
    started = [batches.start(f"b{i}") for i in range(up.MAX_OPEN_BATCHES + 1)]
    with pytest.raises(up.UploadError, match="no upload batch"):
        receive(batches, started[0], "a.md", b"# a\n")
    assert receive(batches, started[-1], "a.md", b"# a\n") == ("a.md", 4)


def test_a_batch_left_for_an_hour_is_dropped(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(up.time, "monotonic", lambda: clock[0])
    batches = up.DocBatches()
    old = batches.start("old")
    clock[0] += up.BATCH_TIMEOUT + 1
    batches.start("new")
    with pytest.raises(up.UploadError, match="no upload batch"):
        receive(batches, old, "a.md", b"# a\n")


def test_the_upload_endpoints_need_the_token(tmp_path):
    async def body(client):
        return (await client.put("/api/uploads/audio?name=a.m4a", content=b"x")).status_code
    assert client_for(tmp_path, body) == 401


def test_only_audio_is_accepted_for_transcription(tmp_path):
    async def body(client):
        return (await client.put("/api/uploads/audio?name=notes.pdf", headers=AUTH, content=b"x")).json()
    assert "not an audio file" in client_for(tmp_path, body)["error"]
    assert slots(tmp_path / "files") == []


# ---------------------------------------------------------------------------
# Receiving
# ---------------------------------------------------------------------------

def test_an_audio_upload_lands_as_a_path_the_model_is_told_about(tmp_path):
    async def body(client):
        saved = (await client.put("/api/uploads/audio?name=meeting.m4a", headers=AUTH, content=b"audio")).json()
        again = (await client.put("/api/uploads/audio?name=meeting.m4a", headers=AUTH, content=b"more")).json()
        state = (await client.get("/api/state", headers=AUTH)).json()
        listed = (await client.get("/api/uploads", headers=AUTH)).json()
        return saved, again, state, listed

    saved, again, state, listed = client_for(tmp_path, body)
    assert saved["name"] == "meeting.m4a" and saved["bytes"] == 5
    # The same name again keeps its name, in a folder of its own: never an overwrite, never "meeting (2)".
    assert again["name"] == "meeting.m4a" and again["path"] != saved["path"]
    assert Path(saved["path"]).read_bytes() == b"audio" and Path(again["path"]).read_bytes() == b"more"
    assert Path(saved["path"]).parent.name == saved["id"]
    assert any("meeting.m4a" in n and saved["path"] in n for n in state["notes"])
    assert [(a["id"], a["name"]) for a in listed["audio"]] == [(again["id"], "meeting.m4a"), (saved["id"], "meeting.m4a")]
    record = run(index_at(tmp_path / "files").get(saved["id"]))
    assert (record.kind, record.made_by, record.sha256) == ("audio", "user", hashlib.sha256(b"audio").hexdigest())


def test_a_half_received_upload_is_never_left_behind(tmp_path):
    root = tmp_path / "files"
    _file_id, target = up.audio_target(root, "long.m4a")

    async def chunks():
        yield b"a" * 10
        raise ConnectionError("browser closed the tab")

    with pytest.raises(ConnectionError):
        asyncio.run(up.receive(target, chunks(), limit=1000))
    assert list(target.parent.iterdir()) == []


def test_an_upload_over_the_limit_is_stopped_and_removed(tmp_path):
    _file_id, target = up.audio_target(tmp_path / "files", "huge.m4a")

    async def chunks():
        for _ in range(5):
            yield b"a" * 100

    with pytest.raises(up.UploadError, match="larger than"):
        asyncio.run(up.receive(target, chunks(), limit=250))
    assert list(target.parent.iterdir()) == []


def test_a_refused_upload_leaves_no_folder_and_no_record(tmp_path, monkeypatch):
    monkeypatch.setattr(up, "MAX_AUDIO_BYTES", 3)

    async def body(client):
        refused = (await client.put("/api/uploads/audio?name=big.m4a", headers=AUTH, content=b"too long")).json()
        empty = (await client.put("/api/uploads/audio?name=empty.m4a", headers=AUTH, content=b"")).json()
        return refused, empty, (await client.get("/api/uploads", headers=AUTH)).json()

    refused, empty, listed = client_for(tmp_path, body)
    assert "larger than" in refused["error"] and "is empty" in empty["error"]
    assert listed["audio"] == [] and slots(tmp_path / "files") == []


def test_one_markdown_file_builds_as_a_file_and_several_as_a_folder(tmp_path):
    """docu-ai gives a lone file one tab and no cover, a folder a tab per file and contents."""
    async def body(client):
        return (await upload_docs(client, "cv.md", [("cv.md", b"# T\n")]))[1], \
            (await upload_docs(client, "handbook", [("01-a.md", b"# A\n"), ("02-b.md", b"# B\n")]))[1]

    single, folder = client_for(tmp_path, body)
    assert single["path"] == str(tmp_path / "texts" / single["id"] / "cv" / "cv.md")
    assert folder["path"] == str(tmp_path / "texts" / folder["id"] / "handbook")
    assert folder["files"] == ["01-a.md", "02-b.md"]


def test_markdown_goes_into_the_database_and_nothing_of_it_onto_disk(tmp_path):
    """The user's call (2026-10-31): the database holds a document's only lasting copy. The path is where a
    tool is lent a copy for one call, and is not there between calls."""
    async def body(client):
        sent, done = await upload_docs(client, "CV - Ama", [("CV - Ama.md", "# Ama Mensah — CV\n".encode())])
        state = (await client.get("/api/state", headers=AUTH)).json()
        return sent, done, state

    sent, done, state = client_for(tmp_path, body)
    assert sent == [{"name": "CV - Ama.md", "bytes": len("# Ama Mensah — CV\n".encode())}]
    index = index_at(tmp_path / "files")
    assert run(index.texts(done["id"])) == {"CV - Ama.md": "# Ama Mensah — CV\n"}
    record = run(index.get(done["id"]))
    assert (record.kind, record.name, record.made_by) == ("docs", "CV - Ama", "user")
    assert (record.sha256, record.bytes) == files.texts_digest({"CV - Ama.md": "# Ama Mensah — CV\n"})
    assert slots(tmp_path / "files") == [] and not (tmp_path / "texts").exists()
    assert not Path(done["path"]).exists()
    assert any("CV - Ama.md" in n and done["path"] in n for n in state["notes"])


def test_a_batch_broken_off_before_it_is_done_stores_nothing(tmp_path):
    async def body(client):
        batch = (await client.post("/api/uploads/docs", headers=AUTH, json={"name": "cv"})).json()["batch"]
        await client.put(f"/api/uploads/docs/{batch}?name=cv.md", headers=AUTH, content=b"# CV\n")
        return (await client.get("/api/uploads", headers=AUTH)).json()

    assert client_for(tmp_path, body)["docs"] == []
    assert run(index_at(tmp_path / "files").all()) == []


def test_a_batch_with_no_markdown_in_it_is_refused_and_stores_nothing(tmp_path):
    async def body(client):
        return (await upload_docs(client, "empty", [("notes.txt", b"plain")]))

    sent, done = client_for(tmp_path, body)
    assert "not a markdown" in sent[0]["error"] and "none of those files" in done["error"]
    assert slots(tmp_path / "files") == [] and run(index_at(tmp_path / "files").all()) == []


def test_finishing_a_batch_twice_records_it_once(tmp_path):
    async def body(client):
        batch = (await client.post("/api/uploads/docs", headers=AUTH, json={"name": "cv"})).json()["batch"]
        await client.put(f"/api/uploads/docs/{batch}?name=cv.md", headers=AUTH, content=b"# CV\n")
        first = (await client.post(f"/api/uploads/docs/{batch}/done", headers=AUTH)).json()
        second = (await client.post(f"/api/uploads/docs/{batch}/done", headers=AUTH)).json()
        return first, second, (await client.get("/api/uploads", headers=AUTH)).json()

    first, second, listed = client_for(tmp_path, body)
    assert first == second and [d["id"] for d in listed["docs"]] == [first["id"]]
    assert listed["docs"][0]["files"] == ["cv.md"] and listed["docs"][0]["draft"] is False


# ---------------------------------------------------------------------------
# Books and voices
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["../escape.pdf", "..", ".hidden.pdf", "a\\b.pdf", "x\x00.pdf", ""])
def test_a_hostile_book_name_is_refused_or_reduced_to_a_plain_file_name(tmp_path, name):
    root = tmp_path / "files"
    try:
        file_id, target = up.book_target(root, name)
    except up.UploadError:
        return
    assert target.parent == (root / file_id).resolve()


def test_only_a_pdf_is_a_book_and_only_audio_is_a_voice(tmp_path):
    root = tmp_path / "files"
    with pytest.raises(up.UploadError, match="not a PDF"):
        up.book_target(root, "novel.epub")
    with pytest.raises(up.UploadError, match="not an audio file"):
        up.voice_target(root, "notes.pdf")
    file_id, target = up.voice_target(root, "me.m4a")
    assert target.name == "me.m4a" and target.parent.name == file_id


def test_books_and_voices_upload_note_themselves_and_stay_out_of_the_meeting_list(tmp_path):
    async def body(client):
        book = (await client.put("/api/uploads/book?name=Novel.pdf", headers=AUTH, content=b"%PDF")).json()
        again = (await client.put("/api/uploads/book?name=Novel.pdf", headers=AUTH, content=b"%PDF2")).json()
        voice = (await client.put("/api/uploads/voice?name=me.m4a", headers=AUTH, content=b"audio")).json()
        bad = (await client.put("/api/uploads/book?name=Novel.epub", headers=AUTH, content=b"x")).json()
        state = (await client.get("/api/state", headers=AUTH)).json()
        listed = (await client.get("/api/uploads", headers=AUTH)).json()
        return book, again, voice, bad, state, listed

    book, again, voice, bad, state, listed = client_for(tmp_path, body)
    # A book's audio is named after its PDF, so the name is kept exactly, even the second time.
    assert book["name"] == again["name"] == "Novel.pdf" and book["path"] != again["path"]
    assert "not a PDF" in bad["error"]
    assert any("book (PDF) Novel.pdf" in n and book["path"] in n for n in state["notes"])
    assert any("clone a voice" in n and voice["path"] in n for n in state["notes"])
    assert {b["id"] for b in listed["books"]} == {book["id"], again["id"]}
    assert [v["name"] for v in listed["voices"]] == ["me.m4a"]
    assert listed["audio"] == []  # a voice sample is not a meeting to transcribe


def test_the_book_and_voice_endpoints_need_the_token(tmp_path):
    async def body(client):
        return [(await client.put(f"/api/uploads/{kind}?name=a.{ext}", content=b"x")).status_code
                for kind, ext in (("book", "pdf"), ("voice", "m4a"))]
    assert client_for(tmp_path, body) == [401, 401]


def test_the_listing_leaves_out_a_record_whose_file_is_gone(tmp_path):
    root = tmp_path / "files"
    kept, _ = store(root, "book", "kept.pdf")
    _gone, path = store(root, "book", "gone.pdf")
    path.unlink()
    listed = run(up.listing(index_at(root), root, tmp_path / "texts"))
    assert [b["id"] for b in listed["books"]] == [kept]


# ---------------------------------------------------------------------------
# Audio a tool made: served only from folders tools.yaml declared
# ---------------------------------------------------------------------------

class Serving(ToolRegistry):
    """A registry that declares media folders without launching any tool."""

    def __init__(self, roots, local):
        super().__init__([], local=local)
        self._roots = roots

    @property
    def media_roots(self):
        return self._roots


def media_client(tmp_path, body):
    app = create_app(tmp_path / "tools.yaml", tmp_path / "memory.json", tmp_path / "audit.jsonl", token=TOKEN,
                     registry_factory=lambda local: Serving([tmp_path / "output"], local), watch_jobs=False,
                     files_path=tmp_path / "files", texts_path=tmp_path / "texts")
    return run(with_client(app, body))


def test_audio_in_a_declared_folder_is_served_and_nothing_else_is(tmp_path):
    out = tmp_path / "output" / "book"
    out.mkdir(parents=True)
    (out / "01.mp3").write_bytes(b"ID3audio")
    (out / "notes.txt").write_text("not audio")
    (tmp_path / "secret.mp3").write_bytes(b"outside")
    (tmp_path / "output" / "link.mp3").symlink_to(tmp_path / "secret.mp3")

    async def get(client, path, headers=AUTH):
        return await client.get("/api/files", params={"path": str(path)}, headers=headers)

    async def body(client):
        return {
            "inside": await get(client, out / "01.mp3"),
            "wrong kind": await get(client, out / "notes.txt"),
            "outside": await get(client, tmp_path / "secret.mp3"),
            "traversal": await get(client, out / ".." / ".." / "secret.mp3"),
            "symlink out": await get(client, tmp_path / "output" / "link.mp3"),
            "missing": await get(client, out / "gone.mp3"),
            "nul byte": await get(client, str(out) + "/01.mp3\x00.txt"),
            "no token": await get(client, out / "01.mp3", headers={}),
        }

    got = media_client(tmp_path, body)
    assert got["inside"].status_code == 200 and got["inside"].content == b"ID3audio"
    assert got["inside"].headers["content-type"] == "audio/mpeg"
    assert {k: v.status_code for k, v in got.items() if k not in ("inside", "no token")} == {
        "wrong kind": 404, "outside": 404, "traversal": 404, "symlink out": 404, "missing": 404, "nul byte": 404}
    assert got["no token"].status_code == 401


def test_with_no_declared_folders_nothing_is_served(tmp_path):
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "a.mp3").write_bytes(b"x")

    async def body(client):
        return (await client.get("/api/files", params={"path": str(tmp_path / "output" / "a.mp3")}, headers=AUTH)).status_code
    assert client_for(tmp_path, body) == 404


# ---------------------------------------------------------------------------
# An upload, by its id
# ---------------------------------------------------------------------------

def test_an_upload_is_served_by_its_id_and_nothing_else_is(tmp_path):
    root = tmp_path / "files"
    book, _ = store(root, "book", "Novel.pdf", data=b"%PDF-1.7")
    docs = store_docs(root, "cv", "cv.md")
    swapped, path = store(root, "audio", "a.m4a")
    (tmp_path / "secret.m4a").write_bytes(b"outside")
    path.unlink()
    path.symlink_to(tmp_path / "secret.m4a")

    async def body(client):
        get = lambda file_id, headers=AUTH: client.get(f"/api/files/{file_id}", headers=headers)
        return {
            "book": await get(book),
            "markdown folder": await get(docs),
            "a link": await get(swapped),
            "unknown": await get("0" * 32),
            "not an id": await get("..%2F..%2Fsecret.m4a"),
            "no token": await get(book, headers={}),
        }

    got = client_for(tmp_path, body)
    assert got["book"].status_code == 200 and got["book"].content == b"%PDF-1.7"
    assert got["book"].headers["content-type"] == "application/pdf"
    assert "Novel.pdf" in got["book"].headers["content-disposition"]
    assert {k: v.status_code for k, v in got.items() if k not in ("book", "no token")} == {
        "markdown folder": 404, "a link": 404, "unknown": 404, "not an id": 404}
    assert got["no token"].status_code == 401


# ---------------------------------------------------------------------------
# Deleting. The same suspicion as uploading: what the id names must be something an upload made,
# in its own folder in the store.
# ---------------------------------------------------------------------------

def audit_rows(tmp_path):
    path = tmp_path / "audit.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def delete(root, file_id):
    return run(up.delete_upload(index_at(root), root, file_id))


@pytest.mark.parametrize("kind,name", [("audio", "meeting.m4a"), ("book", "novel.pdf"), ("voice", "me.wav")])
def test_one_upload_of_each_kind_is_deleted_and_nothing_beside_it(tmp_path, kind, name):
    root = tmp_path / "files"
    file_id, target = store(root, kind, name)
    neighbour, kept = store(root, kind, name)  # the same name, uploaded again
    gone = delete(root, file_id)
    assert not target.exists() and not (root / file_id).exists() and kept.exists()
    assert gone == {"id": file_id, "kind": kind, "name": name, "files": 1, "bytes": 10}
    assert run(index_at(root).get(file_id)) is None and run(index_at(root).get(neighbour)) is not None


def test_a_document_is_deleted_with_every_text_in_it_and_nothing_else(tmp_path):
    root = tmp_path / "files"
    file_id = store_docs(root, "cv", "a.md", "b.md", draft=True)
    other = store_docs(root, "other", "c.md")
    gone = delete(root, file_id)
    assert gone == {"id": file_id, "kind": "docs", "name": "cv", "files": 2, "bytes": 8}
    assert run(index_at(root).get(file_id)) is None and run(index_at(root).texts(file_id)) == {}
    assert run(index_at(root).texts(other)) == {"c.md": "# T\n"}


def test_deleting_a_document_touches_nothing_on_disk(tmp_path):
    """Its text is only in the database. A folder that happens to sit where its id would be -- here a link to
    someone's files elsewhere -- is not the document, and is left exactly as it was."""
    root = tmp_path / "files"
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "cv").mkdir(parents=True)
    (elsewhere / "cv" / "a.md").write_text("mine")
    file_id = store_docs(root, "cv", "a.md")
    (root / file_id).symlink_to(elsewhere, target_is_directory=True)
    delete(root, file_id)
    assert (elsewhere / "cv" / "a.md").read_text() == "mine" and (root / file_id).is_symlink()


def test_a_file_a_tool_left_beside_an_upload_stays(tmp_path):
    """audiobook keeps a book's corrections beside its PDF; deleting the upload is not deleting those."""
    root = tmp_path / "files"
    file_id, pdf = store(root, "book", "novel.pdf")
    corrections = pdf.with_suffix(".corrections.txt")
    corrections.write_text("teh -> the\n")
    delete(root, file_id)
    assert not pdf.exists() and corrections.read_text() == "teh -> the\n"


@pytest.mark.parametrize("file_id", ["", "..", "../x", "a" * 32, "A" * 32, "0" * 31, "0" * 32, "index.json"])
def test_an_id_the_store_did_not_give_deletes_nothing(tmp_path, file_id):
    root = tmp_path / "files"
    kept = [store(root, "audio", "meeting.m4a")[1], store(root, "book", "novel.pdf")[1]]
    document = store_docs(root, "cv", "a.md")
    with pytest.raises(up.UploadError):
        delete(root, file_id)
    assert all(p.exists() for p in kept) and run(index_at(root).texts(document)) == {"a.md": "# T\n"}


def test_a_record_with_a_hostile_name_deletes_nothing(tmp_path):
    root = tmp_path / "files"
    victim = tmp_path / "victim.m4a"
    victim.write_bytes(b"precious")
    file_id, _ = files.new_slot(root)
    run(index_at(root).add(StoredFile(file_id, "audio", "../../victim.m4a", 8, "x", "user", 1.0)))
    with pytest.raises(up.UploadError):
        delete(root, file_id)
    assert victim.read_bytes() == b"precious"


def test_only_what_the_listing_would_show_can_be_deleted(tmp_path):
    root = tmp_path / "files"
    note_id, note = store(root, "audio", "notes.txt")
    with pytest.raises(up.UploadError):
        delete(root, note_id)
    assert note.exists()


def test_a_link_is_never_followed(tmp_path):
    root = tmp_path / "files"
    outside = tmp_path / "outside.m4a"
    outside.write_bytes(b"precious")
    file_id, path = store(root, "audio", "link.m4a")
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(up.UploadError):
        delete(root, file_id)
    assert outside.read_bytes() == b"precious" and path.is_symlink()


def test_a_slot_that_is_a_link_to_a_folder_elsewhere_is_left_alone(tmp_path):
    root = tmp_path / "files"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "novel.pdf").write_bytes(b"mine")
    file_id = "1" * 32
    root.mkdir()
    (root / file_id).symlink_to(elsewhere, target_is_directory=True)
    run(index_at(root).add(StoredFile(file_id, "book", "novel.pdf", 4, "x", "user", 1.0)))
    with pytest.raises(up.UploadError):
        delete(root, file_id)
    assert (elsewhere / "novel.pdf").read_bytes() == b"mine"


def test_a_link_to_another_upload_deletes_neither(tmp_path):
    """Without the link check this is the dangerous one: the link resolves to a real file inside the very
    store, passes every location test, and the real file is what would be removed."""
    root = tmp_path / "files"
    _real_id, real = store(root, "audio", "real.m4a")
    link_id, link = store(root, "audio", "link.m4a")
    link.unlink()
    link.symlink_to(real)
    with pytest.raises(up.UploadError):
        delete(root, link_id)
    assert real.exists() and link.is_symlink()


def test_the_delete_endpoint_needs_the_token(tmp_path):
    async def body(client):
        return (await client.post("/api/uploads/delete", json={"id": "0" * 32})).status_code
    assert client_for(tmp_path, body) == 401


def test_deleting_an_upload_removes_it_tells_the_page_and_the_model_and_is_audited(tmp_path):
    root = tmp_path / "files"
    file_id, _ = store(root, "audio", "meeting.m4a")

    async def body(client):
        done = await client.post("/api/uploads/delete", headers=AUTH, json={"id": file_id})
        state = (await client.get("/api/state", headers=AUTH)).json()
        listing = (await client.get("/api/uploads", headers=AUTH)).json()
        return done, state, listing

    done, state, listing = client_for(tmp_path, body)
    assert done.status_code == 200 and done.json()["name"] == "meeting.m4a"
    assert listing["audio"] == []
    assert any(e["type"] == "upload_deleted" and e["id"] == file_id for e in state["history"])
    assert any("deleted" in note and "meeting.m4a" in note for note in state["notes"])
    row = audit_rows(tmp_path)[-1]
    assert (row["tool"], row["outcome"], row["origin"]) == ("assistant__delete_upload", "ok", "button")


def test_a_refused_delete_is_a_400_that_removes_and_records_nothing(tmp_path):
    root = tmp_path / "files"
    _file_id, kept = store(root, "audio", "meeting.m4a")

    async def body(client):
        return await client.post("/api/uploads/delete", headers=AUTH, json={"id": "../meeting.m4a"})

    refused = client_for(tmp_path, body)
    assert refused.status_code == 400 and "error" in refused.json()
    assert kept.exists() and audit_rows(tmp_path) == []
