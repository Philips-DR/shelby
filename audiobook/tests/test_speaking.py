"""Speaking a chat reply. No model and no ffmpeg: Pocket TTS and the encoder are stand-ins."""

import asyncio
import base64
import contextlib
import io
import json
import time

import numpy as np
import pytest

from audiobook import speaking, tts
from audiobook.mcp_server import ServerPaths, create_audiobook_server
from audiobook.speaking import MAX_SPEAK_CHARS, Speaker

RATE = 24000


class Audio:
    def __init__(self, n):
        self.samples = np.full(n, 0.1, dtype=np.float32)

    def cpu(self):
        return self

    def numpy(self):
        return self.samples


class Pocket:
    """One second of audio per call; remembers what it was asked to say and which voices it loaded."""

    loads = 0

    def __init__(self):
        Pocket.loads += 1
        self.sample_rate = RATE
        self.said = []
        self.prompts = []

    def get_state_for_audio_prompt(self, prompt):
        self.prompts.append(prompt)
        return {"voice": prompt}

    def generate_audio(self, state, text):
        self.said.append(text)
        return Audio(RATE)


def encoded(audio, rate):
    return f"mp3:{len(audio)}@{rate}".encode()


@pytest.fixture(autouse=True)
def voices(tmp_path, monkeypatch):
    Pocket.loads = 0
    folder = tmp_path / "voices"
    folder.mkdir()
    (folder / "abigail.safetensors").write_bytes(b"state")
    monkeypatch.setattr(tts, "VOICES_DIR", folder)
    monkeypatch.setattr(speaking, "VOICES_DIR", folder)
    return folder


def speaker(**kw):
    return Speaker(load=Pocket, encode=encoded, **kw)


def test_a_sentence_comes_back_as_mp3_in_abigail(voices):
    s = speaker()
    result = s.speak("I found three emails from the bank.")
    assert base64.b64decode(result.audio) == f"mp3:{RATE}@{RATE}".encode()
    assert (result.mime, result.seconds, result.voice, result.loaded_now) == ("audio/mpeg", 1.0, "abigail", True)
    assert s._model.prompts == [str(voices / "abigail.safetensors")]
    s.release()


def test_without_a_saved_abigail_a_preset_speaks(voices):
    (voices / "abigail.safetensors").unlink()
    s = speaker()
    assert s.speak("Hello.").voice == "alba"
    s.release()


def test_the_text_is_made_speakable_as_a_book_is():
    s = speaker()
    s.speak("Read Chapter IV & the notes ~ quickly.")
    assert s._model.said == ["Read Chapter Four and the notes quickly."]
    s.release()


def test_the_model_and_each_voice_are_loaded_once_and_kept():
    s = speaker()
    first, second = s.speak("One."), s.speak("Two.")
    s.speak("Three.", voice="alba")
    assert Pocket.loads == 1 and first.loaded_now and not second.loaded_now
    assert len(s._model.prompts) == 2  # abigail once, alba once
    s.release()


def test_the_model_is_let_go_when_replies_stop_coming():
    s = speaker(idle_seconds=0.05)
    s.speak("One.")
    deadline = time.monotonic() + 2
    while s.loaded and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not s.loaded
    assert s.speak("Two.").loaded_now and Pocket.loads == 2
    s.release()


def test_a_long_text_is_spoken_in_chunks_with_a_breath_between():
    s = speaker()
    sentence = "This sentence is about forty characters. "
    result = s.speak(sentence * 14)  # ~560 characters: two chunks of at most 400
    assert len(s._model.said) == 2
    assert result.seconds == pytest.approx(2 + speaking.BETWEEN_CHUNKS_S)
    s.release()


@pytest.mark.parametrize("text, problem", [
    ("x" * (MAX_SPEAK_CHARS + 1), "more than"),
    ("*** ~ ***", "nothing in that to say"),
])
def test_what_cannot_be_spoken_is_refused_before_a_model_is_loaded(text, problem):
    with pytest.raises(ValueError, match=problem):
        speaker().speak(text)
    assert Pocket.loads == 0


def test_a_voice_that_does_not_exist_is_refused_before_a_model_is_loaded():
    with pytest.raises(FileNotFoundError, match="no voice called nobody"):
        speaker().speak("Hello.", voice="nobody")
    assert Pocket.loads == 0


def door(tmp_path, s):
    return create_audiobook_server(ServerPaths(jobs_dir=tmp_path / "jobs"), speaker=s)


def test_the_door_speaks_and_writes_nothing_to_stdout(tmp_path):
    server = door(tmp_path, speaker())
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink):
        result = asyncio.run(server.call_tool("speak", {"text": "Hello there."}))
    payload = json.loads("".join(b.text for b in result.content if b.type == "text"))
    assert payload["voice"] == "abigail" and payload["mime"] == "audio/mpeg" and sink.getvalue() == ""


def test_the_door_reports_a_refusal_as_an_error(tmp_path):
    result = asyncio.run(door(tmp_path, speaker()).call_tool("speak", {"text": "Hi.", "voice": "nobody"}))
    payload = json.loads("".join(b.text for b in result.content if b.type == "text"))
    assert "no voice called nobody" in payload["error"]


def test_speaking_is_marked_for_the_page_only(tmp_path):
    tools = {t.name: t for t in asyncio.run(door(tmp_path, speaker()).list_tools())}
    assert tools["speak"].meta == {"interface_only": True}
    assert tools["start_render"].meta in (None, {})
