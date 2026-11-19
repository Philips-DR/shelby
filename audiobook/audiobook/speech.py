"""Rewrite text into what the voice can say correctly. Pure.

Every rule here was checked by synthesising the text with the abigail voice and transcribing it
with Whisper (2026-09-30). Before → what the voice said:
  "Part III, The Return of The Eagles"   → "Apart at the Return of the Eagles"
  "Ephesians 1:18, the eyes of…"          → "Ephesians 1." — and the rest of the sentence was lost
  "THE JUDGMENT SEAT OF CHRIST"          → "Dijanin's Seat of Christ"
  "turned into a . . . and I stopped"    → "turned into a thin" — rest lost
  "Parts II & III"                       → "hearts and the toughest"
After these rules all five were read correctly. Don't add rules that haven't been checked this way.
Bible references have their own module, `scripture.py`, checked the same way (2026-11-19).
"""

import re

from . import scripture

ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
        "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]
ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}


def roman_to_int(roman: str) -> int:
    total = 0
    for a, b in zip(roman, roman[1:] + " "):
        v = ROMAN_VALUES[a]
        total += -v if b in ROMAN_VALUES and ROMAN_VALUES[b] > v else v
    return total


def number_word(n: int) -> str:
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + ("-" + ONES[n % 10].lower() if n % 10 else "")
    w = int_to_words(n)
    return w[0].upper() + w[1:]


# --- Arabic numerals to words (every digit sequence the voice would otherwise read one at a time) ---


def _under_thousand(n: int) -> str:
    parts = []
    if n >= 100:
        parts.append(ONES[n // 100].lower() + " hundred")
        n %= 100
    if n >= 20:
        t = TENS[n // 10].lower()
        o = n % 10
        parts.append(t + "-" + ONES[o].lower() if o else t)
    elif n > 0:
        parts.append(ONES[n].lower())
    return " ".join(parts)


def int_to_words(n: int) -> str:
    if n == 0:
        return "zero"
    parts = []
    for scale, label in ((1_000_000_000, "billion"), (1_000_000, "million"), (1_000, "thousand")):
        if n >= scale:
            parts.append(_under_thousand(n // scale) + " " + label)
            n %= scale
    if n > 0:
        parts.append(_under_thousand(n))
    return " ".join(parts)


def year_to_words(n: int) -> str:
    if n == 2000:
        return "two thousand"
    if 2001 <= n <= 2009:
        return "two thousand " + ONES[n - 2000].lower()
    hi, lo = divmod(n, 100)
    front = _under_thousand(hi)
    if lo == 0:
        return front + " hundred"
    if lo < 10:
        return front + " oh " + ONES[lo].lower()
    return front + " " + _under_thousand(lo)


_DIGIT_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]


_ORDINAL_SPECIAL = {
    "zero": "zeroth", "one": "first", "two": "second", "three": "third",
    "five": "fifth", "eight": "eighth", "nine": "ninth", "twelve": "twelfth",
}
_ORDINAL_TENS = {
    "twenty": "twentieth", "thirty": "thirtieth", "forty": "fortieth", "fifty": "fiftieth",
    "sixty": "sixtieth", "seventy": "seventieth", "eighty": "eightieth", "ninety": "ninetieth",
}


def ordinal_to_words(n: int) -> str:
    cardinal = int_to_words(n)
    parts = cardinal.rsplit(" ", 1)
    last = parts[-1]
    prefix = parts[0] + " " if len(parts) > 1 else ""
    if "-" in last:
        tens_part, ones_part = last.rsplit("-", 1)
        return prefix + tens_part + "-" + _ORDINAL_SPECIAL.get(ones_part, ones_part + "th")
    if last in _ORDINAL_SPECIAL:
        return prefix + _ORDINAL_SPECIAL[last]
    if last in _ORDINAL_TENS:
        return prefix + _ORDINAL_TENS[last]
    if last in ("hundred", "thousand", "million", "billion"):
        return prefix + last + "th"
    return prefix + last + "th"


ROMAN = r"[IVXL]+"
# "Part III", "Parts II & III", "Chapter IV" — roman numerals only after these words, so the
# pronoun "I" and initials are left alone.
NUMBERED = re.compile(
    rf"\b(Parts?|Chapters?|Books?|Sections?|Volumes?|Acts?)\s+({ROMAN}(?:\s*(?:&|and|,|-|–|to)\s*{ROMAN})*)\b"
)
# Any capitalised word before chapter:verse, for what scripture.py's table of books does not know ("Ephesians 1:18")
SCRIPTURE = re.compile(r"\b((?:[1-3] )?[A-Z][a-z]+) (\d{1,3}):(\d{1,3})(?:[-–](\d{1,3}))?\b")
DIGIT_COLON = re.compile(r"(\d):(\d)")
# Two or more all-caps words with at least one of 4+ letters ("THE JUDGMENT SEAT OF CHRIST"), or a
# single all-caps word of 5+ letters. Shorter single words are left: they're usually acronyms.
CAPS_RUN = re.compile(r"\b[A-Z]+(?:[\s,.'-]+[A-Z]+)+\b")
CAPS_WORD = re.compile(r"\b[A-Z]{5,}\b")
SMALL_WORDS = {"a", "an", "and", "as", "at", "but", "by", "for", "in", "of", "on", "or", "the", "to", "with"}
ORDINAL_NUM = re.compile(r"\b(\d+)(?:st|nd|rd|th)\b")
DECIMAL_NUM = re.compile(r"\b(\d{1,6})\.(\d+)\b")
YEAR_NUM = re.compile(r"(?<!\d)(1[1-9]\d{2}|20\d{2})(?!\d)")
COMMA_NUM = re.compile(r"\b(\d{1,3}(?:,\d{3})+)\b")
DIGITS = re.compile(r"(?<!\d\.)\b(\d{1,6})\b(?!\.\d)")
ELLIPSIS = re.compile(r"\s*(?:\.\s+){2,}\.|\s*…")
UNSPEAKABLE = re.compile(r"[~\[\]{}|^#*]")


def _title_case(words: str) -> str:
    out = []
    for i, w in enumerate(re.split(r"(\W+)", words)):
        low = w.lower()
        out.append(low if i and low in SMALL_WORDS else low.capitalize())
    return "".join(out)


def _numbered(m: re.Match) -> str:
    numbers = re.sub(ROMAN, lambda r: number_word(roman_to_int(r.group())), m.group(2))
    return f"{m.group(1)} {numbers}"


def _scripture(m: re.Match) -> str:
    book, chapter, verse, to = m.groups()
    return f"{book} chapter {chapter}, verses {verse} to {to}" if to else f"{book} chapter {chapter}, verse {verse}"


def _caps_run(m: re.Match) -> str:
    words = re.findall(r"[A-Z]+", m.group())
    return _title_case(m.group()) if len(words) >= 2 and max(map(len, words)) >= 4 else m.group()


def for_speech(text: str) -> str:
    text = text.replace("_", " ")  # first_hop_retrieve → first hop retrieve; before the caps rules
    text = NUMBERED.sub(_numbered, text)
    text = scripture.references(text)  # every Bible reference, whole (scripture.py); before the numbers are words
    text = scripture.verse_marks(text)
    text = scripture.chapter_lists(text)
    text = scripture.verse_lists(text)
    text = scripture.numbered_books(text)
    text = scripture.version_names(text)
    text = SCRIPTURE.sub(_scripture, text)
    text = DIGIT_COLON.sub(r"\1 \2", text)  # any other n:n (times, ratios): a colon cuts the sentence off
    text = ORDINAL_NUM.sub(lambda m: ordinal_to_words(int(m.group(1))), text)
    text = DECIMAL_NUM.sub(
        lambda m: int_to_words(int(m.group(1))) + " point " + " ".join(_DIGIT_WORDS[int(d)] for d in m.group(2)),
        text,
    )
    text = YEAR_NUM.sub(lambda m: year_to_words(int(m.group(1))), text)
    text = COMMA_NUM.sub(lambda m: int_to_words(int(m.group(1).replace(",", ""))), text)
    text = DIGITS.sub(lambda m: int_to_words(int(m.group(1))), text)
    text = CAPS_RUN.sub(_caps_run, text)
    text = CAPS_WORD.sub(lambda m: m.group().capitalize(), text)
    text = ELLIPSIS.sub("...", text)
    text = text.replace("&", "and")
    text = UNSPEAKABLE.sub("", text)
    return re.sub(r"\s{2,}", " ", text).strip()


# --- Per-book corrections: typos in the source text that no general rule can know about ---------


def parse_corrections(text: str) -> list[tuple[str, str]]:
    """Lines of `find => replace`; blank lines and # comments ignored. A line with nothing to find
    is ignored too: replacing "" would put the replacement between every character of the book."""
    pairs = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=>" in line:
            find, _, replace = line.partition("=>")
            if find.strip():
                pairs.append((find.strip(), replace.strip()))
    return pairs


def apply_corrections(text: str, corrections: list[tuple[str, str]]) -> str:
    for find, replace in corrections:
        text = text.replace(find, replace)
    return text
