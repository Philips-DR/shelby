"""Where a chunk's sentences start: guessed from the text, then moved to the pause in the audio that is nearby.

The audio here is made: noise where the voice speaks and true silence where it pauses, so what is checked is what this
code decides (which pause, and what to do when there is none), not how a real voice sounds."""

import numpy as np
import pytest

from audiobook.sentences import guess_starts, pauses, sentence_starts, sentence_words

RATE = 1000
RNG = np.random.default_rng(0)


def voice(*parts: float) -> np.ndarray:
    """Seconds of speech and silence in turn, starting with speech: speak 1.5, pause 0.5, speak 1.5 ..."""
    out = []
    for i, seconds in enumerate(parts):
        n = int(seconds * RATE)
        out.append(RNG.uniform(-0.5, 0.5, n) if i % 2 == 0 else np.zeros(n))
    return np.concatenate(out).astype(np.float32)


def test_words_in_each_sentence():
    assert sentence_words("One two three. Four five six seven. Eight.") == [3, 4, 1]


def test_a_chunk_whose_sentences_do_not_add_up_to_its_words_is_one_sentence(monkeypatch):
    monkeypatch.setattr("audiobook.sentences.split_sentences", lambda chunk: ["One two.", "Three."])   # lost a word
    assert sentence_words("One two. Three four.") == [4]


def test_the_guess_puts_a_later_sentence_later_in_proportion_to_its_text():
    short_first = guess_starts("Go. Then a much longer second sentence follows here.", [1, 8], 10.0)[0]
    long_first = guess_starts("A much longer first sentence goes here. Go.", [7, 1], 10.0)[0]
    assert short_first < 3.0 < 7.0 < long_first


def test_a_pause_is_where_the_voice_stops_and_where_it_starts_again():
    found = pauses(voice(1.5, 0.5, 1.5), RATE)
    assert len(found) == 1
    start, end = found[0]
    assert start == pytest.approx(1.5, abs=0.05) and end == pytest.approx(2.0, abs=0.05)


def test_a_breath_shorter_than_a_pause_is_not_one():
    assert pauses(voice(1.5, 0.08, 1.5), RATE) == []


def test_a_sentence_starts_where_the_voice_starts_again_not_where_the_text_guessed():
    text = "Aa bb cc dd ee ff. Gg hh ii jj kk ll. Mm nn oo pp qq rr."      # three sentences of equal weight
    audio = voice(1.5, 0.5, 2.0, 0.5, 1.0)          # 5.5 s: the voice starts again at 2.0 and 4.5; the text alone says 1.83 and 3.67
    assert guess_starts(text, [6, 6, 6], 5.5) == pytest.approx([5.5 / 3, 5.5 * 2 / 3])
    first, second, third = sentence_starts(text, audio, RATE)
    assert first == {"words": 6, "start": 0.0}
    assert second["start"] == pytest.approx(2.0, abs=0.05)
    assert third["start"] == pytest.approx(4.5, abs=0.05)
    assert [s["words"] for s in (first, second, third)] == [6, 6, 6]


def test_with_no_pause_near_the_guess_it_stays_a_guess():
    text = "One two three four. Five six seven eight."
    audio = voice(4.0)                                # steady sound, no pause anywhere
    second = sentence_starts(text, audio, RATE)[1]
    assert second["start"] == pytest.approx(guess_starts(text, [4, 4], 4.0)[0], abs=0.01)


def test_a_pause_further_than_a_second_from_the_guess_is_not_taken():
    text = "One two three four five six seven eight nine. Ten."
    audio = voice(8.0, 0.5, 1.0)                      # a pause at 8.0-8.5; the guess is near 7.5... and the next one is ~1 s away
    start = sentence_starts(text, audio, RATE)[1]["start"]
    assert start == pytest.approx(8.5, abs=0.05)      # within a second of the guess, so taken
    far = voice(2.0, 0.5, 8.0)                        # the only pause is at 2.0-2.5, the guess near 9
    assert sentence_starts(text, far, RATE)[1]["start"] > 5.0


def test_the_starts_never_run_backwards_or_past_the_end():
    text = "A b. C d. E f. G h."
    for audio in (voice(0.3, 0.2, 0.3, 0.2, 0.3, 0.2, 0.3), voice(2.0), np.zeros(2000, dtype=np.float32)):
        starts = [s["start"] for s in sentence_starts(text, audio, RATE)]
        assert starts == sorted(starts) and starts[-1] <= len(audio) / RATE


def test_silence_and_empty_and_tiny_audio_do_not_fail():
    for audio in (np.zeros(5000, dtype=np.float32), np.zeros(0, dtype=np.float32), np.ones(10, dtype=np.float32)):
        out = sentence_starts("One two. Three four.", audio, RATE)
        assert [s["words"] for s in out] == [2, 2]


def test_one_sentence_is_one_entry_starting_at_zero():
    assert sentence_starts("Just this one sentence.", voice(2.0), RATE) == [{"words": 4, "start": 0.0}]
