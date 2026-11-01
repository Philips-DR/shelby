"""Every login at a glance: the model's and each tool's, checked together, remembered, announced.

One place holds the last check, so Settings, the sidebar and the watcher agree on what is true, and a login going
bad (or coming back) is announced once, whoever noticed it first. The model's login is the assistant's own, so it
is checked here; a tool owns its credentials, so it is asked (`status.tool_logins`) and never read.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

from assistant.config import ModelConfig
from assistant.status import NEEDS_SIGN_IN, SIGN_IN_AGAIN, model_status, tool_logins
from assistant.tools import ToolRegistry
from assistant.watchers import login_notice

Emit = Callable[[dict[str, Any]], Awaitable[None]]


def tool_login_notice(name: str, before: dict[str, Any] | None, found: dict[str, Any]) -> dict[str, Any] | None:
    """The same once-only announcement for a tool's login. `before` is what the last check found, if any. Pure."""
    was_bad = bool(before and before.get("state") in NEEDS_SIGN_IN)
    is_bad = found.get("state") in NEEDS_SIGN_IN
    service = found.get("service") or name
    if is_bad and not was_bad:
        return {"level": "error", "title": f"{service} login needs renewing", "body": SIGN_IN_AGAIN}
    if found.get("state") == "ok" and was_bad:
        return {"level": "success", "title": f"{service} login working again", "body": f"{service} can be used again."}
    return None


class Logins:
    def __init__(self, config: ModelConfig, registry: ToolRegistry, emit: Emit) -> None:
        self.config = config
        self.registry = registry
        self.emit = emit
        # What the last check found: model_status's answer, and each tool's {state, detail, service}, each with
        # the time it was checked. Empty until the first check.
        self.model: dict[str, Any] | None = None
        self.tools: dict[str, dict[str, Any]] = {}
        # Two checks at once (the watcher and a page's Check now) would each announce the same change.
        self._lock = asyncio.Lock()

    async def check(self) -> None:
        async with self._lock:
            model, tools = await asyncio.gather(asyncio.to_thread(model_status, self.config), tool_logins(self.registry))
            now = time.time()
            notices = [login_notice(self.model.get("level") if self.model else None, model)]
            notices += [tool_login_notice(name, self.tools.get(name), found) for name, found in tools.items()]
            self.model = {**model, "checked_at": now}
            self.tools = {name: {**found, "checked_at": now} for name, found in tools.items()}
        for notice in notices:
            if notice:
                await self.emit({"type": "notice", **notice})

    def needs_attention(self) -> bool:
        """Is any login out, as far as the last check could tell? Checked again sooner while one is."""
        return bool(self.model and self.model.get("level") == "error") or any(
            found.get("state") in NEEDS_SIGN_IN for found in self.tools.values())
