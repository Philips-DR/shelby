"""Tests for choosing the way to the model in Settings: the API key or Bedrock (route.py).

No model, no network: the model's login check is a stand-in, and a tool that follows the route is a stand-in
registry that records what it was told.
"""

import asyncio
import json

import httpx
import pytest

import assistant.logins as logins_module
from assistant import route
from assistant.config import ANTHROPIC, BEDROCK, ModelConfig
from assistant.server import create_app
from assistant.tools import RemoteTool, ToolOutcome, ToolRegistry

TOKEN = "test-token"
AUTH = {"x-assistant-token": TOKEN}
OPUS_46 = "us.anthropic.claude-opus-4-6-v1"


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def both_ways_set_up(monkeypatch):
    """A machine like this one: a key and an AWS login in .env, Sonnet named for the API, nothing for Bedrock."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("AWS_PROFILE", "profile")
    monkeypatch.setenv("SHELBY_MODEL", "claude-sonnet-5-5")
    for name in ("ASSISTANT_MODEL", "SHELBY_BEDROCK_MODEL", "ANTHROPIC_AUTH_TOKEN", "AWS_ACCESS_KEY_ID"):
        monkeypatch.delenv(name, raising=False)
    checked = []
    monkeypatch.setattr(logins_module, "model_status",
                        lambda config: checked.append(config.provider) or {"provider": config.provider,
                                                                          "model": config.resolved_model, "level": "ok"})
    return checked


def route_tool(server="meet_ai", read_only=False) -> RemoteTool:
    return RemoteTool(server=server, name="model_route", qualified_name=f"{server}__model_route", description="",
                      input_schema={}, read_only=read_only)


class Told(ToolRegistry):
    """Answers every call with `answer` (a ToolOutcome, an exception, or a coroutine function); records the calls."""

    def __init__(self, tools, answer=None):
        super().__init__([])
        self.tools = tools
        self.answer = answer or ToolOutcome(text='{"provider": "x"}', is_error=False)
        self.calls: list[tuple[str, dict]] = []

    async def call(self, tool, arguments):
        self.calls.append((tool.qualified_name, arguments))
        if isinstance(self.answer, BaseException):
            raise self.answer
        if callable(self.answer):
            return await self.answer()
        return self.answer


def app_at(tmp_path, tools=(), **kwargs):
    registry_holder = {}

    def factory(local):
        registry = Told(list(tools))
        registry._local = {t.name: t for t in local}
        registry_holder["registry"] = registry
        return registry

    app = create_app(tmp_path / "tools.yaml", tmp_path / "memory.json", tmp_path / "audit.jsonl", token=TOKEN,
                     registry_factory=factory, watch_jobs=False, **kwargs)
    return app, registry_holder


async def with_client(app, body):
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8750") as client:
            return await body(client)


# ---------------------------------------------------------------------------
# The saved choice
# ---------------------------------------------------------------------------

def test_nothing_saved_means_env_decides(tmp_path):
    assert route.load(tmp_path / "settings.json") is None


@pytest.mark.parametrize("content", ["not json", "[1, 2]", '{"model_route": "openai"}', '{"model_route": 7}', ""])
def test_a_broken_or_strange_file_is_as_if_nothing_were_saved(tmp_path, content):
    path = tmp_path / "settings.json"
    path.write_text(content)
    assert route.load(path) is None


def test_saving_keeps_the_rest_of_the_file_and_leaves_no_half_file(tmp_path):
    path = tmp_path / "data" / "settings.json"
    path.parent.mkdir()
    path.write_text('{"something_else": 1}')
    route.save(path, BEDROCK)
    assert json.loads(path.read_text()) == {"something_else": 1, "model_route": "bedrock"}
    assert route.load(path) == BEDROCK
    assert [p.name for p in path.parent.iterdir()] == ["settings.json"]


def test_a_way_with_nothing_set_up_cannot_be_chosen_and_says_what_is_missing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.delenv("AWS_PROFILE")
    with pytest.raises(route.RouteError, match="No API key in .env"):
        route.check(ANTHROPIC)
    with pytest.raises(route.RouteError, match="No AWS login in .env"):
        route.check(BEDROCK)
    with pytest.raises(route.RouteError, match="Not a way"):
        route.check("openai")


def test_settings_is_shown_each_way_with_its_own_model():
    shown = route.choices(ModelConfig(provider=ANTHROPIC, model="claude-sonnet-5-5"), None)
    assert shown["current"] == ANTHROPIC and shown["saved"] is None
    models = {c["provider"]: (c["model"], c["unavailable"]) for c in shown["choices"]}
    assert models == {ANTHROPIC: ("claude-sonnet-5-5", None), BEDROCK: (OPUS_46, None)}


# ---------------------------------------------------------------------------
# Telling the tools
# ---------------------------------------------------------------------------

def test_every_tool_offering_the_name_is_told_the_provider_and_model():
    registry = Told([route_tool("meet_ai"), route_tool("other_ai")])
    told = run(route.tell_tools(registry, ModelConfig(provider=BEDROCK)))
    assert told == {"meet-ai": "ok", "other-ai": "ok"}
    assert registry.calls == [("meet_ai__model_route", {"provider": "bedrock", "model": OPUS_46}),
                              ("other_ai__model_route", {"provider": "bedrock", "model": OPUS_46})]


def test_a_read_only_tool_of_that_name_is_never_called():
    registry = Told([route_tool("meet_ai", read_only=True)])
    assert run(route.tell_tools(registry, ModelConfig(provider=BEDROCK))) == {} and registry.calls == []


@pytest.mark.parametrize("answer, said", [
    (ToolOutcome(text="unknown provider", is_error=True), "refused: unknown provider"),
    (ToolOutcome(text='{"error": "not a model id"}', is_error=False), "refused: not a model id"),
    (RuntimeError("Connection closed"), "failed: Connection closed"),
])
def test_a_tool_that_refuses_or_has_died_is_said_never_raised(answer, said):
    assert run(route.tell_tools(Told([route_tool()], answer), ModelConfig(provider=BEDROCK))) == {"meet-ai": said}


def test_a_tool_that_does_not_answer_does_not_hang_the_switch(monkeypatch):
    monkeypatch.setattr(route, "TELL_WAIT", 0.05)

    async def never():
        await asyncio.sleep(30)

    assert run(route.tell_tools(Told([route_tool()], never), ModelConfig(provider=BEDROCK))) == {
        "meet-ai": "did not answer in 0.05 s"}


# ---------------------------------------------------------------------------
# Through the API
# ---------------------------------------------------------------------------

def test_switching_to_bedrock_is_saved_used_told_audited_and_checked(tmp_path, both_ways_set_up):
    app, held = app_at(tmp_path, tools=[route_tool()])

    async def body(client):
        before = (await client.get("/api/status", headers=AUTH)).json()
        switched = await client.post("/api/model/route", headers=AUTH, json={"provider": "bedrock"})
        after = (await client.get("/api/status", headers=AUTH)).json()
        history = (await client.get("/api/history", headers=AUTH)).json()
        return before, switched, after, history, app.state.hub.config

    before, switched, after, history, config = run(with_client(app, body))
    assert before["route"]["current"] == ANTHROPIC and before["route"]["saved"] is None
    assert switched.status_code == 200 and switched.json()["tools"] == {"meet-ai": "ok"}
    assert switched.json()["model"]["provider"] == BEDROCK  # the new way's login, checked there and then
    assert (config.provider, config.resolved_model) == (BEDROCK, OPUS_46)
    assert after["route"]["current"] == BEDROCK and after["route"]["saved"] == BEDROCK
    assert json.loads((tmp_path / "settings.json").read_text()) == {"model_route": "bedrock"}
    # told on start (the API key, as .env says), then on the switch
    assert [a["provider"] for _name, a in held["registry"].calls] == [ANTHROPIC, BEDROCK]
    row = next(r for r in history if r["tool"] == "assistant__set_model_route")
    arguments = json.loads(row["arguments"]) if isinstance(row["arguments"], str) else row["arguments"]
    assert row["origin"] == "button" and arguments == {"provider": "bedrock"} and OPUS_46 in row["result"]
    assert both_ways_set_up[-1] == BEDROCK


def test_a_saved_choice_is_used_after_a_restart_even_with_a_key_in_env(tmp_path):
    (tmp_path / "settings.json").write_text('{"model_route": "bedrock"}')
    app, held = app_at(tmp_path, tools=[route_tool()])

    async def body(client):
        return app.state.hub.config, (await client.get("/api/status", headers=AUTH)).json()["route"]

    config, shown = run(with_client(app, body))
    assert config.provider == BEDROCK and shown == {**shown, "current": BEDROCK, "saved": BEDROCK}
    assert held["registry"].calls == [("meet_ai__model_route", {"provider": "bedrock", "model": OPUS_46})]


def test_the_command_line_provider_still_wins_over_a_saved_choice(tmp_path):
    (tmp_path / "settings.json").write_text('{"model_route": "bedrock"}')
    app, _held = app_at(tmp_path, provider=ANTHROPIC)

    async def body(client):
        return app.state.hub.config.provider

    assert run(with_client(app, body)) == ANTHROPIC


@pytest.mark.parametrize("payload, said", [({"provider": "openai"}, "Not a way"), ({}, "Not a way"),
                                           ({"provider": "anthropic"}, "No API key")])
def test_a_way_that_cannot_be_chosen_is_refused_and_nothing_changes(tmp_path, monkeypatch, payload, said):
    monkeypatch.delenv("ANTHROPIC_API_KEY")  # .env has no key: Bedrock is the way already
    app, held = app_at(tmp_path, tools=[route_tool()])

    async def body(client):
        response = await client.post("/api/model/route", headers=AUTH, json=payload)
        return response, app.state.hub.config.provider

    response, provider = run(with_client(app, body))
    assert response.status_code == 400 and said in response.json()["error"]
    assert provider == BEDROCK and not (tmp_path / "settings.json").exists()
    assert len(held["registry"].calls) == 1  # only the start's


def test_switching_needs_the_token(tmp_path):
    app, _held = app_at(tmp_path)

    async def body(client):
        return (await client.post("/api/model/route", json={"provider": "bedrock"})).status_code

    assert run(with_client(app, body)) == 401 and not (tmp_path / "settings.json").exists()


def test_a_turn_after_the_switch_uses_the_new_way(tmp_path, monkeypatch):
    """What a chat turn is given is the hub's config at the moment it starts."""
    import assistant.server as server_module

    seen = []

    async def fake_turn(registry, config, *args, **kwargs):
        seen.append((config.provider, config.resolved_model))
        return None

    monkeypatch.setattr(server_module, "run_turn", fake_turn)
    app, _held = app_at(tmp_path)

    async def body(client):
        await client.post("/api/chat", headers=AUTH, json={"message": "one"})
        await asyncio.sleep(0.05)
        await client.post("/api/model/route", headers=AUTH, json={"provider": "bedrock"})
        await client.post("/api/chat", headers=AUTH, json={"message": "two"})
        await asyncio.sleep(0.05)
        await client.post("/api/model/route", headers=AUTH, json={"provider": "anthropic"})
        await client.post("/api/chat", headers=AUTH, json={"message": "three"})
        await asyncio.sleep(0.05)

    run(with_client(app, body))
    assert seen == [(ANTHROPIC, "claude-sonnet-5-5"), (BEDROCK, OPUS_46), (ANTHROPIC, "claude-sonnet-5-5")]
