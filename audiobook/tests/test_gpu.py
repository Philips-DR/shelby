"""Speaking on an NVIDIA GPU when there is one, and on the processor otherwise.

No GPU here, and no model: torch's own answer is faked, and the model is a stand-in that records where it was put.
What must hold: a GPU PyTorch can use is used, anything else leaves the processor doing the work as before, and the
audio comes back as numbers whichever device made it.
"""

from types import SimpleNamespace

import numpy as np
import pytest
import torch

from audiobook import tts


class Model:
    def __init__(self, refuse=None):
        self.moves = []
        self.refuse = refuse

    def to(self, device):
        if device == "cuda" and self.refuse:
            raise RuntimeError(self.refuse)
        self.moves.append(device)
        return self


def fake_torch(available, name="NVIDIA GeForce RTX 3060"):
    return SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: available, get_device_name=lambda i: name))


def test_a_gpu_pytorch_can_use_is_used(capsys):
    model = Model()
    assert tts.place(model, fake_torch(True)) == "cuda"
    assert model.moves == ["cuda"]
    assert "Speaking on the GPU: NVIDIA GeForce RTX 3060." in capsys.readouterr().out


def test_without_one_the_model_stays_on_the_processor(capsys):
    model = Model()
    assert tts.place(model, fake_torch(False)) == "cpu"
    assert model.moves == []  # never moved: exactly as before
    assert "Speaking on the processor." in capsys.readouterr().out


def test_a_card_that_cannot_take_the_model_falls_back_to_the_processor(capsys):
    model = Model(refuse="CUDA out of memory. Tried to allocate 20.00 MiB\nmore detail")
    assert tts.place(model, fake_torch(True)) == "cpu"
    assert model.moves == ["cpu"]  # whatever had moved is brought back
    out = capsys.readouterr().out
    assert "Could not use the GPU (CUDA out of memory. Tried to allocate 20.00 MiB); speaking on the processor." in out


def test_the_loading_line_the_job_status_reads_is_still_printed(monkeypatch, capsys):
    import sys

    loaded = Model()
    monkeypatch.setitem(sys.modules, "pocket_tts", SimpleNamespace(TTSModel=SimpleNamespace(load_model=lambda: loaded)))
    tts.load_model.cache_clear()
    try:
        assert tts.load_model() is loaded
    finally:
        tts.load_model.cache_clear()
    assert capsys.readouterr().out.startswith("Loading Pocket TTS...")  # background.read_progress looks for it


class GpuAudio:
    """A tensor in a GPU's memory: numpy refuses it, as torch does, until it is copied to the processor."""

    def __init__(self, values):
        self.values = values

    def numpy(self):
        raise TypeError("can't convert cuda:0 device type tensor to numpy. Use Tensor.cpu() first.")

    def cpu(self):
        return torch.tensor(self.values)


def test_audio_made_on_a_gpu_comes_back_as_numbers(monkeypatch):
    model = SimpleNamespace(sample_rate=24000, get_state_for_audio_prompt=lambda voice: {"voice": voice},
                            generate_audio=lambda state, text: GpuAudio([0.25, -0.5]))
    monkeypatch.setattr(tts, "load_model", lambda: model)
    monkeypatch.setattr(tts, "load_speaking_model", lambda: model)  # what a Narrator speaks with by default
    with pytest.raises(TypeError):
        GpuAudio([0.0]).numpy()
    spoken = tts.Narrator("alba").synthesize("Hello.")
    assert isinstance(spoken, np.ndarray) and spoken.tolist() == [0.25, -0.5]


def test_audio_made_on_the_processor_is_unchanged():
    audio = torch.tensor([0.125, 0.75])
    assert tts.to_array(audio).tolist() == [0.125, 0.75]
