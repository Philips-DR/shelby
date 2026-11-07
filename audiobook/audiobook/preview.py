"""BookPlan → preview.md: the exact text the narrator will read, and what was left out. Pure."""

from collections import defaultdict

from .plan import BookPlan, Chapter

# Measured with Pocket TTS and the abigail voice: ~16 characters of text per second of speech.
CHARS_PER_SECOND = 16
# x real time, on this laptop with the 8-bit model: a whole chapter took 2.18x one piece at a time and 2.36x two at a
# time, with the laptop busy (the full model was 1.4x). A render measures its own rate after its first 500 characters.
RENDER_SPEED = 2.0
EXAMPLES_PER_REASON = 3


def speech_seconds(chars: int) -> float:
    return chars / CHARS_PER_SECOND


def format_duration(seconds: float) -> str:
    minutes = round(seconds / 60)
    if minutes < 60:
        return f"{max(minutes, 1)} min"
    return f"{minutes // 60} h {minutes % 60:02d} min"


def chapter_label(index: int, chapter: Chapter) -> str:
    number = f"{chapter.number}. " if chapter.number else ""
    return f"{number}{chapter.title}"


def _skipped_summary(chapter: Chapter) -> list[str]:
    by_reason = defaultdict(list)
    for s in chapter.skipped:
        by_reason[s.reason].append(s)
    lines = []
    if chapter.citations_removed:
        lines.append(f"- **{chapter.citations_removed} citations** removed from the text")
    for reason, items in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"- **{len(items)} × {reason}**")
        for s in items[:EXAMPLES_PER_REASON]:
            where = f"p{s.page}" if s.page else "?"
            snippet = (s.text[:90] + "…") if len(s.text) > 90 else s.text
            lines.append(f"  - {where}: {snippet or '(no text)'}")
        if len(items) > EXAMPLES_PER_REASON:
            lines.append(f"  - … and {len(items) - EXAMPLES_PER_REASON} more")
    return lines


def render_preview(plan: BookPlan, source: str) -> str:
    total = sum(c.spoken_chars for c in plan.chapters)
    speech = speech_seconds(total)
    out = [
        f"# {plan.title}",
        "",
        *([f"By {plan.author}", ""] if plan.author else []),
        f"Source: `{source}`  ",
        f"{len(plan.chapters)} chapters · ~{format_duration(speech)} of speech · "
        f"~{format_duration(speech / RENDER_SPEED)} to render on this machine",
        "",
        "| # | Chapter | Words | Speech | |",
        "|---|---|---|---|---|",
    ]
    for i, c in enumerate(plan.chapters, 1):
        words = sum(len(s.text.split()) for s in c.segments)
        note = "appendix" if c.appendix else ""
        out.append(f"| {i} | {chapter_label(i, c)} | {words:,} | {format_duration(speech_seconds(c.spoken_chars))} | {note} |")
    out += [
        "",
        "Everything below is the exact text that will be read aloud. The `#` column is what "
        "`--chapters` selects.",
    ]

    for i, c in enumerate(plan.chapters, 1):
        out += ["", "---", "", f"## [{i}] {chapter_label(i, c)}" + (" *(appendix)*" if c.appendix else ""), ""]
        out.append(f"*Announced: “{c.announce or c.title}”*")
        for seg in c.segments:
            out.append("")
            if seg.kind == "title":
                out.append(f"**{seg.text}**")
            elif seg.kind == "heading":
                out.append(f"### {seg.text}")
            elif seg.kind == "list_item":
                out.append(f"- {seg.text}")
            else:
                out.append(seg.text)
        summary = _skipped_summary(c)
        if summary:
            out += ["", "<details><summary>Not read aloud in this chapter</summary>", "", *summary, "", "</details>"]
    return "\n".join(out) + "\n"
