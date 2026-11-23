package ai.ayadata.shelby.tv

import android.content.Context

/** Where a book was left: a chapter, and how far into it. */
data class Place(val chapterId: String, val positionMs: Long)

/**
 * One saved place per book, kept on the TV (the user's decision, 2026-11-22). A chapter can run long, the
 * TV switches its screen off after ten minutes, and with 1.8 GB of RAM the app may well be closed, so the
 * book must be able to carry on where it was. Nothing here goes to the backend.
 */
class Places(context: Context) {
    private val prefs = context.getSharedPreferences("places", Context.MODE_PRIVATE)

    fun get(bookKey: String): Place? {
        val raw = prefs.getString(bookKey, null) ?: return null
        val at = raw.lastIndexOf('|')
        if (at <= 0) return null
        val ms = raw.substring(at + 1).toLongOrNull() ?: return null
        return Place(raw.substring(0, at), ms.coerceAtLeast(0))
    }

    fun save(bookKey: String, chapterId: String, positionMs: Long) {
        prefs.edit().putString(bookKey, "$chapterId|${positionMs.coerceAtLeast(0)}").apply()
    }

    /** The book was finished: next time it starts from the top. */
    fun clear(bookKey: String) {
        prefs.edit().remove(bookKey).apply()
    }
}
