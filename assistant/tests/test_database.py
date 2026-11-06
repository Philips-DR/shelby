"""Tests for the stores behind DATABASE_URL, and for moving the old files into it.

Most run with no database: the file and in-memory stores, and the parts of the import that only read
a file. The rest need a real PostgreSQL and are skipped unless TEST_DATABASE_URL names a server they
may create databases on -- each test makes a new, empty one and drops it, so point it at a throwaway
server, never at data you care about:

    docker run --rm -d -p 127.0.0.1:55432:5432 -e POSTGRES_PASSWORD=test postgres:16-alpine
    TEST_DATABASE_URL=postgres://postgres:test@127.0.0.1:55432/postgres pytest tests/test_database.py
"""

import asyncio
import json
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest

from assistant import db as database_module
from assistant.audit import SUMMARY_LIMIT, FileAuditStore, PgAuditStore
from assistant.auth import MemorySessionStore, PgSessionStore
from assistant.conversations import ConversationStore
from assistant.db import Database, _audit_rows, _fact_rows, _retire, migrate
from assistant.memory import FileMemoryStore, PgMemoryStore
from assistant.server import Hub, create_app
from assistant.setup import stores_for
from assistant.tools import ToolRegistry

ADMIN_URL = os.environ.get("TEST_DATABASE_URL")
needs_postgres = pytest.mark.skipif(not ADMIN_URL, reason="set TEST_DATABASE_URL to a throwaway PostgreSQL")

TOKEN = "test-token"
AUTH = {"x-assistant-token": TOKEN}


def run(coro):
    return asyncio.run(coro)


@asynccontextmanager
async def scratch_database():
    """The URL of a new, empty database on the server TEST_DATABASE_URL names; dropped afterwards."""
    import asyncpg

    name = "test_" + uuid.uuid4().hex[:12]
    admin = await asyncpg.connect(ADMIN_URL)
    await admin.execute(f'CREATE DATABASE "{name}"')
    try:
        yield urlsplit(ADMIN_URL)._replace(path=f"/{name}").geturl()
    finally:
        await admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
        await admin.close()


# ---------------------------------------------------------------------------
# No database needed
# ---------------------------------------------------------------------------

def test_with_no_database_the_stores_are_the_files(tmp_path):
    memory, audit = stores_for(None, tmp_path / "memory.json", tmp_path / "audit.jsonl")
    assert isinstance(memory, FileMemoryStore) and isinstance(audit, FileAuditStore)


def test_with_a_database_the_stores_are_its_tables_and_nothing_connects_yet(tmp_path):
    memory, audit = stores_for(Database("postgres://nobody@nowhere/none"), tmp_path / "m.json", tmp_path / "a.jsonl")
    assert isinstance(memory, PgMemoryStore) and isinstance(audit, PgAuditStore)


def test_a_tool_is_not_started_with_the_database_address(monkeypatch):
    """A tool inherits the backend's environment. With the database address in it, a tool could read
    memory, which no tool may."""
    from assistant.tools import tool_environment

    monkeypatch.setenv("DATABASE_URL", "postgres://suite:secret@postgres:5432/suite")
    monkeypatch.setenv("MEET_AI_AUDIO", "/data/meet-ai/audio")
    env = tool_environment({"MAIL_AI_STORE": "/data/mail-ai/mailbox.sqlite3"})
    assert "DATABASE_URL" not in env
    assert env["MEET_AI_AUDIO"] == "/data/meet-ai/audio" and env["MAIL_AI_STORE"] == "/data/mail-ai/mailbox.sqlite3"


def test_a_store_used_before_the_database_is_connected_says_so():
    with pytest.raises(RuntimeError, match="not connected"):
        Database("postgres://nobody@nowhere/none").pool


def test_the_audit_file_reads_back_newest_first_with_each_servers_last_call(tmp_path):
    audit = FileAuditStore(tmp_path / "audit.jsonl")

    async def scenario():
        await audit.record(tool="docu_ai__build", outcome="ok")
        await audit.record(tool="mail_ai__sync", outcome="ok")
        await audit.record(tool="docu_ai__build", outcome="failed", error="invalid_grant")
        return await audit.recent(2), await audit.last_by_server()

    recent, last = run(scenario())
    assert [r["tool"] for r in recent] == ["docu_ai__build", "mail_ai__sync"]
    assert recent[0]["outcome"] == "failed"
    assert {server: row["outcome"] for server, row in last.items()} == {"docu_ai": "failed", "mail_ai": "ok"}


def test_a_session_lasts_until_it_is_deleted_or_expires():
    sessions = MemorySessionStore()

    async def scenario():
        sid = await sessions.create("me@example.com")
        known = (await sessions.get(sid)).email
        await sessions.delete(sid)
        gone = await sessions.get(sid)
        expired = await sessions.create("me@example.com")
        sessions._sessions[expired].expires_at = time.time() - 1
        return known, gone, await sessions.get(expired), await sessions.get("never-issued")

    known, gone, expired, unknown = run(scenario())
    assert known == "me@example.com"
    assert gone is None and expired is None and unknown is None


def test_a_pending_sign_in_is_used_once():
    sessions = MemorySessionStore()
    sessions.save_pending("state", "verifier", "http://localhost:8751")
    assert sessions.pop_pending("state") == ("verifier", "http://localhost:8751")
    assert sessions.pop_pending("state") is None


def test_a_turn_goes_ahead_with_the_old_context_when_memory_cannot_be_read(tmp_path, monkeypatch):
    """Memory failing degrades what the assistant knows, never whether it runs."""
    import assistant.server as server

    seen = []

    async def recording_turn(*_args, context="", **_kwargs):
        seen.append(context)
    monkeypatch.setattr(server, "run_turn", recording_turn)

    async def broken():
        raise ConnectionError("the database went away")

    hub = Hub(ToolRegistry([]), config=None, context="what it knew at startup",
              audit=FileAuditStore(tmp_path / "a.jsonl"), refresh_context=broken)
    run(hub.run("hello"))
    assert seen == ["what it knew at startup"]
    assert hub.history[-1]["type"] != "turn_error"


def test_the_import_reads_facts_and_keeps_one_with_a_kind_the_database_would_refuse(tmp_path):
    path = tmp_path / "memory.json"
    path.write_text(json.dumps({"facts": [
        {"id": "a1", "kind": "person", "subject": "Kwame", "content": "colleague", "created": "2026-09-21"},
        {"id": "b2", "kind": "hobby", "subject": "chess", "content": "plays", "created": "not a date"},
        {"id": "c3", "kind": "fact", "content": "no subject"},
    ]}), encoding="utf-8")
    rows = _fact_rows(path)
    assert [r[0] for r in rows] == ["a1", "b2"]
    assert rows[0][4] == date(2026, 9, 21)
    assert rows[1][1] == "fact" and rows[1][4] == date.today()


def test_the_import_skips_a_corrupt_audit_line_and_counts_it(tmp_path):
    path = tmp_path / "audit.jsonl"
    path.write_text(
        json.dumps({"at": "2026-10-01T10:00:00+00:00", "tool": "a__b", "outcome": "ok", "arguments": "{}"}) + "\n"
        "not json\n"
        + json.dumps({"tool": "no time", "outcome": "ok"}) + "\n",
        encoding="utf-8")
    rows, skipped = _audit_rows(path)
    assert len(rows) == 1 and skipped == 2
    assert rows[0][0] == datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)


def test_a_file_is_renamed_out_of_the_way_without_overwriting_an_earlier_one(tmp_path):
    first = tmp_path / "memory.json"
    first.write_text("one")
    _retire(first)
    first.write_text("two")
    _retire(first)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["memory.json.imported", "memory.json.imported.2"]
    assert (tmp_path / "memory.json.imported").read_text() == "one"


# ---------------------------------------------------------------------------
# A real PostgreSQL
# ---------------------------------------------------------------------------

@needs_postgres
def test_migrations_apply_once_in_order_and_a_failing_one_leaves_nothing_behind(tmp_path):
    (tmp_path / "001_a.sql").write_text("CREATE TABLE a (n INT);")
    (tmp_path / "002_b.sql").write_text("CREATE TABLE b (n INT);")

    async def scenario():
        async with scratch_database() as url:
            database = Database(url)
            await database.connect()  # the real schema
            pool = database.pool
            first = await migrate(pool, tmp_path)
            again = await migrate(pool, tmp_path)
            (tmp_path / "003_bad.sql").write_text("CREATE TABLE c (n INT); SELECT * FROM does_not_exist;")
            with pytest.raises(Exception):
                await migrate(pool, tmp_path)
            c_exists = await pool.fetchval("SELECT to_regclass('c') IS NOT NULL")
            recorded = [r["name"] for r in await pool.fetch("SELECT name FROM migrations ORDER BY name")]
            await database.close()
            return first, again, c_exists, recorded

    first, again, c_exists, recorded = run(scenario())
    assert first == ["001_a.sql", "002_b.sql"] and again == []
    assert c_exists is False  # the failed file was rolled back whole
    assert recorded == ["001_a.sql", "001_initial.sql", "002_b.sql", "002_files.sql", "003_file_texts.sql",
                        "004_records.sql", "005_conversations.sql", "006_conversation_messages.sql"]


@needs_postgres
def test_memory_in_the_database_behaves_as_the_file_does(tmp_path):
    """The same scenario against both stores: what one does, the other must."""
    async def scenario(store):
        kwame = await store.add("person", "Kwame", "colleague")
        await store.add("person", "kwame", "colleague, leads claims")  # a correction, whatever the case
        await store.add("spelling", "Kwame", "Quami")                  # another kind: another fact
        await store.add("spelling", "Ayé", "Aye")
        await store.add("spelling", "AYÉ", "Ayeh")                     # non-ASCII is the same subject too
        with pytest.raises(ValueError):
            await store.add("nonsense", "x", "y")
        facts = await store.load()
        removed = await store.remove(facts[0].id)
        block = re.sub(r"\[[0-9a-f]{8}\]", "[id]", await store.as_prompt_block())  # ids are random
        return (kwame, [(f.kind, f.subject, f.content) for f in facts], removed.content,
                await store.remove("nope"), await store.lexicon(), block)

    async def against_the_database():
        async with scratch_database() as url:
            async with Database(url) as database:
                return await scenario(PgMemoryStore(database))

    in_file = run(scenario(FileMemoryStore(tmp_path / "memory.json")))
    in_database = run(against_the_database())
    assert in_database[1:] == in_file[1:]
    assert in_database[1] == [("person", "kwame", "colleague, leads claims"), ("spelling", "Kwame", "Quami"),
                              ("spelling", "AYÉ", "Ayeh")]
    assert in_database[0].created == date.today().isoformat()


@needs_postgres
def test_facts_come_back_in_the_order_they_were_written(tmp_path):
    async def scenario():
        async with scratch_database() as url:
            async with Database(url) as database:
                store = PgMemoryStore(database)
                for n in range(8):
                    await store.add("fact", f"subject {n}", "c")
                return [f.subject for f in await store.load()]

    assert run(scenario()) == [f"subject {n}" for n in range(8)]


@needs_postgres
def test_the_audit_log_in_the_database_reads_back_as_the_file_does(tmp_path):
    async def scenario(audit):
        await audit.record(tool="docu_ai__build", arguments={"a": 1}, outcome="ok", error=None,
                           duration_ms=120, result="x" * (SUMMARY_LIMIT * 3), origin="chat")
        await audit.record(tool="mail_ai__send_draft", arguments={"draft": "d1"}, outcome="declined", origin="chat")
        await audit.record(tool="docu_ai__build", outcome="failed", error="invalid_grant", duration_ms=5)
        return await audit.recent(10), await audit.last_by_server()

    async def against_the_database():
        async with scratch_database() as url:
            async with Database(url) as database:
                return await scenario(PgAuditStore(database))

    file_recent, file_last = run(scenario(FileAuditStore(tmp_path / "audit.jsonl")))
    pg_recent, pg_last = run(against_the_database())

    def shape(rows):  # what each row says, without the clock or the empty fields the file keeps as null
        return [{k: v for k, v in r.items() if k != "at" and v is not None} for r in rows]

    assert shape(pg_recent) == shape(file_recent)
    assert [r["outcome"] for r in pg_recent] == ["failed", "declined", "ok"]
    assert len(pg_recent[2]["result"]) == SUMMARY_LIMIT
    assert pg_recent[1]["origin"] == "chat" and "duration_ms" not in pg_recent[1]
    assert {s: r["outcome"] for s, r in pg_last.items()} == {s: r["outcome"] for s, r in file_last.items()}
    assert datetime.fromisoformat(pg_recent[0]["at"]).utcoffset().total_seconds() == 0


@needs_postgres
def test_a_broken_audit_log_never_breaks_the_work():
    async def scenario():
        async with scratch_database() as url:
            database = Database(url)
            await database.connect()
            audit = PgAuditStore(database)
            await database.close()  # the database goes away under it
            await audit.record(tool="a", outcome="ok")
            return await audit.recent(10), await audit.last_by_server()

    assert run(scenario()) == ([], {})


@needs_postgres
def test_a_session_in_the_database_survives_a_restart_and_expires():
    async def scenario():
        async with scratch_database() as url:
            async with Database(url) as database:
                sid = await PgSessionStore(database).create("me@example.com")
                expired = await PgSessionStore(database).create("old@example.com")
                await database.pool.execute("UPDATE sessions SET expires_at = now() - interval '1 second' WHERE sid = $1", expired)
            async with Database(url) as database:  # the backend restarted
                sessions = PgSessionStore(database)
                kept = await sessions.get(sid)
                gone_expired = await sessions.get(expired)
                await sessions.delete(sid)
                deleted = await sessions.get(sid)
                await sessions.create("another@example.com")  # sweeps what has expired
                swept = await database.pool.fetchval("SELECT count(*) FROM sessions WHERE sid = $1", expired)
                return kept, gone_expired, deleted, swept

    kept, expired, deleted, swept = run(scenario())
    assert kept.email == "me@example.com" and kept.expires_at > time.time()
    assert expired is None and deleted is None and swept == 0


@needs_postgres
def test_the_old_files_are_imported_once_and_renamed(tmp_path):
    memory, audit = tmp_path / "memory.json", tmp_path / "audit.jsonl"
    memory.write_text(json.dumps({"version": 1, "facts": [
        {"id": "a1", "kind": "person", "subject": "Kwame", "content": "colleague", "created": "2026-09-21"},
        {"id": "b2", "kind": "spelling", "subject": "Accra", "content": "Akra", "created": "2026-10-15"},
    ]}), encoding="utf-8")
    audit.write_text("".join(
        json.dumps({"at": f"2026-10-0{n}T10:00:00+00:00", "tool": "docu_ai__build", "arguments": "{}",
                    "outcome": "ok", "error": None, "duration_ms": n, "result": "r", "origin": "button"}) + "\n"
        for n in range(1, 4)) + "not json\n", encoding="utf-8")

    async def scenario():
        async with scratch_database() as url:
            async with Database(url, legacy_memory=memory, legacy_audit=audit) as database:
                first = dict(database.imported)
                facts = [(f.id, f.kind, f.subject, f.content, f.created) for f in await PgMemoryStore(database).load()]
                rows = await PgAuditStore(database).recent(10)
            # A start with the files gone does nothing more; a start with them put back merges, never doubles.
            (tmp_path / "memory.json.imported").rename(memory)
            (tmp_path / "audit.jsonl.imported").rename(audit)
            async with Database(url, legacy_memory=memory, legacy_audit=audit) as database:
                second = dict(database.imported)
                counts = (await database.pool.fetchval("SELECT count(*) FROM facts"),
                          await database.pool.fetchval("SELECT count(*) FROM audit_log"))
            return first, facts, rows, second, counts

    first, facts, rows, second, counts = run(scenario())
    assert first == {"facts": 2, "audit": 3, "audit_skipped": 1}
    assert facts == [("a1", "person", "Kwame", "colleague", "2026-09-21"),
                     ("b2", "spelling", "Accra", "Akra", "2026-10-15")]
    assert [r["duration_ms"] for r in rows] == [3, 2, 1]  # newest first, the times kept
    assert rows[0]["at"] == "2026-10-03T10:00:00+00:00"
    assert second == {"facts": 0}  # the facts merged by id; the audit table was not empty, so its file was left alone
    assert counts == (2, 3)
    assert audit.exists() and not memory.exists()


@needs_postgres
def test_the_app_keeps_memory_history_and_sessions_across_a_restart(tmp_path):
    """The whole path: a fact remembered through the API, a second app on the same database."""
    def app_on(url):
        return create_app(
            tmp_path / "tools.yaml", tmp_path / "memory.json", tmp_path / "audit.jsonl", token=TOKEN,
            registry_factory=lambda local: ToolRegistry([], local=local), watch_jobs=False,
            database_url=url)

    async def with_client(app, body):
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8750") as client:
                return await body(client)

    async def scenario():
        async with scratch_database() as url:
            async def first(client):
                await client.post("/api/actions", headers=AUTH, json={
                    "tool": "assistant__remember",
                    "arguments": {"kind": "spelling", "subject": "Accra", "content": "Akra"}})

            async def second(client):
                recalled = (await client.post("/api/actions", headers=AUTH, json={"tool": "assistant__recall"})).json()
                history = (await client.get("/api/history", headers=AUTH)).json()
                return recalled["output"]["facts"], history

            await with_client(app_on(url), first)
            return await with_client(app_on(url), second)

    facts, history = run(scenario())
    assert [(f["kind"], f["subject"], f["content"]) for f in facts] == [("spelling", "Accra", "Akra")]
    assert [(r["tool"], r["outcome"], r["origin"]) for r in history] == [("assistant__remember", "ok", "button")]
    assert json.loads((tmp_path / "lexicon.json").read_text()) == {"Accra": ["Akra"]}
    assert not (tmp_path / "memory.json").exists()  # nothing was written to the old file


@needs_postgres
def test_conversations_are_kept_listed_newest_first_renamed_and_deleted_in_the_database():
    a, b = "a" * 32, "b" * 32

    async def scenario():
        async with scratch_database() as url:
            async with Database(url) as database:
                store = ConversationStore(database)
                await store.save(a, "First", [{"type": "user_message", "text": "hi"}], 1)
                await store.save(b, "Second", [{"type": "user_message", "text": "yo"}], 1)
                # Saved again after a later turn: the same row, now the newest.
                await store.save(a, "First", [{"type": "user_message", "text": "hi"},
                                               {"type": "turn_done", "text": "hello"}], 1)
                listed = [c["id"] for c in await store.list()]
                events = (await store.get(a))["events"]
                renamed = (await store.rename(b, "Renamed"), await store.rename("c" * 32, "x"))
                deleted = (await store.delete(a), await store.delete(a))
                left = [(c["id"], c["title"]) for c in await store.list()]
                with pytest.raises(Exception):
                    await store.save("not-an-id", "x", [], 0)  # the table takes only the ids it makes
                # What the model remembers goes in and comes back; a conversation kept without it says so.
                remembered = [{"role": "user", "content": "hi"},
                              {"role": "assistant", "content": [{"type": "thinking", "thinking": "t", "signature": "s"}]}]
                await store.save(b, "Renamed", [{"type": "user_message", "text": "yo"}], 1, remembered)
                assert (await store.get(b))["messages"] == remembered
                await store.save(b, "Renamed", [{"type": "user_message", "text": "yo"}], 1)
                assert (await store.get(b))["messages"] is None
                return listed, events, renamed, deleted, left

    listed, events, renamed, deleted, left = run(scenario())
    assert listed == [a, b]
    assert [e["type"] for e in events] == ["user_message", "turn_done"]
    assert renamed == (True, False) and deleted == (True, False)
    assert left == [(b, "Renamed")]
