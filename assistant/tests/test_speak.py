"""Speaking a reply: text in, audiobook's `speak` (a stand-in here), MP3 bytes out. Nothing kept, nothing audited."""

import base64
import json

from assistant.tools import RemoteTool, ToolOutcome
from tests.test_dictate import with_dictation as with_tools
from tests.test_server import AUTH, app_for

SPEAK = RemoteTool(server="audiobook", name="speak", qualified_name="audiobook__speak", description="",
                   input_schema={}, read_only=True, interface_only=True)
MP3 = b"ID3\x04fake mp3 bytes"


def speaking(tmp_path, reply=None, seen=None):
    app = app_for(tmp_path)

    async def fake_call(tool, arguments):
        if seen is not None:
            seen.append(arguments)
        return ToolOutcome(text=json.dumps(reply if reply is not None else {
            "audio": base64.b64encode(MP3).decode(), "mime": "audio/mpeg", "seconds": 1.2, "voice": "abigail",
            "loaded_now": False}), is_error=False)

    async def install():
        app.state.hub.registry.tools.append(SPEAK)
        app.state.hub.registry.call = fake_call

    return app, install


def test_a_sentence_comes_back_as_mp3_and_nothing_is_recorded(tmp_path):
    seen = []
    app, install = speaking(tmp_path, seen=seen)

    async def body(client, hub):
        spoken = await client.post("/api/speak", headers=AUTH, json={"text": "I found three emails."})
        state = (await client.get("/api/state", headers=AUTH)).json()
        return spoken, state, list(hub.notes)

    spoken, state, notes = with_tools(app, install, body)
    assert spoken.status_code == 200 and spoken.content == MP3
    assert spoken.headers["content-type"] == "audio/mpeg" and spoken.headers["cache-control"] == "no-store"
    assert seen == [{"text": "I found three emails."}]  # no voice named: the tool picks its own
    assert state["history"] == [] and notes == [] and not (tmp_path / "audit.jsonl").exists()


def test_a_voice_asked_for_is_passed_on(tmp_path):
    seen = []
    app, install = speaking(tmp_path, seen=seen)

    async def body(client, hub):
        return await client.post("/api/speak", headers=AUTH, json={"text": "Hi.", "voice": "alba"})

    assert with_tools(app, install, body).status_code == 200 and seen == [{"text": "Hi.", "voice": "alba"}]


def test_what_the_tool_refuses_is_said_in_its_own_words(tmp_path):
    app, install = speaking(tmp_path, reply={"error": "no voice called nobody"})

    async def body(client, hub):
        return await client.post("/api/speak", headers=AUTH, json={"text": "Hi.", "voice": "nobody"})

    answered = with_tools(app, install, body)
    assert answered.status_code == 422 and answered.json() == {"error": "no voice called nobody"}


def test_something_that_is_not_audio_is_not_passed_to_the_page(tmp_path):
    app, install = speaking(tmp_path, reply={"audio": "not base64 at all!", "mime": "audio/mpeg"})

    async def body(client, hub):
        return await client.post("/api/speak", headers=AUTH, json={"text": "Hi."})

    answered = with_tools(app, install, body)
    assert answered.status_code == 502 and "not audio" in answered.json()["error"]


def test_without_the_audiobook_tool_speaking_says_so(tmp_path):
    import asyncio

    async def body(client, hub):
        return await client.post("/api/speak", headers=AUTH, json={"text": "Hi."})

    answered = with_tools(app_for(tmp_path), lambda: asyncio.sleep(0), body)
    assert answered.status_code == 503 and "audiobook" in answered.json()["error"]


def test_speaking_needs_the_token(tmp_path):
    app, install = speaking(tmp_path)

    async def body(client, hub):
        return (await client.post("/api/speak", json={"text": "Hi."})).status_code

    assert with_tools(app, install, body) == 401
