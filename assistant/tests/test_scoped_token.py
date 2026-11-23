"""A scoped token (the TV's ASSISTANT_TV_TOKEN): what it may reach, what it may read there, and that nothing else opens.

The real app, in-process, as test_server.py has it. The data is shaped like the real records (2026-11-23): a tool keeps
chapters and books, but also voices with their recordings, samples, job logs and a whole-book file, and the uploads
hold meeting audio and voice samples too. The token is for playing books and must never reach any of the rest.
"""

import asyncio

import pytest

from assistant import files
from assistant.config import Grant, ToolServer, load_tool_servers
from assistant.files import JsonFileIndex, StoredFile
from assistant.records import JsonRecordStore, Record
from assistant.server import MIN_SCOPED_TOKEN, create_app, scoped_route
from assistant.tools import Granted, ToolRegistry, tool_environment
from tests.test_server import AUTH, TOKEN, run, with_client

TV = "tv-" + "t" * 40
TVH = {"x-assistant-token": TV}

# What the real tools.yaml grants the tv scope, with built-in tools standing in for the two audiobook calls: `recall`
# is read-only and granted; `remember` writes and is granted by mistake, which must still be refused.
GRANTED = Granted(actions=frozenset({"assistant__recall", "assistant__remember"}),
                  records={"audiobook": frozenset({"chapter", "book"})},
                  files={"audiobook": frozenset({"audio"})},
                  uploads=frozenset({"book"}))


class Granting(ToolRegistry):
    """A registry that grants without launching any tool."""

    def __init__(self, local, granted):
        super().__init__([], local=local)
        self._granted = granted

    def grants(self, scope):
        return self._granted if scope == "tv" else Granted()


def app_for(tmp_path, granted=GRANTED, **kwargs):
    kwargs.setdefault("scoped_tokens", {"tv": TV})
    return create_app(tmp_path / "tools.yaml", tmp_path / "memory.json", tmp_path / "audit.jsonl", token=TOKEN,
                      registry_factory=lambda local: Granting(local, granted), watch_jobs=False,
                      files_path=tmp_path / "files", texts_path=tmp_path / "texts", **kwargs)


def seed(tmp_path):
    """Files and records as the real store has them. Returns the ids by name."""
    root = tmp_path / "files"
    index, records = JsonFileIndex(root / "index.json"), JsonRecordStore(root / "records.json")
    ids: dict[str, str] = {}

    def keep(label, kind, name, data, made_by="tool"):
        file_id, slot = files.new_slot(root)
        (slot / name).write_bytes(data)
        run(index.add(StoredFile(file_id, kind, name, len(data), "x", made_by, 1.0)))
        ids[label] = file_id

    keep("chapter audio", "made", "01.mp3", b"ID3 a chapter")
    keep("chapter extra", "made", "notes.txt", b"a file the same chapter keeps in another role")
    keep("voice sample", "made", "sample.wav", b"RIFF a voice")
    keep("voice source", "made", "source.wav", b"RIFF its source")
    keep("whole book", "made", "book.m4b", b"m4b")
    keep("another tool's audio", "made", "other.mp3", b"ID3 other")
    keep("shared", "made", "shared.mp3", b"ID3 shared")
    keep("book upload", "book", "Novel.pdf", b"%PDF-1.7", "user")
    keep("meeting upload", "audio", "meeting.m4a", b"meeting", "user")
    keep("voice upload", "voice", "me.wav", b"mine", "user")

    def record(label, tool, kind, held, text=None):
        ids[label] = f"{len(ids):032x}"
        run(records.put(Record(ids[label], tool, kind, label, {"title": label}, text, "v", {r: ids[f] for r, f in held.items()},
                               1.0, 1.0)))

    # The chapter is a kind the token may read, so only the role keeps `notes` from it (as with a real chapter's PDF).
    record("a chapter", "audiobook", "chapter", {"audio": "chapter audio", "notes": "chapter extra"}, "Its words.")
    record("a book", "audiobook", "book", {})
    record("a voice", "audiobook", "voice", {"sample": "voice sample", "source": "voice source"})
    record("a job", "audiobook", "job", {})
    record("an m4b", "audiobook", "audiobook", {"audio": "whole book"})
    record("another tool's chapter", "meet_ai", "chapter", {"audio": "another tool's audio"}, "secret")
    # One file two records keep: the chapter's audio and, by a mistake, a voice's recording.
    record("shared chapter", "audiobook", "chapter", {"audio": "shared"})
    record("shared voice", "audiobook", "voice", {"sample": "shared"})
    return ids


def call(tmp_path, body, **kwargs):
    return run(with_client(app_for(tmp_path, **kwargs), body))


# ---------------------------------------------------------------------------
# A way in, and only five routes
# ---------------------------------------------------------------------------

def test_a_scoped_token_is_a_way_in_and_a_wrong_one_is_not(tmp_path):
    async def body(client):
        return [(await client.get("/api/uploads", headers=h)).status_code
                for h in (TVH, {"x-assistant-token": "x" * 40}, {})]
    assert call(tmp_path, body) == [200, 401, 401]


def test_no_scoped_token_set_means_no_such_way_in(tmp_path):
    async def body(client):
        return (await client.get("/api/uploads", headers=TVH)).status_code
    assert call(tmp_path, body, scoped_tokens={}) == 401


REFUSED = [
    ("GET", "/api/tools"), ("GET", "/api/state"), ("GET", "/api/status"), ("GET", "/api/history"),
    ("GET", "/api/usage"), ("GET", "/api/conversations"), ("GET", "/api/files?path=/etc/hosts"),
    ("GET", f"/api/events?token={TV}"), ("GET", "/api/actions"), ("GET", "/api/records/not-an-id"),
    ("GET", "/api/files/not-an-id"), ("GET", "/api/records/"), ("GET", "/api/records//"),
    ("POST", "/api/chat"), ("POST", "/api/chat/clear"), ("POST", "/api/chat/stop"), ("POST", "/api/approvals/x"),
    ("POST", "/api/records/delete"), ("POST", "/api/uploads/delete"), ("POST", "/api/uploads/rename"),
    ("POST", "/api/model/route"), ("POST", "/api/speak"), ("POST", "/api/uploads/docs"),
    ("PUT", "/api/uploads/book"), ("PUT", "/api/uploads/audio"), ("PUT", "/api/uploads/voice"),
    ("PUT", "/api/dictate"), ("DELETE", "/api/conversations/x"), ("PATCH", "/api/conversations/x"),
    ("PUT", "/api/records"), ("DELETE", "/api/records"), ("PUT", "/api/uploads"), ("POST", "/api/uploads"),
]


def test_a_scoped_token_reaches_five_routes_and_nothing_else(tmp_path):
    ids = seed(tmp_path)

    async def knock(client, method, path):
        # Bounded: if the guard were ever broken, the event stream among these never ends, and a test that hangs
        # tells nobody what failed.
        return (await asyncio.wait_for(client.request(method, path, headers=TVH, content=b"{}"), 5)).status_code

    async def body(client):
        got = {(m, p): await knock(client, m, p) for m, p in REFUSED}
        still_there = (await client.get(f"/api/records/{ids['a chapter']}", headers=AUTH)).status_code
        return got, still_there
    got, still_there = call(tmp_path, body)
    assert {k: v for k, v in got.items() if v != 403} == {}
    assert still_there == 200  # the delete it tried did not run


def test_the_route_rule_alone_lets_through_exactly_five(tmp_path):
    some_id = "a" * 32
    allowed = [("GET", "/api/records"), ("GET", "/api/uploads"), ("POST", "/api/actions"),
               ("GET", f"/api/records/{some_id}"), ("GET", f"/api/files/{some_id}")]
    assert all(scoped_route(m, p) for m, p in allowed)
    for method, path in REFUSED + [("POST", f"/api/records/{some_id}"), ("DELETE", f"/api/files/{some_id}"),
                                   ("GET", f"/api/files/{some_id}/x"), ("GET", f"/api/files/{some_id}/../x"),
                                   ("GET", f"/api/records/x/{some_id}"), ("GET", f"/api/records/{some_id.upper()}")]:
        assert not scoped_route(method, path.split("?")[0]), (method, path)


def test_the_launch_token_still_reaches_everything_it_did(tmp_path):
    async def body(client):
        return [(await client.get(p, headers=AUTH)).status_code
                for p in ("/api/tools", "/api/state", "/api/history", "/api/uploads", "/api/records?tool=audiobook")]
    assert call(tmp_path, body) == [200, 200, 200, 200, 200]


def test_a_header_with_a_character_no_token_has_is_a_401_not_a_crash(tmp_path):
    """compare_digest raises on a non-ASCII str, and a stranger can send one."""
    async def body(client):
        raw = [(b"x-assistant-token", "é".encode("utf-8") * 30)]
        return (await client.get("/api/uploads", headers=raw)).status_code
    assert call(tmp_path, body) == 401


# ---------------------------------------------------------------------------
# Records: chapters and books, not what else the tool keeps
# ---------------------------------------------------------------------------

def test_a_scoped_token_lists_only_the_kinds_it_is_granted(tmp_path):
    ids = seed(tmp_path)

    async def body(client):
        get = lambda q: client.get(f"/api/records?{q}", headers=TVH)
        return {"chapters": await get("tool=audiobook&kind=chapter"), "books": await get("tool=audiobook&kind=book"),
                "any kind": await get("tool=audiobook"),
                "voices": await get("tool=audiobook&kind=voice"), "jobs": await get("tool=audiobook&kind=job"),
                "whole book": await get("tool=audiobook&kind=audiobook"),
                "another tool": await get("tool=meet_ai&kind=chapter"), "a tool not named": await get("tool=nope")}
    got = call(tmp_path, body)
    assert {r["labels"]["title"] for r in got["chapters"].json()["records"]} == {"a chapter", "shared chapter"}
    assert [r["kind"] for r in got["books"].json()["records"]] == ["book"]
    # No kind asked for: only the kinds it may have, though the tool keeps voices, jobs and a whole-book file too.
    assert {r["kind"] for r in got["any kind"].json()["records"]} == {"chapter", "book"}
    asked_for_more = ("voices", "jobs", "whole book", "another tool", "a tool not named")
    assert {k: got[k].status_code for k in asked_for_more} == {k: 403 for k in asked_for_more}
    assert all(got[k].status_code == 200 for k in ("chapters", "books", "any kind"))
    assert ids["a voice"] not in str([v.text for v in got.values()])


def test_a_scoped_token_reads_a_chapter_with_its_text_and_not_what_it_may_not(tmp_path):
    ids = seed(tmp_path)

    async def body(client):
        read = lambda label: client.get(f"/api/records/{ids[label]}", headers=TVH)
        return {label: await read(label) for label in
                ("a chapter", "a book", "a voice", "a job", "an m4b", "another tool's chapter")}, \
            await client.get(f"/api/records/{'9' * 32}", headers=TVH)
    got, missing = call(tmp_path, body)
    assert got["a chapter"].status_code == 200 and got["a chapter"].json()["text"] == "Its words."
    assert got["a book"].status_code == 200
    refused = {label: r for label, r in got.items() if label not in ("a chapter", "a book")}
    assert {r.status_code for r in refused.values()} == {404}
    # The same plain answer a missing record gets: it says nothing about what exists.
    assert {r.text for r in refused.values()} == {missing.text}


# ---------------------------------------------------------------------------
# Files: the audio of a chapter, not a voice's recording or an upload
# ---------------------------------------------------------------------------

def test_a_scoped_token_plays_a_chapters_audio_by_range_and_gets_no_other_file(tmp_path):
    ids = seed(tmp_path)

    async def body(client):
        get = lambda label, **h: client.get(f"/api/files/{ids[label]}", headers={**TVH, **h})
        return {"chapter audio": await get("chapter audio"), "a range": await get("chapter audio", range="bytes=0-2"),
                **{label: await get(label) for label in
                   ("chapter extra", "voice sample", "voice source", "whole book", "another tool's audio", "shared",
                    "book upload", "meeting upload", "voice upload")},
                "unknown": await client.get(f"/api/files/{'9' * 32}", headers=TVH)}
    got = call(tmp_path, body)
    assert got["chapter audio"].status_code == 200 and got["chapter audio"].content == b"ID3 a chapter"
    assert got["a range"].status_code == 206 and got["a range"].content == b"ID3"
    refused = {k: v for k, v in got.items() if k not in ("chapter audio", "a range")}
    assert {k: v.status_code for k, v in refused.items()} == {k: 404 for k in refused}
    assert len({v.text for v in refused.values()}) == 1  # one plain answer for all of them


def test_the_launch_token_still_plays_every_one_of_those_files(tmp_path):
    ids = seed(tmp_path)

    async def body(client):
        return {label: (await client.get(f"/api/files/{ids[label]}", headers=AUTH)).status_code
                for label in ("chapter audio", "voice sample", "whole book", "book upload", "meeting upload")}
    assert set(call(tmp_path, body).values()) == {200}


# ---------------------------------------------------------------------------
# The uploads list: books only
# ---------------------------------------------------------------------------

def test_a_scoped_token_sees_the_books_in_the_uploads_list_and_nothing_else(tmp_path):
    ids = seed(tmp_path)

    async def body(client):
        return (await client.get("/api/uploads", headers=TVH)).json(), (await client.get("/api/uploads", headers=AUTH)).json()
    tv, full = call(tmp_path, body)
    assert [b["id"] for b in tv["books"]] == [ids["book upload"]] and tv["books"][0]["path"].endswith("Novel.pdf")
    assert (tv["audio"], tv["voices"], tv["docs"]) == ([], [], [])  # the same shape, so what parses it keeps working
    assert [a["id"] for a in full["audio"]] == [ids["meeting upload"]]  # they exist: the full token sees them
    assert [v["id"] for v in full["voices"]] == [ids["voice upload"]]


# ---------------------------------------------------------------------------
# Actions: the granted ones, and only if read-only
# ---------------------------------------------------------------------------

def test_a_scoped_token_presses_a_granted_read_only_button_and_no_other(tmp_path):
    async def body(client):
        press = lambda tool: client.post("/api/actions", headers=TVH, json={"tool": tool, "arguments": {}})
        return {"granted and read-only": await press("assistant__recall"),
                "read-only, not granted": await press("assistant__list_uploads"),
                "granted by mistake, writes": await press("assistant__remember"),
                "a write, not granted": await press("assistant__forget"),
                "not a tool": await press("nope")}, \
            (await client.get("/api/state", headers=AUTH)).json()["notes"], \
            await client.post("/api/actions", headers=AUTH, json={"tool": "nope"})
    got, notes, full_unknown = call(tmp_path, body)
    assert got["granted and read-only"].status_code == 200 and got["granted and read-only"].json()["outcome"] == "ok"
    assert {k: v.status_code for k, v in got.items() if k != "granted and read-only"} == {
        "read-only, not granted": 403, "granted by mistake, writes": 403, "a write, not granted": 403, "not a tool": 403}
    assert notes == []  # nothing was written
    assert full_unknown.status_code == 404  # the launch token is told as before


# ---------------------------------------------------------------------------
# Starting: a mistake in the setup stops the server, and never says the token
# ---------------------------------------------------------------------------

def test_a_token_that_is_too_short_stops_the_server_starting_without_saying_it(tmp_path):
    short = "s" * (MIN_SCOPED_TOKEN - 1)
    with pytest.raises(ValueError) as stopped:
        app_for(tmp_path, scoped_tokens={"tv": short})
    assert "shorter than" in str(stopped.value) and short not in str(stopped.value)
    app_for(tmp_path, scoped_tokens={"tv": "s" * MIN_SCOPED_TOKEN})  # the shortest allowed


def test_a_scoped_token_that_is_the_launch_token_or_another_scopes_is_refused(tmp_path):
    with pytest.raises(ValueError, match="same as the launch token"):
        create_app(tmp_path / "tools.yaml", tmp_path / "memory.json", tmp_path / "audit.jsonl", token=TV,
                   registry_factory=lambda local: Granting(local, GRANTED), watch_jobs=False,
                   files_path=tmp_path / "files", texts_path=tmp_path / "texts", scoped_tokens={"tv": TV})
    with pytest.raises(ValueError, match="share one token"):
        app_for(tmp_path, scoped_tokens={"tv": TV, "other": TV})


def test_a_token_with_nothing_granted_stops_the_server_instead_of_looking_broken(tmp_path):
    async def body(client):
        return None
    with pytest.raises(ValueError, match="no tool in tools.yaml grants the tv scope"):
        call(tmp_path, body, granted=Granted())


def test_a_grant_of_an_upload_kind_the_list_does_not_show_stops_the_server(tmp_path):
    async def body(client):
        return None
    with pytest.raises(ValueError, match="uploads of kind docs"):
        call(tmp_path, body, granted=Granted(uploads=frozenset({"docs"})))


def test_no_tool_inherits_a_token_that_opens_the_api(monkeypatch):
    """The launch token and the TV's both. A tool can reach the API from inside the container, and web-ai reads
    arbitrary web pages; what a tool is given on purpose still reaches it (tools.yaml's env)."""
    monkeypatch.setenv("ASSISTANT_TV_TOKEN", TV)
    monkeypatch.setenv("ASSISTANT_TOKEN", TOKEN)
    monkeypatch.setenv("AUDIOBOOK_HOME", "kept")
    environment = tool_environment({"MEET_AI_AUDIO": "/data/audio"})
    assert not {"ASSISTANT_TV_TOKEN", "ASSISTANT_TOKEN"} & set(environment)
    assert environment["AUDIOBOOK_HOME"] == "kept" and environment["MEET_AI_AUDIO"] == "/data/audio"


# ---------------------------------------------------------------------------
# tools.yaml: the grant is declared there, and read strictly
# ---------------------------------------------------------------------------

def servers_from(tmp_path, scopes_yaml):
    (tmp_path / "tools.yaml").write_text(f"servers:\n  - name: audiobook\n    command: /bin/true\n{scopes_yaml}")
    return load_tool_servers(tmp_path / "tools.yaml")


def test_a_scope_is_read_from_tools_yaml(tmp_path):
    [server] = servers_from(tmp_path, "    scopes:\n      tv:\n        actions: [read_chapter]\n"
                                      "        records: [chapter, book]\n        files: [audio]\n"
                                      "        uploads: [book]\n")
    assert server.scopes == {"tv": Grant(("read_chapter",), ("chapter", "book"), ("audio",), ("book",))}
    assert servers_from(tmp_path, "")[0].scopes == {}


@pytest.mark.parametrize("scopes, complaint", [
    ("    scopes: [tv]\n", "must name each scope"),
    ("    scopes:\n      TV:\n        actions: [a]\n", "lower-case"),
    ("    scopes:\n      tv: {}\n", "must say what it may use"),
    ("    scopes:\n      tv:\n        action: [a]\n", "only actions, records, files, uploads"),
    ("    scopes:\n      tv:\n        actions: read_chapter\n", "must be a list of plain names"),
    ("    scopes:\n      tv:\n        records: [../chapter]\n", "must be a list of plain names"),
    ("    scopes:\n      tv:\n        files: [[audio]]\n", "must be a list of plain names"),
])
def test_a_mistake_in_a_scope_stops_the_server_starting(tmp_path, scopes, complaint):
    with pytest.raises(ValueError, match=complaint):
        servers_from(tmp_path, scopes)


def test_grants_are_added_up_across_tools_by_the_names_the_server_uses(tmp_path):
    registry = ToolRegistry([
        ToolServer(name="meet-ai", command="x", scopes={"tv": Grant(("peek",), ("note",), ("audio",), ("audio",)),
                                                         "other": Grant(("poke",))}),
        ToolServer(name="audiobook", command="x", scopes={"tv": Grant(("read_chapter",), ("chapter",), ("audio",),
                                                                      ("book",))}),
        ToolServer(name="mail-ai", command="x"),
    ])
    tv = registry.grants("tv")
    assert tv.actions == {"meet_ai__peek", "audiobook__read_chapter"}  # as qualified names are written
    assert tv.records == {"meet_ai": {"note"}, "audiobook": {"chapter"}}
    assert tv.uploads == {"audio", "book"}
    assert registry.grants("other").actions == {"meet_ai__poke"} and not registry.grants("nobody")


def test_the_real_tools_yaml_grants_the_tv_only_what_it_plays_with(tmp_path):
    from assistant.server import ROOT
    registry = ToolRegistry(load_tool_servers(ROOT / "tools.yaml"))
    tv = registry.grants("tv")
    assert tv.actions == {"audiobook__preview_book", "audiobook__read_chapter"}
    assert tv.records == {"audiobook": {"chapter", "book"}} and tv.files == {"audiobook": {"audio"}}
    assert tv.uploads == {"book"}  # no voice, sample, job, meeting, document or mail
