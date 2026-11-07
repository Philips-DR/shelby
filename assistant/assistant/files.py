"""The central file store (layer 1b of ../../plan.md): every file Shelby keeps, in one place.

A file lives at <root>/<id>/<name>. The folder is named by an id that says nothing about whose the file is or
which tool it is for; the file inside keeps the name it came with, exactly, because tools use it: docu-ai titles
a Doc after its folder or file, audiobook names a book's audio after its PDF, meet-ai a transcript after its
recording. So a path is still all any tool takes, and no tool learns the store exists.

The record of each file -- what kind it is, who made it, its size and hash, when it came -- is a row in the
`files` table, or, with no database, an entry in index.json at the root (what the tests and a bare checkout
use, as memory.json is for facts). Who owns a file is a column, never a folder: there are no per-user folders.

Markdown is the exception: it is text, so it is kept in the database and not on disk at all (the user's call,
2026-10-31). A `docs` record holds its files' texts (`file_texts`), written in the same transaction as the
record, and a tool that reads one is lent a copy for that one call (texts.py).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from assistant.db import Database

KINDS = ("audio", "book", "voice", "docs", "made")  # made: by a tool, kept under a record (records.py)
MADE_BY = ("user", "assistant", "tool")
_ID = re.compile(r"[0-9a-f]{32}")


@dataclass(frozen=True)
class StoredFile:
    id: str
    kind: str
    name: str  # as it came: a file's own name, or a markdown folder's
    bytes: int
    sha256: str
    made_by: str  # "user": uploaded; "assistant": a draft it wrote, never the user's own material
    created: float  # seconds since the epoch


def is_id(value: str) -> bool:
    return bool(_ID.fullmatch(value))


def path_of(root: Path, record: StoredFile) -> Path:
    return root / record.id / record.name


def new_id() -> str:
    return uuid.uuid4().hex


def new_slot(root: Path) -> tuple[str, Path]:
    """A new, empty folder for one file. Its id is new, so nothing already stored can be overwritten, and a
    second upload with the same name keeps that name."""
    root.mkdir(parents=True, exist_ok=True)
    file_id = new_id()
    folder = root / file_id
    folder.mkdir()
    return file_id, folder


def discard_slot(root: Path, file_id: str) -> None:
    """Remove a slot once it is empty: an upload refused or broken off, or one deleted. A slot still holding
    something (a tool's file beside the upload) is left as it is."""
    if is_id(file_id):
        try:
            (root / file_id).rmdir()
        except OSError:
            pass


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def texts_digest(texts: dict[str, str]) -> tuple[str, int]:
    """A markdown record's hash (each file's name and the hash of its UTF-8 bytes, in name order) and its size."""
    digest = hashlib.sha256()
    size = 0
    for name in sorted(texts):
        data = texts[name].encode("utf-8")
        digest.update(f"{name}\0{hashlib.sha256(data).hexdigest()}\n".encode())
        size += len(data)
    return digest.hexdigest(), size


class FileIndex(ABC):
    """The records, and the text of markdown ones. Every other file is on disk under the root."""

    @abstractmethod
    async def add(self, record: StoredFile, texts: dict[str, str] | None = None) -> None:
        """Record a file; for markdown, with its files' texts by name, in one step."""

    @abstractmethod
    async def get(self, file_id: str) -> StoredFile | None: ...

    @abstractmethod
    async def all(self, kind: str | None = None) -> list[StoredFile]:
        """Newest first."""

    @abstractmethod
    async def texts(self, file_id: str) -> dict[str, str]:
        """A markdown record's files, by name. Empty for anything else."""

    @abstractmethod
    async def text_names(self) -> dict[str, list[str]]:
        """Every markdown record's file names, in order, by id: what a listing shows without the texts."""

    @abstractmethod
    async def remove(self, file_id: str) -> None:
        """Forget a file, and its texts with it."""


class JsonFileIndex(FileIndex):
    """index.json beside the files. Written whole, to a temporary name and then renamed, so a crash part-way
    leaves the old index, never half of one."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _load(self) -> tuple[list[StoredFile], dict[str, dict[str, str]]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return [], {}
        return [StoredFile(**entry) for entry in raw.get("files", [])], raw.get("texts", {})

    def _save(self, records: list[StoredFile], texts: dict[str, dict[str, str]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".index-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                json.dump({"version": 1, "files": [asdict(r) for r in records], "texts": texts}, out,
                          ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    async def add(self, record: StoredFile, texts: dict[str, str] | None = None) -> None:
        records, kept = self._load()
        kept.pop(record.id, None)
        if texts:
            kept[record.id] = dict(texts)
        self._save([*(r for r in records if r.id != record.id), record], kept)

    async def get(self, file_id: str) -> StoredFile | None:
        return next((r for r in self._load()[0] if r.id == file_id), None)

    async def all(self, kind: str | None = None) -> list[StoredFile]:
        found = (r for r in self._load()[0] if kind is None or r.kind == kind)
        return sorted(found, key=lambda r: r.created, reverse=True)

    async def texts(self, file_id: str) -> dict[str, str]:
        return dict(self._load()[1].get(file_id, {}))

    async def text_names(self) -> dict[str, list[str]]:
        return {file_id: sorted(texts) for file_id, texts in self._load()[1].items()}

    async def remove(self, file_id: str) -> None:
        records, texts = self._load()
        texts.pop(file_id, None)
        self._save([r for r in records if r.id != file_id], texts)


_COLUMNS = "id, kind, name, bytes, sha256, made_by, created_at"


def _from_row(row: Any) -> StoredFile:
    return StoredFile(id=row["id"], kind=row["kind"], name=row["name"], bytes=row["bytes"],
                      sha256=row["sha256"], made_by=row["made_by"], created=row["created_at"].timestamp())


class PgFileIndex(FileIndex):
    """The `files` and `file_texts` tables (migrations/002_files.sql, 003_file_texts.sql). Reads the pool when
    called, like the other stores."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def add(self, record: StoredFile, texts: dict[str, str] | None = None) -> None:
        async with self.database.pool.acquire() as connection, connection.transaction():
            await connection.execute(
                f"INSERT INTO files ({_COLUMNS}) VALUES ($1, $2, $3, $4, $5, $6, $7)",
                record.id, record.kind, record.name, record.bytes, record.sha256, record.made_by,
                datetime.fromtimestamp(record.created, timezone.utc))
            if texts:
                await connection.executemany(
                    "INSERT INTO file_texts (file_id, name, body) VALUES ($1, $2, $3)",
                    [(record.id, name, body) for name, body in texts.items()])

    async def get(self, file_id: str) -> StoredFile | None:
        row = await self.database.pool.fetchrow(f"SELECT {_COLUMNS} FROM files WHERE id = $1", file_id)
        return _from_row(row) if row is not None else None

    async def all(self, kind: str | None = None) -> list[StoredFile]:
        rows = await self.database.pool.fetch(
            f"SELECT {_COLUMNS} FROM files WHERE $1::text IS NULL OR kind = $1 ORDER BY created_at DESC, id", kind)
        return [_from_row(row) for row in rows]

    async def texts(self, file_id: str) -> dict[str, str]:
        rows = await self.database.pool.fetch("SELECT name, body FROM file_texts WHERE file_id = $1", file_id)
        return {row["name"]: row["body"] for row in rows}

    async def text_names(self) -> dict[str, list[str]]:
        # Sorted here, not in SQL, whose order follows the database's locale (as db.py found for lower()).
        names: dict[str, list[str]] = {}
        for row in await self.database.pool.fetch("SELECT file_id, name FROM file_texts"):
            names.setdefault(row["file_id"], []).append(row["name"])
        return {file_id: sorted(found) for file_id, found in names.items()}

    async def remove(self, file_id: str) -> None:
        # Its texts go with it (ON DELETE CASCADE).
        await self.database.pool.execute("DELETE FROM files WHERE id = $1", file_id)


async def drop_made(index: FileIndex, root: Path, file_id: str) -> int:
    """Remove a file a tool made (kind `made`), once no record names it: the file, its slot, its row. Never
    anything a person uploaded. Returns its size, 0 if there was nothing of the kind to remove."""
    stored = await index.get(file_id) if is_id(file_id) else None
    if stored is None or stored.kind != "made":
        return 0
    path = path_of(root, stored)
    if path.is_file() and not path.is_symlink():
        path.unlink()
    discard_slot(root, file_id)
    await index.remove(file_id)
    return stored.bytes


def index_for(database: Database | None, root: Path) -> FileIndex:
    """The `files` table with a database, index.json at the root without one."""
    return PgFileIndex(database) if database is not None else JsonFileIndex(root / "index.json")
