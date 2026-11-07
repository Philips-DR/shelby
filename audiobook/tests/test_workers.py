"""Faster renders (2026-11-06): the 8-bit model's pieces kept apart from the full model's, and a chapter's pieces made
two at a time. No model and no worker process: the voice and the pool are stand-ins."""

import sys
import time
from concurrent.futures import Future

import numpy as np
import pytest

from audiobook import render, tts, workers
from audiobook.plan import Chapter, Segment
from audiobook.speaking import Speaker
from audiobook.workers import WorkerPool, chat_is_speaking, plan_workers


class Voice:
    """What render needs of a narrator: one sample of 0.5 per character, and which pieces it was asked for."""

    def __init__(self, variant="-int8"):
        self.voice_id, self.variant, self.prompt, self.sample_rate = "abigail-1234", variant, "voices/abigail.safetensors", 100
        self.said = []

    def synthesize(self, text):
        self.said.append(text)
        return np.full(len(text), 0.5, dtype=np.float32)


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(render, "CACHE_DIR", tmp_path / "audio")
    monkeypatch.setattr(render, "encode_mp3", lambda wav, mp3, *a: mp3.write_bytes(b"ID3"))
    return tmp_path / "audio"


def chapter(*sentences):
    return Chapter(title="Opening", announce="", segments=[Segment("paragraph", " ".join(sentences), [])])


def keep(folder, text):
    folder.mkdir(parents=True, exist_ok=True)
    np.save(folder / render.ChunkRenderer._name(text), np.full(len(text), 0.25, dtype=np.float32))


def test_a_chapter_the_full_model_has_whole_is_spoken_from_it_and_one_it_has_part_of_is_made_in_8_bit(cache):
    r = render.ChunkRenderer(Voice())
    whole, part = ["Opening", "The text."], ["Opening", "New words."]
    for text in whole:
        keep(cache / "abigail-1234", text)
    assert r.choose(whole) == cache / "abigail-1234"
    assert r.missing(whole) == []
    assert r.choose(part) == cache / "abigail-1234-int8"  # never one piece from each model
    assert r.missing(part) == ["Opening", "New words."]


def test_on_a_card_the_full_model_has_one_cache_as_before(cache):
    r = render.ChunkRenderer(Voice(variant=""))
    assert r.choose(["Opening"]) == cache / "abigail-1234"


def test_each_missing_piece_is_made_once_in_order(cache):
    r = render.ChunkRenderer(Voice())
    keep(cache / "abigail-1234-int8", "Kept.")
    assert r.missing(["One.", "Kept.", "Two.", "One."]) == ["One.", "Two."]


class Pool:
    """Makes pieces as a worker would (in the same process), and remembers being closed."""

    made, closed = [], False

    def __init__(self, voice, n):
        Pool.made, Pool.closed = [], False
        self.voice = Voice()

    def generate(self, texts):
        for text in texts:
            Pool.made.append(text)
            yield text, self.voice.synthesize(text), 0.5

    def close(self):
        Pool.closed = True


def run(tmp_path, chapters, n, monkeypatch, voice=None):
    monkeypatch.setattr(workers, "WorkerPool", Pool)
    Pool.made, Pool.closed = [], False
    seen = []
    out = tmp_path / f"out{n}"
    render.render_book(chapters, voice or Voice(), out, "Book", False, 1.0, workers=n,
                       on_progress=seen.append)
    return out, seen


def test_a_render_with_workers_says_exactly_what_one_without_them_says(tmp_path, monkeypatch):
    chapters = [(1, chapter("First sentence.", "Said twice.", "Said twice.")), (2, chapter("Another one."))]
    alone, _ = run(tmp_path, chapters, 1, monkeypatch)
    one = {p.name: p.read_text() for p in alone.glob("*.json")}
    for f in (tmp_path / "audio" / "abigail-1234-int8").glob("*.npy"):
        f.unlink()  # start the second render with nothing kept
    together, seen = run(tmp_path, chapters, 2, monkeypatch)
    assert {p.name: p.read_text() for p in together.glob("*.json")} == one
    assert Pool.made == ["Opening", "First sentence. Said twice. Said twice.", "Another one."] and Pool.closed
    # Progress counts every piece once, in order, to the end.
    done = [p.chunks_done for p in seen]
    assert done[-1] == seen[-1].chunks_total and done == sorted(done)


@pytest.mark.parametrize("n", [1, 2])
def test_a_chapter_the_full_model_made_before_is_kept_and_only_the_new_one_is_made(tmp_path, monkeypatch, n):
    old = Chapter(title="Before", announce="", segments=[Segment("paragraph", "Made by the full model.", [])])
    new = Chapter(title="After", announce="", segments=[Segment("paragraph", "Not made yet.", [])])
    for text in render.chapter_texts(old):
        keep(tmp_path / "audio" / "abigail-1234", text)
    voice = Voice()
    _, seen = run(tmp_path, [(1, old), (2, new)], n, monkeypatch, voice)
    assert voice.said + Pool.made == render.chapter_texts(new)
    # The time left is worked out from the new chapter's words alone, from the start.
    assert seen[0].chars_left == sum(len(t) for t in render.chapter_texts(new))


def test_nothing_to_make_starts_no_workers(tmp_path, monkeypatch):
    chapters = [(1, chapter("Kept already."))]
    for text in render.chapter_texts(chapters[0][1]):
        keep(tmp_path / "audio" / "abigail-1234-int8", text)
    run(tmp_path, chapters, 2, monkeypatch)
    assert Pool.made == [] and not Pool.closed  # no pool was made at all


def test_progress_skips_once_what_the_workers_counted_and_counts_a_repeat():
    counted = []
    tracker = type("T", (), {"chunk_done": lambda self, text, s: counted.append(text)})()
    wrapped = render._AlreadyCounted(tracker, ["A.", "B."])
    for text in ["A.", "B.", "A.", "C."]:
        wrapped.chunk_done(text, 0.0)
    assert counted == ["A.", "C."]


@pytest.mark.parametrize("gpu, free, setting, n, why", [
    (False, 6.0, None, 2, "2 pieces at a time"),
    (False, 1.5, None, 1, "one piece at a time: only 1.5 GB of memory free"),
    (True, 12.0, None, 1, "one piece at a time, on the GPU"),
    (False, 1.0, "3", 3, "3 pieces at a time (AUDIOBOOK_RENDER_WORKERS)"),
    (False, 6.0, "many", 2, "2 pieces at a time"),
])
def test_how_many_pieces_at_once(gpu, free, setting, n, why):
    assert plan_workers(gpu, free, setting) == (n, why)


def test_a_reply_read_aloud_in_the_last_half_minute_is_seen(tmp_path):
    mark = tmp_path / "speaking"
    assert not chat_is_speaking(mark)
    mark.touch()
    assert chat_is_speaking(mark)
    assert not chat_is_speaking(mark, now=time.time() + 31)


class Executor:
    """Holds each piece until the pool waits for it, as a worker does, noting the most it held at once."""

    def __init__(self):
        self.held, self.peak = [], 0

    def submit(self, fn, text):
        future = Future()
        self.held.append((future, text))
        self.peak = max(self.peak, len(self.held))
        return future

    def finish(self, futures, return_when=None):
        for future, text in self.held:
            future.set_result((text, np.zeros(1, dtype=np.float32)))
        self.held = []
        return set(futures), set()

    def shutdown(self, **_):
        pass


def pool_with(executor, mark):
    pool = WorkerPool.__new__(WorkerPool)
    pool.workers, pool.mark, pool._pool = 2, mark, executor
    return pool


def test_two_pieces_at_a_time_but_one_while_a_reply_is_read(tmp_path, monkeypatch):
    texts = [f"Sentence {i}." for i in range(6)]
    mark = tmp_path / "speaking"
    free = Executor()
    monkeypatch.setattr(workers, "wait", lambda fs, return_when: free.finish(fs))
    # In the order they are finished, which with two at once is not always the order given: each exactly once.
    assert sorted(t for t, _, _ in pool_with(free, mark).generate(texts)) == texts
    mark.touch()
    busy = Executor()
    monkeypatch.setattr(workers, "wait", lambda fs, return_when: busy.finish(fs))
    assert sorted(t for t, _, _ in pool_with(busy, mark).generate(texts)) == texts
    assert (free.peak, busy.peak) == (2, 1)


def test_reading_a_reply_marks_it_for_a_render_beside_it(tmp_path):
    mark = tmp_path / "speaking"

    class Pocket:
        sample_rate = 24000

        def get_state_for_audio_prompt(self, prompt):
            return {}

        def generate_audio(self, state, text):
            return type("A", (), {"cpu": lambda s: s, "numpy": lambda s: np.zeros(10, dtype=np.float32)})()

    Speaker(load=Pocket, encode=lambda a, r: b"mp3", mark=mark).speak("Hello.", voice="alba")
    assert chat_is_speaking(mark)


def test_a_voice_loads_no_model_until_it_speaks_and_says_which_model_it_is(monkeypatch):
    def refuse():
        raise AssertionError("a model was loaded")

    monkeypatch.setattr(tts, "load_speaking_model", refuse)
    monkeypatch.setattr(tts, "load_model", refuse)
    monkeypatch.setattr(tts, "eight_bit_here", lambda: True)
    assert tts.Narrator("alba").variant == "-int8"
    assert tts.Narrator("alba", fast=False).variant == ""
    monkeypatch.setattr(tts, "eight_bit_here", lambda: False)  # an NVIDIA card: the full model
    assert tts.Narrator("alba").variant == ""


def test_a_worker_says_it_is_loading_while_it_loads(monkeypatch):
    """A job's status reads "loading the voice model" from that line in its log (background.py); a worker's line used to
    sit in the worker's own buffer and reach the log only when the render ended."""

    class Out:
        written, flushed = "", ""

        def write(self, text):
            Out.written += text

        def flush(self):
            Out.flushed = Out.written

    class Loading:
        state = None

        def __init__(self, voice):
            print("Loading Pocket TTS...")

    monkeypatch.setattr(sys, "stdout", Out())
    monkeypatch.setattr(tts, "Narrator", Loading)
    monkeypatch.setattr(workers, "_narrator", None)
    workers._start("alba")
    assert "Loading Pocket TTS" in Out.flushed
