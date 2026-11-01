"""Tests for collecting what a tool made (collect.py, records.py). The assistant files what a tool labels without
knowing what it is; every file it takes must be a plain file in a folder the tool declared, copied intact; the tool
lets go of its copy only once it is filed, and only the copy that was filed."""

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from assistant import files
from assistant.collect import Collector, ItemError, checked
from assistant.files import JsonFileIndex
from assistant.records import JsonRecordStore, Record
from assistant.tools import RemoteTool, ToolRegistry
from tests.test_server import run


class Bench:
    """A tool at its own bench: an output folder, an inventory of what is in it, and a release that deletes only
    what it is told, and only if the hash is the one filed -- as audiobook's does."""

    def __init__(self, folder: Path):
        self.folder = folder
        self.items: list[dict] = []
        self.releases: list[list[dict]] = []

    def make(self, name: str, data: bytes, kind="chapter", key=None, labels=None, text=None, release=True, version=None):
        path = self.folder / name
        path.write_bytes(data)
        self.items.append({"kind": kind, "key": key or name, "labels": labels or {"book": "b"}, "text": text,
                           "version": version or hashlib.sha256(data).hexdigest()[:16],
                           "files": [{"path": str(path), "role": "audio"}], "release": release})
        return path

    async def call_tool(self, name, arguments):
        if name == "inventory":
            text = json.dumps({"items": self.items})
        else:
            self.releases.append(arguments["files"])
            gone = []
            for f in arguments["files"]:
                p = Path(f["path"])
                if p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest() == f["sha256"]:
                    p.unlink()
                    gone.append(f["path"])
            text = json.dumps({"released": gone})
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], is_error=False)


class Declared(ToolRegistry):
    def __init__(self, folders):
        super().__init__([])
        self._folders = folders

    def folders_of(self, server):
        return self._folders if server == "bench" else []


def setup(tmp_path, read_only=True):
    out = tmp_path / "output"
    out.mkdir()
    bench = Bench(out)
    registry = Declared([out])
    registry._sessions["bench"] = bench
    registry.tools += [
        RemoteTool(server="bench", name="inventory", qualified_name="bench__inventory", description="",
                   input_schema={}, read_only=read_only),
        RemoteTool(server="bench", name="release", qualified_name="bench__release", description="",
                   input_schema={}, read_only=False),
    ]
    root = tmp_path / "files"
    index = JsonFileIndex(root / "index.json")
    records = JsonRecordStore(root / "records.json")
    return bench, Collector(registry, index, records, root), index, records, root


def test_a_finished_file_is_filed_under_the_tools_labels_and_the_tool_lets_go_of_it(tmp_path):
    bench, collector, index, records, root = setup(tmp_path)
    mp3 = bench.make("03-chapter-i-0.95x.mp3", b"ID3 chapter one", key="b/03", text="It was the best of times.",
                     labels={"book": "b", "number": 3, "title": "Chapter I"})
    got = run(collector.collect("bench"))
    assert (got["filed"], got["released"], got["refused"]) == (1, 1, [])
    record = run(records.get("bench", "chapter", "b/03"))
    assert record.labels == {"book": "b", "number": 3, "title": "Chapter I"} and record.text == "It was the best of times."
    stored = run(index.get(record.files["audio"]))
    assert (stored.kind, stored.made_by, stored.name) == ("made", "tool", mp3.name)
    assert files.path_of(root, stored).read_bytes() == b"ID3 chapter one"
    assert not mp3.exists()  # the bench is cleared
    # Not among uploads.
    from assistant import uploads as up
    assert run(up.listing(index, root, tmp_path / "texts")) == {"audio": [], "docs": [], "books": [], "voices": []}


def test_the_same_version_is_not_filed_twice_and_a_new_one_replaces_the_old(tmp_path):
    bench, collector, index, records, root = setup(tmp_path)
    bench.make("a.mp3", b"first", key="b/a", release=False)
    assert run(collector.collect("bench"))["filed"] == 1
    assert run(collector.collect("bench"))["filed"] == 0  # unchanged: nothing copied again
    first = run(records.get("bench", "chapter", "b/a"))
    bench.items.clear()
    bench.make("a.mp3", b"second, re-rendered", key="b/a", release=False)
    assert run(collector.collect("bench"))["filed"] == 1
    second = run(records.get("bench", "chapter", "b/a"))
    assert second.id == first.id and second.files["audio"] != first.files["audio"]
    assert run(index.get(first.files["audio"])) is None and not (root / first.files["audio"]).exists()
    assert files.path_of(root, run(index.get(second.files["audio"]))).read_bytes() == b"second, re-rendered"


def test_something_kept_as_a_working_copy_is_filed_and_left_where_it_is(tmp_path):
    bench, collector, _index, _records, _root = setup(tmp_path)
    voice = bench.make("abigail.safetensors", b"state", kind="voice", key="abigail", release=False)
    run(collector.collect("bench"))
    assert voice.exists() and bench.releases == []


@pytest.mark.parametrize("where", ["outside", "link", "link inside", "relative", "climb"])
def test_only_a_plain_file_in_a_declared_folder_is_taken(tmp_path, where):
    bench, collector, index, records, root = setup(tmp_path)
    secret = tmp_path / "secret.mp3"
    secret.write_bytes(b"not the tool's")
    path = {"outside": str(secret), "relative": "secret.mp3", "climb": str(bench.folder / ".." / "secret.mp3")}.get(where)
    if where == "link":
        (bench.folder / "link.mp3").symlink_to(secret)
        path = str(bench.folder / "link.mp3")
    if where == "link inside":  # a link is never followed, even to the tool's own file: nothing here makes one
        (bench.folder / "real.mp3").write_bytes(b"the tool's")
        (bench.folder / "link.mp3").symlink_to(bench.folder / "real.mp3")
        path = str(bench.folder / "link.mp3")
    bench.items.append({"kind": "chapter", "key": "x", "labels": {}, "text": None, "version": "1",
                        "files": [{"path": path, "role": "audio"}], "release": True})
    got = run(collector.collect("bench"))
    assert got["filed"] == 0 and len(got["refused"]) == 1
    assert run(records.get("bench", "chapter", "x")) is None and run(index.all()) == []
    assert secret.read_bytes() == b"not the tool's" and bench.releases == []


@pytest.mark.parametrize("item,error", [
    ({"kind": "", "key": "k", "version": "1"}, "kind"),
    ({"kind": "k", "key": "k", "version": "1", "text": "a\x00b"}, "NUL"),
    ({"kind": "k", "key": "k", "version": "1", "labels": "not an object"}, "labels"),
    ({"kind": "k", "key": "k", "version": "1", "files": [{"path": "/a", "role": "r"}, {"path": "/b", "role": "r"}]}, "two files"),
    ({"kind": "k", "key": "k"}, "version"),
])
def test_an_item_described_wrongly_is_refused_by_its_shape(item, error):
    with pytest.raises(ItemError, match=error):
        checked(item)


def test_a_tool_whose_inventory_is_not_read_only_is_never_asked(tmp_path):
    bench, collector, index, _records, _root = setup(tmp_path, read_only=False)
    bench.make("a.mp3", b"x")
    assert collector.offering() == [] and run(collector.collect("bench")) == {"filed": 0}
    assert run(index.all()) == []


def test_a_failed_copy_leaves_no_half_filed_record(tmp_path, monkeypatch):
    bench, collector, index, records, root = setup(tmp_path)
    bench.make("a.mp3", b"x" * 100, key="b/a")
    real = files.sha256_of
    calls = []

    def lying(path):
        calls.append(path)
        return "0" * 64 if len(calls) == 2 else real(path)  # the copy's hash comes out different
    monkeypatch.setattr(files, "sha256_of", lying)
    got = run(collector.collect("bench"))
    assert got["filed"] == 0 and "did not copy intact" in got["refused"][0]
    assert run(records.get("bench", "chapter", "b/a")) is None and run(index.all()) == []
    assert not any(files.is_id(p.name) for p in root.iterdir()) if root.exists() else True
    assert (bench.folder / "a.mp3").exists() and bench.releases == []


# ---------------------------------------------------------------------------
# The records, in PostgreSQL too
# ---------------------------------------------------------------------------

from assistant.db import Database
from assistant.files import PgFileIndex, StoredFile
from assistant.records import PgRecordStore
from tests.test_database import needs_postgres, scratch_database


async def behaves_like_records(records, index):
    await index.add(StoredFile("f" * 32, "made", "a.mp3", 3, "x", "tool", 1.0))
    await index.add(StoredFile("e" * 32, "made", "b.mp3", 3, "x", "tool", 1.0))
    first = Record("1" * 32, "bench", "chapter", "b/1", {"book": "b", "number": 1, "title": "Á"}, "words", "v1",
                   {"audio": "f" * 32}, created=10.0, updated=10.0)
    await records.put(first)
    await records.put(Record("2" * 32, "bench", "voice", "abigail", {"name": "abigail"}, None, "v1", {},
                             created=20.0, updated=20.0))
    got = await records.get("bench", "chapter", "b/1")
    listed = [(r.kind, r.text) for r in await records.find("bench")]
    chapters = [r.id for r in await records.find("bench", "chapter")]
    # Filed again under the same key: replaced, files and all.
    await records.put(Record("1" * 32, "bench", "chapter", "b/1", {"book": "b"}, "new words", "v2", {"audio": "e" * 32},
                             created=10.0, updated=30.0))
    replaced = await records.by_id("1" * 32)
    await records.remove("2" * 32)
    after = [r.id for r in await records.find("bench")]
    return got, listed, chapters, replaced, after


def check_records(got, listed, chapters, replaced, after):
    assert got.labels == {"book": "b", "number": 1, "title": "Á"} and got.text == "words" and got.files == {"audio": "f" * 32}
    assert listed == [("voice", None), ("chapter", None)]  # newest first, and a listing carries no text
    assert chapters == ["1" * 32]
    assert (replaced.text, replaced.version, replaced.files) == ("new words", "v2", {"audio": "e" * 32})
    assert after == ["1" * 32]


def test_the_records_file_keeps_records_by_tool_kind_and_key(tmp_path):
    root = tmp_path / "files"
    check_records(*run(behaves_like_records(JsonRecordStore(root / "records.json"), JsonFileIndex(root / "index.json"))))


@needs_postgres
def test_the_records_table_keeps_them_as_the_file_does():
    async def body():
        async with scratch_database() as url:
            async with Database(url) as database:
                return await behaves_like_records(PgRecordStore(database), PgFileIndex(database))
    check_records(*run(body()))


@needs_postgres
def test_a_stored_file_a_record_names_cannot_be_deleted_from_under_it():
    import asyncpg

    async def body():
        async with scratch_database() as url:
            async with Database(url) as database:
                index, records = PgFileIndex(database), PgRecordStore(database)
                await index.add(StoredFile("f" * 32, "made", "a.mp3", 3, "x", "tool", 1.0))
                await records.put(Record("1" * 32, "bench", "chapter", "k", {}, None, "v", {"audio": "f" * 32}, 1.0, 1.0))
                try:
                    await index.remove("f" * 32)
                except asyncpg.ForeignKeyViolationError:
                    refused = True
                else:
                    refused = False
                await records.remove("1" * 32)  # its links go with it
                await index.remove("f" * 32)
                return refused, await index.get("f" * 32)
    assert run(body()) == (True, None)


@needs_postgres
def test_the_store_takes_a_tools_file_once_the_migration_allows_it():
    import asyncpg

    async def body():
        async with scratch_database() as url:
            async with Database(url) as database:
                index = PgFileIndex(database)
                await index.add(StoredFile("f" * 32, "made", "a.mp3", 3, "x", "tool", 1.0))
                try:
                    await index.add(StoredFile("e" * 32, "made", "a.mp3", 3, "x", "someone", 1.0))
                except asyncpg.CheckViolationError:
                    return True
                return False
    assert run(body()) is True


# ---------------------------------------------------------------------------
# What sets it off, and the page's side
# ---------------------------------------------------------------------------

def test_a_call_that_may_have_changed_something_is_told_and_a_read_is_not(tmp_path):
    bench, collector, *_ = setup(tmp_path)
    registry = collector.registry
    registry.tools.append(RemoteTool(server="bench", name="render", qualified_name="bench__render", description="",
                                     input_schema={}, read_only=False))
    told = []
    registry.changed = lambda tool: told.append(tool.name)

    async def calls():
        bench.call_tool = lambda name, arguments: _answer("{}")  # every call answers the same
        await registry.call(registry.find("bench__inventory"), {})
        await registry.call(registry.find("bench__render"), {})
    run(calls())
    assert told == ["render"]


async def _answer(text, is_error=False):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], is_error=is_error)


def test_the_watcher_asks_for_a_collection_when_a_job_finishes_a_chapter_or_ends(monkeypatch):
    from assistant import watchers

    polls = iter([
        {"job": {"id": "j", "state": "running", "outputs": []}},
        {"job": {"id": "j", "state": "running", "outputs": []}},
        {"job": {"id": "j", "state": "running", "outputs": ["/o/01.mp3"]}},
        {"job": {"id": "j", "state": "done", "outputs": ["/o/01.mp3"]}},
        {"job": {"id": "j", "state": "done", "outputs": ["/o/01.mp3"]}},
    ])
    asked = []

    async def read(_registry, name):
        if name != "audiobook__job_status":
            return None
        try:
            return next(polls)
        except StopIteration:
            raise asyncio.CancelledError

    async def nothing(_event):
        return None
    monkeypatch.setattr(watchers, "_read", read)
    monkeypatch.setattr(watchers, "POLL_SECONDS", 0)
    with pytest.raises(asyncio.CancelledError):
        run(watchers.watch(None, nothing, on_change=asked.append))
    assert asked == ["audiobook", "audiobook"]  # the chapter, then the end; never the quiet polls


def test_the_page_lists_reads_and_deletes_records_and_only_their_own_files(tmp_path):
    from tests.test_server import AUTH, app_for, with_client

    root = tmp_path / "files"
    index, records = JsonFileIndex(root / "index.json"), JsonRecordStore(root / "records.json")
    made_id, slot = files.new_slot(root)
    (slot / "01.mp3").write_bytes(b"ID3")
    run(index.add(StoredFile(made_id, "made", "01.mp3", 3, "x", "tool", 1.0)))
    upload_id, upslot = files.new_slot(root)
    (upslot / "book.pdf").write_bytes(b"%PDF")
    run(index.add(StoredFile(upload_id, "book", "book.pdf", 4, "x", "user", 1.0)))
    run(records.put(Record("1" * 32, "audiobook", "chapter", "b/01", {"book": "b", "title": "One"}, "Its words.", "v",
                           {"audio": made_id, "pdf": upload_id}, 1.0, 1.0)))

    async def body(client):
        listed = (await client.get("/api/records?tool=audiobook&kind=chapter", headers=AUTH)).json()
        one = (await client.get(f"/api/records/{'1' * 32}", headers=AUTH)).json()
        missing = (await client.get(f"/api/records/{'2' * 32}", headers=AUTH)).status_code
        no_token = (await client.get("/api/records?tool=audiobook")).status_code
        refused = (await client.post("/api/records/delete", headers=AUTH, json={"ids": ["1" * 32, "../x"]})).status_code
        deleted = (await client.post("/api/records/delete", headers=AUTH, json={"ids": ["1" * 32]})).json()
        state = (await client.get("/api/state", headers=AUTH)).json()
        return listed, one, missing, no_token, refused, deleted, state

    listed, one, missing, no_token, refused, deleted, state = run(with_client(app_for(tmp_path), body))
    assert [r["labels"]["title"] for r in listed["records"]] == ["One"] and "text" not in listed["records"][0]
    assert listed["records"][0]["files"]["audio"] == {"id": made_id, "name": "01.mp3", "bytes": 3}
    assert one["text"] == "Its words." and (missing, no_token, refused) == (404, 401, 400)
    assert deleted == {"deleted": 1, "bytes": 3}
    assert run(records.by_id("1" * 32)) is None and run(index.get(made_id)) is None and not (root / made_id).exists()
    # A record naming an upload never takes the upload with it.
    assert (upslot / "book.pdf").read_bytes() == b"%PDF" and run(index.get(upload_id)) is not None
    assert any("deleted 1 kept item" in n and "One" in n for n in state["notes"])
    audited = json.loads((tmp_path / "audit.jsonl").read_text().splitlines()[-1])
    assert (audited["tool"], audited["origin"]) == ("assistant__delete_records", "button")


def test_the_model_can_see_what_is_kept(tmp_path):
    from assistant.records import kept_tools

    root = tmp_path / "files"
    index, records = JsonFileIndex(root / "index.json"), JsonRecordStore(root / "records.json")
    run(records.put(Record("1" * 32, "audiobook", "chapter", "b/01", {"book": "b", "title": "One"}, "words", "v", {}, 1.0, 1.0)))
    (tool,) = kept_tools(records, index)
    seen = json.loads(run(tool.handler({"tool": "audiobook"})))
    assert tool.read_only and [r["labels"]["title"] for r in seen["records"]] == ["One"] and "text" not in seen["records"][0]


def test_the_servers_collection_does_not_set_itself_off_again(tmp_path):
    """The collector's own release changes something, and every change asks for a collection: the server must not
    count its own inventory and release as changes, or collecting would never end."""
    from assistant.server import create_app
    from tests.test_server import TOKEN, with_client

    out = tmp_path / "output"
    out.mkdir()
    bench = Bench(out)
    bench.make("a.mp3", b"chapter", key="b/a")
    asked = []
    real = bench.call_tool

    async def counting(name, arguments):
        asked.append(name)
        return await real(name, arguments)
    bench.call_tool = counting

    def registry(local):
        r = Declared([out])
        r._local = {t.name: t for t in local}
        r._sessions["bench"] = bench
        r.tools += [RemoteTool(server="bench", name="inventory", qualified_name="bench__inventory", description="",
                               input_schema={}, read_only=True),
                    RemoteTool(server="bench", name="release", qualified_name="bench__release", description="",
                               input_schema={}, read_only=False)]
        return r

    async def body(client):
        for _ in range(40):  # the start's collection, in the background
            if "release" in asked:
                break
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.5)  # time enough for a loop to show itself
        return list(asked)

    app = create_app(tmp_path / "tools.yaml", tmp_path / "memory.json", tmp_path / "audit.jsonl", token=TOKEN,
                     registry_factory=registry, watch_jobs=False, files_path=tmp_path / "files",
                     texts_path=tmp_path / "texts")
    assert run(with_client(app, body)) == ["inventory", "release"]
    assert not (out / "a.mp3").exists()
