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
    announcement,
    chapter_texts,
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
    return voice, render_chapter(ch, voice, RATE, _Tracker())


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
    voice, audio = rendered(chapter("Chapter 6 Knowing the Source", body="Go on now."))
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
    _, audio = rendered(chapter("Foreword", body="Go on now."))
    assert runs(audio) == [("sound", 1.0), ("silence", TITLE_PAUSE), ("sound", 3.0), ("silence", PARAGRAPH_PAUSE)]


def test_the_pause_between_label_and_title_is_audible_but_shorter_than_the_one_after_the_title():
    assert SENTENCE_PAUSE < LABEL_PAUSE < TITLE_PAUSE


def test_progress_counts_exactly_what_the_voice_is_asked_for():
    ch = chapter("Chapter 6 Knowing the Source", body="One. Two.")
    voice, _ = rendered(ch)
    assert chapter_texts(ch) == voice.said
