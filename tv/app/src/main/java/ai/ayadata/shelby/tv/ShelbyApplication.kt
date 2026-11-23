package ai.ayadata.shelby.tv

import android.app.Application
import androidx.media3.common.util.UnstableApi

/**
 * Holds the one [Playback] for as long as the process lives, which is longer than the screen: the activity can be
 * stopped (Home, another app in front, the screen off) or even destroyed while the book plays on, and
 * [PlaybackService] is what keeps the process alive meanwhile (plan.md, step 7). Made the first time something asks.
 */
@UnstableApi
class ShelbyApplication : Application() {
    val playback: Playback by lazy { Playback(this, BuildConfig.API_TOKEN, Places(this)) }
}
