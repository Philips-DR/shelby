"""How a book's chapters and title are found when it is not laid out like a paper.

Shaped on a real ebook (Dreams and Visions, 2026-10-30), with made-up text: Docling read its contents page as
headings, each followed by a line about the chapter, so every entry became a chapter of one sentence and the
whole book went into the last of them ("Introduction", 4 h 09 min). Its own chapters were "Chapter 3" on a line
of its own, which Docling read as text and put at the foot of the chapter's first page, sometimes with no title
heading at all. Its PDF named no title, so the first heading on its first page ("Praise for") became the title.
"""

import pytest
from docling_core.types.doc import BoundingBox, DocItemLabel, DoclingDocument, ProvenanceItem, Size

from audiobook.names import chapter_audio, chapter_stem, is_placeholder_title, title_at_heading, title_from_file_name
from audiobook.plan import build_plan, choose_title

LONG = "The water ran on through the night and nobody stopped it. " * 12  # over a contents entry's 60 words


def book(*pages: list[tuple[str, str]]) -> DoclingDocument:
    """A document of pages, each a list of ("h" heading | "t" text, text)."""
    doc = DoclingDocument(name="book")
    for number, page in enumerate(pages, 1):
        doc.add_page(page_no=number, size=Size(width=100, height=100))
        prov = ProvenanceItem(page_no=number, bbox=BoundingBox(l=0, t=0, r=1, b=1), charspan=(0, 1))
        for kind, text in page:
            if kind == "h":
                doc.add_heading(text, prov=prov)
            else:
                doc.add_text(label=DocItemLabel.TEXT, text=text, prov=prov)
    return doc


RIVER = book(
    [("h", "Praise for"), ("t", "A fine book about water, says a reader."), ("h", "THE RIVER BOOK")],
    # The contents page, read as headings with a line under each.
    [("h", "Contents"), ("h", "Foreword"), ("h", "Chapter 1 Where the River Starts"), ("t", "What is a spring?"),
     ("h", "Chapter 2 The Long Valley"), ("t", "Why do rivers bend? Where do they go?"),
     ("h", "Chapter 3 Into the Sea"), ("t", "What is a delta?")],
    [("h", "FOREWORD"), ("t", "Foreword text. " + LONG)],
    # Label, then its title on the same page: one heading.
    [("t", "Chapter 1"), ("h", "WHERE THE RIVER STARTS"), ("t", "Chapter one begins. " + LONG)],
    # Title first, then a paragraph, then the label, all on the chapter's first page.
    [("h", "THE LONG VALLEY"), ("t", "Chapter two begins. " + LONG), ("t", "Chapter 2")],
    # The label at the foot of the first page with no title at all; a section heading on the next page.
    [("t", "Chapter three begins. " + LONG), ("t", "Chapter 3")],
    [("h", "Deltas and Mud"), ("t", "Chapter three goes on. " + LONG)],
)


@pytest.fixture(scope="module")
def river():
    return build_plan(RIVER, file_name="The River Book Being a Guide to Water (Ann Brook [Brook, Ann]) (Z-Library)")


def test_the_contents_page_is_left_out_and_each_chapter_starts_on_its_own_first_page(river):
    assert [c.title for c in river.chapters] == [
        "Opening", "Foreword", "Chapter 1 Where the River Starts", "Chapter 2 The Long Valley", "Chapter 3 Into the Sea",
    ]
    firsts = [c.segments[0].text for c in river.chapters[2:]]
    assert firsts[0].startswith("Chapter one begins") and firsts[1].startswith("Chapter two begins")
    assert firsts[2].startswith("Chapter three begins")  # not left at the end of chapter 2
    assert [s.text for s in river.chapters[4].segments if s.kind == "heading"] == ["Deltas and Mud"]
    left_out = [s.text for c in river.chapters for s in c.skipped if s.reason == "table of contents"]
    assert "What is a spring?" in left_out and "Contents" in left_out and "Chapter 3 Into the Sea" in left_out


def test_a_chapter_is_named_as_the_contents_page_names_it_and_its_title_is_not_read_twice(river):
    """"THE LONG VALLEY" under "Chapter 2 The Long Valley" would be announced, then read again."""
    spoken = [s.text for c in river.chapters for s in c.segments]
    assert "THE LONG VALLEY" not in spoken
    assert [s.text for c in river.chapters for s in c.skipped if s.reason == "repeated heading"] == ["THE LONG VALLEY"]


def test_the_title_is_the_file_name_cut_where_the_title_page_s_heading_ends(river):
    assert (river.title, river.author) == ("The River Book", "Ann Brook")
    assert river.chapters[0].segments[0].kind == "heading"  # "Praise for" is read, not taken for the title


def test_a_book_that_numbers_its_chapters_again_in_each_part_keeps_them_all():
    """Two "Chapter 1"s that each open straight onto a section are chapters, not a contents page."""
    part = [("h", "Chapter 1"), ("h", "1.1 Background"), ("t", LONG), ("h", "Chapter 2"), ("h", "2.1 Method"), ("t", LONG)]
    plan = build_plan(book([("h", "Part I")] + part, [("h", "Part II")] + part), file_name="two parts")
    assert [c.title for c in plan.chapters] == ["Chapter 1", "Chapter 2", "Chapter 1", "Chapter 2"]
    assert not [s for c in plan.chapters for s in c.skipped if s.reason == "table of contents"]


def test_a_label_read_as_text_does_not_swallow_the_chapter_s_first_numbered_section():
    plan = build_plan(book([("t", "Chapter 1"), ("h", "1.1 Background"), ("t", LONG)],
                           [("t", "Chapter 2"), ("h", "2.1 Method"), ("t", LONG)]), file_name="two chapters")
    assert [c.title for c in plan.chapters] == ["Chapter 1", "Chapter 2"]
    assert [s.text for c in plan.chapters for s in c.segments if s.kind == "heading"] == ["Background", "Method"]


@pytest.mark.parametrize("stem, title, author", [
    ("Dreams and Visions Understanding Your Dreams (Jane Hamon [Hamon, Jane]) (Z-Library)",
     "Dreams and Visions Understanding Your Dreams", "Jane Hamon"),
    ("The Final Quest (Rick Joyner) (z-lib.org)", "The Final Quest", "Rick Joyner"),
    ("Collected Poems (2nd edition)", "Collected Poems (2nd edition)", None),  # no site's tag: not an author
    ("Roberts Liardon - Sharpen your discernment (2004, Whitaker House ) - libgen.li-1",
     "Sharpen your discernment", "Roberts Liardon"),
    ("Rivers of Light (2004) - libgen.li", "Rivers of Light", None),
    ("Overcoming Addictive Behavior The Victory Over the Darkness Series"
     " (Neil T. Anderson [Anderson, Neil T.]) (z-library.sk, 1lib.sk, z-lib.sk)",
     "Overcoming Addictive Behavior The Victory Over the Darkness Series", "Neil T. Anderson"),
    ("_OceanofPDF.com_The_King_Is_Coming_-_John_Bevere", "The King Is Coming", "John Bevere"),
    ("_OceanofPDF.com_Great_Expectations_-_Charles_Dickens", "Great Expectations", "Charles Dickens"),
    ("the_long_valley", "the long valley", None),
    ("2609.09153v1", None, None),  # no word in it
])
def test_a_title_and_author_from_a_file_name(stem, title, author):
    assert title_from_file_name(stem) == (title, author)


def test_the_cut_needs_a_heading_that_begins_the_name():
    name = "Dreams and Visions Understanding Your Dreams"
    assert title_at_heading(name, ["Praise for", "DREAMS AND VISIONS"]) == "Dreams and Visions"
    assert title_at_heading(name, ["Dreams"]) is None  # one word cuts only when it is the whole name
    assert title_at_heading("Dune", ["DUNE"]) == "Dune"
    assert title_at_heading(name, ["Praise for"]) is None


def test_which_title_wins():
    front = ["Praise for", "THE RIVER BOOK"]
    assert choose_title("The River Book Guide", "Its Own Title", None, front)[0] == "Its Own Title"  # the PDF's own
    assert choose_title("The River Book Guide", None, None, front)[0] == "The River Book"
    assert choose_title("River Guide Notes", None, None, front)[0] == "River Guide Notes"  # two words or more
    # A one-word or wordless file name says less than the book's first heading, which becomes the title.
    assert choose_title("paper", None, None, front)[0] is None
    assert choose_title("2609.09153v1", None, None, front)[0] is None


def test_a_chapter_s_audio_is_found_by_its_whole_name_at_any_speed():
    names = [
        "03-chapter-2-the-long-valley-0.95x.mp3", "03-chapter-2-the-long-valley.mp3",
        "03-chapter-2-old-name-0.95x.mp3",  # an earlier reading numbered the chapters differently
        "03-chapter-2-the-long-valley-0.95x.wav", "the-river-book-0.95x.m4b",
    ]
    assert chapter_stem(3, "Chapter 2 The Long Valley") == "03-chapter-2-the-long-valley"
    assert chapter_audio(names, 3, "Chapter 2 The Long Valley") == [
        ("03-chapter-2-the-long-valley-0.95x.mp3", 0.95), ("03-chapter-2-the-long-valley.mp3", 1.0),
    ]


@pytest.mark.parametrize("title, placeholder", [
    ("about:blank", True), ("Untitled", True), ("Microsoft Word - draft 3.docx", True), ("chapter-one.pdf", True),
    ("The Final Quest", False), ("Procedural Graphs: Self-Evolving Execution Structures for LLM Agents", False),
])
def test_a_title_a_program_filled_in_by_itself_is_not_the_book_s(title, placeholder):
    """Chrome wrote "about:blank" into a PDF it printed, and the library called the book that."""
    assert is_placeholder_title(title) is placeholder
