# Shelby TV — plan

Written 2026-11-22. **Steps 1 to 8 are done (step 7's last check is noted under it, and step 8's one question was answered); step 9 is done: the TV-only token and the home-network route are built and run on the real TV, with the gaps listed under it.** This file says what we are making, what was checked, what
is still unknown, and the steps in order. Update it as steps finish. Later the same day, at the user's
request, **follow-along was added to version 1**; the checks behind it are under "Follow-along data".

## What we are making

A native Android TV app (Kotlin), installed on the user's TV as an APK with `adb`. It talks to Shelby's
backend over HTTP and nothing else. It is a separate program, like `web/`: its own folder, its own build,
no code shared with any other part of Shelby.

**First piece: the audiobook player.** Pick a book, pick a chapter, play it, **follow the text as it is
read** (the sentence being spoken is lit, as in the web app's follow-along), and drive it all with the
remote. Other tools (Meetings, Mail, Documents) are not part of this.

**Speed matters most.** The TV is slow: 32-bit, 1.8 GB of RAM, and it was swapping and drawing at about
20 frames a second before the 2026-11-21 clean-up (`memory: reference-home-tv`). So the app is kept lean,
and every step is measured on the real TV, not guessed.

## What exists today (checked 2026-11-22 against the running backend)

- **The TV:** Android 12 (API 31), CPU `armeabi-v7a` only, shown at 1920x1080. Reachable over network ADB
  at 192.168.70.103:5555 (the address can change; the memory file says how to find it).
- **Books:** 311 audiobook records are kept. 9 books, 242 chapter MP3s, and 1 whole-book M4B (123 MB,
  "The Final Quest").
- **Chapters carry:** a number (all 242), a title, the book name, and a duration (`seconds`) on only 146
  of the 242. So the app cannot rely on the duration label. The player reads it from the audio.
- **Chapter sizes:** median 1.8 MB, largest 154.5 MB, one is under 0.1 MB (it may be empty; look at it).
- **Listing:** `GET /api/records?tool=audiobook` (with `&kind=chapter` or `&kind=book`). All records come
  to 1.1 MB, and 0.8 MB of that is word-timing data the TV does not need.
- **Audio:** `GET /api/files/{id}` serves the file. A range request returned `206 Partial Content` with
  `accept-ranges: bytes`, so seeking and starting before the whole file arrives should work. `HEAD` is
  refused (405), so the app must use `GET`.
- **Every call needs** the header `x-assistant-token`, and the request's Host must be one the backend
  lists (`127.0.0.1` and `localhost` always are).
- **Duplicates:** 16 chapter numbers have two files with different titles. They look like chapters from an
  earlier reading of the same book. **Not confirmed.** The web app decides which is current by asking the
  tool for the book's own chapter list (`audiobook__book_overview`, through `/api/actions`). The TV app
  must do the same or show both. Look at the real data before building the chapter list.

### Follow-along data (checked 2026-11-22 against the running backend, read-only)

- **The text** comes from `audiobook__read_chapter` (through `/api/actions`), given the book's PDF path,
  the chapter number and a `start`. It returns the paragraphs (each with a kind: paragraph, heading or
  list item) and the spoken announcement ("Chapter eleven"). **It comes in pages.** For the longest
  timed chapter, the first page held 110 of its 149 paragraphs and said `truncated: true` with
  `next_start: 110`. The app must keep asking until it says `truncated: false`. A page is about 24 KB.
- **The PDF path trap.** A chapter record's own `pdf` label is not always usable. The record I tried
  held a path as it was on the host, and the call failed with "no PDF at /home/philip/...". The web app
  takes the path from the uploads list instead. The TV app must do the same: `GET /api/uploads`, match the
  book by its PDF's file name, use that `path`. With that path the same chapter read fine.
- **The timing** is in each chapter record's `timing` label: one entry per paragraph (kind, start, end,
  and chunks; each chunk has a word count and where each of its sentences starts). **The first entry is
  the spoken announcement and has no text**; the rest line up one for one with the text's paragraphs. On
  the real chapter I read, 9 paragraphs against 9 timing entries: same kinds, and the same word count in
  all 9.
- **One record by id:** `GET /api/records/{id}` returns just that chapter's record. For the longest
  timed chapter it was 59 KB, against 1.1 MB for the whole listing. So the TV can get the timing of
  the chapter being played on its own.
- **Coverage is partial.** 136 of the 242 chapters have timing, and every one of those has a start time
  for each sentence. The other 106 have none, and the tool's output folder holds no timing for them
  either:

  | Book | Chapters with timing |
  |---|---|
  | When Godly People Do Ungodly Things | 84 of 84 |
  | Rediscovering Kingdom Worship | 45 of 45 |
  | Myles Munroe 365 Day Devotional | 4 of 4 |
  | Great Expectations | 2 of 19 |
  | Overcoming Addictive Behavior | 1 of 11 |
  | Sharpen Your Discernment | 0 of 36 |
  | Dreams and Visions | 0 of 35 |
  | The Final Quest | 0 of 6 |
  | The Purpose and Power of Woman | 0 of 2 |

  A chapter with no timing can be played and its text shown, but no sentence can be lit.
- **The web app's rules are the spec.** The matching of words to times is in `audiobookSentences.ts`
  (`unitsFor`, `unitAt`), `audiobookTiming.ts` (`spokenSegments`, `activeSegment`) and the glide in
  `audiobookGlide.ts`; their test files hold 17 cases between them. Where the words in a paragraph do not
  add up to the chunks' word counts (the text was corrected after the render), the whole paragraph is
  lit, not its sentences. A sentence's start can be a few tenths of a second out: the render guesses it
  from the text and moves it to the nearest pause in the audio.
- **The web player's steps:** back 15 seconds, forward 30. Previous paragraph goes to the start of the
  paragraph being read, or to the one before it if the current one began less than 2 seconds ago.

## Reaching the backend (decided 2026-11-22: build over ADB, then the home network; not Tailscale)

The backend listens only on this laptop (`127.0.0.1`), by a rule in the root `CLAUDE.md`.

**Status (2026-11-23): built; what was done and checked is under step 9, part 2.** The reasoning below is as decided on
2026-11-22. Where it differs from what was built: publishing the home address is an **opt-in setting** (`SHELBY_HOME_ADDRESS`
in `.env`, which adds `compose.home.yaml`), not a change to the default, so "nothing is published beyond 127.0.0.1" still
holds when it is unset; the token comes from the git-ignored `tv/token.txt` and the address from the git-ignored
`tv/server.txt`, both at build time; and the plain-http permission for one IP address is written by the build and works on
this TV (the "not yet checked" at the end of this section is answered).

- **While building:** `adb reverse tcp:8750 tcp:8750`, so the TV reaches the backend through the ADB link.
  Nothing is exposed and no Shelby rule changes. It works only while ADB is connected.
- **Daily use: the home network.** The user's choice on 2026-11-22; Tailscale is out. At step 9 the
  backend is published on the laptop's home address and the TV calls it over plain http. **This breaks
  the root rule "nothing is published beyond 127.0.0.1"**, so that rule, the comment at the top of
  `compose.yaml` and the README are rewritten in the same change to say what is then true. To settle at
  step 9:
  - Publish only the laptop's home address in `compose.yaml`, not every address.
  - Add that address to `ASSISTANT_HOSTS`. The backend answers 403 to any Host that is not listed (read in
    `assistant/server.py`).
  - The laptop has two home addresses today (192.168.70.108 wired, 192.168.70.164 Wi-Fi). Give it a fixed
    one in the router, or the TV loses it when the address changes.
  - The laptop and the backend must be running whenever the TV is used.
  - Plain http means anything on the Wi-Fi can read what the TV fetches. Only the TV-only token (below)
    belongs on this route.
- **The main token is random on every launch** of `./start-docker up`, which would break the TV on every
  restart. The TV needs a fixed one: see "A TV-only token" under "Decisions".
- **How the token gets into the app is not decided.** Typing 32 characters with a remote is miserable.
  Recommendation: read it at build time from a git-ignored file. Shelby is a public repo, so the token and
  any APK that holds it are never committed, and `./publish-check` must stay clean.
- **Plain http needs permission from Android.** Cleartext traffic is blocked by default on modern Android.
  While building, the app allows it for `127.0.0.1` only; at step 9, for the laptop's address. **Not yet
  checked on this TV**, nor how Android's network-security file takes a single IP address.

## How it will work

- **Language and parts:** Kotlin. Media3 ExoPlayer for playback (it plays a URL with a header and a byte
  range, so no waiting for a whole file, unlike the web app, which loads each file whole). OkHttp for the
  calls.
- **Screens:** Books, then Chapters, then Now Playing, with the chapter's text and the lit sentence on
  it (follow-along). Remote control throughout: Up/Down/Left/Right to move, OK to choose or play/pause,
  Back to go up one screen, media keys if the remote has them.
- **Follow-along:** the text is shown as it is read, the sentence being spoken is lit, and the text
  glides so that sentence stays about 42% of the way down the screen (the web app's numbers). The lit
  sentence comes from the player's own position, checked about every frame, and only the sentence that
  changes is redrawn, as in the web app, so the TV does not redraw a whole chapter several times a
  second. The matching rules are **rewritten in Kotlin** from the web app's, not shared, and tested
  with the web app's own test cases and against the real chapters.
- **Remote keys while following (agreed 2026-11-22):** Up and Down go to the previous and next
  paragraph, Left and Right skip back 15 s and forward 30 s, OK plays and pauses, Back leaves.
- **A chapter with no timing** still plays and shows its text with nothing lit, so the screen is never
  blank. Nothing more is designed for it: the user said not to worry about those chapters for now, and
  will render those books again (2026-11-22).
- **Keeps playing** with the screen off or another app in front (a media session and a foreground service). Built and
  checked at step 7. **The now-playing strip on the shelf** (chapter, book, time, bar, and five buttons) was added at the
  user's request during step 7 (2026-11-22): "show now playing in the home screen of the app", then "now playing should
  have controls".
- **UI toolkit is decided by measurement, not by taste.** Plan: try Jetpack Compose for TV first
  (`tv-material` 1.1.0), because it handles remote focus for us. Follow-along is the heaviest screen, so
  it is the test: a long text with a lit sentence that moves and a text that glides. If that, or a list
  of ~240 chapters, is not smooth on this TV, switch to plain Android views before writing more screens.
- **Newest library versions found on 2026-11-22** (from Google's and Maven's own indexes): Android Gradle
  Plugin 9.5.2 (bundles Kotlin 2.4.21), Gradle 9.9.2, Media3 1.11.1, Compose BOM 2026.11.01, OkHttp 5.5.1,
  tv-material 1.1.0, tv-foundation 1.0.0 (not 1.1.0 — it does not exist). compileSdk must be android-37.2
  for the BOM. Use these unless a build error says otherwise.
- **Signing:** the debug key is enough for sideloading to one TV. A new APK installs over the old one only
  if the key is the same, so keep the key (`~/.android/debug.keystore`) and back it up.

## Build tools (installed 2026-11-22, with the user's yes)

- JDK 17.0.21.1 at `~/jdks/jdk-17` (checked against Adoptium's SHA-256).
- Android SDK at `~/Android/Sdk`: command-line tools 23.0, platform 34, build tools 34.0.0. Download
  checked against Google's SHA-1. The SDK license was accepted for the user.
- Gradle 9.9.2, downloaded and checked against Gradle's SHA-256. It sits in this session's scratch folder
  and is only needed once, to make the project's Gradle wrapper. The scratch folder can be cleared, so
  download it again if it is gone.
- Needed in the shell: `JAVA_HOME=~/jdks/jdk-17` and `ANDROID_HOME=~/Android/Sdk`.
- Together about 770 MB. Deleting `~/jdks`, `~/Android` and `~/.gradle` removes all of it.

## Steps, in order

Each step is done only when it has been run on the real TV and looked at (the root rule: "Done means run
for real and looked at"). Screenshots come from `adb exec-out screencap`; the remote is driven with
`adb shell input keyevent`.

1. **An empty app on the TV.** ✓ Done 2026-11-22. It appears in the TV's app row (checked by stepping
   through the row on the TV: the "Shelby / Audiobooks" banner is there), opens, and Back leaves it.
   Cleartext to 127.0.0.1 is allowed by a network-security file in the app. `adb reverse tcp:8750 tcp:8750`
   is what lets the TV reach the backend; it must be run again whenever ADB reconnects.

   **Libraries that actually built:** AGP 9.5.2 (it bundles Kotlin, so no separate Kotlin plugin), Kotlin
   Compose plugin 2.4.21, Compose BOM 2026.11.01, tv-material 1.1.0, tv-foundation 1.0.0 (1.1.0 does not
   exist), compileSdk android-37.2 (the BOM needs it), OkHttp 5.5.1, Media3 not yet used.

   **Measured on the TV, 2026-11-22, release build** (`./gradlew assembleRelease`, signed with the debug
   key). Two numbers per cell where it matters: the app as a fresh install runs it, and after
   `adb shell cmd package compile -m speed -f ai.ayadata.shelby.tv` (the app compiled ahead of time; we
   own this TV, so it can be done once after each install):

   | | Shelby, as installed | Shelby, compiled | Spotify | VLC |
   |---|---|---|---|---|
   | APK size | 2.0 MB (debug build: 55 MB) | | ~35 MB | ~90 MB |
   | Cold start | 410 ms | 427 ms | 1,255 ms | 297 ms |
   | Memory (PSS) | 54 MB | 56 MB | 148 MB | 95 MB |
   | Shelf, 13 moves: late frames | 10.8% | **5.4%** | 29% | 2.3% |
   | Shelf: typical frame | 15 ms | 9 ms | 31 ms | 6 ms |
   | Chapters, 20 downs: late frames | 1.3% | **0%** | | |
   | Chapters: typical frame | 9 ms | 7 ms | | |

   Spotify's and VLC's cells are from the first session's measurements of their own screens, not today's
   shelf. **Lessons from getting here:**
   - **Judge speed on the release build only.** The same screens on a debug build: shelf 77% late at 77 ms,
     chapters 21% late at 34 ms; cold start 1,884 ms. The first session's "keep Compose" decision was made
     on debug numbers. It still stands, but now on release numbers (below), for the shelf and the list.
   - **Draw once, show as a picture.** The first version of the new look drew each cover live (a gradient, a
     120 sp letter and a darkening layer, times seven, over a full-screen gradient) and the shelf ran at
     65 ms a frame, 62% of frames late, every one late in the drawing. Covers and the background are now
     drawn once into a bitmap (`Art.kt`): 62% became 10.8% late, 69 ms became 15 ms.
   - **Follow-along has not been re-measured on release.** The test screen's numbers (first session) were
     on debug. The real thing is built and measured at step 6.
2. **Two test screens, to pick the toolkit.** ✓ Done 2026-11-22. **Decision: keep Compose for TV**, now
   backed by release numbers (above). The two test screens (`ListTestScreen.kt`,
   `FollowAlongTestScreen.kt`) were removed on 2026-11-22 when the real follow-along replaced them. Their debug-build numbers from the first session (list 9.8% late at realistic pace, follow-along
   41% late at 19 ms) are not repeated here because they are superseded.
3. **Books.** ✓ Done 2026-11-22, **with a new interface the same day** (the user asked for a nicer one).
   Checked against the API's own list: 10 books (9 when first counted; "A Prayer for Owen Meany" was
   rendered in between). The shelf: the focused book described large at the top (title, author), covers
   along the bottom with a teal ring and a small grow on focus, the shelf lands on the book you came from
   when you press Back. Colours and fonts come from the web app (`web/src/styles/tokens.css`,
   Bricolage Grotesque and Instrument Sans, both SIL OFL, fetched as TTF from Google Fonts because Android
   cannot read the web app's WOFF2). The books have no cover art, so `Art.kt` draws one: the audiobook
   colour fading into the surface and a big soft initial. Also fixed: a grey default title bar across the
   top, a default robot icon and a flat-colour banner (now drawn from the same fonts and colours), and
   Back being swallowed on the shelf (it now leaves the app). The token comes from `tv/token.txt` at build
   time. **That file was NOT git-ignored until `tv/.gitignore` was added on 2026-11-22**, although this
   plan said it was; the repo is public and `tv/` was untracked, so nothing had been committed, and it
   was checked that the token appears in no committable file. The messy titles ("mm_dev&journ:...",
   "...(z-library.sk, 1lib.sk, z-lib.sk)") are what the data holds, shown as they are, cut at three lines
   on a cover and two at the top; fixing them is the user's.
4. **Chapters.** ✓ Done 2026-11-22. **The first version of this step was wrong and was corrected.** It
   kept the newest file for each chapter number and called the result "correct". Checked against the
   audiobook tool's own list for "Dreams and Visions" (read twice, so each number has two files), that
   rule picks the wrong chapter in **14 of 19 slots**, and the book has **17** current chapters, not 19
   (Foreword and Introduction are not rendered in the current reading; the 18 files the tool does not
   list belong to the old one). Now (`ChapterChoice.kt`, `ShelbyApi.kt`): if no number repeats, the kept
   files are used as they are; if a number repeats, the app asks the tool (`audiobook__preview_book`, with
   the book's PDF found in the uploads list) and uses its list, as the web app does. That call takes 1.2
   to 5 s, so it is made only then. If the PDF is no longer in Shelby, or the tool cannot answer, the app
   says so instead of guessing. Checked for all 10 books: for the 7 the tool can analyse, its list and the
   kept files agree except for Dreams and Visions; "A Prayer for Owen Meany" and "The Final Quest" have no
   PDF in the uploads (so the tool cannot be asked) and no repeated numbers. **Tests:** 6 unit tests on the
   real Dreams and Visions data (`./gradlew testDebugUnitTest`), and two deliberate breaks of the rule,
   each caught (4 tests failed, then 1). **On the TV:** Dreams and Visions shows "17 chapters" starting
   Opening, Chapter 1 God's Purpose for Dreams and Visions, Chapter 2 ...; Owen Meany shows its 2 with
   durations. The list shows each chapter's length where the render recorded it (146 of the first 242 did),
   its position (not the book's internal number, which counts front matter), and its title. Back from a
   book to the shelf needed an `OnBackPressedCallback` in the activity; Compose for TV's `BackHandler`
   does not intercept Back while a TV-material list item has focus.
5. **Play.** ✓ Built and run on the TV 2026-11-22. **One finding needs a decision from the user: seeking
   in today's MP3s lands seconds away from the time shown (below).** Media3's ExoPlayer streams each chapter
   from Shelby by byte range, with the access token in a header, and the chapters of a book are one
   playlist, so a chapter that ends is followed by the next with no code of ours. Now Playing shows the
   chapter, a progress bar with both times, and the keys: OK plays and pauses (media keys too), Left skips
   back 15 s, Right forward 30 s (the web player's steps). Up and Down are left free for follow-along. Back
   leaves the screen and the chapter goes on playing; the chapter list shows a teal ▶ on the one playing.
   **The saved place** (decided yes): one per book, the chapter and the seconds, on the TV (`Places.kt`),
   written every 5 s while playing and on pause, cleared when the book ends. The chapter list lands on it and
   says "Resume 0:23".

   **Checked on the real TV (release build):**
   - **Time from pressing play to the first sound:** 185 to 230 ms on a 57-second chapter and on the 84-minute
     one; **217 ms on the 154.5 MB chapter** (6 h 39 min 45 s long). Streaming means no waiting for the file.
   - **Sound:** Android reports an active `AudioTrack` (media, speech) in `started`, going to `paused` and back
     on OK, and the progress bar moves. **The user listened on 2026-11-22 and said the sound is right.**
   - **Smoothness while playing** (the 154.5 MB chapter, 20 s, the bar updating four times a second): 103
     frames, 1% late, typical frame 5 ms.
   - **A chapter ending on its own** went into the next one ("chapter 2 of 4" at 0:06). **Leaving and
     returning:** left at about 23 s; the list said "Resume 0:23"; OK restarted at 0:27 four seconds later.
   - **Skips:** forward 30 s and back 15 s, 43 of them on the long chapter, all logged. Forward skips inside
     what is already loaded make no new request (none of 40 did); every backward skip asked the server for a
     new byte.
   - **Tests:** 10 unit tests (`./gradlew testDebugUnitTest`): the chapter rule (6) and the clock text (4).
   - **Not checked:** the error messages (refused token, missing audio, server down) are written and never
     shown; the long-chapter UI past 6 hours has been seen once at 19:39 of 6:39:45; keeping playing with the
     screen off is step 7.

   **Seeking is not accurate in today's files.** They are variable-bitrate MP3 (`render.py` encodes with
   `libmp3lame -q:a 4`), and the only seek map in them is a 100-point table. After a skip the player shows the
   time it was asked for, but the audio is from the byte the table gives, which is off. Measured by walking
   every frame of the real files, and confirmed against Media3's own seeking code and, for three seeks,
   against the real player on the TV (it asked the server for the byte the model predicted, to within 18 to
   40 bytes of 2.7 million):

   | | typical miss | worst miss | file size |
   |---|---|---|---|
   | 17 min chapter, as rendered today (variable bitrate) | 2.0 s | 6.1 s | 6.1 MB |
   | 84 min chapter, as rendered today | 7.5 s | 29.6 s | 31.5 MB |
   | 6 h 40 min chapter, as rendered today | 48 s | 134 s | 154.5 MB |
   | 17 min chapter, constant bitrate 64 kbps | 0.04 s | 0.05 s | 7.9 MB |
   | 84 min chapter, constant bitrate 64 kbps | 0.05 s | 0.10 s | 39.3 MB |
   | the same, constant bitrate with no header | 0.00 to 0.01 s | 0.02 s | same |

   A +30 s skip from today's files lands about 1 s (17 min chapter), 5 s (84 min) or 6 s (6 h 40) away from
   30 s exactly. Near the start of a long file the error is small (the TV landed within 3 s at about 20 min
   into the 6 h 40 chapter) and it grows towards the middle. **Why it matters:** follow-along lights the
   sentence for the player's position; after any skip or resume, today's audio is some seconds away from
   that position, so the wrong sentence is lit until the chapter is left. Playing straight through is
   unaffected (frames after the first are in step), and so is plain listening, where a few seconds on a skip
   does not matter.

   **The fix is at the source, one line, in the user's tool:** `audiobook/audiobook/render.py` line 231,
   `-q:a 4` becomes `-b:a 64k` (constant bitrate). Files are about 29% bigger. Media3 then seeks by simple
   arithmetic (`ConstantBitrateSeeker`: checked for both header cases). `audiobook/CLAUDE.md` says speech
   comes from the chunk cache, so a re-encode costs seconds; the four books the user means to re-render for
   timing would get exact seeking if the change lands first. **Done 2026-11-22 (the user said yes):**
   `render.py` now encodes `-b:a 64k`; see "After the change" just below.
   The M4B is AAC and not affected. **Method, to repeat it:** re-encode a real chapter three ways with
   ffmpeg; run Media3's `Mp3Extractor` in a JVM unit test (it needs a stand-in `android.os.Build`, because
   Media3 reads `Build.FINGERPRINT`) to get the byte it seeks to for a grid of times; walk the file's frames
   to find the true time at that byte. Not kept in the repo: the files are big and the test was a throwaway.
   **After the change (2026-11-22).** `audiobook/audiobook/render.py` `encode_mp3` is now constant bitrate. Checked
   by running real chapters through that very function at its default speed (0.95, with tags) and then Media3's own
   seeker: it picks `ConstantBitrateSeeker`, and the miss is **0.04 s typical, 0.11 s worst** on a 17 min and an
   84 min chapter (the old setting at the same speed: 1.2 s and 6.1 s on average). New test
   `audiobook/tests/test_encode.py` encodes a clip through the real encoder and checks every frame has one
   bitrate; with the old setting put back it fails (2 of 3 tests), and the third is the control that the old
   setting does vary. The audiobook suite: 411 pass, **1 fails and failed before this change**
   (`test_mcp_door::test_the_door_advertises_exactly_its_operations`: the door lists `exclude_chapters`, which that
   test's expected list lacks; not touched). `audiobook/CLAUDE.md` and `audiobook/plan.md` say why. Not committed.
   **What it does not fix by itself: the 244 chapters already kept are still variable-bitrate** until each is
   encoded again, and the 136 that have timing (the only ones follow-along can light) are among them. Per
   `audiobook/CLAUDE.md`, encoding is the cheap step (speech comes from the cache), so rendering a finished book
   again should cost little where its text has not changed since (the three complete books were rendered with
   today's rules on 2026-11-19); that is the user's to run. Until then follow-along on those books is exact when
   a chapter plays straight through and a few seconds out after a skip or resume.
6. **Follow-along.** ✓ Built and run on the TV 2026-11-22, in three parts, each checked before the next.
   **Not yet judged by ear:** the lit sentence follows the time the player shows, as the web app's does. Whether
   it is on the right words by ear, on a chapter that plays straight through, is the user's check (see the
   seeking note under step 5 for what a skip does to variable-bitrate files).

   **Part 1, the rules (`FollowRules.kt`, `TimingJson.kt`).** The web app's matching rules rewritten in Kotlin
   (`unitsFor`, `unitAt`, `wordsOf`, `wordsByChunk`, `spokenSegments`, `activeSegment`, `glideBy`, and the
   paragraph skip). **Checked against the web app's own code on 11 real chapters** of three books (a temporary
   vitest spec ran the web's real modules and wrote down its answers; the Kotlin was held to them exactly):
   505 paragraphs (497 cut by words into 1,366 sentence or chunk units, 8 shown whole) and the active paragraph
   and sentence at every quarter-second, 33,011 samples: **no difference.** Every case from the web's two test
   files is ported (17), plus tests for the active paragraph, the leading announcement, the paragraph skip, the
   whitespace and the sentence layout. **Deliberate breaks:** four breaks of the port (a unit starting only after
   its time; the first sentence taking its own start; a silence holding nothing; plain-ASCII whitespace) were put
   in turn; the first run let two through, which were fixed by adding a test and by redoing a break that had not
   applied; all four are then caught. Three real chapters are kept as fixtures (`src/test/resources/follow`,
   timing numbers and word counts only: the text is copyrighted and is not in the repo) with the web's answers.
   The temporary web spec and Kotlin cross-check were removed; `org.json` was added as a test library.

   **Part 2, the text (`ShelbyApi.getChapterText`, `getTiming`, `Follow.kt`).** The text comes from the book's PDF
   through the audiobook tool (the PDF path from the uploads list, as the web does), in pages until it says there
   are no more; the timing from the chapter's record by id. **Real coverage, scanned 2026-11-22 over every timed
   chapter that has a PDF (136; Owen Meany's 4 timed chapters have no PDF):** the text lines up with the timing in
   **135 of 136** (the one that does not: When Godly People Do Ungodly Things chapter 71, 96 timed paragraphs and
   97 in the text now); in the first three books every paragraph can be cut by sentence (2,845 of 2,845), in
   Overcoming Addictive Behavior 10 of 14 (4 are lit whole). **Time to open:** the text 2.0 to 3.9 s (the PDF is
   read each time; the last four chapters are kept in memory), the timing about 50 ms. The audio does not wait.

   **Part 3, lit and gliding (`FollowText.kt`, `NowPlayingScreen.kt`).** The paragraph being read is bright and the
   others step back; inside it the sentences already spoken are bright, the one being spoken is lit (teal, on a soft
   teal ground) and the ones to come are softer; list items show a bullet. Only the paragraph being read is split
   into sentences; the player is asked ten times a second and a redraw happens only when the paragraph or sentence
   changes. The text glides, by the clock, so the lit line sits about 42% of the way down. The remote: Up and Down
   skip by paragraph (Up restarts the paragraph if it began more than 2 s ago, as the web view does); the rest as
   step 5. A soft fade at the foot of the text stops a line being cut through the middle.

   **Checked on the real TV (release build):**
   - **The lit sentence is the one the timing says.** Paused at known times, each screenshot was read and set
     against what the web rules give from the real timing and text (the words themselves are not quoted here: the
     books are copyrighted). In the Myles Munroe 365 devotional chapter "Discouragement": 0:08 paragraph 0,
     sentence 1; 0:16 paragraph 0, sentence 2; 1:11 paragraph 3, sentence 0 (a paragraph far down the screen
     from the first). In "The Opinions of Others": 0:22 after Down paragraph 1, sentence 0; 4:03 after a far skip
     paragraph 14, sentence 0. All five match; each lit line sits at the anchor.
   - **Paragraph skips:** the log shows Down at 7.97 s going to 22.947 s (the next paragraph's start) and Up at
     22.947 s going to 3.032 s (the one before, because it was within 2 s of that paragraph's start).
   - **A skip far away** (eight Right presses, 3 s to 243 s) brings the text to the right paragraph.
   - **Chapters that cannot be followed say so, never blank:** Owen Meany ("This book's PDF is no longer in Shelby,
     so its text can't be shown."), Dreams and Visions ("This chapter was made before Shelby kept the timing of each
     sentence, so it can't be followed yet."), and the real chapter 71 ("The text no longer matches this recording
     (97 paragraphs now, 96 when it was made), so it can't be followed. Render the chapter again to follow along.").
     The Up and Down hint is hidden when the text is not showing.
   - **Smoothness while playing and following (30 s, a 17 min chapter):** 238 frames, 1.26% late, typical frame
     6 ms, 90th 8 ms; the same as a fresh install runs it (239 frames, 1.26%, 6 ms). **Memory 51 MB.** Cold start
     367 to 388 ms. This settles the question this step was meant to answer: Compose holds up on the heaviest screen.
   - **Tests:** 41 unit tests, all pass.

   **Found by running it, fixed:** (1) the text stuck where it was when the voice moved to a paragraph that was not
   on screen (the glide waited for that paragraph to say where its line was, and an undrawn paragraph never does):
   it now jumps there first; (2) the lit line settled 85% of the way down and ran off the bottom: the list
   measures an item's position from where its content starts, after the padding, and the anchor was measured from the
   top. Both were seen in screenshots before they were understood.

   **Not built, not checked:** the text is not prefetched for the next chapter (a few seconds of "Opening the text…"
   after each change); no way to scroll the text by hand (Up and Down are paragraph skips, as agreed); a chapter's
   audio and text for a book read twice follow the current reading only (step 4's rule). **A sentence's start can be a
   few tenths of a second out** (how the render makes it, as in the web app). **After a skip or a resume in a
   variable-bitrate chapter the audio can be seconds from the time shown** (step 5): exact once the chapters are
   constant bitrate, and 244 of them still are.
7. **Keeps playing** with the screen off and with another app in front. Done means: it was left for
   10 minutes and still played, with the screen off, and Projectivy did not kill it.

   **Built.** The player moved out of the screen: `ShelbyApplication` holds the one `Playback` for as long as the
   process lives; `PlaybackService` (a Media3 `MediaSessionService`, foreground type media playback) wraps its ExoPlayer in
   a session and is started by `Playback` just before anything plays. ExoPlayer's wake lock is on
   (`WAKE_MODE_NETWORK`: the processor and Wi-Fi are held while a chapter plays). Closing the screen (Back from the shelf)
   no longer stops the book, and opening the app again lands on the player of the book that is playing. The 10 Hz
   follow-along tick and the 4 Hz bar run only while the screen is showing (`repeatOnLifecycle`). The service is exported
   so the system can reach it, and `mayControl()` lets only this app, the system and its own notification connect (5 tests,
   one deliberately broken and caught). APK 3.1 to 3.6 MB (media3-session). 46 unit tests pass.

   **Before (the old build, same TV):** after Home the sound kept going and a 40 s screen-off did not stop it (the audio
   system holds the processor while sound plays), but the process sat at **priority 700 (a cached app: the first closed on
   a 1.8 GB TV)** and ExoPlayer's wake lock was switched off.

   **After, measured on the TV (release build):**
   - Playing in front: priority 0, foreground service `isForeground=true`, wake lock and Wi-Fi lock held, a notification
     (id 1001, category transport). First sound still 273 ms after play was pressed.
   - After Home: priority 50, then 200 (foreground service, away from the screen). With the YouVersion app in front and
     free memory down to 390 MB: still playing, same process.
   - **Remote media keys** reach the session with the home screen in front: pause (position stopped), play, play/pause
     toggle, next and previous chapter, all seen in the session's state. With YouVersion in front they do not: that app
     swallows the keys itself. (`cmd media_session dispatch` fails on this TV, so `input keyevent` was used.)
   - **Back from the shelf finishes the activity** (confirmed: no activity left in the app's history) **and the book plays
     on**: session playing, service foreground, same process; opening the app again showed the player at 0:57 with the
     right sentence lit. (Before step 7 `onDestroy` released the player, so this stopped the book.)
   - **12 minutes in the background across a chapter boundary** (home screen or another launcher in front; the screen
     was ON: see below): the position advanced 60 s a minute at every sample, the next chapter followed by itself at the
     end of the first, priority 50 to 200, both locks held throughout, free memory steady at about 520 MB.
   - **The strip:** Down from the books lands on play/pause, Up returns to the same book (without `focusRestorer` it went to
     the nearest tile). Every button was checked against the session: pause froze the position, play resumed, +30 s went
     27.4 s to 57.4 s, 15 s back went 61.1 s to 46.1 s, next and previous chapter moved between chapters, and OK on the title
     opened the player. Shelf smoothness with the strip showing (release, ahead-of-time compiled, 13 moves): 233 frames,
     3.0% late, typical frame 9 ms, 90th 15 ms (without it, 5.4% and 9 ms); memory 52.6 MB.

   **Not shown:** that the sound is heard with the screen blanked for 10 minutes. The first attempt used the TV's sleep key,
   which is its power-off (it also sends an HDMI standby to other devices: it was pressed twice and **should not be
   pressed again**) and the TV was woken 13 seconds later by someone using the remote, so the screen was awake for all 12
   minutes.

   **The hands-off attempt** (no key sent; the TV's own 10-minute idle timer was to blank the screen): also not a screen-off
   test, because someone kept using the TV (the "last user activity" clock moved every few minutes and the screen stayed
   awake at every sample). What it did show: 10 minutes 30 seconds of the 33-minute chapter in the background, the
   position advancing in step with the clock (574.8 s of audio in 574 s), priority 200, both locks held. At 10:40 it
   **paused by itself because the TCL TV app (live TV) took the audio focus** (00:21:02 in the audio log, uid 1000): that
   is the designed behaviour, the book gives way when another app plays, and the wake locks were released when it paused.
   **Still to do: a run with nobody touching the TV for 11 minutes, to see the screen go off and the book play on.** Until
   then step 7 is "playing in the background: done; with the screen blanked for 10 minutes: not shown". What stands
   in for it: the old build already kept sound through a 40 s screen-off, the processor is held by the audio system and now
   also by the player's own lock, and the Wi-Fi lock is held. These are reasons to expect it, not a measurement.

   **Found on the way:** another app (`app.tvhome`, installed 23:50 and updated 00:09 on 2026-11-22) was in front during
   one of the tests, and the TCL quick panel once opened on a stray key and took the TV to live TV (23:38): the TV is being
   used by someone else while these tests run, so a key-driven test must check the front activity first.

   **Corrected 2026-11-23: the buttons on the launcher's now-playing card did NOT work, and step 7 had not tested them.**
   The user asked whether the card's controls would work for Shelby as they do for Spotify. The card showed Shelby (chapter,
   author, bar, previous / pause / next) and the session offered the right actions, so it looked fine, but every press on the
   card did nothing: Shelby's log said `controller app.tvhome: trusted=false ownNotification=false -> REJECTED`, a
   millisecond after Android's own `Package app.tvhome doesn't exist`. **Cause: package visibility.** Since Android 11 an app
   sees only the apps it asks to (`<queries>`); Shelby asked for none, so Android could not say the launcher (an enabled
   notification listener, which Android trusts) was trusted, and `mayControl()` rejected it. The remote's media keys worked
   because they arrive from the system (package `android`, always visible), which is why step 7's key tests passed. **Fix:**
   a `<queries>` entry for the home screen's intent (MAIN + HOME), not for one launcher by name, and `PlaybackService` now logs
   every controller it accepts or rejects under `ShelbyTV`, so a refusal is no longer silent.
   **Checked on the real TV (release build, 2026-11-23), before and after the fix, with the launcher in front:** before, Enter
   on the card left the state at 3 and the log said REJECTED; after, the log said `controller app.tvhome: trusted=true -> accepted`
   and the session answered each press: **Enter** on the card toggled play and pause (3 to 2, position frozen for 3 s, the
   card said "PAUSED" with a play triangle; again 2 to 3), **Right** went to the next chapter (item 3 to 4, position 0),
   **Left** to the previous (2 s into a chapter: the chapter before; 21 s into one: that chapter's start, the player's usual
   rule). To reach the card by remote: Up from the app row, then Enter / Left / Right. A tap at the button's position
   (`input tap`) did nothing, so the card is a remote's control here.
   **Then, with Spotify (the baseline the user named), same day:** the card showed "NOW PLAYING · SPOTIFY" and Enter paused
   it (state 3 to 2, card "PAUSED") and played it again, the same keys and the same behaviour as for Shelby. With Spotify
   playing, starting Shelby in its own screen made Spotify give way (3 to 2, audio focus) and Shelby took the media buttons;
   from the launcher the card then showed Shelby and Enter paused and resumed it, Right went to the next chapter and Left to
   the previous, while Spotify's session stayed paused and untouched. Not checked: any launcher but this one, and Spotify
   starting while Shelby plays (only the other order). **A Spotify trap for the next test:** its "Dark mode" screen dims
   within seconds and the first key after the dim only wakes it, so a play press sent after a screenshot lands on the dim
   and does nothing; send one key, wait a second, then Enter, in one command.
8. **Housekeeping.** ✓ Done 2026-11-23. Each item was checked against the real files and the real image, not
   remembered from the list below.
   - **Already in place:** `tv/CLAUDE.md`; `tv/.gitignore`. `git check-ignore -v` says `token.txt`, `build/`, `.gradle/`,
     `local.properties` and the release APK are all ignored, and `git add -n tv` lists **48 files, none of them build
     output, an APK or the token file**. The token's value was searched for in all 48 (never printed): in none. The three
     follow fixtures hold timing numbers and word counts only. The only personal details in them are home-network addresses
     (192.168.x.x) and one `/home/philip/` path: `./publish-check` flags public addresses only, and other committed
     files already carry such a path.
   - **Added:** a section and a row in the root `CLAUDE.md` and `plan.md`.
   - **Found: the backend image was holding `tv/`.** `docker/backend.Dockerfile` copies the whole repo (`COPY . /app`)
     and `.dockerignore` did not list `tv`. The image built 2026-11-23 15:31 held `/app/tv`: `token.txt`, a debug APK
     (55 MB), a release APK (3.6 MB, carries the token) and 210 MB in all. The image is local (nothing in `compose.yaml`
     pushes it), but it broke "the images hold no credentials". **Fix:** `tv` is now in `.dockerignore`. Proved with
     throwaway builds that copy a path out of the context: `web/package.json` copies; `data` (already ignored), `tv` and
     `tv/token.txt` are refused. **The image on this machine still has `/app/tv` until the backend is next rebuilt**
     (`./start-docker up` does it); not rebuilt here, because that recreates the running containers.
   - **Decided: the TV's tests are in `./test`, when the toolchain is there.** The root `test` runs
     `./gradlew testDebugUnitTest --offline --no-daemon` if `~/jdks/jdk-17` and `~/Android/Sdk` exist, and otherwise says
     SKIPPED and ends with `NOT RUN: tv` instead of "All passed". Why not leave them out: they pass with no network, which
     is the rule `./test` holds, **shown** by running them inside a namespace with no route out and no DNS (46 pass, 50 s),
     and left out they would be the one suite nobody runs. Wiring checked on the real script text: toolchain missing gives
     SKIPPED, `NOT RUN: tv` and exit 0; one test broken in a throwaway copy gives "46 tests completed, 1 failed",
     `FAILED: tv` and exit 1. **The whole `./test`, run once (2 min 23 s):** assistant 437 passed (16 skipped), meet-ai
     166, mail-ai 178, apply-ai 111, web-ai 149, docu-ai 415 (1 skipped), web 233, publish 15; audiobook 411 passed and
     1 failed, **the same failure this plan already records from before** (`test_mcp_door`: the door lists
     `exclude_chapters`; not touched), which is why that run ended `FAILED: audiobook`. In the tv step Gradle said
     "UP-TO-DATE": nothing in `tv/` had changed since the forced no-network run (46 pass), so it did not run them
     again. That is Gradle's rule, not a skip of ours; `--rerun-tasks` forces it.
   - **Not done, on purpose:** nothing is staged or committed (the user's call). The README is not touched: step 9
     rewrites it. **Fonts, answered yes by the user later the same day:** the five font files (`res/font`) are under the
     SIL Open Font License, which asks that the licence text travel with the fonts, and none did (the web app commits
     no font files, so the TV is the first). The two licence texts, fetched from Google Fonts' own repository
     (only their copyright line differs; no error page), are in `tv/licenses/`, which makes 50 files for git to add.
9. **The home-network route.** Needs the TV-only token to exist first. Make the changes listed under
   "Reaching the backend", and rewrite the root `CLAUDE.md` rule, `compose.yaml`'s comment and the README.
   Done means: ADB disconnected, the TV plays a chapter and follows it over the Wi-Fi; a request from
   the TV with a wrong token and one with a Host that is not listed are both refused; and the TV-only
   token is refused for a Mail call.

   **Part 1, the TV-only token: ✓ built and run for real 2026-11-23, after the user was shown the design and chose
   "audiobooks only".** In `assistant/` (details and the reasons: `assistant/CLAUDE.md` -> Scoped tokens). The token is
   `ASSISTANT_TV_TOKEN` in the root `.env`, passed to the backend only and withheld from every tool. What it may use is
   declared in `assistant/tools.yaml` under the audiobook tool (`scopes: tv`): five routes only, and on them the
   `chapter` and `book` records, the `audio` of those chapters, the books in the uploads list, and the two read-only calls
   `preview_book` and `read_chapter`. **Tighter than the plan's first list, on purpose:** the same routes would also have
   served the tool's 7 voices (with their recordings), 8 samples, 51 job logs and its whole-book file, and every upload
   (8 meeting recordings, 10 documents, 4 voice samples). **Checked:** 27 new tests and eight deliberate breaks of the
   server, each caught (480 tests pass with a throwaway Postgres); then **57 of 57 checks on the live backend, on the real
   records**: 246 chapters and 10 books listed; a chapter's audio plays by range (206); every voice, sample, job,
   whole-book and upload file is a 404; `job_status`, a Mail call and `/api/state` are 403; a wrong token is 401 and a Host
   not on the list is 403. The backend was restarted for it (`./start-docker up --tailscale`) with nothing running.
   `tv/token.txt` now holds this token, so a build no longer goes stale when the backend restarts.
   **The app against the new token** was checked in part 2 below: every call in its code is inside the grant (the record
   lists by kind, one record, a chapter's audio by id, the uploads list, `read_chapter`, `preview_book`), and on the TV it
   worked. **Not tried:** a `pdf` path to a PDF that is not an upload (the tool said "passwd is not a PDF" for `/etc/passwd`,
   and reads only PDFs it has analysed). **Also done with part 2, at the user's yes:** `ASSISTANT_TOKEN`, the launch token,
   is now withheld from every tool (all six held it, and none reads it): checked in the running container, and one read-only
   call to each of four tools (and a real input to `apply_ai`) still answers; `web_ai` is up and lists its tools.

   **Part 2, the route: ✓ built and run on the real TV 2026-11-23 (the user said yes to all three: the app rebuilt, the tools
   denied the launch token, and the route).**
   - **The backend side.** `SHELBY_HOME_ADDRESS=192.168.70.108` in `.env` (the laptop's wired address: the default route; its
     Wi-Fi, .164, is not used) makes `./start-docker up` add `compose.home.yaml` and list the address as a Host. **Opt-in:** unset,
     nothing is published beyond 127.0.0.1, as before. Before anything starts, `up` refuses an address that is not an IPv4 one, not
     private, or not the machine's own right now: seven bad values (`abc`, 8.8.8.8, 127.0.0.1, a tailnet address, an address the
     machine lacks, 0.0.0.0, two addresses) were each refused and the running containers were left alone. **Checked on the
     machine after the restart:** the port listens on exactly 127.0.0.1 and 192.168.70.108 (`ss`), not 0.0.0.0, not the Wi-Fi
     address; the web app only on 127.0.0.1; Postgres not published; the backend lists `192.168.70.108, backend` and the tailnet
     name as Hosts. The root rule, `compose.yaml`'s comments, the README and `assistant/CLAUDE.md` were rewritten in the same
     change to say "except this, on purpose".
   - **The app side.** `tv/server.txt` (git-ignored) holds `http://192.168.70.108:8750`; the build bakes it in as
     `BuildConfig.SHELBY_URL` and **writes** the plain-http rule from it (`writeNetworkConfig`: 127.0.0.1 and that address), so
     they cannot disagree; the build refuses an address that is not private (six bad values tried, each refused). The old
     checked-in XML file is gone. A single IP address in a network-security file works on this TV (shown at step 1 for 127.0.0.1,
     and now for the home address).
   - **From the TV itself** (a one-off Java probe run with `app_process`, deleted after: the TV has no curl): the TV token, books
     list, Host = the home address: **200**; a wrong token **401**; no token **401**; the TV token with a Host not listed
     **403**; the TV token asking Mail for its status **403**; asking for the app's state **403**; deleting records **403**. To the
     laptop's Wi-Fi address on 8750 and to 8751 on the home address: **connection refused**.
   - **The app on the TV** (the new build installed over the old one, compiled ahead of time, **no `adb reverse` rule**, so the
     ADB tunnel could not be the way): the shelf listed the books; "Dreams and Visions" showed 17 chapters (that is `preview_book`
     through the TV token); "Rediscovering Kingdom Worship" showed 45 chapters with their lengths; "Opening" (5:20) played, the
     text opened and the lit sentence followed it, the text gliding with it (screenshots at 0:11 and 1:19); the player said
     "playing" with about 2.7 minutes buffered; the TV's own `netstat` showed its sockets to port 8750 on the laptop.
   - **ADB disconnected** for 45 s while it played: the position went from 32.4 s to 79.5 s over 47 s of real time, still playing.
     Said exactly: about 2.7 minutes were already buffered, so this shows the app does not depend on ADB, not that Wi-Fi was
     needed for those 47 s; the Wi-Fi route is shown by the other lines (no reverse rule, the shelf and the chapter lists, the
     sockets).
   - **Left on the TV:** a saved place in "Rediscovering Kingdom Worship" at 1:35 (from this test); the book paused; the app left.
     **VLC had a paused video (an episode, 11:35 in) in front when this began; launching the app stopped it** (see
     `CLAUDE.md`); VLC was left on its browse screen. Whether VLC kept the place was not checked.
   - **Also found, not Shelby's and not changed:** other projects' containers on this laptop publish on every address, so the
     home network can reach them: `rag-postgres` (5432; the TV's probe connected to it, one malformed request, no data),
     `rag-opensearch` (9200, 9600) and `annotation_orchestration_backend` (8080). They were reachable before any of this.
   - **Not checked:** the laptop keeping 192.168.70.108 (a fixed address in the router is the user's to set; the setting is
     one line in `.env` and `tv/server.txt`, and the TV says "Can't reach Shelby" when it moves); the sound by ear; hours over
     the Wi-Fi; the laptop asleep or the containers down (the app then says it cannot reach Shelby, as designed); `./start`
     (it passes through to `up`, which reads `.env`, but was not run, only `./start-docker up --tailscale`).

## Left out of version 1

The web app's "page" and "lyrics" modes (one look only), the waveform bar, switching chapter from inside
follow-along, voices and cloning, uploading a PDF, rendering, deleting, the chat, and every other tool.
Also not built unless asked: remembering where each chapter was left off, playback speed, a sleep
timer. Remembering the place is the most useful of these, and is the one to ask about.

## Risks and unknowns

- **Weak TV.** Memory and smoothness are the main risk. Measure at every step, and say plainly if a step
  is slow.
- **The laptop must be on** and the backend running. Nothing here changes that.
- **Publishing on the home network** puts the backend's port within reach of every device on the Wi-Fi,
  guests included, behind only a token sent over plain http. The TV-only token is what limits the harm.
- **A backend restart changes the token** unless it is fixed in `.env`. The app must say "the token was
  refused", not sit blank.
- **A 1.1 MB listing on every start** is fine on a good network and unmeasured on this TV. If it is slow,
  the fix is a small backend option to leave the timing data out. That is a backend change, so it is the
  user's call.
- **The two cases above that were marked not checked:** cleartext on this TV (shown to work at step 3 over the ADB
  link; the home-network address is step 9), and playback surviving the launcher (step 7: it does, priority 50 to 200;
  the launcher in front was Projectivy and, later, another launcher, `app.tvhome`).
- **Follow-along is the heaviest screen** and the one most likely to be slow on this TV. It is why the
  toolkit test (step 2) includes it, and why smoothness is measured while it plays.
- **Most chapters cannot be followed today:** 106 of 242, and four whole books (see the table). Giving
  them timing means rendering them again, which is the audiobook tool's job and not the TV app's. The
  user will do that, so the TV app does nothing special for them, and follow-along will look like it
  does nothing on those books until then.
- **Two copies of the rules.** The web app and the TV app will each hold the matching rules. If one
  changes, the other drifts. The shared test cases and the real-chapter comparison in step 6 are what
  catch that; note in `tv/CLAUDE.md` that a change to `audiobookSentences.ts` means a change here.
- **Seeking in today's MP3s is inexact** (step 5): a skip lands seconds from the time shown, and the lit sentence
  follows the shown time. Fixed at the source by constant bitrate (the user's decision, above).
- **Timing can be slightly out** (a sentence may light a few tenths of a second early or late). That is
  how the render makes it, not a TV fault, and the web app has the same limit.
- **The text could be changed after a render.** The word counts then do not add up, and the paragraph
  is lit whole. That is correct behaviour, but it will look coarser.

## Decisions

**All decided 2026-11-22 by the user.** Nothing is waiting on them except the word to start step 1.

- Build over the ADB link first, then use the home network for daily use. Tailscale is out.
- Follow-along is in version 1. Chapters with no timing get no special handling (the user will render
  them again). The remote keys while following are as proposed above.
- **Remember the place: yes.** One saved place per book (the chapter and the seconds), kept on the TV,
  no backend change. Why: a chapter can run long (one real one is 17 minutes), the TV switches its
  screen off after 10 minutes, and with 1.8 GB of RAM the app may well be closed. Built at step 5.
- **A TV-only token: yes.** Built 2026-11-23 as "audiobooks only" (step 9, part 1), tighter than the list below. The user
  agreed to the change to `assistant/`. **The design is shown to the
  user before it is built** (step 3), because it touches who may call the backend. It is a second token,
  fixed in `.env`, that the backend accepts only for what the player needs: the book and chapter lists,
  one chapter's text and timing, the audio, the uploads list, and `audiobook__read_chapter`. The main
  token stays random on every launch. The reasons, checked 2026-11-22:
  - The full token runs any tool through `/api/actions`, and that includes Mail's read-only
    `list_threads`, `read_thread` and `search`, so it opens the mailbox. (Listed, not called: no mail
    was read.)
  - The TV's ADB is open to the whole home network with no prompt, and a token inside the app can be
    copied off the TV.
  - With the home network as the daily route, the token crosses the Wi-Fi in plain http. With a TV-only
    token, what can be heard there is the books and not the mailbox. Without it, step 9 should not be
    done.

### Decided after step 5 (2026-11-22)

1. **Constant bitrate: yes**, done (see "After the change" under step 5).
2. **The sound on the TV is right**: the user listened.

**Open for the user after step 6:**
- **Listen to a followable chapter** (for example the Myles Munroe 365 devotional, "Discouragement" or "The Opinions
  of Others", or any chapter of Rediscovering Kingdom Worship or When Godly People Do Ungodly Things) and say whether
  the lit sentence is on the words being spoken. Checked so far against the timing, not by ear.
- **Owen Meany and The Final Quest have no PDF in Shelby's uploads**, so their text can't be shown (they play).
  Uploading the PDFs again would let Owen Meany (4 timed chapters) be followed.
- **Re-render the finished books whose chapters are already kept** (at least the three with
timing: When Godly People Do Ungodly Things, Rediscovering Kingdom Worship, the Myles Munroe 365 Day Devotional) so
their files are constant bitrate; and the four books with no timing, which the user is re-rendering anyway, will
be constant bitrate from the start.

## Housekeeping when code starts (all done at step 8, 2026-11-23)

- `tv/CLAUDE.md` with this tool's rules and a gotcha ledger, as every tool has one. ✓
- A row in the root `CLAUDE.md` and `plan.md`, and `tv/` in `.gitignore` for `build/`, `.gradle/`,
  `local.properties` and any APK. ✓ (And `tv` in the root `.dockerignore`: see step 8.)
- **Tests and `./test`:** decided at step 8: they run in `./test` with `--offline` when the toolchain is installed,
  and say NOT RUN when it is not. The first build needs the network once, to fetch the libraries. ✓
- Stage by explicit path. Run `./publish-check` before any push (it reads commits, so it sees nothing until
  there is one). Commit as the user, as the root `CLAUDE.md` says. Nothing here has been staged or committed.
