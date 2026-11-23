package ai.ayadata.shelby.tv

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.RadialGradient
import android.graphics.Shader
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.FilterQuality
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.layout.ContentScale

/**
 * Pictures drawn ONCE and shown as images.
 *
 * The first version drew each cover live: a gradient, a 120 sp letter and a darkening layer, times seven
 * covers on screen, plus a full-screen gradient behind them, all redone on every frame while the shelf
 * slid. On this TV that was 65 ms a frame (about 15 per second, 62% of frames late) in a release build, and
 * every late frame was late in the drawing, not in our code. A finished picture is one cheap image copy per
 * frame. Measured result is in tv/plan.md.
 */

/** The pixel size of a cover: 150 x 210 dp at this TV's 2x density, so it is shown 1:1 and stays sharp. */
private const val COVER_W = 300
private const val COVER_H = 420

private val covers = HashMap<String, ImageBitmap>()
private var backdrop: ImageBitmap? = null

/** The first letter or digit of a title, for the big letter behind a cover. */
fun initialOf(title: String): String = title.firstOrNull { it.isLetterOrDigit() }?.uppercase() ?: "•"

/**
 * A book's cover: the audiobook colour fading into the surface, a large soft initial, and (with
 * `withScrim`) a darkening at the foot for the title to sit on. The direction of the fade comes from the
 * title, so neighbours differ a little without leaving the one colour (a tool has one colour everywhere,
 * web/DESIGN.md rule 3). Main thread only; at most one picture per book.
 */
fun coverBitmap(context: Context, title: String, withScrim: Boolean): ImageBitmap =
    covers.getOrPut("$withScrim|$title") {
        val w = COVER_W.toFloat()
        val h = COVER_H.toFloat()
        val bitmap = Bitmap.createBitmap(COVER_W, COVER_H, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bitmap)
        val paint = Paint(Paint.ANTI_ALIAS_FLAG or Paint.DITHER_FLAG)

        // the fade: same four directions the title's hash picks between
        val (x0, y0, x1, y1) = when ((title.hashCode() and 0x7fffffff) % 4) {
            0 -> floatArrayOf(0f, 0f, w, h)
            1 -> floatArrayOf(w, 0f, 0f, h)
            2 -> floatArrayOf(0f, 0f, 0f, h)
            else -> floatArrayOf(w, h, 0f, 0f)
        }
        paint.shader = LinearGradient(
            x0, y0, x1, y1,
            Tok.Book.copy(alpha = 0.55f).toArgb(), Tok.Surface2.toArgb(), Shader.TileMode.CLAMP,
        )
        canvas.drawRect(0f, 0f, w, h, paint)

        // the big soft initial, top right, running off the edge a little
        val letter = initialOf(title)
        val text = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            typeface = context.resources.getFont(R.font.bricolage_bold)
            textSize = 240f
            color = android.graphics.Color.argb(26, 255, 255, 255)   // white at 10%
        }
        canvas.drawText(letter, w - text.measureText(letter) + 20f, 190f, text)

        if (withScrim) {
            val scrim = Paint(Paint.DITHER_FLAG)
            scrim.shader = LinearGradient(
                0f, h * 0.40f, 0f, h,
                Tok.Bg.copy(alpha = 0f).toArgb(), Tok.Bg.copy(alpha = 0.88f).toArgb(), Shader.TileMode.CLAMP,
            )
            canvas.drawRect(0f, h * 0.40f, w, h, scrim)
        }
        bitmap.asImageBitmap()
    }

/**
 * The faint magenta glow behind every screen. A smooth gradient, so it is drawn small (480 x 270) and
 * stretched: a quarter-megabyte picture instead of a 1080p gradient to fill on every frame.
 */
fun backdropBitmap(): ImageBitmap = backdrop ?: run {
    val w = 480
    val h = 270
    val bitmap = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
    val canvas = Canvas(bitmap)
    canvas.drawColor(Tok.Bg.toArgb())
    val paint = Paint(Paint.DITHER_FLAG)
    paint.shader = RadialGradient(
        65f, 0f, 375f,
        Tok.Book.copy(alpha = 0.16f).toArgb(), Tok.Book.copy(alpha = 0f).toArgb(), Shader.TileMode.CLAMP,
    )
    canvas.drawRect(0f, 0f, w.toFloat(), h.toFloat(), paint)
    bitmap.asImageBitmap().also { backdrop = it }
}

@Composable
fun Backdrop() {
    val art = remember { backdropBitmap() }
    Image(
        bitmap = art,
        contentDescription = null,
        modifier = Modifier.fillMaxSize(),
        contentScale = ContentScale.FillBounds,
        filterQuality = FilterQuality.Medium,
    )
}
