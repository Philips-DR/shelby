"""How a book and its files are named: a title read from a PDF's file name, and the audio file of a chapter.

Pure: no I/O. render.py names the files with these, and operations.py finds them again with the same rules.
"""

import re

# ---------------------------------------------------------------------------------------------
# A chapter's audio file: "02-chapter-1-god-s-purpose-for-dreams-and-visions-0.95x.mp3"


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "chapter"


def speed_suffix(speed: float) -> str:
    return "" if speed == 1 else f"-{speed:g}x"


def chapter_stem(number: int, title: str) -> str:
    """A chapter's file name before the speed: its number as the book's plan counts it, and its title."""
    return f"{number:02d}-{slugify(title)}"


SPEED_AND_SUFFIX = re.compile(r"(?:-(?P<speed>\d+(?:\.\d+)?)x)?\.mp3")


def chapter_audio(names: list[str], number: int, title: str) -> list[tuple[str, float]]:
    """The files among `names` that are this chapter, rendered at any speed, as (name, speed).

    Matched on the whole stem, number and title alike, so a file left from an earlier reading of the book, when
    its chapters were found differently, belongs to no chapter of the current one."""
    stem = chapter_stem(number, title)
    found = []
    for name in names:
        m = SPEED_AND_SUFFIX.fullmatch(name[len(stem):]) if name.startswith(stem) else None
        if m:
            found.append((name, float(m["speed"] or 1)))
    return found


# ---------------------------------------------------------------------------------------------
# A title from the file name, for a PDF that names none in its own metadata

# A download site’s tag at the end: "(Z-Library)", "(z-lib.org)", "[libgen.li]", "(Anna’s Archive)",
# and the multi-domain mirror list newer Z-Library downloads use: "(z-library.sk, 1lib.sk, z-lib.sk)".
SITE_TAG = re.compile(
    r"\s*[(\[]\s*(?:z-?lib(?:rary)?|1lib|libgen|anna[‘’]s archive)(?:\.\w+)?(?:\s*,\s*\S+)*\s*[)\]]\s*$",
    re.IGNORECASE,
)
# OceanofPDF names a file "_OceanofPDF.com_Title_-_Author" (underscores become spaces above).
OCEAN_PREFIX = re.compile(r"^\s*OceanofPDF\.com\s+", re.IGNORECASE)
# Library Genesis names a file "Author - Title (Year, Publisher) - libgen.li", sometimes with "-1" after it.
LIBGEN_TAG = re.compile(r"\s+-\s+libgen(?:\.\w+)?(?:-\d+)?\s*$", re.IGNORECASE)
YEAR_AND_PUBLISHER = re.compile(r"\s*\(\s*\d{4}\s*(?:,[^()]*)?\)\s*$")
# The author, last: "(Jane Hamon [Hamon, Jane])". The bracket is the catalogue's "Last, First".
AUTHOR_GROUP = re.compile(r"\s*\((?P<author>[^()\[\]]+?)\s*(?P<sorted>\[[^\[\]]*\])?\)\s*$")
# A title has a word in it: "2609.09153v1" has none, and its first heading names it better.
A_WORD = re.compile(r"[^\W\d_]{3}")


def title_from_file_name(stem: str) -> tuple[str | None, str | None]:
    """(title, author) from a PDF's file name, without what a download site added to it.

    "Dreams and Visions Understanding Your Dreams… (Jane Hamon [Hamon, Jane]) (Z-Library)" →
    ("Dreams and Visions Understanding Your Dreams…", "Jane Hamon"). A last group in brackets is taken for the
    author only when a site's tag came after it or it has the catalogue's "[Last, First]": "Collected Poems
    (2nd edition)" keeps its brackets. Library Genesis puts the author first: "Roberts Liardon - Sharpen your
    discernment (2004, Whitaker House ) - libgen.li-1" → ("Sharpen your discernment", "Roberts Liardon"). The title
    is None when the name has no word in it."""
    name = stem.replace("_", " ")
    if m := OCEAN_PREFIX.match(name):
        rest = name[m.end():]
        title_part, sep, author_part = rest.rpartition(" - ")
        if sep and A_WORD.search(title_part):
            return re.sub(r"\s+", " ", title_part).strip(), author_part.strip() or None
        name = rest
    if m := LIBGEN_TAG.search(name):
        author, dash, title = YEAR_AND_PUBLISHER.sub("", name[: m.start()]).partition(" - ")
        if dash and A_WORD.search(title):
            return re.sub(r"\s+", " ", title).strip(), author.strip() or None
        name = author  # no "Author - " before the title: the whole of it is the title
    tagged = False
    while m := SITE_TAG.search(name):
        name, tagged = name[: m.start()], True
    author = None
    m = AUTHOR_GROUP.search(name)
    if m and (tagged or m["sorted"]):
        name, author = name[: m.start()], m["author"].strip()
    name = re.sub(r"\s+", " ", name).strip()
    return (name if A_WORD.search(name) else None), author or None


def title_at_heading(name: str, headings: list[str]) -> str | None:
    """The file's title cut where a heading on the book's title page ends, or None when no heading begins it.

    A file name runs a title and its subtitle together ("Dreams and Visions Understanding Your Dreams and How
    God…"); the title page sets the title apart ("DREAMS AND VISIONS"). The cut keeps the file's own spelling,
    as a title page is often in capitals. A heading of one word cuts only when it is the whole name, so a title
    page's "The" or "Praise" does not."""
    words = list(re.finditer(r"\w+", name))
    keys = [w.group().casefold() for w in words]
    longest = 0
    for heading in headings:
        wanted = [w.casefold() for w in re.findall(r"\w+", heading)]
        if wanted and (len(wanted) >= 2 or len(wanted) == len(keys)) and keys[: len(wanted)] == wanted:
            longest = max(longest, len(wanted))
    return name[: words[longest - 1].end()] if longest else None


# What a program writes as a PDF's title when nobody gave it one: Chrome printing a page with no title wrote
# "about:blank" (found 2026-10-30); Word writes "Microsoft Word - <file>"; others write the source's file name.
PLACEHOLDER_TITLE = re.compile(
    r"^(about:blank|untitled( document)?|document\d*|title|microsoft (word|powerpoint|excel) - .*"
    r"|.*\.(docx?|pdf|odt|rtf|tex|indd|html?|txt|pages))$",
    re.IGNORECASE,
)


def is_placeholder_title(title: str) -> bool:
    return bool(PLACEHOLDER_TITLE.match(title.strip()))
