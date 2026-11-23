package ai.ayadata.shelby.tv

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.unit.dp
import androidx.tv.material3.ExperimentalTvMaterial3Api
import kotlinx.coroutines.android.awaitFrame

/**
 * A book's chapters: the book on the left, its chapters in order on the right.
 *
 * The remote lands on the chapter to carry on with: the one the book was left in, else the one playing, else
 * the first. That chapter says "Resume 12:34"; the one playing shows a teal ▶.
 */
@OptIn(ExperimentalTvMaterial3Api::class)
@Composable
fun ChaptersScreen(
    book: Book,
    chapters: List<Chapter>,
    isLoading: Boolean,
    error: String?,
    /** The chapter playing now, if it is of this book. */
    playingId: String?,
    /** Where this book was left. */
    place: Place?,
    onChapterSelected: (Int, Chapter) -> Unit,
) {
    Box(Modifier.fillMaxSize()) {
        Backdrop()
        when {
            isLoading -> StateMessage("Loading chapters…")
            error != null -> StateMessage("Can’t load this book", error)
            chapters.isEmpty() -> StateMessage("No chapters yet", "This book has no audio rendered.")
            else -> {
                val landOn = chapters.indexOfFirst { it.id == (place?.chapterId ?: playingId) }.coerceAtLeast(0)
                val listState = rememberLazyListState()
                val landing = remember { FocusRequester() }
                LaunchedEffect(chapters) {
                    listState.scrollToItem((landOn - 2).coerceAtLeast(0))
                    awaitFrame()
                    try { landing.requestFocus() } catch (_: IllegalStateException) { /* not drawn yet: the remote still works */ }
                }
                Row(Modifier.fillMaxSize().padding(horizontal = 48.dp, vertical = 32.dp)) {
                    BookPanel(book, pill = if (chapters.size == 1) "1 chapter" else "${chapters.size} chapters")
                    Spacer(Modifier.width(36.dp))
                    LazyColumn(
                        state = listState,
                        modifier = Modifier.weight(1f).fillMaxSize(),
                        contentPadding = PaddingValues(vertical = 6.dp),
                        verticalArrangement = Arrangement.spacedBy(4.dp),
                    ) {
                        itemsIndexed(chapters, key = { _, c -> c.id }) { i, c ->
                            ChapterRow(
                                position = i + 1,
                                chapter = c,
                                onClick = { onChapterSelected(i, c) },
                                isPlaying = c.id == playingId,
                                resumeMs = place?.takeIf { it.chapterId == c.id && it.positionMs >= 3_000 && c.id != playingId }?.positionMs,
                                modifier = if (i == landOn) Modifier.focusRequester(landing) else Modifier,
                            )
                        }
                    }
                }
            }
        }
    }
}
