"""How a chapter opens: its label and its title said apart, with a pause between them.

Said as one phrase, "Chapter 6 Knowing the Source of Your Dreams" ran "six" into "knowing" (Whisper's word times, on a
finished chapter: 6 ended at 1.10 s and Knowing began at 1.10). The voice is replaced by a stand-in that makes one
second of sound per word, so what is checked is the order and the silences, which is all this code decides."""

import numpy as np
import pytest

from audiobook.plan import Chapter, Segment
from audiobook.render import (
    LABEL_PAUSE,
    PARAGRAPH_PAUSE,
    SENTENCE_PAUSE,
    TITLE_PAUSE,
    ChunkRenderer,
    _timing_for_speed,
    announcement,
    chapter_texts,
    compact_timing,
    render_chapter,
)

RATE = 1000  # a sample a millisecond, so a pause of 0.7 s is 700 samples


def chapter(title: str, announce: str = "", body: str = "The text.") -> Chapter:
    return Chapter(title=title, announce=announce, segments=[Segment("paragraph", body, [])])


@pytest.mark.parametrize("title,expected", [
    ("Chapter 6 Knowing the Source of Your Dreams", ["Chapter 6.", "Knowing the Source of Your Dreams"]),
    ("Chapter 12: The Language of Symbolism", ["Chapter 12.", "The Language of Symbolism"]),
    ("Part Three, The Return of the Eagles", ["Part Three.", "The Return of the Eagles"]),
    ("Book One The Beginning", ["Book One.", "The Beginning"]),
    ("chapter 4 natural dreams", ["chapter 4.", "natural dreams"]),
])
def test_a_label_and_its_title_are_said_apart_the_label_as_a_sentence_of_its_own(title, expected):
    assert announcement(chapter(title)) == expected


@pytest.mark.parametrize("title", ["Opening", "Foreword", "Introduction", "Chapter 6", "Part Time Jobs", "Booking a Room", "Chapter"])
def test_a_title_with_no_label_to_split_is_said_whole(title):
    assert announcement(chapter(title)) == [title]


def test_what_is_spoken_is_what_was_made_ready_for_the_voice_not_the_raw_title():
    # the announcement is the title as the voice should say it ("Part III" -> "Part Three"), never the page's own text
    assert announcement(chapter("Part III, The Return", announce="Part Three, The Return")) == ["Part Three.", "The Return"]


class Counting(ChunkRenderer):
    """A voice that makes one second of 1.0 per word, remembering what it was asked."""

    def __init__(self):
        self.said: list[str] = []

    def __call__(self, text: str) -> np.ndarray:
        self.said.append(text)
        return np.ones(len(text.split()) * RATE, dtype=np.float32)


def rendered(ch: Chapter):
    voice = Counting()
    audio, timing = render_chapter(ch, voice, RATE, _Tracker())
    return voice, audio, timing


class _Tracker:
    def chunk_done(self, text, seconds):
        pass


def runs(audio: np.ndarray) -> list[tuple[str, float]]:
    """The sound and silence in order, each with its length in seconds."""
    out: list[tuple[str, float]] = []
    for sample in audio:
        kind = "sound" if sample else "silence"
        if out and out[-1][0] == kind:
            out[-1] = (kind, out[-1][1] + 1 / RATE)
        else:
            out.append((kind, 1 / RATE))
    return [(kind, round(length, 2)) for kind, length in out]  # the last sample of a pause can be lost to rounding


def test_a_pause_sits_between_the_label_and_the_title_and_a_longer_one_after_the_title():
    voice, audio, _ = rendered(chapter("Chapter 6 Knowing the Source", body="Go on now."))
    assert voice.said[:3] == ["Chapter 6.", "Knowing the Source", "Go on now."]
    assert runs(audio) == [
        ("sound", 2.0),                      # Chapter 6.
        ("silence", LABEL_PAUSE),            # the breath that was missing
        ("sound", 3.0),                      # Knowing the Source
        ("silence", TITLE_PAUSE),
        ("sound", 3.0),                      # Go on now.
        ("silence", PARAGRAPH_PAUSE),
    ]


def test_a_chapter_with_no_label_has_only_the_pause_after_its_title():
    _, audio, _ = rendered(chapter("Foreword", body="Go on now."))
    assert runs(audio) == [("sound", 1.0), ("silence", TITLE_PAUSE), ("sound", 3.0), ("silence", PARAGRAPH_PAUSE)]


def test_the_pause_between_label_and_title_is_audible_but_shorter_than_the_one_after_the_title():
    assert SENTENCE_PAUSE < LABEL_PAUSE < TITLE_PAUSE


def test_timing_records_every_segment_and_chunk_with_correct_offsets():
    ch = chapter("Chapter 6 Knowing the Source", body="Go on now. And again.")
    _, audio, timing = rendered(ch)
    # Two announcement entries (label + title), then one paragraph segment
    assert len(timing) == 3
    assert timing[0]["kind"] == "announcement"
    assert timing[0]["text"] == "Chapter 6."
    assert timing[1]["kind"] == "announcement"
    assert timing[1]["text"] == "Knowing the Source"
    assert timing[2]["kind"] == "paragraph"
    assert timing[2]["text"] == "Go on now. And again."
    # The paragraph has one chunk (both sentences fit in MAX_CHUNK_CHARS)
    assert len(timing[2]["chunks"]) == 1
    assert timing[2]["chunks"][0]["text"] == "Go on now. And again."
    # Timing is contiguous: each segment starts after the previous ends (with silence gaps)
    for i in range(1, len(timing)):
        assert timing[i]["start"] > timing[i - 1]["end"]
    # Segment start/end bracket its chunks
    seg = timing[2]
    assert seg["start"] == seg["chunks"][0]["start"]
    assert seg["end"] == seg["chunks"][-1]["end"]
    # Total audio length equals the last silence's end plus the trailing pause
    total_seconds = len(audio) / RATE
    assert timing[-1]["end"] < total_seconds  # chunk end is before the trailing silence


def test_timing_with_multiple_chunks():
    long_body = "A short one. " + "This is a much longer sentence that keeps going and going. " * 8
    ch = chapter("Opening", body=long_body)
    _, _, timing = rendered(ch)
    # "Opening" is one announcement, then one paragraph with multiple chunks
    assert timing[0]["kind"] == "announcement"
    seg = timing[1]
    assert seg["kind"] == "paragraph"
    assert len(seg["chunks"]) > 1
    # Chunks are in order and non-overlapping
    for i in range(1, len(seg["chunks"])):
        assert seg["chunks"][i]["start"] > seg["chunks"][i - 1]["end"]


def test_compact_timing_carries_each_chunks_word_count_and_no_text():
    long_body = "A short one. " + "This is a much longer sentence that keeps going and going. " * 8
    _, _, timing = rendered(chapter("Opening", body=long_body))
    compact = compact_timing(timing)
    paragraph = compact[1]
    assert all("text" not in c for seg in compact for c in seg["chunks"])
    assert len(paragraph["chunks"]) > 1
    # the chunks' words, in order, are the paragraph's words: the page shares the paragraph's own words out by these
    assert sum(c["words"] for c in paragraph["chunks"]) == len(long_body.split())
    assert [c["words"] for c in paragraph["chunks"]] == [len(c["text"].split()) for c in timing[1]["chunks"]]


def test_timing_carries_each_chunks_sentences_with_their_word_counts_and_starts():
    _, _, timing = rendered(chapter("Opening", body="One two three. Four five six seven."))
    chunk = timing[1]["chunks"][0]
    sentences = chunk["sentences"]
    assert [s["words"] for s in sentences] == [3, 4]
    assert sentences[0]["start"] == chunk["start"]                       # the first sentence starts with its chunk
    assert chunk["start"] < sentences[1]["start"] < chunk["end"]


def test_sentence_starts_are_in_playback_seconds_and_the_compact_form_keeps_them_without_the_text():
    _, _, timing = rendered(chapter("Opening", body="One two three. Four five six seven."))
    raw = timing[1]["chunks"][0]["sentences"][1]["start"]
    slow = _timing_for_speed(timing, 0.5)                                # atempo 0.5 doubles every time
    assert slow[1]["chunks"][0]["sentences"][1]["start"] == pytest.approx(raw * 2, abs=0.001)
    compact = compact_timing(slow)[1]["chunks"][0]
    assert "text" not in compact and [s["words"] for s in compact["sentences"]] == [3, 4]
    assert compact["sentences"][1]["start"] == slow[1]["chunks"][0]["sentences"][1]["start"]


def test_progress_counts_exactly_what_the_voice_is_asked_for():
    ch = chapter("Chapter 6 Knowing the Source", body="One. Two.")
    voice, _, _ = rendered(ch)
    assert chapter_texts(ch) == voice.said
