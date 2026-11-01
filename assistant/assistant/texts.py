"""Lending stored markdown to a tool, for one call (layer 1b of ../../plan.md).

The text of every markdown upload and draft is in the database, its only lasting copy (files.py). docu-ai and
apply-ai read files by path, and no tool may reach the database -- so the assistant lends: when a call's
arguments name a stored document, a read-only copy of it is written under the texts root just before the call,
and removed as soon as the call ends. A path is still all any tool takes, and nothing of a document stays on
disk between calls.

A document's path is <texts root>/<id>/<its name>/, a folder of its files under their own names, as docu-ai
expects (it titles a Doc after the folder and gives each file a tab), or that folder's one file when it holds
just one. A draft the assistant wrote carries the `.draft` marker apply-ai refuses. That path is what the
listing, the model and the audit log see; it exists on disk only while some call holds it.

Copies are counted: two calls naming one document share one copy, which goes when the last of them ends.
Whatever a backend that stopped mid-call left behind is cleared on start.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Iterator

from assistant import files
from assistant.files import FileIndex, StoredFile

# Beside every draft the assistant wrote. A tool that checks a new draft against "the user's own material"
# (apply-ai) refuses a folder that holds it: a model's earlier draft is not the user's word. A convention in a
# filename, not an import; the record says the same (made_by "assistant"), but apply-ai reads folders.
DRAFT = ".draft"

# What a lend leaves in the root: an id's folder, or one still being written (".<id>-<random>").
_LENT = re.compile(r"\.?[0-9a-f]{32}(-[A-Za-z0-9_]+)?")
_NOT_PLAIN = re.compile(r"[\x00-\x1f/\\]")


def _plain(name: str) -> bool:
    """One ordinary file or folder name. Checked again here, though uploads checked it: this writes to disk."""
    return bool(name) and name not in (".", "..") and not name.startswith(".") and not _NOT_PLAIN.search(name)


def path_for(root: Path, record: StoredFile, names: list[str]) -> Path:
    """What a tool is handed for a document: its one file, or its folder when it holds several (docu-ai gives a
    lone file one tab and no cover, a folder a tab per file and a contents page)."""
    folder = root / record.id / record.name
    return folder / names[0] if len(names) == 1 else folder


def is_under(root: Path, path: str) -> bool:
    try:
        return Path(os.path.normpath(os.path.expanduser(path))).is_relative_to(root)
    except (TypeError, ValueError):
        return False


def _parts(root: Path, path: str) -> tuple[str, ...] | None:
    """(id, name, file) as far as a path names them, or None for a path that is not a document's: elsewhere on
    the machine, climbing out with .., or not starting with an id. Worked out from the text alone, so a path
    that exists on disk for no reason is no different from one that does not."""
    if not path.startswith(("/", "~")) or not is_under(root, path):
        return None
    parts = Path(os.path.normpath(os.path.expanduser(path))).relative_to(root).parts
    if not parts or len(parts) > 3 or not files.is_id(parts[0]):
        return None
    return parts


async def find_text(root: Path, index: FileIndex, path: str) -> tuple[Path, str] | None:
    """One stored markdown file, by the path the listing or a draft gave: (that path, its text). A document's
    folder names its file when it holds just one."""
    parts = _parts(root, path)
    if parts is None or len(parts) < 2:
        return None
    record = await index.get(parts[0])
    if record is None or record.kind != "docs" or parts[1] != record.name:
        return None
    texts = await index.texts(record.id)
    if len(parts) == 3:
        name = parts[2]
    elif len(texts) == 1:
        name = next(iter(texts))
    else:
        return None
    if name not in texts:
        return None
    return root / record.id / record.name / name, texts[name]


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def _remove(path: Path) -> None:
    """A lent copy, read-only as it is: made writable again on the way down, then removed."""
    if path.is_symlink():
        path.unlink()
        return
    if not path.is_dir():
        return
    for folder, _dirs, _files in os.walk(path):
        os.chmod(folder, 0o700)
    shutil.rmtree(path)


def _read_only(path: Path) -> None:
    for folder, _dirs, names in os.walk(path):
        for name in names:
            os.chmod(os.path.join(folder, name), 0o444)
        os.chmod(folder, 0o555)


class Lender:
    """Copies of stored documents, each for as long as some call holds it."""

    def __init__(self, root: Path, index: FileIndex) -> None:
        self.root = root
        self.index = index
        self._held: dict[str, int] = {}
        self._lock = asyncio.Lock()

    def clear(self) -> None:
        """Remove what a backend that stopped mid-call left: only what a lend makes, never anything else that
        happens to be in the folder."""
        if not self.root.is_dir():
            return  # made by the first lend
        for entry in self.root.iterdir():
            if _LENT.fullmatch(entry.name) and entry.is_dir() and not entry.is_symlink():
                _remove(entry)

    @asynccontextmanager
    async def lend(self, arguments: Any) -> AsyncIterator[None]:
        """For the length of one call: a copy of every stored document its arguments name, in any field and at
        any depth (apply-ai takes a list of sources). Anything else is left as it is: a path that names no stored
        document reaches the tool unchanged, and the tool says it is not there."""
        wanted = sorted({parts[0] for value in _strings(arguments) if (parts := _parts(self.root, value))})
        held: list[str] = []
        try:
            for file_id in wanted:
                if await self._take(file_id):
                    held.append(file_id)
            yield
        finally:
            for file_id in held:
                await self._give_back(file_id)

    async def _take(self, file_id: str) -> bool:
        async with self._lock:
            if self._held.get(file_id):
                self._held[file_id] += 1
                return True
            record = await self.index.get(file_id)
            if record is None or record.kind != "docs" or not _plain(record.name):
                return False
            texts = {name: body for name, body in (await self.index.texts(file_id)).items() if _plain(name)}
            if not texts:
                return False
            self._write(record, texts)
            self._held[file_id] = 1
            return True

    async def _give_back(self, file_id: str) -> None:
        async with self._lock:
            self._held[file_id] -= 1
            if not self._held[file_id]:
                del self._held[file_id]
                _remove(self.root / file_id)

    def _write(self, record: StoredFile, texts: dict[str, str]) -> None:
        """Written whole under a temporary name and renamed into place, so a tool never sees half a copy; then
        made read-only, since anything a tool wrote into it would vanish with it."""
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / record.id
        _remove(target)  # a copy no call holds any more: never the case unless a removal failed
        staging = Path(tempfile.mkdtemp(prefix=f".{record.id}-", dir=self.root))
        try:
            folder = staging / record.name
            folder.mkdir()
            for name, body in texts.items():
                (folder / name).write_bytes(body.encode("utf-8"))
            if record.made_by == "assistant":
                (folder / DRAFT).write_text("written by the assistant, not by the user\n", encoding="utf-8")
            staging.rename(target)
        except BaseException:
            _remove(staging)
            raise
        _read_only(target)
