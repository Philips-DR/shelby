"""What the model was asked and what it took: one row per request to a model.

Two things reach it. The assistant's own chat steps are counted where the answer comes back
(`session.run_turn`). A tool that calls a model itself (meet-ai's notes and minutes) says so in its result,
under one agreed key, `model_usage`, and the assistant records that (`usage_from_result`): the tool
keeps working alone, and the assistant learns no tool's business. Only the name and its four fields are
agreed, as with `login_status`.

Tokens are stored, dollars are not: `cost_usd` is worked out when a row is read, from the table below, so
a corrected price fixes the past too. A price is an estimate, never a bill (see PRICES).

A JSON-lines file (tests, a bare checkout) or the `model_usage` table (the containers), like the audit log.
"""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from assistant.db import Database

log = logging.getLogger("assistant.usage")

CHAT = "chat"

# Anthropic's own list prices for its own API, in dollars per million tokens: (input, output). From the model
# list the claude-api reference carried on 2026-11-03. Only models whose price is in that list are here: a
# model not here is counted in tokens and shown with no price, never with a guessed one.
#
# **An estimate.** A bill differs where a price changes in the middle of a day, and on Amazon Bedrock, which
# prices a model itself (the Bedrock route ends at the end of November 2026). Neither assistant nor meet-ai asks
# for prompt caching, which is why cache tokens have no column. Haiku is left out on purpose: its price depends
# on the size of the prompt.
PRICES_AS_OF = "2026-11-03"
PRICES: dict[str, tuple[float, float]] = {
    "claude-fable-5-2": (8.00, 40.00),
    "claude-fable-5-1": (10.00, 50.00),
    "claude-fable-5": (10.00, 50.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-6": (5.00, 25.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-sonnet-4-6": (3.00, 15.00),
}

# "us.anthropic.claude-opus-4-6-v1" and "anthropic.claude-opus-4-6-v1:0" are Bedrock's names for
# "claude-opus-4-6"; a dated "claude-opus-4-5-20251101" is that model too.
_MODEL_ID = re.compile(
    r"^(?:[a-z]{2,6}\.)?(?:anthropic\.)?(?P<id>claude-[a-z0-9-]+?)(?:-v\d+(?::\d+)?)?(?:-\d{8})?(?:@\w+)?$"
)

FIELDS = ("model", "provider", "input_tokens", "output_tokens")


def price_key(model: str) -> str:
    """The first-party id a provider's name for a model stands for: `claude-opus-4-6` for Bedrock's
    `us.anthropic.claude-opus-4-6-v1`. A name that is not one of those is returned as it came."""
    match = _MODEL_ID.match(model.strip().lower())
    return match.group("id") if match else model.strip().lower()


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Dollars at list price, or None for a model with no price here."""
    prices = PRICES.get(price_key(model))
    if prices is None:
        return None
    return round((input_tokens * prices[0] + output_tokens * prices[1]) / 1_000_000, 6)


def _count(value: Any) -> int | None:
    """A whole number of tokens, or None for anything else (a bool, a float, a string, a negative)."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def usage_from_result(text: str) -> dict[str, Any] | None:
    """The `model_usage` a tool put in its result, or None. The tool's output is untrusted: anything that is
    not exactly a model, a provider and two whole token counts is ignored, never half-recorded."""
    if '"model_usage"' not in text:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    reported = data.get("model_usage") if isinstance(data, dict) else None
    if not isinstance(reported, dict):
        return None
    model, provider = reported.get("model"), reported.get("provider")
    tokens_in, tokens_out = _count(reported.get("input_tokens")), _count(reported.get("output_tokens"))
    if not (isinstance(model, str) and model and isinstance(provider, str) and provider
            and tokens_in is not None and tokens_out is not None):
        return None
    return {"model": model, "provider": provider, "input_tokens": tokens_in, "output_tokens": tokens_out}


def usage_of(response: Any) -> tuple[int, int] | None:
    """(input, output) tokens from an API response, or None if it carries no usage."""
    usage = getattr(response, "usage", None)
    tokens_in, tokens_out = _count(getattr(usage, "input_tokens", None)), _count(getattr(usage, "output_tokens", None))
    return None if tokens_in is None or tokens_out is None else (tokens_in, tokens_out)


def priced(row: dict[str, Any]) -> dict[str, Any]:
    """A stored row with its estimated cost added (None when the model has no price here)."""
    return {**row, "cost_usd": cost_usd(row["model"], row["input_tokens"], row["output_tokens"])}


def _stamped(fields: dict[str, Any]) -> dict[str, Any]:
    return {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **fields}


class UsageStore(ABC):
    @abstractmethod
    async def record(self, **fields: Any) -> None:
        """Add one row (source, model, provider, input_tokens, output_tokens). Never raises: counting
        tokens must not break the work."""

    @abstractmethod
    async def recent(self, limit: int) -> list[dict[str, Any]]:
        """The newest `limit` rows, newest first, each as stored (no cost)."""


class FileUsageStore(UsageStore):
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    async def record(self, **fields: Any) -> None:
        row = _stamped(fields)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError:
            pass

    async def recent(self, limit: int) -> list[dict[str, Any]]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        rows: list[dict[str, Any]] = []
        for line in reversed(lines[-limit:]):
            try:
                row = json.loads(line)
            except ValueError:
                continue  # one corrupt line must not hide the rest
            if isinstance(row, dict) and all(key in row for key in ("at", "source", *FIELDS)):
                rows.append(row)
        return rows


_COLUMNS = "used_at, source, model, provider, input_tokens, output_tokens"


class PgUsageStore(UsageStore):
    def __init__(self, database: "Database") -> None:
        self._db = database

    async def record(self, **fields: Any) -> None:
        row = _stamped(fields)
        try:
            await self._db.pool.execute(
                f"INSERT INTO model_usage ({_COLUMNS}) VALUES ($1, $2, $3, $4, $5, $6)",
                datetime.fromisoformat(row["at"]), row["source"], row["model"], row["provider"],
                row["input_tokens"], row["output_tokens"])
        except Exception:
            log.warning("a model usage row could not be written", exc_info=True)

    async def recent(self, limit: int) -> list[dict[str, Any]]:
        try:
            records = await self._db.pool.fetch(
                f"SELECT {_COLUMNS} FROM model_usage ORDER BY used_at DESC, id DESC LIMIT $1", limit)
        except Exception:
            log.warning("model usage could not be read", exc_info=True)
            return []
        return [{"at": r["used_at"].astimezone(timezone.utc).isoformat(timespec="seconds"),
                 **{key: r[key] for key in ("source", *FIELDS)}} for r in records]


def usage_for(database: "Database | None", path: Path) -> UsageStore:
    """The database's store when there is a database, the file otherwise (not connected yet: it reads the
    pool when it is used)."""
    return FileUsageStore(path) if database is None else PgUsageStore(database)


def usage_path_for(audit_path: Path) -> Path:
    """Beside the audit file, so one setting places both and a test's temporary folder holds its own."""
    return Path(audit_path).with_name("usage.jsonl")


async def count_response(store: UsageStore | None, config: Any, response: Any, source: str = CHAT) -> None:
    """Record one model response, if there is somewhere to and it says what it took."""
    if store is None:
        return
    tokens = usage_of(response)
    if tokens is not None:
        await store.record(source=source, model=config.resolved_model, provider=config.provider,
                           input_tokens=tokens[0], output_tokens=tokens[1])


async def count_result(store: UsageStore | None, tool: str, text: str) -> None:
    """Record the `model_usage` a tool reported in its result, if it reported one."""
    if store is None:
        return
    reported = usage_from_result(text)
    if reported is not None:
        await store.record(source=tool, **reported)
