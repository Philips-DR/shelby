"""Render chapters to audio, caching each chunk so interrupted runs resume where they stopped."""

import hashlib
import json
import subprocess
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import scipy.io.wavfile

from .chunk import chunk_paragraph
from .names import chapter_stem, slugify, speed_suffix
from .plan import CHAPTER_PREFIX, Chapter
from .preview import CHARS_PER_SECOND, RENDER_SPEED
from .tts import Narrator

CACHE_DIR = Path(".cache/audio")
SENTENCE_PAUSE = 0.40
PARAGRAPH_PAUSE = 0.6
HEADING_PAUSE_BEFORE = 0.8
HEADING_PAUSE_AFTER = 0.5
TITLE_PAUSE = 1.2
LABEL_PAUSE = 0.7  # between "Chapter 6" and its title: shorter than the one after the title, so the order is audible


def _silence(seconds: float, sample_rate: int) -> np.ndarray:
    return np.zeros(int(seconds * sample_rate), dtype=np.float32)


def _to_int16(audio: np.ndarray) -> np.ndarray:
    return (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)


def format_clock(seconds: float) -> str:
    h, rem = divmod(int(seconds), 3600)
    return f"{h}:{rem // 60:02d}:{rem % 60:02d}"


class ChunkRenderer:
    """Each piece of speech, made once and kept: `.cache/audio/<voice id><variant>/<text hash>.npy`.

    The 8-bit model's pieces (`-int8`, 2026-11-06) are kept apart from the full model's, and a chapter is spoken from
    one or the other, never both (`choose`): from the full model's when it already has every piece of the chapter (a
    chapter rendered before, at another speed or again, costs nothing and sounds as it did), else from the 8-bit
    model's, making whatever is missing."""

    def __init__(self, narrator: Narrator):
        self.narrator = narrator
        self.full = CACHE_DIR / narrator.voice_id
        self.own = CACHE_DIR / f"{narrator.voice_id}{narrator.variant}"
        self.cache = self.own
        self.cache.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _name(text: str) -> str:
        return f"{hashlib.sha256(text.encode()).hexdigest()[:24]}.npy"

    def _path(self, text: str) -> Path:
        return self.cache / self._name(text)

    def choose(self, texts: list[str]) -> Path:
        """Which model's pieces this chapter is spoken from (see the class)."""
        whole = self.own != self.full and all((self.full / self._name(t)).exists() for t in texts)
        self.cache = self.full if whole else self.own
        return self.cache

    def is_cached(self, text: str) -> bool:
        return self._path(text).exists()

    def missing(self, texts: list[str]) -> list[str]:
        """The pieces still to make, each once, in order."""
        return list(dict.fromkeys(t for t in texts if not self.is_cached(t)))

    def store(self, text: str, audio: np.ndarray) -> None:
        np.save(self._path(text), audio.astype(np.float32))

    def __call__(self, text: str) -> np.ndarray:
        path = self._path(text)
        if path.exists():
            return np.load(path)
        audio = self.narrator.synthesize(text).astype(np.float32)
        np.save(path, audio)
        return audio


@dataclass
class Progress:
    """Where a render is, for front doors to display. Chunks already cached count as done at once."""

    chapter: int
    chapter_title: str
    chunks_done: int
    chunks_total: int
    chars_left: int  # still to generate
    seconds_left: float | None  # None until there's something to estimate from

    @property
    def fraction(self) -> float:
        return self.chunks_done / self.chunks_total if self.chunks_total else 1.0


class ProgressTracker:
    def __init__(self, texts: list[str], render: ChunkRenderer, on_progress: Callable[[Progress], None] | None,
                 pending: list[str] | None = None):
        self.total = len(texts)
        pending = set(pending) if pending is not None else {t for t in texts if not render.is_cached(t)}
        self.chars_left = sum(len(t) for t in pending)
        self.pending = pending
        self.done = 0
        self.generated_chars = 0
        self.generating_seconds = 0.0
        self.on_progress = on_progress
        self.chapter, self.chapter_title = 0, ""

    def rate(self) -> float:
        """Characters generated per second: measured once there's enough to go on, else the estimate."""
        if self.generated_chars >= 500:
            return self.generated_chars / self.generating_seconds
        return CHARS_PER_SECOND * RENDER_SPEED

    def chunk_done(self, text: str, seconds: float) -> None:
        self.done += 1
        if text in self.pending:
            self.pending.discard(text)
            self.chars_left -= len(text)
            self.generated_chars += len(text)
            self.generating_seconds += seconds
        if self.on_progress:
            left = self.chars_left / self.rate() if self.chars_left else 0.0
            self.on_progress(Progress(self.chapter, self.chapter_title, self.done, self.total, self.chars_left, left))


class _AlreadyCounted:
    """Progress for a chapter whose missing pieces the workers made and counted: render_chapter's count of each of
    those is skipped once; the rest (pieces already kept, a sentence said twice) are counted as before."""

    def __init__(self, tracker: ProgressTracker, made: list[str]):
        self.tracker = tracker
        self.left = Counter(made)

    def chunk_done(self, text: str, seconds: float) -> None:
        if self.left[text]:
            self.left[text] -= 1
            return
        self.tracker.chunk_done(text, 0.0)


def announcement(chapter: Chapter) -> list[str]:
    """What opens a chapter, as the pieces to say one after the other.

    "Chapter 6 Knowing the Source of Your Dreams" said as one phrase ran "six" straight into "knowing" with no
    breath between them (heard in a finished book, and in Whisper's word times: 6 ended at 1.10 s, Knowing began at
    1.10). The label and the title are two things, so they are said apart, the label as a sentence of its own so the
    voice comes down at its end. A chapter with no label ("Opening", "Foreword") is one piece."""
    text = chapter.announce or chapter.title
    label = CHAPTER_PREFIX.match(text)
    title = text[label.end():].strip() if label else ""
    if not label or not title:
        return [text]
    return [label.group().strip(" .:,") + ".", title]


def chapter_texts(chapter: Chapter) -> list[str]:
    """Everything the voice generates for a chapter, in order: what opens it, then each chunk."""
    return [*announcement(chapter)] + [chunk for seg in chapter.segments for chunk in chunk_paragraph(seg.text)]


def render_chapter(chapter: Chapter, render: ChunkRenderer, sample_rate: int, tracker: ProgressTracker) -> np.ndarray:
    def speak(text: str) -> np.ndarray:
        started = time.monotonic()
        audio = render(text)
        tracker.chunk_done(text, time.monotonic() - started)
        return audio

    pieces = []
    opening = announcement(chapter)
    for i, part in enumerate(opening):
        pieces += [speak(part), _silence(LABEL_PAUSE if i < len(opening) - 1 else TITLE_PAUSE, sample_rate)]
    for seg in chapter.segments:
        is_heading = seg.kind in ("heading", "title")
        if is_heading:
            pieces.append(_silence(HEADING_PAUSE_BEFORE, sample_rate))
        for chunk in chunk_paragraph(seg.text):
            pieces += [speak(chunk), _silence(SENTENCE_PAUSE, sample_rate)]
        after = HEADING_PAUSE_AFTER if is_heading else PARAGRAPH_PAUSE
        pieces.append(_silence(after - SENTENCE_PAUSE, sample_rate))
    return np.concatenate(pieces)


def _tempo(speed: float) -> list[str]:
    """ffmpeg's atempo changes pace without changing pitch."""
    return [] if speed == 1 else ["-af", f"atempo={speed}"]


def encode_mp3(wav: Path, mp3: Path, title: str, album: str, track: int, speed: float = 1) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), *_tempo(speed), "-c:a", "libmp3lame", "-q:a", "4",
         "-metadata", f"title={title}", "-metadata", f"album={album}", "-metadata", f"track={track}", str(mp3)],
        check=True,
    )


def encode_m4b(wavs: list[Path], titles: list[str], sample_rate: int, out: Path, album: str, speed: float = 1) -> None:
    """Join chapter WAVs into a single M4B audiobook with chapter markers."""
    work = out.parent
    concat_list = work / "concat.txt"
    concat_list.write_text("".join(f"file '{w.resolve()}'\n" for w in wavs))

    metadata = [";FFMETADATA1", f"title={album}"]
    start = 0
    for wav, title in zip(wavs, titles):
        rate, data = scipy.io.wavfile.read(wav)
        end = start + int(len(data) / rate / speed * 1000)
        metadata += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={start}", f"END={end}", f"title={title}"]
        start = end
    metadata_file = work / "chapters.txt"
    metadata_file.write_text("\n".join(metadata) + "\n")

    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat_list),
         "-i", str(metadata_file), "-map_metadata", "1", "-map_chapters", "1", *_tempo(speed),
         "-c:a", "aac", "-b:a", "64k", str(out)],
        check=True,
    )
    concat_list.unlink()
    metadata_file.unlink()


def render_book(
    chapters: list[tuple[int, Chapter]],
    narrator: Narrator,
    out_dir: Path,
    album: str,
    m4b: bool,
    speed: float = 1,
    on_progress: Callable[[Progress], None] | None = None,
    on_chapter_done: Callable[[Path, float], None] | None = None,
    labels: dict | None = None,
    workers: int = 1,
) -> Path | None:
    """Render chapters to MP3s (and optionally one M4B). Returns the M4B path if built.

    Beside each MP3 goes `<its name>.json`: the chapter's number, title and book, the speed, `labels` (voice, PDF,
    author), and exactly the text it speaks, written down as it was spoken. That is what Shelby keeps with the
    audio (keeping.py); the plan can change after (corrections, a better reading), the MP3 does not."""
    out_dir.mkdir(parents=True, exist_ok=True)
    render = ChunkRenderer(narrator)
    sr = narrator.sample_rate
    pending: list[str] = []
    for _, c in chapters:
        render.choose(chapter_texts(c))
        pending += render.missing(chapter_texts(c))
    tracker = ProgressTracker([t for _, c in chapters for t in chapter_texts(c)], render, on_progress, pending)
    # More than one worker: a chapter's missing pieces are made side by side first (workers.py), then it is put
    # together from the cache below, exactly as a one-at-a-time render puts it together.
    pool = None
    if workers > 1 and pending:
        from .workers import WorkerPool

        pool = WorkerPool(narrator.prompt, workers)
    wavs, titles = [], []
    try:
        _render_chapters(chapters, render, sr, tracker, pool, out_dir, album, speed, on_chapter_done, labels, m4b,
                         wavs, titles)
    finally:
        if pool is not None:
            pool.close()

    book = None
    if m4b:
        book = out_dir / f"{slugify(album)}{speed_suffix(speed)}.m4b"
        encode_m4b(wavs, titles, sr, book, album, speed)
    for wav in wavs:
        wav.unlink()
    return book


def _render_chapters(chapters, render, sr, tracker, pool, out_dir, album, speed, on_chapter_done, labels, m4b,
                     wavs, titles) -> None:
    for number, chapter in chapters:
        tracker.chapter, tracker.chapter_title = number, chapter.title
        texts = chapter_texts(chapter)
        render.choose(texts)
        counted = tracker
        if pool is not None:
            made = []
            for text, piece, seconds in pool.generate(render.missing(texts)):
                render.store(text, piece)
                tracker.chunk_done(text, seconds)
                made.append(text)
            counted = _AlreadyCounted(tracker, made)
        audio = render_chapter(chapter, render, sr, counted)
        stem = f"{chapter_stem(number, chapter.title)}{speed_suffix(speed)}"
        wav = out_dir / f"{stem}.wav"
        scipy.io.wavfile.write(wav, sr, _to_int16(audio))
        mp3 = out_dir / f"{stem}.mp3"
        encode_mp3(wav, mp3, chapter.title, album, number, speed)
        seconds = len(audio) / sr / speed
        spoken = "\n\n".join([*announcement(chapter), *(seg.text for seg in chapter.segments)])
        mp3.with_suffix(".json").write_text(json.dumps(
            {"number": number, "title": chapter.title, "album": album, "speed": speed, "seconds": round(seconds, 1),
             **(labels or {}), "text": spoken}, ensure_ascii=False, indent=1), encoding="utf-8")
        if on_chapter_done:
            on_chapter_done(mp3, seconds)
        if m4b:
            wavs.append(wav)  # joined into the M4B at the end
        else:
            wav.unlink()  # don't leave WAVs behind if a long render is stopped
        titles.append(chapter.title)
