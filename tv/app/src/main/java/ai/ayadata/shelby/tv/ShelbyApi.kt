package ai.ayadata.shelby.tv

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.IOException

data class Book(
    val id: String,
    val key: String,
    val title: String,
    val author: String
)

data class Chapter(
    val id: String,
    val number: Int,
    val title: String,
    val audioFileId: String,
    /** How long it plays, when the render recorded it. */
    val seconds: Double? = null,
    /** Shelby's id for the chapter's record: its timing is fetched by it. */
    val recordId: String = "",
)

/** One paragraph of a chapter's text: `kind` is "paragraph", "heading" or "list_item". */
data class Paragraph(val kind: String, val text: String)

/** The chapter's text cannot be had, and why, in words for the person holding the remote. */
class NoTextException(message: String) : IOException(message)

class ShelbyApi(private val token: String) {

    private val client = OkHttpClient()
    private val baseUrl = SHELBY_URL
    private val json = "application/json".toMediaType()

    private fun send(request: Request): JSONObject {
        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) throw IOException("HTTP ${response.code}")
            return JSONObject(response.body!!.string())
        }
    }

    private fun get(path: String): JSONObject =
        send(Request.Builder().url("$baseUrl$path").header("x-assistant-token", token).build())

    /** Run one of Shelby's read-only tools, as the web app's buttons do. */
    private fun tool(name: String, arguments: JSONObject): JSONObject {
        val body = JSONObject().put("tool", name).put("arguments", arguments).put("confirmed", false)
        val reply = send(
            Request.Builder().url("$baseUrl/api/actions").header("x-assistant-token", token)
                .post(body.toString().toRequestBody(json)).build(),
        )
        val output = reply.optJSONObject("output") ?: throw IOException("$name gave no answer")
        if (output.has("error")) throw IOException(output.optString("error"))
        return output
    }

    fun getBooks(): List<Book> {
        val records = get("/api/records?tool=audiobook&kind=book").getJSONArray("records")
        return (0 until records.length()).map { i ->
            val r = records.getJSONObject(i)
            val labels = r.getJSONObject("labels")
            Book(
                id = r.getString("id"),
                key = r.getString("key"),
                title = labels.optString("title", r.getString("key")),
                author = labels.optString("author", "").let {
                    if (it == "None" || it == "null" || it.isBlank()) "" else it
                }
            )
        }.sortedBy { it.title.lowercase() }
    }

    /**
     * A book's chapters with audio, in order. Usually the kept files say it all. When a number repeats the
     * book was read twice, and only the audiobook tool knows which reading is current (see ChapterChoice.kt):
     * that costs 1 to 5 seconds, so it is asked only then, and if it cannot answer the app says so rather
     * than guess.
     */
    fun getChapters(bookKey: String): List<Chapter> {
        val kept = keptChapters(bookKey)
        val chosen = if (hasDuplicateNumbers(kept)) currentReading(kept, toolChapters(bookKey)) else onePerNumber(kept)
        return chosen.map {
            Chapter(id = it.audioFileId, number = it.number, title = it.title, audioFileId = it.audioFileId, seconds = it.seconds, recordId = it.recordId)
        }
    }

    private fun keptChapters(bookKey: String): List<KeptChapter> {
        val records = get("/api/records?tool=audiobook&kind=chapter").getJSONArray("records")
        val kept = mutableListOf<KeptChapter>()
        for (i in 0 until records.length()) {
            val r = records.getJSONObject(i)
            val labels = r.getJSONObject("labels")
            if (labels.optString("book", "") != bookKey) continue
            val number = when (val n = labels.opt("number")) {
                is Number -> n.toInt()
                is String -> n.toIntOrNull() ?: continue
                else -> continue
            }
            val audio = r.optJSONObject("files")?.optJSONObject("audio") ?: continue
            val audioId = audio.optString("id", "")
            if (audioId.isEmpty()) continue
            kept += KeptChapter(
                number = number,
                title = labels.optString("title", "Chapter $number"),
                audioFileId = audioId,
                fileName = audio.optString("name", ""),
                created = r.optDouble("created", 0.0),
                seconds = labels.optDouble("seconds", Double.NaN).takeIf { !it.isNaN() && it > 0 },
                recordId = r.optString("id", ""),
            )
        }
        return kept
    }

    /**
     * When each paragraph and sentence of a chapter is spoken, from its record (59 KB for the longest real chapter;
     * the whole listing is 1.1 MB). Null when the chapter has none: it was made before Shelby kept it.
     */
    fun getTiming(recordId: String): List<SegmentTiming>? {
        if (recordId.isEmpty()) return null
        val timing = get("/api/records/$recordId").optJSONObject("labels")?.optJSONArray("timing") ?: return null
        return if (timing.length() == 0) null else parseTiming(timing)
    }

    /**
     * The exact text a chapter speaks, read from the book's PDF by the audiobook tool, which hands it over in pages
     * (the longest real chapter's first page held 110 of its 149 paragraphs), so this asks until it says there is no more.
     */
    fun getChapterText(bookKey: String, chapterNumber: Int): List<Paragraph> {
        val pdf = findPdf(bookKey) ?: throw NoTextException("This book’s PDF is no longer in Shelby, so its text can’t be shown.")
        val paragraphs = ArrayList<Paragraph>()
        var start = 0
        while (true) {
            val page = tool("audiobook__read_chapter", JSONObject().put("pdf", pdf).put("chapter", chapterNumber).put("start", start))
            val segments = page.optJSONArray("segments") ?: break
            for (i in 0 until segments.length()) {
                val p = segments.getJSONObject(i)
                paragraphs += Paragraph(p.optString("kind", "paragraph"), p.optString("text", ""))
            }
            if (!page.optBoolean("truncated", false) || page.isNull("next_start")) break
            start = page.getInt("next_start")
        }
        return paragraphs
    }

    /** The chapters the audiobook tool lists for a book's current reading. It reads the book's PDF. */
    private fun toolChapters(bookKey: String): List<ToolChapter> {
        val pdf = findPdf(bookKey) ?: throw IOException(
            "This book was read more than once, and its PDF is no longer in Shelby, so the app can’t tell which chapters are the current ones.",
        )
        val overview = try {
            tool("audiobook__preview_book", JSONObject().put("pdf", pdf))
        } catch (e: IOException) {
            throw IOException("Shelby couldn’t check which chapters are the current ones: ${e.message}")
        }
        val chapters = overview.optJSONArray("chapters")
        if (!overview.optBoolean("analysed", false) || chapters == null) {
            throw IOException("This book hasn’t been read by Shelby yet, so the app can’t tell which chapters are the current ones.")
        }
        return (0 until chapters.length()).map { i ->
            val c = chapters.getJSONObject(i)
            ToolChapter(c.getInt("number"), c.optString("stem", "").ifEmpty { null })
        }
    }

    /** The path of the book's PDF in Shelby's uploads: the file name without ".pdf" is the book's key, or
     *  starts with it (the tool leaves site tags such as "(z-lib.org)" out of the key). */
    private fun findPdf(bookKey: String): String? {
        val books = get("/api/uploads").optJSONArray("books") ?: return null
        val all = (0 until books.length()).map { books.getJSONObject(it) }
        val exact = all.firstOrNull { it.optString("name").removeSuffix(".pdf") == bookKey }
        val starts = all.filter { it.optString("name").startsWith(bookKey) }
        return (exact ?: starts.singleOrNull())?.optString("path")?.takeIf { it.isNotEmpty() }
    }
}
