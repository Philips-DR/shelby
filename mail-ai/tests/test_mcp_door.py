"""Tests for the MCP front door.

Driven through list_tools() and call_tool(), which is the same path a real session takes
once the transport is stripped away. No network, no credentials, no Gmail.
"""

import asyncio
import base64
import contextlib
import io
import json

import pytest

from mailai.auth import AuthConfig
from mailai.mcp_server import ServerPaths, create_mail_ai_server
from mailai.store import open_store, upsert_message


@pytest.fixture
def store_path(tmp_path):
    path = tmp_path / "mailbox.sqlite3"
    connection = open_store(path)
    for n, (mid, thread, body) in enumerate([
        ("m1", "t1", "Can we move the review?"),
        ("m2", "t1", "Tuesday works."),
        ("m3", "t2", "Invoice attached."),
    ]):
        upsert_message(connection, dict(
            id=mid, thread_id=thread, internal_date=1000 + n, from_addr="a@x.com",
            to_addr="me@x.com", cc_addr="", subject="Claims review",
            normalised_subject="Claims review", snippet=body[:20], body=body, quoted="",
            labels=["INBOX"], attachments=[],
        ))
    connection.commit()
    return path


@pytest.fixture
def server(store_path, tmp_path):
    return create_mail_ai_server(
        ServerPaths(store=store_path),
        AuthConfig(credentials_path=tmp_path / "nope.json", token_path=tmp_path / "nope-token.json"),
    )


def call(server, name, **arguments) -> dict:
    result = asyncio.run(server.call_tool(name, arguments))
    text = "".join(b.text for b in result.content if b.type == "text")
    return json.loads(text)


def test_the_door_advertises_exactly_the_read_path_and_sync(server):
    names = sorted(t.name for t in asyncio.run(server.list_tools()))
    assert names == ["list_threads", "login_status", "read_thread", "search", "status", "sync"]


def test_without_a_compose_credential_the_door_cannot_send_at_all(server):
    """Not "refuses to send" -- has no tool for it. A model cannot call a tool that was
    never advertised, which is a stronger guarantee than one that checks a flag."""
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert not names & {"send_draft", "draft_new", "draft_reply", "discard_draft"}


def test_only_sync_is_marked_as_writing(server):
    read_only = {t.name: t.annotations.read_only_hint for t in asyncio.run(server.list_tools())}
    assert read_only["sync"] is False
    assert all(read_only[n] is True for n in ("status", "list_threads", "read_thread", "search", "login_status"))


def test_status_works_offline_with_no_credentials(server):
    report = call(server, "status")
    assert report["messages"] == 3
    assert report["threads"] == 2
    assert report["full_sync_complete"] is False


def test_threads_come_back_newest_first(server):
    threads = call(server, "list_threads")["threads"]
    assert [t["thread_id"] for t in threads] == ["t2", "t1"]


def test_a_thread_reads_oldest_first(server):
    """A conversation is read in the order it happened, whatever order threads are listed."""
    detail = call(server, "read_thread", thread_id="t1")
    assert [m["id"] for m in detail["messages"]] == ["m1", "m2"]


def test_an_unknown_thread_is_an_error_not_an_exception(server):
    """A door that raises takes the session down with it."""
    assert "error" in call(server, "read_thread", thread_id="nope")


def test_search_finds_by_body_text(server):
    found = call(server, "search", text="Tuesday")["messages"]
    assert [m["id"] for m in found] == ["m2"]


def test_status_says_when_the_last_sync_finished(store_path, tmp_path, monkeypatch):
    """The newest message is not when the mailbox was last brought level: a quiet day has no new mail."""
    from mailai import operations
    from tests.fake_gmail import FakeGmail, message

    assert operations.status(store_path).synced_at == ""
    fake = FakeGmail([message("m9", "t9", "Hello", "Hi.", date=5000)], history_id="900")
    monkeypatch.setattr("mailai.client.build_service", lambda credentials: fake)
    monkeypatch.setattr(operations, "load_credentials", lambda auth: None)
    operations.sync_mailbox(AuthConfig(credentials_path=tmp_path / "c.json", token_path=tmp_path / "t.json"),
                            store_path, labels=["INBOX"])
    assert operations.status(store_path).synced_at.startswith("20")


def test_nothing_is_written_to_stdout_while_a_tool_runs(server):
    """On stdio, stdout IS the protocol stream: one stray line corrupts the session."""
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink):
        call(server, "status")
        call(server, "list_threads")
        call(server, "search", text="review")
    assert sink.getvalue() == ""


def test_a_sync_without_credentials_reports_rather_than_crashing(server):
    """The one tool that needs the network must fail like every other tool here."""
    assert "error" in call(server, "sync", limit=1)


# ---------------------------------------------------------------------------
# Drafting, once a compose credential is supplied
# ---------------------------------------------------------------------------

@pytest.fixture
def composing_server(store_path, tmp_path):
    from mailai.auth import COMPOSE_SCOPES

    return create_mail_ai_server(
        ServerPaths(store=store_path),
        AuthConfig(credentials_path=tmp_path / "c.json", token_path=tmp_path / "t.json"),
        AuthConfig(credentials_path=tmp_path / "c.json", token_path=tmp_path / "tc.json",
                   scopes=tuple(COMPOSE_SCOPES)),
    )


def test_a_compose_credential_turns_drafting_on(composing_server):
    names = {t.name for t in asyncio.run(composing_server.list_tools())}
    assert {"draft_new", "draft_reply", "review_draft", "send_draft"} <= names


def test_send_is_the_only_tool_marked_destructive(composing_server):
    """Everything else can be repeated or undone. Sending cannot."""
    destructive = {
        t.name for t in asyncio.run(composing_server.list_tools())
        if t.annotations and t.annotations.destructive_hint
    }
    assert "send_draft" in destructive
    assert "draft_new" not in destructive
    assert "draft_reply" not in destructive


def test_no_tool_on_this_door_takes_content_and_sends_it(composing_server):
    """Compose-and-send in one call is not something a caller has to avoid; it is not
    offered. send_draft takes an id and a confirmation, and nothing else."""
    send_tool = next(
        t for t in asyncio.run(composing_server.list_tools()) if t.name == "send_draft"
    )
    assert set(send_tool.input_schema["properties"]) == {"draft_id", "confirmation"}


def test_review_is_read_only_so_it_can_be_run_unattended(composing_server):
    """Reading a draft to decide whether to send it must never itself need approval, or the
    approval step becomes two approvals and people stop reading."""
    review = next(
        t for t in asyncio.run(composing_server.list_tools()) if t.name == "review_draft"
    )
    assert review.annotations.read_only_hint is True


# ---------------------------------------------------------------------------
# Attachments through the door
# ---------------------------------------------------------------------------

CV_BYTES = b"%PDF-1.7 cv bytes"


def encoded(data: bytes) -> str:
    return base64.b64encode(data).decode()


@pytest.fixture
def gmail(monkeypatch):
    """Drafting goes to a stand-in, so what reaches 'Gmail' can be looked at."""
    from tests.fake_drafts import FakeDrafts

    service = FakeDrafts()
    monkeypatch.setattr("mailai.operations._compose_service", lambda auth: service)
    return service


def draft_with_cv(server) -> dict:
    return call(server, "draft_new", to="hr@example.org", subject="Application",
                body="Attached.", attachments=[{"filename": "cv.pdf", "data": encoded(CV_BYTES)}])


def test_draft_new_takes_attachments_and_the_other_tools_still_take_none(composing_server):
    tools = {t.name: t for t in asyncio.run(composing_server.list_tools())}
    assert "attachments" in tools["draft_new"].input_schema["properties"]
    assert set(tools["send_draft"].input_schema["properties"]) == {"draft_id", "confirmation"}
    assert set(tools["review_draft"].input_schema["properties"]) == {"draft_id"}


def test_a_draft_with_a_file_is_reviewed_and_sent_through_the_door(composing_server, gmail):
    made = draft_with_cv(composing_server)
    assert made["attachments"] == [{"filename": "cv.pdf", "size": len(CV_BYTES)}]

    reviewed = call(composing_server, "review_draft", draft_id=made["draft_id"])
    assert reviewed["confirmation"] == made["confirmation"]
    assert f"cv.pdf ({len(CV_BYTES)} bytes)" in reviewed["rendered"]

    call(composing_server, "send_draft", draft_id=made["draft_id"],
         confirmation=reviewed["confirmation"])
    assert gmail.sent == [made["draft_id"]]


def test_a_file_swapped_after_review_is_not_sent_through_the_door(composing_server, gmail):
    made = draft_with_cv(composing_server)
    reviewed = call(composing_server, "review_draft", draft_id=made["draft_id"])
    gmail.replace_attachment(made["draft_id"], "cv.pdf", b"%PDF-1.7 somebody else's cv")

    refused = call(composing_server, "send_draft", draft_id=made["draft_id"],
                   confirmation=reviewed["confirmation"])
    assert "error" in refused
    assert gmail.sent == []


@pytest.mark.parametrize("attachments", [
    [{"filename": "../cv.pdf", "data": encoded(CV_BYTES)}],
    [{"filename": "cv.pdf", "data": "this is not base64!!"}],
    [{"filename": "cv.pdf", "data": ""}],
    # One good file beside a bad one: neither is drafted.
    [{"filename": "cv.pdf", "data": encoded(CV_BYTES)},
     {"filename": "a/b.pdf", "data": encoded(CV_BYTES)}],
])
def test_a_refused_file_is_an_error_and_makes_no_draft(composing_server, gmail, attachments):
    result = call(composing_server, "draft_new", to="hr@example.org", subject="Application",
                  body="Attached.", attachments=attachments)
    assert "error" in result
    assert gmail.store == {}


def test_drafts_are_listed_with_who_they_are_to_and_what_about(composing_server, gmail):
    """A list of bare ids is no list a person can choose from. Read as metadata, so no file is fetched."""
    first = gmail.add("hr@example.org", "Application", "Please find my CV attached.", thread_id="t1",
                      files=[("cv.pdf", b"%PDF-1.4 cv", "application/pdf")])
    gmail.add("me@example.com", "Notes", "Remember the meeting.")
    listed = call(composing_server, "list_drafts")["drafts"]
    assert [(d["draft_id"], d["to"], d["subject"], d["thread_id"]) for d in listed] == [
        (first, "hr@example.org", "Application", "t1"), ("d2", "me@example.com", "Notes", "")]
    assert listed[0]["snippet"].startswith("Please find") and listed[0]["updated"].startswith("2023")
    assert set(gmail.formats) == {"metadata"}


def test_a_draft_deleted_while_drafts_are_listed_is_left_out(composing_server, gmail, monkeypatch):
    gmail.add("a@example.org", "Gone", "x")
    kept = gmail.add("b@example.org", "Kept", "y")
    from mailai import drafts

    real = drafts.summary
    monkeypatch.setattr(drafts, "summary", lambda service, draft_id: real(service, "nope") if draft_id == "d1" else real(service, draft_id))
    assert [d["draft_id"] for d in call(composing_server, "list_drafts")["drafts"]] == [kept]
