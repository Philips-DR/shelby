"""Every login at a glance: asked of the tools, remembered, announced once, and never a hang.

No child process, no network, no boto3: a stand-in registry answers as a tool would, and the model's own check is
replaced. What these pin is the rules -- only a read-only tool is asked, a login that is gone is an error whatever the
last call did, "could not tell" is never "fine", and a change is announced once."""

import asyncio
import json

import httpx
import pytest

import assistant.logins as logins_module
import assistant.status as status_module
from assistant.audit import FileAuditStore
from assistant.logins import Logins, tool_login_notice
from assistant.server import create_app
from assistant.status import SIGN_IN_AGAIN, tool_logins, tools_status
from assistant.tools import LocalTool, RemoteTool, ToolOutcome, ToolRegistry

TOKEN = "test-token"
AUTH = {"x-assistant-token": TOKEN}


def login_tool(server="mail_ai", read_only=True, name="login_status") -> RemoteTool:
    return RemoteTool(server=server, name=name, qualified_name=f"{server}__{name}", description="", input_schema={}, read_only=read_only)


def other_tool(server) -> RemoteTool:
    return RemoteTool(server=server, name="sync", qualified_name=f"{server}__sync", description="", input_schema={}, read_only=False)


class Registry(ToolRegistry):
    """Answers a login_status call with whatever the test queued for that server; records who was asked."""

    def __init__(self, tools, answers):
        super().__init__([])
        self.tools = tools
        self.answers = answers
        self.asked: list[str] = []

    async def call(self, tool, arguments):
        self.asked.append(tool.server)
        answer = self.answers[tool.server]
        if isinstance(answer, BaseException):
            raise answer
        if callable(answer):
            return await answer()
        return ToolOutcome(text=answer if isinstance(answer, str) else json.dumps(answer), is_error=False)


def run(coro):
    return asyncio.run(coro)


# ---- asking the tools -------------------------------------------------------------------------------------------


def test_each_tool_that_offers_a_login_check_is_asked_and_answers_by_its_name():
    registry = Registry([login_tool("mail_ai"), login_tool("docu_ai")], {
        "mail_ai": {"state": "ok", "detail": "", "service": "Gmail"},
        "docu_ai": {"state": "dead", "detail": "invalid_grant", "service": "Google Docs"},
    })
    found = run(tool_logins(registry))
    assert found == {
        "mail-ai": {"state": "ok", "detail": "", "service": "Gmail"},
        "docu-ai": {"state": "dead", "detail": "invalid_grant", "service": "Google Docs"},
    }


def test_a_tool_that_is_not_read_only_is_never_called_for_this():
    # a tool that happened to use the name for something that changes things must not be run by a page looking at health
    registry = Registry([login_tool("sneaky", read_only=False)], {"sneaky": {"state": "ok"}})
    assert run(tool_logins(registry)) == {}
    assert registry.asked == []


def test_only_the_login_tool_is_asked_and_a_tool_without_one_is_left_alone():
    registry = Registry([other_tool("meet_ai"), login_tool("mail_ai")], {"mail_ai": {"state": "ok"}, "meet_ai": {"state": "dead"}})
    assert list(run(tool_logins(registry))) == ["mail-ai"]
    assert registry.asked == ["mail_ai"]


@pytest.mark.parametrize("answer", [
    RuntimeError("the tool went away"),
    ToolOutcome(text="boom", is_error=True),
    "not json",
    '["ok"]',
    {"state": "perhaps"},
    {"detail": "no state at all"},
])
def test_an_answer_that_cannot_be_used_is_unknown_never_ok(answer):
    if isinstance(answer, ToolOutcome):
        failed = answer

        async def failing():
            return failed
        answer = failing
    found = run(tool_logins(Registry([login_tool()], {"mail_ai": answer})))
    assert found["mail-ai"]["state"] == "unknown"


def test_a_tool_too_busy_to_answer_is_unknown_not_a_hang(monkeypatch):
    monkeypatch.setattr(status_module, "LOGIN_WAIT", 0.05)

    async def busy():
        await asyncio.sleep(5)

    found = run(tool_logins(Registry([login_tool()], {"mail_ai": busy})))
    assert found["mail-ai"]["state"] == "unknown"
    assert "no answer" in found["mail-ai"]["detail"]


def test_one_tool_failing_does_not_hide_another_that_answered():
    registry = Registry([login_tool("mail_ai"), login_tool("docu_ai")], {
        "mail_ai": RuntimeError("down"), "docu_ai": {"state": "dead", "detail": "invalid_grant"}})
    found = run(tool_logins(registry))
    assert found["mail-ai"]["state"] == "unknown" and found["docu-ai"]["state"] == "dead"


# ---- what a tool's row says -------------------------------------------------------------------------------------


def status_for(tmp_path, rows, logins):
    audit = FileAuditStore(tmp_path / "audit.jsonl")
    (tmp_path / "audit.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    registry = ToolRegistry([])
    registry.tools = [other_tool("mail_ai")]
    return run(tools_status(registry, audit, logins))[0]


OK_CALL = {"at": "t1", "tool": "mail_ai__sync", "outcome": "ok", "origin": "chat"}
FAILED_CALL = {"at": "t1", "tool": "mail_ai__sync", "outcome": "failed", "error": "boom", "origin": "chat"}


@pytest.mark.parametrize("state", ["dead", "missing"])
def test_a_login_that_is_gone_is_an_error_whatever_the_last_call_did(tmp_path, state):
    row = status_for(tmp_path, [OK_CALL], {"mail-ai": {"state": state, "detail": "x"}})
    assert row["level"] == "error"
    assert row["login"]["state"] == state


def test_a_working_login_does_not_hide_a_failed_last_call(tmp_path):
    assert status_for(tmp_path, [FAILED_CALL], {"mail-ai": {"state": "ok", "detail": ""}})["level"] == "warning"


def test_not_being_able_to_tell_changes_nothing_about_the_row(tmp_path):
    assert status_for(tmp_path, [OK_CALL], {"mail-ai": {"state": "unknown", "detail": "no network"}})["level"] == "ok"
    assert status_for(tmp_path, [FAILED_CALL], {"mail-ai": {"state": "unknown", "detail": "no network"}})["level"] == "warning"


def test_a_row_with_no_login_check_is_what_it_was(tmp_path):
    row = status_for(tmp_path, [OK_CALL], None)
    assert row["level"] == "ok" and row["login"] is None


# ---- announcing a change once -----------------------------------------------------------------------------------


def test_a_login_going_bad_is_announced_once_with_the_one_command():
    found = {"state": "dead", "service": "Gmail"}
    notice = tool_login_notice("mail-ai", {"state": "ok"}, found)
    assert notice["title"] == "Gmail login needs renewing"
    assert notice["body"] == SIGN_IN_AGAIN and "./auth" in notice["body"]
    assert tool_login_notice("mail-ai", {"state": "dead"}, found) is None  # not again on every check


def test_a_login_bad_at_the_first_check_is_announced():
    assert tool_login_notice("mail-ai", None, {"state": "missing", "service": ""})["title"] == "mail-ai login needs renewing"


def test_a_login_coming_back_says_so_and_unknown_says_nothing():
    assert tool_login_notice("docu-ai", {"state": "dead"}, {"state": "ok", "service": "Google Docs"})["title"] == "Google Docs login working again"
    assert tool_login_notice("docu-ai", {"state": "dead"}, {"state": "unknown", "service": "Google Docs"}) is None
    assert tool_login_notice("docu-ai", None, {"state": "ok", "service": "Google Docs"}) is None


# ---- the object that remembers ---------------------------------------------------------------------------------


def logins_for(monkeypatch, model_levels, tool_states):
    """A Logins whose model check and tool answers come from the queues given, one entry per check."""
    events: list[dict] = []

    async def emit(event):
        events.append(event)

    def model_status(config):
        return {"provider": "bedrock", "model": "m", "level": model_levels.pop(0)}

    monkeypatch.setattr(logins_module, "model_status", model_status)

    async def fake_tool_logins(registry):
        return {"mail-ai": {"state": tool_states.pop(0), "detail": "", "service": "Gmail"}}

    monkeypatch.setattr(logins_module, "tool_logins", fake_tool_logins)
    return Logins(None, None, emit), events


def test_a_check_remembers_the_model_and_each_tool_with_the_time(monkeypatch):
    logins, _ = logins_for(monkeypatch, ["ok"], ["ok"])
    assert logins.model is None and logins.tools == {}
    run(logins.check())
    assert logins.model["level"] == "ok" and logins.model["checked_at"] > 0
    assert logins.tools["mail-ai"]["state"] == "ok" and logins.tools["mail-ai"]["checked_at"] > 0


def test_two_checks_announce_a_bad_login_once_and_its_return_once(monkeypatch):
    logins, events = logins_for(monkeypatch, ["ok", "ok", "ok", "ok"], ["ok", "dead", "dead", "ok"])

    async def go():
        for _ in range(4):
            await logins.check()

    run(go())
    assert [e["title"] for e in events] == ["Gmail login needs renewing", "Gmail login working again"]
    assert all(e["type"] == "notice" for e in events)


def test_the_model_login_is_announced_through_the_same_check(monkeypatch):
    logins, events = logins_for(monkeypatch, ["ok", "error"], ["ok", "ok"])

    async def go():
        await logins.check()
        await logins.check()

    run(go())
    assert [e["title"] for e in events] == ["AWS login needs renewing"]


@pytest.mark.parametrize("model,tool,needs", [
    ("ok", "ok", False), ("error", "ok", True), ("ok", "dead", True), ("ok", "missing", True), ("ok", "unknown", False),
])
def test_any_login_out_means_look_again_sooner(monkeypatch, model, tool, needs):
    logins, _ = logins_for(monkeypatch, [model], [tool])
    assert logins.needs_attention() is False  # nothing known yet
    run(logins.check())
    assert logins.needs_attention() is needs


# ---- the endpoint -----------------------------------------------------------------------------------------------


def test_settings_gets_the_logins_live_and_the_instant_view_keeps_them(tmp_path, monkeypatch):
    monkeypatch.setattr(logins_module, "model_status",
                        lambda config: {"provider": "bedrock", "model": "m", "profile": "p", "region": "r", "level": "error",
                                        "detail": "expired", "signed_out": True, "hint": SIGN_IN_AGAIN})
    monkeypatch.setattr(status_module, "network_status", lambda: [])
    import assistant.server as server_module
    monkeypatch.setattr(server_module, "network_status", lambda: [])

    app = create_app(tmp_path / "tools.yaml", tmp_path / "memory.json", tmp_path / "audit.jsonl", token=TOKEN,
                     registry_factory=lambda local: ToolRegistry([], local=local), watch_jobs=False)

    async def scenario():
        async with app.router.lifespan_context(app):
            hub = app.state.hub
            hub.registry.tools.append(login_tool("mail_ai"))
            hub.registry.tools.append(other_tool("mail_ai"))

            async def call(tool, arguments):
                return ToolOutcome(text=json.dumps({"state": "dead", "detail": "invalid_grant", "service": "Gmail"}), is_error=False)

            hub.registry.call = call
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8750") as client:
                before = (await client.get("/api/status", headers=AUTH)).json()
                live = (await client.get("/api/status?live=true", headers=AUTH)).json()
                after = (await client.get("/api/status", headers=AUTH)).json()
            return before, live, after

    before, live, after = run(scenario())
    assert "level" not in before["model"] and before["tools"][0]["login"] is None  # nothing checked yet
    assert live["tools"][0]["level"] == "error" and live["tools"][0]["login"]["state"] == "dead"
    assert live["model"]["level"] == "error" and live["model"]["signed_out"] is True
    # the instant view carries what the last check found, so a page does not flash "not checked"
    assert "network" not in after
    assert after["tools"][0]["login"]["state"] == "dead" and after["model"]["level"] == "error"


# ---- the model's own login --------------------------------------------------------------------------------------


def model_with(monkeypatch, message):
    """model_status as it runs when AWS refuses: a stand-in boto3 whose first call fails with this message."""
    import sys
    import types

    class Session:
        def __init__(self, **kwargs):
            pass

        def client(self, name):
            raise RuntimeError(message)

    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(Session=Session))
    from assistant.config import BEDROCK, ModelConfig
    return status_module.model_status(ModelConfig(provider=BEDROCK, model=None, region="r", profile="p", api_key=None))


@pytest.mark.parametrize("message", [
    "Error when retrieving token from sso: Token has expired and refresh failed",
    "The SSO session associated with this profile has expired",
])
def test_an_expired_aws_login_is_signed_out_and_points_at_the_one_command(monkeypatch, message):
    found = model_with(monkeypatch, message)
    assert found["level"] == "error" and found["signed_out"] is True
    assert found["hint"] == SIGN_IN_AGAIN and "./auth" in found["hint"]


def test_a_model_that_is_out_of_reach_for_another_reason_is_not_called_signed_out(monkeypatch):
    # signing in again would not fix a network that is down, so it must not be what the page says
    found = model_with(monkeypatch, "Could not connect to the endpoint URL")
    assert found["level"] == "error" and found["signed_out"] is False and found["hint"] == ""


# ---- the first-party API key route ----------------------------------------------------------------------------


def key_status(monkeypatch, retrieve_raises=None, listed=(), key="sk-ant-test"):
    """model_status on the API-key route, with a stand-in `anthropic` whose model lookup fails (or not) as the API would."""
    import sys
    import types

    def refusal(name):
        return type(name, (Exception,), {})

    classes = {n: refusal(n) for n in ("AuthenticationError", "PermissionDeniedError", "NotFoundError", "APIConnectionError")}

    class Models:
        def retrieve(self, model_id):
            if retrieve_raises:
                raise classes[retrieve_raises](f"{retrieve_raises}: {model_id}")

        def list(self, limit=20):
            return types.SimpleNamespace(data=[types.SimpleNamespace(id=i) for i in listed])

    class Anthropic:
        def __init__(self, **kwargs):
            self.models = Models()

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=Anthropic, **classes))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    from assistant.config import ANTHROPIC, ModelConfig
    # the AWS settings are in .env too (the key wins over them), and must not be shown as this route's
    return status_module.model_status(ModelConfig(provider=ANTHROPIC, api_key=key, profile="aws-profile", region="us-east-1"))


def test_a_key_the_api_accepts_for_a_model_it_has_is_ok(monkeypatch):
    found = key_status(monkeypatch)
    assert found["level"] == "ok" and found["model"] == "claude-opus-5-5"
    assert found["profile"] is None and found["region"] is None  # AWS's settings are not this route's


@pytest.mark.parametrize("raised", ["AuthenticationError", "PermissionDeniedError"])
def test_a_key_the_api_refuses_says_to_replace_it_not_to_sign_in(monkeypatch, raised):
    found = key_status(monkeypatch, retrieve_raises=raised)
    assert found["level"] == "error" and found["key_refused"] is True
    assert found["hint"] == status_module.KEY_HINT and "ANTHROPIC_API_KEY" in found["hint"] and "./auth" not in found["hint"]
    assert not found.get("signed_out")


def test_a_model_the_key_cannot_use_names_what_it_can(monkeypatch):
    found = key_status(monkeypatch, retrieve_raises="NotFoundError", listed=["claude-opus-5-5", "claude-sonnet-5-5"])
    assert found["level"] == "error" and found["model_missing"] is True and not found.get("key_refused")
    assert found["available"] == ["claude-opus-5-5", "claude-sonnet-5-5"]
    assert "SUITE_MODEL" in found["hint"]


def test_the_model_list_failing_does_not_hide_that_the_model_is_missing(monkeypatch):
    found = key_status(monkeypatch, retrieve_raises="NotFoundError")
    assert found["model_missing"] is True and found["available"] == []


def test_the_network_being_down_is_neither_a_bad_key_nor_a_bad_model(monkeypatch):
    found = key_status(monkeypatch, retrieve_raises="APIConnectionError")
    assert found["level"] == "error" and not found.get("key_refused") and not found.get("model_missing") and found["hint"] == ""


def test_no_key_at_all_is_not_set_up_which_is_not_an_alarm(monkeypatch):
    found = key_status(monkeypatch, key=None)
    assert found["configured"] is False and found["level"] == "warning" and "ANTHROPIC_API_KEY" in found["hint"]


def test_no_aws_login_at_all_is_not_set_up_either(monkeypatch):
    # an expired SSO login is "signed out"; having none to expire is a different thing, fixed by adding a key
    found = model_with(monkeypatch, "Unable to locate credentials")
    assert found["level"] == "error"  # unchanged for any other error text
    import sys
    import types

    class NoCredentialsError(Exception):
        pass

    class Session:
        def __init__(self, **kwargs):
            pass

        def client(self, name):
            raise NoCredentialsError("Unable to locate credentials")

    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(Session=Session))
    from assistant.config import BEDROCK, ModelConfig
    found = status_module.model_status(ModelConfig(provider=BEDROCK, region="r", profile=None))
    assert found["configured"] is False and found["level"] == "warning"
    assert not found.get("signed_out")


def test_the_model_can_be_named_in_the_environment(monkeypatch):
    from assistant.config import model_config_from_environment
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ASSISTANT_MODEL", raising=False)
    monkeypatch.setenv("SUITE_MODEL", "claude-sonnet-5-5")
    assert model_config_from_environment().model == "claude-sonnet-5-5"
    monkeypatch.setenv("ASSISTANT_MODEL", "claude-opus-5-5")
    assert model_config_from_environment().model == "claude-opus-5-5"  # the assistant's own line wins
    assert model_config_from_environment(model="explicit").model == "explicit"  # and a flag beats both
    monkeypatch.delenv("SUITE_MODEL")
    monkeypatch.delenv("ASSISTANT_MODEL")
    assert model_config_from_environment().model is None


# ---- a chat turn that failed because of the model ---------------------------------------------------------------


@pytest.mark.parametrize("provider,error,says", [
    ("bedrock", Exception("Error when retrieving token from sso: Token has expired and refresh failed"), "login has expired"),
    ("bedrock", type("NoCredentialsError", (Exception,), {})("Unable to locate credentials"), "No model is set up"),
    ("bedrock", ValueError("No AWS region was provided. Set the `aws_region` argument, the `AWS_REGION` / `AWS_DEFAULT_REGION` environment variable"), "No model is set up"),
    ("anthropic", type("AuthenticationError", (Exception,), {})("401"), "API key was refused"),
    ("anthropic", type("NotFoundError", (Exception,), {})("404"), "not available to this API key"),
    ("anthropic", type("APIConnectionError", (Exception,), {})("Connection error."), "could not reach its model"),
    ("anthropic", TypeError("Could not resolve authentication method. Expected an api_key"), "No model is set up"),
])
def test_a_model_failure_in_chat_is_said_in_plain_words(provider, error, says):
    from assistant.config import ModelConfig
    message = status_module.model_failure(error, ModelConfig(provider=provider))
    assert message and says in message and "Settings" in message


def test_a_failure_that_is_not_the_models_is_left_as_it_was():
    from assistant.config import ModelConfig
    assert status_module.model_failure(ValueError("a tool exploded"), ModelConfig(provider="bedrock")) is None
    assert status_module.model_failure(ValueError("x"), None) is None


def test_chat_keeps_the_raw_error_beside_the_plain_one(tmp_path, monkeypatch):
    import assistant.server as server
    from assistant.config import ModelConfig

    async def expired(*_args, **_kwargs):
        raise RuntimeError("Token has expired and refresh failed")
    monkeypatch.setattr(server, "run_turn", expired)
    hub = server.Hub(ToolRegistry([]), config=ModelConfig(provider="bedrock"), context="", audit=FileAuditStore(tmp_path / "a.jsonl"))
    run(hub.run("hello"))
    event = hub.history[-1]
    assert event["type"] == "turn_error" and event["settings"] is True
    assert "login has expired" in event["error"] and "Token has expired" in event["detail"]


# ---- the model's key goes to the one tool that uses it ----------------------------------------------------------


def test_the_models_key_is_not_inherited_by_tools(monkeypatch):
    from assistant.tools import tool_environment
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "token-secret")
    env = tool_environment({"MAIL_AI_STORE": "/x"})
    assert "ANTHROPIC_API_KEY" not in env and "ANTHROPIC_AUTH_TOKEN" not in env
    assert env["MAIL_AI_STORE"] == "/x"  # what tools.yaml injects still arrives


def test_tools_yaml_gives_the_key_to_meet_ai_and_to_no_other_tool(monkeypatch):
    from pathlib import Path
    from assistant.config import load_tool_servers
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret")
    servers = {s.name: s for s in load_tool_servers(Path(__file__).resolve().parent.parent / "tools.yaml")}
    assert servers["meet-ai"].env["ANTHROPIC_API_KEY"] == "sk-ant-secret"
    for name, server in servers.items():
        if name != "meet-ai":
            assert "ANTHROPIC_API_KEY" not in server.env, name


def test_with_no_key_meet_ai_is_given_an_empty_one_which_is_not_a_provider(monkeypatch):
    from pathlib import Path
    from assistant.config import load_tool_servers
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    servers = {s.name: s for s in load_tool_servers(Path(__file__).resolve().parent.parent / "tools.yaml")}
    assert servers["meet-ai"].env["ANTHROPIC_API_KEY"] == ""
