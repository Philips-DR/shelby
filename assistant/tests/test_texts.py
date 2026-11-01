"""Tests for lending stored markdown to a tool (texts.py). The database holds a document's only lasting copy;
a tool is lent one for the length of a call, read-only, and it is gone when the call ends."""

import asyncio
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from assistant import files, texts
from assistant.files import JsonFileIndex, StoredFile
from assistant.server import create_app
from assistant.texts import Lender
from assistant.tools import RemoteTool, ToolRegistry
from tests.test_server import AUTH, TOKEN, app_for, run, with_client


def stored(index, name, contents, made_by="user"):
    sha, size = files.texts_digest(contents)
    record = StoredFile(files.new_id(), "docs", name, size, sha, made_by, 1.0)
    run(index.add(record, contents))
    return record


def setup(tmp_path):
    index = JsonFileIndex(tmp_path / "files" / "index.json")
    return index, Lender(tmp_path / "texts", index)


def lent_during(lender, arguments, look):
    """What `look` saw while a call with these arguments was running."""
    async def body():
        async with lender.lend(arguments):
            return look()
    return run(body())


def test_a_document_is_on_disk_only_while_a_call_holds_it(tmp_path):
    index, lender = setup(tmp_path)
    cv = stored(index, "CV - Ama", {"CV - Ama.md": "# Ama Mensah — CV\n"})
    path = texts.path_for(tmp_path / "texts", cv, ["CV - Ama.md"])
    assert not path.exists()
    seen = lent_during(lender, {"path": str(path)}, lambda: path.read_text(encoding="utf-8"))
    assert seen == "# Ama Mensah — CV\n"
    assert not path.exists() and list((tmp_path / "texts").iterdir()) == []


def test_a_lent_copy_is_read_only_whole_and_marked_when_the_assistant_wrote_it(tmp_path):
    index, lender = setup(tmp_path)
    book = stored(index, "handbook", {"01-a.md": "# A\n", "02-b.md": "# B\n"})
    draft = stored(index, "CV - Role", {"CV - Role.md": "# CV\n"}, made_by="assistant")
    folder = texts.path_for(tmp_path / "texts", book, ["01-a.md", "02-b.md"])
    draft_path = texts.path_for(tmp_path / "texts", draft, ["CV - Role.md"])

    def look():
        modes = {p.name: stat.S_IMODE(p.stat().st_mode) for p in (folder, folder / "01-a.md")}
        return sorted(p.name for p in folder.iterdir()), sorted(p.name for p in draft_path.parent.iterdir()), modes

    in_book, in_draft, modes = lent_during(lender, {"sources": [str(folder), {"also": str(draft_path)}]}, look)
    # docu-ai titles a Doc after the folder and gives each file a tab: names exactly as stored.
    assert in_book == ["01-a.md", "02-b.md"]
    # apply-ai refuses a folder holding the marker: a draft is never the user's own material.
    assert in_draft == [".draft", "CV - Role.md"]
    assert modes == {"handbook": 0o555, "01-a.md": 0o444}


@pytest.mark.parametrize("argument", [
    "/etc/passwd",
    "relative/path.md",
    "{root}/../files/index.json",
    "{root}/" + "0" * 32 + "/cv/cv.md",  # an id nothing is stored under
    "{root}/{audio}/meeting.m4a",  # a stored file that is not markdown
    "{root}/not-an-id/cv.md",
])
def test_a_path_that_names_no_stored_document_lends_nothing(tmp_path, argument):
    index, lender = setup(tmp_path)
    stored(index, "cv", {"cv.md": "# CV\n"})
    audio = StoredFile(files.new_id(), "audio", "meeting.m4a", 1, "x", "user", 1.0)
    run(index.add(audio))
    value = argument.format(root=tmp_path / "texts", audio=audio.id)
    assert lent_during(lender, {"path": value}, lambda: (tmp_path / "texts").exists()) is False


def test_two_calls_share_one_copy_and_it_goes_when_the_last_ends(tmp_path):
    index, lender = setup(tmp_path)
    cv = stored(index, "cv", {"cv.md": "# CV\n"})
    path = texts.path_for(tmp_path / "texts", cv, ["cv.md"])

    async def body():
        first_done, second_started = asyncio.Event(), asyncio.Event()
        seen = {}

        async def first():
            async with lender.lend({"path": str(path)}):
                await second_started.wait()
            first_done.set()

        async def second():
            async with lender.lend({"path": str(path)}):
                second_started.set()
                await first_done.wait()
                seen["after the first ended"] = path.exists()
            seen["after both"] = path.exists()

        await asyncio.gather(first(), second())
        return seen

    assert run(body()) == {"after the first ended": True, "after both": False}


def test_a_call_that_fails_still_gives_its_copy_back(tmp_path):
    index, lender = setup(tmp_path)
    cv = stored(index, "cv", {"cv.md": "# CV\n"})
    path = texts.path_for(tmp_path / "texts", cv, ["cv.md"])

    async def body():
        async with lender.lend({"path": str(path)}):
            raise ConnectionError("the tool died")

    with pytest.raises(ConnectionError):
        run(body())
    assert not path.exists()


def test_clearing_on_start_removes_only_what_a_lend_makes(tmp_path):
    root = tmp_path / "texts"
    left = root / ("a" * 32) / "cv"
    left.mkdir(parents=True)
    (left / "cv.md").write_text("# left from a crash")
    left.chmod(0o555)
    half = root / (".%s-x1y2" % ("b" * 32))
    half.mkdir()
    (root / "notes.txt").write_text("not a lend's")
    (root / "keep").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / ("c" * 32)).symlink_to(outside, target_is_directory=True)
    Lender(root, JsonFileIndex(tmp_path / "index.json")).clear()
    assert sorted(p.name for p in root.iterdir()) == ["c" * 32, "keep", "notes.txt"] and outside.is_dir()


def test_clearing_a_folder_that_is_not_there_makes_nothing(tmp_path):
    Lender(tmp_path / "texts", JsonFileIndex(tmp_path / "index.json")).clear()
    assert not (tmp_path / "texts").exists()


class FakeSession:
    """A tool on the far side of MCP that reads the path it is given, as docu-ai and apply-ai do."""

    async def call_tool(self, name, arguments):
        path = Path(arguments["path"])
        text = path.read_text() if path.is_file() else f"no such file: {path}"
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], is_error=False)


def reader(local=()):
    registry = ToolRegistry([], local=list(local))
    registry._sessions["docu_ai"] = FakeSession()
    registry.tools.append(RemoteTool(server="docu_ai", name="preview", qualified_name="docu_ai__preview",
                                     description="", input_schema={}, read_only=True))
    return registry


def test_every_call_to_a_tool_is_lent_what_it_names(tmp_path):
    index, lender = setup(tmp_path)
    cv = stored(index, "cv", {"cv.md": "# CV\n"})
    path = texts.path_for(tmp_path / "texts", cv, ["cv.md"])
    registry = reader()
    registry.lend = lender.lend
    outcome = run(registry.call(registry.find("docu_ai__preview"), {"path": str(path)}))
    assert outcome.text == "# CV\n" and not path.exists()


def test_a_button_reaches_a_tool_with_an_uploaded_document_and_leaves_nothing(tmp_path):
    """End to end: uploaded through the API, read by a tool through a button, gone from disk after."""
    async def body(client):
        batch = (await client.post("/api/uploads/docs", headers=AUTH, json={"name": "cv"})).json()["batch"]
        await client.put(f"/api/uploads/docs/{batch}?name=cv.md", headers=AUTH, content=b"# Ama\n")
        done = (await client.post(f"/api/uploads/docs/{batch}/done", headers=AUTH)).json()
        acted = (await client.post("/api/actions", headers=AUTH,
                                   json={"tool": "docu_ai__preview", "arguments": {"path": done["path"]}})).json()
        return done, acted

    app = create_app(tmp_path / "tools.yaml", tmp_path / "memory.json", tmp_path / "audit.jsonl", token=TOKEN,
                     registry_factory=reader, watch_jobs=False,
                     files_path=tmp_path / "files", texts_path=tmp_path / "texts")
    done, acted = run(with_client(app, body))
    assert acted == {"outcome": "ok", "output": "# Ama\n"}
    assert not Path(done["path"]).exists() and list((tmp_path / "texts").iterdir()) == []


def test_the_texts_folder_and_the_file_store_must_be_apart(tmp_path):
    for files_path, texts_path in ((tmp_path / "store", tmp_path / "store" / "texts"),
                                   (tmp_path / "store", tmp_path / "store"),
                                   (tmp_path / "texts" / "store", tmp_path / "texts")):
        with pytest.raises(ValueError, match="must be apart"):
            app_for(tmp_path, files_path=files_path, texts_path=texts_path)
