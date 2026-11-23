package ai.ayadata.shelby.tv

import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.sign

/*
 * Which words are being spoken at a given moment, for follow-along. A COPY, in Kotlin, of the web app's rules:
 * web/src/components/audiobookSentences.ts (unitsFor, unitAt, wordsOf, wordsByChunk), audiobookTiming.ts
 * (spokenSegments, activeSegment), audiobookGlide.ts (glideBy) and the paragraph skip in AudioFollow.tsx. The two
 * must agree: a change there is a change here (CLAUDE.md), and the tests run the web code's answers on real chapters
 * (FollowFixtureTest). Pure Kotlin on purpose, so it is tested on a plain JVM.
 *
 * What the render knows (audiobook/render.py): for each paragraph a start and end time, and inside it "chunks" of a
 * few sentences, each with its word count and, since 2026-11-13, where each of its sentences starts (a guess from the
 * text moved to the nearest pause in the audio, so a sentence start can be a few tenths of a second out). Nothing
 * here invents a time: what is not known is not split.
 */

/** Where one sentence of a chunk starts, and how many words it has. */
data class SentenceTiming(val words: Int, val start: Double)

/** `text` is there in the sidecar file; `words` (a count) in the kept record's compact form, which has no text. */
data class ChunkTiming(
    val start: Double,
    val end: Double,
    val text: String? = null,
    val words: Int? = null,
    val sentences: List<SentenceTiming>? = null,
)

/** One paragraph's timing: `kind` is "paragraph", "heading", "list_item" or "announcement". */
data class SegmentTiming(val kind: String, val start: Double, val end: Double, val chunks: List<ChunkTiming>)

/** Words [first, last) of a paragraph are spoken from `start` to `end`, in playback seconds. */
data class SpokenUnit(val first: Int, val last: Int, val start: Double, val end: Double)

/** JavaScript's whitespace (what the web app splits on), written out: Kotlin's own `\s` is narrower. */
private val WHITESPACE = Regex("[\\t\\n\\u000B\\f\\r \\u00A0\\u1680\\u2000-\\u200A\\u2028\\u2029\\u202F\\u205F\\u3000\\uFEFF]+")

/** The words of a paragraph, split at whitespace: the same split the render's chunks keep. */
fun wordsOf(text: String): List<String> = text.split(WHITESPACE).filter { it.isNotEmpty() }

/**
 * Share a paragraph's words out among its chunks, in order, by how many words each chunk had. Null when a chunk's
 * count is missing or the counts do not add up to the paragraph's words (the text was corrected after the render, or
 * the timing is from before the counts were kept): the paragraph is then shown whole.
 */
fun wordsByChunk(words: List<String>, chunks: List<ChunkTiming>): List<List<String>>? {
    val counts = chunks.map { c -> if (c.text != null) wordsOf(c.text).size else c.words }
    if (counts.any { it == null || it < 0 }) return null
    if (counts.sumOf { it!! } != words.size) return null
    val shared = ArrayList<List<String>>(counts.size)
    var at = 0
    for (n in counts) {
        shared += words.subList(at, at + n!!)
        at += n
    }
    return shared
}

/**
 * The paragraph cut where the render knows it was spoken: by sentence where a chunk has its sentences, else by
 * chunk. Null when the words cannot be shared out among the chunks at all.
 */
fun unitsFor(words: List<String>, chunks: List<ChunkTiming>): List<SpokenUnit>? {
    val shared = wordsByChunk(words, chunks) ?: return null
    val units = ArrayList<SpokenUnit>()
    var at = 0
    chunks.forEachIndexed { i, chunk ->
        val n = shared[i].size
        val sentences = chunk.sentences
        if (!sentences.isNullOrEmpty() && sentences.sumOf { it.words } == n) {
            var first = at
            sentences.forEachIndexed { k, s ->
                val end = if (k + 1 < sentences.size) sentences[k + 1].start else chunk.end
                if (s.words > 0) units += SpokenUnit(first, first + s.words, if (k == 0) chunk.start else s.start, end)
                first += s.words
            }
        } else if (n > 0) {
            units += SpokenUnit(at, at + n, chunk.start, chunk.end)
        }
        at += n
    }
    return units
}

/** The unit being spoken at `time`: the last whose start has passed (so a rest between two stays with the one before). -1 before the first. */
fun unitAt(units: List<SpokenUnit>, time: Double): Int {
    var low = 0
    var high = units.size - 1
    var found = -1
    while (low <= high) {
        val mid = (low + high) ushr 1
        if (units[mid].start <= time) { found = mid; low = mid + 1 } else high = mid - 1
    }
    return found
}

/** The timing entries for the chapter's text: the announcement ("Chapter 6.", the title) is spoken first and is not among the text's paragraphs, so the rest line up with them by index. */
fun spokenSegments(timing: List<SegmentTiming>): List<SegmentTiming> {
    val first = timing.indexOfFirst { it.kind != "announcement" }
    return if (first < 0) emptyList() else timing.subList(first, timing.size)
}

/** The paragraph whose time bracket contains `time`, or the one just passed when it falls in a silence between two, or -1. */
fun activeSegment(timing: List<SegmentTiming>, time: Double): Int {
    for (i in timing.indices) if (time >= timing[i].start && time <= timing[i].end) return i
    for (i in timing.indices.reversed()) if (time > timing[i].end) return i
    return -1
}

/**
 * Can this chapter be followed: the text has one paragraph for each of the timing's, in step. The paragraphs are
 * matched to the timing by position, so if the text was changed after the render (a correction, a different reading
 * of the book) they cannot be, and the screen says so instead of lighting the wrong words. As the web view does.
 */
fun isAligned(textParagraphs: Int, segs: List<SegmentTiming>): Boolean = segs.isNotEmpty() && textParagraphs == segs.size

/**
 * A paragraph set out as its units for drawing: the text (each unit's words joined by single spaces, the units joined
 * by one space, as the web view's spans are) and where each unit sits in it, as a range of characters. Kept apart
 * from the screen so it can be tested.
 */
fun unitRanges(words: List<String>, units: List<SpokenUnit>): Pair<String, List<IntRange>> {
    val text = StringBuilder()
    val ranges = ArrayList<IntRange>(units.size)
    units.forEachIndexed { i, u ->
        if (i > 0) text.append(' ')
        val from = text.length
        text.append(words.subList(u.first, u.last).joinToString(" "))
        ranges += from until text.length
    }
    return text.toString() to ranges
}

// ---- the text's glide to the line being read ----------------------------------------------------------------

/** The time constant of the glide, in milliseconds: 1/60 s over -ln(0.8), the 20% a frame it replaced (web). */
const val GLIDE_MS = 75.0
/** A gap this small is closed at once: the text is there. */
const val ARRIVED = 1.0

/** How far to move now, along a gap of `diff` pixels, after `ms` milliseconds since the last step: a share of the gap, never less than a whole pixel (it would be lost to rounding), and in the direction of the gap. */
fun glideBy(diff: Double, ms: Double): Double {
    val move = diff * (1 - exp(-ms / GLIDE_MS))
    return if (abs(move) < 1) sign(diff) else move
}

// ---- skipping by paragraph (the web view's previous and next) ------------------------------------------------

/** A paragraph is restarted rather than skipped back from when this far into it, in seconds (web: RESTART_AFTER). */
const val RESTART_AFTER = 2.0

/** Where Previous goes: the start of the paragraph being read if it began more than [RESTART_AFTER] ago, else the one before. Null with no paragraphs. */
fun previousStart(segs: List<SegmentTiming>, active: Int, time: Double): Double? {
    if (segs.isEmpty()) return null
    val seg = segs.getOrNull(active)
    val to = if (seg != null && time - seg.start > RESTART_AFTER) active else active - 1
    return segs[to.coerceIn(0, segs.lastIndex)].start
}

/** Where Next goes: the start of the following paragraph (the last paragraph stays where it is). Null with no paragraphs. */
fun nextStart(segs: List<SegmentTiming>, active: Int): Double? {
    if (segs.isEmpty()) return null
    return segs[(active + 1).coerceIn(0, segs.lastIndex)].start
}
