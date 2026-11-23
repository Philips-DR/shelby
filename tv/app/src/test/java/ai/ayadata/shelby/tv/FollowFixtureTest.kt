package ai.ayadata.shelby.tv

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Real chapters, against the web app's own answers (src/test/resources/follow). Each fixture holds the timing Shelby kept,
 * how many words each paragraph has (the cut depends on nothing else, so the copyrighted text is not kept), and what the
 * web app's code (audiobookSentences.ts, audiobookTiming.ts) said about it: every paragraph's cut, and the active
 * paragraph and sentence every half second. This port must say the same.
 */
class FollowFixtureTest {
    private fun fixture(name: String): JSONObject =
        JSONObject(javaClass.getResourceAsStream("/follow/$name.json")!!.bufferedReader().readText())

    private fun check(name: String) {
        val f = fixture(name)
        val segs = spokenSegments(parseTiming(f.getJSONArray("timing")))
        val counts = f.getJSONArray("wordCounts")
        assertTrue(name, isAligned(counts.length(), segs))
        // a paragraph of the right number of words: the cut depends on how many, not on which
        val units = (0 until counts.length()).map { i -> unitsFor(List(counts.getInt(i)) { "w" }, segs[i].chunks) }
        val expected = f.getJSONArray("units")
        for (i in units.indices) {
            if (expected.isNull(i)) { assertNull("$name paragraph $i is shown whole", units[i]); continue }
            val want = expected.getJSONArray(i)
            val got = units[i]!!
            assertEquals("$name paragraph $i: units", want.length(), got.size)
            for (k in 0 until want.length()) {
                val e = want.getJSONObject(k)
                assertEquals(e.getInt("first"), got[k].first)
                assertEquals(e.getInt("last"), got[k].last)
                assertEquals(e.getDouble("start"), got[k].start, 0.0)
                assertEquals(e.getDouble("end"), got[k].end, 0.0)
            }
        }
        val step = f.getDouble("step")
        val segAt = f.getJSONArray("segAt"); val unitIdx = f.getJSONArray("unitIdx")
        for (k in 0 until segAt.length()) {
            val t = k * step
            val a = activeSegment(segs, t)
            assertEquals("$name at $t s: active paragraph", segAt.getInt(k), a)
            val u = if (a >= 0 && units[a] != null) unitAt(units[a]!!, t) else -2
            assertEquals("$name at $t s: active sentence", unitIdx.getInt(k), u)
        }
    }

    @Test fun `a chapter cut into sentences throughout (31 paragraphs)`() = check("myles365_ch4")

    @Test fun `a chapter where some paragraphs can only be shown whole`() = check("overcoming_ch2")

    @Test fun `a chapter of two very long paragraphs`() = check("great_expectations_ch3")

    @Test fun `the paragraphs shown whole are the ones whose counts do not add up`() {
        val f = fixture("overcoming_ch2")
        assertEquals(4, (0 until f.getJSONArray("units").length()).count { f.getJSONArray("units").isNull(it) })
    }

    @Test fun `a chapter whose text has one paragraph more than the timing cannot be followed`() {
        // Real: "When Godly People Do Ungodly Things" chapter 71, 2026-11-22: 96 timed paragraphs, 97 in the text now.
        val segs = List(96) { SegmentTiming("paragraph", it * 10.0, it * 10.0 + 9, emptyList()) }
        assertFalse(isAligned(97, segs))
        assertTrue(isAligned(96, segs))
        assertFalse(isAligned(0, emptyList()))
    }

    @Test fun `timing is read from the record's compact form`() {
        val timing = parseTiming(JSONArray("""[
            {"kind":"announcement","start":0,"end":1.5,"chunks":[{"start":0,"end":1.5,"words":2}]},
            {"kind":"paragraph","start":2.0,"end":9.0,"chunks":[
                {"start":2.0,"end":5.0,"words":5,"sentences":[{"words":3,"start":2.0},{"words":2,"start":3.5}]},
                {"start":6.0,"end":9.0,"words":4}]}]"""))
        assertEquals(listOf("announcement", "paragraph"), timing.map { it.kind })
        val chunks = timing[1].chunks
        assertEquals(listOf(SentenceTiming(3, 2.0), SentenceTiming(2, 3.5)), chunks[0].sentences)
        assertNull(chunks[1].sentences)
        assertNull(chunks[1].text)
        assertEquals(4, chunks[1].words)
    }
}
