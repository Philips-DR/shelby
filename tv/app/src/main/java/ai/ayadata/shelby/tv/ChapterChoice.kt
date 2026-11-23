package ai.ayadata.shelby.tv

/*
 * Which chapter files make up a book. Kept apart from the network and the screen so it can be tested
 * against real data (app/src/test).
 *
 * A book can be read twice. "Dreams and Visions" was: the second reading found different chapter
 * boundaries, so the files of both readings sit in Shelby under the same chapter numbers but with
 * different titles. Taking the newest file for each number was tried and is WRONG for it: it picked the
 * wrong chapter in 14 of 19 slots (checked 2026-11-22 against the audiobook tool's own list). The tool's
 * list for the current reading is what decides, as it does in the web app (audiobookKept.ts, withKept).
 */

/** One rendered chapter file as Shelby keeps it. */
data class KeptChapter(
    val number: Int,
    val title: String,
    val audioFileId: String,
    val fileName: String,
    val created: Double,
    /** How long it plays, when the render recorded it (146 of the first 242 real chapters did). */
    val seconds: Double?,
    /** Shelby's id for the chapter's record (not the audio file's): the timing is fetched by it. */
    val recordId: String = "",
)

/** One chapter of a book's current reading, as the audiobook tool lists it (`preview_book`). */
data class ToolChapter(val number: Int, val stem: String?)

/** After a chapter's stem only its speed may follow, as the tool matches its own files, so
 *  "01-chapter-1" never claims "01-chapter-10-...". Copied from the web app (audiobookKept.ts). */
private val SPEED_AND_SUFFIX = Regex("^(?:-\\d+(?:\\.\\d+)?x)?\\.mp3$")

/** True when a chapter number has more than one file: the book was read more than once. */
fun hasDuplicateNumbers(kept: List<KeptChapter>): Boolean =
    kept.groupingBy { it.number }.eachCount().any { it.value > 1 }

/** One file per number, in order. Only right when no number repeats (see [hasDuplicateNumbers]); with a
 *  repeat it takes the newest, which is a guess, so callers use [currentReading] for those books. */
fun onePerNumber(kept: List<KeptChapter>): List<KeptChapter> =
    kept.groupBy { it.number }.map { (_, files) -> files.maxBy { it.created } }.sortedBy { it.number }

/**
 * The chapters of the current reading that have audio: for each chapter the tool lists, the newest kept
 * file whose name starts with the tool's stem (and then only a speed). A chapter the tool lists that has
 * no file is left out (it is not rendered); a kept file no chapter claims belongs to an older reading
 * and is left out.
 */
fun currentReading(kept: List<KeptChapter>, tool: List<ToolChapter>): List<KeptChapter> =
    tool.mapNotNull { t ->
        val stem = t.stem?.takeIf { it.isNotEmpty() } ?: return@mapNotNull null
        kept.filter { it.fileName.startsWith(stem) && SPEED_AND_SUFFIX.matches(it.fileName.substring(stem.length)) }
            .maxByOrNull { it.created }
            ?.copy(number = t.number)
    }.sortedBy { it.number }
