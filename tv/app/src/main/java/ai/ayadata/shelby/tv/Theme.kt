package ai.ayadata.shelby.tv

import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.sp
import androidx.tv.material3.ExperimentalTvMaterial3Api
import androidx.tv.material3.MaterialTheme
import androidx.tv.material3.darkColorScheme

/**
 * The look, taken from the web app's dark theme (web/src/styles/tokens.css, web/DESIGN.md), so the TV
 * app is recognisably the same product. A TV is watched from across a room and in a dim one, so only the
 * dark theme exists here. One brand accent (teal); the audiobook tool's own colour (magenta, `--s5`) is
 * used for books and nothing else; status colours are not used yet.
 *
 * Keep these in step with tokens.css. Never write a literal colour or font in a screen: use these.
 */
object Tok {
    // surfaces
    val Bg = Color(0xFF0B0F15)
    val Bg2 = Color(0xFF10161F)
    val Surface = Color(0xFF141A23)
    val Surface2 = Color(0xFF19212C)
    val Line = Color(0x17FFFFFF)        // rgba(255,255,255,0.09)
    val LineStrong = Color(0x2EFFFFFF)  // rgba(255,255,255,0.18)

    // ink
    val Ink = Color(0xFFE6EBF2)
    val Ink2 = Color(0xFFA7B1C2)
    val Ink3 = Color(0xFF8B96A8)

    // brand
    val Brand = Color(0xFF3DD6C6)
    val BrandInk = Color(0xFF06201D)
    val BrandSoft = Color(0x1F3DD6C6)   // 0.12
    val BrandLine = Color(0x663DD6C6)   // 0.40

    // the audiobook tool's colour (palette.ts: slot 5, dark value)
    val Book = Color(0xFFD55181)

    // shape
    const val RCard = 14
    const val RControl = 10
}

/** Bricolage Grotesque for titles, Instrument Sans for everything else: the web app's two faces. */
val Display = FontFamily(
    Font(R.font.bricolage_semibold, FontWeight.SemiBold),
    Font(R.font.bricolage_bold, FontWeight.Bold),
)
val Ui = FontFamily(
    Font(R.font.instrument_regular, FontWeight.Normal),
    Font(R.font.instrument_medium, FontWeight.Medium),
    Font(R.font.instrument_semibold, FontWeight.SemiBold),
)

/** Text styles, sized for reading across a room (the screen is 960 x 540 dp). */
object Type {
    fun display(size: TextUnit, weight: FontWeight = FontWeight.Bold) =
        TextStyle(fontFamily = Display, fontWeight = weight, fontSize = size, lineHeight = size * 1.12f, color = Tok.Ink)

    fun ui(size: TextUnit, weight: FontWeight = FontWeight.Normal, color: Color = Tok.Ink) =
        TextStyle(fontFamily = Ui, fontWeight = weight, fontSize = size, lineHeight = size * 1.3f, color = color)

    val HeroTitle = display(36.sp)
    val ScreenTitle = display(28.sp)
    val TileTitle = display(15.sp, FontWeight.SemiBold)
    val Author = ui(18.sp, FontWeight.Medium, Tok.Ink2)
    val Small = ui(13.sp, FontWeight.Medium, Tok.Ink3)
    val Row = ui(18.sp, FontWeight.Medium)

    /** The chapter's own text in follow-along: larger and looser than a list, for reading across a room. */
    val Body = ui(22.sp, FontWeight.Medium).copy(lineHeight = 33.sp)
    val BodyHeading = display(26.sp, FontWeight.SemiBold).copy(lineHeight = 33.sp)
}

@OptIn(ExperimentalTvMaterial3Api::class)
@Composable
fun ShelbyTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = darkColorScheme(
            primary = Tok.Brand,
            onPrimary = Tok.BrandInk,
            background = Tok.Bg,
            onBackground = Tok.Ink,
            surface = Tok.Surface,
            onSurface = Tok.Ink,
            surfaceVariant = Tok.Surface2,
            onSurfaceVariant = Tok.Ink2,
        ),
        content = content,
    )
}
