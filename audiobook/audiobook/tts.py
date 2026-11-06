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


def load_speaking_model():
    """Pocket TTS for speaking a chat reply while someone waits (speaking.py), kept apart from `load_model`'s.
    On the processor it is the 8-bit model, measured 2.0x real time against 1.38x on this laptop; on a card it
    is the full model, since dynamic 8-bit is a processor technique."""
    import torch
    from pocket_tts import TTSModel

    model = TTSModel.load_model(quantize=not torch.cuda.is_available())
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
    def __init__(self, voice: str):
        self.model = load_model()
        self.sample_rate: int = self.model.sample_rate

        voice_path = Path(resolve_voice(voice))
        if not voice_path.exists():
            # A built-in preset name such as "alba".
            self.voice_id = voice
            self.state = self.model.get_state_for_audio_prompt(voice)
            return

        self.voice_id = f"{voice_path.stem}-{file_hash(voice_path)}"
        if voice_path.suffix == ".safetensors":
            # An already-cloned voice, e.g. voices/abigail.safetensors.
            self.state = self.model.get_state_for_audio_prompt(str(voice_path))
            return

        cached = VOICES_DIR / f"{self.voice_id}.safetensors"
        if cached.exists():
            self.state = self.model.get_state_for_audio_prompt(str(cached))
            return

        VOICES_DIR.mkdir(exist_ok=True)
        reference = VOICES_DIR / f"{self.voice_id}.wav"
        prepare_reference(voice_path, reference)
        print(f"Cloning voice from {voice_path}...")
        self.state = clone(reference, cached)

    def synthesize(self, text: str) -> np.ndarray:
        return to_array(self.model.generate_audio(self.state, text))
