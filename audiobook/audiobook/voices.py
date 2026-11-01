"""Voice management: add (clone from a recording), test, list. Data in, data out; no printing.

Findings behind the rules here (see CLAUDE.md): ~30 s of reference beats shorter clips; more than
30 s breaks generation (it never stops speaking); unfiltered audio clones best; which 30 s window
you pick matters, so for longer recordings several windows are tried and scored by how much the
clone sounds like the rest of the recording.
"""

import json
import re
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

import numpy as np

from .tts import PRESETS, VOICES_DIR, clone, load_model, prepare_reference, to_array

MAX_PROMPT_S = 30.0
MIN_PROMPT_S = 15.0
CANDIDATE_WINDOWS = 4
SAMPLE_TEXT = (
    "It was a quiet evening in early autumn, and the air smelled of rain. Somewhere behind him a door "
    "creaked. He turned, but there was no one there. \"Hello?\" he called. Nobody answered."
)
SCORING_TEXTS = [
    "It was a quiet evening in early autumn, and the air smelled of rain.",
    "The committee reviewed the proposal carefully, and agreed to fund the project for three more years.",
]
NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")


@dataclass
class Voice:
    name: str
    kind: str  # "cloned" or "preset"
    source: str | None = None
    window: tuple[float, float] | None = None
    similarity: float | None = None
    added: str | None = None
    consent: str | None = None  # who agreed to this voice being cloned, as the person said it


@dataclass
class AddResult:
    voice: Voice
    candidates: list[tuple[float, float, float]] = field(default_factory=list)  # (start, end, similarity)
    warnings: list[str] = field(default_factory=list)


def _decode(path: Path, sample_rate: int) -> np.ndarray:
    out = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", str(path), "-ac", "1", "-ar", str(sample_rate), "-f", "f32le", "-"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(out, dtype=np.float32)


def _pause_midpoints(path: Path) -> list[float]:
    err = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(path), "-af", "silencedetect=noise=-35dB:d=0.3", "-f", "null", "-"],
        capture_output=True, text=True,
    ).stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", err)]
    return [(a + b) / 2 for a, b in zip(starts, ends)]


def candidate_windows(duration: float, pauses: list[float], count: int = CANDIDATE_WINDOWS) -> list[tuple[float, float]]:
    """Up to `count` windows of at most 30 s, spread across the recording, cut at pauses."""
    points = [0.0] + [p for p in pauses if 0 < p < duration] + [duration]
    windows = []
    for target in np.linspace(0, max(duration - MAX_PROMPT_S, 0), count):
        start = min(points, key=lambda p: abs(p - target))
        ends = [p for p in points if start + MIN_PROMPT_S <= p <= start + MAX_PROMPT_S]
        if ends and (start, max(ends)) not in windows:
            windows.append((start, max(ends)))
    return windows


class _Similarity:
    """Speaker similarity with WavLM x-vectors (0.99 = two parts of the same real recording)."""

    def __init__(self):
        import torch
        from transformers import AutoFeatureExtractor, WavLMForXVector

        self.torch = torch
        self.fe = AutoFeatureExtractor.from_pretrained("microsoft/wavlm-base-plus-sv")
        self.model = WavLMForXVector.from_pretrained("microsoft/wavlm-base-plus-sv").eval()

    def embed(self, audio16k: np.ndarray):
        with self.torch.no_grad():
            e = self.model(**self.fe(audio16k, sampling_rate=16000, return_tensors="pt")).embeddings[0]
        return self.torch.nn.functional.normalize(e, dim=-1)


def _to16k(audio: np.ndarray, rate: int) -> np.ndarray:
    out = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "f32le", "-ar", str(rate), "-ac", "1", "-i", "-", "-ar", "16000",
         "-f", "f32le", "-"],
        input=audio.astype(np.float32).tobytes(), capture_output=True, check=True,
    ).stdout
    return np.frombuffer(out, dtype=np.float32)


def _paths(name: str) -> tuple[Path, Path, Path]:
    return VOICES_DIR / f"{name}.safetensors", VOICES_DIR / f"{name}.wav", VOICES_DIR / f"{name}.json"


def list_voices() -> list[Voice]:
    saved = []
    for meta in sorted(VOICES_DIR.glob("*.json")):
        data = json.loads(meta.read_text())
        data["window"] = tuple(data["window"]) if data.get("window") else None
        saved.append(Voice(**data))
    known = {v.name for v in saved}
    # Voices cloned before `voice add` existed have no metadata file.
    saved += [Voice(p.stem, "cloned") for p in sorted(VOICES_DIR.glob("*.safetensors")) if p.stem not in known]
    return saved + [Voice(p, "preset") for p in PRESETS]


def add_voice(
    name: str,
    clip: Path,
    start: float | None = None,
    end: float | None = None,
    search: bool = True,
    overwrite: bool = False,
    consent: str | None = None,
    on_status: Callable[[str], None] = lambda _: None,
) -> AddResult:
    if not NAME.match(name):
        raise ValueError("voice name: lowercase letters, digits, - and _ only")
    if name in PRESETS:
        raise ValueError(f"'{name}' is a built-in voice; pick another name")
    state_path, wav_path, meta_path = _paths(name)
    if state_path.exists() and not overwrite:
        raise FileExistsError(f"voice '{name}' already exists (--overwrite replaces it)")
    VOICES_DIR.mkdir(exist_ok=True)

    duration = len(_decode(clip, 16000)) / 16000
    result = AddResult(Voice(name, "cloned", str(clip), added=date.today().isoformat(), consent=consent))

    if start is not None or end is not None:
        window = (start or 0.0, min(end if end is not None else duration, (start or 0.0) + MAX_PROMPT_S))
        if end is not None and end - (start or 0.0) > MAX_PROMPT_S:
            result.warnings.append(f"window cut to {MAX_PROMPT_S:.0f} s: longer references break generation")
        windows = [window]
    elif duration <= MAX_PROMPT_S:
        windows = [(0.0, duration)]
    else:
        windows = candidate_windows(duration, _pause_midpoints(clip)) or [(0.0, MAX_PROMPT_S)]
        if not search:
            windows = windows[:1]

    if windows[0][1] - windows[0][0] < MIN_PROMPT_S:
        result.warnings.append(
            f"only {windows[0][1] - windows[0][0]:.0f} s of speech: {MIN_PROMPT_S:.0f}-{MAX_PROMPT_S:.0f} s clones better"
        )

    best = windows[0]
    if len(windows) > 1:
        on_status(f"Trying {len(windows)} windows of the recording to find the best clone...")
        sim = _Similarity()
        model = load_model()
        full = _decode(clip, 16000)
        for i, (a, b) in enumerate(windows):
            # Judge each clone against the parts of the recording it didn't hear.
            rest = np.concatenate([full[: int(a * 16000)], full[int(b * 16000):]])
            pieces = np.array_split(rest, max(1, int(len(rest) / 16000 // 20)))[:3]
            target = sim.torch.nn.functional.normalize(sum(sim.embed(p) for p in pieces), dim=-1)
            tmp = VOICES_DIR / f".{name}-candidate.wav"
            prepare_reference(clip, tmp, a, b)
            state = clone(tmp)
            spoken = [_to16k(to_array(model.generate_audio(state, t)), model.sample_rate) for t in SCORING_TEXTS]
            score = float(np.mean([float(target @ sim.embed(s)) for s in spoken]))
            tmp.unlink()
            result.candidates.append((a, b, score))
            on_status(f"  window {i + 1}/{len(windows)}: {a:.1f}-{b:.1f} s → similarity {score:.3f}")
        best_a, best_b, best_score = max(result.candidates, key=lambda c: c[2])
        best, result.voice.similarity = (best_a, best_b), round(best_score, 3)

    prepare_reference(clip, wav_path, *best)
    clone(wav_path, state_path)
    result.voice.window = (round(best[0], 2), round(best[1], 2))
    meta_path.write_text(json.dumps(asdict(result.voice), indent=1))
    return result


def test_voice(name: str, out: Path, text: str = SAMPLE_TEXT, speed: float = 0.95) -> Path:
    """Speak a sample paragraph in the voice; returns the MP3 path."""
    from .tts import Narrator

    narrator = Narrator(name)
    audio = narrator.synthesize(text).astype(np.float32)
    out.parent.mkdir(parents=True, exist_ok=True)
    tempo = [] if speed == 1 else ["-af", f"atempo={speed}"]
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "f32le", "-ar", str(narrator.sample_rate), "-ac", "1", "-i", "-",
         *tempo, "-c:a", "libmp3lame", "-q:a", "4", str(out)],
        input=audio.tobytes(), check=True,
    )
    return out
