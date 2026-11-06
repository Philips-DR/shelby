"""Tests for the web server.

The real app, in-process, with a registry holding only the built-in memory tools: no child
processes, no model, no network. The security tests come first, because this process can
send email as you.
"""

import asyncio
import json

import httpx
import pytest

from assistant.audit import FileAuditStore
from assistant.server import Hub, create_app
from assistant.session import ApprovalRequest
from assistant.tools import ApprovalPreview, RemoteTool, ToolRegistry

TOKEN = "test-token"
AUTH = {"x-assistant-token": TOKEN}


def app_for(tmp_path, **kwargs):
    kwargs.setdefault("files_path", tmp_path / "files")  # never the real store beside the code
    kwargs.setdefault("texts_path", tmp_path / "texts")
    return create_app(
        tmp_path / "tools.yaml", tmp_path / "memory.json", tmp_path / "audit.jsonl",
        token=TOKEN,
        registry_factory=lambda local: ToolRegistry([], local=local),
        watch_jobs=False,
        **kwargs,
    )


async def with_client(app, body):
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8750") as client:
            return await body(client)


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

def test_the_api_refuses_a_request_without_the_token(tmp_path):
    async def body(client):
        return (await client.get("/api/tools")).status_code
    assert run(with_client(app_for(tmp_path), body)) == 401


def test_the_api_refuses_a_wrong_token(tmp_path):
    async def body(client):
        return (await client.get("/api/tools", headers={"x-assistant-token": "guess"})).status_code
    assert run(with_client(app_for(tmp_path), body)) == 401


def test_a_request_for_another_host_is_refused(tmp_path):
    """DNS rebinding: a hostile name that resolves to 127.0.0.1 still says so in Host."""
    async def body(client):
        return (await client.get("/api/tools", headers={**AUTH, "host": "evil.example"})).status_code
    assert run(with_client(app_for(tmp_path), body)) == 403


def test_the_token_is_only_accepted_in_a_url_for_the_event_stream(tmp_path):
    """EventSource cannot send headers. Everywhere else a token in a URL would end up in
    logs and history, so it is refused there."""
    async def body(client):
        return (await client.get(f"/api/tools?token={TOKEN}")).status_code
    assert run(with_client(app_for(tmp_path), body)) == 401


# ---------------------------------------------------------------------------
# Buttons
# ---------------------------------------------------------------------------

def test_the_tool_list_is_available_to_the_interface(tmp_path):
    async def body(client):
        return (await client.get("/api/tools", headers=AUTH)).json()
    names = {t["qualified_name"] for t in run(with_client(app_for(tmp_path), body))}
    assert {"assistant__remember", "assistant__forget"} <= names


def test_a_button_that_changes_something_is_noted_for_the_model(tmp_path):
    """The mode switch only works if buttons and chat share one state. Something done
    with a button must reach the model with the next message."""
    async def body(client):
        done = await client.post("/api/actions", headers=AUTH, json={
            "tool": "assistant__remember",
            "arguments": {"kind": "fact", "subject": "office", "content": "Accra"},
        })
        state = (await client.get("/api/state", headers=AUTH)).json()
        return done.json(), state["notes"]
    result, notes = run(with_client(app_for(tmp_path), body))
    assert result["outcome"] == "ok"
    assert len(notes) == 1 and "remember" in notes[0]


def test_a_button_for_an_unknown_tool_is_refused(tmp_path):
    async def body(client):
        return (await client.post("/api/actions", headers=AUTH, json={"tool": "nope"})).status_code
    assert run(with_client(app_for(tmp_path), body)) == 404


def test_a_button_for_a_tool_with_a_preview_confirms_before_acting(tmp_path):
    """Pressing Send must show the email first. The click is the approval for most
    buttons -- not for the ones whose effect cannot be seen from their arguments."""
    from assistant.tools import ToolOutcome

    app = app_for(tmp_path)
    sent = []

    async def scenario():
        async with app.router.lifespan_context(app):
            hub = app.state.hub
            hub.registry.tools.append(RemoteTool(
                server="mail_ai", name="send_draft", qualified_name="mail_ai__send_draft",
                description="", input_schema={}, read_only=False,
                preview=ApprovalPreview("review_draft", {"draft_id": "draft_id"}, "rendered"),
            ))

            async def fake_preview(tool, arguments):
                return "To: kwame@example.com\n\nTuesday works."

            async def fake_call(tool, arguments):
                sent.append(arguments)
                return ToolOutcome(text="{}", is_error=False)

            hub.registry.preview_of = fake_preview
            hub.registry.call = fake_call

            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8750") as client:
                first = (await client.post("/api/actions", headers=AUTH, json={
                    "tool": "mail_ai__send_draft", "arguments": {"draft_id": "d1"}})).json()
                assert sent == []  # nothing sent on the first press
                second = (await client.post("/api/actions", headers=AUTH, json={
                    "tool": "mail_ai__send_draft", "arguments": {"draft_id": "d1"},
                    "confirmed": True})).json()
                return first, second

    first, second = run(scenario())
    assert first["needs_confirmation"] is True
    assert "kwame@example.com" in first["preview"]
    assert second["outcome"] == "ok"
    assert sent == [{"draft_id": "d1"}]


# ---------------------------------------------------------------------------
# The chat gate, suspended on a click
# ---------------------------------------------------------------------------

def test_the_gate_suspends_until_the_browser_answers(tmp_path):
    async def scenario():
        hub = Hub(ToolRegistry([]), config=None, context="", audit=FileAuditStore(tmp_path / "a.jsonl"))
        tool = RemoteTool(server="s", name="t", qualified_name="s__t", description="",
                          input_schema={}, read_only=False)
        request = ApprovalRequest(tool=tool, arguments={"x": 1}, preview=None, preview_expected=False)
        waiting = asyncio.create_task(hub.web_gate(request))
        await asyncio.sleep(0.05)
        assert not waiting.done()  # the turn is parked, not blocked on a terminal
        assert request.id in hub.pending
        hub.pending[request.id][1].set_result(True)
        return await waiting, hub

    approved, hub = run(scenario())
    assert approved is True
    assert hub.pending == {}
    assert any(e["type"] == "approval_needed" for e in hub.history)


def test_answering_an_approval_that_does_not_exist_is_a_404(tmp_path):
    async def body(client):
        return (await client.post("/api/approvals/nope", headers=AUTH, json={"approve": True})).status_code
    assert run(with_client(app_for(tmp_path), body)) == 404


# ---------------------------------------------------------------------------
# One conversation
# ---------------------------------------------------------------------------

def test_notes_reach_the_model_with_the_next_message_and_only_once(tmp_path):
    hub = Hub(ToolRegistry([]), config=None, context="", audit=FileAuditStore(tmp_path / "a.jsonl"))
    hub.notes.append("meet_ai.stop_recording({}) -> ok: audio/x.flac")
    first = hub.compose("write it up")
    assert "audio/x.flac" in first and first.endswith("write it up")
    assert hub.compose("and again") == "and again"


def test_a_failed_turn_rolls_the_conversation_back_and_keeps_the_notes(tmp_path, monkeypatch):
    """A turn that dies mid-way can leave a tool call without its result, which poisons
    every later turn. Roll back to before it; what the user did with buttons is not lost."""
    import assistant.server as server

    async def exploding_turn(*_args, **_kwargs):
        raise RuntimeError("model unreachable")
    monkeypatch.setattr(server, "run_turn", exploding_turn)

    hub = Hub(ToolRegistry([]), config=None, context="", audit=FileAuditStore(tmp_path / "a.jsonl"))
    hub.notes.append("did something")
    run(hub.run("hello"))

    assert hub.messages == []
    assert hub.notes == ["did something"]
    assert hub.history[-1]["type"] == "turn_error"



def test_memory_written_mid_session_reaches_the_next_turn(tmp_path, monkeypatch):
    """The server runs for days. A fact remembered in one turn must be in the model's
    context on the next -- found when a live test remembered a preference and the running
    server kept sending the context it had loaded at startup."""
    import assistant.server as server

    seen = []

    async def recording_turn(*_args, context="", **_kwargs):
        seen.append(context)
    monkeypatch.setattr(server, "run_turn", recording_turn)

    fresh = iter(["old context", "context with the new fact"])

    async def refresh():
        return next(fresh)
    hub = Hub(ToolRegistry([]), config=None, context="startup", audit=FileAuditStore(tmp_path / "a.jsonl"),
              refresh_context=refresh)
    run(hub.run("first"))
    run(hub.run("second"))
    assert seen == ["old context", "context with the new fact"]


def test_history_reads_the_audit_log_newest_first_and_skips_corrupt_lines(tmp_path):
    (tmp_path / "audit.jsonl").write_text(
        '{"tool": "a", "outcome": "ok"}\nnot json\n{"tool": "b", "outcome": "failed"}\n',
        encoding="utf-8")

    async def body(client):
        return (await client.get("/api/history", headers=AUTH)).json()
    rows = run(with_client(app_for(tmp_path), body))
    assert [r["tool"] for r in rows] == ["b", "a"]


def test_a_read_from_the_interface_is_not_audited_but_a_change_is(tmp_path):
    """The panels poll every few seconds. Auditing each poll flooded the log -- found by
    opening the History page and seeing nothing but "recording status: ok"."""
    import json as _json

    async def body(client):
        await client.post("/api/actions", headers=AUTH, json={"tool": "assistant__recall"})
        await client.post("/api/actions", headers=AUTH, json={
            "tool": "assistant__remember",
            "arguments": {"kind": "fact", "subject": "s", "content": "c"}})
        return None
    run(with_client(app_for(tmp_path), body))
    rows = [_json.loads(l) for l in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert [r["tool"] for r in rows] == ["assistant__remember"]


def test_a_button_gets_the_same_spelling_corrections_chat_does(tmp_path):
    """Chat is told the lexicon's path and passes it on. A button has no model to tell, so
    until the server filled it in, a spelling taught to the assistant corrected transcripts
    written up from chat and silently not the ones written up from a button."""
    import json
    from assistant.tools import LocalTool

    async def echo_arguments(arguments):
        return json.dumps(arguments)

    echo = LocalTool(
        name="echo", description="Returns its arguments.",
        input_schema={"type": "object", "properties": {"lexicon": {"type": "string"}}},
        read_only=True, handler=echo_arguments,
    )
    app = create_app(
        tmp_path / "tools.yaml", tmp_path / "memory.json", tmp_path / "audit.jsonl", token=TOKEN,
        registry_factory=lambda local: ToolRegistry([], local=[*local, echo]), watch_jobs=False,
    )

    async def body(client):
        before = (await client.post("/api/actions", headers=AUTH, json={"tool": "assistant__echo", "arguments": {}})).json()
        await client.post("/api/actions", headers=AUTH, json={
            "tool": "assistant__remember",
            "arguments": {"kind": "spelling", "subject": "Accra", "content": "Akra"}})
        after = (await client.post("/api/actions", headers=AUTH, json={"tool": "assistant__echo", "arguments": {}})).json()
        return before, after

    before, after = run(with_client(app, body))
    assert "lexicon" not in before["output"]  # nothing taught yet, nothing to pass
    lexicon = after["output"]["lexicon"]
    assert json.loads(open(lexicon).read()) == {"Accra": ["Akra"]}



def test_the_server_runs_what_tools_yaml_schedules_with_no_page_open(tmp_path):
    """Mail was synced by a timer in the page, so a closed tab left the mailbox five days stale. The server runs
    it now: once at start, audited as the schedule's, and never shown in the chat or noted for the model."""
    from assistant.tools import LocalTool

    calls: list[dict] = []

    async def tick(arguments):
        calls.append(arguments)
        return '{"added": 0}'

    sync = LocalTool(name="tick", description="Stands in for a sync.", input_schema={"type": "object"},
                     read_only=False, handler=tick)

    class Scheduled(ToolRegistry):
        @property
        def schedules(self):
            return [("mail-ai", "assistant__tick", 3600)]

    app = create_app(
        tmp_path / "tools.yaml", tmp_path / "memory.json", tmp_path / "audit.jsonl", token=TOKEN,
        registry_factory=lambda local: Scheduled([], local=[*local, sync]), watch_jobs=False,
    )

    async def body(client):
        for _ in range(100):
            if calls:
                break
            await asyncio.sleep(0.01)
        return (await client.get("/api/state", headers=AUTH)).json()

    state = run(with_client(app, body))
    assert calls == [{}]
    rows = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert [(r["tool"], r["origin"], r["outcome"]) for r in rows] == [("assistant__tick", "schedule", "ok")]
    assert not [e for e in state["history"] if e["type"].startswith("tool_")]
    assert state["notes"] == []


def test_status_reports_tools_from_the_audit_without_touching_the_network(tmp_path):
    """Settings opens instantly: no live check unless asked for."""
    import json
    (tmp_path / "audit.jsonl").write_text(
        json.dumps({"at": "t1", "tool": "assistant__remember", "outcome": "ok"}) + "\n")

    async def body(client):
        return (await client.get("/api/status", headers=AUTH)).json()

    status = run(with_client(app_for(tmp_path), body))
    assert "network" not in status  # not live
    assert status["model"]["model"]
    assert status["mail_compose"] is False
    assert status["tools"] == []  # only the built-in memory tools, which are not a server


# ---------------------------------------------------------------------------
# A separate web app
# ---------------------------------------------------------------------------

WEB = "http://127.0.0.1:8751"


def test_the_server_is_an_api_and_serves_no_page(tmp_path):
    """The web app is its own program now. This server must not hand out a page, and above
    all must not hand out the token inside one."""
    async def body(client):
        return (await client.get("/")).json()
    root = run(with_client(app_for(tmp_path), body))
    assert root == {"service": "assistant", "api": "/api"}
    assert TOKEN not in str(root)


def test_the_web_app_may_call_across_origins_with_its_token(tmp_path):
    async def body(client):
        preflight = await client.options("/api/tools", headers={
            "origin": WEB, "access-control-request-method": "GET",
            "access-control-request-headers": "x-assistant-token"})
        call = await client.get("/api/tools", headers={**AUTH, "origin": WEB})
        return preflight, call
    preflight, call = run(with_client(app_for(tmp_path), body))
    # The preflight carries no token and must still be answered, or no call can follow it.
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == WEB
    assert call.status_code == 200 and call.headers["access-control-allow-origin"] == WEB


def test_a_wrong_token_is_still_readable_as_a_401_by_the_web_app(tmp_path):
    """Without CORS headers on the refusal, the browser hides the status and the app cannot
    tell 'paste the new token' from 'the server is down'."""
    async def body(client):
        return await client.get("/api/tools", headers={"x-assistant-token": "old", "origin": WEB})
    refused = run(with_client(app_for(tmp_path), body))
    assert refused.status_code == 401
    assert refused.headers["access-control-allow-origin"] == WEB


def test_a_page_from_anywhere_else_cannot_read_responses(tmp_path):
    async def body(client):
        return await client.get("/api/tools", headers={**AUTH, "origin": "http://evil.example"})
    response = run(with_client(app_for(tmp_path), body))
    assert "access-control-allow-origin" not in response.headers


def test_the_browser_approval_shows_a_long_preview_whole(tmp_path):
    """Found live: a tailored CV's approval stopped at 4,000 characters, mid-word -- Skills,
    Education and Certifications never shown to the person approving it. The terminal keeps
    its short limit; the browser's box scrolls, so it gets the whole thing."""
    from assistant.server import approval_view
    from assistant.session import ApprovalRequest
    tool = RemoteTool(server="assistant", name="write_draft", qualified_name="assistant__write_draft",
                      description="", input_schema={}, read_only=False)
    long = "x" * 9000 + "END"
    view = approval_view(ApprovalRequest(id="a1", tool=tool, arguments={}, preview=long, preview_expected=True))
    assert view["preview"].endswith("END") and "truncated" not in view["preview"]


# ---------------------------------------------------------------------------
# Hosts beyond localhost (a Tailscale name), and the one place requests are authenticated
# ---------------------------------------------------------------------------

def test_hosts_are_exact_lowercase_names_never_patterns():
    from assistant.server import parse_hosts
    assert parse_hosts(None) == frozenset() and parse_hosts("") == frozenset()
    assert parse_hosts("Suite.Tail1234.ts.net, backend web") == {"suite.tail1234.ts.net", "backend", "web"}


def test_a_configured_name_may_reach_the_api_and_any_other_may_not(tmp_path):
    from assistant.server import create_app
    app = create_app(tmp_path / "tools.yaml", tmp_path / "memory.json", tmp_path / "audit.jsonl", token=TOKEN,
                     registry_factory=lambda local: ToolRegistry([], local=local), watch_jobs=False,
                     hosts=frozenset({"suite.tail1234.ts.net"}))

    async def body(client):
        got = {}
        for host in ("suite.tail1234.ts.net", "SUITE.tail1234.ts.net:8443", "127.0.0.1:8750", "evil.example", "tail1234.ts.net"):
            got[host] = (await client.get("/api/tools", headers={**AUTH, "host": host})).status_code
        got["right name, no token"] = (await client.get("/api/tools", headers={"host": "suite.tail1234.ts.net"})).status_code
        return got

    got = run(with_client(app, body))
    assert got == {"suite.tail1234.ts.net": 200, "SUITE.tail1234.ts.net:8443": 200, "127.0.0.1:8750": 200,
                   "evil.example": 403, "tail1234.ts.net": 403, "right name, no token": 401}


def test_without_configured_names_only_localhost_is_allowed(tmp_path):
    async def body(client):
        return (await client.get("/api/tools", headers={**AUTH, "host": "suite.tail1234.ts.net"})).status_code
    assert run(with_client(app_for(tmp_path), body)) == 403


# ---------------------------------------------------------------------------
# Clearing the chat
# ---------------------------------------------------------------------------

def test_clearing_the_chat_needs_the_token(tmp_path):
    async def body(client):
        return (await client.post("/api/chat/clear")).status_code
    assert run(with_client(app_for(tmp_path), body)) == 401


def test_clearing_the_chat_forgets_the_conversation_but_keeps_what_other_pages_read(tmp_path):
    app = app_for(tmp_path)

    async def body(client):
        hub = app.state.hub
        hub.messages.extend([{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}])
        hub.notes.append("a button was pressed")
        for event in (
            {"type": "user_message", "text": "hi"},
            {"type": "assistant_text", "text": "hello"},
            {"type": "tool_started", "tool": "x__y", "origin": "chat"},
            {"type": "tool_finished", "tool": "x__y", "origin": "chat", "outcome": "ok"},
            {"type": "turn_done", "text": "hello"},
            {"type": "notice", "title": "Transcription finished"},
            {"type": "upload", "kind": "audio", "name": "a.m4a"},
            {"type": "tool_finished", "tool": "meet_ai__start", "origin": "button", "outcome": "ok", "read_only": False},
        ):
            await hub.emit(event)
        cleared = await client.post("/api/chat/clear", headers=AUTH)
        state = (await client.get("/api/state", headers=AUTH)).json()
        return cleared, state, hub

    cleared, state, hub = run(with_client(app, body))
    assert cleared.status_code == 200 and cleared.json() == {"cleared": 2}
    assert hub.messages == [] and state["notes"] == []
    # What stays is not conversation: a notice, an upload and a button's own result, then the marker that
    # tells every open page to fetch this pruned history.
    assert [e["type"] for e in state["history"]] == ["notice", "upload", "tool_finished", "chat_cleared"]
    assert state["history"][2]["origin"] == "button"
    seqs = [e["seq"] for e in state["history"]]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)  # a page de-duplicates by seq


def test_clearing_the_chat_leaves_memory_alone_and_is_audited(tmp_path):
    async def body(client):
        await client.post("/api/actions", headers=AUTH, json={
            "tool": "assistant__remember", "arguments": {"kind": "fact", "subject": "office", "content": "Accra"}})
        return await client.post("/api/chat/clear", headers=AUTH)

    assert run(with_client(app_for(tmp_path), body)).status_code == 200
    assert "Accra" in (tmp_path / "memory.json").read_text()
    rows = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert (rows[-1]["tool"], rows[-1]["outcome"], rows[-1]["origin"]) == ("assistant__clear_chat", "ok", "button")


def test_the_chat_cannot_be_cleared_while_a_message_is_being_worked_on(tmp_path):
    app = app_for(tmp_path)

    async def body(client):
        hub = app.state.hub
        hub.messages.append({"role": "user", "content": "hi"})
        hub.turn = asyncio.create_task(asyncio.sleep(30))
        try:
            refused = await client.post("/api/chat/clear", headers=AUTH)
        finally:
            hub.turn.cancel()
        return refused, len(hub.messages)

    refused, kept = run(with_client(app, body))
    assert refused.status_code == 409 and kept == 1


def test_the_chat_cannot_be_cleared_while_an_approval_is_waiting(tmp_path):
    app = app_for(tmp_path)

    async def body(client):
        hub = app.state.hub
        hub.messages.append({"role": "user", "content": "hi"})
        hub.pending["a1"] = (object(), asyncio.get_running_loop().create_future())
        refused = await client.post("/api/chat/clear", headers=AUTH)
        return refused, len(hub.messages)

    refused, kept = run(with_client(app, body))
    assert refused.status_code == 409 and kept == 1


# ---------------------------------------------------------------------------
# Conversation history
# ---------------------------------------------------------------------------

class DictConversations:
    """What the routes and the hub ask of a conversation store, held in a dict: no PostgreSQL needed."""

    def __init__(self):
        self.rows = {}

    async def list(self, limit=50):
        return [{k: v for k, v in row.items() if k != "events"} for row in list(self.rows.values())[:limit]]

    async def get(self, conversation_id):
        return self.rows.get(conversation_id)

    async def save(self, conversation_id, title, events, message_count):
        self.rows[conversation_id] = {"id": conversation_id, "title": title, "events": events,
                                      "message_count": message_count, "created_at": "2026-11-06T09:00:00+00:00",
                                      "updated_at": "2026-11-06T09:00:00+00:00"}
        return conversation_id

    async def delete(self, conversation_id):
        return self.rows.pop(conversation_id, None) is not None

    async def rename(self, conversation_id, title):
        if conversation_id not in self.rows:
            return False
        self.rows[conversation_id]["title"] = title
        return True


def test_a_conversation_is_titled_by_its_first_message_cut_at_a_word():
    from assistant.conversations import TITLE_MAX, title_from_message

    assert title_from_message("  What did Kwame say?\n") == "What did Kwame say?"
    assert title_from_message("first line\nsecond line") == "first line second line"
    long = title_from_message("word " * 40)
    assert long.endswith("…") and len(long) <= TITLE_MAX + 1 and not long[:-1].endswith(" ")


def test_clearing_the_chat_keeps_the_conversation_in_history_without_what_was_not_conversation(tmp_path):
    app = app_for(tmp_path)

    async def body(client):
        hub = app.state.hub
        hub.conversations = store = DictConversations()
        hub.conversation_id, hub.conversation_title = "a" * 32, "What did Kwame say?"
        for event in (
            {"type": "user_message", "text": "What did Kwame say?"},
            {"type": "assistant_text", "text": "He agreed."},
            {"type": "turn_done", "text": "He agreed."},
            {"type": "notice", "title": "Transcription finished"},
        ):
            await hub.emit(event)
        cleared = await client.post("/api/chat/clear", headers=AUTH)
        return cleared, store, hub

    cleared, store, hub = run(with_client(app, body))
    assert cleared.status_code == 200
    kept = store.rows["a" * 32]
    assert kept["title"] == "What did Kwame say?" and kept["message_count"] == 1
    assert [e["type"] for e in kept["events"]] == ["user_message", "assistant_text", "turn_done"]
    assert hub.conversation_id is None and hub.conversation_title == ""  # the next message starts a new one


def test_a_conversation_with_no_message_in_it_is_not_kept(tmp_path):
    app = app_for(tmp_path)

    async def body(client):
        hub = app.state.hub
        hub.conversations = store = DictConversations()
        hub.conversation_id = "a" * 32
        await hub.emit({"type": "notice", "title": "Transcription finished"})
        await client.post("/api/chat/clear", headers=AUTH)
        return store

    assert run(with_client(app, body)).rows == {}


def test_past_conversations_are_listed_opened_renamed_and_deleted(tmp_path):
    app = app_for(tmp_path)

    async def body(client):
        hub = app.state.hub
        hub.conversations = store = DictConversations()
        await store.save("a" * 32, "First", [{"type": "user_message", "text": "hi"}], 1)
        listed = (await client.get("/api/conversations", headers=AUTH)).json()
        opened = (await client.get(f"/api/conversations/{'a' * 32}", headers=AUTH)).json()
        empty = await client.patch(f"/api/conversations/{'a' * 32}", headers=AUTH, json={"title": "   "})
        renamed = await client.patch(f"/api/conversations/{'a' * 32}", headers=AUTH, json={"title": " Kwame "})
        title = store.rows["a" * 32]["title"]
        deleted = await client.delete(f"/api/conversations/{'a' * 32}", headers=AUTH)
        return listed, opened, empty.status_code, renamed.status_code, title, deleted.status_code, store.rows

    listed, opened, empty, renamed, title, deleted, left = run(with_client(app, body))
    assert [c["title"] for c in listed] == ["First"] and "events" not in listed[0]  # the list is light
    assert opened["events"] == [{"type": "user_message", "text": "hi"}]
    assert empty == 400 and renamed == 200 and title == "Kwame"
    assert deleted == 200 and left == {}


def test_a_conversation_that_is_not_there_is_a_404_whatever_is_asked_of_it(tmp_path):
    app = app_for(tmp_path)

    async def body(client):
        app.state.hub.conversations = DictConversations()
        missing = f"/api/conversations/{'b' * 32}"
        return [(await client.get(missing, headers=AUTH)).status_code,
                (await client.delete(missing, headers=AUTH)).status_code,
                (await client.patch(missing, headers=AUTH, json={"title": "x"})).status_code]

    assert run(with_client(app, body)) == [404, 404, 404]


def test_with_no_database_there_is_no_history_and_nothing_fails(tmp_path):
    async def body(client):
        return ((await client.get("/api/conversations", headers=AUTH)).json(),
                (await client.get(f"/api/conversations/{'a' * 32}", headers=AUTH)).status_code)

    assert run(with_client(app_for(tmp_path), body)) == ([], 404)


def test_conversation_history_needs_the_token(tmp_path):
    async def body(client):
        return [(await client.get("/api/conversations")).status_code,
                (await client.delete(f"/api/conversations/{'a' * 32}")).status_code]

    assert run(with_client(app_for(tmp_path), body)) == [401, 401]


def test_deleting_the_conversation_chat_is_in_empties_chat_and_it_does_not_come_back(tmp_path):
    """Found in Chrome: deleted from the list while still open, the next message saved it again with its old title
    and the deleted messages."""
    app = app_for(tmp_path)

    async def body(client):
        hub = app.state.hub
        hub.conversations = store = DictConversations()
        hub.conversation_id, hub.conversation_title = "a" * 32, "Kwame"
        hub.messages.append({"role": "user", "content": "Kwame?"})
        await hub.emit({"type": "user_message", "text": "Kwame?"})
        await hub.save_conversation()
        deleted = await client.delete(f"/api/conversations/{'a' * 32}", headers=AUTH)
        await hub.save_conversation()  # what the next turn does on its way out
        return deleted.json(), store.rows, hub

    deleted, rows, hub = run(with_client(app, body))
    assert deleted == {"deleted": True, "cleared": True}
    assert rows == {} and hub.messages == [] and hub.conversation_id is None
    audit = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert (audit[-1]["tool"], audit[-1]["origin"]) == ("assistant__delete_conversation", "button")
    assert "Kwame" in audit[-1]["result"] and "Chat cleared" in audit[-1]["result"]


def test_deleting_an_older_conversation_leaves_chat_alone(tmp_path):
    app = app_for(tmp_path)

    async def body(client):
        hub = app.state.hub
        hub.conversations = store = DictConversations()
        await store.save("b" * 32, "Older", [{"type": "user_message", "text": "hi"}], 1)
        hub.conversation_id = "a" * 32
        hub.messages.append({"role": "user", "content": "now"})
        deleted = await client.delete(f"/api/conversations/{'b' * 32}", headers=AUTH)
        return deleted.json(), hub

    deleted, hub = run(with_client(app, body))
    assert deleted == {"deleted": True, "cleared": False}
    assert hub.conversation_id == "a" * 32 and len(hub.messages) == 1


def test_the_conversation_chat_is_in_cannot_be_deleted_mid_reply(tmp_path):
    app = app_for(tmp_path)

    async def body(client):
        hub = app.state.hub
        hub.conversations = store = DictConversations()
        await store.save("a" * 32, "Kwame", [{"type": "user_message", "text": "hi"}], 1)
        hub.conversation_id = "a" * 32
        hub.turn = asyncio.get_running_loop().create_future()  # a reply in progress
        refused = await client.delete(f"/api/conversations/{'a' * 32}", headers=AUTH)
        hub.turn.cancel()
        return refused.status_code, store.rows

    status, rows = run(with_client(app, body))
    assert status == 409 and "a" * 32 in rows


def test_renaming_the_conversation_chat_is_in_survives_its_next_message(tmp_path):
    app = app_for(tmp_path)

    async def body(client):
        hub = app.state.hub
        hub.conversations = store = DictConversations()
        hub.conversation_id, hub.conversation_title = "a" * 32, "What did Kwame say?"
        await hub.emit({"type": "user_message", "text": "What did Kwame say?"})
        await hub.save_conversation()
        await client.patch(f"/api/conversations/{'a' * 32}", headers=AUTH, json={"title": "Kwame and the budget"})
        await hub.save_conversation()  # the next turn
        return store.rows["a" * 32]["title"]

    assert run(with_client(app, body)) == "Kwame and the budget"
