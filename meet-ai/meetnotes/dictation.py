"""Dictation: a short clip from the chat page's microphone, turned into text while someone waits.

Not a transcription job. A meeting is minutes to hours, decoded in the background by distil-large-v3, which
reads at 1.9x real time on long audio. A clip is seconds, and a person is waiting on it. Measured on this
machine (2026-11-06, a 10 s clip of real speech, int8_float32, the model already loaded): distil-large-v3 took
18-20 s, because Whisper pads every clip to a 30-second window, so a short clip costs what a long one does;
small 3.8-4.3 s; base.en 1.4-1.6 s. So dictation keeps its own small model, loaded on the first clip, kept while
clips keep coming, and let go after `idle_seconds` so its ~630 MB go back to a laptop with little to spare.

The clip is decoded here rather than measured with ffprobe first: a browser's MediaRecorder writes WebM with no
duration in its header, so the cap is checked on the decoded samples. Nothing is written; the caller deletes
the clip.
"""

from __future__ import annotations

import contextlib
import gc
import io
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from meetnotes.operations import OperationError

DICTATION_MODEL = "base.en"
DICTATION_MAX_SECONDS = 120
DICTATION_IDLE_SECONDS = 600
SAMPLE_RATE = 16000


@dataclass(frozen=True)
class DictationResult:
    text: str
    seconds: float
    model: str
    # This clip waited for the model to load (a few seconds), which the page can say rather than look stuck.
    loaded_now: bool


def _load_whisper(name: str) -> Any:
    from transcribe import build_parser, load_whisper

    args = build_parser().parse_args(["-m", name])
    # load_whisper reports where it runs on stdout, which for the MCP door is the protocol stream.
    with contextlib.redirect_stdout(io.StringIO()):
        return load_whisper(args)


def _decode(path: Path) -> Any:
    from faster_whisper import decode_audio

    return decode_audio(str(path), sampling_rate=SAMPLE_RATE)


class Dictation:
    """One small Whisper, kept loaded between clips and released when they stop coming."""

    def __init__(self, model: str | None = None, idle_seconds: float = DICTATION_IDLE_SECONDS,
                 max_seconds: float = DICTATION_MAX_SECONDS,
                 load: Callable[[str], Any] = _load_whisper, decode: Callable[[Path], Any] = _decode) -> None:
        self.model_name = model or os.environ.get("MEET_AI_DICTATION_MODEL") or DICTATION_MODEL
        self.idle_seconds = idle_seconds
        self.max_seconds = max_seconds
        self._load = load
        self._decode = decode
        self._lock = threading.Lock()
        self._model: Any = None
        self._timer: threading.Timer | None = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def transcribe(self, audio: Path) -> DictationResult:
        if not audio.is_file():
            raise OperationError(f"no audio file at {audio}")
        try:
            samples = self._decode(audio)
        except Exception as error:  # PyAV raises its own kinds for a file that is not audio
            raise OperationError(f"{audio.name} could not be read as audio: {error}") from error
        seconds = len(samples) / SAMPLE_RATE
        if seconds > self.max_seconds:
            raise OperationError(
                f"the clip is {seconds:.0f} s, past the {self.max_seconds:.0f}-second limit for dictation. "
                f"A longer recording is a meeting: upload it on Meetings to transcribe it."
            )
        with self._lock:
            loaded_now = self._model is None
            if loaded_now:
                self._model = self._load(self.model_name)
            # English only: base.en is English-only, and an English-only model given another language does not
            # fail, it writes fluent nonsense (CLAUDE.md, "Measured facts").
            segments, _ = self._model.transcribe(samples, language="en", beam_size=5, vad_filter=True)
            text = " ".join(segment.text.strip() for segment in segments).strip()
            self._release_later()
        return DictationResult(text=text, seconds=round(seconds, 2), model=self.model_name, loaded_now=loaded_now)

    def _release_later(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
        self._timer = threading.Timer(self.idle_seconds, self.release)
        self._timer.daemon = True
        self._timer.start()

    def release(self) -> None:
        """Let the model go: the next clip loads it again."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._model = None
        gc.collect()  # CTranslate2 frees the model's memory when the object goes
