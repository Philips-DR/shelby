"""Taking what a tool made into Shelby's keeping (layer 1b of ../../plan.md, phase B; shape A).

The tool works at its own bench, in its own folders, alone or in Shelby; it never learns the store or the
database exists. A tool that makes things worth keeping offers two tools by agreed name, as `login_status` is
agreed (only the names; a tool without them is simply not asked):

- `inventory`, read-only: everything it holds that should be kept, as items
  {kind, key, labels, text, version, files: [{path, role}], release}.
- `release`: delete these working copies, each named by its path and the SHA-256 of the copy the assistant filed.
  The tool checks the hash before deleting, so only something already filed can go.

Collecting copies each file into the store (checked by hash), files the record under (tool, kind, key) without
reading inside it, removes a replaced record's old files from the store, and then releases what the tool said it
may let go. An item whose version is already filed is not filed again. Files are taken only from the folders the
tool declared in tools.yaml (`files:`), so a tool cannot hand over something of anyone else's. One collection at a
time; asked for again while one runs, it runs once more after.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from assistant import files
from assistant.files import FileIndex, StoredFile
from assistant.records import Record, RecordStore
from assistant.tools import QUALIFIER, ToolRegistry

log = logging.getLogger(__name__)

INVENTORY = "inventory"
RELEASE = "release"
MAX_TEXT = 5 * 1024**2
MAX_LABELS = 64 * 1024
MAX_NAME = 500


class ItemError(ValueError):
    """An item the tool described in a way that cannot be filed: skipped, and said so."""


def _text(value: Any, what: str, limit: int = MAX_NAME) -> str:
    if not isinstance(value, str) or not value or len(value) > limit or "\x00" in value:
        raise ItemError(f"{what} must be a short piece of text")
    return value


def checked(item: Any) -> dict[str, Any]:
    """An inventory item as the tool must give it, or ItemError. The assistant does not know what any of it means;
    it checks only the shape, and that nothing in it could not be kept."""
    if not isinstance(item, dict):
        raise ItemError("an item must be an object")
    labels = item.get("labels", {})
    if not isinstance(labels, dict) or len(json.dumps(labels, ensure_ascii=False)) > MAX_LABELS:
        raise ItemError("labels must be a small object")
    if "\\u0000" in json.dumps(labels):
        raise ItemError("labels must hold no NUL")
    text = item.get("text")
    if text is not None and (not isinstance(text, str) or len(text) > MAX_TEXT or "\x00" in text):
        raise ItemError("text must be text, under 5 MB, with no NUL")
    found = item.get("files", [])
    if not isinstance(found, list):
        raise ItemError("files must be a list")
    roles: dict[str, str] = {}
    for f in found:
        if not isinstance(f, dict):
            raise ItemError("each file must be an object")
        role = _text(f.get("role"), "a file's role", 64)
        if role in roles:
            raise ItemError(f"two files play the role {role!r}")
        roles[role] = _text(f.get("path"), "a file's path", 4096)
    return {"kind": _text(item.get("kind"), "kind", 64), "key": _text(item.get("key"), "key"),
            "labels": labels, "text": text, "version": _text(item.get("version"), "version"),
            "files": roles, "release": item.get("release") is True}


class Collector:
    def __init__(self, registry: ToolRegistry, index: FileIndex, records: RecordStore, root: Path,
                 emit: Callable[[dict[str, Any]], Awaitable[None]] | None = None) -> None:
        self.registry = registry
        self.index = index
        self.records = records
        self.root = root
        self.emit = emit
        self._lock = asyncio.Lock()
        self._again: set[str] = set()
        self._running: dict[str, asyncio.Task] = {}

    def offering(self) -> list[str]:
        """The tools that keep things: those with a read-only `inventory`. Only a read-only one is called, as with
        `login_status`: a tool that used the name for something that changes things must not be run by this."""
        return sorted({t.server for t in self.registry.tools
                       if t.name == INVENTORY and t.read_only and t.server != "assistant"})

    def soon(self, server: str) -> None:
        """Collect from this tool, in the background; asked again while it runs, once more after."""
        if server not in self.offering():
            return
        running = self._running.get(server)
        if running is not None and not running.done():
            self._again.add(server)
            return

        async def go() -> None:
            while True:
                self._again.discard(server)
                try:
                    await self.collect(server)
                except Exception:  # a failed collection must not take the server with it; the next one retries
                    log.exception("collecting from %s failed", server)
                if server not in self._again:
                    return

        self._running[server] = asyncio.ensure_future(go())

    async def stop(self) -> None:
        """On shutdown. A copy cut off part-way is cleared away (`_store`); the next start files it again."""
        tasks = [t for t in self._running.values() if not t.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def collect(self, server: str) -> dict[str, Any]:
        async with self._lock:
            return await self._collect(server)

    async def _collect(self, server: str) -> dict[str, Any]:
        inventory = self.registry.find(f"{server}{QUALIFIER}{INVENTORY}")
        if inventory is None or not inventory.read_only:
            return {"filed": 0}
        outcome = await self.registry.call(inventory, {})
        if outcome.is_error:
            raise RuntimeError(f"{server} inventory failed: {outcome.text[:200]}")
        items = json.loads(outcome.text).get("items", [])
        folders = [f.resolve() for f in self.registry.folders_of(server)]
        filed = skipped = 0
        refused: list[str] = []
        to_release: list[dict[str, str]] = []
        for raw in items if isinstance(items, list) else []:
            try:
                item = checked(raw)
                done, releasing = await self._file(server, item, folders)
            except (ItemError, OSError) as error:
                refused.append(f"{raw.get('kind') if isinstance(raw, dict) else '?'} "
                               f"{raw.get('key') if isinstance(raw, dict) else '?'}: {error}")
                continue
            filed += done
            skipped += not done
            to_release += releasing
        released = await self._release(server, to_release)
        if refused:
            log.warning("%s: %d item(s) not filed: %s", server, len(refused), "; ".join(refused[:5]))
        if (filed or released) and self.emit is not None:
            await self.emit({"type": "records_changed", "tool": server, "filed": filed})
        return {"filed": filed, "skipped": skipped, "released": released, "refused": refused}

    def _source(self, path: str, folders: list[Path]) -> Path:
        """A file the tool named, only if it is a plain file inside a folder the tool declared."""
        candidate = Path(path)
        if not candidate.is_absolute() or candidate.is_symlink():
            raise ItemError(f"{path} is not a file this tool may hand over")
        resolved = candidate.resolve()
        if not resolved.is_file() or not any(resolved.is_relative_to(f) for f in folders):
            raise ItemError(f"{path} is not a file in a folder this tool declared")
        return resolved

    async def _file(self, server: str, item: dict[str, Any], folders: list[Path]) -> tuple[bool, list[dict[str, str]]]:
        """File one item. Returns whether it was filed (False: that version already was) and what may be released."""
        existing = await self.records.get(server, item["kind"], item["key"])
        if existing is not None and existing.version == item["version"]:
            # Already filed. If the tool still holds it, a release earlier did not happen: ask again.
            return False, await self._releasable(item, existing.files) if item["release"] else []
        sources = {role: self._source(path, folders) for role, path in item["files"].items()}
        made: dict[str, str] = {}
        try:
            for role, source in sources.items():
                made[role] = await self._store(source)
        except BaseException:
            for file_id in made.values():
                await self._drop(file_id)
            raise
        now = time.time()
        await self.records.put(Record(
            id=existing.id if existing else files.new_id(), tool=server, kind=item["kind"], key=item["key"],
            labels=item["labels"], text=item["text"], version=item["version"], files=made,
            created=existing.created if existing else now, updated=now))
        for old in (existing.files.values() if existing else []):
            if old not in made.values():
                await self._drop(old)
        return True, await self._releasable(item, made) if item["release"] else []

    async def _releasable(self, item: dict[str, Any], filed: dict[str, str]) -> list[dict[str, str]]:
        out = []
        for role, path in item["files"].items():
            record = await self.index.get(filed[role]) if role in filed else None
            if record is not None and Path(path).is_file():
                out.append({"path": path, "sha256": record.sha256})
        return out

    async def _store(self, source: Path) -> str:
        """A copy of a tool's file in a slot of its own, under its own name, checked against the original."""
        sha256 = files.sha256_of(source)
        file_id, slot = files.new_slot(self.root)
        target = slot / source.name
        try:
            shutil.copy2(source, target)
            if files.sha256_of(target) != sha256:
                raise OSError(f"{source.name} did not copy intact")
            stat = target.stat()
            await self.index.add(StoredFile(id=file_id, kind="made", name=source.name, bytes=stat.st_size,
                                            sha256=sha256, made_by="tool", created=stat.st_mtime))
        except BaseException:
            target.unlink(missing_ok=True)
            files.discard_slot(self.root, file_id)
            raise
        return file_id

    async def _drop(self, file_id: str) -> None:
        await files.drop_made(self.index, self.root, file_id)

    async def _release(self, server: str, wanted: list[dict[str, str]]) -> int:
        release = self.registry.find(f"{server}{QUALIFIER}{RELEASE}")
        if not wanted or release is None:
            return 0
        outcome = await self.registry.call(release, {"files": wanted})
        if outcome.is_error:
            log.warning("%s release failed: %s", server, outcome.text[:200])
            return 0
        try:
            return len(json.loads(outcome.text).get("released", []))
        except (json.JSONDecodeError, AttributeError):
            return 0
