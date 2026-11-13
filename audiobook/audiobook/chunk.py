"""Split paragraphs into sentence-aligned chunks for synthesis."""

import re

# Keep chunks short enough for steady progress and cheap re-renders, but never split a sentence.
MAX_CHUNK_CHARS = 400

# A sentence ends at . ! ? or …, together with any closing quote or bracket that belongs to it, when a capital or a
# digit (after an opening quote or bracket, if any) starts the next one. The closers stay with the sentence they close:
# when the split used them up, a closing quote or bracket after a full stop was lost before the voice ever heard it
# (843 of 6,232 real paragraphs, 2026-11-13).
CLOSING = "\"'”’)]"
SENTENCE_END = re.compile(rf"[.!?…][{re.escape(CLOSING)}]*(?=\s+[\"'“‘(\[]?[A-Z0-9])")
ABBREVIATIONS = ("Mr.", "Mrs.", "Ms.", "Dr.", "St.", "Prof.", "Sr.", "Jr.", "vs.", "etc.", "e.g.", "i.e.", "No.")


def split_sentences(paragraph: str) -> list[str]:
    sentences: list[str] = []
    start = 0
    for end in [m.end() for m in SENTENCE_END.finditer(paragraph)] + [len(paragraph)]:
        part = paragraph[start:end].strip()
        start = end
        if not part:
            continue
        # Re-join splits that happened after an abbreviation such as "Mr." (or "Dr.)")
        if sentences and sentences[-1].rstrip(CLOSING).endswith(ABBREVIATIONS):
            sentences[-1] += " " + part
        else:
            sentences.append(part)
    return sentences


def chunk_paragraph(paragraph: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    chunks: list[str] = []
    current = ""
    for sentence in split_sentences(paragraph):
        if current and len(current) + 1 + len(sentence) > max_chars:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current)
    return chunks
