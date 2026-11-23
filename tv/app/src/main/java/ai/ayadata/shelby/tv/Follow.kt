package ai.ayadata.shelby.tv

import java.io.IOException

/** What the follow-along view has for the chapter playing. */
sealed interface Follow {
    data object Loading : Follow

    /** It cannot be followed, and why, in words for the person holding the remote. Never blank, never pretending. */
    data class Off(val reason: String) : Follow

    /** The text and the timing, one paragraph of text for each paragraph of timing (checked by [isAligned]). */
    data class Ready(val paragraphs: List<Paragraph>, val segments: List<SegmentTiming>) : Follow
}

/** The last few chapters' text, so leaving the player and coming back does not read the PDF again (1 to 5 s). */
private val recent = object : LinkedHashMap<String, Follow.Ready>(8, 0.75f, true) {
    override fun removeEldestEntry(eldest: MutableMap.MutableEntry<String, Follow.Ready>?) = size > 4
}

/**
 * Decide whether a chapter can be followed, and get what it takes. Blocking: call it off the main thread.
 * Same rules as the web app's follow view: it needs the chapter's timing, its text from the book's PDF, and
 * one paragraph of text for each of the timing's (the text may have been corrected since the render).
 */
fun loadFollow(api: ShelbyApi, book: Book, chapter: Chapter): Follow {
    synchronized(recent) { recent[chapter.id] }?.let { return it }
    val timing = try {
        api.getTiming(chapter.recordId)
    } catch (e: IOException) {
        return Follow.Off("Can’t get this chapter’s timing: ${e.message}")
    }
    val segments = timing?.let { spokenSegments(it) }.orEmpty()
    if (segments.isEmpty()) {
        return Follow.Off("This chapter was made before Shelby kept the timing of each sentence, so it can’t be followed yet.")
    }
    val paragraphs = try {
        api.getChapterText(book.key, chapter.number)
    } catch (e: NoTextException) {
        return Follow.Off(e.message ?: "This chapter’s text can’t be shown.")
    } catch (e: IOException) {
        return Follow.Off("Can’t read this chapter’s text: ${e.message}")
    }
    if (!isAligned(paragraphs.size, segments)) {
        return Follow.Off(
            "The text no longer matches this recording (${paragraphs.size} paragraphs now, ${segments.size} when it was made), " +
                "so it can’t be followed. Render the chapter again to follow along.",
        )
    }
    return Follow.Ready(paragraphs, segments).also { synchronized(recent) { recent[chapter.id] = it } }
}
