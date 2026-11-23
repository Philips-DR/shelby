package ai.ayadata.shelby.tv

import android.app.PendingIntent
import android.content.Intent
import android.util.Log
import androidx.media3.common.util.UnstableApi
import androidx.media3.session.MediaSession
import androidx.media3.session.MediaSessionService

/**
 * Keeps the book playing when the screen goes off or another app comes to the front.
 *
 * Three things come with it, and each is a separate reason the audio would otherwise stop or the app be closed:
 *  - Android treats an app with a playing media session as one the person is using: it runs as a foreground service
 *    (Media3 makes it one when playback starts and lets go 10 minutes after it pauses), so it is not among the first
 *    to be closed when this TV's 1.8 GB runs short;
 *  - the session is what the remote's play, pause and skip keys are sent to when another app is in front;
 *  - the notification it shows (the TV lists it) says what is playing.
 *
 * The player itself is not here: it is [Playback]'s, in the application, so the screen and this service share it.
 * Releasing the session does not release the player.
 */
private const val TAG = "ShelbyTV"

@UnstableApi
class PlaybackService : MediaSessionService() {
    private var session: MediaSession? = null

    override fun onCreate() {
        super.onCreate()
        val playback = (application as ShelbyApplication).playback
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val made = MediaSession.Builder(this, playback.player)
            .setId("shelby")
            .setSessionActivity(open)
            .setCallback(object : MediaSession.Callback {
                override fun onConnect(session: MediaSession, controller: MediaSession.ControllerInfo): MediaSession.ConnectionResult {
                    val own = session.isMediaNotificationController(controller)
                    val allowed = mayControl(controller.packageName, packageName, controller.isTrusted, own)
                    // A refusal is silent to the one refused (its buttons just do nothing), so say it here.
                    Log.i(TAG, "controller ${controller.packageName}: trusted=${controller.isTrusted} ownNotification=$own -> ${if (allowed) "accepted" else "REJECTED"}")
                    return if (allowed) MediaSession.ConnectionResult.AcceptedResultBuilder(session).build()
                    else MediaSession.ConnectionResult.reject()
                }
            })
            .build()
        session = made
        addSession(made)
    }

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaSession? = session

    override fun onDestroy() {
        session?.release()
        session = null
        super.onDestroy()
    }
}

/**
 * Who may play, pause and skip: this app, what Android itself calls trusted (the remote's media keys come from the system;
 * the launcher's now-playing card from the launcher, an enabled notification listener), and the notification this service
 * makes. Another installed app may not (the service is exported so the system can reach it, which would otherwise let any
 * app on the TV control the book).
 *
 * "Trusted" is only true for an app this one can see: from Android 11 that needs `<queries>` in the manifest, and without
 * it the launcher is untrusted and its buttons do nothing (they did nothing until 2026-11-23).
 */
fun mayControl(callerPackage: String, ownPackage: String, trustedBySystem: Boolean, isOwnNotification: Boolean): Boolean =
    isOwnNotification || trustedBySystem || callerPackage == ownPackage
