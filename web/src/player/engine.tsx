// The one audio element, and everything about playing it. It lives above the pages (see main.tsx), not
// inside the Audiobooks panel: the pages are mounted one at a time, so an <audio> that belonged to a page
// stopped the moment you went to another. Here it carries on; the panel and the docked mini player are
// only views of this.
//
// Three contexts, so a view re-renders only for what it shows: the slow state (what is loaded, playing or
// not, speed, volume, the sleep timer), the clock (the time, four times a second), and the actions (which
// never change). The bar itself moves through a CSS variable written to the views' DOM nodes every
// animation frame, so sixty updates a second re-render nothing.

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { CONTINUE_KEY, PREFETCH_SECONDS, continuesFrom } from './queue'
import { numeric, store } from './storage'
import { useWaveform, type Wave } from './waveform'

export const BACK = 15
export const FORWARD = 30

/** What plays after (or before) a track: its name, to show, and how to fetch it when it is wanted. */
export interface Upcoming { title: string; load: () => Promise<Track> }
/** Where a track is shown playing: a book (its PDF's path) and the chapter in it, so the docked player can take you there. */
export interface Home { book: string; chapter: number }
export interface Track { key: string; title: string; album?: string; blob: Blob; home?: Home; next?: Upcoming; previous?: Upcoming }
type Loaded = Track & { url: string }
export interface Sleep { minutes: number; endsAt: number }

interface PlayerState {
  track: Loaded | null
  playing: boolean
  waiting: boolean
  failed: boolean
  rate: number
  volume: number
  muted: boolean
  resumed: number | null
  sleep: Sleep | null
  wave: Wave
  /** How many full players are on screen; the docked one steps aside while there is one. */
  fullViews: number
  /** Whether the next chapter starts by itself when one ends. */
  continues: boolean
  /** Why the next chapter did not start, when it could not be fetched. */
  notice: string
}
interface PlayerClock { time: number; duration: number; sleepLeft: number }
interface PlayerActions {
  open(track: Track): void
  close(): void
  toggle(): void
  seek(to: number): void
  skip(by: number): void
  setRate(rate: number): void
  setVolume(volume: number): void
  setMuted(muted: boolean): void
  setSleep(minutes: number | null): void
  setContinues(on: boolean): void
  /** Go to the track after or before this one, when there is one (the headphones' and lock screen's buttons). */
  playNext(): void
  playPrevious(): void
  startOver(): void
  dismissResume(): void
  /** A view is dragging the bar: leave it alone until it lets go. */
  scrub(on: boolean): void
  /** Have `el`'s --progress kept current. Returns the undo. */
  paintInto(el: HTMLElement): () => void
  /** Tell the player a full view is on screen. Returns the undo. */
  showFull(): () => void
}

const StateContext = createContext<PlayerState | null>(null)
const ClockContext = createContext<PlayerClock | null>(null)
const ActionsContext = createContext<PlayerActions | null>(null)

const need = <T,>(value: T | null): T => {
  if (value === null) throw new Error('the audio player is not mounted: wrap the app in <PlayerProvider>')
  return value
}
export const usePlayer = () => need(useContext(StateContext))
export const usePlayerClock = () => need(useContext(ClockContext))
export const usePlayerActions = () => need(useContext(ActionsContext))

const positionKey = (key: string) => `assistant-player:${key}`
const lengthOf = (el: HTMLAudioElement, fallback: number) => (Number.isFinite(el.duration) && el.duration > 0 ? el.duration : fallback)
const SAVE_EVERY_MS = 4000
const FADE_MS = 3500

export function PlayerProvider({ children }: { children: ReactNode }) {
  const audio = useRef<HTMLAudioElement>(null)
  const [track, setTrack] = useState<Loaded | null>(null)
  const trackRef = useRef<Loaded | null>(null)
  const [playing, setPlaying] = useState(false)
  const [waiting, setWaiting] = useState(false)
  const [failed, setFailed] = useState(false)
  const [time, setTime] = useState(0)
  const [length, setLength] = useState(0)
  const [rate, setRateState] = useState(() => numeric('assistant-player-rate', 1))
  const [volume, setVolumeState] = useState(() => Math.min(1, Math.max(0, numeric('assistant-player-volume', 1))))
  const [muted, setMuted] = useState(false)
  const [resumed, setResumed] = useState<number | null>(null)
  const [sleep, setSleepState] = useState<Sleep | null>(null)
  const [sleepLeft, setSleepLeft] = useState(0)
  const [fullViews, setFullViews] = useState(0)
  const [continues, setContinuesState] = useState(() => continuesFrom(store.read(CONTINUE_KEY)))
  const [notice, setNotice] = useState('')
  const wave = useWaveform(track?.blob ?? null)

  const rateRef = useRef(rate)
  rateRef.current = rate
  const continuesRef = useRef(continues)
  continuesRef.current = continues
  const waveSeconds = useRef(0)
  waveSeconds.current = wave.seconds
  const dragging = useRef(false)

  // ---- the progress variable, painted straight into the views' DOM nodes
  const targets = useRef(new Set<HTMLElement>())
  const progress = useRef(0)
  const dur = useCallback((el: HTMLAudioElement) => lengthOf(el, waveSeconds.current), [])
  const paint = useCallback((t: number, d: number) => {
    progress.current = d > 0 ? Math.min(1, Math.max(0, t / d)) : 0
    for (const el of targets.current) el.style.setProperty('--progress', String(progress.current))
  }, [])

  // ---- remembering where you stopped
  const lastSaved = useRef(0)
  const remember = useCallback(() => {
    const el = audio.current
    const t = trackRef.current
    if (el && t && el.currentTime > 5 && !el.ended) store.write(positionKey(t.key), String(Math.floor(el.currentTime)))
  }, [])

  // ---- the next track: fetched a little before this one ends, then opened when it does
  const upcoming = useRef<{ after: string; track: Promise<Track | null> } | null>(null)
  const openRef = useRef<(track: Track) => void>(() => {})
  const fetchNext = useCallback((t: Loaded) => {
    if (!t.next) return null
    if (upcoming.current?.after !== t.key) upcoming.current = { after: t.key, track: t.next.load().catch(() => null) }
    return upcoming.current.track
  }, [])
  const advance = useCallback((t: Loaded, whenEnded: boolean) => {
    const next = fetchNext(t)
    if (!next) return
    setWaiting(true)
    void next.then((track) => {
      // Something else was chosen meanwhile, or the ended chapter was played again: leave it be.
      if (trackRef.current !== t || (whenEnded && !audio.current?.ended)) return
      if (track) openRef.current(track)
      else { setWaiting(false); setNotice(`Could not fetch ${t.next!.title}. Press its Play to try again.`) }
    })
  }, [fetchNext])

  // ---- the audio element's own events, wired once
  useEffect(() => {
    const el = audio.current
    if (!el) return
    const syncSession = () => {
      const d = dur(el)
      if (!('mediaSession' in navigator) || !(d > 0)) return
      try { navigator.mediaSession.setPositionState({ duration: d, playbackRate: el.playbackRate || 1, position: Math.min(el.currentTime, d) }) } catch { /* not allowed yet */ }
    }
    const onMeta = () => {
      const t = trackRef.current
      if (!t) return
      el.playbackRate = rateRef.current // loading a file resets the speed to the default
      setLength(Number.isFinite(el.duration) ? el.duration : 0)
      setWaiting(false)
      const saved = numeric(positionKey(t.key), 0)
      if (saved > 5 && Number.isFinite(el.duration) && saved < el.duration - 10) {
        el.currentTime = saved
        setTime(saved)
        setResumed(saved)
        paint(saved, el.duration)
      }
      void el.play().catch(() => {}) // the click that chose this file; if the browser still refuses, the Play button is there
    }
    const onPlay = () => { setPlaying(true); syncSession() }
    const onPause = () => { setPlaying(false); remember(); paint(el.currentTime, dur(el)); syncSession() }
    const onEnded = () => {
      setPlaying(false)
      const t = trackRef.current
      if (t) store.write(positionKey(t.key), null)
      setResumed(null)
      paint(dur(el), dur(el))
      if (t && continuesRef.current) advance(t, true)
    }
    const onTime = () => {
      setTime(el.currentTime)
      if (Date.now() - lastSaved.current > SAVE_EVERY_MS) { lastSaved.current = Date.now(); remember() }
      const t = trackRef.current
      if (t && continuesRef.current && Number.isFinite(el.duration) && el.duration - el.currentTime < PREFETCH_SECONDS) fetchNext(t)
    }
    const onDuration = () => { setLength(Number.isFinite(el.duration) ? el.duration : 0); syncSession() }
    const onWaiting = () => setWaiting(true)
    const onReady = () => setWaiting(false)
    const onError = () => { if (!trackRef.current) return; setFailed(true); setWaiting(false) }
    const onHide = () => remember()
    const events: [string, () => void][] = [
      ['loadedmetadata', onMeta], ['play', onPlay], ['pause', onPause], ['ended', onEnded], ['timeupdate', onTime],
      ['durationchange', onDuration], ['waiting', onWaiting], ['playing', onReady], ['canplay', onReady], ['error', onError],
      ['seeked', syncSession], ['ratechange', syncSession],
    ]
    for (const [name, handler] of events) el.addEventListener(name, handler)
    window.addEventListener('pagehide', onHide)
    return () => {
      for (const [name, handler] of events) el.removeEventListener(name, handler)
      window.removeEventListener('pagehide', onHide)
    }
  }, [paint, remember, dur, advance, fetchNext])

  // A blob URL holds the whole file in memory until it is revoked.
  const url = track?.url
  useEffect(() => () => { if (url) URL.revokeObjectURL(url) }, [url])

  // ---- speed and volume
  useEffect(() => {
    const el = audio.current
    if (el) { el.playbackRate = rate; el.defaultPlaybackRate = rate }
    store.write('assistant-player-rate', String(rate))
  }, [rate])
  useEffect(() => {
    const el = audio.current
    if (el) { el.volume = volume; el.muted = muted }
    store.write('assistant-player-volume', String(volume))
  }, [volume, muted])

  // ---- the bar, while playing
  useEffect(() => {
    if (!playing) return
    let frame = 0
    const tick = () => {
      const el = audio.current
      if (el && !dragging.current) paint(el.currentTime, dur(el))
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [playing, paint, dur])

  // ---- the sleep timer: counts down, then fades out over a few seconds and pauses
  useEffect(() => {
    if (!sleep) return
    const left = () => Math.max(0, Math.round((sleep.endsAt - Date.now()) / 1000))
    setSleepLeft(left())
    const timer = window.setInterval(() => {
      const remaining = left()
      setSleepLeft(remaining)
      if (remaining > 0) return
      window.clearInterval(timer)
      setSleepState(null)
      const el = audio.current
      if (!el || el.paused) return
      const start = performance.now()
      const from = el.volume
      const step = (now: number) => {
        const t = Math.min(1, (now - start) / FADE_MS)
        el.volume = from * (1 - t)
        if (t < 1) requestAnimationFrame(step)
        else { el.pause(); el.volume = from }
      }
      requestAnimationFrame(step)
    }, 1000)
    return () => window.clearInterval(timer)
  }, [sleep])

  // ---- actions
  const actions = useMemo<PlayerActions>(() => {
    const seek = (to: number) => {
      const el = audio.current
      if (!el) return
      const d = dur(el)
      const t = Math.min(Math.max(0, to), d > 0 ? d : Math.max(0, to))
      el.currentTime = t
      setTime(t)
      paint(t, d)
    }
    return {
      open(next) {
        const el = audio.current
        const prev = trackRef.current
        if (prev && prev.key === next.key) { if (el?.paused) void el.play().catch(() => {}); return }
        remember()
        const loaded: Loaded = { ...next, url: URL.createObjectURL(next.blob) }
        trackRef.current = loaded
        upcoming.current = null // played now, or not wanted: either way not held in memory
        setNotice('')
        setFailed(false)
        setWaiting(true)
        setResumed(null)
        setTime(0)
        setLength(0)
        paint(0, 0)
        setTrack(loaded)
      },
      close() {
        const el = audio.current
        remember()
        trackRef.current = null
        if (el) { el.pause(); el.removeAttribute('src'); el.load() } // dropping the attribute alone would not stop it
        setTrack(null)
        setPlaying(false)
        setWaiting(false)
        setFailed(false)
        setResumed(null)
        setSleepState(null)
        setNotice('')
        upcoming.current = null
        setTime(0)
        setLength(0)
        paint(0, 0)
      },
      toggle() {
        const el = audio.current
        if (!el || !trackRef.current) return
        if (el.paused) void el.play().catch(() => setPlaying(false))
        else el.pause()
      },
      seek,
      skip: (by) => seek((audio.current?.currentTime ?? 0) + by),
      setRate: setRateState,
      setVolume: (v) => { setVolumeState(Math.min(1, Math.max(0, v))); setMuted(false) },
      setMuted,
      setSleep: (minutes) => setSleepState(minutes === null ? null : { minutes, endsAt: Date.now() + minutes * 60_000 }),
      setContinues(on) {
        setContinuesState(on)
        store.write(CONTINUE_KEY, on ? '1' : '0')
      },
      playNext() {
        const t = trackRef.current
        if (t?.next) advance(t, false)
      },
      playPrevious() {
        const t = trackRef.current
        if (!t?.previous) return
        setWaiting(true)
        void t.previous.load().then(
          (track) => { if (trackRef.current === t) openRef.current(track) },
          () => { if (trackRef.current === t) { setWaiting(false); setNotice(`Could not fetch ${t.previous!.title}.`) } },
        )
      },
      startOver() {
        seek(0)
        setResumed(null)
        const t = trackRef.current
        if (t) store.write(positionKey(t.key), null)
      },
      dismissResume: () => setResumed(null),
      scrub(on) { dragging.current = on },
      paintInto(el) {
        targets.current.add(el)
        el.style.setProperty('--progress', String(progress.current))
        return () => { targets.current.delete(el) }
      },
      showFull() {
        setFullViews((n) => n + 1)
        return () => setFullViews((n) => n - 1)
      },
    }
  }, [paint, remember, dur, advance])
  openRef.current = actions.open

  // ---- lock screen and headphone controls
  const title = track?.title
  const album = track?.album ?? 'Audiobook'
  const hasNext = Boolean(track?.next)
  const hasPrevious = Boolean(track?.previous)
  useEffect(() => {
    if (!('mediaSession' in navigator) || !title) return
    const session = navigator.mediaSession
    session.metadata = new MediaMetadata({ title, artist: 'Audiobook', album })
    const set = (action: MediaSessionAction, handler: MediaSessionActionHandler | null) => { try { session.setActionHandler(action, handler) } catch { /* not supported here */ } }
    set('play', () => { void audio.current?.play() })
    set('pause', () => audio.current?.pause())
    set('seekbackward', (d) => actions.skip(-(d.seekOffset ?? BACK)))
    set('seekforward', (d) => actions.skip(d.seekOffset ?? FORWARD))
    set('seekto', (d) => { if (d.seekTime !== undefined) actions.seek(d.seekTime) })
    set('nexttrack', hasNext ? () => actions.playNext() : null)
    set('previoustrack', hasPrevious ? () => actions.playPrevious() : null)
    return () => {
      for (const a of ['play', 'pause', 'seekbackward', 'seekforward', 'seekto', 'nexttrack', 'previoustrack'] as const) set(a, null)
      session.metadata = null
    }
  }, [title, album, hasNext, hasPrevious, actions])

  const duration = length > 0 ? length : wave.seconds
  const state = useMemo<PlayerState>(
    () => ({ track, playing, waiting, failed, rate, volume, muted, resumed, sleep, wave, fullViews, continues, notice }),
    [track, playing, waiting, failed, rate, volume, muted, resumed, sleep, wave, fullViews, continues, notice],
  )
  const clockValue = useMemo<PlayerClock>(() => ({ time, duration, sleepLeft }), [time, duration, sleepLeft])

  return (
    <ActionsContext.Provider value={actions}>
      <StateContext.Provider value={state}>
        <ClockContext.Provider value={clockValue}>
          {children}
          <audio ref={audio} src={track?.url} preload="auto" />
        </ClockContext.Provider>
      </StateContext.Provider>
    </ActionsContext.Provider>
  )
}
