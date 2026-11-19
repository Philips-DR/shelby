"""Bible references, said the way a person reads them aloud. Pure.

The voice cannot be left to read "1 John 2:23", "Gen. 1:31", "Ps. 31:5; 45:4" or "Rom. 6:23a" by itself. Whisper heard the
rendered audio of six real books (2026-11-19, abigail): "1 John 1:9" came out as "John 1, verse 9" (the number lost),
"2 Samuel 24:14b" as "To Samuel 2440", "Gen. 1:31" as "Cgen 131", "Ps. 111:7" as "Pez 111-1", "1 Cor. 3:16; 6:19" as "One
Core 316-619", "Rom. 6:23a" as "rome six two threea", and "KJV" as "K J D".

So a reference is read as a whole, from a table of the 66 books (full names and the short forms books use), and every
form comes out the same way:

    1 John 2:23              First John chapter 2, verse 23
    Ps. 23:4                 Psalm 23, verse 4
    Rom. 1:24, 26            Romans chapter 1, verses 24 and 26
    Exod. 25:1-3,8           Exodus chapter 25, verses 1 to 3 and 8
    Rom. 6:23a               Romans chapter 6, verse 23 a
    Gen. 8:21-9:1            Genesis chapter 8, verse 21, to chapter 9, verse 1
    Ps. 31:5; 45:4           Psalm 31, verse 5; and Psalm 45, verse 4
    (Rom. 3:23 NKJV)         (Romans chapter 3, verse 23, New King James Version)
    vv. 37-38                verses 37 to 38

The digits are left for `speech.for_speech` to turn into words, as for every other number. A name is read as a book only
with a chapter and a verse after it ("Is 3:30" and "Am 3:30" are never Isaiah and Amos, and the short forms that are also
English words are not in the table), so "I John 3:16" is First John but "and I John saw" is left alone."""

import re

# Spoken name -> the ways it is written. A numbered book is written with a 1, 2 or 3 (or I, II, III, First...) in front.
_NUMBERED = {
    "John": ["John", "Jn", "Jhn"],
    "Corinthians": ["Corinthians", "Cor"],
    "Thessalonians": ["Thessalonians", "Thess", "Thes"],
    "Timothy": ["Timothy", "Tim", "Tm"],
    "Peter": ["Peter", "Pet"],
    "Samuel": ["Samuel", "Sam", "Sm"],
    "Kings": ["Kings", "Kgs"],
    "Chronicles": ["Chronicles", "Chron", "Chr"],
}
_PLAIN = {
    "Genesis": ["Genesis", "Gen", "Gn"],
    "Exodus": ["Exodus", "Exod", "Exo", "Ex"],
    "Leviticus": ["Leviticus", "Lev", "Lv"],
    "Numbers": ["Numbers", "Num"],
    "Deuteronomy": ["Deuteronomy", "Deut", "Dt"],
    "Joshua": ["Joshua", "Josh", "Jos"],
    "Judges": ["Judges", "Judg", "Jdg", "Jg"],
    "Ruth": ["Ruth"],
    "Ezra": ["Ezra"],
    "Nehemiah": ["Nehemiah", "Neh"],
    "Esther": ["Esther", "Esth", "Est"],
    "Job": ["Job"],
    "Psalm": ["Psalms", "Psalm", "Pss", "Psa", "Ps"],
    "Proverbs": ["Proverbs", "Prov", "Prv", "Pr"],
    "Ecclesiastes": ["Ecclesiastes", "Eccles", "Eccl", "Ecc"],
    "Song of Solomon": ["Song of Solomon", "Song of Sol", "Song"],
    "Song of Songs": ["Song of Songs"],
    "Isaiah": ["Isaiah", "Isa"],
    "Jeremiah": ["Jeremiah", "Jer"],
    "Lamentations": ["Lamentations", "Lam"],
    "Ezekiel": ["Ezekiel", "Ezek", "Eze", "Ezk"],
    "Daniel": ["Daniel", "Dan", "Dn"],
    "Hosea": ["Hosea", "Hos"],
    "Joel": ["Joel"],
    "Amos": ["Amos"],
    "Obadiah": ["Obadiah", "Obad"],
    "Jonah": ["Jonah", "Jon"],
    "Micah": ["Micah", "Mic"],
    "Nahum": ["Nahum", "Nah"],
    "Habakkuk": ["Habakkuk", "Hab"],
    "Zephaniah": ["Zephaniah", "Zeph"],
    "Haggai": ["Haggai", "Hag"],
    "Zechariah": ["Zechariah", "Zech", "Zec"],
    "Malachi": ["Malachi", "Mal"],
    "Matthew": ["Matthew", "Matt", "Mat", "Mt"],
    "Mark": ["Mark", "Mk"],
    "Luke": ["Luke", "Lk"],
    "John": ["John", "Jn", "Jhn"],
    "Acts": ["Acts"],
    "Romans": ["Romans", "Rom", "Rm"],
    "Galatians": ["Galatians", "Gal"],
    "Ephesians": ["Ephesians", "Eph", "Ephes"],
    "Philippians": ["Philippians", "Phil"],
    "Colossians": ["Colossians", "Col"],
    "Titus": ["Titus", "Tit"],
    "Philemon": ["Philemon", "Philem", "Phlm", "Phm"],
    "Hebrews": ["Hebrews", "Heb"],
    "James": ["James", "Jas"],
    "Jude": ["Jude"],
    "Revelation": ["Revelation", "Revelations", "Rev"],
}
_ORDINAL = {"1": "First", "I": "First", "1st": "First", "First": "First",
            "2": "Second", "II": "Second", "2nd": "Second", "Second": "Second",
            "3": "Third", "III": "Third", "3rd": "Third", "Third": "Third"}

# Bible versions: the letters a book writes after a reference, and what a person says.
VERSIONS = {
    "KJV": "King James Version", "NKJV": "New King James Version", "NIV": "New International Version",
    "NASB": "New American Standard Bible", "ESV": "English Standard Version", "NLT": "New Living Translation",
    "NRSV": "New Revised Standard Version", "RSV": "Revised Standard Version", "ASV": "American Standard Version",
    "AMP": "Amplified Bible", "AMPC": "Amplified Bible, Classic Edition", "TLB": "The Living Bible",
    "MSG": "The Message", "TPT": "The Passion Translation", "CEV": "Contemporary English Version",
    "GNB": "Good News Bible", "HCSB": "Holman Christian Standard Bible", "CSB": "Christian Standard Bible",
}
# These letters are a version wherever they stand ("(NKJV)", `["glory" NKJV]`); the rest only after a reference.
_ANYWHERE = ("KJV", "NKJV", "NIV", "NASB", "ESV", "NLT", "NRSV")


def _forms(table: dict[str, list[str]]) -> tuple[dict[str, str], str]:
    """Every written form (and the same in capitals, for a heading) -> its spoken name, and a pattern for them."""
    spoken: dict[str, str] = {}
    for name, forms in table.items():
        for form in forms:
            spoken[form] = name
            if len(form) >= 4:
                spoken[form.upper()] = name
    pattern = "|".join(re.escape(f).replace(r"\ ", r"\s+") for f in sorted(spoken, key=len, reverse=True))
    return spoken, rf"(?:{pattern})\.?"


_NUMBERED_SPOKEN, _NUMBERED_PATTERN = _forms(_NUMBERED)
_PLAIN_SPOKEN, _PLAIN_PATTERN = _forms(_PLAIN)

# The start of a reference: the name, then chapter and a colon. Numbered books need their number, so "John 3:16" is the
# gospel and "1 John 3:16" is First John. The text before a number must not be a word, a number or a path.
_HEAD = re.compile(
    r"(?:(?<![\w:./-])(?P<n>[1-3]|I{1,3}|1st|2nd|3rd|First|Second|Third)[ \u00a0]?(?P<nb>" + _NUMBERED_PATTERN + r")"
    r"|(?<![\w])(?P<pb>" + _PLAIN_PATTERN + r"))"
    r"[ \u00a0]*(?P<ch>\d{1,3})[ \u00a0]?:[ \u00a0]?(?:[-–—][ \u00a0]?)?(?=\d)"  # "Ps. 91:-16": a stray hyphen is skipped
)
# One verse, or a range of them: "16", "16b", "16-18", "13b-14", "21-9:1" (into the next chapter).
_ITEM = re.compile(
    r"(?P<v>\d{1,3})(?P<l>[a-c])?(?:\s?[-–—]\s?(?:(?P<c2>\d{1,3})\s?:\s?)?(?P<v2>\d{1,3})(?P<l2>[a-c])?)?(?![A-Za-z\d])"
)
_NEXT = re.compile(r"\s*(?:[,;]\s*(?:and\s+|&\s*)?|and\s+|&\s*)")
_CHAPTER = re.compile(r"(?P<ch>\d{1,3})\s?:\s?(?=\d)")
# A bare number after a list of verses ("Romans 1:24, 26") is a verse only when the reference plainly ends there.
_COLON = re.compile(r"\s?:")
_ENDS = re.compile(r"(?=[)\]\.,;!?\"”’]|\s*$|\s+[A-Z])")
_TAG = re.compile(r"(?P<pre>\s*,?\s*[(\[]?)(?P<tag>(?i:" + "|".join(sorted(VERSIONS, key=len, reverse=True)) + r"))(?![A-Za-z])")
_ANYWHERE_TAG = re.compile(r"\b(" + "|".join(sorted(_ANYWHERE, key=len, reverse=True)) + r")\b")
_VERSE_ABBREVIATION = re.compile(
    r"(?:(?<![\w])(?P<v>vv?)|(?<=\()(?P<s>vss?))\.[ \u00a0]?(?P<a>\d{1,3})(?P<la>[a-c])?(?:\s?[-–—]\s?(?P<b>\d{1,3})(?P<lb>[a-c])?)?(?![A-Za-z\d])"
)
_VERSE_LIST = re.compile(
    r"\bverses?\s+(?P<first>\d{1,3}[a-c]?)(?P<rest>(?:\s?[-–—]\s?\d{1,3}[a-c]?|,\d{1,3}[a-c]?)+)(?![A-Za-z\d])"
)
# "(AMP)" after a quotation: in brackets, these letters are a version in these books, never the word.
_BRACKETED_VERSION = re.compile(r"\((" + "|".join(sorted(VERSIONS, key=len, reverse=True)) + r")\)")
# "the Book of 1 John": a number and John after these words can only be the letter.
_BOOK_OF_JOHN = re.compile(r"\b(?P<of>(?:[Bb]ook|[Ee]pistles?|[Ll]etters?) of )(?P<n>[1-3]|1st|2nd|3rd) John\b")
_UNAMBIGUOUS_NUMBERED = re.compile(
    r"(?<![\w:./-])(?P<n>[1-3]|1st|2nd|3rd)[ \u00a0]?(?P<b>Corinthians|Thessalonians|Timothy|Peter|Samuel|Kings|Chronicles)\b"
)

_FULL_FORMS = {"Psalms", "Revelations", "Song of Songs"}  # the forms of a book's name that are not abbreviations


def _abbreviations(table: dict[str, list[str]]) -> str:
    """The forms of a book's name that are shortened (so they carry a full stop), as a pattern."""
    short = [f for name, forms in table.items() for f in forms if f != name and f not in _FULL_FORMS]
    return "|".join(re.escape(f).replace(r"\ ", r"\s+") for f in sorted(short, key=len, reverse=True))


_ABBREVIATED = re.compile(
    r"(?:(?<![\w:./-])(?P<n>[1-3]|I{1,3}|1st|2nd|3rd)[ \u00a0]?(?P<nb>" + _abbreviations(_NUMBERED) + r")"
    r"|(?<![\w])(?P<pb>" + _abbreviations(_PLAIN) + r"))\.[ \u00a0]?(?=\d)"
)
# One chapter or a range of them, with nothing after it that makes it a verse ("Gen. 22:3") or a longer number.
_CHAPTER_ITEM = re.compile(r"(?P<c>\d{1,3})(?:\s?[-–—]\s?(?P<c2>\d{1,3}))?(?![A-Za-z\d]|\s?:\s?\d)")
# More chapters follow a semicolon, comma or "and" only when the number plainly ends there ("Exod. 15; 1 Sam. 18:6").
_CHAPTERS_END = re.compile(r"(?=[)\]\.,;!?\"”’]|\s*$)")

MAX_CHAPTER, MAX_VERSE = 150, 176  # the Bible's own: Psalm 150, Psalm 119:176

# "Acts 9:1012": the PDF lost the dash of "9:10-12" (9 references in the user's six books; the dash step restores some
# and misses others). No verse has four digits, so right after a book, chapter and colon a run of four digits that is two
# ascending verses can only be a range whose dash was lost.
_LOST_DASH = re.compile(_HEAD.pattern + r"(?P<a>\d{2})(?P<b>\d{2})(?![A-Za-z\d])")
# ...and one lost after a half-verse's letter: "Mark 7:14b23" is "14b-23" (a letter with digits straight after it).
_LOST_DASH_LETTER = re.compile(_HEAD.pattern + r"(?P<a>\d{1,3})(?P<l>[a-c])(?P<b>\d{1,3})(?![A-Za-z\d])")


def _verse(number: str, letter: str | None) -> str:
    return f"{number} {letter}" if letter else number


def _item(m: re.Match) -> str:
    start = _verse(m["v"], m["l"])
    if m["v2"] is None:
        return start
    end = _verse(m["v2"], m["l2"])
    return f"{start}, to chapter {m['c2']}, verse {end}" if m["c2"] else f"{start} to {end}"


def _join(items: list[str]) -> str:
    return " and ".join(items) if len(items) <= 2 else ", ".join(items[:-1]) + " and " + items[-1]


def _segment(book: str, chapter: str, items: list[re.Match]) -> str:
    """One chapter's verses: "Romans chapter 1, verses 24 and 26". A psalm is a "Psalm 23", not a chapter of one."""
    several = len(items) > 1 or (items[0]["v2"] is not None and items[0]["c2"] is None)
    verses = ("verses " if several else "verse ") + _join([_item(i) for i in items])
    return f"Psalm {chapter}, {verses}" if book == "Psalm" else f"{book} chapter {chapter}, {verses}"


def _book(head: re.Match) -> str:
    if head["pb"]:
        return _PLAIN_SPOKEN[head["pb"].rstrip(".")]
    return f"{_ORDINAL[head['n']]} {_NUMBERED_SPOKEN[head['nb'].rstrip('.')]}"


def _in_range(chapter: str, items: list[re.Match]) -> bool:
    numbers = [int(i[k]) for i in items for k in ("v", "v2") if i[k]]
    return 0 < int(chapter) <= MAX_CHAPTER and all(0 < n <= MAX_VERSE for n in numbers)


def _read(text: str, head: re.Match) -> tuple[str, int] | None:
    """The spoken form of the reference that begins at `head`, and where it ends; None when it is not one."""
    item = _ITEM.match(text, head.end())
    if not item:
        return None
    segments: list[tuple[str, list[re.Match]]] = []
    chapter, items, at = head["ch"], [item], item.end()
    while True:
        more = _NEXT.match(text, at)
        if not more:
            break
        after = more.end()
        new_chapter = _CHAPTER.match(text, after)
        if new_chapter:  # "; 45:4" or ", 50:23": the same book, another chapter
            item = _ITEM.match(text, new_chapter.end())
            if not item:
                break
            segments.append((chapter, items))
            chapter, items, at = new_chapter["ch"], [item], item.end()
            continue
        bare = _ITEM.match(text, after)  # ", 26" or "; 14-18": more verses of the same chapter
        # After a semicolon only a range is taken for verses: a lone number there may be a chapter ("Gen. 1:1; 2").
        verses = bare and ("," in more.group() or (";" in more.group() and bare["v2"] and not bare["c2"]))
        tight = more.group() == ","  # "19,20": no space, so it is a list whatever follows it
        if verses and not _COLON.match(text, bare.end()) and (tight or _ENDS.match(text, bare.end())):
            items.append(bare)
            at = bare.end()
            continue
        break
    segments.append((chapter, items))
    if not all(_in_range(c, i) for c, i in segments):
        return None
    parts = [_segment(_book(head), c, i) for c, i in segments]
    spoken = parts[0] if len(parts) == 1 else "; ".join(parts[:-1]) + "; and " + parts[-1]
    tag = _TAG.match(text, at)
    if tag:  # "(Rom. 3:23 NKJV)": the version's name, after a comma when the book wrote none
        spoken += (tag["pre"] if tag["pre"].strip() else ", ") + VERSIONS[tag["tag"].upper()]
        at = tag.end()
    return spoken, at


def _restore_dash(m: re.Match) -> str:
    if not int(m["a"]) < int(m["b"]):
        return m.group()
    return m.string[m.start():m.start("a")] + f"{m['a']}-{m['b']}"


def _restore_dash_after_letter(m: re.Match) -> str:
    if not int(m["a"]) < int(m["b"]):
        return m.group()
    return m.string[m.start():m.start("a")] + f"{m['a']}{m['l']}-{m['b']}"


def references(text: str) -> str:
    """Every Bible reference in `text`, said the way it is read aloud (digits left for the number rules)."""
    text = _LOST_DASH.sub(_restore_dash, text)
    text = _LOST_DASH_LETTER.sub(_restore_dash_after_letter, text)
    out, at = [], 0
    for head in _HEAD.finditer(text):
        if head.start() < at:
            continue  # inside a reference already read
        read = _read(text, head)
        if read is None:
            continue
        out.append(text[at:head.start()])
        out.append(read[0])
        at = read[1]
    out.append(text[at:])
    return "".join(out)


def chapter_lists(text: str) -> str:
    """A chapter, or chapters, after an abbreviation with its full stop ("Gen. 22", "Exod. 29-30;39-40", "1 Sam. 13, 15,
    and 16"): the book's whole name, which the voice cannot make of "Gen." ("Cgen"). A book written out in full ("Genesis
    22") is left to the number rules, which read it well."""
    out, at = [], 0
    for head in _ABBREVIATED.finditer(text):
        if head.start() < at:
            continue
        first = _CHAPTER_ITEM.match(text, head.end())
        if not first:
            continue
        items, end = [first], first.end()
        while (more := _NEXT.match(text, end)) and (nxt := _CHAPTER_ITEM.match(text, more.end())) and _CHAPTERS_END.match(text, nxt.end()):
            items.append(nxt)
            end = nxt.end()
        chapters = [int(i[k]) for i in items for k in ("c", "c2") if i[k]]
        if not all(0 < c <= MAX_CHAPTER for c in chapters) or any(i["c2"] and int(i["c2"]) <= int(i["c"]) for i in items):
            continue
        book = _PLAIN_SPOKEN[head["pb"]] if head["pb"] else f"{_ORDINAL[head['n']]} {_NUMBERED_SPOKEN[head['nb']]}"
        said = [f"{i['c']} to {i['c2']}" if i["c2"] else i["c"] for i in items]
        if len(items) == 1 and not items[0]["c2"]:
            spoken = f"{book} {said[0]}"
        else:
            spoken = f"{'Psalms' if book == 'Psalm' else book + ' chapters'} {_join(said)}"
        out += [text[at:head.start()], spoken]
        at = end
    out.append(text[at:])
    return "".join(out)


def verse_marks(text: str) -> str:
    """"v. 39", "(vs. 3)" and "vv. 37-38", which a book writes after a quotation, said as verses."""
    def say(m: re.Match) -> str:
        first = _verse(m["a"], m["la"])
        if m["b"] is None:
            return "verses " + first if (m["v"] or m["s"]) in ("vv", "vss") else f"verse {first}"
        return f"verses {first} to {_verse(m['b'], m['lb'])}"

    return _VERSE_ABBREVIATION.sub(say, text)


def verse_lists(text: str) -> str:
    """What a book writes out itself: "verses 29-32" and "verse 17,18" (read as digits, "twenty-nine-thirty-two")."""
    def say(m: re.Match) -> str:
        items = [m["first"]]
        for sign, number in re.findall(r"([-–—]|,)\s?(\d{1,3}[a-c]?)", m["rest"]):
            if sign == ",":
                items.append(number)
            else:
                items[-1] += f" to {number}"
        return "verses " + _join([re.sub(r"(\d)([a-c])\b", r"\1 \2", i) for i in items])

    return _VERSE_LIST.sub(say, text)


def numbered_books(text: str) -> str:
    """"1 Corinthians" with no chapter after it: "First Corinthians" (the voice reads the digit as a count). Also "the
    Book of 1 John"."""
    text = _BOOK_OF_JOHN.sub(lambda m: f"{m['of']}{_ORDINAL[m['n']]} John", text)
    return _UNAMBIGUOUS_NUMBERED.sub(lambda m: f"{_ORDINAL[m['n']]} {m['b']}", text)


def version_names(text: str) -> str:
    """"NKJV", "KJV", "NIV"... standing alone: the version's name (read as letters, KJV came out "K J D")."""
    text = _ANYWHERE_TAG.sub(lambda m: VERSIONS[m.group(1)], text)
    return _BRACKETED_VERSION.sub(lambda m: f"({VERSIONS[m.group(1)]})", text)
