package ai.ayadata.shelby.tv

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Real data: the 35 chapter files Shelby kept for "Dreams and Visions" on 2026-11-22, and the 19 chapters
 * the audiobook tool listed for it. The book was read twice; the files of both readings are here.
 * (Generated from the running backend; ids are replaced by f1, f2 ... )
 */
class ChapterChoiceTest {
    private val kept = listOf(
        KeptChapter(1, "Opening", "f1", "01-opening-0.95x.mp3", 1793532742.672106, null),
        KeptChapter(2, "Chapter 1 God's Purpose for Dreams and Visions", "f2", "02-chapter-1-god-s-purpose-for-dreams-and-visions-0.95x.mp3", 1793532742.692529, null),
        KeptChapter(3, "Chapter 2 Dreams, Visions and Prophecy", "f3", "03-chapter-2-dreams-visions-and-prophecy-0.95x.mp3", 1793532742.709756, null),
        KeptChapter(4, "Chapter 1 God's Purpose for Dreams and Visions", "f4", "04-chapter-1-god-s-purpose-for-dreams-and-visions-0.95x.mp3", 1793532742.773193, null),
        KeptChapter(4, "Chapter 3 Spiritual Dreams and Visions", "f5", "04-chapter-3-spiritual-dreams-and-visions-0.95x.mp3", 1793532742.791153, null),
        KeptChapter(5, "Chapter 2 Dreams, Visions and Prophecy", "f6", "05-chapter-2-dreams-visions-and-prophecy-0.95x.mp3", 1793532742.850652, null),
        KeptChapter(5, "Chapter 4 Natural Dreams and Visions", "f7", "05-chapter-4-natural-dreams-and-visions-0.95x.mp3", 1793532742.869748, null),
        KeptChapter(6, "Chapter 3 Spiritual Dreams and Visions", "f8", "06-chapter-3-spiritual-dreams-and-visions-0.95x.mp3", 1793532742.933723, null),
        KeptChapter(6, "Chapter 5 False Dreams and Visions", "f9", "06-chapter-5-false-dreams-and-visions-0.95x.mp3", 1793532742.950505, null),
        KeptChapter(7, "Chapter 4 Natural Dreams and Visions", "f10", "07-chapter-4-natural-dreams-and-visions-0.95x.mp3", 1793532743.013068, null),
        KeptChapter(7, "Chapter 6 Knowing the Source of Your Dreams", "f11", "07-chapter-6-knowing-the-source-of-your-dreams-0.95x.mp3", 1793532743.034933, null),
        KeptChapter(8, "Chapter 5 False Dreams and Visions", "f12", "08-chapter-5-false-dreams-and-visions-0.95x.mp3", 1793532743.096124, null),
        KeptChapter(8, "Chapter 7 Dreams Reveal the Heart", "f13", "08-chapter-7-dreams-reveal-the-heart-0.95x.mp3", 1793532743.113338, null),
        KeptChapter(9, "Chapter 6 Knowing the Source of Your Dreams", "f14", "09-chapter-6-knowing-the-source-of-your-dreams-0.95x.mp3", 1793532743.169515, null),
        KeptChapter(9, "Chapter 8 Dreams of Encouragement", "f15", "09-chapter-8-dreams-of-encouragement-0.95x.mp3", 1793532743.186608, null),
        KeptChapter(10, "Chapter 7 Dreams Reveal the Heart", "f16", "10-chapter-7-dreams-reveal-the-heart-0.95x.mp3", 1793532743.289513, null),
        KeptChapter(10, "Chapter 9 Warning and Direction from Dreams and Visions", "f17", "10-chapter-9-warning-and-direction-from-dreams-and-visions-0.95x.mp3", 1793532743.306642, null),
        KeptChapter(11, "Chapter 10 Dreams and the Gifts of the Holy Spirit", "f18", "11-chapter-10-dreams-and-the-gifts-of-the-holy-spirit-0.95x.mp3", 1793532743.325522, null),
        KeptChapter(11, "Chapter 8 Dreams of Encouragement", "f19", "11-chapter-8-dreams-of-encouragement-0.95x.mp3", 1793532743.419541, null),
        KeptChapter(12, "Chapter 11 Dreams, Visions and Spiritual Warfare", "f20", "12-chapter-11-dreams-visions-and-spiritual-warfare-0.95x.mp3", 1793532743.443221, null),
        KeptChapter(12, "Chapter 9 Warning and Direction from Dreams and Visions", "f21", "12-chapter-9-warning-and-direction-from-dreams-and-visions-0.95x.mp3", 1793532743.497454, null),
        KeptChapter(13, "Chapter 10 Dreams and the Gifts of the Holy Spirit", "f22", "13-chapter-10-dreams-and-the-gifts-of-the-holy-spirit-0.95x.mp3", 1793532743.588669, null),
        KeptChapter(13, "Chapter 12 The Language of Symbolism", "f23", "13-chapter-12-the-language-of-symbolism-0.95x.mp3", 1793532743.603862, null),
        KeptChapter(14, "Chapter 11 Dreams, Visions and Spiritual Warfare", "f24", "14-chapter-11-dreams-visions-and-spiritual-warfare-0.95x.mp3", 1793532743.657786, null),
        KeptChapter(14, "Chapter 13 Basic Symbols", "f25", "14-chapter-13-basic-symbols-0.95x.mp3", 1793532743.673645, null),
        KeptChapter(15, "Chapter 12 The Language of Symbolism", "f26", "15-chapter-12-the-language-of-symbolism-0.95x.mp3", 1793532743.757478, null),
        KeptChapter(15, "Chapter 14 Interpreting Your Dreams and Visions", "f27", "15-chapter-14-interpreting-your-dreams-and-visions-0.95x.mp3", 1793532743.773374, null),
        KeptChapter(16, "Chapter 13 Basic Symbols", "f28", "16-chapter-13-basic-symbols-0.95x.mp3", 1793532743.880858, null),
        KeptChapter(16, "Chapter 15 Responding to Your Dreams and Visions", "f29", "16-chapter-15-responding-to-your-dreams-and-visions-0.95x.mp3", 1793532743.898374, null),
        KeptChapter(17, "Chapter 14 Interpreting Your Dreams and Visions", "f30", "17-chapter-14-interpreting-your-dreams-and-visions-0.95x.mp3", 1793532743.975914, null),
        KeptChapter(17, "Chapter 16 A Charge to Dreamers", "f31", "17-chapter-16-a-charge-to-dreamers-0.95x.mp3", 1793532743.99408, null),
        KeptChapter(18, "Chapter 15 Responding to Your Dreams and Visions", "f32", "18-chapter-15-responding-to-your-dreams-and-visions-0.95x.mp3", 1793532744.068679, null),
        KeptChapter(18, "FOREWORD", "f33", "18-foreword-0.95x.mp3", 1793532744.110561, null),
        KeptChapter(19, "Chapter 16 A Charge to Dreamers", "f34", "19-chapter-16-a-charge-to-dreamers-0.95x.mp3", 1793532744.152364, null),
        KeptChapter(19, "INTRODUCTION", "f35", "19-introduction-0.95x.mp3", 1793532745.049516, null),
    )

    private val tool = listOf(
        ToolChapter(1, "01-opening"),
        ToolChapter(2, "02-foreword"),
        ToolChapter(3, "03-introduction"),
        ToolChapter(4, "04-chapter-1-god-s-purpose-for-dreams-and-visions"),
        ToolChapter(5, "05-chapter-2-dreams-visions-and-prophecy"),
        ToolChapter(6, "06-chapter-3-spiritual-dreams-and-visions"),
        ToolChapter(7, "07-chapter-4-natural-dreams-and-visions"),
        ToolChapter(8, "08-chapter-5-false-dreams-and-visions"),
        ToolChapter(9, "09-chapter-6-knowing-the-source-of-your-dreams"),
        ToolChapter(10, "10-chapter-7-dreams-reveal-the-heart"),
        ToolChapter(11, "11-chapter-8-dreams-of-encouragement"),
        ToolChapter(12, "12-chapter-9-warning-and-direction-from-dreams-and-visions"),
        ToolChapter(13, "13-chapter-10-dreams-and-the-gifts-of-the-holy-spirit"),
        ToolChapter(14, "14-chapter-11-dreams-visions-and-spiritual-warfare"),
        ToolChapter(15, "15-chapter-12-the-language-of-symbolism"),
        ToolChapter(16, "16-chapter-13-basic-symbols"),
        ToolChapter(17, "17-chapter-14-interpreting-your-dreams-and-visions"),
        ToolChapter(18, "18-chapter-15-responding-to-your-dreams-and-visions"),
        ToolChapter(19, "19-chapter-16-a-charge-to-dreamers"),
    )

    @Test fun `a book read twice has numbers that repeat`() {
        assertTrue(hasDuplicateNumbers(kept))
        assertEquals(19, kept.map { it.number }.toSet().size)
        assertEquals(16, kept.groupBy { it.number }.count { it.value.size > 1 })
    }

    @Test fun `the current reading has 17 chapters, the two unrendered ones left out`() {
        val chosen = currentReading(kept, tool)
        assertEquals(17, chosen.size)
        assertEquals((1..19).filter { it != 2 && it != 3 }, chosen.map { it.number })
    }

    @Test fun `each slot plays the chapter the tool names, not the newest file`() {
        val chosen = currentReading(kept, tool).associateBy { it.number }
        assertEquals("Opening", chosen[1]!!.title)
        assertEquals("Chapter 1 God's Purpose for Dreams and Visions", chosen[4]!!.title.removeSuffix("."))
        assertEquals("Chapter 16 A Charge to Dreamers", chosen[19]!!.title.removeSuffix("."))
        // every chosen file starts with the tool's stem for its slot
        val stems = tool.associate { it.number to it.stem!! }
        assertTrue(chosen.values.all { it.fileName.startsWith(stems[it.number]!!) })
    }

    @Test fun `taking the newest file per number is wrong for this book`() {
        val newest = onePerNumber(kept).associateBy { it.number }
        val right = currentReading(kept, tool).associateBy { it.number }
        val wrong = right.keys.count { newest[it]!!.audioFileId != right[it]!!.audioFileId }
        assertEquals(14, wrong)
    }

    @Test fun `a book with no repeated numbers needs no tool`() {
        val one = kept.filter { it.fileName.startsWith("04-chapter-1-") }
        assertFalse(hasDuplicateNumbers(one))
        assertEquals(one.size, onePerNumber(one).size)
    }

    @Test fun `a stem never claims a longer one`() {
        val files = listOf(
            KeptChapter(1, "One", "a", "01-chapter-1-0.95x.mp3", 1.0, null),
            KeptChapter(10, "Ten", "b", "01-chapter-10-0.95x.mp3", 2.0, null),
        )
        val chosen = currentReading(files, listOf(ToolChapter(1, "01-chapter-1")))
        assertEquals(listOf("a"), chosen.map { it.audioFileId })
    }
}
