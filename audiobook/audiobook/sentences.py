"""Where each sentence of a chunk starts, so the page can light a sentence, not a paragraph.

The voice is asked for a whole chunk (up to 400 characters, a few sentences) and gives back only audio, so a sentence's
start is worked out here, in two steps: guessed from the text (every word's share of the chunk is its letters, with a
rest after a comma and a longer one after a full stop, spread over the chunk's own length), then moved to the longest
pause in the audio within a second of the guess. A guess that finds no pause near it stays a guess.

Measured against Whisper's word times (2026-11-13, abigail, 175 real sentence starts in two books): the guess alone was
within a quarter second 39% of the time and within half a second 68%; moved to a pause, 75% and 85%. Whisper is a
yardstick, not the truth: where it disagreed most, its start often fell inside a silence the audio plainly showed. A
sentence start can still be a few tenths of a second out, and now and then more than a second.

Every time here is seconds from the start of the chunk's own audio."""

import re

import numpy as np

from .chunk import split_sentences

_END = re.compile(r"[.!?…][\"'”’)\]]*$")
_CLAUSE = re.compile(r"[,;:—–][\"'”’)\]]*$")

HOP = 0.010          # the energy is read every 10 ms, over 25 ms
WINDOW = 0.025
QUIET = 0.10         # quiet is under a tenth of the chunk's loud level
MIN_PAUSE = 0.12     # a quiet stretch shorter than this is a breath, not a pause
REACH = 1.0          # how far from the guess a pause may be to be taken
APART = 0.3          # sentences start at least this far apart
LONGER = 0.3         # a pause beats a nearer one by this much of its own extra length per second of distance


def sentence_words(chunk: str) -> list[int]:
    """Words in each sentence, in order; the chunk as one sentence when its sentences do not add up to its words."""
    total = len(chunk.split())
    counts = [len(s.split()) for s in split_sentences(chunk)]
    return counts if counts and sum(counts) == total else [total]


def _weight(word: str) -> int:
    letters = len(re.sub(r"[\W_]", "", word))
    return 2 + letters + (6 if _END.search(word) else 3 if _CLAUSE.search(word) else 0)


def guess_starts(chunk: str, counts: list[int], length: float) -> list[float]:
    """The start of every sentence after the first, worked out from the text alone."""
    weights = [_weight(w) for w in chunk.split()]
    if not weights or length <= 0:
        return [0.0] * (len(counts) - 1)
    scale = length / sum(weights)
    starts, at, word = [], 0.0, 0
    for n in counts[:-1]:
        at += sum(weights[word:word + n]) * scale
        word += n
        starts.append(at)
    return starts


def pauses(audio: np.ndarray, rate: int) -> list[tuple[float, float]]:
    """(start, end) of every quiet stretch of at least MIN_PAUSE: where the voice stops and where it starts again."""
    hop, window = max(1, int(HOP * rate)), max(1, int(WINDOW * rate))
    if len(audio) < window + hop:
        return []
    squares = np.concatenate(([0.0], np.cumsum(np.square(audio.astype(np.float64)))))
    at = np.arange(0, len(audio) - window + 1, hop)
    level = np.sqrt((squares[at + window] - squares[at]) / window)
    loud = np.percentile(level, 90)
    if loud <= 0:
        return []
    quiet = np.concatenate(([False], level < QUIET * loud, [False]))
    edges = np.flatnonzero(np.diff(quiet.astype(np.int8)))
    runs = []
    for first, after in zip(edges[::2], edges[1::2]):
        if (after - first) * HOP >= MIN_PAUSE:
            runs.append((float(first * HOP), float(after * HOP)))
    return runs


def _snap(guesses: list[float], runs: list[tuple[float, float]], length: float) -> list[float]:
    out: list[float] = []
    previous = 0.0
    for guess in guesses:
        near = [r for r in runs if abs(r[1] - guess) <= REACH and r[1] > previous + APART]
        if near:
            guess = max(near, key=lambda r: (r[1] - r[0]) - LONGER * abs(r[1] - guess))[1]
        guess = min(max(guess, previous + HOP), length)
        out.append(guess)
        previous = guess
    return out


def sentence_starts(chunk: str, audio: np.ndarray, rate: int) -> list[dict]:
    """[{"words": n, "start": seconds}, ...], one per sentence, the first starting at 0."""
    counts = sentence_words(chunk)
    length = len(audio) / rate if rate else 0.0
    starts = [0.0]
    if len(counts) > 1:
        starts += _snap(guess_starts(chunk, counts, length), pauses(audio, rate), length)
    return [{"words": n, "start": round(s, 3)} for n, s in zip(counts, starts)]
