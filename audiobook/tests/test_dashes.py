"""Putting back the dashes the PDF reader turned into hyphens.

The PDF's text has the real characters; Docling's has "-" for every em and en dash, and closed up the gap where one fell
at the end of a line. The cases are the real ones from Beth Moore's book, Great Expectations and the others."""

from audiobook.dashes import Dashes, read, restore

# page text the way pdfium gives it: lines end in \r\n
PAGE = ("You have been an unspeakable inspiration—\r\nespecially at times when I've grieved, and I will overcome—particularly "
        "when pressed. It was a well-known fact that the algo-\r\nrithms ran. In 1843–\r\n4 it ended and he said\r\n—later that it was done.")


def test_what_the_pdf_has_between_words():
    d = read(PAGE)
    assert d.inline == {("overcome", "particularly")}
    assert d.split == {"inspirationespecially": ("inspiration", "—", "especially"), "18434": ("1843", "-", "4")}
    assert d.lead == {("said", "later"): "—"}
    assert ("well", "known") in d.hyphens and ("algo", "rithms") in d.hyphens


def test_a_dash_inside_a_line_comes_back_as_an_em_dash():
    assert restore("I will overcome-particularly when pressed.", read(PAGE)) == "I will overcome—particularly when pressed."


def test_a_dash_at_the_end_of_a_line_is_reopened_and_the_words_are_apart_again():
    text = "an unspeakable inspirationespecially at times"
    assert restore(text, read(PAGE)) == "an unspeakable inspiration—especially at times"


def test_an_en_dash_gets_its_gap_back_as_a_hyphen_so_a_number_range_reads_as_it_always_did():
    assert restore("In 18434 it ended", read(PAGE)) == "In 1843-4 it ended"


def test_a_dash_that_starts_a_line_loses_the_space_before_it():
    assert restore("he said -later that it was done", read(PAGE)) == "he said—later that it was done"


def test_a_real_hyphen_is_never_touched():
    d = read(PAGE)
    assert restore("It was a well-known fact that the algo-rithms ran.", d) == "It was a well-known fact that the algo-rithms ran."
    assert restore("self-control and overcome-particularly", d) == "self-control and overcome—particularly"


def test_a_pair_the_pdf_joins_both_ways_is_left_alone():
    d = read("It was well—known to some, a well-known fact to others.")
    assert restore("It was well-known to some", d) == "It was well-known to some"


def test_a_word_that_only_looks_like_a_closed_up_pair_is_not_split():
    d = read(PAGE)
    assert restore("an inspirationespecially and xinspirationespeciallyx", d) == "an inspiration—especially and xinspirationespeciallyx"


def test_a_dash_in_a_chain_gives_both_pairs():
    d = read("Purity—boundless—power came.")
    assert d.inline == {("Purity", "boundless"), ("boundless", "power")}
    assert restore("Purity-boundless-power came.", d) == "Purity—boundless—power came."


def test_two_readings_that_disagree_change_nothing():
    d = read("one a—\r\nb and a–\r\nb")          # "ab" reopened as an em dash once, as a hyphen once
    assert "ab" not in d.split
    assert restore("see ab here", d) == "see ab here"


def test_text_with_no_dash_is_returned_as_it_came():
    d = read(PAGE)
    plain = "Nothing here but plain words, and a well-known hyphen: 12-15."
    assert restore(plain, d) == plain
    assert restore(plain, Dashes()) == plain


def test_pages_merge_and_survive_the_cache():
    a, b = read("one—two. "), read("three—\r\nfour")
    both = a.merge(b)
    assert both.inline == {("one", "two")} and "threefour" in both.split
    again = Dashes.from_json(both.to_json())
    assert again.inline == both.inline and again.split == both.split and again.lead == both.lead and again.hyphens == both.hyphens
    assert restore("one-two and threefour", again) == "one—two and three—four"


def test_an_en_dash_inside_a_line_is_left_as_the_hyphen_it_already_is():
    d = read("See pages 12–15 and Monday–Friday of that week—really.")
    assert d.inline == {("week", "really")}                      # only the em dash is put back; the en dashes are not recorded
    assert restore("See pages 12-15 and Monday-Friday of that week-really.", d) == "See pages 12-15 and Monday-Friday of that week—really."
