"""Dictation: the chat page's microphone. No model and no audio: the model and the decoder are stand-ins."""

import asyncio
import contextlib
import io
import json
import time
from types import SimpleNamespace

import pytest

from meetnotes.client import ModelConfig
from meetnotes.dictation import SAMPLE_RATE, Dictation
from meetnotes.mcp_server import ServerPaths, create_meet_ai_server
from meetnotes.operations import OperationError


class Whisper:
    """Says what it was given, and counts its loads."""

    loads = 0

    def __init__(self, name):
        Whisper.loads += 1
        self.name = name
        self.calls = []

    def transcribe(self, samples, **options):
        self.calls.append(options)
        return iter([SimpleNamespace(text=" Draft a reply "), SimpleNamespace(text="to Ama. ")]), None


def seconds_of(n):
    return lambda path: [0.0] * int(n * SAMPLE_RATE)


@pytest.fixture
def clip(tmp_path):
    path = tmp_path / "clip.webm"
    path.write_bytes(b"not decoded: the decoder is a stand-in")
    return path


@pytest.fixture(autouse=True)
def count_from_zero():
    Whisper.loads = 0


def test_a_clip_comes_back_as_its_words_in_english(clip):
    dictation = Dictation(model="base.en", load=Whisper, decode=seconds_of(4))
    result = dictation.transcribe(clip)
    assert result.text == "Draft a reply to Ama."
    assert (result.seconds, result.model, result.loaded_now) == (4.0, "base.en", True)
    # English only: an English-only model given another language writes fluent nonsense.
    assert dictation._model.calls[0]["language"] == "en"
    dictation.release()


def test_the_model_is_loaded_once_and_kept_between_clips(clip):
    dictation = Dictation(load=Whisper, decode=seconds_of(4))
    first, second = dictation.transcribe(clip), dictation.transcribe(clip)
    assert Whisper.loads == 1 and first.loaded_now and not second.loaded_now
    dictation.release()


def test_the_model_is_let_go_when_clips_stop_coming_and_loaded_again_after(clip):
    dictation = Dictation(load=Whisper, decode=seconds_of(4), idle_seconds=0.05)
    dictation.transcribe(clip)
    deadline = time.monotonic() + 2
    while dictation.loaded and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not dictation.loaded
    assert dictation.transcribe(clip).loaded_now and Whisper.loads == 2
    dictation.release()


def test_a_clip_past_the_limit_is_refused_before_a_model_is_loaded(clip):
    dictation = Dictation(load=Whisper, decode=seconds_of(121), max_seconds=120)
    with pytest.raises(OperationError, match="120-second limit"):
        dictation.transcribe(clip)
    assert Whisper.loads == 0


def test_a_file_that_is_not_audio_says_so(clip):
    def broken(path):
        raise ValueError("Invalid data found when processing input")

    with pytest.raises(OperationError, match="could not be read as audio"):
        Dictation(load=Whisper, decode=broken).transcribe(clip)


def test_a_missing_clip_says_so(tmp_path):
    with pytest.raises(OperationError, match="no audio file"):
        Dictation(load=Whisper, decode=seconds_of(1)).transcribe(tmp_path / "gone.webm")


def door(tmp_path, dictation):
    (tmp_path / "audio").mkdir(exist_ok=True)
    (tmp_path / "transcripts").mkdir(exist_ok=True)
    return create_meet_ai_server(ServerPaths(tmp_path / "audio", tmp_path / "transcripts"),
                                 ModelConfig(region="us-east-1"), dictation=dictation)


def test_the_door_returns_the_words_and_writes_nothing_to_stdout(tmp_path, clip):
    server = door(tmp_path, Dictation(load=Whisper, decode=seconds_of(4)))
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink):
        result = asyncio.run(server.call_tool("dictate", {"audio": str(clip)}))
    payload = json.loads("".join(block.text for block in result.content if block.type == "text"))
    assert payload["text"] == "Draft a reply to Ama." and sink.getvalue() == ""
    assert sorted(p.name for p in tmp_path.rglob("*") if p.is_file()) == ["clip.webm"]  # nothing written


def test_the_door_reports_a_refusal_as_an_error(tmp_path, clip):
    server = door(tmp_path, Dictation(load=Whisper, decode=seconds_of(200)))
    result = asyncio.run(server.call_tool("dictate", {"audio": str(clip)}))
    payload = json.loads("".join(block.text for block in result.content if block.type == "text"))
    assert "limit for dictation" in payload["error"]


def test_dictation_is_marked_for_the_page_only(tmp_path):
    tools = {t.name: t for t in asyncio.run(door(tmp_path, Dictation(load=Whisper)).list_tools())}
    assert tools["dictate"].meta == {"interface_only": True}
    assert tools["transcribe"].meta in (None, {})
