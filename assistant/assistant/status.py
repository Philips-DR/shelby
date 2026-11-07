"""Is everything this assistant depends on actually working? Reads only.

Three kinds of check, each at the level that owns the thing checked:

  * the model login is the assistant's own credential, so it is checked here, live;
  * the network is checked per address family, because the failure that prompted this
    module was IPv6 with no route plus slow IPv4 -- curl got through, Node gave up, and
    the error read like a dead Google login;
  * tools own their credentials, so a tool's health is read from what the assistant
    already records -- whether it is connected, and how its last write call went --
    never by opening another tool's token file. A tool that can say whether its own login is
    still accepted offers a read-only `login_status`, and is asked (`tool_logins`): the
    assistant never learns what a Google token is.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import socket
import time
from typing import Any

from assistant.audit import AuditStore
from assistant.config import BEDROCK, ModelConfig
from assistant.tools import LOCAL_SERVER, ToolRegistry

# Hosts the tools actually call. Google for docu-ai and mail-ai, Bedrock for the model.
ENDPOINTS = {
    "Google": "oauth2.googleapis.com",
    "AWS Bedrock": "bedrock-runtime.us-east-1.amazonaws.com",
}
CONNECT_TIMEOUT = 3.0

# The one command that renews every login that needs it. It is what the person is told, whichever login it was.
SIGN_IN_AGAIN = "Run `./auth` in the shelby folder: it renews only the logins that need it."

# The model through the first-party API, when `ANTHROPIC_API_KEY` is set (it wins over Bedrock): its key is not renewed by a
# browser, it is replaced in `.env`, so the fix is different from `./auth`'s and the words are too.
KEY_HINT = "Put a working key in `.env` as `ANTHROPIC_API_KEY=…`, then run `./start-docker up`."
MODEL_HINT = "Set `SHELBY_MODEL=<a model id this key can use>` in `.env`, then run `./start-docker up`."
NOT_SET_UP_HINT = ("No model is set up. Add `ANTHROPIC_API_KEY=…` to `.env` and run `./start-docker up`. "
                   "Chat and meeting notes need one; everything else works without.")
KEY_CHECK_SECONDS = 15.0
# What boto3 raises when there is no AWS login to try at all (as opposed to one that has lapsed).
NOT_CONFIGURED_ERRORS = ("NoCredentialsError", "ProfileNotFound", "PartialCredentialsError")

# A tool that can say whether its login is still accepted offers this, read-only. Only the name is agreed.
LOGIN_TOOL = "login_status"
LOGIN_STATES = ("ok", "dead", "missing", "unknown")
NEEDS_SIGN_IN = ("dead", "missing")
LOGIN_WAIT = 25.0  # a tool busy with a long call answers late; that is "unknown", not a hang


def _connect_ms(host: str, family: socket.AddressFamily) -> tuple[float | None, str]:
    try:
        infos = socket.getaddrinfo(host, 443, family, socket.SOCK_STREAM)
    except socket.gaierror:
        return None, "no address"
    address = infos[0][4]
    began = time.monotonic()
    try:
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.settimeout(CONNECT_TIMEOUT)
            sock.connect(address)
        return round((time.monotonic() - began) * 1000), ""
    except OSError as error:
        return None, error.strerror or type(error).__name__


def network_status() -> list[dict[str, Any]]:
    out = []
    for label, host in ENDPOINTS.items():
        v4, v4_error = _connect_ms(host, socket.AF_INET)
        v6, v6_error = _connect_ms(host, socket.AF_INET6)
        if v4 is None and v6 is None:
            verdict, level = "unreachable", "error"
        elif v4 is not None and v4 > 400 and v6 is None:
            # Exactly the combination that broke docu-ai: Node's default 250ms attempt window
            # is shorter than the IPv4 connect, and IPv6 is no fallback. docu-ai now allows
            # 2s, but a slow line is still worth seeing.
            verdict, level = "slow, IPv4 only", "warning"
        else:
            verdict, level = "ok", "ok"
        out.append({"name": label, "host": host, "ipv4_ms": v4, "ipv4_error": v4_error,
                    "ipv6_ms": v6, "ipv6_error": v6_error, "verdict": verdict, "level": level})
    return out


def _key_status(config: ModelConfig) -> dict[str, Any]:
    """The first-party route: ask the API whether this key exists and may use this model (one read, nothing spent).

    Three answers apart, because each is fixed differently: the key was refused (replace it), the model is not one this
    key can use (name another), and everything else (the network, the API being down), which no setting fixes.
    Nothing is sent but the key and a model id."""
    base = {"provider": config.provider, "model": config.resolved_model, "profile": None, "region": None}
    if not (config.api_key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return {**base, "level": "warning", "configured": False, "detail": "no API key", "hint": NOT_SET_UP_HINT}
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=config.api_key or None, max_retries=0, timeout=KEY_CHECK_SECONDS)
        client.models.retrieve(config.resolved_model)
    except Exception as error:  # every failure here means the same thing to the reader
        name, message = type(error).__name__, str(error)[:300]
        if name in ("AuthenticationError", "PermissionDeniedError"):
            return {**base, "level": "error", "key_refused": True, "detail": message, "hint": KEY_HINT}
        if name == "NotFoundError":
            return {**base, "level": "error", "model_missing": True, "detail": message, "hint": MODEL_HINT,
                    "available": _available_models(client)}
        return {**base, "level": "error", "detail": message, "hint": ""}
    return {**base, "level": "ok", "detail": "The API key is accepted and the model is available."}


def _available_models(client: Any) -> list[str]:
    try:
        return [str(m.id) for m in client.models.list(limit=20).data][:12]
    except Exception:
        return []


def model_status(config: ModelConfig) -> dict[str, Any]:
    """Can the model be reached with the credentials the assistant holds right now?"""
    if config.provider != BEDROCK:
        return _key_status(config)
    base = {"provider": config.provider, "model": config.resolved_model,
            "profile": config.profile, "region": config.region}
    try:
        import boto3

        session = boto3.Session(profile_name=config.profile, region_name=config.region)
        identity = session.client("sts").get_caller_identity()
    except Exception as error:  # every failure here means the same thing to the reader
        message = str(error)
        if type(error).__name__ in NOT_CONFIGURED_ERRORS:
            return {**base, "level": "warning", "configured": False, "detail": message[:300], "hint": NOT_SET_UP_HINT}
        expired = any(s in message.lower() for s in ("expired", "sso", "token", "refresh"))
        return {**base, "level": "error", "detail": message[:300], "signed_out": expired,
                "hint": SIGN_IN_AGAIN if expired else ""}
    # arn:aws:sts::<account>:assumed-role/AWSReservedSSO_<role>_<hash>/<user> -> <role>
    parts = str(identity.get("Arn", "")).split("/")
    role = re.sub(r"^AWSReservedSSO_(.+)_[0-9a-f]+$", r"\1", parts[1]) if len(parts) > 2 else ""
    return {**base, "level": "ok", "account": identity.get("Account"),
            "role": role, "detail": "Signed in."}


def model_failure(error: BaseException, config: ModelConfig) -> str | None:
    """Plain words for a chat turn that failed because of the model, or None when it failed for another reason.

    A person who sent a message and got a botocore traceback could not tell a lapsed login from a bug. Settings has the
    fix, so this says what happened and where to go; the raw error stays in the event for whoever is reporting it."""
    if config is None:
        return None
    name, text = type(error).__name__, str(error).lower()
    if config.provider == BEDROCK:
        # With no profile and no region at all the SDK complains about the region, which is "no model", not a bug.
        if name in NOT_CONFIGURED_ERRORS or "no aws region" in text:
            return "No model is set up, so the assistant cannot answer. Settings says how to add one."
        if any(s in text for s in ("expired", "sso", "token", "refresh")):
            return "The model's login has expired, so the assistant cannot answer. Settings has the one command that signs back in."
    else:
        if name in ("AuthenticationError", "PermissionDeniedError"):
            return "The Anthropic API key was refused, so the assistant cannot answer. Settings says what to change."
        if name == "NotFoundError":
            return f"The model {config.resolved_model} is not available to this API key. Settings says what to change."
        if name == "TypeError" and "authentication" in text:
            return "No model is set up, so the assistant cannot answer. Settings says how to add one."
    if name in ("APIConnectionError", "APITimeoutError", "EndpointConnectionError", "ConnectTimeoutError", "ConnectError"):
        return "The assistant could not reach its model. Check the network connection (Settings shows what is reachable) and try again."
    return None


async def _ask_login(registry: ToolRegistry, tool: Any) -> dict[str, str]:
    """One tool's answer, as {state, detail, service}. A tool that cannot be asked, or answers nonsense, is
    "unknown": that says nothing was learned, which is not the same as the login being fine."""
    try:
        outcome = await asyncio.wait_for(registry.call(tool, {}), LOGIN_WAIT)
    except asyncio.TimeoutError:
        return {"state": "unknown", "detail": f"no answer in {LOGIN_WAIT:.0f} seconds", "service": ""}
    except Exception as error:  # every failure here means the same thing to the reader
        return {"state": "unknown", "detail": str(error)[:200], "service": ""}
    if outcome.is_error:
        return {"state": "unknown", "detail": outcome.text[:200], "service": ""}
    try:
        answer = json.loads(outcome.text)
    except ValueError:
        answer = None
    if not isinstance(answer, dict) or answer.get("state") not in LOGIN_STATES:
        return {"state": "unknown", "detail": "the tool's answer could not be read", "service": ""}
    return {"state": answer["state"], "detail": str(answer.get("detail") or "")[:300],
            "service": str(answer.get("service") or "")[:60]}


async def tool_logins(registry: ToolRegistry) -> dict[str, dict[str, str]]:
    """Ask every tool that offers a read-only `login_status` whether its login is still accepted, by tool name.

    Only a read-only tool is called, as with an approval's preview: a tool that happened to use this name for
    something that changes things must not be run by a page looking at health."""
    tools = [t for t in registry.tools if t.name == LOGIN_TOOL and t.server != LOCAL_SERVER and t.read_only]
    answers = await asyncio.gather(*(_ask_login(registry, t) for t in tools))
    return {t.server.replace("_", "-"): answer for t, answer in zip(tools, answers)}


async def tools_status(registry: ToolRegistry, audit: AuditStore,
                       logins: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Each tool server: connected, how many tools, how its last write call went, and -- when it has been
    asked -- whether its login is still accepted. A login that is gone is an error, whatever the last call did."""
    last = await audit.last_by_server()

    servers: dict[str, int] = {}
    for tool in registry.tools:
        if tool.server != LOCAL_SERVER:
            servers[tool.server] = servers.get(tool.server, 0) + 1

    out = []
    for server, count in sorted(servers.items()):
        row = last.get(server)
        failed = bool(row and row.get("outcome") not in ("ok", "declined"))
        login = (logins or {}).get(server.replace("_", "-"))
        signed_out = bool(login and login.get("state") in NEEDS_SIGN_IN)
        out.append({
            "name": server.replace("_", "-"),
            "tools": count,
            "level": "error" if signed_out else "warning" if failed else "ok",
            "login": login,
            "last_call": {
                "at": row.get("at"), "tool": row.get("tool"), "outcome": row.get("outcome"),
                "error": (row.get("error") or "")[:300] if failed else "",
            } if row else None,
        })
    return out
