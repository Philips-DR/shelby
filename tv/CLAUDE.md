# Shelby TV — rules and gotchas

A native Android TV app (Kotlin, Jetpack Compose for TV), sideloaded to the user's TV. It talks to Shelby's
backend over HTTP and shares no code with any other part of Shelby. **`plan.md` holds the state, the
measurements and the decisions; this file holds the rules.** Read both before changing anything.

## Build, install, test

    export JAVA_HOME=~/jdks/jdk-17 ANDROID_HOME=~/Android/Sdk PATH=$JAVA_HOME/bin:$PATH
    cd tv
    ./gradlew assembleRelease                     # the build that goes on the TV (about 3.6 MB)
    ./gradlew testDebugUnitTest                   # the chapter rules, on real data
    adb connect 192.168.70.103:5555               # the address can move: see the home-tv memory
    adb -s 192.168.70.103:5555 install -r app/build/outputs/apk/release/app-release.apk
    adb -s 192.168.70.103:5555 shell cmd package compile -m speed -f ai.ayadata.shelby.tv   # once per install
    adb -s 192.168.70.103:5555 reverse tcp:8750 tcp:8750     # only with no tv/server.txt: the ADB route (see below)

**Where Shelby is** comes from the git-ignored `tv/server.txt`, read at build time: one line such as
`http://192.168.70.108:8750`, the laptop's address on the home network (the `SHELBY_HOME_ADDRESS` in the root `.env`, which
makes `./start-docker up` publish the backend's port there). The TV then needs no ADB at all. With no `server.txt` the app
uses `http://127.0.0.1:8750`, which only works through the `adb reverse` line above (it must be run again whenever ADB
reconnects). The build refuses an address that is not private (127.x, 10.x, 172.16-31.x, 192.168.x), because the same
address is the only one the app may speak plain http to.

The access token is read at build time from `tv/token.txt` (one line). **Since 2026-11-23 it is the TV's own token, the
`ASSISTANT_TV_TOKEN` in the root `.env`: fixed, so a backend restart no longer breaks the installed app.** It may play
books and nothing else (`assistant/CLAUDE.md` -> Scoped tokens): the app must stay inside what `tools.yaml` grants the
`tv` scope, and a call outside it is a 403. Before that date the file held the launch token, which changes on every
`./start-docker up`; an APK built then says "Can't reach Shelby" and must be rebuilt.

The root `./test` runs these unit tests too (`--offline --no-daemon`) when `~/jdks/jdk-17` and `~/Android/Sdk` exist;
without them it prints SKIPPED and ends with `NOT RUN: tv`, never a plain "All passed". It needs the libraries Gradle kept
from the first build (run `assembleDebug` once, with the network); after that it needs none. To prove that, run the tests
in a namespace with no network: `unshare -rn sh -c 'ip link set lo up; ./gradlew testDebugUnitTest --offline --no-daemon'`,
with `GRADLE_USER_HOME`, `ANDROID_USER_HOME` and `-Duser.home` set to the real folders, because there Java finds the home
of uid 0 (`/root`) and Gradle fails with "Could not create parent directory for lock file". Checked 2026-11-23: 46 pass.
Gradle does not run the tests again when nothing in `tv/` has changed since the last run (`:app:testDebugUnitTest
UP-TO-DATE`), so a quiet pass in `./test` can mean that; add `--rerun-tasks` when a run has to be real.

## Rules

- **The repository is public.** `token.txt`, any APK (it carries the token), `local.properties` and build
  output are in `tv/.gitignore`. Never print the token, never put it in a doc, a test or a commit. On
  2026-11-22 `token.txt` was found NOT ignored; check with `git check-ignore tv/token.txt` after any change
  to ignore files. Stage by explicit path; run `./publish-check` before any push.
- **The plain-http rule is generated, not written.** `res/xml/network_security_config.xml` is not in the source tree:
  `app/build.gradle.kts` writes it (task `writeNetworkConfig`, into `build/generated/shelby/res`) from `tv/server.txt`, so
  the address the app calls and the one it may use plain http for cannot disagree. Do not add a file of that name back: the
  build then fails with a duplicate resource. 127.0.0.1 stays in it, for development over ADB. `server.txt` is private
  (git-ignored, with `token.txt`): it is the address of somebody's home network, in a public repository.
- **Taking the TV's screen can close what someone left on it.** On 2026-11-23, with VLC paused on a video (an episode, 11:35
  in) and the screen awake, launching this app put it in front and VLC's session went to "stopped"; its video screen was no
  longer in its stack afterwards, only its browse screen. Whether VLC remembers the place was not checked. Before a test that
  launches the app, look at what is in front (`dumpsys activity activities | grep mResumedActivity`) and at the media
  sessions (`dumpsys media_session`): a paused video is somebody's, and say so afterwards.
- **A request from the TV, without a tool on it.** The TV has no curl, nc or wget (toybox has only ping and netstat). To make
  the requests that really come from the TV (a wrong token, a Host that is not listed), compile a one-off Java class with
  `javac --release 8`, turn it into a dex with `~/Android/Sdk/build-tools/34.0.0/d8`, push it to `/data/local/tmp` and run
  `CLASSPATH=/data/local/tmp/x.dex app_process /system/bin X args`, then delete it. Catch exceptions and print them: an
  uncaught one makes Android kill the process (exit 137, "Killed") and says nothing, which looks like a hang.
- **`tv` stays in the root `.dockerignore`.** The backend image copies the whole repo (`COPY . /app` in
  `docker/backend.Dockerfile`), and until 2026-11-23 it held this folder: `token.txt`, a debug APK, a release APK
  (which carries the token) and 210 MB in all. After any change to ignore files or the Dockerfile, check the image:
  `docker run --rm --entrypoint sh shelby-backend -c 'ls /app/tv'` must say there is no such directory (an image built
  before the fix still has it until the backend is rebuilt).
- **Judge speed on the release build only.** A debug build is several times slower under Compose
  (shelf 77% late frames on debug, 5% on release). Measure on the real TV, every time, with the same
  keystrokes and the same book. State which build a number came from.
- **Draw once, show a picture.** Anything big, static and expensive (gradients, large glyphs, full-screen
  backgrounds) is drawn once into a bitmap (`Art.kt`) and shown as an image. Drawing covers live made the
  shelf run at 65 ms a frame. No blur, no big shadows, no many-things-animating: this TV's graphics are weak.
- **The look comes from the web app's tokens** (`web/src/styles/tokens.css`, `web/DESIGN.md`), dark only.
  Colours and fonts are in `Theme.kt`: never write a literal colour or font in a screen. The audiobook colour
  is for books and nothing else; the teal accent is for focus.
- **Which chapter files make a book is decided by `ChapterChoice.kt`**, not by "newest wins". "Newest per
  number" picked the wrong chapter in 14 of 19 slots for a book that had been read twice. The rule mirrors the
  web app (`audiobookKept.ts`, `withKept`); if that changes, change this and its test.
- **The follow-along rules are a copy of the web app's** (`FollowRules.kt` from `audiobookSentences.ts`,
  `audiobookTiming.ts`, `audiobookGlide.ts` and the paragraph skip in `AudioFollow.tsx`). A change there means a
  change here. They were held to the web code's own answers on 11 real chapters (505 paragraphs, 33,011 samples, no
  difference) and three of those are fixtures (`src/test/resources/follow`): timing and word counts only, because the
  text is copyrighted. **Never put a book's text in a fixture, a test or a commit.** To redo the check: a temporary
  vitest spec in `web/src/components` that stubs `../api` and writes what the web's real modules say, compared with
  the Kotlin; delete the spec in the same step.
- **Say the truth on screen.** When the app cannot tell something, it says so in plain words; it does not
  guess. Error text is for the person holding the remote, not for a developer.

## Gotchas

- An XML comment may not contain `--` (the build fails with a message about it). Do not quote web token
  names such as `--bg` in `res/` comments.
- Android cannot read WOFF2, which is what the web app bundles. The fonts here are TTFs from Google Fonts
  (SIL OFL): Bricolage Grotesque (titles), Instrument Sans (everything else). The licence texts, which the
  OFL asks to travel with the fonts, are in `tv/licenses/` (from Google Fonts' own repository, 2026-11-23); not in
  `res/font`, which takes only font files. A new font means its licence file goes there in the same change.
- The default theme draws a grey action bar and a white flash on start; `Theme.Shelby` removes both.
- Compose for TV's `BackHandler` does not catch Back while a TV-material list item has focus: the activity
  holds an `OnBackPressedCallback`, enabled only while a book is open, so Back on the shelf leaves the app.
- A focus request before the item is drawn throws; wait one frame (`awaitFrame()`) and catch it.
- The TV is shown at 1920x1080 at 2x density: the screen is 960 x 540 dp. Keep 48 dp from the left and
  right edges (overscan).
- `dumpsys gfxinfo` counts only frames that were drawn: a screen that does not change shows few frames.
  Check the screenshot, not just the number, or you may measure a screen that was not the one you meant.
- `adb install -r` over a build signed with another key fails: every build here uses the debug key.
- **The player (`Playback.kt`) logs under the tag `ShelbyTV`**: when play was pressed to ready and to first sound,
  every seek (from and to), and the byte each HTTP request starts from. A seek is a request from a new byte, so
  the log is how seeking is checked against the real file (see plan.md, step 5). Forward skips inside what is
  already loaded make no request.
- **Read the TV's log as a live stream, not afterwards.** Its log buffer is small and full of the system's own
  messages, so an hour-old `logcat -d` has lost the start. Start the stream before the test and stop it after.
- **`pkill -f` kills your own shell if its pattern appears anywhere in the command you are running** (exit code
  144), including as text in a command that starts the log. Put starting and stopping the stream in separate
  script files and keep the pattern out of the command that calls them.
- **`switching` in `Playback` is not decoration.** When a new book is handed over, events from the old
  chapters arrive for a moment; without the guard they are saved as the new book's place.
- **A number read from a downscaled screenshot is a guess.** One total time was read as 0:54 from a half-size
  picture and was 0:57; the full-size crop settled it. Crop the original before reporting.
- **Seeking depends on how the audio was encoded.** Today's chapters are variable-bitrate MP3 with a
  100-point table, and a skip lands seconds from the time shown (plan.md, step 5). Constant bitrate seeks
  exactly. Do not build anything that needs the position to match the audio to the second (follow-along does)
  without saying which kind of file it was tested on.
- **Saved places survive a new install.** `adb install -r` keeps them; `adb shell pm clear ai.ayadata.shelby.tv`
  wipes them. Clear before any test that needs a book with no place, or the list will land on a "Resume".
- **Follow-along: a paragraph that is not drawn cannot say where its line is.** The glide must jump to the active
  paragraph first (`scrollToItem`), and only then wait for the paragraph to report; the other order waited for ever
  and the text stuck while the voice moved on (seen on the TV).
- **A lazy list's item offsets start where the content starts, after `contentPadding`**, not at the top of the list.
  The anchor line is `0.42 * viewport height - beforeContentPadding` in those coordinates. Measured from the top, the
  lit line settled 85% of the way down and ran off the screen (seen on the TV).
- **Look at the screen, and check it against the data, before believing a follow-along change.** Both bugs above
  passed every unit test: they were in how the screen moved, not in the rules. Pause at a known time, take a
  screenshot, and compute from the real timing and text which sentence should be lit.
- **Do not put the literal log command in the same command as `pkill`.** I hit exit 144 four times in one day, once
  after writing the rule down. Write start and stop scripts with the file-writing tool (never with `printf` or a
  heredoc inside a command that also calls them), or filter the log by saved file and `kill` a saved pid.
- **A saved place moves where the chapter list lands.** After any test that plays, `pm clear` before navigating by
  counting key presses, or the count starts from "Resume" and not from the first row.
- **The text takes 2 to 4 s to open** (the PDF is read each time); the audio does not wait. If that is too slow, the
  next chapter's text can be fetched while this one plays (not built).
- **The player belongs to the process, not the screen (step 7).** `ShelbyApplication.playback` holds the one `Playback`;
  `PlaybackService` (a Media3 `MediaSessionService`, foreground type media playback) wraps its ExoPlayer in a session and
  is started by `Playback` just before anything plays. Never release the player from the activity: Back from the shelf
  finishes the activity and the book must play on (it did not before, because `onDestroy` released the player). The
  service is exported so the system can reach it; `mayControl()` (tested) lets only this app, the system and the
  service's own notification connect as controllers. Start the service from the foreground only: Android 12 refuses from
  the background.
- **Check what Android thinks of the app, not just whether sound comes out.** Playing with Home pressed already made
  sound before step 7, but the process sat at priority 700 (cached: the first to be closed on a 1.8 GB TV) and the
  player's wake lock was switched off. Now 50 to 200 (foreground service) and the wake lock is held. Read them with
  `cat /proc/<pid>/oom_score_adj`, `dumpsys activity services ai.ayadata.shelby.tv` (`isForeground=true`),
  `dumpsys power` (the line for `ExoPlayer:WakeLockManager` under "Wake Locks": `DISABLED` means off; the log above it lists
  old ones and fools a plain grep) and `dumpsys media_session` (state 3 playing, 2 paused, and the position).
- **Test the remote's media keys with the launcher in front.** `input keyevent KEYCODE_MEDIA_PAUSE` reaches the session
  only if the app in front does not swallow the key: YouVersion does, Projectivy does not. `cmd media_session dispatch`
  fails on this TV ("packageName may not be empty").
- **The launcher's now-playing card is a different caller from the remote's keys, and was broken until 2026-11-23.** The keys
  come from the system (always visible to this app); the card's buttons come from the launcher (`app.tvhome`), which this app
  could not see on Android 11+ without `<queries>`, so Android did not call it trusted and `mayControl()` rejected it, silently.
  The manifest now asks for the home screen's intent. **Any new caller that must control the session needs the same check**, and
  `PlaybackService` logs each controller under `ShelbyTV` (`controller <package>: trusted=… -> accepted/REJECTED`): look there first
  when a button does nothing. Android's own hint is `Package <name> doesn't exist` (tag `MediaSessionManager`). To test the card by
  remote with the launcher in front: Up from the app row focuses it, then Enter is play/pause, Left previous, Right next
  (`input tap` on the buttons does nothing). A check that passes for the remote's keys says nothing about the card.
- **Nothing is polled while the screen is not showing.** The 10 Hz follow-along tick, the 4 Hz bar and the shelf strip's
  1 Hz tick run inside `repeatOnLifecycle(STARTED)`; a new loop that reads the player must do the same.
- **The strip on the shelf** (`NowPlayingStrip.kt`): Down from the books lands on play/pause (`focusProperties { enter }`;
  `focusRestorer` with a fallback did not land on the fallback), and Up returns to the book that was focused
  (`focusRestorer()` on the row; without it focus went to the nearest tile). Its pictures are drawn shapes, not glyphs.
- **A stray key can open TCL's quick panel and send the TV to live TV** (seen once, 23:38 on 2026-11-22, with the app
  in front; not reproduced). Before a key-driven test, check the front activity.
- **`settings put global always_finish_activities 1` does nothing here.** To destroy the activity while the book plays,
  press Back on the shelf.

