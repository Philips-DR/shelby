"""Files a person hands the assistant: audio to transcribe, markdown to turn into a Doc,
a PDF to make into an audiobook, a recording to clone a voice from.

Each file is kept in the central file store (files.py): in a new folder of its own, under its own name, with a
record in the `files` table. An upload still ends in a path, and a path is what every tool already takes --
so a file uploaded here and a file that was always on disk are the same thing to every tool, and the tools
never learn the store exists. Markdown is text, so it goes into the database instead, and a tool reading it
is lent a copy for the call (texts.py).

Everything a browser sends is a name to distrust. Every path component is checked, the result must resolve
inside the store, and a file is written to a `.part` name and renamed only once complete, so a half-received
upload is never listed or transcribed. Deleting is by id, as the listing gave it, never by a path.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

from assistant import files, texts
from assistant.files import FileIndex, StoredFile
from assistant.texts import DRAFT

AUDIO_EXTS = {".m4a", ".mp3", ".wav", ".flac", ".ogg", ".opus", ".webm", ".mp4", ".aac", ".wma"}
DOC_EXTS = {".md"}
BOOK_EXTS = {".pdf"}
# A two-hour meeting is ~115 MB as m4a and ~350 MB as FLAC; four hours of WAV is ~2.5 GB.
MAX_AUDIO_BYTES = 4 * 1024**3
# All of one batch of markdown, which is held in memory until it is finished. A long CV is 10 KB.
MAX_DOC_BYTES = 20 * 1024**2
# Batches started and not finished; the oldest is dropped to make room, and any left for an hour.
MAX_OPEN_BATCHES = 5
BATCH_TIMEOUT = 3600
# A scanned book is a photograph of every page.
MAX_BOOK_BYTES = 1024**3
# A voice is cloned from about 30 seconds; a long recording is searched for its best window.
MAX_VOICE_BYTES = 512 * 1024**2
PART = ".part"

# The extensions each kind is listed, and may be deleted, by.
EXTENSIONS = {"audio": AUDIO_EXTS, "book": BOOK_EXTS, "voice": AUDIO_EXTS}
# Where each kind appears in the listing.
LISTED = {"audio": "audio", "book": "books", "voice": "voices"}

_BAD_COMPONENT = re.compile(r"[\x00-\x1f/\\]")


class UploadError(Exception):
    """Something the person can fix, phrased for them."""


def _clean_component(name: str) -> str:
    name = name.strip()
    if not name or name in (".", "..") or _BAD_COMPONENT.search(name) or name.startswith("."):
        raise UploadError(f"not an acceptable file or folder name: {name!r}")
    return name


def _inside(root: Path, candidate: Path) -> Path:
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise UploadError("that path would land outside the file store")
    return resolved


def _new_file(root: Path, name: str) -> tuple[str, Path]:
    file_id, folder = files.new_slot(root)
    return file_id, _inside(root, folder / name)


def audio_target(root: Path, name: str) -> tuple[str, Path]:
    name = _clean_component(Path(name).name)
    if Path(name).suffix.lower() not in AUDIO_EXTS:
        raise UploadError(f"{name} is not an audio file this can transcribe "
                          f"({', '.join(sorted(AUDIO_EXTS))})")
    return _new_file(root, name)


def book_target(root: Path, name: str) -> tuple[str, Path]:
    name = _clean_component(Path(name).name)
    if Path(name).suffix.lower() not in BOOK_EXTS:
        raise UploadError(f"{name} is not a PDF")
    return _new_file(root, name)


def voice_target(root: Path, name: str) -> tuple[str, Path]:
    """A recording to clone a voice from. Its own kind, not `audio`, which is meetings: a voice sample must
    not turn up in the list of things to transcribe."""
    name = _clean_component(Path(name).name)
    if Path(name).suffix.lower() not in AUDIO_EXTS:
        raise UploadError(f"{name} is not an audio file ({', '.join(sorted(AUDIO_EXTS))})")
    return _new_file(root, name)


def document_name(name: str) -> str:
    """A set of markdown's name: the uploaded folder's own, or the file's without `.md`. It becomes the Doc's
    default title, so it is kept as it came."""
    return _clean_component(Path(name).name.removesuffix(".md").removesuffix(".MD") or "Documents")


def text_of(name: str, data: bytes) -> str:
    """Markdown as the database keeps it: UTF-8 text, exactly as sent. A NUL is refused, since no text holds one
    and PostgreSQL's text type cannot."""
    if not data:
        raise UploadError(f"{name} is empty")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise UploadError(f"{name} is not UTF-8 text") from None
    if "\x00" in text:
        raise UploadError(f"{name} is not a text file")
    return text


@dataclass
class _Batch:
    name: str
    started: float
    texts: dict[str, str] = field(default_factory=dict)
    size: int = 0


class DocBatches:
    """Markdown arriving a file at a time, held in memory until the batch is finished. Only then is anything
    stored, the record and every text in one step, so an upload broken off part-way leaves nothing behind."""

    def __init__(self) -> None:
        self._open: dict[str, _Batch] = {}

    def start(self, name: str) -> str:
        name = document_name(name)
        now = time.monotonic()
        for batch, held in list(self._open.items()):
            if now - held.started > BATCH_TIMEOUT:
                del self._open[batch]
        while len(self._open) >= MAX_OPEN_BATCHES:
            del self._open[next(iter(self._open))]  # the oldest
        batch = files.new_id()
        self._open[batch] = _Batch(name, started=now)
        return batch

    async def receive(self, batch: str, name: str, chunks: AsyncIterator[bytes]) -> tuple[str, int]:
        """One markdown file, at the top level of its batch -- docu-ai reads only a folder's top level, so a
        nested file would upload and then silently do nothing. Returns its name, as kept, and its size."""
        held = self._open.get(batch) if files.is_id(batch) else None
        if held is None:
            raise UploadError(f"no upload batch {batch!r}")
        name = _clean_component(name)
        if Path(name).suffix.lower() not in DOC_EXTS:
            raise UploadError(f"{name} is not a markdown (.md) file")
        if name in held.texts:
            raise UploadError(f"{name} is already in this upload")
        data = bytearray()
        async for chunk in chunks:
            data += chunk
            if held.size + len(data) > MAX_DOC_BYTES:
                raise UploadError(f"{name} takes this upload over the {MAX_DOC_BYTES // 1024**2} MB limit")
        text = text_of(name, bytes(data))
        if name in held.texts:  # the same name, sent twice at once
            raise UploadError(f"{name} is already in this upload")
        held.texts[name] = text
        held.size += len(data)
        return name, len(data)

    async def finish(self, index: FileIndex, batch: str) -> tuple[StoredFile, list[str]]:
        """Store a batch: its record and its texts together. Finishing twice is the same as once."""
        held = self._open.pop(batch, None) if files.is_id(batch) else None
        if held is None:
            record = await index.get(batch) if files.is_id(batch) else None
            if record is not None and record.kind == "docs":
                return record, (await index.text_names()).get(batch, [])
            raise UploadError(f"no upload batch {batch!r}")
        if not held.texts:
            raise UploadError("none of those files were markdown (.md)")
        sha256, size = files.texts_digest(held.texts)
        record = StoredFile(id=batch, kind="docs", name=held.name, bytes=size, sha256=sha256,
                            made_by="user", created=time.time())
        await index.add(record, held.texts)
        return record, sorted(held.texts)


async def receive(target: Path, chunks: AsyncIterator[bytes], limit: int) -> tuple[int, str]:
    """Stream to `<target>.part`, then rename. Nothing half-written is ever visible. Returns the size and
    the SHA-256, worked out on the way in."""
    part = target.with_name(target.name + PART)
    digest = hashlib.sha256()
    size = 0
    try:
        with part.open("xb") as out:
            async for chunk in chunks:
                size += len(chunk)
                if size > limit:
                    raise UploadError(f"{target.name} is larger than the {limit // 1024**2} MB limit")
                digest.update(chunk)
                out.write(chunk)
        if size == 0:
            raise UploadError(f"{target.name} is empty")
        part.rename(target)
        return size, digest.hexdigest()
    except BaseException:
        part.unlink(missing_ok=True)
        raise


async def keep(index: FileIndex, file_id: str, kind: str, target: Path, size: int, sha256: str) -> StoredFile:
    """Record a file a person uploaded, now that it is whole."""
    record = StoredFile(id=file_id, kind=kind, name=target.name, bytes=size, sha256=sha256,
                        made_by="user", created=time.time())
    await index.add(record)
    return record


async def listing(index: FileIndex, root: Path, texts_root: Path) -> dict[str, Any]:
    """What is stored, newest first, as the web app and the model have always been given it, now with each
    one's id. A file recorded but no longer on disk is left out rather than offered. A document's path is
    where its copy appears while a tool reads it (texts.py)."""
    out: dict[str, list[dict[str, Any]]] = {"audio": [], "docs": [], "books": [], "voices": []}
    names_by_id = await index.text_names()
    for record in await index.all():
        path = files.path_of(root, record)
        if record.kind == "docs":
            names = names_by_id.get(record.id, [])
            if names:
                out["docs"].append({"id": record.id, "name": record.name,
                                    "path": str(texts.path_for(texts_root, record, names)),
                                    "files": names, "at": record.created, "draft": record.made_by == "assistant"})
        elif record.kind in LISTED and path.is_file() and not path.is_symlink():
            out[LISTED[record.kind]].append({"id": record.id, "name": record.name, "path": str(path),
                                             "bytes": record.bytes, "at": record.created})
    return out


async def delete_upload(index: FileIndex, root: Path, file_id: str) -> dict[str, Any]:
    """Remove one upload the listing offered, by its id, and say what went.

    Markdown is only in the database, so its record and texts go together and nothing on disk is touched (a
    copy lent to a call still running goes when the call ends). A file: only what an upload could have made,
    the one file of its kind's extensions. A link is refused outright: nothing here ever makes one, and
    following it could land on a file elsewhere. The slot goes too once empty; a file a tool left beside an
    upload (audiobook's corrections, beside its PDF) stays."""
    record = await index.get(file_id) if files.is_id(file_id) else None
    if record is None:
        raise UploadError("no such upload")
    if record.kind == "docs":
        names = (await index.text_names()).get(record.id, [])
        await index.remove(record.id)
        return {"id": record.id, "kind": record.kind, "name": record.name, "files": len(names),
                "bytes": record.bytes}
    slot = root / record.id
    if slot.is_symlink() or not slot.is_dir():
        raise UploadError(f"no such upload: {record.name}")
    candidate = slot / _clean_component(record.name)
    if candidate.is_symlink():
        raise UploadError(f"{record.name} is a link, not an upload")
    target = _inside(root, candidate)
    if target.parent != slot.resolve():
        raise UploadError(f"no such upload: {record.name}")
    if target.suffix.lower() not in EXTENSIONS.get(record.kind, set()) or not target.is_file():
        raise UploadError(f"no such upload: {record.name}")
    size = target.stat().st_size
    target.unlink()
    files.discard_slot(root, record.id)
    await index.remove(record.id)
    return {"id": record.id, "kind": record.kind, "name": record.name, "files": 1, "bytes": size}


# ---------------------------------------------------------------------------
# The one-time move of the old uploads folder into the store
# ---------------------------------------------------------------------------

OLD_FOLDERS = (("audio", "audio", AUDIO_EXTS), ("books", "book", BOOK_EXTS), ("voices", "voice", AUDIO_EXTS))


def _retire(path: Path) -> Path:
    """Rename an imported folder out of the way, without overwriting an earlier one (as db.py does)."""
    target = path.with_name(path.name + ".imported")
    n = 1
    while target.exists():
        n += 1
        target = path.with_name(f"{path.name}.imported.{n}")
    path.rename(target)
    return target


def _copy_checked(source: Path, dest: Path) -> None:
    shutil.copy2(source, dest)
    if files.sha256_of(dest) != files.sha256_of(source):
        raise OSError(f"{source} did not copy intact")


async def import_old_uploads(index: FileIndex, root: Path, old: Path) -> dict[str, int]:
    """The uploads folder as it was before the store (audio/, books/, voices/, docs/<folder>/), copied in once.

    Each file is copied into a slot of its own under its own name, checked against the original's hash, and
    recorded with the time it was uploaded (its modification time). A book's corrections file travels with
    it, because audiobook looks for it beside the PDF. A folder of markdown goes into the database instead,
    each file's text read back and checked the same way. Then each old folder is renamed `<name>.imported`:
    nothing is deleted. Safe to run again: anything already recorded with the same kind, name and hash is
    not copied twice. exports/ stays where it is: docu-ai saves files there for mail-ai to attach (phase E).
    Returns how many of each it copied, and, as `docs_unreadable`, any markdown folder it could not take as
    text (left in docs.imported)."""
    imported: dict[str, int] = {}
    for folder_name, kind, extensions in OLD_FOLDERS:
        source = old / folder_name
        if source.is_symlink() or not source.is_dir():
            continue
        known = {(r.name, r.sha256) for r in await index.all(kind)}
        count = 0
        for p in sorted(source.iterdir()):
            if p.is_symlink() or not p.is_file() or p.suffix.lower() not in extensions:
                continue
            sha256 = files.sha256_of(p)
            if (p.name, sha256) in known:
                continue
            file_id, slot = files.new_slot(root)
            _copy_checked(p, slot / p.name)
            corrections = p.with_suffix(".corrections.txt")
            if kind == "book" and corrections.is_file() and not corrections.is_symlink():
                _copy_checked(corrections, slot / corrections.name)
            await index.add(StoredFile(id=file_id, kind=kind, name=p.name, bytes=p.stat().st_size,
                                       sha256=sha256, made_by="user", created=p.stat().st_mtime))
            count += 1
        imported[folder_name] = count
        _retire(source)

    docs = old / "docs"
    if docs.is_dir() and not docs.is_symlink():
        known = {(r.name, r.sha256) for r in await index.all("docs")}
        count = unreadable = 0
        for batch in sorted(docs.iterdir()):
            if batch.is_symlink() or not batch.is_dir():
                continue
            found = {p.name: p.read_bytes() for p in batch.iterdir()
                     if p.is_file() and not p.is_symlink() and p.suffix.lower() in DOC_EXTS}
            if not found:
                continue
            try:
                name = _clean_component(batch.name)
                taken = {_clean_component(n): text_of(n, data) for n, data in found.items()}
            except UploadError:
                unreadable += 1
                continue
            sha256, size = files.texts_digest(taken)
            if (name, sha256) in known:
                continue
            file_id = files.new_id()
            await index.add(StoredFile(id=file_id, kind="docs", name=name, bytes=size, sha256=sha256,
                                       made_by="assistant" if (batch / DRAFT).exists() else "user",
                                       created=batch.stat().st_mtime), taken)
            if files.texts_digest(await index.texts(file_id))[0] != sha256:
                raise OSError(f"{batch} did not go into the database intact")
            count += 1
        imported["docs"] = count
        if unreadable:
            imported["docs_unreadable"] = unreadable
        _retire(docs)
    return imported
