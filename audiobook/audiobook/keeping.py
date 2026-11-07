"""What this tool hands over for keeping, and letting go of it after (the suite's layer 1b, ../../plan.md).

Alone, none of this runs: finished audio stays in output/ as it always has. In the suite, the assistant asks
`inventory` for everything here worth keeping, labelled so that something which knows what a book is (the
Audiobooks page) can find it again; the assistant files it in its own store and database without reading inside,
then calls `release` for the working copies this tool no longer needs to hold. This tool never learns where they
went.

What is handed over, and what this tool keeps a working copy of:

- a chapter's MP3 (`chapter`), a whole book's M4B (`audiobook`), a voice's sample MP3 (`sample`) and audio left
  loose at the top of output/ (`other`): released once filed, since nothing here reads them again. A chapter carries the exact text it speaks when its render wrote it
  down (`<mp3 stem>.json` beside it, since 2026-11-01); one rendered before that has its MP3's own tags only.
- a book (`book`): its title and author as this tool names them, so a book can be named once its audio is kept and
  no longer listed here. Kept: it describes the folder.
- a voice (`voice`): its record, the sample it was cloned from and its state. Kept: a render needs them.
- a book's corrections (`corrections`): kept beside the PDF, where a render reads them.
- a finished job (`job`): its record and its log, tidied of progress lines. Kept: `job_status` reads them.

A render still running hands over only the chapters its log says are finished: the others in that folder may be
being written over.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import asdict
from pathlib import Path

from . import background
from .names import SPEED_AND_SUFFIX
from .operations import book_names, output_dir

OUTPUT = Path("output")
VOICES = Path("voices")
SAMPLES = OUTPUT / "voices"
CHAPTER = re.compile(r"(?P<number>\d+)-(?P<slug>.+?)" + SPEED_AND_SUFFIX.pattern)
FINISHED = {"done", "failed", "interrupted", "cancelled"}


def _version(*paths: Path, extra: str = "") -> str:
    parts = [f"{p.name}:{p.stat().st_size}:{p.stat().st_mtime_ns}" for p in paths if p.is_file()]
    return hashlib.sha256(("|".join(parts) + "|" + extra).encode()).hexdigest()[:32]


def _tags(path: Path) -> dict[str, str]:
    """An audio file's own tags (title, album, track), which every MP3 this tool made carries."""
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format_tags", "-of", "json", str(path)],
                             capture_output=True, text=True, timeout=30, check=True).stdout
        return {k.lower(): v for k, v in json.loads(out).get("format", {}).get("tags", {}).items()}
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return {}


def _chapter(book: str, mp3: Path) -> dict | None:
    match = CHAPTER.fullmatch(mp3.name)
    if match is None:
        return None
    side = mp3.with_suffix(".json")
    written = {}
    if side.is_file():
        try:
            written = json.loads(side.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            written = {}
    tags = _tags(mp3) if not written else {}
    labels = {
        "book": book,
        "number": int(match["number"]),
        "title": written.get("title") or tags.get("title") or match["slug"].replace("-", " "),
        "album": written.get("album") or tags.get("album"),
        "speed": float(match["speed"]) if match["speed"] else 1.0,
        **{k: written[k] for k in ("author", "voice", "pdf", "seconds") if k in written},
    }
    return {"kind": "chapter", "key": f"{book}/{mp3.name}", "labels": labels, "text": written.get("text"),
            "version": _version(mp3, side), "files": [{"path": str(mp3.resolve()), "role": "audio"}],
            "release": True}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _log_text(jobs_dir: Path, job_id: str) -> str:
    """A job's log as a person would read it: each progress line kept only as it last stood."""
    try:
        # Bytes, not read_text: reading as text turns every \r into a line break, and each progress update
        # would come back as a line of its own.
        raw = (Path(jobs_dir) / f"{job_id}.log").read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(line.split("\r")[-1].rstrip() for line in raw.split("\n")).strip().replace("\x00", "")


def inventory(jobs_dir: Path) -> dict:
    items: list[dict] = []
    running = background.current(jobs_dir)
    busy = output_dir(Path(running.target)).name if running and running.kind in ("render", "analyse") else None
    finished_now = {Path(p).name for p in running.outputs} if running and running.kind == "render" else set()

    for folder in sorted(p for p in OUTPUT.iterdir() if p.is_dir() and not p.is_symlink() and p != SAMPLES) \
            if OUTPUT.is_dir() else []:
        if any(f.is_file() and not f.is_symlink() for f in folder.iterdir()):
            # A book's title and author as this tool names them (list_audiobooks gave the same). Once its audio is
            # kept the tool no longer lists the book, and a chapter's own tag may be from an early, wrong reading
            # ("Praise for"): so the title travels as a record of its own, and stays current when it changes.
            title, author = book_names(folder)
            items.append({"kind": "book", "key": folder.name,
                          "labels": {"book": folder.name, "title": title, "author": author}, "text": None,
                          "version": hashlib.sha256(f"{title}|{author}".encode()).hexdigest()[:32],
                          "files": [], "release": False})
        for f in sorted(folder.iterdir()):
            if f.is_symlink() or not f.is_file():
                continue
            if folder.name == busy and f.name not in finished_now:
                continue  # may be being written: only what the running render says it finished
            if f.suffix == ".mp3":
                item = _chapter(folder.name, f)
                if item:
                    items.append(item)
            elif f.suffix == ".m4b":
                tags = _tags(f)
                speed = SPEED_AND_SUFFIX.search(f.name.replace(".m4b", ".mp3"))
                items.append({"kind": "audiobook", "key": f"{folder.name}/{f.name}",
                              "labels": {"book": folder.name, "title": tags.get("title"),
                                         "speed": float(speed["speed"]) if speed and speed["speed"] else 1.0},
                              "text": None, "version": _version(f), "files": [{"path": str(f.resolve()), "role": "audio"}],
                              "release": True})

    # Audio left loose at the top of output/, in no book's folder (early voice tests and comparisons): no page shows
    # it, but it is the user's, so it is handed over like the rest rather than left behind.
    for f in sorted(OUTPUT.iterdir()) if OUTPUT.is_dir() else []:
        if f.is_file() and not f.is_symlink() and f.suffix in (".mp3", ".m4b"):
            items.append({"kind": "other", "key": f.name, "labels": {}, "text": None, "version": _version(f),
                          "files": [{"path": str(f.resolve()), "role": "audio"}], "release": True})

    for f in sorted(SAMPLES.glob("*-test.mp3")) if SAMPLES.is_dir() else []:
        if f.is_file() and not f.is_symlink():
            items.append({"kind": "sample", "key": f.name, "labels": {"voice": f.name.removesuffix("-test.mp3")},
                          "text": None, "version": _version(f), "files": [{"path": str(f.resolve()), "role": "audio"}],
                          "release": True})

    for state in sorted(VOICES.glob("*.safetensors")) if VOICES.is_dir() else []:
        name = state.stem
        record = VOICES / f"{name}.json"
        labels = {"name": name}
        if record.is_file():
            try:
                labels.update(json.loads(record.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                pass
        parts = [{"path": str(state.resolve()), "role": "state"}]
        if (VOICES / f"{name}.wav").is_file():
            parts.append({"path": str((VOICES / f"{name}.wav").resolve()), "role": "sample"})
        source = Path(str(labels.get("source", "")))
        if labels.get("source") and not source.is_absolute() and source.is_file():
            parts.append({"path": str(source.resolve()), "role": "source"})
        items.append({"kind": "voice", "key": name, "labels": labels, "text": labels.get("consent"),
                      "version": _version(state, record, *(Path(p["path"]) for p in parts)),
                      "files": parts, "release": False})

    pdfs = set()
    for job in background.history(jobs_dir):
        if job.kind in ("analyse", "render"):
            pdfs.add(job.target)
        if job.state in FINISHED:
            log = _log_text(jobs_dir, job.id)
            labels = {k: v for k, v in asdict(job).items() if k not in ("pid",)}
            items.append({"kind": "job", "key": job.id, "labels": labels, "text": log or None,
                          "version": hashlib.sha256(json.dumps(labels, sort_keys=True).encode() + log.encode())
                          .hexdigest()[:32], "files": [], "release": False})
    for pdf in sorted(pdfs):
        corrections = Path(pdf).with_suffix(".corrections.txt")
        if corrections.is_file() and not corrections.is_symlink():
            text = corrections.read_text(encoding="utf-8", errors="replace").replace("\x00", "")
            items.append({"kind": "corrections", "key": pdf, "labels": {"book": Path(pdf).stem, "pdf": pdf},
                          "text": text, "version": hashlib.sha256(text.encode()).hexdigest()[:32], "files": [],
                          "release": False})
    return {"items": items}


def release(wanted: list[dict]) -> dict:
    """Delete working copies the suite has filed: only finished audio in output/, only a plain file whose SHA-256
    is the one filed (so nothing changed since, and nothing not filed, can go), with a chapter's text beside it."""
    root = OUTPUT.resolve()
    released, kept = [], []
    for entry in wanted:
        path = Path(str(entry.get("path", "")))
        try:
            ok = (path.is_absolute() and not path.is_symlink() and path.is_file()
                  and path.resolve().is_relative_to(root) and path.suffix in (".mp3", ".m4b"))
            if not ok:
                kept.append({"path": str(path), "reason": "not finished audio in this tool's output folder"})
                continue
            if _sha256(path) != entry.get("sha256"):
                kept.append({"path": str(path), "reason": "it is not the copy that was filed"})
                continue
            path.unlink()
            side = path.with_suffix(".json")
            if side.is_file() and not side.is_symlink():
                side.unlink()
            released.append(str(path))
        except OSError as error:
            kept.append({"path": str(path), "reason": str(error)})
    return {"released": released, "kept": kept}
