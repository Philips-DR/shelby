"""Continuing a past conversation: what the model remembered is given back, and Chat shows it again."""

import asyncio
import json

from anthropic.types import TextBlock, ThinkingBlock, ToolUseBlock

from assistant.conversations import messages_for_storage, messages_from_events
from tests.test_server import AUTH, DictConversations, app_for, run, with_client

A, B = "a" * 32, "b" * 32


def test_what_the_model_remembers_is_kept_as_the_api_takes_it_back():
    remembered = [
        {"role": "user", "content": "What is in my inbox?"},
        {"role": "assistant", "content": [
            ThinkingBlock(type="thinking", thinking="Search first.", signature="sig-1"),
            TextBlock(type="text", text="Looking."),
            ToolUseBlock(type="tool_use", id="t1", name="mail_ai__search", input={"query": "bank"}),
        ]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "3 emails"}]},
    ]
    kept = json.loads(json.dumps(messages_for_storage(remembered)))  # through JSON, as the database keeps it
    assert kept[0] == {"role": "user", "content": "What is in my inbox?"}
    assert kept[1]["content"] == [
        {"type": "thinking", "thinking": "Search first.", "signature": "sig-1"},  # the signature the API checks
        {"type": "text", "text": "Looking."},
        {"type": "tool_use", "id": "t1", "name": "mail_ai__search", "input": {"query": "bank"}},
    ]
    assert kept[2] == remembered[2]


def test_a_conversation_kept_before_its_messages_were_is_rebuilt_from_its_words():
    events = [
        {"type": "user_message", "text": "hi"},
        {"type": "turn_error", "error": "No model is set up"},           # never answered: left out
        {"type": "user_message", "text": "What is in my inbox?"},
        {"type": "assistant_text", "text": "Let me look."},
        {"type": "tool_finished", "tool": "mail_ai__search", "origin": "chat"},
        {"type": "assistant_text", "text": "Three emails."},              # the same reply, after a tool
        {"type": "turn_done", "text": "Three emails."},
        {"type": "user_message", "text": "Thanks"},                       # the last one, unanswered: left out
    ]
    assert messages_from_events(events) == [
        {"role": "user", "content": "What is in my inbox?"},
        {"role": "assistant", "content": "Let me look.\n\nThree emails."},
    ]


def continuing(tmp_path, kept_messages):
    app = app_for(tmp_path)

    async def body(client):
        hub = app.state.hub
        hub.conversations = store = DictConversations()
        await store.save(B, "The bank", [
            {"type": "user_message", "text": "What is in my inbox?", "seq": 7, "at": 1.0},
            {"type": "assistant_text", "text": "Three emails.", "seq": 8, "at": 2.0},
            {"type": "turn_done", "text": "Three emails.", "seq": 9, "at": 2.0},
        ], 1, kept_messages)
        # Chat is in another conversation, with a note waiting for the next message.
        hub.conversation_id, hub.conversation_title = A, "Kwame"
        hub.messages.extend([{"role": "user", "content": "Kwame?"}, {"role": "assistant", "content": "He agreed."}])
        hub.notes.append("a button was pressed")
        await hub.emit({"type": "user_message", "text": "Kwame?"})
        await hub.emit({"type": "notice", "title": "Transcription finished"})
        answered = await client.post(f"/api/conversations/{B}/continue", headers=AUTH)
        state = (await client.get("/api/state", headers=AUTH)).json()
        return answered, state, hub, store

    return run(with_client(app, body))


def test_continuing_gives_back_what_the_model_remembered_and_what_chat_showed(tmp_path):
    remembered = [{"role": "user", "content": "What is in my inbox?"},
                  {"role": "assistant", "content": [{"type": "text", "text": "Three emails."}]}]
    answered, state, hub, store = continuing(tmp_path, remembered)
    assert answered.status_code == 200 and answered.json() == {"id": B, "title": "The bank", "restored": 3}
    assert hub.messages == remembered and hub.notes == []
    assert (hub.conversation_id, hub.conversation_title) == (B, "The bank")
    # The one Chat was in is kept first, as Clear chat keeps it.
    assert store.rows[A]["title"] == "Kwame" and store.rows[A]["messages"][1]["content"] == "He agreed."
    # Every page is told to start again, then sent the conversation, numbered after the marker.
    types = [e["type"] for e in state["history"]]
    assert types == ["notice", "chat_cleared", "user_message", "assistant_text", "turn_done"]
    seqs = [e["seq"] for e in state["history"]]
    assert seqs == sorted(seqs) and seqs[2] > seqs[1]
    rows = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert (rows[-1]["tool"], rows[-1]["origin"], rows[-1]["result"]) == ("assistant__continue_conversation", "button", "'The bank'")


def test_a_conversation_kept_without_its_messages_is_continued_from_its_words(tmp_path):
    answered, _, hub, _ = continuing(tmp_path, None)
    assert answered.status_code == 200
    assert hub.messages == [{"role": "user", "content": "What is in my inbox?"},
                            {"role": "assistant", "content": "Three emails."}]


def test_continuing_the_conversation_chat_is_in_changes_nothing(tmp_path):
    app = app_for(tmp_path)

    async def body(client):
        hub = app.state.hub
        hub.conversations = DictConversations()
        hub.conversation_id = A
        hub.messages.append({"role": "user", "content": "Kwame?"})
        answered = await client.post(f"/api/conversations/{A}/continue", headers=AUTH)
        return answered, hub

    answered, hub = run(with_client(app, body))
    assert answered.status_code == 200 and answered.json()["restored"] == 0 and len(hub.messages) == 1


def test_continuing_is_refused_mid_reply_and_for_a_conversation_that_is_not_there(tmp_path):
    app = app_for(tmp_path)

    async def body(client):
        hub = app.state.hub
        hub.conversations = store = DictConversations()
        await store.save(B, "The bank", [{"type": "user_message", "text": "hi"}], 1)
        missing = (await client.post(f"/api/conversations/{'c' * 32}/continue", headers=AUTH)).status_code
        hub.turn = asyncio.get_running_loop().create_future()
        busy = (await client.post(f"/api/conversations/{B}/continue", headers=AUTH)).status_code
        hub.turn.cancel()
        untoken = (await client.post(f"/api/conversations/{B}/continue")).status_code
        return missing, busy, untoken, hub.conversation_id

    assert run(with_client(app, body)) == (404, 409, 401, None)


def test_each_save_keeps_what_the_model_remembers(tmp_path):
    app = app_for(tmp_path)

    async def body(client):
        hub = app.state.hub
        hub.conversations = store = DictConversations()
        hub.conversation_id, hub.conversation_title = A, "Kwame"
        hub.messages.extend([{"role": "user", "content": "Kwame?"},
                             {"role": "assistant", "content": [TextBlock(type="text", text="He agreed.")]}])
        await hub.emit({"type": "user_message", "text": "Kwame?"})
        await hub.save_conversation()
        return store.rows[A]["messages"]

    kept = run(with_client(app, body))
    assert json.loads(json.dumps(kept))[1]["content"] == [{"type": "text", "text": "He agreed."}]
