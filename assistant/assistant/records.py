"""What tools made that Shelby keeps (layer 1b of ../../plan.md; shape A, the user's choice of 2026-11-01).

A tool labels each thing it made that is worth keeping -- its kind, its key, labels, its text and its files -- and
the assistant files it here under those labels, without knowing what any of it is: no domain logic, as everywhere
in the assistant. The page that shows them, which does know (Audiobooks knows a chapter), reads them back. One
record per (tool, kind, key): filing the same key again replaces it, as a tool overwriting its own file did.

The text is in the `records` table and each file in the store (files.py), linked by role in `record_files`; with no
database, records.json beside the store's index.json, as everywhere else.
"""

from __future__ import annotations

import json
import os
import tempfile
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from assistant.db import Database


@dataclass(frozen=True)
class Record:
    id: str
    tool: str
    kind: str
    key: str
    labels: dict[str, Any]
    text: str | None
    version: str  # the tool's; the same version is the same thing, and is not filed twice
    files: dict[str, str] = field(default_factory=dict)  # role -> file id in the store
    created: float = 0.0
    updated: float = 0.0


class RecordStore(ABC):
    @abstractmethod
    async def put(self, record: Record) -> None:
        """Write a record, replacing whatever was filed under its (tool, kind, key), files included."""

    @abstractmethod
    async def get(self, tool: str, kind: str, key: str) -> Record | None: ...

    @abstractmethod
    async def by_id(self, record_id: str) -> Record | None: ...

    @abstractmethod
    async def find(self, tool: str, kind: str | None = None) -> list[Record]:
        """A tool's records, newest first, without their text (a listing does not need a book's words)."""

    @abstractmethod
    async def remove(self, record_id: str) -> None: ...


class JsonRecordStore(RecordStore):
    """records.json, written whole to a temporary name and renamed, as index.json is."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _load(self) -> list[Record]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        return [Record(**entry) for entry in raw.get("records", [])]

    def _save(self, records: list[Record]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".records-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                json.dump({"version": 1, "records": [asdict(r) for r in records]}, out, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    async def put(self, record: Record) -> None:
        kept = [r for r in self._load() if (r.tool, r.kind, r.key) != (record.tool, record.kind, record.key)]
        self._save([*kept, record])

    async def get(self, tool: str, kind: str, key: str) -> Record | None:
        return next((r for r in self._load() if (r.tool, r.kind, r.key) == (tool, kind, key)), None)

    async def by_id(self, record_id: str) -> Record | None:
        return next((r for r in self._load() if r.id == record_id), None)

    async def find(self, tool: str, kind: str | None = None) -> list[Record]:
        found = [r for r in self._load() if r.tool == tool and (kind is None or r.kind == kind)]
        return [Record(**{**asdict(r), "text": None}) for r in sorted(found, key=lambda r: r.updated, reverse=True)]

    async def remove(self, record_id: str) -> None:
        self._save([r for r in self._load() if r.id != record_id])


def _when(seconds: float) -> datetime:
    return datetime.fromtimestamp(seconds, timezone.utc)


class PgRecordStore(RecordStore):
    """The `records` and `record_files` tables (migrations/004_records.sql)."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def put(self, record: Record) -> None:
        async with self.database.pool.acquire() as connection, connection.transaction():
            await connection.execute(
                "DELETE FROM records WHERE tool = $1 AND kind = $2 AND key = $3 AND id <> $4",
                record.tool, record.kind, record.key, record.id)
            await connection.execute(
                """INSERT INTO records (id, tool, kind, key, labels, body, version, created_at, updated_at)
                   VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9)
                   ON CONFLICT (id) DO UPDATE SET labels = EXCLUDED.labels, body = EXCLUDED.body,
                       version = EXCLUDED.version, updated_at = EXCLUDED.updated_at""",
                record.id, record.tool, record.kind, record.key, json.dumps(record.labels, ensure_ascii=False),
                record.text, record.version, _when(record.created), _when(record.updated))
            await connection.execute("DELETE FROM record_files WHERE record_id = $1", record.id)
            if record.files:
                await connection.executemany(
                    "INSERT INTO record_files (record_id, role, file_id) VALUES ($1, $2, $3)",
                    [(record.id, role, file_id) for role, file_id in record.files.items()])

    async def _one(self, where: str, *values: Any) -> Record | None:
        row = await self.database.pool.fetchrow(
            f"SELECT id, tool, kind, key, labels, body, version, created_at, updated_at FROM records WHERE {where}",
            *values)
        if row is None:
            return None
        files = await self.database.pool.fetch("SELECT role, file_id FROM record_files WHERE record_id = $1", row["id"])
        return _from_row(row, {f["role"]: f["file_id"] for f in files})

    async def get(self, tool: str, kind: str, key: str) -> Record | None:
        return await self._one("tool = $1 AND kind = $2 AND key = $3", tool, kind, key)

    async def by_id(self, record_id: str) -> Record | None:
        return await self._one("id = $1", record_id)

    async def find(self, tool: str, kind: str | None = None) -> list[Record]:
        rows = await self.database.pool.fetch(
            """SELECT id, tool, kind, key, labels, NULL AS body, version, created_at, updated_at FROM records
               WHERE tool = $1 AND ($2::text IS NULL OR kind = $2) ORDER BY updated_at DESC, id""", tool, kind)
        files = await self.database.pool.fetch(
            """SELECT f.record_id, f.role, f.file_id FROM record_files f JOIN records r ON r.id = f.record_id
               WHERE r.tool = $1 AND ($2::text IS NULL OR r.kind = $2)""", tool, kind)
        by_record: dict[str, dict[str, str]] = {}
        for f in files:
            by_record.setdefault(f["record_id"], {})[f["role"]] = f["file_id"]
        return [_from_row(row, by_record.get(row["id"], {})) for row in rows]

    async def remove(self, record_id: str) -> None:
        await self.database.pool.execute("DELETE FROM records WHERE id = $1", record_id)


def _from_row(row: Any, files: dict[str, str]) -> Record:
    labels = row["labels"]
    return Record(id=row["id"], tool=row["tool"], kind=row["kind"], key=row["key"],
                  labels=json.loads(labels) if isinstance(labels, str) else dict(labels), text=row["body"],
                  version=row["version"], files=files, created=row["created_at"].timestamp(),
                  updated=row["updated_at"].timestamp())


def records_for(database: Database | None, root: Path) -> RecordStore:
    return PgRecordStore(database) if database is not None else JsonRecordStore(root / "records.json")


async def shown(record: Record, index: Any) -> dict[str, Any]:
    """A record as the page and the model see it: everything but its text, each file by id, name and size."""
    stored = {}
    for role, file_id in record.files.items():
        found = await index.get(file_id)
        if found is not None:
            stored[role] = {"id": file_id, "name": found.name, "bytes": found.bytes}
    return {"id": record.id, "tool": record.tool, "kind": record.kind, "key": record.key, "labels": record.labels,
            "files": stored, "created": record.created, "updated": record.updated}


def kept_tools(records: RecordStore, index: Any) -> list:
    """For the model: what tools made that is kept. A tool that let go of what it made (audiobook's finished
    audio) no longer lists it itself, so without this the model would say a rendered book has no audio."""
    from assistant.tools import LocalTool

    async def list_kept(arguments: dict[str, Any]) -> str:
        found = await records.find(str(arguments.get("tool", "")), arguments.get("kind") or None)
        return json.dumps({"records": [await shown(r, index) for r in found[:500]],
                           "more": max(0, len(found) - 500)}, ensure_ascii=False)

    return [LocalTool(
        name="list_kept",
        description=(
            "What a tool made that Shelby keeps, under the labels the tool gave it: for audiobook, every rendered "
            "chapter (kind 'chapter': book, number, title, speed), whole-book M4Bs ('audiobook'), voice samples "
            "('sample'), voices ('voice'), books' titles and authors ('book'), corrections, finished jobs and loose early tests ('other'). Finished audio is "
            "kept here, not by the "
            "tool, so use this to say what has been rendered. `tool` is the tool's name as in its tools' names "
            "(audiobook); `kind` narrows it. Reads only."
        ),
        input_schema={"type": "object", "properties": {"tool": {"type": "string"}, "kind": {"type": "string"}},
                      "required": ["tool"]},
        read_only=True,
        handler=list_kept,
    )]
