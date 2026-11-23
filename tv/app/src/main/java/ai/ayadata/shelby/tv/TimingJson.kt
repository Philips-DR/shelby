package ai.ayadata.shelby.tv

import org.json.JSONArray
import org.json.JSONObject

/**
 * A chapter's timing as Shelby keeps it in the record's `timing` label: compact, no text (the paragraph's words
 * are matched to it by count). Same shape as the web app's `fromCompact` (audiobookTiming.ts). Anything that is
 * not there stays null: a chunk with no count, or no sentences, is cut more coarsely by [unitsFor], never invented.
 */
fun parseTiming(array: JSONArray): List<SegmentTiming> =
    (0 until array.length()).map { i ->
        val s = array.getJSONObject(i)
        val chunks = s.optJSONArray("chunks") ?: JSONArray()
        SegmentTiming(
            kind = s.optString("kind", ""),
            start = s.getDouble("start"),
            end = s.getDouble("end"),
            chunks = (0 until chunks.length()).map { j -> parseChunk(chunks.getJSONObject(j)) },
        )
    }

private fun parseChunk(c: JSONObject): ChunkTiming {
    val sentences = c.optJSONArray("sentences")
    return ChunkTiming(
        start = c.getDouble("start"),
        end = c.getDouble("end"),
        text = if (c.has("text") && !c.isNull("text")) c.getString("text") else null,
        words = if (c.has("words") && !c.isNull("words")) c.getInt("words") else null,
        sentences = sentences?.let { arr ->
            (0 until arr.length()).map { k -> arr.getJSONObject(k).let { SentenceTiming(it.getInt("words"), it.getDouble("start")) } }
        },
    )
}
