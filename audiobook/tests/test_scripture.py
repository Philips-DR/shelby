"""Bible references (scripture.py), through `for_speech` so the digits are words as they will be spoken.

Each "read as" below is a form found in the user's real books; Whisper heard what the voice made of them before this
module existed (see its docstring)."""

import pytest

from audiobook.scripture import references
from audiobook.speech import for_speech


@pytest.mark.parametrize(
    "text, expected",
    [
        # A numbered book keeps its number, spoken as First, Second, Third.
        ("1 John 2:23", "First John chapter two, verse twenty-three"),
        ("1 John 4:8, 16", "First John chapter four, verses eight and sixteen"),
        ("2 Samuel 24:14b", "Second Samuel chapter twenty-four, verse fourteen b"),
        ("First Corinthians 15:38", "First Corinthians chapter fifteen, verse thirty-eight"),
        ("II Peter 1:3", "Second Peter chapter one, verse three"),
        ("1st John 1:9", "First John chapter one, verse nine"),
        # Short forms, with and without the full stop.
        ("Gen. 1:31", "Genesis chapter one, verse thirty-one"),
        ("Exod. 19:10", "Exodus chapter nineteen, verse ten"),
        ("Heb. 10:24-25", "Hebrews chapter ten, verses twenty-four to twenty-five"),
        ("2 Chron. 3:1", "Second Chronicles chapter three, verse one"),
        ("1 Cor. 3:16", "First Corinthians chapter three, verse sixteen"),
        ("Pr 5:19, 20", "Proverbs chapter five, verses nineteen and twenty"),
        ("Matt. 24:48", "Matthew chapter twenty-four, verse forty-eight"),
        ("Song of Solomon 2:1", "Song of Solomon chapter two, verse one"),
        ("HEBREWS 5:14", "Hebrews chapter five, verse fourteen"),
        # Psalms are "Psalm 23", not a chapter of one.
        ("Ps. 23:4", "Psalm twenty-three, verse four"),
        ("Psalms 119:105", "Psalm one hundred nineteen, verse one hundred five"),
        # Half-verses are said with their letter.
        ("Rom. 6:23a", "Romans chapter six, verse twenty-three a"),
        ("Rev. 19:16b", "Revelation chapter nineteen, verse sixteen b"),
        ("2 Samuel 12:13b-14", "Second Samuel chapter twelve, verses thirteen b to fourteen"),
        ("Genesis 4:3-4a", "Genesis chapter four, verses three to four a"),
        # Ranges, lists and chains.
        ("Isaiah 55:10-11", "Isaiah chapter fifty-five, verses ten to eleven"),
        ("Exodus 25:1-3,8", "Exodus chapter twenty-five, verses one to three and eight"),
        ("1 Corinthians 7:17, 28, 36", "First Corinthians chapter seven, verses seventeen, twenty-eight and thirty-six"),
        ("Revelation 21:1-2, 22-23", "Revelation chapter twenty-one, verses one to two and twenty-two to twenty-three"),
        ("Gen. 1:1-8; 14-18", "Genesis chapter one, verses one to eight and fourteen to eighteen"),
        ("1 Chronicles 16:1-2,4;7-12;23-29;34-36",
         "First Chronicles chapter sixteen, verses one to two, four, seven to twelve, twenty-three to twenty-nine "
         "and thirty-four to thirty-six"),
        ("Gen. 1:1; 2", "Genesis chapter one, verse one; two"),  # a lone number after a semicolon is not taken for a verse
        ("Genesis 8:21-9:1", "Genesis chapter eight, verse twenty-one, to chapter nine, verse one"),
        ("Ps. 31:5; 45:4", "Psalm thirty-one, verse five; and Psalm forty-five, verse four"),
        ("See John 13:34-35; 17:21-23.",
         "See John chapter thirteen, verses thirty-four to thirty-five; and John chapter seventeen, "
         "verses twenty-one to twenty-three."),
        ("(see Ps. 42:4, 50:23, and 56:12 KJV)",
         "(see Psalm forty-two, verse four; Psalm fifty, verse twenty-three; and Psalm fifty-six, verse twelve, "
         "King James Version)"),
        # The version a book names, said in full (read as letters, KJV came out "K J D").
        ("(Rom. 3:23 NKJV)", "(Romans chapter three, verse twenty-three, New King James Version)"),
        ("John 3:16 NIV", "John chapter three, verse sixteen, New International Version"),
        ("Romans 6:6 (NIV)", "Romans chapter six, verse six (New International Version)"),
        ("Ps. 4:4 AMP)", "Psalm four, verse four, Amplified Bible)"),
        ("(2 Corinthians 10:4,5, KJV, emphasis added)",
         "(Second Corinthians chapter ten, verses four and five, King James Version, emphasis added)"),
        ('the splendor ["glory" NKJV] of', 'the splendor "glory" New King James Version of'),  # the brackets go, as before
        ("as the NIV puts it", "as the New International Version puts it"),
        # A chapter with no verse, after an abbreviation: the whole name ("Gen." was heard as "Cgen").
        ("(see Gen. 22). This story", "(see Genesis twenty-two). This story"),
        ("(see Ps. 150) and", "(see Psalm one hundred fifty) and"),
        ("(see 2 Chron. 20.) Every", "(see Second Chronicles twenty.) Every"),
        ("Abel Gen. 4", "Abel Genesis four"),
        ("(see Exod. 29-30;39-40; Lev. 8)",
         "(see Exodus chapters twenty-nine to thirty and thirty-nine to forty; Leviticus eight)"),
        ("(see 1 Sam. 13, 15, and 16)", "(see First Samuel chapters thirteen, fifteen and sixteen)"),
        ("Exod. 15; 1 Sam. 18:6; 2 Sam. 22).",
         "Exodus fifteen; First Samuel chapter eighteen, verse six; Second Samuel twenty-two)."),
        ("Gen. 22:3 is a verse", "Genesis chapter twenty-two, verse three is a verse"),
        ("see Genesis 22)", "see Genesis twenty-two)"),  # written out in full: the number rules already read it well
        # "vs." after a bracket, a dash lost after a letter, a stray hyphen after the colon.
        ("(vs. 38b). Jesus", "(verse thirty-eight b). Jesus"),
        ("(vss. 3-5)", "(verses three to five)"),
        ("(Mark 7:14b23).", "(Mark chapter seven, verses fourteen b to twenty-three)."),
        ("(Ps. 91:-16).", "(Psalm ninety-one, verse sixteen)."),
        # A number after a verse that is not a verse stays a number.
        ("Romans 1:24, 26 people came", "Romans chapter one, verse twenty-four, twenty-six people came"),
        # The PDF lost the dash of a range ("9:10-12"): no verse has four digits, so two ascending verses are a range.
        ("(Acts 9:1012).", "(Acts chapter nine, verses ten to twelve)."),
        ("In Genesis 1:2627, we read", "In Genesis chapter one, verses twenty-six to twenty-seven, we read"),
        ("1 Corinthians 6:1320 (NIV) to", "First Corinthians chapter six, verses thirteen to twenty (New International Version) to"),
        ("(Eph. 6:1013 AMP)", "(Ephesians chapter six, verses ten to thirteen, Amplified Bible)"),
        # A list written tight is verses whatever follows it; so is a book's own "verses 29-32".
        ("Hebrews 11:19,20 we read", "Hebrews chapter eleven, verses nineteen and twenty we read"),
        ("(See verses 29-32.)", "(See verses twenty-nine to thirty-two.)"),
        ("in verse 17,18 he says", "in verses seventeen and eighteen he says"),
        ("verses 4-5,8", "verses four to five and eight"),
        # A version in brackets after a quotation, and a letter named by its book.
        ('"... into sin" (AMP). Not only', '"... into sin" (Amplified Bible). Not only'),
        ("(TPT) and (NIV)", "(The Passion Translation) and (New International Version)"),
        ("the entire Book of 1 John is written", "the entire Book of First John is written"),
        ("in the epistle of 2 John", "in the epistle of Second John"),
        ("I have 1 John to read", "I have one John to read"),  # a count of Johns is left as a count
        ("an amp (and a net)", "an amp (and a net)"),
        # After a quotation.
        ('(v. 39)', '(verse thirty-nine)'),
        ('(vv. 37-38)', '(verses thirty-seven to thirty-eight)'),
        ("in 1 Corinthians and 2 Timothy", "in First Corinthians and Second Timothy"),
    ],
)
def test_references_are_said_whole(text, expected):
    assert for_speech(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "And I John saw the holy city",  # the pronoun, not First John
        "Is 3:30 too late?",  # not Isaiah
        "Am 3:30 early enough?",  # not Amos
        "at 3:30 we left",  # a time
        "I Peter said so",  # the pronoun
        "Psalm 150:177",  # no such verse: left for the fallback, not made up
    ],
)
def test_what_is_not_a_reference_is_left_alone(text):
    assert references(text) == text


def test_four_digits_that_are_not_a_lost_range_are_left_alone():
    # Descending, or not four digits: not two ascending verses, so nothing is invented.
    assert references("Acts 9:2010") == "Acts 9:2010"
    assert references("Acts 9:10123") == "Acts 9:10123"
    assert references("Acts 9:1010") == "Acts 9:1010"


def test_the_scripture_a_book_does_not_name_still_reads_as_before():
    """A capitalised word the table does not know, before chapter:verse, keeps the older rule."""
    assert for_speech("as Paul prayed in Ephesians 1:18, the more") == (
        "as Paul prayed in Ephesians chapter one, verse eighteen, the more"
    )
    assert for_speech("Selah 4:9") == "Selah chapter four, verse nine"


def test_a_reference_is_one_sentence_for_the_chunker():
    """"Ps. 31:5" used to be cut at "Ps." because a digit followed; said whole, there is no stop to cut at."""
    from audiobook.chunk import split_sentences

    spoken = for_speech("He is righteous (see Ps. 31:5; 45:4). This is why David sang.")
    assert len(split_sentences(spoken)) == 2


def test_tags_that_are_words_are_not_versions_elsewhere():
    assert for_speech("a speaker and an amp on the net") == "a speaker and an amp on the net"
