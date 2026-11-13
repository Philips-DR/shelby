"""Splitting a paragraph into sentences and chunks for the voice.

A closing quote or bracket after a full stop belongs to the sentence it closes. The split used to use it up, so the
voice was given `He said "Stop.` with the quote opened and never closed (843 of 6,232 real paragraphs lost one)."""

import pytest

from audiobook.chunk import MAX_CHUNK_CHARS, chunk_paragraph, split_sentences


def test_plain_sentences_split_as_they_always_did():
    assert split_sentences("One went. Two stayed! Did three? Yes. 4 more came.") == [
        "One went.", "Two stayed!", "Did three?", "Yes.", "4 more came."]


@pytest.mark.parametrize("paragraph,expected", [
    ('He said "Stop." Then he left.', ['He said "Stop."', "Then he left."]),
    ("“Stop!” Then he left.", ["“Stop!”", "Then he left."]),
    ("It was over (at last.) Then came rest.", ["It was over (at last.)", "Then came rest."]),
    ("See the list [done.] Next it began.", ["See the list [done.]", "Next it began."]),
    ('She asked, "Why?" "Because." Then silence.', ['She asked, "Why?"', '"Because."', "Then silence."]),
    ("It ended…” Then it began.", ["It ended…”", "Then it began."]),
    ("He said 'Go.' Then left.", ["He said 'Go.'", "Then left."]),
])
def test_a_closing_quote_or_bracket_stays_with_its_sentence(paragraph, expected):
    assert split_sentences(paragraph) == expected


@pytest.mark.parametrize("paragraph", [
    'He said "Stop." Then he left. "Why?" she asked. "Because." It ended.',
    "Mr. Smith asked (Dr. Jones agreed.) Then they left.",
    "One. Two. Three. Four. Five.",
    'A "quoted." B "quoted." C "quoted."',
    "No closers here at all. Just plain text follows. It goes on.",
])
def test_no_word_or_mark_is_lost(paragraph):
    assert " ".join(split_sentences(paragraph)) == paragraph


def test_an_abbreviation_does_not_end_a_sentence_even_with_a_closer_after_it():
    assert split_sentences("Mr. Smith left. Dr. Jones came.") == ["Mr. Smith left.", "Dr. Jones came."]
    assert split_sentences("They asked (see Dr.) Smith about it. Then left.") == ["They asked (see Dr.) Smith about it.", "Then left."]


def test_chunks_keep_every_word_and_mark_and_stay_within_the_limit():
    paragraph = " ".join(f'Sentence number {i} says "go on." Then it rests.' for i in range(40))
    chunks = chunk_paragraph(paragraph)
    assert " ".join(chunks) == paragraph
    assert len(chunks) > 1 and all(len(c) <= MAX_CHUNK_CHARS for c in chunks)
    assert all(c.count('"') % 2 == 0 for c in chunks)                       # no chunk opens a quote and leaves it open


def test_a_chunk_never_splits_a_sentence():
    paragraph = 'He said "Stop." ' * 30
    for chunk in chunk_paragraph(paragraph):
        assert chunk.startswith("He said") and chunk.endswith('"Stop."')


def test_empty_and_whitespace_make_no_sentences():
    assert split_sentences("") == [] and split_sentences("   ") == []
    assert chunk_paragraph("") == []
