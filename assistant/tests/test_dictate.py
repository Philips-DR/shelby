"""The chat page's microphone: a clip in, its words out, through meet-ai's `dictate`, and a tool kept for the page.

No child process, no model: meet-ai's tool is a stand-in that records what it was given.
"""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from assistant import server as server_module
from assistant.tools import RemoteTool, ToolOutcome, ToolRegistry
from tests.test_server import AUTH, app_for
from tests.test_stop import FakeModel, FakeTools, answer, text, tool_use, turn

DICTATE = RemoteTool(server="meet_ai", name="dictate", qualified_name="meet_ai__dictate", description="",
                     input_schema={}, read_only=True, interface_only=True)


def test_a_page_only_tool_is_read_off_its_meta_and_never_shown_to_the_model():
    def listed(name, meta, read_only):
        return SimpleNamespace(name=name, description="", input_schema={}, meta=meta, title="",
                               annotations=SimpleNamespace(read_only_hint=read_only, title=None))

    async def list_tools():
        return SimpleNamespace(tools=[listed("dictate", {"interface_only": True}, True),
                                      listed("transcribe", None, False)])

    tools = asyncio.run(ToolRegistry._describe(SimpleNamespace(safe_name="meet_ai"),
                                               SimpleNamespace(list_tools=list_tools)))
    registry = ToolRegistry([])
    registry.tools.extend(tools)
    assert [t["name"] for t in registry.anthropic_tools()] == ["meet_ai__transcribe"]
    assert registry.find("meet_ai__dictate").interface_only  # the page still reaches it by name


def test_the_model_naming_a_page_only_tool_is_refused_and_nothing_runs(monkeypatch, tmp_path):
    class Tools(FakeTools):
        def find(self, name):
            return DICTATE if name == DICTATE.qualified_name else super().find(name)

    tools = Tools()
    model = FakeModel(answer(tool_use("b1", DICTATE), stop_reason="tool_use"), answer(text("I cannot hear.")))
    reply, messages, _ = turn(monkeypatch, tmp_path, model, tools, asyncio.Event())
    assert tools.ran == [] and reply == "I cannot hear."
    result = messages[2]["content"][0]
    assert result["is_error"] and result["content"] == "no such tool: meet_ai__dictate"


def dictating(tmp_path, reply=None, seen=None):
    """The app with meet-ai's dictate replaced by a stand-in that notes the clip it was given."""
    app = app_for(tmp_path)

    async def fake_call(tool, arguments):
        clip = Path(arguments["audio"])
        if seen is not None:
            seen.append((clip, clip.read_bytes()))
        return ToolOutcome(text=json.dumps(reply or {"text": "Draft a reply to Ama.", "seconds": 3.2,
                                                     "model": "base.en", "loaded_now": False}), is_error=False)

    async def install():
        hub = app.state.hub
        hub.registry.tools.append(DICTATE)
        hub.registry.call = fake_call

    return app, install


async def put(client, body=b"OggS opus bytes", name="clip.webm", headers=AUTH):
    return await client.put(f"/api/dictate?name={name}", headers=headers, content=body)


def with_dictation(app, install, body):
    async def go():
        async with app.router.lifespan_context(app):
            await install()
            import httpx
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8750") as client:
                return await body(client, app.state.hub)
    return asyncio.run(go())


def test_a_clip_comes_back_as_its_words_and_leaves_nothing_behind(tmp_path):
    seen = []
    app, install = dictating(tmp_path, seen=seen)

    async def body(client, hub):
        answered = await put(client)
        state = (await client.get("/api/state", headers=AUTH)).json()
        uploads = (await client.get("/api/uploads", headers=AUTH)).json()
        return answered, state, uploads, list(hub.notes)

    answered, state, uploads, notes = with_dictation(app, install, body)
    assert answered.status_code == 200 and answered.json()["text"] == "Draft a reply to Ama."
    (clip, data), = seen
    assert data == b"OggS opus bytes" and clip.suffix == ".webm"
    assert not clip.exists() and not clip.parent.exists()  # deleted as soon as meet-ai has read it
    # Not an upload, not a note for the model, not a step in Chat, not an audit row: the page reading.
    assert notes == [] and state["history"] == []
    assert all(not group for group in uploads.values() if isinstance(group, list))
    assert not (tmp_path / "audit.jsonl").exists()


def test_what_meet_ai_refuses_is_said_in_its_own_words(tmp_path):
    app, install = dictating(tmp_path, reply={"error": "the clip is 130 s, past the 120-second limit for dictation."})

    async def body(client, hub):
        return await put(client)

    answered = with_dictation(app, install, body)
    assert answered.status_code == 422 and "120-second limit" in answered.json()["error"]


def test_a_file_that_is_not_audio_is_refused_before_anything_is_written(tmp_path):
    seen = []
    app, install = dictating(tmp_path, seen=seen)

    async def body(client, hub):
        return await put(client, name="notes.txt")

    answered = with_dictation(app, install, body)
    assert answered.status_code == 400 and "not an audio file" in answered.json()["error"] and seen == []


def test_a_clip_too_large_is_refused_and_nothing_is_left(tmp_path, monkeypatch):
    monkeypatch.setattr(server_module, "MAX_DICTATION_BYTES", 8)
    seen = []
    app, install = dictating(tmp_path, seen=seen)

    async def body(client, hub):
        return await put(client, body=b"x" * 64)

    answered = with_dictation(app, install, body)
    assert answered.status_code == 400 and "limit" in answered.json()["error"] and seen == []


def test_without_meet_ai_dictation_says_so(tmp_path):
    async def body(client, hub):
        return await put(client)

    answered = with_dictation(app_for(tmp_path), lambda: asyncio.sleep(0), body)
    assert answered.status_code == 503 and "meet-ai" in answered.json()["error"]


def test_dictation_needs_the_token(tmp_path):
    app, install = dictating(tmp_path)

    async def body(client, hub):
        return (await put(client, headers={})).status_code

    assert with_dictation(app, install, body) == 401
