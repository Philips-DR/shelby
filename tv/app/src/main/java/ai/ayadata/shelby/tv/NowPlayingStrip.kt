package ai.ayadata.shelby.tv

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.focusGroup
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.focusProperties
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.repeatOnLifecycle
import androidx.media3.common.util.UnstableApi
import androidx.tv.material3.Border
import androidx.tv.material3.ClickableSurfaceDefaults
import androidx.tv.material3.ExperimentalTvMaterial3Api
import androidx.tv.material3.Surface
import androidx.tv.material3.Text
import kotlinx.coroutines.delay

/**
 * What is playing, on the shelf, with its controls: the chapter and book, how far in, a thin bar, and five buttons
 * (previous chapter, back 15 s, play or pause, forward 30 s, next chapter: the steps the player screen's keys make).
 * Down from the books lands on play/pause; Left goes along the buttons to the title, and OK on the title opens the player.
 * Nothing is drawn when nothing is loaded (or the book has finished).
 *
 * It asks the player once a second and only while the screen is showing: the bar is a hair's width a second on a chapter
 * of minutes, and the shelf is a screen the remote moves quickly across, so it should cost it almost nothing. The
 * buttons' pictures are drawn as shapes (no image files, no font glyphs the TV may not have).
 */
@UnstableApi
@OptIn(ExperimentalTvMaterial3Api::class, ExperimentalComposeUiApi::class)
@Composable
fun NowPlayingStrip(playback: Playback, onOpen: () -> Unit, modifier: Modifier = Modifier) {
    val book = playback.book ?: return
    val chapter = playback.currentChapter ?: return
    if (playback.ended) return

    var position by remember { mutableLongStateOf(0L) }
    var length by remember { mutableLongStateOf(0L) }
    fun refresh() { position = playback.position(); length = playback.duration() }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(playback.index) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
            while (true) {
                refresh()
                delay(1000)
            }
        }
    }
    val fraction = if (length > 0) (position.toFloat() / length).coerceIn(0f, 1f) else 0f
    val playPause = remember { FocusRequester() }
    val shape = RoundedCornerShape(Tok.RControl.dp)

    Column(modifier.fillMaxWidth().clip(shape).background(Tok.Surface).border(1.dp, Tok.Line, shape)) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 10.dp, vertical = 6.dp)
                // coming into the strip from the books lands on play/pause, whichever part is nearest
                .focusProperties { enter = { playPause } }
                .focusGroup(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            // the title: OK opens the player
            StripSurface(onClick = onOpen, modifier = Modifier.weight(1f)) {
                Column(Modifier.fillMaxWidth().padding(horizontal = 10.dp, vertical = 3.dp)) {
                    Row {
                        Text(
                            text = when {
                                playback.error != null -> "CAN’T PLAY"
                                playback.isPlaying -> "NOW PLAYING"
                                else -> "PAUSED"
                            },
                            style = Type.ui(13.sp, FontWeight.SemiBold, if (playback.isPlaying) Tok.Brand else Tok.Ink3),
                        )
                        Text("   ·   " + book.title, style = Type.Small, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    }
                    Text(chapter.title, style = Type.Row, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
            Spacer(Modifier.width(10.dp))
            Text(
                text = formatClock(position / 1000.0) + if (length > 0) " / " + formatClock(length / 1000.0) else "",
                style = Type.Small,
            )
            Spacer(Modifier.width(14.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
                StripSurface(onClick = { playback.previous(); refresh() }, modifier = Modifier.width(44.dp)) {
                    Glyph(Picture.Previous, Tok.Ink)
                }
                StripSurface(onClick = { playback.skipBack(); refresh() }, modifier = Modifier.width(62.dp)) {
                    Text("−15 s", style = Type.ui(14.sp, FontWeight.SemiBold, Tok.Ink))
                }
                StripSurface(onClick = { playback.toggle(); refresh() }, modifier = Modifier.width(56.dp).focusRequester(playPause)) {
                    Glyph(if (playback.isPlaying) Picture.Pause else Picture.Play, Tok.Brand)
                }
                StripSurface(onClick = { playback.skipForward(); refresh() }, modifier = Modifier.width(62.dp)) {
                    Text("+30 s", style = Type.ui(14.sp, FontWeight.SemiBold, Tok.Ink))
                }
                StripSurface(onClick = { playback.next(); refresh() }, modifier = Modifier.width(44.dp)) {
                    Glyph(Picture.Next, Tok.Ink)
                }
            }
        }
        // the bar sits on the strip's lower edge; the column clips it to the rounded corners
        Box(Modifier.fillMaxWidth().height(3.dp).background(Tok.Surface2)) {
            Box(Modifier.fillMaxWidth(fraction).fillMaxHeight().background(Tok.Brand))
        }
    }
}

/** One focusable part of the strip: a teal ring when the remote is on it, nothing otherwise (the strip has its own look). */
@OptIn(ExperimentalTvMaterial3Api::class)
@Composable
private fun StripSurface(onClick: () -> Unit, modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    val shape = RoundedCornerShape(8.dp)
    Surface(
        onClick = onClick,
        modifier = modifier.height(44.dp),
        shape = ClickableSurfaceDefaults.shape(shape),
        colors = ClickableSurfaceDefaults.colors(
            containerColor = Color.Transparent,
            focusedContainerColor = Tok.Surface2,
            contentColor = Tok.Ink,
            focusedContentColor = Tok.Ink,
        ),
        scale = ClickableSurfaceDefaults.scale(focusedScale = 1f),
        border = ClickableSurfaceDefaults.border(
            border = Border(BorderStroke(2.dp, Color.Transparent), shape = shape),
            focusedBorder = Border(BorderStroke(2.dp, Tok.Brand), shape = shape),
        ),
    ) {
        // a button's picture is centred; the title's column fills the width and lays itself out
        Box(Modifier.fillMaxWidth().fillMaxHeight(), contentAlignment = Alignment.Center) { content() }
    }
}

private enum class Picture { Previous, Play, Pause, Next }

/** A control's picture, drawn as shapes. */
@Composable
private fun Glyph(picture: Picture, colour: Color) {
    Canvas(Modifier.size(22.dp)) {
        when (picture) {
            Picture.Play -> triangle(colour, left = 0.22f, tip = 0.88f, pointsRight = true)
            Picture.Pause -> {
                val corner = CornerRadius(size.width * 0.05f)
                drawRoundRect(colour, Offset(size.width * 0.2f, size.height * 0.14f), Size(size.width * 0.22f, size.height * 0.72f), corner)
                drawRoundRect(colour, Offset(size.width * 0.58f, size.height * 0.14f), Size(size.width * 0.22f, size.height * 0.72f), corner)
            }
            Picture.Previous -> {
                drawRect(colour, Offset(size.width * 0.12f, size.height * 0.16f), Size(size.width * 0.13f, size.height * 0.68f))
                triangle(colour, left = 0.36f, tip = 0.88f, pointsRight = false)
            }
            Picture.Next -> {
                drawRect(colour, Offset(size.width * 0.75f, size.height * 0.16f), Size(size.width * 0.13f, size.height * 0.68f))
                triangle(colour, left = 0.12f, tip = 0.64f, pointsRight = true)
            }
        }
    }
}

/** A triangle between two x positions (shares of the width), pointing right or left. */
private fun DrawScope.triangle(colour: Color, left: Float, tip: Float, pointsRight: Boolean) {
    val w = size.width; val h = size.height
    val path = Path().apply {
        if (pointsRight) {
            moveTo(w * left, h * 0.14f); lineTo(w * tip, h * 0.5f); lineTo(w * left, h * 0.86f)
        } else {
            moveTo(w * tip, h * 0.14f); lineTo(w * left, h * 0.5f); lineTo(w * tip, h * 0.86f)
        }
        close()
    }
    drawPath(path, colour)
}
