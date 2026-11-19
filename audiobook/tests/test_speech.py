import pytest

from audiobook.speech import (
    apply_corrections,
    for_speech,
    int_to_words,
    ordinal_to_words,
    parse_corrections,
    roman_to_int,
    year_to_words,
)


# --- int_to_words ---


@pytest.mark.parametrize("n, expected", [
    (0, "zero"), (1, "one"), (5, "five"), (10, "ten"), (13, "thirteen"),
    (19, "nineteen"), (20, "twenty"), (21, "twenty-one"), (42, "forty-two"),
    (99, "ninety-nine"), (100, "one hundred"), (101, "one hundred one"),
    (119, "one hundred nineteen"), (200, "two hundred"), (550, "five hundred fifty"),
    (999, "nine hundred ninety-nine"), (1000, "one thousand"),
    (1001, "one thousand one"), (5000, "five thousand"),
    (10000, "ten thousand"), (100000, "one hundred thousand"),
    (999999, "nine hundred ninety-nine thousand nine hundred ninety-nine"),
    (1000000, "one million"), (1000001, "one million one"),
])
def test_int_to_words(n, expected):
    assert int_to_words(n) == expected


# --- year_to_words ---


@pytest.mark.parametrize("n, expected", [
    (1100, "eleven hundred"), (1805, "eighteen oh five"),
    (1900, "nineteen hundred"), (1954, "nineteen fifty-four"),
    (1972, "nineteen seventy-two"), (1995, "nineteen ninety-five"),
    (2000, "two thousand"), (2001, "two thousand one"), (2009, "two thousand nine"),
    (2010, "twenty ten"), (2024, "twenty twenty-four"), (2026, "twenty twenty-six"),
])
def test_year_to_words(n, expected):
    assert year_to_words(n) == expected


# --- ordinal_to_words ---


@pytest.mark.parametrize("n, expected", [
    (0, "zeroth"), (1, "first"), (2, "second"), (3, "third"), (4, "fourth"),
    (5, "fifth"), (8, "eighth"), (9, "ninth"), (12, "twelfth"),
    (13, "thirteenth"), (14, "fourteenth"), (20, "twentieth"),
    (21, "twenty-first"), (22, "twenty-second"), (30, "thirtieth"),
    (100, "one hundredth"), (101, "one hundred first"), (1000, "one thousandth"),
])
def test_ordinal_to_words(n, expected):
    assert ordinal_to_words(n) == expected


# --- for_speech: original rules (verified by synthesis + Whisper, see speech.py) ---


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Part III, The Return of The Eagles", "Part Three, The Return of The Eagles"),
        ("Parts II & III were published", "Parts Two and Three were published"),
        ("Chapter XIV begins", "Chapter Fourteen begins"),
        ("as Paul prayed in Ephesians 1:18, the more",
         "as Paul prayed in Ephesians chapter one, verse eighteen, the more"),
        ("read 1 John 3:16-18 aloud",
         "read First John chapter three, verses sixteen to eighteen aloud"),
        ("at 3:30 we left", "at three thirty we left"),
        ('I read "THE JUDGMENT SEAT OF CHRIST."', 'I read "The Judgment Seat of Christ."'),
        ("turned into a . . . and I stopped", "turned into a... and I stopped"),
        ("the world . . . to give sight", "the world... to give sight"),
        ("call first_hop_retrieve then LEADS_TO", "call first hop retrieve then Leads to"),
        ("I said I would, and the USA and NASA agreed.",
         "I said I would, and the USA and NASA agreed."),
    ],
)
def test_for_speech(text, expected):
    assert for_speech(text) == expected


# --- for_speech: numbers to words ---


@pytest.mark.parametrize(
    "text, expected",
    [
        # Years
        ("In early 1995, the Lord gave me a dream.",
         "In early nineteen ninety-five, the Lord gave me a dream."),
        ("after I became a Christian in 1972",
         "after I became a Christian in nineteen seventy-two"),
        ("Copyright 2026 John Bevere", "Copyright twenty twenty-six John Bevere"),
        # Plain integers
        ("the 5 Ps", "the five Ps"),
        ("in chapter 1", "in chapter one"),
        ("chapters 23 and 28", "chapters twenty-three and twenty-eight"),
        ("an eight-dimension comparison of 24 methods",
         "an eight-dimension comparison of twenty-four methods"),
        ("Figure 1", "Figure one"),
        ("Section 3.2", "Section three point two"),
        # Ordinals
        ("Thursday the 14th", "Thursday the fourteenth"),
        ("the 1st day", "the first day"),
        ("the 21st century", "the twenty-first century"),
        # Comma numbers
        ("1,000 people gathered", "one thousand people gathered"),
        # Bible refs: digits in the expansion are also converted
        ("Psalm 119:15 nkjv", "Psalm one hundred nineteen, verse fifteen, New King James Version"),
        # Decimals read as "N point digit digit..."
        ("accuracy of 78.78 points", "accuracy of seventy-eight point seven eight points"),
        ("scored 67.00%", "scored sixty-seven point zero zero%"),
        ("Claude Sonnet 4.6", "Claude Sonnet four point six"),
        ("Section 5.3 compares", "Section five point three compares"),
        # Letter-dot-digit section numbering: digit is still converted
        ("Appendix B.1", "Appendix B.one"),
        # Decimal with no trailing word boundary stays as-is
        ("$39.62M", "$39.62M"),
        # Long digit sequences (> 6 digits) are left alone
        ("ISBN 9781400349685", "ISBN 9781400349685"),
    ],
)
def test_for_speech_numbers(text, expected):
    assert for_speech(text) == expected


def test_roman():
    assert [roman_to_int(r) for r in ("I", "IV", "IX", "XIV", "XL")] == [1, 4, 9, 14, 40]


def test_corrections():
    pairs = parse_corrections("# comment\n\nwit1~ My heart => with My heart\nbad line\n")
    assert pairs == [("wit1~ My heart", "with My heart")]
    assert apply_corrections("understand wit1~ My heart.", pairs) == "understand with My heart."
