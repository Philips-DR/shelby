"""Transcribing on an NVIDIA GPU when there is one, and on the CPU otherwise.

No GPU, no model: CTranslate2's answers are faked, and so is the model, which records how it was asked to load.
What must hold: a card CTranslate2 can see is used with cuBLAS loaded first; anything else is the CPU exactly as
before, so a long recording's finished chunks (keyed by the compute type) are still reused.
"""

import sys
from types import SimpleNamespace

import pytest

import transcribe
from transcribe import CPU_COMPUTE, build_parser, cache_key, choose_device, load_cublas, load_whisper


def ct2(cards: int, cuda_types=("float32", "float16", "int8_float16")):
    return SimpleNamespace(get_cuda_device_count=lambda: cards,
                           get_supported_compute_types=lambda device: set(cuda_types))


@pytest.fixture
def cublas_ok(monkeypatch):
    monkeypatch.setattr(transcribe, "load_cublas", lambda: None)


def test_no_card_is_the_cpu_as_before():
    assert choose_device(ct2(0), None) == ("cpu", "int8_float32", "CPU")
    assert choose_device(ct2(0), "int8") == ("cpu", "int8", "CPU")  # a named compute type is kept


def test_a_card_with_cublas_runs_in_float16(cublas_ok):
    assert choose_device(ct2(1), None) == ("cuda", "float16", "GPU")
    assert choose_device(ct2(1), "int8_float16") == ("cuda", "int8_float16", "GPU")


def test_a_card_too_old_for_float16_runs_in_float32(cublas_ok):
    assert choose_device(ct2(1, cuda_types=("float32", "int8")), None) == ("cuda", "float32", "GPU")


def test_a_card_without_cublas_is_the_cpu_and_says_why(monkeypatch):
    monkeypatch.setattr(transcribe, "load_cublas", lambda: "cuBLAS for CUDA 12 is not installed")
    device, compute, where = choose_device(ct2(1), None)
    assert (device, compute) == ("cpu", "int8_float32")
    assert where == "CPU: there is an NVIDIA card, but cuBLAS for CUDA 12 is not installed"


def test_cublas_is_loaded_from_the_pip_package_lt_first(monkeypatch, tmp_path):
    lib = tmp_path / "nvidia" / "cublas" / "lib"
    lib.mkdir(parents=True)
    for name in transcribe.CUBLAS:
        (lib / name).write_bytes(b"")
    spec = SimpleNamespace(submodule_search_locations=[str(lib.parent)])
    monkeypatch.setattr("importlib.util.find_spec", lambda name: spec)
    loaded = []
    monkeypatch.setattr("ctypes.CDLL", lambda path, mode=0: loaded.append(path))
    assert load_cublas() is None
    assert loaded == [str(lib / "libcublasLt.so.12"), str(lib / "libcublas.so.12")]


def test_without_the_package_cublas_is_looked_for_by_name_and_its_absence_said(monkeypatch):
    def missing(name):
        raise ModuleNotFoundError(name)

    def refuse(path, mode=0):
        raise OSError(f"{path}: cannot open shared object file")

    monkeypatch.setattr("importlib.util.find_spec", missing)
    monkeypatch.setattr("ctypes.CDLL", refuse)
    assert "cuBLAS for CUDA 12 is not installed" in load_cublas()


class Whisper:
    loads: list = []

    def __init__(self, model, device, compute_type, **options):
        if device == "cuda" and self.refuse:
            raise RuntimeError(self.refuse)
        self.loads.append((device, compute_type))


@pytest.fixture
def whisper(monkeypatch):
    Whisper.loads = []
    Whisper.refuse = None
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=Whisper))
    return Whisper


def args_for(monkeypatch, cards, environment=None):
    monkeypatch.delenv("WHISPER_COMPUTE", raising=False)
    if environment:
        monkeypatch.setenv("WHISPER_COMPUTE", environment)
    monkeypatch.setitem(sys.modules, "ctranslate2", ct2(cards))
    return build_parser().parse_args(["meeting.flac"])


def test_on_the_cpu_the_settings_and_the_chunk_cache_are_unchanged(monkeypatch, whisper, tmp_path, capsys):
    args = args_for(monkeypatch, 0)
    assert args.compute_type is None  # settled when the model loads, not by the parser
    load_whisper(args)
    assert whisper.loads == [("cpu", "int8_float32")]
    assert "Loading model 'distil-large-v3' (CPU, int8_float32)..." in capsys.readouterr().out
    # the key a chunk was cached under before this change, when the parser's default was int8_float32
    audio = tmp_path / "meeting.flac"
    audio.write_bytes(b"x")
    before = SimpleNamespace(**{**vars(args), "compute_type": "int8_float32"})
    assert cache_key(audio, args, 10.0) == cache_key(audio, before, 10.0)


def test_on_a_card_whisper_loads_on_the_gpu(monkeypatch, whisper, cublas_ok, capsys):
    args = args_for(monkeypatch, 1)
    load_whisper(args)
    assert whisper.loads == [("cuda", "float16")] and args.compute_type == "float16"
    assert "(GPU, float16)" in capsys.readouterr().out  # jobs.py reads "Loading model" for its phase


def test_a_card_that_cannot_take_the_model_falls_back_to_the_cpu(monkeypatch, whisper, cublas_ok, capsys):
    whisper.refuse = "CUDA failed with error out of memory\nmore"
    args = args_for(monkeypatch, 1)
    load_whisper(args)
    assert whisper.loads == [("cpu", CPU_COMPUTE)] and args.compute_type == CPU_COMPUTE
    assert "Could not use the GPU (CUDA failed with error out of memory); using the CPU (int8_float32)." in capsys.readouterr().out


def test_a_compute_type_set_in_the_environment_is_kept(monkeypatch, whisper):
    args = args_for(monkeypatch, 0, environment="int8")
    load_whisper(args)
    assert whisper.loads == [("cpu", "int8")]
