"""Is a saved Gmail login still accepted? Asked of Google once, and nothing written.

Google is never called: `ask` is the one seam, replaced by a function that answers as Google would. The file written
or not is checked byte for byte, since "a check must not change what it checks" is the rule this exists under.
"""

import asyncio
import json

import pytest

from mailai.auth import AuthConfig, LoginCheck, check_login
from mailai.mcp_server import ServerPaths, create_mail_ai_server


def config(tmp_path, token=None, client=None, name="token.json") -> AuthConfig:
    token_path, client_path = tmp_path / name, tmp_path / "credentials.json"
    if token is not None:
        token_path.write_text(token if isinstance(token, str) else json.dumps(token))
    if client is not None:
        client_path.write_text(json.dumps(client))
    return AuthConfig(credentials_path=client_path, token_path=token_path)


GOOD = {"refresh_token": "r-1", "client_id": "id-from-token", "client_secret": "s-from-token"}
CLIENT = {"installed": {"client_id": "id-from-file", "client_secret": "s-from-file"}}


def says(answer="", seen=None):
    def ask(body: bytes) -> str:
        if seen is not None:
            seen.append(body.decode())
        return answer
    return ask


def unreachable(body: bytes) -> str:
    raise OSError("Network is unreachable")


def test_a_refresh_token_google_accepts_is_ok(tmp_path):
    assert check_login(config(tmp_path, GOOD), says("")) == LoginCheck("ok")


def test_invalid_grant_is_the_one_answer_that_means_signed_out(tmp_path):
    assert check_login(config(tmp_path, GOOD), says("invalid_grant")) == LoginCheck("dead", "invalid_grant")


def test_any_other_answer_says_so_without_calling_the_login_gone(tmp_path):
    # a wrong client secret is a fault in the setup, and signing in again would not fix it
    assert check_login(config(tmp_path, GOOD), says("invalid_client")) == LoginCheck("unknown", "invalid_client")


def test_google_out_of_reach_is_unknown_not_dead(tmp_path):
    check = check_login(config(tmp_path, GOOD), unreachable)
    assert check.state == "unknown"
    assert "Network is unreachable" in check.detail


def test_no_token_is_missing(tmp_path):
    check = check_login(config(tmp_path, None, CLIENT), says(""))
    assert check.state == "missing"


@pytest.mark.parametrize("token", ["{not json", "[]", json.dumps({"client_id": "x"}), json.dumps({"refresh_token": ""})])
def test_a_token_that_cannot_be_used_is_dead(tmp_path, token):
    assert check_login(config(tmp_path, token, CLIENT), says("")).state == "dead"


def test_no_client_to_ask_with_is_unknown(tmp_path):
    token = {"refresh_token": "r-1"}  # no client id of its own, and no credentials.json beside it
    assert check_login(config(tmp_path, token), says("")).state == "unknown"


def test_the_clients_own_id_in_the_token_wins_over_the_file(tmp_path):
    seen: list[str] = []
    check_login(config(tmp_path, GOOD, CLIENT), says("", seen))
    assert "client_id=id-from-token" in seen[0]
    assert "client_secret=s-from-token" in seen[0]


def test_a_token_without_a_client_uses_credentials_json(tmp_path):
    seen: list[str] = []
    check_login(config(tmp_path, {"refresh_token": "r-1"}, CLIENT), says("", seen))
    assert "client_id=id-from-file" in seen[0]


def test_the_refresh_token_is_what_is_offered(tmp_path):
    seen: list[str] = []
    check_login(config(tmp_path, GOOD), says("", seen))
    assert "grant_type=refresh_token" in seen[0] and "refresh_token=r-1" in seen[0]


@pytest.mark.parametrize("answer", ["", "invalid_grant", "invalid_client"])
def test_a_check_never_changes_the_token_file(tmp_path, answer):
    cfg = config(tmp_path, GOOD, CLIENT)
    before = cfg.token_path.read_bytes()
    check_login(cfg, says(answer))
    assert cfg.token_path.read_bytes() == before


def test_the_detail_never_carries_the_secrets(tmp_path):
    for ask in (says("invalid_grant"), unreachable, says("")):
        check = check_login(config(tmp_path, GOOD, CLIENT), ask)
        assert "r-1" not in check.detail and "s-from-token" not in check.detail


# ---- the tool a person or Settings asks -----------------------------------------------------------------------


@pytest.fixture
def door(tmp_path, monkeypatch):
    """A server whose Google answers what the test says: the reading login and, if asked, the drafting one."""
    answers = {}

    def build(reading, drafting=None):
        answers.update(reading=reading, drafting=drafting)
        reading_cfg = config(tmp_path, GOOD, CLIENT, "reading.json")
        drafting_cfg = config(tmp_path, GOOD, CLIENT, "drafting.json") if drafting is not None else None

        import mailai.mcp_server as door_module

        def fake_check(cfg, ask=None):
            which = "reading" if cfg is reading_cfg else "drafting"
            return answers[which]

        monkeypatch.setattr(door_module, "check_login", fake_check)
        return create_mail_ai_server(ServerPaths(store=tmp_path / "m.sqlite3"), reading_cfg, drafting_cfg)

    return build


def ask_door(server) -> dict:
    result = asyncio.run(server.call_tool("login_status", {}))
    return json.loads("".join(b.text for b in result.content if b.type == "text"))


def test_the_tool_reports_one_login_when_drafting_is_off(door):
    out = ask_door(door(LoginCheck("ok")))
    assert out["state"] == "ok" and out["detail"] == "" and out["service"] == "Gmail"
    assert [l["name"] for l in out["logins"]] == ["Reading"]


def test_the_worst_login_is_the_state_and_names_which(door):
    out = ask_door(door(LoginCheck("ok"), LoginCheck("dead", "invalid_grant")))
    assert out["state"] == "dead"
    assert out["detail"] == "Drafting: invalid_grant"
    assert [l["state"] for l in out["logins"]] == ["ok", "dead"]


@pytest.mark.parametrize("states,worst", [
    (("unknown", "ok"), "unknown"),
    (("ok", "missing"), "missing"),
    (("unknown", "missing"), "missing"),
    (("dead", "missing"), "dead"),
    (("ok", "ok"), "ok"),
])
def test_dead_beats_missing_beats_unknown_beats_ok(door, states, worst):
    assert ask_door(door(LoginCheck(states[0]), LoginCheck(states[1])))["state"] == worst
