"""Put back the dashes the PDF reader turned into hyphens.

Docling's PDF parser hands over every em and en dash as a control character, and Docling writes that as "-". Inside a
line it reads "overcome-particularly": one hyphenated word, with no pause. At the end of a line the hyphen looks like
a word split across two lines, so Docling closes the gap: "inspiration—" / "especially" became "inspirationespecially",
and "1843–" / "4" became "18434". Dashes that begin a line become "word -word". In six real books (1,571 pages) that was
about 1,500 places, 87 of 88 line-end dashes among them (2026-11-13).

The PDF's own text layer still has the real characters. This reads them back, page by page, as word pairs: which two
words had a dash between them, and in which of the three shapes. Docling's text is then repaired only where a pair
matches, so a real hyphen ("well-known") is never touched and nothing is guessed.

An em dash is put back as an em dash: the voice pauses at one for about half a second and makes no odd sound (heard with
the real voice and read back with Whisper). An en dash only has its gap put back, as a hyphen, so number ranges and
scripture references ("Ephesians 1:18-20") read as they always did."""

import re
from dataclasses import dataclass, field

EM = "—"
_DASHES = "—–"
_HYPHENS = "-‐‑­￾"     # what a real hyphen can be in the PDF's text (￾: one pdfium inserts at a wrap)

# The PDF's text: a word, a dash, a word. Each pattern is a lookahead from a word's start, so "a—b—c" gives both pairs.
_IN_LINE = re.compile(rf"(?<!\w)(?=(\w+)([{_DASHES}])(\w+)(?!\w))")
_LINE_END = re.compile(rf"(?<!\w)(?=(\w+)([{_DASHES}])\r?\n(\w+)(?!\w))")
_LINE_START = re.compile(rf"(?<!\w)(?=(\w+)\r?\n([{_DASHES}])(\w+)(?!\w))")
_HYPHEN_IN_LINE = re.compile(rf"(?<!\w)(?=(\w+)[{_HYPHENS}](\w+)(?!\w))")
_HYPHEN_LINE_END = re.compile(rf"(?<!\w)(?=(\w+)[{_HYPHENS}]\r?\n(\w+)(?!\w))")
_HYPHEN_LINE_START = re.compile(rf"(?<!\w)(?=(\w+)\r?\n[{_HYPHENS}](\w+)(?!\w))")

# Docling's text.
_HYPHENATED = re.compile(r"(?<!\w)(?=(\w+)-(\w+)(?!\w))")
_SPACE_HYPHEN = re.compile(r"(?<!\w)(\w+) -(\w+)(?!\w)")
_WORD = re.compile(r"\w+")


def _mark(dash: str) -> str:
    """What a dash is put back as: an em dash as itself, an en dash as the hyphen it already was."""
    return EM if dash == EM else "-"


@dataclass
class Dashes:
    """The word pairs one or more pages of the PDF have a dash between."""

    inline: set[tuple[str, str]] = field(default_factory=set)            # em dash inside a line: "a—b"
    split: dict[str, tuple[str, str, str]] = field(default_factory=dict)  # "ab" → (a, mark, b): "a—" at a line's end, "b" next
    lead: dict[tuple[str, str], str] = field(default_factory=dict)       # (a, b) → mark: "a" ends a line, "—b" starts the next
    hyphens: set[tuple[str, str]] = field(default_factory=set)           # pairs the PDF joins with a real hyphen
    _clash: set = field(default_factory=set, repr=False)                 # keys two different readings wanted

    def __bool__(self) -> bool:
        return bool(self.inline or self.split or self.lead)

    def _put_split(self, a: str, mark: str, b: str) -> None:
        key = a + b
        if key in self.split and self.split[key] != (a, mark, b):
            self._clash.add(key)
        self.split[key] = (a, mark, b)

    def _put_lead(self, a: str, b: str, mark: str) -> None:
        if (a, b) in self.lead and self.lead[(a, b)] != mark:
            self._clash.add((a, b))
        self.lead[(a, b)] = mark

    def settle(self) -> "Dashes":
        """Drop what two readings disagreed about: with nothing to choose by, nothing is changed."""
        for key in self._clash:
            if isinstance(key, str):
                self.split.pop(key, None)
            else:
                self.lead.pop(key, None)
        self._clash.clear()
        return self

    def merge(self, other: "Dashes") -> "Dashes":
        out = Dashes(set(self.inline), dict(self.split), dict(self.lead), set(self.hyphens), set(self._clash))
        out.inline |= other.inline
        out.hyphens |= other.hyphens
        for key, (a, mark, b) in other.split.items():
            out._put_split(a, mark, b)
        for (a, b), mark in other.lead.items():
            out._put_lead(a, b, mark)
        out._clash |= other._clash
        return out.settle()

    def to_json(self) -> dict:
        return {"inline": sorted(map(list, self.inline)), "split": sorted([a, m, b] for a, m, b in self.split.values()),
                "lead": sorted([a, b, m] for (a, b), m in self.lead.items()), "hyphens": sorted(map(list, self.hyphens))}

    @staticmethod
    def from_json(data: dict) -> "Dashes":
        out = Dashes({tuple(p) for p in data["inline"]}, {a + b: (a, m, b) for a, m, b in data["split"]},
                     {(a, b): m for a, b, m in data["lead"]}, {tuple(p) for p in data["hyphens"]})
        return out


def read(page_text: str) -> Dashes:
    """The dashes on one page of the PDF's own text."""
    found = Dashes()
    for m in _IN_LINE.finditer(page_text):
        a, dash, b = m.groups()
        if dash == EM:                                    # an en dash inside a line already reads as a hyphen
            found.inline.add((a, b))
    for m in _LINE_END.finditer(page_text):
        a, dash, b = m.groups()
        found._put_split(a, _mark(dash), b)
    for m in _LINE_START.finditer(page_text):
        a, dash, b = m.groups()
        found._put_lead(a, b, _mark(dash))
    for pattern in (_HYPHEN_IN_LINE, _HYPHEN_LINE_END, _HYPHEN_LINE_START):
        for m in pattern.finditer(page_text):
            found.hyphens.add(m.groups())
    return found.settle()


def restore(text: str, dashes: Dashes) -> str:
    """Docling's text with the dashes put back where the PDF has them. Text with none of them is returned as it came."""
    if not dashes:
        return text
    if dashes.split:                                      # "inspirationespecially" → "inspiration—especially"
        def reopen(m: re.Match) -> str:
            hit = dashes.split.get(m.group())
            return f"{hit[0]}{hit[1]}{hit[2]}" if hit else m.group()
        text = _WORD.sub(reopen, text)
    if dashes.inline:                                     # "overcome-particularly" → "overcome—particularly"
        at = [m.start() + len(m.group(1)) for m in _HYPHENATED.finditer(text)
              if (m.group(1), m.group(2)) in dashes.inline and (m.group(1), m.group(2)) not in dashes.hyphens]
        if at:
            chars = list(text)
            for i in at:
                chars[i] = EM
            text = "".join(chars)
    if dashes.lead:                                       # "word -word" → "word—word"
        def close(m: re.Match) -> str:
            mark = dashes.lead.get((m.group(1), m.group(2)))
            return f"{m.group(1)}{mark}{m.group(2)}" if mark and (m.group(1), m.group(2)) not in dashes.hyphens else m.group()
        text = _SPACE_HYPHEN.sub(close, text)
    return text
