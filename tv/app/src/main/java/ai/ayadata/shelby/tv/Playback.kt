package ai.ayadata.shelby.tv

import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.MimeTypes
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DataSource
import androidx.media3.datasource.DataSpec
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.datasource.HttpDataSource
import androidx.media3.datasource.TransferListener
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory

const val SHELBY_URL = BuildConfig.SHELBY_URL  // from tv/server.txt at build time; 127.0.0.1 (ADB) when there is none
const val SKIP_BACK_MS = 15_000L      // the web player's steps (web/src/player/engine.tsx)
const val SKIP_FORWARD_MS = 30_000L
private const val SAVE_EVERY_MS = 5_000L
private const val TAG = "ShelbyTV"

/**
 * One book playing: its chapters as a playlist, so a chapter that ends is followed by the next with no
 * code of ours. The audio is streamed from Shelby: ExoPlayer asks for the byte ranges it needs, with the
 * access token in a header, so a chapter starts before it has arrived and a skip fetches only what it needs
 * (unlike the web app, which loads a file whole).
 *
 * The state the screens read is Compose state, so a screen that reads it redraws when it changes. The
 * position is not: it moves four times a second, and only the progress bar reads it (by asking).
 *
 * Lives as long as the process, held by [ShelbyApplication], not by the activity: the book plays on with the screen off
 * or another app in front, and [PlaybackService] (started here when something is about to play) is what keeps the
 * process alive and gives the remote's media keys somewhere to go (plan.md, step 7).
 */
@UnstableApi
class Playback(context: Context, token: String, val places: Places) {
    private val appContext = context.applicationContext
    private val handler = Handler(Looper.getMainLooper())

    /** Logs the byte each request starts from: how a seek is checked (a seek is a request from a new byte). */
    private val transfers = object : TransferListener {
        override fun onTransferInitializing(source: DataSource, dataSpec: DataSpec, isNetwork: Boolean) {}
        override fun onTransferStart(source: DataSource, dataSpec: DataSpec, isNetwork: Boolean) {
            Log.i(TAG, "request: file ${dataSpec.uri.lastPathSegment?.take(8)} from byte ${dataSpec.position}")
        }
        override fun onBytesTransferred(source: DataSource, dataSpec: DataSpec, isNetwork: Boolean, bytesTransferred: Int) {}
        override fun onTransferEnd(source: DataSource, dataSpec: DataSpec, isNetwork: Boolean) {}
    }

    private val http = DefaultHttpDataSource.Factory()
        .setDefaultRequestProperties(mapOf("x-assistant-token" to token))
        .setConnectTimeoutMs(15_000)
        .setReadTimeoutMs(30_000)
        .setTransferListener(transfers)

    val player: ExoPlayer = ExoPlayer.Builder(context)
        .setMediaSourceFactory(DefaultMediaSourceFactory(http))
        .setAudioAttributes(
            AudioAttributes.Builder().setUsage(C.USAGE_MEDIA).setContentType(C.AUDIO_CONTENT_TYPE_SPEECH).build(),
            /* handleAudioFocus = */ true,
        )
        .setHandleAudioBecomingNoisy(true)
        // With the screen off the TV may sleep its processor and its Wi-Fi; this holds both while a chapter plays
        // (it streams, so it needs the network as well as the processor). Released by the player when it pauses.
        .setWakeMode(C.WAKE_MODE_NETWORK)
        .build()

    var bookKey by mutableStateOf<String?>(null); private set
    var chapters by mutableStateOf<List<Chapter>>(emptyList()); private set
    var book by mutableStateOf<Book?>(null); private set
    var index by mutableIntStateOf(-1); private set
    var isPlaying by mutableStateOf(false); private set
    var ended by mutableStateOf(false); private set
    /** Why playback failed, in words for the person holding the remote; null when it has not. */
    var error by mutableStateOf<String?>(null); private set

    val currentChapter: Chapter? get() = chapters.getOrNull(index)
    fun position(): Long = player.currentPosition
    fun duration(): Long = player.duration.takeIf { it != C.TIME_UNSET } ?: 0L

    private var pressedAt = 0L
    private var soundLogged = true
    /** True from the moment a new set of chapters is handed over until it is ready: events from the old
     *  ones must not be saved as the new book's place. */
    private var switching = false

    init {
        player.addListener(object : Player.Listener {
            override fun onIsPlayingChanged(isPlaying: Boolean) {
                this@Playback.isPlaying = isPlaying
                if (isPlaying) {
                    if (!soundLogged) {
                        soundLogged = true
                        Log.i(TAG, "first sound ${SystemClock.elapsedRealtime() - pressedAt} ms after play was pressed")
                    }
                    scheduleSave()
                } else {
                    saveNow()
                }
            }

            override fun onPlaybackStateChanged(state: Int) {
                if (state == Player.STATE_READY) {
                    if (switching) {
                        switching = false
                        Log.i(TAG, "ready ${SystemClock.elapsedRealtime() - pressedAt} ms after play was pressed, length ${player.duration} ms")
                    }
                }
                if (state == Player.STATE_ENDED) {
                    ended = true
                    bookKey?.let { places.clear(it) }
                    Log.i(TAG, "the book ended")
                }
            }

            override fun onMediaItemTransition(mediaItem: MediaItem?, reason: Int) {
                index = player.currentMediaItemIndex
                if (reason == Player.MEDIA_ITEM_TRANSITION_REASON_AUTO) {
                    Log.i(TAG, "chapter ended, next is ${currentChapter?.title}")
                    val key = bookKey; val chapter = currentChapter
                    if (key != null && chapter != null) places.save(key, chapter.id, 0)
                }
            }

            override fun onTimelineChanged(timeline: androidx.media3.common.Timeline, reason: Int) {
                // The player may revise a chapter's length once it has read the file: logged so it is seen.
                Log.i(TAG, "length of the current chapter is now ${player.duration} ms (timeline change, reason $reason)")
            }

            override fun onPositionDiscontinuity(old: Player.PositionInfo, new: Player.PositionInfo, reason: Int) {
                if (reason == Player.DISCONTINUITY_REASON_SEEK) {
                    Log.i(TAG, "seek: chapter ${old.mediaItemIndex} at ${old.positionMs} ms -> chapter ${new.mediaItemIndex} at ${new.positionMs} ms")
                }
            }

            override fun onPlayerError(e: PlaybackException) {
                error = describe(e)
                Log.w(TAG, "player error: ${e.errorCodeName} ${e.cause}")
            }
        })
    }

    /** Start a book: its chapters as a playlist, from chapter `index` at `startMs`. */
    fun start(book: Book, chapters: List<Chapter>, index: Int, startMs: Long) {
        saveNow()
        switching = true
        this.book = book
        bookKey = book.key
        this.chapters = chapters
        this.index = index
        ended = false
        error = null
        begin()
        keepAlive()
        player.setMediaItems(chapters.map { item(book, it) }, index, startMs)
        player.prepare()
        player.play()
    }

    /** Go to another chapter of the book already loaded. */
    fun jumpTo(index: Int, startMs: Long) {
        saveNow()
        ended = false
        error = null
        begin()
        keepAlive()
        switching = true
        this.index = index
        player.seekTo(index, startMs)
        player.prepare()
        player.play()
    }

    fun toggle() {
        if (player.isPlaying) {
            player.pause()
        } else {
            if (player.playbackState == Player.STATE_ENDED) player.seekTo(0, 0)
            begin(); soundLogged = true   // resuming is not a first sound
            keepAlive()
            player.play()
        }
    }

    fun skipBack() = seekBy(-SKIP_BACK_MS)

    fun skipForward() = seekBy(SKIP_FORWARD_MS)

    /** Go to a time in the chapter playing (a paragraph skip in follow-along). */
    fun seekToMs(ms: Long) {
        player.seekTo(ms.coerceAtLeast(0))
    }

    fun next() = player.seekToNextMediaItem()

    fun previous() = player.seekToPreviousMediaItem()

    private fun seekBy(delta: Long) {
        val length = player.duration
        val target = (player.currentPosition + delta).coerceAtLeast(0)
        if (length != C.TIME_UNSET && target >= length) {
            if (player.hasNextMediaItem()) player.seekToNextMediaItem() else player.seekTo(length)
        } else {
            player.seekTo(target)
        }
    }

    /** Start the service that keeps the process (and so the book) alive when the screen is not showing. From the
     *  foreground only: Android 12 refuses to start one from the background, and says so with an exception. */
    private fun keepAlive() {
        try {
            appContext.startService(Intent(appContext, PlaybackService::class.java))
        } catch (e: IllegalStateException) {
            Log.w(TAG, "could not start the playback service: ${e.message}")
        }
    }

    private fun begin() {
        pressedAt = SystemClock.elapsedRealtime()
        soundLogged = false
    }

    private fun item(book: Book, chapter: Chapter) = MediaItem.Builder()
        .setMediaId(chapter.id)
        .setUri("$SHELBY_URL/api/files/${chapter.audioFileId}")
        .setMimeType(MimeTypes.AUDIO_MPEG)
        .setMediaMetadata(
            MediaMetadata.Builder().setTitle(chapter.title).setAlbumTitle(book.title)
                .apply { if (book.author.isNotEmpty()) setArtist(book.author) }.build(),
        )
        .build()

    private fun saveNow() {
        if (switching || player.playbackState == Player.STATE_ENDED) return
        val key = bookKey ?: return
        val chapter = currentChapter ?: return
        places.save(key, chapter.id, player.currentPosition)
    }

    private val saveTick = object : Runnable {
        override fun run() {
            saveNow()
            if (player.isPlaying) handler.postDelayed(this, SAVE_EVERY_MS)
        }
    }

    private fun scheduleSave() {
        handler.removeCallbacks(saveTick)
        handler.postDelayed(saveTick, SAVE_EVERY_MS)
    }

    private fun describe(e: PlaybackException): String {
        val http = generateSequence<Throwable>(e) { it.cause }.filterIsInstance<HttpDataSource.InvalidResponseCodeException>().firstOrNull()
        return when {
            http?.responseCode == 401 -> "Shelby refused the app’s access token. It changes whenever the backend restarts, so the app has to be built again."
            http?.responseCode == 404 -> "That chapter’s audio is no longer in Shelby."
            http != null -> "Shelby answered with error ${http.responseCode}."
            e.errorCode == PlaybackException.ERROR_CODE_IO_NETWORK_CONNECTION_FAILED ||
                e.errorCode == PlaybackException.ERROR_CODE_IO_NETWORK_CONNECTION_TIMEOUT -> "Can’t reach Shelby. Is it running?"
            else -> "This chapter can’t be played (${e.errorCodeName})."
        }
    }
}
