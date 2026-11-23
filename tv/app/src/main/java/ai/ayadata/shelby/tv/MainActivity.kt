package ai.ayadata.shelby.tv

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.activity.compose.setContent
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.media3.common.util.UnstableApi
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

@UnstableApi
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // The player is the application's, not this screen's: it keeps playing when this activity is stopped or destroyed.
        val playback = (application as ShelbyApplication).playback
        setContent {
            ShelbyTheme {
                ShelbyApp(this, playback)
            }
        }
    }
}

@UnstableApi
@Composable
fun ShelbyApp(activity: ComponentActivity, playback: Playback) {
    val api = remember { ShelbyApi(BuildConfig.API_TOKEN) }
    var books by remember { mutableStateOf<List<Book>>(emptyList()) }
    var booksLoading by remember { mutableStateOf(true) }
    var booksError by remember { mutableStateOf<String?>(null) }

    // A book already playing (the screen was closed and opened again while it played on) opens on the player, as the
    // person left it; otherwise the shelf.
    val resuming = playback.book?.takeIf { !playback.ended }
    var selectedBook by remember { mutableStateOf<Book?>(resuming) }
    /** Where the shelf was left, so Back lands on the same book. */
    var shelfIndex by remember { mutableIntStateOf(0) }
    var chapters by remember { mutableStateOf<List<Chapter>>(emptyList()) }
    var chaptersLoading by remember { mutableStateOf(false) }
    var chaptersError by remember { mutableStateOf<String?>(null) }
    /** On the now-playing screen. Leaving it does not stop the chapter. */
    var inPlayer by remember { mutableStateOf(resuming != null) }

    // Back goes up one screen: player to chapters, chapters to the shelf. On the shelf the callback is off,
    // so Back leaves the app as it should.
    DisposableEffect(selectedBook != null, inPlayer) {
        val callback = object : OnBackPressedCallback(selectedBook != null) {
            override fun handleOnBackPressed() {
                if (inPlayer) inPlayer = false else selectedBook = null
            }
        }
        activity.onBackPressedDispatcher.addCallback(callback)
        onDispose { callback.remove() }
    }

    LaunchedEffect(Unit) {
        try {
            books = withContext(Dispatchers.IO) { api.getBooks() }
        } catch (e: Exception) {
            booksError = e.message ?: "Failed to load books"
        } finally {
            booksLoading = false
        }
    }

    LaunchedEffect(selectedBook) {
        val book = selectedBook ?: return@LaunchedEffect
        chaptersLoading = true
        chaptersError = null
        chapters = emptyList()
        try {
            chapters = withContext(Dispatchers.IO) { api.getChapters(book.key) }
        } catch (e: Exception) {
            chaptersError = e.message ?: "Failed to load chapters"
        } finally {
            chaptersLoading = false
        }
    }

    val book = selectedBook
    when {
        book != null && inPlayer -> NowPlayingScreen(playback, api)
        book != null -> {
            // Re-read on coming back from the player: the place moves while a chapter plays.
            val place = remember(book.key, inPlayer) { playback.places.get(book.key) }
            ChaptersScreen(
                book = book,
                chapters = chapters,
                isLoading = chaptersLoading,
                error = chaptersError,
                playingId = playback.currentChapter?.id?.takeIf { playback.bookKey == book.key && !playback.ended },
                place = place,
                onChapterSelected = { index, chapter ->
                    val resumeMs = place?.takeIf { it.chapterId == chapter.id }?.positionMs ?: 0L
                    when {
                        playback.bookKey == book.key && playback.currentChapter?.id == chapter.id && !playback.ended -> {
                            // already on it: just show the player
                        }
                        playback.bookKey == book.key && playback.chapters.map { it.id } == chapters.map { it.id } ->
                            playback.jumpTo(index, resumeMs)
                        else -> playback.start(book, chapters, index, resumeMs)
                    }
                    inPlayer = true
                },
            )
        }
        else -> BooksScreen(
            books = books,
            isLoading = booksLoading,
            error = booksError,
            focusIndex = shelfIndex,
            playback = playback,
            onOpenPlayer = {
                // the player of the book that is playing; Back from it goes to that book's chapters, then to its place on the shelf
                playback.book?.let { playing ->
                    shelfIndex = books.indexOfFirst { it.key == playing.key }.coerceAtLeast(0)
                    selectedBook = playing
                    inPlayer = true
                }
            },
            onBookSelected = { index, chosen ->
                shelfIndex = index
                selectedBook = chosen
            },
        )
    }
}
