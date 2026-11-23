package ai.ayadata.shelby.tv

import androidx.compose.foundation.gestures.scrollBy
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.repeatOnLifecycle
import androidx.media3.common.util.UnstableApi
import androidx.tv.material3.ExperimentalTvMaterial3Api
import androidx.tv.material3.Text
import kotlinx.coroutines.delay
import kotlin.math.abs

/** Which paragraph is being read, shared so the remote's Up and Down know where they are. -1 before the first. */
class FollowCursor {
    var active by mutableIntStateOf(-1)
}

/** Where the line being read sits, as a share of the text area's height (the web app's numbers). */
private const val ANCHOR = 0.42f

/**
 * The chapter's text, following the voice: the paragraph being read is bright, the others step back; inside it the
 * sentence being spoken is lit, the sentences before it are bright and the ones to come are softer. The text glides
 * so that sentence stays about 42% of the way down, moving by the clock (glideBy) and not by the frame.
 *
 * Cost, because the TV is weak: only the paragraph being read is split into sentences; the player is asked ten
 * times a second and the screen is redrawn only when the paragraph or sentence changes; nothing is drawn behind the
 * text that has to be redone on each frame. A sentence's start can be a few tenths of a second out (the render
 * guesses it from the text and moves it to the nearest pause), and after a skip in a variable-bitrate chapter the
 * audio can be seconds from the time shown (plan.md, step 5).
 */
@UnstableApi
@OptIn(ExperimentalTvMaterial3Api::class)
@Composable
fun FollowText(follow: Follow.Ready, playback: Playback, cursor: FollowCursor, modifier: Modifier = Modifier) {
    val paragraphs = follow.paragraphs
    val segments = follow.segments
    val words = remember(follow) { paragraphs.map { wordsOf(it.text) } }
    val unitCache = remember(follow) { arrayOfNulls<List<SpokenUnit>>(paragraphs.size) }
    val unitDone = remember(follow) { BooleanArray(paragraphs.size) }
    val unitsOf: (Int) -> List<SpokenUnit>? = remember(follow) {
        { i ->
            if (!unitDone[i]) { unitCache[i] = unitsFor(words[i], segments[i].chunks); unitDone[i] = true }
            unitCache[i]
        }
    }

    // The sentence being spoken in the active paragraph: -1 before its first, -2 when the paragraph is lit whole.
    var unit by remember(follow) { mutableIntStateOf(-1) }
    // Only while the screen is showing: with it off or another app in front nothing is drawn, so nothing is worked out
    // (the book plays on without it; it catches up on the next tick when the screen comes back).
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(follow) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
            while (true) {
                val t = playback.position() / 1000.0
                val a = activeSegment(segments, t)
                val u = if (a < 0) -1 else (unitsOf(a)?.let { unitAt(it, t) } ?: -2)
                if (a != cursor.active) cursor.active = a
                if (u != unit) unit = u
                delay(100)
            }
        }
    }

    BoxWithConstraints(modifier) {
        val listState = rememberLazyListState()
        // Where the lit line is inside the paragraph being read, as that paragraph last said (its number, pixels from its top).
        var lit by remember(follow) { mutableStateOf<Pair<Int, Float>?>(null) }
        val active = cursor.active

        LazyColumn(
            state = listState,
            userScrollEnabled = false,   // the remote's Up and Down skip by paragraph; the text moves by itself
            // room above and below so the first and last paragraphs can reach the anchor line
            contentPadding = PaddingValues(top = maxHeight * ANCHOR, bottom = maxHeight * (1 - ANCHOR)),
            verticalArrangement = Arrangement.spacedBy(18.dp),
        ) {
            itemsIndexed(paragraphs, key = { i, _ -> i }) { i, paragraph ->
                if (i == active) {
                    ActiveParagraph(i, paragraph, words[i], unitsOf(i), unit) { index, top -> lit = index to top }
                } else {
                    PlainParagraph(paragraph, if (i == active + 1) Tok.Ink2 else Tok.Ink3)
                }
            }
        }

        // Glide to the line being read. Restarted whenever the line changes, so there is only ever one goal.
        LaunchedEffect(follow, active, unit, lit) {
            if (active < 0) return@LaunchedEffect
            // Far away (after a skip, or a resume): jump to it first. A paragraph that is not on screen is not drawn and so
            // cannot say where its line is; waiting for it to would wait for ever (seen on the TV: the text stuck at 0:47
            // while the voice was at 1:57). It then draws, says where, and this runs again to glide the rest.
            if (listState.layoutInfo.visibleItemsInfo.none { it.index == active }) listState.scrollToItem(active)
            val inParagraph = lit?.takeIf { it.first == active }?.second ?: return@LaunchedEffect   // wait for the paragraph to say where
            // An item's offset is measured from where the list's content starts, which is `beforeContentPadding` below
            // the top of the list: so the anchor line is that far back from 0.42 of the way down (seen on the TV: measured
            // from the top of the list, the lit line settled at 0.85 of the way down and ran off the bottom).
            val anchor = ANCHOR * listState.layoutInfo.viewportSize.height - listState.layoutInfo.beforeContentPadding
            var last = withFrameNanos { it }
            while (true) {
                val item = listState.layoutInfo.visibleItemsInfo.firstOrNull { it.index == active } ?: break
                val diff = item.offset + inParagraph - anchor
                if (abs(diff) < ARRIVED) break
                val now = withFrameNanos { it }
                val ms = (now - last) / 1_000_000.0
                last = now
                listState.scrollBy(glideBy(diff.toDouble(), ms).toFloat())
            }
        }
    }
}

private fun isHeading(kind: String) = kind == "heading" || kind == "title"
private fun prefixOf(kind: String) = if (kind == "list_item") "• " else ""

/** A paragraph that is not being read: one piece of text, stepped back. */
@OptIn(ExperimentalTvMaterial3Api::class)
@Composable
private fun PlainParagraph(paragraph: Paragraph, colour: Color) {
    Text(
        text = prefixOf(paragraph.kind) + paragraph.text,
        style = if (isHeading(paragraph.kind)) Type.BodyHeading else Type.Body,
        color = colour,
        modifier = Modifier.fillMaxWidth(),
    )
}

/**
 * The paragraph being read. Cut into sentences where the render knows them (or chunks, or lit whole), with the one
 * being spoken marked. It tells its caller where that line is, once it has been laid out, so the text can glide there.
 */
@OptIn(ExperimentalTvMaterial3Api::class)
@Composable
private fun ActiveParagraph(
    index: Int,
    paragraph: Paragraph,
    words: List<String>,
    units: List<SpokenUnit>?,
    unit: Int,
    onLitTop: (Int, Float) -> Unit,
) {
    val prefix = prefixOf(paragraph.kind)
    val style = if (isHeading(paragraph.kind)) Type.BodyHeading else Type.Body
    val (body, ranges) = remember(words, units) {
        if (units != null) unitRanges(words, units) else paragraph.text to emptyList()
    }
    val text = remember(body, ranges, unit) {
        buildAnnotatedString {
            append(prefix + body)
            ranges.forEachIndexed { k, range ->
                val colour = when {
                    unit < 0 -> Tok.Ink2             // before its first sentence: all still to come
                    k < unit -> Tok.Ink              // already spoken: bright
                    k == unit -> Tok.Brand           // being spoken
                    else -> Tok.Ink2                 // still to come: softer
                }
                addStyle(
                    SpanStyle(color = colour, background = if (k == unit) Tok.BrandSoft else Color.Unspecified),
                    prefix.length + range.first, prefix.length + range.last + 1,
                )
            }
        }
    }
    var layout by remember { mutableStateOf<TextLayoutResult?>(null) }
    val litAt = if (units != null && unit in ranges.indices) prefix.length + ranges[unit].first else 0
    LaunchedEffect(layout, litAt) {
        val l = layout ?: return@LaunchedEffect
        val offset = litAt.coerceIn(0, (l.layoutInput.text.length - 1).coerceAtLeast(0))
        onLitTop(index, l.getLineTop(l.getLineForOffset(offset)))
    }
    Text(
        text = text,
        style = style,
        color = if (units == null) Tok.Ink else Tok.Ink2,   // lit whole: bright; cut: the spans say
        onTextLayout = { layout = it },
        modifier = Modifier.fillMaxWidth(),
    )
}
