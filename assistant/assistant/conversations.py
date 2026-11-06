"""Conversation history: save, list, load and delete past chat conversations.

With a database, conversations are rows in the `conversations` table. Without one (tests, bare
checkouts), the store holds nothing and every method returns empty -- conversation history is a
database feature, not a file-backed one, because a conversation is a large JSONB blob that does
not benefit from being a flat file the way a single fact or an audit line does.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import uuid4

log = logging.getLogger("assistant.conversations")

TITLE_MAX = 80


def title_from_message(text: str) -> str:
    clean = text.strip().replace("\n", " ")
    if len(clean) <= TITLE_MAX:
        return clean
    return clean[:TITLE_MAX].rsplit(" ", 1)[0] + "…"


def _new_id() -> str:
    return uuid4().hex


class ConversationStore:
    """Postgres-backed conversation history."""

    def __init__(self, database: Any) -> None:
        self._db = database

    async def list(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = await self._db.pool.fetch(
            "SELECT id, title, message_count, created_at, updated_at "
            "FROM conversations ORDER BY updated_at DESC LIMIT $1",
            limit,
        )
        return [
            {
                "id": r["id"],
                "title": r["title"],
                "message_count": r["message_count"],
                "created_at": r["created_at"].isoformat(),
                "updated_at": r["updated_at"].isoformat(),
            }
            for r in rows
        ]

    async def get(self, conversation_id: str) -> dict[str, Any] | None:
        row = await self._db.pool.fetchrow(
            "SELECT id, title, events, message_count, created_at, updated_at "
            "FROM conversations WHERE id = $1",
            conversation_id,
        )
        if row is None:
            return None
        return {
            "id": row["id"],
            "title": row["title"],
            "events": json.loads(row["events"]),
            "message_count": row["message_count"],
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat(),
        }

    async def save(
        self,
        conversation_id: str,
        title: str,
        events: list[dict[str, Any]],
        message_count: int,
    ) -> str:
        await self._db.pool.execute(
            "INSERT INTO conversations (id, title, events, message_count) "
            "VALUES ($1, $2, $3::jsonb, $4) "
            "ON CONFLICT (id) DO UPDATE SET title = $2, events = $3::jsonb, "
            "message_count = $4, updated_at = clock_timestamp()",
            conversation_id,
            title,
            json.dumps(events, default=str),
            message_count,
        )
        return conversation_id

    async def delete(self, conversation_id: str) -> bool:
        result = await self._db.pool.execute(
            "DELETE FROM conversations WHERE id = $1", conversation_id
        )
        return result == "DELETE 1"

    async def rename(self, conversation_id: str, title: str) -> bool:
        result = await self._db.pool.execute(
            "UPDATE conversations SET title = $1, updated_at = clock_timestamp() WHERE id = $2",
            title,
            conversation_id,
        )
        return result == "UPDATE 1"


class NullConversationStore:
    """No database: conversation history is not available."""

    async def list(self, limit: int = 50) -> list[dict[str, Any]]:
        return []

    async def get(self, conversation_id: str) -> dict[str, Any] | None:
        return None

    async def save(self, conversation_id: str, title: str, events: list[dict[str, Any]], message_count: int) -> str:
        return conversation_id

    async def delete(self, conversation_id: str) -> bool:
        return False

    async def rename(self, conversation_id: str, title: str) -> bool:
        return False
