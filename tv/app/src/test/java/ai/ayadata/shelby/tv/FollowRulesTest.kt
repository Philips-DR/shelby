package ai.ayadata.shelby.tv

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.abs
import kotlin.math.roundToLong

/**
 * The web app's own cases (web/src/components/audiobookSentences.test.ts and audiobookGlide.test.ts), ported one for
 * one: the web code's behaviour is the spec. Then the pieces it does not test on their own (the active paragraph, the
 * leading announcement, skipping by paragraph) and the whitespace its split uses.
 */
class FollowRulesTest {
    private fun chunk(start: Double, end: Double, words: Int? = null, text: String? = null, sentences: List<SentenceTiming>? = null) =
        ChunkTiming(start, end, text, words, sentences)

    // ---- wordsByChunk ----

    private val sample = wordsOf("One two three.  Four five\nsix seven.")

    @Test fun `words split at any whitespace`() {
        assertEquals(listOf("One", "two", "three.", "Four", "five", "six", "seven."), sample)
    }

    @Test fun `words are shared out by each chunk's word count, in order`() {
        val chunks = listOf(chunk(0.0, 1.0, words = 3), chunk(2.0, 3.0, words = 4))
        assertEquals(listOf(listOf("One", "two", "three."), listOf("Four", "five", "six", "seven.")), wordsByChunk(sample, chunks))
    }

    @Test fun `a chunk's own text is counted when it has it, whatever its count says`() {
        val chunks = listOf(chunk(0.0, 1.0, text = "One two three."), chunk(2.0, 3.0, text = "Four five six seven."))
        assertEquals(listOf(3, 4), wordsByChunk(sample, chunks)?.map { it.size })
    }

    @Test fun `no sharing when a count is missing or the counts do not add up to the paragraph`() {
        assertNull(wordsByChunk(sample, listOf(chunk(0.0, 1.0), chunk(2.0, 3.0, words = 4))))
        assertNull(wordsByChunk(sample, listOf(chunk(0.0, 1.0, words = 3), chunk(2.0, 3.0, words = 3))))
        assertNull(wordsByChunk(sample, listOf(chunk(0.0, 1.0, words = 9))))
    }

    // ---- unitsFor ----

    // 12 words: sentences of 3, 2, 4 and 3; the chunks are the first two sentences (5 words) and the last two (7)
    private val twelve = wordsOf("A b c. D e. F g h i. J k l.")

    @Test fun `a chunk is cut by its sentences, each running to the next one's start and the last to the chunk's end`() {
        val chunks = listOf(
            chunk(10.0, 20.0, words = 5, sentences = listOf(SentenceTiming(3, 10.0), SentenceTiming(2, 16.5))),
            chunk(21.0, 30.0, words = 7, sentences = listOf(SentenceTiming(4, 21.0), SentenceTiming(3, 27.0))),
        )
        assertEquals(
            listOf(SpokenUnit(0, 3, 10.0, 16.5), SpokenUnit(3, 5, 16.5, 20.0), SpokenUnit(5, 9, 21.0, 27.0), SpokenUnit(9, 12, 27.0, 30.0)),
            unitsFor(twelve, chunks),
        )
    }

    @Test fun `the first sentence of a chunk starts when the chunk does, whatever start it carries itself`() {
        // the render's guess for a first sentence can differ a little from where its chunk starts; the chunk's is the one the audio has
        val chunks = listOf(chunk(10.0, 20.0, words = 5, sentences = listOf(SentenceTiming(3, 10.3), SentenceTiming(2, 16.5))))
        assertEquals(listOf(SpokenUnit(0, 3, 10.0, 16.5), SpokenUnit(3, 5, 16.5, 20.0)), unitsFor(twelve.take(5), chunks))
    }

    @Test fun `a chunk with no sentences is cut by chunk (a chapter rendered before they were found)`() {
        val chunks = listOf(chunk(0.0, 5.0, words = 5), chunk(6.0, 12.0, words = 7))
        assertEquals(listOf(SpokenUnit(0, 5, 0.0, 5.0), SpokenUnit(5, 12, 6.0, 12.0)), unitsFor(twelve, chunks))
    }

    @Test fun `sentences where a chunk has them, the chunk where it does not`() {
        val chunks = listOf(
            chunk(0.0, 5.0, words = 5, sentences = listOf(SentenceTiming(3, 0.0), SentenceTiming(2, 2.5))),
            chunk(6.0, 12.0, words = 7),
        )
        assertEquals(listOf(0 to 3, 3 to 5, 5 to 12), unitsFor(twelve, chunks)?.map { it.first to it.last })
    }

    @Test fun `sentences whose words do not add up to their chunk are ignored`() {
        val chunks = listOf(chunk(0.0, 12.0, words = 12, sentences = listOf(SentenceTiming(3, 0.0), SentenceTiming(2, 5.0))))
        assertEquals(listOf(SpokenUnit(0, 12, 0.0, 12.0)), unitsFor(twelve, chunks))
    }

    @Test fun `no units when the words cannot be shared out among the chunks`() {
        assertNull(unitsFor(twelve, listOf(chunk(0.0, 5.0))))
        assertNull(unitsFor(twelve, listOf(chunk(0.0, 5.0, words = 4))))
    }

    // ---- unitAt ----

    private val units = listOf(SpokenUnit(0, 3, 2.0, 4.0), SpokenUnit(3, 5, 4.5, 6.0), SpokenUnit(5, 9, 8.0, 12.0))

    @Test fun `before the first unit is -1, and after the end is the last unit`() {
        assertEquals(-1, unitAt(units, 1.9))
        assertEquals(2, unitAt(units, 99.0))
    }

    @Test fun `a unit is found on its first instant, and held through the rest after it`() {
        assertEquals(0, unitAt(units, 2.0))
        assertEquals(0, unitAt(units, 4.4))     // the rest between the first and second: still the first
        assertEquals(1, unitAt(units, 4.5))
        assertEquals(1, unitAt(units, 7.0))
        assertEquals(2, unitAt(units, 8.0))
    }

    @Test fun `no units gives -1`() {
        assertEquals(-1, unitAt(emptyList(), 1.0))
    }

    // ---- the glide ----

    /** Run a glide the way the view does, on a screen whose scroll position is whole pixels, with a frame every `frameMs`. */
    private fun glide(gap: Double, frameMs: Double): Pair<Int, Double>? {
        var top = 0.0
        var ms = 0.0
        var frames = 0
        while (ms < 60_000) {
            val diff = gap - top
            if (abs(diff) < ARRIVED) return frames to ms
            top = (top + glideBy(diff, frameMs)).roundToLong().toDouble()   // the screen keeps whole pixels
            ms += frameMs
            frames += 1
        }
        return null
    }

    @Test fun `it closes a fifth of the way in one 60 Hz frame`() {
        assertEquals(0.2, glideBy(1000.0, 1000.0 / 60) / 1000, 0.005)
    }

    @Test fun `it goes as far in two short steps as in one long one`() {
        val one = glideBy(1000.0, 40.0)
        val first = glideBy(1000.0, 20.0)
        val second = glideBy(1000.0 - first, 20.0)
        assertEquals(one, first + second, 5e-7)
    }

    @Test fun `it goes the way of the gap, up or down`() {
        assertTrue(glideBy(500.0, 16.0) > 0)
        assertTrue(glideBy(-500.0, 16.0) < 0)
    }

    @Test fun `it catches up after a long frame instead of crawling`() {
        assertTrue(glideBy(1000.0, 1000.0) > 999)
    }

    @Test fun `it never takes a step the screen would round away`() {
        assertEquals(1.0, glideBy(3.0, 16.0), 0.0)
        assertEquals(-1.0, glideBy(-3.0, 16.0), 0.0)
        assertEquals(1.0, glideBy(1.5, 1.0), 0.0)
    }

    @Test fun `the glide ends, by the clock and not the frame`() {
        for (gap in listOf(1.0, 2.0, 3.0, 7.0, 50.0, 333.0, 4000.0, 25_000.0)) {
            val fast = glide(gap, 1000.0 / 60)
            val slow = glide(gap, 200.0)
            assertNotNull("no arrival across $gap px at 60 Hz", fast)
            assertNotNull("no arrival across $gap px at 5 Hz", slow)
            assertTrue("$gap px: 5 Hz took ${slow!!.second} ms, 60 Hz ${fast!!.second} ms", slow.second <= fast.second + 400)
            assertTrue("$gap px took ${fast.second} ms", fast.second < GLIDE_MS * 14)
        }
    }

    // ---- the pieces the web app does not test on their own ----

    private fun seg(kind: String, start: Double, end: Double) = SegmentTiming(kind, start, end, emptyList())

    @Test fun `the announcement spoken first is not one of the text's paragraphs`() {
        val all = listOf(seg("announcement", 0.0, 2.0), seg("paragraph", 2.6, 5.0), seg("heading", 5.5, 7.0))
        assertEquals(listOf("paragraph", "heading"), spokenSegments(all).map { it.kind })
        assertTrue(spokenSegments(listOf(seg("announcement", 0.0, 2.0))).isEmpty())
        assertEquals(2, spokenSegments(listOf(seg("paragraph", 0.0, 1.0), seg("paragraph", 2.0, 3.0))).size)
    }

    @Test fun `the active paragraph is the one whose time it is, else the one just passed`() {
        val segs = listOf(seg("paragraph", 2.0, 4.0), seg("paragraph", 5.0, 8.0), seg("paragraph", 9.0, 12.0))
        assertEquals(-1, activeSegment(segs, 1.0))
        assertEquals(0, activeSegment(segs, 2.0))
        assertEquals(0, activeSegment(segs, 4.0))
        assertEquals(0, activeSegment(segs, 4.5))      // the silence between the first and second
        assertEquals(1, activeSegment(segs, 5.0))
        assertEquals(2, activeSegment(segs, 99.0))     // after the end: the last
        assertEquals(-1, activeSegment(emptyList(), 1.0))
    }

    @Test fun `previous goes to the start of this paragraph when it began a while ago, else to the one before`() {
        val segs = listOf(seg("paragraph", 2.0, 4.0), seg("paragraph", 5.0, 8.0), seg("paragraph", 9.0, 12.0))
        assertEquals(5.0, previousStart(segs, 1, 7.5)!!, 0.0)    // 2.5 s in: restart it
        assertEquals(2.0, previousStart(segs, 1, 6.5)!!, 0.0)    // 1.5 s in: the one before
        assertEquals(2.0, previousStart(segs, 0, 1.0)!!, 0.0)    // already the first: stay at the first
        assertEquals(2.0, previousStart(segs, -1, 0.0)!!, 0.0)   // before the first: the first
        assertNull(previousStart(emptyList(), 0, 0.0))
    }

    @Test fun `next goes to the following paragraph, and the last stays`() {
        val segs = listOf(seg("paragraph", 2.0, 4.0), seg("paragraph", 5.0, 8.0), seg("paragraph", 9.0, 12.0))
        assertEquals(5.0, nextStart(segs, 0)!!, 0.0)
        assertEquals(9.0, nextStart(segs, 1)!!, 0.0)
        assertEquals(9.0, nextStart(segs, 2)!!, 0.0)
        assertEquals(2.0, nextStart(segs, -1)!!, 0.0)
        assertNull(nextStart(emptyList(), 0))
    }

    @Test fun `a paragraph's sentences are laid out as one text with a range for each`() {
        val words = wordsOf("A b c. D e. F g h i.")
        val units = listOf(SpokenUnit(0, 3, 0.0, 1.0), SpokenUnit(3, 5, 1.0, 2.0), SpokenUnit(5, 9, 2.0, 3.0))
        val (text, ranges) = unitRanges(words, units)
        assertEquals("A b c. D e. F g h i.", text)
        assertEquals(listOf("A b c.", "D e.", "F g h i."), ranges.map { text.substring(it.first, it.last + 1) })
        // a paragraph cut a different way is still one text, joined with single spaces
        val (text2, ranges2) = unitRanges(wordsOf("One   two\nthree"), listOf(SpokenUnit(0, 3, 0.0, 1.0)))
        assertEquals("One two three", text2)
        assertEquals(listOf(0..12), ranges2)
    }

    @Test fun `words split at the whitespace the web app splits at, not only at the plain kinds`() {
        assertEquals(listOf("a", "b"), wordsOf("a b"))            // a non-breaking space
        assertEquals(listOf("a", "b"), wordsOf("a b"))            // a thin space
        assertEquals(listOf("a", "b"), wordsOf("a﻿b"))            // a zero-width no-break space, which JavaScript counts
        assertEquals(listOf("a", "b"), wordsOf("  a \t\n b\r\n "))     // and no empty words at the ends
        assertEquals(emptyList<String>(), wordsOf("   "))
    }
}
