package ai.ayadata.shelby.tv

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Who may play, pause and skip the book from outside the screen (the service is exported, so this is the door's lock). */
class MayControlTest {
    private val me = "ai.ayadata.shelby.tv"

    @Test fun anotherInstalledAppMayNot() {
        assertFalse(mayControl("com.example.other", me, trustedBySystem = false, isOwnNotification = false))
    }

    @Test fun theSystemMay() {
        // the remote's media keys and the TV's own controls arrive as a caller the system trusts
        assertTrue(mayControl("com.android.systemui", me, trustedBySystem = true, isOwnNotification = false))
    }

    @Test fun theAppItselfMay() {
        assertTrue(mayControl(me, me, trustedBySystem = false, isOwnNotification = false))
    }

    @Test fun theNotificationTheServiceMakesMay() {
        // without this the service cannot show what is playing, nor become a foreground service
        assertTrue(mayControl("androidx.media3.session", me, trustedBySystem = false, isOwnNotification = true))
    }

    @Test fun anAppNamedLikeMeButNotMeMayNot() {
        assertFalse(mayControl("ai.ayadata.shelby.tv.fake", me, trustedBySystem = false, isOwnNotification = false))
    }
}
