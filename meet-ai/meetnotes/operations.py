"""What meet-ai can be asked to do, as data in and data out.

Both front doors sit on this: ./transcribe and ./notes format these results for a person,
mcp_server.py returns them as JSON to a model. Neither door wraps the other -- a door that
delegates to the other inherits its output format, its exit codes and its assumptions about
who is reading, and the two drift the moment either is changed for its own audience.

Nothing here writes to stdout. transcribe.py predates this module and prints its progress
as it goes, so the one operation that calls into it redirects that away: for the MCP door
stdout IS the protocol stream, and a stray line of progress corrupts it. The information is
in the returned value either way.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from meetnotes.client import ModelConfig
from meetnotes.lexicon import apply_lexicon, load_lexicon
from meetnotes.render import minutes_title, notes_title, recorded_at, write_minutes, write_notes
from meetnotes.spans import TimelineIndex
from meetnotes.timeline import load_timeline, resolve_timeline, timeline_for

# A synchronous transcription of a real meeting takes about as long as the meeting itself,
# which no request/response protocol survives. The door refuses past this and says to use
# the CLI, rather than hanging for an hour and timing out with nothing to show. Lifting it
# means a background job with a status operation, which is a feature, not a bigger number.
MAX_SYNC_AUDIO_SECONDS = 15 * 60


class OperationError(Exception):
    """Something the caller can act on, phrased for whoever is reading."""


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TranscriptEntry:
    markdown: str
    timeline: str | None
    notes: str | None
    minutes: str | None = None
    # What a person knows a meeting by, so a list need not show a file name (2026-10-31). Each is
    # read from what is on disk -- the transcript's own header, the date in the recording's name,
    # the meeting's name as the minutes verified it -- and is None when nothing says. Never guessed.
    source: str | None = None
    recorded: str | None = None
    duration_seconds: float | None = None
    speakers: int | None = None
    meeting: str | None = None


@dataclass(frozen=True)
class AudioEntry:
    path: str
    recorded: str | None = None


@dataclass(frozen=True)
class Recordings:
    audio: list[str] = field(default_factory=list)
    transcripts: list[TranscriptEntry] = field(default_factory=list)
    # Audio in the audio folder that no transcript names as its source: recorded, never transcribed.
    untranscribed: list[AudioEntry] = field(default_factory=list)


# The header a transcript opens with is a few short lines; a long meeting's file is 100 KB and the
# list is asked for every few seconds, so only its start is read.
HEADER_BYTES = 4096


def transcript_header(md: Path) -> dict[str, str]:
    """The `key: value` lines between a transcript's opening `---` lines, as written by
    transcribe.py. Nothing for a file with no header, or one that cannot be read."""
    try:
        with md.open("r", encoding="utf-8", errors="replace") as handle:
            head = handle.read(HEADER_BYTES)
    except OSError:
        return {}
    lines = head.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    header: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return header
        key, sep, value = line.partition(":")
        if sep and key.strip():
            header[key.strip()] = value.strip().strip('"')
    return {}  # never closed: not a header


def _seconds(clock: str | None) -> float | None:
    """'02:05:10' as 7510.0; None for anything else."""
    parts = (clock or "").split(":")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return None
    hours, minutes, seconds = (int(part) for part in parts)
    return float(hours * 3600 + minutes * 60 + seconds)


def _meeting_named(written: Path) -> str | None:
    """The meeting's name as notes or minutes recorded it -- a claim that survived the check
    against the transcript, or nothing (render.py drops a name whose quote did not resolve)."""
    try:
        meeting = json.loads(written.read_text(encoding="utf-8")).get("meeting")
    except (OSError, ValueError, AttributeError):
        return None
    return meeting.strip() if isinstance(meeting, str) and meeting.strip() else None


def _when(name: str) -> str | None:
    when = recorded_at(name)
    return when.isoformat(timespec="minutes") if when else None


def list_recordings(audio_dir: Path, transcript_dir: Path) -> Recordings:
    """What is on disk, and which transcripts already have a timeline beside them.

    A transcript without a timeline cannot have notes made from it, and saying so here is
    what stops a caller discovering that only after a failed call.
    """
    from transcribe import AUDIO_EXTS

    audio = sorted(
        str(p) for p in audio_dir.glob("*") if p.is_file() and p.suffix.lower() in AUDIO_EXTS
    ) if audio_dir.is_dir() else []

    transcripts: list[TranscriptEntry] = []
    if transcript_dir.is_dir():
        for md in sorted(transcript_dir.glob("*.md")):
            # What meet-ai writes from a transcript sits beside it; none of it is a transcript.
            if md.name.endswith((".notes.md", ".minutes.md")):
                continue
            timeline = timeline_for(md)
            notes = md.with_suffix("").with_suffix(".notes.md")
            minutes = md.with_suffix("").with_suffix(".minutes.md")
            header = transcript_header(md)
            source = header.get("source") or None
            speakers = header.get("speakers", "")
            meeting = None
            for written in (minutes, notes):  # x.minutes.md beside x.minutes.json, which holds the claims
                meeting = meeting or _meeting_named(written.with_name(written.name.removesuffix(".md") + ".json"))
            transcripts.append(
                TranscriptEntry(
                    markdown=str(md),
                    timeline=str(timeline) if timeline.exists() else None,
                    notes=str(notes) if notes.exists() else None,
                    minutes=str(minutes) if minutes.exists() else None,
                    source=source,
                    recorded=_when(source or md.name),
                    duration_seconds=_seconds(header.get("duration")),
                    speakers=int(speakers) if speakers.isdigit() else None,
                    meeting=meeting,
                )
            )

    # A transcript names its audio in its header; one written before headers did is matched by name.
    named = {t.source for t in transcripts if t.source} | {Path(t.markdown).stem for t in transcripts}
    untranscribed = [
        AudioEntry(path=path, recorded=_when(Path(path).name))
        for path in audio if Path(path).name not in named and Path(path).stem not in named
    ]
    return Recordings(audio=audio, transcripts=transcripts, untranscribed=untranscribed)


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

def _load_segments(timeline_path: Path, lexicon_path: Path | None) -> tuple[dict, list[dict], int]:
    if not timeline_path.exists():
        raise OperationError(
            f"no timeline at {timeline_path}. Transcripts written before timelines existed "
            f"have none; re-run transcription with force=true to produce one."
        )
    timeline = load_timeline(timeline_path)
    segments = timeline["segments"]

    corrections = 0
    if lexicon_path is not None:
        corrected = apply_lexicon(segments, load_lexicon(lexicon_path))
        corrections = sum(
            1 for before, after in zip(segments, corrected)
            if before.get("text") != after.get("text")
        )
        segments = corrected

    return timeline, segments, corrections


@dataclass(frozen=True)
class NotesPreview:
    timeline: str
    segments: int
    words: int
    approx_tokens: int
    lexicon_corrections: int
    would_write: str


def preview_notes(timeline_path: Path, out_dir: Path | None = None,
                  lexicon_path: Path | None = None) -> NotesPreview:
    """Everything up to the model call, and nothing that costs money or writes a file.

    The preview every tool in Shelby owes. It is the one notes operation that needs no
    credentials, which is exactly why it is the approval surface.
    """
    from meetnotes.extract import transcript_for_model

    timeline_path = resolve_timeline(timeline_path)
    timeline, segments, corrections = _load_segments(timeline_path, lexicon_path)
    prompt = transcript_for_model(segments)
    source = timeline.get("source", timeline_path.stem)
    target = (out_dir or timeline_path.parent) / f"{Path(source).stem}.notes.md"

    return NotesPreview(
        timeline=str(timeline_path),
        segments=len(segments),
        words=len(prompt.split()),
        # Deliberately labelled "approx": a real count needs the tokenizer, and this only
        # exists to tell a caller whether they are about to send a page or a novel.
        approx_tokens=len(prompt) // 4,
        lexicon_corrections=corrections,
        would_write=str(target),
    )


@dataclass(frozen=True)
class NotesResult:
    markdown: str
    json: str
    title: str
    summary: str
    verified_claims: int
    dropped_claims: int
    decisions: int
    actions: int
    questions: int
    model: str
    effort: str = ""
    output_tokens: int = 0
    seconds: float = 0.0


def generate_notes(timeline_path: Path, config: ModelConfig, out_dir: Path | None = None,
                   lexicon_path: Path | None = None, effort: str = "high") -> NotesResult:
    """Read a timeline, ask a model what happened, keep only the claims it can evidence."""
    from meetnotes.client import NoModel, check_configured, explain_model_error
    from meetnotes.extract import ModelOutOfRoom, extract_notes
    from meetnotes.verify import verify

    try:
        check_configured(config, "notes")
    except NoModel as error:
        raise OperationError(str(error)) from error
    timeline_path = resolve_timeline(timeline_path)
    timeline, segments, _ = _load_segments(timeline_path, lexicon_path)
    source = timeline.get("source", timeline_path.stem)
    duration = float(timeline.get("duration", 0.0))

    try:
        raw, usage = extract_notes(segments, config, effort=effort)
    except ModelOutOfRoom as error:
        raise OperationError(f"no notes written: {error}") from error
    except Exception as error:
        plain = explain_model_error(error, config, "notes")
        if plain is None:
            raise
        raise OperationError(plain) from error
    notes = verify(raw, TimelineIndex(segments))

    target_dir = out_dir or timeline_path.parent
    md_path, json_path = write_notes(
        target_dir / f"{Path(source).stem}.notes.md",
        notes,
        notes_title(notes, source),
        source,
        duration,
    )

    return NotesResult(
        markdown=str(md_path),
        json=str(json_path),
        title=notes_title(notes, source),
        summary=notes.summary,
        verified_claims=notes.claim_count,
        dropped_claims=len(notes.dropped),
        decisions=len(notes.decisions),
        actions=len(notes.actions),
        questions=len(notes.questions),
        model=config.resolved_model,
        effort=effort,
        output_tokens=usage.output_tokens,
        seconds=usage.seconds,
    )


# ---------------------------------------------------------------------------
# Minutes
# ---------------------------------------------------------------------------

def preview_minutes(timeline_path: Path, out_dir: Path | None = None,
                    lexicon_path: Path | None = None) -> NotesPreview:
    """preview_notes for minutes: the same transcript goes to the model, to a different file."""
    preview = preview_notes(timeline_path, out_dir, lexicon_path)
    target = Path(preview.would_write).with_name(
        Path(preview.would_write).name.replace(".notes.md", ".minutes.md"))
    return NotesPreview(**{**asdict(preview), "would_write": str(target)})


@dataclass(frozen=True)
class MinutesResult:
    markdown: str
    json: str
    title: str
    items: list[str]
    verified_claims: int
    dropped_claims: int
    model: str
    effort: str
    output_tokens: int
    seconds: float


def generate_minutes(timeline_path: Path, config: ModelConfig, out_dir: Path | None = None,
                     lexicon_path: Path | None = None, effort: str | None = None) -> MinutesResult:
    """Formal minutes, held to the notes' rule: every point must be found in the transcript."""
    from meetnotes.client import NoModel, check_configured, explain_model_error
    from meetnotes.extract import MINUTES_EFFORT, ModelOutOfRoom, extract_minutes
    from meetnotes.verify import verify_minutes

    try:
        check_configured(config, "minutes")
    except NoModel as error:
        raise OperationError(str(error)) from error
    effort = effort or MINUTES_EFFORT
    timeline_path = resolve_timeline(timeline_path)
    timeline, segments, _ = _load_segments(timeline_path, lexicon_path)
    source = timeline.get("source", timeline_path.stem)
    duration = float(timeline.get("duration", 0.0))

    try:
        raw, usage = extract_minutes(segments, config, effort=effort)
    except ModelOutOfRoom as error:
        raise OperationError(f"no minutes written: {error}") from error
    except Exception as error:
        plain = explain_model_error(error, config, "minutes")
        if plain is None:
            raise
        raise OperationError(plain) from error
    minutes = verify_minutes(raw, TimelineIndex(segments))

    target_dir = out_dir or timeline_path.parent
    md_path, json_path = write_minutes(
        target_dir / f"{Path(source).stem}.minutes.md", minutes, source, duration)

    return MinutesResult(
        markdown=str(md_path),
        json=str(json_path),
        title=minutes_title(minutes, source),
        items=[item.heading for item in minutes.items],
        verified_claims=minutes.claim_count,
        dropped_claims=len(minutes.dropped),
        model=config.resolved_model,
        effort=effort,
        output_tokens=usage.output_tokens,
        seconds=usage.seconds,
    )


# ---------------------------------------------------------------------------
# Reading a transcript
# ---------------------------------------------------------------------------

# A new paragraph starts when the speaker changes, or after this much audio, so a caller
# can place a line in time without a timestamp on every segment.
PARAGRAPH_SECONDS = 60.0
# A two-hour meeting renders to about 90k characters. The cap exists for the six-hour
# recording, where one unpaged read would crowd out everything else a caller holds.
MAX_READ_CHARS = 200_000


@dataclass(frozen=True)
class TranscriptText:
    timeline: str | None  # None: read from the markdown, for a transcript written before timelines
    source: str
    duration: float
    start: float
    end: float
    segments: int
    truncated: bool
    text: str


def _paragraphs(segments: list[dict]) -> list[tuple[float, str]]:
    """Group segments into (start, text) paragraphs, each opening with its timestamp."""
    from transcribe import hhmmss

    grouped: list[tuple[float, object, list[str]]] = []
    for segment in segments:
        start = float(segment.get("start", 0.0))
        speaker = segment.get("speaker")
        if not grouped or speaker != grouped[-1][1] or start - grouped[-1][0] >= PARAGRAPH_SECONDS:
            grouped.append((start, speaker, []))
        grouped[-1][2].append(str(segment.get("text", "")))

    out: list[tuple[float, str]] = []
    for start, speaker, texts in grouped:
        label = f" Speaker {speaker + 1}:" if isinstance(speaker, int) else ""
        out.append((start, " ".join(f"[{hhmmss(start)}]{label} {' '.join(texts)}".split())))
    return out


def read_transcript(path: Path, start: float | None = None, end: float | None = None,
                    lexicon_path: Path | None = None) -> TranscriptText:
    """The transcript as timestamped paragraphs, whole or between two offsets in seconds.

    A VIEW for a caller to read and answer questions from -- not the verified path. The
    timestamps are the timeline's own, copied as they are, but whatever a caller writes
    from this text is not checked against the transcript the way notes and minutes are.
    """
    timeline_path = resolve_timeline(path)
    lower = start or 0.0
    upper = end if end is not None else float("inf")
    if upper <= lower:
        raise OperationError(f"end ({end}) must be after start ({lower}).")
    if path.suffix == ".md" and not timeline_path.exists() and path.is_file():
        return _read_markdown_transcript(path, lower, upper)
    timeline, segments, _ = _load_segments(timeline_path, lexicon_path)
    chosen = [s for s in segments
              if float(s.get("end", 0.0)) > lower and float(s.get("start", 0.0)) < upper]

    kept: list[str] = []
    size, truncated = 0, False
    reached = float(chosen[-1]["end"]) if chosen else lower
    for opened_at, paragraph in _paragraphs(chosen):
        # Always return at least one paragraph: an empty page with end == start would send
        # a caller told to "call again with start=end" round in a loop forever.
        if kept and size + len(paragraph) > MAX_READ_CHARS:
            # Stop at a paragraph boundary and say where, so the caller can ask for the rest
            # with start=end rather than silently receiving half a meeting.
            truncated, reached = True, opened_at
            break
        kept.append(paragraph)
        size += len(paragraph) + 2

    return TranscriptText(
        timeline=str(timeline_path),
        source=str(timeline.get("source", timeline_path.stem)),
        duration=float(timeline.get("duration", 0.0)),
        start=lower,
        end=reached,
        segments=len(chosen),
        truncated=truncated,
        text="\n\n".join(kept),
    )


# How transcribe.py wrote a paragraph's start into the markdown: `**Speaker 2** *[00:01:05]*` on a line of its
# own when speakers were labelled, `**[00:01:05]** text` when they were not.
_MD_SPEAKER = re.compile(r"^\*\*(Speaker \d+)\*\* \*\[(\d\d):(\d\d):(\d\d)\]\*$")
_MD_STAMPED = re.compile(r"^\*\*\[(\d\d):(\d\d):(\d\d)\]\*\*\s*(.*)$", re.S)


def _read_markdown_transcript(path: Path, lower: float, upper: float) -> TranscriptText:
    """A transcript written before timelines existed, read from its markdown into the same
    `[hh:mm:ss] Speaker N: text` paragraphs. Its stamps are the ones transcribe.py wrote into the
    file. No lexicon is applied: corrections work on a timeline's segments, and this has none."""
    header = transcript_header(path)
    text = path.read_text(encoding="utf-8")
    if header:
        lines = text.splitlines(keepends=True)
        closing = next(i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---")
        text = "".join(lines[closing + 1:])
    paragraphs: list[tuple[float, str]] = []
    speaker, at = "", 0.0
    for block in (b.strip() for b in text.split("\n\n")):
        if not block or block.startswith("# "):
            continue
        named = _MD_SPEAKER.match(block)
        if named:
            speaker, at = named.group(1), _clock(*named.group(2, 3, 4))
            paragraphs.append((at, f"[{_stamp(at)}] {speaker}:"))
            continue
        stamped = _MD_STAMPED.match(block)
        if stamped:
            at = _clock(*stamped.group(1, 2, 3))
            paragraphs.append((at, f"[{_stamp(at)}] {' '.join(stamped.group(4).split())}"))
        elif paragraphs and speaker:
            opened, said = paragraphs[-1]
            paragraphs[-1] = (opened, f"{said} {' '.join(block.split())}")
        else:
            paragraphs.append((at, " ".join(block.split())))
    chosen = [(at, line) for at, line in paragraphs if lower <= at < upper]
    kept: list[str] = []
    size, truncated, reached = 0, False, chosen[-1][0] if chosen else lower
    for opened_at, paragraph in chosen:
        if kept and size + len(paragraph) > MAX_READ_CHARS:
            truncated, reached = True, opened_at
            break
        kept.append(paragraph)
        size += len(paragraph) + 2
    return TranscriptText(
        timeline=None,
        source=header.get("source") or path.stem,
        duration=_seconds(header.get("duration")) or 0.0,
        start=lower,
        end=reached,
        segments=len(chosen),
        truncated=truncated,
        text="\n\n".join(kept),
    )


def _clock(hours: str, minutes: str, seconds: str) -> float:
    return float(int(hours) * 3600 + int(minutes) * 60 + int(seconds))


def _stamp(seconds: float) -> str:
    whole = int(seconds)
    return f"{whole // 3600:02d}:{whole % 3600 // 60:02d}:{whole % 60:02d}"


@dataclass(frozen=True)
class WrittenText:
    path: str
    kind: str
    generated: str | None
    text: str


WRITTEN_SUFFIXES = {".notes.md": "notes", ".minutes.md": "minutes"}


def read_written(path: Path, transcript_dir: Path) -> WrittenText:
    """Notes or minutes meet-ai wrote, as their markdown, without the header.

    Only a .notes.md or .minutes.md file directly in the transcript folder is read: this is a
    door to what meet-ai wrote, not to any file a caller can name."""
    kind = next((k for suffix, k in WRITTEN_SUFFIXES.items() if path.name.endswith(suffix)), None)
    if kind is None:
        raise OperationError(f"{path.name} is not notes or minutes: their names end in .notes.md or .minutes.md.")
    folder = transcript_dir.resolve()
    real = path.resolve()  # follows links: the check is on where the file really is
    if real.parent != folder or not real.is_file():
        raise OperationError(f"no notes or minutes called {path.name} in the transcript folder.")
    text = real.read_text(encoding="utf-8")
    header = transcript_header(real)
    if header:
        # drop the header: everything up to and including its closing line
        lines = text.splitlines(keepends=True)
        closing = next(i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---")
        text = "".join(lines[closing + 1:]).lstrip("\n")
    return WrittenText(path=str(real), kind=kind, generated=header.get("generated") or None, text=text)


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TranscriptionResult:
    markdown: str
    timeline: str
    duration_seconds: float
    segments: int
    language: str
    speakers: int


def probe_audio_duration(audio_path: Path) -> float:
    from transcribe import probe_duration

    if not audio_path.exists():
        raise OperationError(f"no audio file at {audio_path}")
    return probe_duration(audio_path)


def transcribe_audio(audio_path: Path, out_dir: Path, diarize: bool = False,
                     speakers: int = 0, language: str | None = None,
                     prompt: str | None = None, force: bool = False,
                     max_seconds: float = MAX_SYNC_AUDIO_SECONDS) -> TranscriptionResult:
    """Decode one file to a transcript and a timeline. Synchronous, and capped.

    The options object comes from transcribe.py's own parser rather than a second set of
    defaults here -- twenty restated defaults would drift from the canonical ones within a
    release.
    """
    from transcribe import build_parser, load_whisper, timeline_path, transcribe_file

    duration = probe_audio_duration(audio_path)
    if duration > max_seconds:
        raise OperationError(
            f"{audio_path.name} is {duration / 60:.0f} minutes, past the "
            f"{max_seconds / 60:.0f}-minute cap for a synchronous call. Decoding takes "
            f"roughly as long as the recording, which no request survives. Use "
            f"start_transcription instead: it returns at once and runs in the background."
        )

    argv = [str(audio_path), "-o", str(out_dir)]
    if diarize:
        argv.append("-d")
    if speakers:
        argv += ["-s", str(speakers)]
    if language:
        argv += ["-l", language]
    if prompt:
        argv += ["-p", prompt]
    if force:
        argv.append("-f")

    args = build_parser().parse_args(argv)
    if str(args.chunk_minutes).lower() == "auto":
        args.chunk_minutes = None

    # transcribe.py writes progress and a summary to stdout. For the MCP door stdout is the
    # protocol stream, so it is captured here rather than at each door -- one place to be
    # right, and the CLI gets the same facts from the returned value.
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink):
        model = load_whisper(args)
        written = transcribe_file(model, audio_path, args)

    if written is None:
        raise OperationError(
            f"a transcript for {audio_path.name} already exists in {out_dir}. "
            f"Pass force=true to redo it."
        )

    produced = load_timeline(timeline_path(written))
    return TranscriptionResult(
        markdown=str(written),
        timeline=str(timeline_path(written)),
        duration_seconds=float(produced.get("duration", duration)),
        segments=len(produced["segments"]),
        language=str(produced.get("language", "")),
        speakers=int(produced.get("speakers", 0)),
    )


def as_dict(value: object) -> dict:
    """Dataclass to plain JSON-able dict, for a door that returns JSON."""
    return asdict(value)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Capture (layer 1)
# ---------------------------------------------------------------------------
#
# Recording is a session, not a call: start and stop both return at once, and the audio is
# written by a detached recorder in between. That is what lets a model say "record this
# meeting" without a chat turn blocking until the meeting ends.

def list_audio_sources() -> list[dict]:
    import capture

    try:
        return capture.list_sources()
    except capture.CaptureError as error:
        raise OperationError(str(error)) from error


def recording_status(audio_dir: Path) -> dict | None:
    """The unfinished session, if any -- including one whose recorder died, which `stop`
    will still recover."""
    import capture

    session = capture.active(audio_dir)
    if session is None:
        return None
    return {**asdict(session), "recorded_seconds": round(capture.elapsed_seconds(session), 1)}


def start_recording(audio_dir: Path, source: str | None = None, consent: str | None = None,
                    name: str | None = None) -> dict:
    import capture

    try:
        return asdict(capture.start(audio_dir, source=source, consent=consent, name=name))
    except capture.CaptureError as error:
        raise OperationError(str(error)) from error


def stop_recording(audio_dir: Path, session_id: str | None = None) -> dict:
    """Finish a session, or recover an interrupted one. Returns where the audio landed."""
    import capture

    try:
        return asdict(capture.stop(audio_dir, session_id))
    except capture.CaptureError as error:
        raise OperationError(str(error)) from error


# ---------------------------------------------------------------------------
# Transcription jobs
# ---------------------------------------------------------------------------
#
# The synchronous transcribe_audio above stays for short clips, because it hands back the
# result in one call. Anything longer goes through a job: started at once, polled for
# progress, no cap -- the decode runs as long as it needs while nothing waits on it.

def start_transcription(audio_path: Path, out_dir: Path, diarize: bool = False,
                        speakers: int = 0, language: str | None = None,
                        vocabulary: str | None = None, force: bool = False) -> dict:
    import jobs

    try:
        return asdict(jobs.start(audio_path, out_dir, diarize=diarize, speakers=speakers,
                                 language=language, vocabulary=vocabulary, force=force))
    except jobs.JobError as error:
        raise OperationError(str(error)) from error


def transcription_status(out_dir: Path, job_id: str | None = None) -> dict | None:
    """One job by id, or the most recent. Refreshed from its process and its log."""
    import jobs

    try:
        job = jobs.get(out_dir, job_id) if job_id else jobs.latest(out_dir)
    except jobs.JobError as error:
        raise OperationError(str(error)) from error
    return asdict(job) if job else None
