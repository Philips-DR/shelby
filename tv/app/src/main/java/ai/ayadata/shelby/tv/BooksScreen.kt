package ai.ayadata.shelby.tv

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.focusRestorer
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.media3.common.util.UnstableApi
import androidx.tv.material3.ExperimentalTvMaterial3Api
import androidx.tv.material3.Text
import kotlinx.coroutines.android.awaitFrame

/**
 * The shelf: what is focused is described at the top, large; the books run along the bottom. The remote
 * moves along the row, and the description follows it.
 *
 * `focusIndex` is the book to land on: the first on a fresh start, the one just left when Back comes
 * from its chapters (a TV that drops you at the start of the shelf every time is a miserable one).
 *
 * What is playing is shown along the bottom, with the book still playing from before (the screen was left, or
 * closed, and the book played on): OK on it opens the player.
 */
@UnstableApi
@OptIn(ExperimentalTvMaterial3Api::class)
@Composable
fun BooksScreen(
    books: List<Book>,
    isLoading: Boolean,
    error: String?,
    focusIndex: Int,
    playback: Playback,
    onOpenPlayer: () -> Unit,
    onBookSelected: (Int, Book) -> Unit,
) {
    Box(Modifier.fillMaxSize()) {
        Backdrop()
        when {
            isLoading -> StateMessage("Loading your books…")
            error != null -> StateMessage("Can’t reach Shelby", error)
            books.isEmpty() -> StateMessage("No audiobooks yet", "Render a book in Shelby and it will appear here.")
            else -> Shelf(books, focusIndex, playback, onOpenPlayer, onBookSelected)
        }
    }
}

@UnstableApi
@OptIn(ExperimentalTvMaterial3Api::class, ExperimentalComposeUiApi::class)
@Composable
private fun Shelf(books: List<Book>, focusIndex: Int, playback: Playback, onOpenPlayer: () -> Unit, onBookSelected: (Int, Book) -> Unit) {
    val start = focusIndex.coerceIn(0, books.lastIndex)
    var focused by remember { mutableIntStateOf(start) }
    val listState = rememberLazyListState()
    val landing = remember { FocusRequester() }

    // Land on the right book: scroll it into the list, wait for it to be drawn, then focus it.
    LaunchedEffect(books) {
        listState.scrollToItem(start)
        awaitFrame()
        try { landing.requestFocus() } catch (_: IllegalStateException) { /* not drawn yet: the remote still works */ }
    }

    val book = books[focused.coerceIn(0, books.lastIndex)]
    Column(Modifier.fillMaxSize().padding(top = 28.dp)) {
        Wordmark("Audiobooks", Modifier.padding(horizontal = 48.dp))

        // What is focused, large. Bottom-aligned so a one-line title sits close to the books.
        Box(Modifier.fillMaxWidth().height(124.dp).padding(horizontal = 48.dp), contentAlignment = Alignment.BottomStart) {
            Column(Modifier.widthIn(max = 720.dp)) {
                Text(book.title, style = Type.HeroTitle, maxLines = 2, overflow = TextOverflow.Ellipsis)
                Spacer(Modifier.height(6.dp))
                Text(book.author.ifEmpty { "Unknown author" }, style = Type.Author, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }

        Spacer(Modifier.height(18.dp))
        Text("Your books", style = Type.Small, modifier = Modifier.padding(horizontal = 48.dp))
        LazyRow(
            // Up from the now-playing strip lands on the book that was focused, not on whichever is nearest
            modifier = Modifier.focusRestorer(),
            state = listState,
            contentPadding = PaddingValues(horizontal = 48.dp, vertical = 14.dp),
            horizontalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            itemsIndexed(books, key = { _, b -> b.id }) { i, b ->
                BookTile(
                    book = b,
                    onClick = { onBookSelected(i, b) },
                    onFocused = { focused = i },
                    modifier = if (i == start) Modifier.focusRequester(landing) else Modifier,
                )
            }
        }

        // below the books, with the space that is left: Down from the shelf lands on it
        Spacer(Modifier.weight(1f))
        NowPlayingStrip(playback, onOpenPlayer, Modifier.padding(start = 48.dp, end = 48.dp, bottom = 16.dp))
    }
}
