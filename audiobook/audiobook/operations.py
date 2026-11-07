"""What the audiobook tool can be asked to do: data in, data out.

Front doors (the CLI and the web app) call these and format the results for their audience.
Nothing here prints or exits.
"""

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from . import background
from .names import chapter_audio, chapter_stem, title_from_file_name
from .plan import BookPlan, build_plan
from .preview import RENDER_SPEED, chapter_label, format_duration, render_preview, speech_seconds
from .speech import parse_corrections

AUDIO = (".mp3", ".m4b")
DEFAULT_SPEED = 0.95


@dataclass
class PreviewResult:
    plan: BookPlan
    preview_path: Path
    plan_path: Path


def output_dir(pdf: Path) -> Path:
    title, _ = title_from_file_name(pdf.stem)
    folder = Path("output") / (title or pdf.stem)
    if folder.name != pdf.stem:
        old = Path("output") / pdf.stem
        if old.is_dir() and not folder.exists():
            return old
    return folder


def plan_book(pdf: Path) -> BookPlan:
    from .extract import extract, pdf_metadata  # Docling is slow to import; keep it off the CLI's startup path.

    title, author = pdf_metadata(pdf)
    return build_plan(extract(pdf), file_name=pdf.stem, title=title, author=author, corrections=load_corrections(pdf))


def unread_names(pdf: Path) -> tuple[str, str | None]:
    """A book's title and author before Docling has read it, when its title page is not yet known: the PDF's
    own, else its file name's, else the file name as it is."""
    from .extract import pdf_metadata

    try:
        own_title, own_author = pdf_metadata(pdf)
    except RuntimeError:  # pdfium cannot open it: the reading will say so in its own log
        own_title = own_author = None
    named, named_author = title_from_file_name(pdf.stem)
    return own_title or named or pdf.stem, own_author or named_author


def corrections_path(pdf: Path) -> Path:
    """Typos in the source text, next to the PDF: book.pdf → book.corrections.txt"""
    return pdf.with_suffix(".corrections.txt")


def load_corrections(pdf: Path) -> list[tuple[str, str]]:
    path = corrections_path(pdf)
    return parse_corrections(path.read_text()) if path.exists() else []


def preview_book(pdf: Path, out_dir: Path | None = None) -> PreviewResult:
    plan = plan_book(pdf)
    out = out_dir or output_dir(pdf)
    out.mkdir(parents=True, exist_ok=True)
    preview_path = out / "preview.md"
    preview_path.write_text(render_preview(plan, str(pdf)))
    plan_path = out / "plan.json"
    plan_path.write_text(json.dumps(asdict(plan), indent=1, ensure_ascii=False))
    return PreviewResult(plan, preview_path, plan_path)


def render_pdf(
    pdf: Path,
    voice: str,
    chapters: list[int] | None = None,
    speed: float = 0.95,
    m4b: bool = False,
    out_dir: Path | None = None,
    on_progress: "Callable | None" = None,
    on_chapter_done: Callable[[Path, float], None] | None = None,
) -> Path | None:
    """Render chapters (1-based, as numbered by preview; default all). Returns the M4B path if built."""
    from .render import render_book
    from .tts import Narrator

    plan = plan_book(pdf)
    selected = chapters or list(range(1, len(plan.chapters) + 1))
    bad = [n for n in selected if not 1 <= n <= len(plan.chapters)]
    if bad:
        raise ValueError(f"no chapter {bad[0]}: this book has {len(plan.chapters)}")
    from .workers import workers_here

    narrator = Narrator(voice)
    workers, why = workers_here()
    print(f"Rendering {why}.", flush=True)
    return render_book(
        [(n, plan.chapters[n - 1]) for n in selected], narrator, out_dir or output_dir(pdf), plan.title, m4b, speed,
        on_progress=on_progress, on_chapter_done=on_chapter_done,
        labels={"voice": voice, "pdf": str(pdf), **({"author": plan.author} if plan.author else {})},
        workers=workers,
    )


# ---------------------------------------------------------------------------
# For a model: what a book is, what a voice is, and long work as background jobs.
#
# A PDF is named by its path, wherever it lives; everything the tool makes goes in its own
# `output/`, which is relative to the folder every front door runs from.
# ---------------------------------------------------------------------------


def parse_selection(spec: str, count: int) -> list[int]:
    """Parse '1-3,5' into 1-based chapter numbers; every number must exist."""
    numbers: set[int] = set()
    for part in spec.split(","):
        first, _, last = part.strip().partition("-")
        try:
            low, high = int(first), int(last or first)
        except ValueError:
            raise ValueError(f"chapters must look like '1-3,5', not '{spec}'") from None
        # Checked before the range is expanded, so '1-99999999999' cannot build a giant set, and a
        # reversed '5-3' is an error instead of silently selecting nothing (which renders everything).
        if low > high:
            raise ValueError(f"'{part.strip()}' runs backwards: write it as {high}-{low}")
        for n in (low, high):
            if not 1 <= n <= count:
                raise ValueError(f"no chapter {n}: this book has {count} (see preview)")
        numbers.update(range(low, high + 1))
    return sorted(numbers)


def check_speed(speed: float) -> float:
    if not 0.5 <= speed <= 2.0:
        raise ValueError("speed must be between 0.5 and 2.0, e.g. 0.95")
    return speed


def pdf_file(path: str | Path) -> Path:
    pdf = Path(path).expanduser()
    if pdf.suffix.lower() != ".pdf":
        raise ValueError(f"{pdf.name} is not a PDF")
    if not pdf.is_file():
        raise FileNotFoundError(f"no PDF at {pdf}")
    return pdf.resolve()


def book_overview(pdf: Path) -> dict:
    """What a book will be: its chapters, how long each is, and how much was left out. Planning is
    instant once Docling has analysed the PDF; before that this says so instead of waiting minutes."""
    from .extract import is_extracted

    if not is_extracted(pdf):
        title, author = unread_names(pdf)
        return {"pdf": str(pdf), "analysed": False, "title": title, "author": author,
                "hint": "Docling has not read this PDF yet. start_analysis does that in the "
                        "background (about 2-4 seconds a page, cached afterwards)."}
    plan = plan_book(pdf)
    total = sum(c.spoken_chars for c in plan.chapters)
    skipped = Counter(s.reason for c in plan.chapters for s in c.skipped)
    files = _audio_files(output_dir(pdf))
    names = [f.name for f in files]
    claimed: set[str] = set()

    def audio(number: int, chapter) -> list[dict]:
        found = chapter_audio(names, number, chapter.title)
        claimed.update(name for name, _ in found)
        return [{**_audio_entry(output_dir(pdf) / name), "speed": speed} for name, speed in found]

    return {
        "pdf": str(pdf), "analysed": True, "title": plan.title, "author": plan.author,
        "chapters": [
            # `stem`: how this chapter's audio is named, before the speed (names.chapter_stem). Audio the suite now
            # keeps instead of this folder is matched to the chapter by it, as `audio` here is.
            {"number": i, "label": chapter_label(i, c), "appendix": c.appendix, "stem": chapter_stem(i, c.title),
             "words": sum(len(s.text.split()) for s in c.segments),
             "speech": format_duration(speech_seconds(c.spoken_chars)),
             "audio": audio(i, c)}
            for i, c in enumerate(plan.chapters, 1)
        ],
        # The whole book's .m4b, and files from an earlier reading whose chapters were found differently.
        "other_audio": [_audio_entry(f) for f in files if f.name not in claimed],
        "speech": format_duration(speech_seconds(total)),
        "render_time": format_duration(speech_seconds(total) / RENDER_SPEED),
        "citations_removed": sum(c.citations_removed for c in plan.chapters),
        "skipped": dict(skipped.most_common()),
        "corrections": str(corrections_path(pdf)) if corrections_path(pdf).exists() else None,
        "output_dir": str(output_dir(pdf).resolve()),
    }


def chapter_text(pdf: Path, chapter: int, start: int = 0, limit_chars: int = 20000) -> dict:
    """The exact text the narrator will speak for one chapter, as segments from `start`. A long
    chapter comes back truncated with next_start set; call again with start=next_start."""
    from .extract import is_extracted

    if not is_extracted(pdf):
        raise ValueError("this PDF has not been analysed yet: call start_analysis first")
    plan = plan_book(pdf)
    if not 1 <= chapter <= len(plan.chapters):
        raise ValueError(f"no chapter {chapter}: this book has {len(plan.chapters)}")
    selected = plan.chapters[chapter - 1]
    segments, used = [], 0
    for index in range(max(start, 0), len(selected.segments)):
        seg = selected.segments[index]
        if segments and used + len(seg.text) > limit_chars:
            return {"chapter": chapter, "label": chapter_label(chapter, selected), "announce": selected.announce
                    or selected.title, "segments": segments, "truncated": True, "next_start": index}
        segments.append({"kind": seg.kind, "text": seg.text})
        used += len(seg.text)
    return {"chapter": chapter, "label": chapter_label(chapter, selected),
            "announce": selected.announce or selected.title, "segments": segments,
            "truncated": False, "next_start": None}


def voice_choices() -> list[dict]:
    from .voices import list_voices

    return [asdict(v) for v in list_voices()]


def _audio_files(folder: Path) -> list[Path]:
    """A book's audio, newest first."""
    if not folder.is_dir():
        return []
    return sorted((f for f in folder.iterdir() if f.suffix in AUDIO and f.is_file()), key=lambda f: -f.stat().st_mtime)


def _audio_entry(f: Path) -> dict:
    return {"name": f.name, "path": str(f.resolve()), "megabytes": round(f.stat().st_size / 1e6, 1),
            "modified": f.stat().st_mtime}


def book_names(folder: Path) -> tuple[str, str | None]:
    """A book's title and author as its last reading found them (the plan.json reading the book writes), else
    as its folder's name, which is the PDF's, gives them."""
    try:
        plan = json.loads((folder / "plan.json").read_text())
        if isinstance(plan, dict) and isinstance(plan.get("title"), str) and plan["title"].strip():
            return plan["title"], plan.get("author") if isinstance(plan.get("author"), str) else None
    except (OSError, ValueError):
        pass
    title, author = title_from_file_name(folder.name)
    return title or folder.name, author


def list_audiobooks(root: Path | None = None) -> list[dict]:
    """Every book with audio in the output folder: its title, author and files, newest first. `book` is the
    folder's name, which is the PDF's without .pdf, and is what describe and delete take."""
    root = root or Path("output")
    books = []
    for folder in sorted(p for p in root.glob("*") if p.is_dir()) if root.is_dir() else []:
        files = sorted(f for f in folder.iterdir() if f.suffix in AUDIO)
        if not files:
            continue
        title, author = book_names(folder) if folder.name not in NOT_A_BOOK else ("Voice samples", None)
        books.append({
            "book": folder.name, "title": title, "author": author, "folder": str(folder.resolve()),
            "files": [_audio_entry(f) for f in files],
            "updated": max(f.stat().st_mtime for f in files),
        })
    return sorted(books, key=lambda b: -b["updated"])


# `output/voices` holds the samples `voice test` makes, not a book, so it is never a book to remove.
NOT_A_BOOK = {"voices"}
# The jobs that work on a book's output folder. A voice job does not.
BOOK_JOBS = ("render", "analyse")


def book_folder(book: str, root: Path | None = None) -> Path:
    """The output folder of one book, by the name `list_audiobooks` gave it.

    A name and never a path: a model supplies it, and a path would reach anywhere. The folder, when it is
    there, must be a real folder directly inside the output folder, never a link."""
    root = root or Path("output")
    if not book or book != book.strip() or book.startswith(".") or re.search(r"[\x00-\x1f/\\]", book):
        raise ValueError(f"not the name of a book: {book!r}")
    if book in NOT_A_BOOK:
        raise ValueError(f"{book} holds voice samples, not a book")
    folder = root / book
    if folder.is_symlink():
        raise ValueError(f"{book} is a link, not a book's folder")
    if folder.exists() and folder.resolve().parent != root.resolve():
        raise ValueError(f"{book} is not directly inside the output folder")
    return folder


def _book_files(folder: Path) -> list[Path]:
    """What a book's folder holds, which must be plain files: if it holds anything else, nothing is touched."""
    entries = sorted(folder.iterdir())
    odd = [e.name for e in entries if e.is_symlink() or not e.is_file()]
    if odd:
        raise ValueError(f"{folder.name} holds something other than files ({', '.join(odd[:3])}), so it was left alone")
    return entries


def working_on(book: str, jobs_dir: Path) -> str | None:
    """What is being done to this book right now ("render" or "analyse"), or None."""
    job = background.current(jobs_dir)
    if job is not None and job.kind in BOOK_JOBS and output_dir(Path(job.target)).name == book:
        return job.kind
    return None


def describe_audiobook(book: str, jobs_dir: Path, root: Path | None = None) -> dict:
    """What is stored for one book, in words a person can approve a delete from. Reads only."""
    folder = book_folder(book, root)
    busy = working_on(book, jobs_dir)
    if not folder.is_dir():
        return {"book": book, "exists": False, "files": [], "bytes": 0,
                "summary": f"Nothing is stored for \u201c{book}\u201d in the output folder."}
    files = [{"name": f.name, "bytes": f.stat().st_size} for f in _book_files(folder)]
    total = sum(f["bytes"] for f in files)
    shown = ", ".join(f"{f['name']} ({f['bytes'] / 1e6:.1f} MB)" for f in files[:10])
    if len(files) > 10:
        shown += f", and {len(files) - 10} more"
    lines = [f"\u201c{book}\u201d: {len(files)} file(s), {total / 1e6:.1f} MB, in the output folder.", shown or "(empty folder)"]
    if busy:
        lines.insert(0, f"A {busy} of this book is running, so it cannot be deleted until it is stopped.")
    lines.append("Deleting removes only these files. Every voice and the shared reading and speech caches are not "
                 "touched.")
    return {"book": book, "exists": True, "files": files, "bytes": total, "running": busy, "summary": "\n".join(lines)}


def delete_audiobook(book: str, jobs_dir: Path, root: Path | None = None) -> dict:
    """Remove one book's output folder: its audio and working files. Refused while that book is being read or
    rendered. Deleting what is not there removes nothing and says so."""
    folder = book_folder(book, root)
    busy = working_on(book, jobs_dir)
    if busy:
        raise background.JobError(f"a {busy} of {book} is running; stop it before deleting its audio")
    if not folder.is_dir():
        return {"book": book, "deleted": False, "files": 0, "bytes": 0}
    files = _book_files(folder)
    size = sum(f.stat().st_size for f in files)
    for f in files:
        f.unlink()
    folder.rmdir()
    return {"book": book, "deleted": True, "files": len(files), "bytes": size}


def check_voice(voice: str, allow_file: bool = True) -> str:
    """A voice a job can actually use, as the name to hand it: a saved or built-in name, or (for a
    render) an existing audio file to clone, as its full path -- the job runs elsewhere and would not
    expand a `~`."""
    from .voices import list_voices

    known = list_voices()
    if voice in {v.name for v in known}:
        return voice
    if allow_file and Path(voice).expanduser().is_file():
        return str(Path(voice).expanduser().resolve())
    names = ", ".join(v.name for v in known if v.kind == "cloned") or "none yet"
    raise ValueError(f"no voice '{voice}'. Cloned voices here: {names}; built-in presets work too (list_voices).")


def start_analysis(pdf: Path, jobs_dir: Path) -> dict:
    """Run Docling over a PDF in the background. It is the slow first step; everything after it
    (preview, reading the text, rendering) works from its cache."""
    title = unread_names(pdf)[0]
    return asdict(background.start("analyse", str(pdf), jobs_dir, ["preview", str(pdf)], title=title))


def start_render(pdf: Path, voice: str, jobs_dir: Path, chapters: str | None = None,
                 speed: float = DEFAULT_SPEED, m4b: bool = False) -> dict:
    """Render chapters in the background. Everything that can be wrong is checked here, before
    a job exists: a render that fails in its first second is a job nobody should have to poll."""
    from .extract import is_extracted

    if not is_extracted(pdf):
        raise ValueError("this PDF has not been analysed yet: call start_analysis first")
    check_speed(speed)
    voice = check_voice(voice)
    plan = plan_book(pdf)
    selected = parse_selection(chapters, len(plan.chapters)) if chapters else None
    arguments = ["render", str(pdf), "--voice", voice, "--speed", f"{speed:g}"]
    if selected:
        arguments += ["--chapters", chapters]
    if m4b:
        arguments.append("--m4b")
    return asdict(background.start("render", str(pdf), jobs_dir, arguments, title=plan.title))


def get_corrections(pdf: Path) -> dict:
    """The book's corrections file as text: `find => replace` lines for what the source got wrong
    (a typo, a name the voice cannot say). Empty when there is none."""
    path = corrections_path(pdf)
    return {"path": str(path), "text": path.read_text() if path.exists() else ""}


def set_corrections(pdf: Path, text: str) -> dict:
    """Replace the book's corrections. Applied the next time the book is planned, so previews and
    renders pick them up at once; chunks already spoken stay cached, and only changed text is re-read."""
    ignored = [line.strip() for line in text.splitlines()
               if line.strip() and not line.strip().startswith("#") and not parse_corrections(line)]
    path = corrections_path(pdf)
    path.write_text(text)
    return {"path": str(path), "pairs": len(parse_corrections(text)), "ignored": ignored}


def start_voice_clone(name: str, clip: Path, consent: str, jobs_dir: Path, overwrite: bool = False) -> dict:
    """Clone a voice from a recording, in the background. Only voices the person owns or has the
    speaker's permission to use: `consent` says which, and is kept with the voice."""
    from .voices import NAME, PRESETS, VOICES_DIR

    if not consent.strip():
        raise ValueError("say whose voice this is and that they agreed to it being cloned (consent)")
    if not NAME.match(name):
        raise ValueError("voice name: lowercase letters, digits, - and _ only")
    if name in PRESETS:
        raise ValueError(f"'{name}' is a built-in voice; pick another name")
    if (VOICES_DIR / f"{name}.safetensors").exists() and not overwrite:
        raise ValueError(f"voice '{name}' already exists (pass overwrite to replace it)")
    if not clip.is_file():
        raise FileNotFoundError(f"no recording at {clip}")
    arguments = ["voice", "add", name, str(clip), f"--consent={consent.strip()}"]
    if overwrite:
        arguments.append("--overwrite")
    return asdict(background.start("voice", str(clip), jobs_dir, arguments))


def start_voice_sample(name: str, jobs_dir: Path, speed: float = DEFAULT_SPEED) -> dict:
    """Have a voice read a sample paragraph, in the background; about half a minute. The MP3 is
    the job's output. Judge a clone with this before committing hours of rendering to it."""
    check_speed(speed)
    # A name only: the sample is written under output/voices/<name>-test.mp3, and a path as the name
    # would put it wherever that path points.
    check_voice(name, allow_file=False)
    return asdict(background.start("sample", name, jobs_dir, ["voice", "test", name, "--speed", f"{speed:g}"]))


def cancel_job(jobs_dir: Path, job_id: str | None = None) -> dict:
    """Stop the running job. A render keeps every sentence it had spoken, so starting it again
    carries on; reading a book and cloning a voice start over."""
    return asdict(background.cancel(jobs_dir, job_id))


def job_status(jobs_dir: Path, job_id: str | None = None) -> dict | None:
    """One job by id, or the most recent. Refreshed from its process and its log."""
    job = background.get(jobs_dir, job_id) if job_id else background.latest(jobs_dir)
    return asdict(job) if job else None
