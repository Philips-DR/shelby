package ai.ayadata.shelby.tv

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.tv.material3.Border
import androidx.tv.material3.ClickableSurfaceDefaults
import androidx.tv.material3.ExperimentalTvMaterial3Api
import androidx.tv.material3.Surface
import androidx.tv.material3.Text

/** "3:07" or "1:02:09". */
fun formatClock(seconds: Double): String {
    val total = seconds.toLong().coerceAtLeast(0)
    val h = total / 3600
    val m = (total % 3600) / 60
    val s = total % 60
    return if (h > 0) "%d:%02d:%02d".format(h, m, s) else "%d:%02d".format(m, s)
}

/**
 * A book's cover. The books have no cover art, so Art.kt draws one (once, as a picture); this puts the
 * title and author over it. Live text over a finished picture is cheap: only the small text is drawn
 * each frame.
 */
@Composable
fun BookCover(
    title: String,
    author: String,
    modifier: Modifier = Modifier,
    titleLines: Int = 3,
    showText: Boolean = true,
) {
    val context = LocalContext.current
    val art = remember(title, showText) { coverBitmap(context, title, withScrim = showText) }
    Box(modifier = modifier) {
        Image(
            bitmap = art,
            contentDescription = null,
            modifier = Modifier.fillMaxSize(),
            contentScale = ContentScale.FillBounds,
        )
        if (showText) {
            Column(Modifier.align(Alignment.BottomStart).padding(12.dp)) {
                Text(title, style = Type.TileTitle, maxLines = titleLines, overflow = TextOverflow.Ellipsis)
                if (author.isNotEmpty()) {
                    Spacer(Modifier.height(3.dp))
                    Text(author, style = Type.ui(12.sp, FontWeight.Medium, Tok.Ink2), maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
        }
    }
}

/** A book on the shelf. Focus: it grows a little and gets a teal ring. Nothing else moves. */
@OptIn(ExperimentalTvMaterial3Api::class)
@Composable
fun BookTile(
    book: Book,
    onClick: () -> Unit,
    onFocused: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val shape = RoundedCornerShape(Tok.RCard.dp)
    Surface(
        onClick = onClick,
        modifier = modifier.size(150.dp, 210.dp).onFocusChanged { if (it.hasFocus) onFocused() },
        shape = ClickableSurfaceDefaults.shape(shape),
        colors = ClickableSurfaceDefaults.colors(containerColor = Tok.Surface, focusedContainerColor = Tok.Surface),
        scale = ClickableSurfaceDefaults.scale(focusedScale = 1.08f),
        border = ClickableSurfaceDefaults.border(
            border = Border(BorderStroke(1.dp, Tok.Line), shape = shape),
            focusedBorder = Border(BorderStroke(3.dp, Tok.Brand), shape = shape),
        ),
    ) {
        BookCover(book.title, book.author, Modifier.fillMaxSize())
    }
}

/** A chapter in the list. Focus: a lifted background and a teal ring; the list does not scale (it would shove its neighbours). */
@OptIn(ExperimentalTvMaterial3Api::class)
@Composable
fun ChapterRow(
    position: Int,
    chapter: Chapter,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    /** This is the chapter that is playing now. */
    isPlaying: Boolean = false,
    /** Where this book was left, when it was left in this chapter: shown instead of the length. */
    resumeMs: Long? = null,
) {
    val shape = RoundedCornerShape(Tok.RControl.dp)
    Surface(
        onClick = onClick,
        modifier = modifier.fillMaxWidth(),
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
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = if (isPlaying) "▶" else "%02d".format(position),
                style = Type.ui(16.sp, FontWeight.SemiBold, if (isPlaying) Tok.Brand else Tok.Ink3),
                modifier = Modifier.width(40.dp),
            )
            Text(
                text = chapter.title,
                style = Type.Row,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f),
            )
            if (resumeMs != null) {
                Spacer(Modifier.width(16.dp))
                Text("Resume ${formatClock(resumeMs / 1000.0)}", style = Type.ui(13.sp, FontWeight.SemiBold, Tok.Brand))
            } else {
                chapter.seconds?.let {
                    Spacer(Modifier.width(16.dp))
                    Text(formatClock(it), style = Type.Small)
                }
            }
        }
    }
}

/** The book on the left of the chapters and now-playing screens: cover, title, author, and an optional label. */
@OptIn(ExperimentalTvMaterial3Api::class)
@Composable
fun BookPanel(book: Book, modifier: Modifier = Modifier, pill: String? = null) {
    Column(modifier.width(220.dp)) {
        val cover = RoundedCornerShape(Tok.RCard.dp)
        BookCover(
            title = book.title,
            author = book.author,
            showText = false,
            modifier = Modifier.size(150.dp, 210.dp).clip(cover).border(1.dp, Tok.Line, cover),
        )
        Spacer(Modifier.height(18.dp))
        Text(book.title, style = Type.display(22.sp), maxLines = 3, overflow = TextOverflow.Ellipsis)
        if (book.author.isNotEmpty()) {
            Spacer(Modifier.height(4.dp))
            Text(book.author, style = Type.ui(15.sp, FontWeight.Medium, Tok.Ink2), maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
        if (pill != null) {
            Spacer(Modifier.height(14.dp))
            Pill(pill)
        }
    }
}

/** A small rounded label, e.g. "19 chapters". */
@OptIn(ExperimentalTvMaterial3Api::class)
@Composable
fun Pill(text: String, modifier: Modifier = Modifier) {
    Text(
        text = text,
        style = Type.ui(13.sp, FontWeight.SemiBold, Tok.Ink2),
        modifier = modifier
            .background(Tok.Surface2, RoundedCornerShape(50))
            .padding(horizontal = 12.dp, vertical = 5.dp),
    )
}

/** The wordmark: a teal dot and "Shelby", and the section's name beside it. */
@OptIn(ExperimentalTvMaterial3Api::class)
@Composable
fun Wordmark(section: String, modifier: Modifier = Modifier) {
    Row(modifier = modifier, verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(10.dp).background(Tok.Brand, CircleShape))
        Spacer(Modifier.width(10.dp))
        Text("Shelby", style = Type.display(18.sp, FontWeight.SemiBold))
        Spacer(Modifier.width(14.dp))
        Box(Modifier.width(1.dp).height(16.dp).background(Tok.LineStrong))
        Spacer(Modifier.width(14.dp))
        Text(section, style = Type.ui(16.sp, FontWeight.Medium, Tok.Ink2))
    }
}

/** Full-screen message: loading, or something that went wrong, in words that say what to do. */
@OptIn(ExperimentalTvMaterial3Api::class)
@Composable
fun StateMessage(title: String, detail: String? = null, modifier: Modifier = Modifier) {
    Box(modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(title, style = Type.ScreenTitle)
            if (detail != null) {
                Text(detail, style = Type.ui(16.sp, FontWeight.Normal, Tok.Ink2), modifier = Modifier.padding(horizontal = 96.dp))
            }
        }
    }
}
