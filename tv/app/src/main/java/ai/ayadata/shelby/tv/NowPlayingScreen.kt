package ai.ayadata.shelby.tv

import androidx.compose.foundation.background
import androidx.compose.foundation.focusable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.key.Key
import androidx.compose.ui.input.key.KeyEventType
import androidx.compose.ui.input.key.key
import androidx.compose.ui.input.key.onKeyEvent
import androidx.compose.ui.input.key.type
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.repeatOnLifecycle
import androidx.media3.common.util.UnstableApi
import androidx.tv.material3.ExperimentalTvMaterial3Api
import androidx.tv.material3.Text
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.android.awaitFrame
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext

/**
 * What is playing, with the chapter's text following the voice (follow-along) where it can.
 *
 * Keys: OK plays and pauses; Left skips back 15 s and Right forward 30 s (the web player's steps); Up and Down go to
 * the previous and next paragraph when the text is showing (Previous restarts the paragraph if it began more than two
 * seconds ago, as the web view does); the media keys do what they say. Back is the activity's (it leaves this screen and
 * the chapter keeps playing).
 */
@UnstableApi
@OptIn(ExperimentalTvMaterial3Api::class)
@Composable
fun NowPlayingScreen(playback: Playback, api: ShelbyApi) {
    val book = playback.book
    val chapter = playback.currentChapter
    val focus = remember { FocusRequester() }
    LaunchedEffect(Unit) {
        awaitFrame()
        try { focus.requestFocus() } catch (_: IllegalStateException) { /* not drawn yet */ }
    }

    // The text and timing of the chapter playing; read again when the chapter changes. The audio does not wait for it.
    val follow by produceState<Follow>(Follow.Loading, chapter?.id) {
        value = Follow.Loading
        value = if (book != null && chapter != null) withContext(Dispatchers.IO) { loadFollow(api, book, chapter) } else Follow.Off("")
    }
    val cursor = remember(chapter?.id) { FollowCursor() }

    fun skipParagraph(forward: Boolean): Boolean {
        val ready = follow as? Follow.Ready ?: return false
        val to = if (forward) nextStart(ready.segments, cursor.active) else previousStart(ready.segments, cursor.active, playback.position() / 1000.0)
        if (to != null) playback.seekToMs((to * 1000).toLong())
        return true
    }

    Box(
        Modifier
            .fillMaxSize()
            .focusRequester(focus)
            .focusable()
            .onKeyEvent { event ->
                if (event.type != KeyEventType.KeyDown) return@onKeyEvent false
                when (event.key) {
                    Key.DirectionCenter, Key.Enter, Key.NumPadEnter -> {
                        if (event.nativeKeyEvent.repeatCount == 0) playback.toggle()
                        true
                    }
                    Key.MediaPlayPause, Key.MediaPlay, Key.MediaPause -> { playback.toggle(); true }
                    Key.DirectionLeft, Key.MediaRewind, Key.MediaSkipBackward -> { playback.skipBack(); true }
                    Key.DirectionRight, Key.MediaFastForward, Key.MediaSkipForward -> { playback.skipForward(); true }
                    Key.DirectionUp -> skipParagraph(forward = false)
                    Key.DirectionDown -> skipParagraph(forward = true)
                    Key.MediaNext -> { playback.next(); true }
                    Key.MediaPrevious -> { playback.previous(); true }
                    else -> false
                }
            },
    ) {
        Backdrop()
        Row(Modifier.fillMaxSize().padding(horizontal = 48.dp, vertical = 32.dp)) {
            if (book != null) BookPanel(book, pill = playback.chapters.size.let { "Chapter ${playback.index + 1} of $it" })
            Spacer(Modifier.width(36.dp))
            Column(Modifier.weight(1f).fillMaxHeight()) {
                Text(
                    text = when {
                        playback.error != null -> "CAN’T PLAY"
                        playback.ended -> "FINISHED"
                        playback.isPlaying -> "NOW PLAYING"
                        else -> "PAUSED"
                    },
                    style = Type.ui(13.sp, FontWeight.SemiBold, if (playback.isPlaying) Tok.Brand else Tok.Ink3),
                )
                Spacer(Modifier.height(4.dp))
                Text(chapter?.title ?: "", style = Type.display(24.sp), maxLines = 1, overflow = TextOverflow.Ellipsis)
                Spacer(Modifier.height(10.dp))

                Box(Modifier.weight(1f).fillMaxWidth()) {
                    when (val f = follow) {
                        is Follow.Ready -> {
                            FollowText(f, playback, cursor, Modifier.fillMaxSize())
                            // a soft edge where the text runs out, instead of a line cut through the middle of a word:
                            // one still gradient, the same colour as the page there (the glow behind is at the top left)
                            Box(
                                Modifier.align(Alignment.BottomCenter).fillMaxWidth().height(36.dp)
                                    .background(Brush.verticalGradient(listOf(Color.Transparent, Tok.Bg))),
                            )
                        }
                        is Follow.Loading -> Note("Opening the text…")
                        is Follow.Off -> Note(f.reason)
                    }
                }

                Spacer(Modifier.height(12.dp))
                if (playback.error != null) {
                    Text(playback.error!!, style = Type.ui(18.sp, FontWeight.Normal, Tok.Ink2))
                } else {
                    Progress(playback)
                }
                Spacer(Modifier.height(10.dp))
                Text(
                    text = "OK  play or pause      ◀  back 15 s      forward 30 s  ▶" +
                        if (follow is Follow.Ready) "      ▲ ▼  paragraph" else "",
                    style = Type.Small,
                )
            }
        }
    }
}

/** A line of plain words where the text would be: while it opens, or why it cannot be shown. */
@OptIn(ExperimentalTvMaterial3Api::class)
@Composable
private fun Note(words: String) {
    Text(words, style = Type.ui(18.sp, FontWeight.Normal, Tok.Ink2), modifier = Modifier.padding(top = 8.dp, end = 24.dp))
}

/** The bar and the two times. It asks the player four times a second and is the only thing that redraws. */
@UnstableApi
@OptIn(ExperimentalTvMaterial3Api::class)
@Composable
private fun Progress(playback: Playback) {
    var position by remember { mutableLongStateOf(0L) }
    var length by remember { mutableLongStateOf(0L) }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(playback.index) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {   // not while the screen is off or covered
            while (true) {
                position = playback.position()
                length = playback.duration()
                delay(250)
            }
        }
    }
    val fraction = if (length > 0) (position.toFloat() / length).coerceIn(0f, 1f) else 0f
    Column(Modifier.fillMaxWidth()) {
        Box(Modifier.fillMaxWidth().height(8.dp).clip(RoundedCornerShape(4.dp)).background(Tok.Surface2)) {
            Box(Modifier.fillMaxWidth(fraction).fillMaxHeight().background(Tok.Brand))
        }
        Spacer(Modifier.height(10.dp))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text(formatClock(position / 1000.0), style = Type.Small)
            Text(if (length > 0) formatClock(length / 1000.0) else "", style = Type.Small)
        }
    }
}
