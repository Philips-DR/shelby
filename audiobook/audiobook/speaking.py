"""Speaking a chat reply: a sentence or two in, an MP3 of it out, while someone waits.

Not a render. A render is a detached job of hours that loads the full model; a reply is seconds, and a person is
listening for the first word. So this keeps its own model loaded between calls, and lets it go after
`idle_seconds` so its memory goes back to a laptop with little to spare.

On the processor it is the 8-bit model (`quantize=True`). Measured on this laptop (2026-11-06, the abigail voice,
a five-sentence reply): 2.0x real time against the full model's 1.38x, a short opening phrase ready in 0.8 s
against 1.35 s, every word right when Whisper read it back (7 runs of 7), and likeness to abigail's own recording
0.953 against 0.957. Kyutai's optional torchao made it six times slower here and is not used. On an NVIDIA card
it is the full model: dynamic 8-bit is a processor technique.

Nothing is written but a timestamp: the audio comes back as base64 in the result, and each call touches
`workers.SPEAKING_MARK`, so a render running beside it makes one piece at a time while a reply is being read.
"""

from __future__ import annotations

import base64
import contextlib
import gc
import io
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .chunk import chunk_paragraph
from .speech import for_speech
from .tts import PRESETS, VOICES_DIR, load_speaking_model, resolve_voice, to_array
from .workers import SPEAKING_MARK

MAX_SPEAK_CHARS = 600
SPEAK_IDLE_SECONDS = 600
DEFAULT_VOICE = "abigail"
FALLBACK_VOICE = "alba"  # a preset, for a machine with no saved voice
BETWEEN_CHUNKS_S = 0.15


@dataclass(frozen=True)
class SpeechResult:
    audio: str  # base64 MP3
    mime: str
    seconds: float
    voice: str
    # This call waited for the model to load (a few seconds), which the page can say rather than look stuck.
    loaded_now: bool


def _load_model() -> Any:
    # Pocket TTS and place() report on stdout, which for the MCP door is the protocol stream.
    with contextlib.redirect_stdout(io.StringIO()):
        return load_speaking_model()


def _mp3(audio: np.ndarray, sample_rate: int) -> bytes:
    done = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "f32le", "-ar", str(sample_rate), "-ac", "1", "-i", "-",
         "-c:a", "libmp3lame", "-q:a", "4", "-f", "mp3", "-"],
        input=audio.astype(np.float32).tobytes(), capture_output=True, check=True,
    )
    return done.stdout


def default_voice() -> str:
    return DEFAULT_VOICE if (VOICES_DIR / f"{DEFAULT_VOICE}.safetensors").exists() else FALLBACK_VOICE


class Speaker:
    """One Pocket TTS, kept loaded between replies and released when they stop coming."""

    def __init__(self, idle_seconds: float = SPEAK_IDLE_SECONDS, load: Callable[[], Any] = _load_model,
                 encode: Callable[[np.ndarray, int], bytes] = _mp3, mark: Path = SPEAKING_MARK) -> None:
        self.idle_seconds = idle_seconds
        self.mark = mark
        self._load = load
        self._encode = encode
        self._lock = threading.Lock()
        self._model: Any = None
        self._voices: dict[str, Any] = {}
        self._timer: threading.Timer | None = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def speak(self, text: str, voice: str | None = None) -> SpeechResult:
        if len(text) > MAX_SPEAK_CHARS:
            raise ValueError(f"{len(text)} characters is more than the {MAX_SPEAK_CHARS} one call speaks: "
                             f"send a reply a sentence or two at a time")
        spoken = for_speech(text)
        if not any(c.isalnum() for c in spoken):
            raise ValueError("there is nothing in that to say")
        name = voice or default_voice()
        try:  # a render running beside this makes one piece at a time for a while (workers.py)
            self.mark.parent.mkdir(parents=True, exist_ok=True)
            self.mark.touch()
        except OSError:
            pass
        if name not in PRESETS and not (VOICES_DIR / f"{name}.safetensors").exists():
            raise FileNotFoundError(f"no voice called {name}")
        with self._lock:
            loaded_now = self._model is None
            if loaded_now:
                self._model = self._load()
            state = self._voices.get(name)
            if state is None:
                state = self._voices[name] = self._model.get_state_for_audio_prompt(resolve_voice(name))
            rate = self._model.sample_rate
            gap = np.zeros(int(BETWEEN_CHUNKS_S * rate), dtype=np.float32)
            pieces: list[np.ndarray] = []
            for chunk in chunk_paragraph(spoken):
                if pieces:
                    pieces.append(gap)
                pieces.append(to_array(self._model.generate_audio(state, chunk)).astype(np.float32))
            self._release_later()
        audio = np.concatenate(pieces)
        return SpeechResult(audio=base64.b64encode(self._encode(audio, rate)).decode("ascii"), mime="audio/mpeg",
                            seconds=round(len(audio) / rate, 2), voice=name, loaded_now=loaded_now)

    def _release_later(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
        self._timer = threading.Timer(self.idle_seconds, self.release)
        self._timer.daemon = True
        self._timer.start()

    def release(self) -> None:
        """Let the model go: the next reply loads it again."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._model = None
            self._voices.clear()
        gc.collect()
