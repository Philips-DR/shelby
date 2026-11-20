"""Which way Chat and meeting notes reach a model: the Anthropic API key or Amazon Bedrock, chosen in Settings
(the user's request, 2026-11-20). Before, `.env` decided and could not be changed without a restart: an API key
there always won.

- **Kept in a small file, not the database** (`settings.json` beside memory, `/data/assistant/settings.json` in the
  containers): `./auth` runs on the host, where the database cannot be reached (it publishes no port), and has to
  know which login is in use, so that it renews the AWS one only when Bedrock is the route.
- **A tool follows it through one agreed name, `model_route`**, as with `login_status` and `inventory`: a tool that
  calls a model itself (meet-ai, for notes and minutes) offers it, takes `{provider, model}`, and uses them from its
  next call. Its credentials stay its own, injected at launch as before; only the choice moves. Called on start, so a
  restart keeps the choice, and on every switch. The assistant learns nothing else of the tool.
- **No choice saved means `.env` decides**, as it always has (`config.resolve_provider`: a key wins).
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from assistant.config import ANTHROPIC, BEDROCK, PROVIDERS, ModelConfig, model_config_from_environment
from assistant.tools import LOCAL_SERVER, ToolRegistry

ROUTE_TOOL = "model_route"
KEY = "model_route"
# A tool is told in a moment; one that does not answer in this long is said to have not followed.
TELL_WAIT = 10.0
LABELS = {ANTHROPIC: "Anthropic API key", BEDROCK: "Amazon Bedrock"}


class RouteError(Exception):
    """A route that cannot be chosen, said for the person choosing it."""


def load(path: Path) -> str | None:
    """The saved route, or None for "as .env says". A missing, unreadable or hand-broken file is None: the backend
    must start whatever is in it."""
    try:
        saved = json.loads(path.read_text(encoding="utf-8")).get(KEY)
    except (OSError, ValueError, AttributeError):
        return None
    return saved if saved in PROVIDERS else None


def save(path: Path, provider: str) -> None:
    """Write the route, keeping anything else in the file. Written whole and renamed into place, so a crash halfway
    leaves the old file, never half of one."""
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(current, dict):
            current = {}
    except (OSError, ValueError):
        current = {}
    current[KEY] = provider
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    part.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    os.replace(part, path)


def unavailable(provider: str) -> str | None:
    """Why a route cannot be chosen at all, or None. Only what is missing from the setup: whether its login still
    works is the model check's to say (status.model_status), and a dead login can be renewed with ./auth."""
    if provider == ANTHROPIC and not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return "No API key in .env (ANTHROPIC_API_KEY)."
    if provider == BEDROCK and not (os.environ.get("AWS_PROFILE") or os.environ.get("AWS_ACCESS_KEY_ID")):
        return "No AWS login in .env (AWS_PROFILE)."
    return None


def choices(current: ModelConfig, saved: str | None) -> dict[str, Any]:
    """What Settings shows: the route in use, whether it was chosen there, and each route with its model."""
    return {
        "current": current.provider,
        "saved": saved,
        "choices": [{"provider": p, "label": LABELS[p], "model": model_config_from_environment(p).resolved_model,
                     "unavailable": unavailable(p)} for p in PROVIDERS],
    }


def check(provider: Any) -> str:
    if provider not in PROVIDERS:
        raise RouteError(f"Not a way to reach a model: {provider!r}. Choose one of {', '.join(PROVIDERS)}.")
    reason = unavailable(provider)
    if reason:
        raise RouteError(reason)
    return provider


async def tell_tools(registry: ToolRegistry, config: ModelConfig) -> dict[str, str]:
    """Tell every tool that offers `model_route` which provider and model to use: by tool name, "ok" or why not.
    Never raises. Only a tool that declares it changes something is called: a read-only one by this name would be
    a tool that misunderstood the name, and saying "ok" for it would be a lie."""
    tools = [t for t in registry.tools if t.name == ROUTE_TOOL and t.server != LOCAL_SERVER and not t.read_only]
    arguments = {"provider": config.provider, "model": config.resolved_model}

    async def tell(tool) -> str:
        try:
            outcome = await asyncio.wait_for(registry.call(tool, dict(arguments)), TELL_WAIT)
        except TimeoutError:
            return f"did not answer in {TELL_WAIT:g} s"
        except Exception as error:  # a tool server that has died, or anything else: said, never raised
            return f"failed: {error}"[:300]
        if outcome.is_error:
            return f"refused: {outcome.text}"[:300]
        # A tool may also refuse in its answer, as meet-ai does every refusal: {"error": "..."}.
        try:
            answer = json.loads(outcome.text)
        except ValueError:
            answer = None
        if isinstance(answer, dict) and answer.get("error"):
            return f"refused: {answer['error']}"[:300]
        return "ok"

    answers = await asyncio.gather(*(tell(t) for t in tools))
    return {t.server.replace("_", "-"): answer for t, answer in zip(tools, answers)}
