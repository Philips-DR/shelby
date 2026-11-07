"""Pocket TTS wrapper: model loading, voice cloning, cached voice states and per-chunk synthesis."""

import hashlib
import subprocess
from functools import cache
from pathlib import Path

import numpy as np

VOICES_DIR = Path("voices")
SAMPLE_RATE = 24000
PRESETS = [
    "alba", "anna", "azelma", "bill_boerst", "caro_davy", "charles", "cosette", "eponine", "estelle", "eve",
    "fantine", "george", "jane", "javert", "jean", "marius", "mary", "michael", "paul", "peter_yearsley",
    "stuart_bell", "vera",
]  # English presets from the Pocket TTS catalogue


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def prepare_reference(src: Path, dest: Path, start: float | None = None, end: float | None = None) -> None:
    """Convert any audio file (or a window of it) to the 16-bit mono PCM WAV Pocket TTS can read.
    No filtering: highpass/loudnorm measurably reduced clone likeness."""
    window = (["-ss", str(start)] if start is not None else []) + (["-to", str(end)] if end is not None else [])
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", *window, "-i", str(src), "-ac", "1", "-ar", str(SAMPLE_RATE),
         "-c:a", "pcm_s16le", str(dest)],
        check=True,
    )


def place(model, torch) -> str:
    """Put the model on an NVIDIA GPU when PyTorch can use one, else leave it on the processor; say which.

    PyTorch's CPU build (the usual install) never sees a GPU: ./setup and the image install its CUDA
    build only where an NVIDIA card is. A card that cannot take the model (too little memory, a driver
    too old) costs nothing: it speaks on the processor, as before.
    """
    if not torch.cuda.is_available():
        print("Speaking on the processor.")
        return "cpu"
    try:
        model.to("cuda")
    except RuntimeError as error:
        model.to("cpu")
        print(f"Could not use the GPU ({str(error).splitlines()[0]}); speaking on the processor.")
        return "cpu"
    print(f"Speaking on the GPU: {torch.cuda.get_device_name(0)}.")
    return "cuda"


@cache
def load_model():
    """Load Pocket TTS once per process (a render and a voice test each run in one process)."""
    import torch
    from pocket_tts import TTSModel

    print("Loading Pocket TTS...")
    model = TTSModel.load_model()
    place(model, torch)
    return model


def eight_bit_here() -> bool:
    """Whether speech is made by the 8-bit model on this machine: yes on the processor, no on an NVIDIA card (dynamic
    8-bit is a processor technique)."""
    import torch

    return not torch.cuda.is_available()


def load_speaking_model():
    """Pocket TTS as books and chat replies are spoken (2026-11-06): the 8-bit model on the processor. Measured on this
    laptop with abigail: 2.0x real time against the full model's 1.38x, likeness 0.953 against 0.957, every word right,
    and the user heard no difference. Not cached here: a caller that keeps it (speaking.py) also lets it go."""
    import torch
    from pocket_tts import TTSModel

    print("Loading Pocket TTS...")  # background.read_progress looks for it
    model = TTSModel.load_model(quantize=eight_bit_here())
    place(model, torch)
    return model


def to_array(audio) -> np.ndarray:
    """Pocket TTS returns audio on the model's device; numpy reads it only from the processor's memory."""
    return audio.cpu().numpy()


def clone(reference_wav: Path, out: Path | None = None):
    """Voice state for a reference WAV; saved to `out` (.safetensors) when given."""
    from pocket_tts import export_model_state

    state = load_model().get_state_for_audio_prompt(str(reference_wav))
    if out is not None:
        export_model_state(state, str(out))
    return state


def resolve_voice(voice: str) -> str:
    """A saved voice's name ("abigail") → its file; paths and preset names pass through."""
    saved = VOICES_DIR / f"{voice}.safetensors"
    return str(saved) if "/" not in voice and saved.exists() else voice


class Narrator:
    """A voice, ready to speak. Its model is loaded when it first speaks, so a render whose pieces are made in worker
    processes (workers.py) holds no copy of its own. `fast` (the default) is the 8-bit model; `variant` says which
    model's pieces these are, so the chunk cache keeps them apart (render.py)."""

    def __init__(self, voice: str, fast: bool = True):
        self.fast = fast
        self.sample_rate: int = SAMPLE_RATE
        self.variant = "-int8" if fast and eight_bit_here() else ""
        self._model = None
        self._state = None

        voice_path = Path(resolve_voice(voice))
        if not voice_path.exists():
            # A built-in preset name such as "alba".
            self.voice_id = self.prompt = voice
            return

        self.voice_id = f"{voice_path.stem}-{file_hash(voice_path)}"
        if voice_path.suffix == ".safetensors":
            # An already-cloned voice, e.g. voices/abigail.safetensors.
            self.prompt = str(voice_path)
            return

        cached = VOICES_DIR / f"{self.voice_id}.safetensors"
        if not cached.exists():
            VOICES_DIR.mkdir(exist_ok=True)
            reference = VOICES_DIR / f"{self.voice_id}.wav"
            prepare_reference(voice_path, reference)
            print(f"Cloning voice from {voice_path}...")
            clone(reference, cached)
        self.prompt = str(cached)

    @property
    def model(self):
        if self._model is None:
            self._model = load_speaking_model() if self.fast else load_model()
        return self._model

    @property
    def state(self):
        if self._state is None:
            self._state = self.model.get_state_for_audio_prompt(self.prompt)
        return self._state

    def synthesize(self, text: str) -> np.ndarray:
        return to_array(self.model.generate_audio(self.state, text))
