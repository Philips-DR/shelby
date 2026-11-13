// Follow along: the chapter's text as a full-screen layer, with the sentence being spoken lit as it is said, the way
// a lyrics view does it.
//
//   - The paragraph being read is the bright one; the others step back. Inside it the sentence being spoken is
//     marked, the sentences before it are bright and the ones to come are softer. The line it starts on stays about
//     a third of the way down, the text moving under it; you can scroll away and a "Back to now" button brings you back.
//   - A sentence's start is worked out by the render (audiobook/sentences.py): a guess from the text moved to the
//     nearest pause in the audio. It can be a few tenths of a second out. A chapter rendered before that has chunks,
//     not sentences, and is lit a chunk at a time; one with neither is lit a paragraph at a time. Nothing is invented.
//   - The sentences are moved by the DOM, one frame at a time, from the audio's own time (`now()`), not through React:
//     only the paragraph being read has a span per sentence, and only the sentence that changes is touched.
//   - Tap a paragraph, or a sentence of the one being read, to go there. The controls are the player's own (the same
//     audio, the same docked player stepping aside), so nothing here plays on its own.
//
// Three additions (2026-11-13):
//   - A waveform scrubber replaces the thin progress line at the bottom: the real audio's loud and quiet, tappable
//     to seek, with the played portion coloured. Falls back to the thin line when no waveform is available.
//   - A chapter list that slides up from the bottom: every chapter, its duration, and which is playing. Tap a
//     rendered chapter to switch to it without leaving the follow-along view.
//   - A mode toggle between "lyrics" (the original: large text, one paragraph focused, immersive) and "page"
//     (smaller text, all paragraphs readable, the spoken one highlighted — better for skimming ahead).

import { Fragment, memo, useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent } from 'react'
import { createPortal } from 'react-dom'
import { call } from '../call'
import { toolColor } from '../charts/palette'
import { useWidth } from '../charts/useWidth'
import { BACK, FORWARD, usePlayer, usePlayerActions, usePlayerClock } from '../player/engine'
import { clock } from '../player/format'
import { store } from '../player/storage'
import { WAVE_BUCKETS } from '../player/waveform'
import { IconClose, IconDown, IconForward, IconList, IconNext, IconPage, IconPause, IconPlay, IconPrevious, IconRewind, IconSpeak, IconTrash } from '../ui/icons'
import { activeSegment, spokenSegments, type SegmentTiming } from './audiobookTiming'
import { unitAt, unitsFor, wordsOf, type Unit } from './audiobookSentences'
import '../styles/player.css'
import '../styles/panels/follow.css'

interface Para { kind: string; text: string }
interface Page { segments: Para[]; truncated: boolean; next_start: number | null }

/** A chapter as far as the chapter list needs it. */
export interface FollowChapter { number: number; label: string; speech: string; audio?: { name: string }[] }

/** Where the line being read sits, as a share of the screen's height. */
const ANCHOR = 0.36
/** Keys that scroll the text when it has the focus: using one is taking over from the follower. */
const SCROLL_KEYS = new Set(['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End'])
/** A paragraph is restarted rather than skipped back from when this far into it. */
const RESTART_AFTER = 2

const WAVE_BAR = 2
const WAVE_GAP = 1
const WAVE_H = 28
const MODE_KEY = 'ab-follow-mode'

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

// ---- mini waveform scrubber -------------------------------------------------------------------------------------

const FoWave = memo(function FoWave({ onSeek }: { onSeek: (t: number) => void }) {
  const { wave } = usePlayer()
  const { duration } = usePlayerClock()
  const act = usePlayerActions()
  const [ref, width] = useWidth<HTMLDivElement>(320)
  const dragging = useRef(false)

  const count = Math.max(16, Math.floor((width + WAVE_GAP) / (WAVE_BAR + WAVE_GAP)))
  const heights = useMemo(() => {
    if (wave.state !== 'ready') return null
    return Array.from({ length: count }, (_, i) => {
      const from = Math.floor((i * WAVE_BUCKETS) / count)
      const to = Math.max(from + 1, Math.floor(((i + 1) * WAVE_BUCKETS) / count))
      let peak = 0
      for (let b = from; b < to; b++) peak = Math.max(peak, wave.peaks[b] ?? 0)
      return Math.max(2, Math.round(peak * WAVE_H))
    })
  }, [wave, count])

  const fraction = (e: { clientX: number }) => {
    const box = ref.current?.getBoundingClientRect()
    return box && box.width > 0 ? Math.min(1, Math.max(0, (e.clientX - box.left) / box.width)) : 0
  }
  const onDown = (e: React.PointerEvent) => {
    dragging.current = true
    act.scrub(true)
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
    const t = fraction(e) * duration
    act.seek(t)
    onSeek(t)
  }
  const onMove = (e: React.PointerEvent) => {
    if (!dragging.current) return
    const t = fraction(e) * duration
    act.seek(t)
  }
  const onUp = (e: React.PointerEvent) => {
    if (!dragging.current) return
    dragging.current = false
    act.scrub(false)
    const el = e.currentTarget as HTMLElement
    if (el.hasPointerCapture(e.pointerId)) el.releasePointerCapture(e.pointerId)
  }

  if (wave.state !== 'ready' || !heights) {
    return <span className="fo-line" aria-hidden><i /></span>
  }

  const svgW = count * (WAVE_BAR + WAVE_GAP) - WAVE_GAP
  const svgH = WAVE_H + 4
  const bars = (cls: string) => (
    <g className={cls}>
      {heights.map((h, i) => <rect key={i} x={i * (WAVE_BAR + WAVE_GAP)} y={(svgH - h) / 2} width={WAVE_BAR} height={h} rx={1} />)}
    </g>
  )

  return (
    <div
      className="fo-wave"
      ref={ref}
      role="slider"
      tabIndex={0}
      aria-label="Seek"
      aria-valuemin={0}
      aria-valuemax={Math.max(1, Math.round(duration))}
      aria-valuenow={Math.round(act.now())}
      aria-valuetext={`${clock(act.now())} of ${clock(duration)}`}
      onPointerDown={onDown}
      onPointerMove={onMove}
      onPointerUp={onUp}
      onPointerCancel={onUp}
      onKeyDown={(e) => {
        const big = e.shiftKey ? 3 : 1
        if (e.key === 'ArrowRight') { e.preventDefault(); e.stopPropagation(); const t = act.now() + 5 * big; act.seek(t); onSeek(t) }
        else if (e.key === 'ArrowLeft') { e.preventDefault(); e.stopPropagation(); const t = act.now() - 5 * big; act.seek(t); onSeek(t) }
      }}
    >
      <svg width="100%" height={svgH} viewBox={`0 0 ${svgW} ${svgH}`} preserveAspectRatio="none" aria-hidden>
        {bars('fo-wave-rest')}
        {bars('fo-wave-played')}
      </svg>
      <i className="fo-wave-head" aria-hidden />
    </div>
  )
})

// ---- chapter list sheet -----------------------------------------------------------------------------------------

function ChapterSheet({ chapters, current, onSelect, onClose, onDelete, onRender }: {
  chapters: readonly FollowChapter[]
  current: number
  onSelect: (num: number) => void
  onClose: () => void
  onDelete?: (num: number) => void
  onRender?: (num: number) => void
}) {
  const listRef = useRef<HTMLUListElement>(null)
  const [selected, setSelected] = useState<number | null>(null)

  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>('[aria-current]')
    el?.scrollIntoView({ block: 'center' })
  }, [])

  return (
    <div className="fo-chapters" role="dialog" aria-label="Chapters">
      <div className="fo-ch-head">
        <b>Chapters</b>
        <button className="ghost icon" aria-label="Close chapter list" title="Close" onClick={onClose}><IconClose size={18} aria-hidden /></button>
      </div>
      <ul className="fo-ch-list" ref={listRef}>
        {chapters.map(ch => {
          const hasAudio = !!ch.audio?.length
          const isCurrent = ch.number === current
          const isSelected = selected === ch.number
          return (
            <li key={ch.number} className={`fo-ch-item ${isCurrent ? 'current' : ''} ${isSelected ? 'selected' : ''}`}>
              <button
                className="fo-ch-btn"
                aria-current={isCurrent || undefined}
                aria-selected={isSelected || undefined}
                onClick={() => {
                  if (hasAudio) { onSelect(ch.number); onClose() }
                  else setSelected(isSelected ? null : ch.number)
                }}
              >
                <span className="fo-ch-num">{ch.number}</span>
                <span className="fo-ch-label">{ch.label}</span>
                <span className="fo-ch-time">{ch.speech}</span>
                {isCurrent && <span className="fo-ch-eq" aria-label="Playing"><i /><i /><i /></span>}
              </button>
              <span className="fo-ch-acts">
                {hasAudio && onDelete && (
                  <button className="ghost icon fo-ch-del" aria-label={`Delete ${ch.label}`} title="Delete audio" onClick={() => onDelete(ch.number)}>
                    <IconTrash size={15} aria-hidden />
                  </button>
                )}
                {!hasAudio && isSelected && onRender && (
                  <button className="fo-ch-render" onClick={() => { onRender(ch.number); setSelected(null) }}>
                    <IconSpeak size={15} aria-hidden />Render
                  </button>
                )}
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

// ---- the paragraph being read: the only one with a span per sentence ------------------------------------------

const Sentences = memo(function Sentences({ words, units }: { words: string[]; units: Unit[] }) {
  return <>{units.map((u, i) => <Fragment key={i}>{i > 0 ? ' ' : ''}<span className="fs">{words.slice(u.first, u.last).join(' ')}</span></Fragment>)}</>
})

function Spoken({ text, seg, bullet, playing, time, anchor, seekTo }: {
  text: string
  seg: SegmentTiming
  bullet: boolean
  playing: boolean
  time: number
  anchor: (el: HTMLElement, force?: boolean) => void
  seekTo: (seconds: number) => void
}) {
  const act = usePlayerActions()
  const root = useRef<HTMLParagraphElement>(null)
  const spans = useRef<HTMLElement[]>([])
  const last = useRef(-2)

  const words = useMemo(() => wordsOf(text), [text])
  const units = useMemo(() => unitsFor(words, seg.chunks), [words, seg])

  const paint = useCallback((t: number) => {
    if (!units) return
    const i = unitAt(units, t)
    if (i === last.current) return
    last.current = i
    const list = spans.current
    list.forEach((el, k) => { el.className = k < i ? 'fs read' : k === i ? 'fs on' : 'fs' })
    const here = list[i]
    if (here) anchor(here)
  }, [units, anchor])

  useEffect(() => {
    spans.current = Array.from(root.current?.querySelectorAll<HTMLElement>('.fs') ?? [])
    last.current = -2
    if (!units && root.current) anchor(root.current)
    paint(act.now())
  }, [paint, act, units, anchor])

  useEffect(() => {
    if (!playing) return
    let frame = 0
    const tick = () => { paint(act.now()); frame = requestAnimationFrame(tick) }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [playing, paint, act])

  useEffect(() => { if (!playing) paint(act.now()) }, [playing, paint, act, time])

  const onClick = (e: React.MouseEvent) => {
    const hit = (e.target as HTMLElement).closest('.fs')
    const at = hit ? spans.current.indexOf(hit as HTMLElement) : -1
    seekTo(units && at >= 0 ? units[at]!.start : seg.start)
  }

  return (
    <p ref={root} className={`fp now ${units ? 'units' : 'whole'}`} aria-current="true" onClick={onClick}>
      {bullet && '• '}
      {units ? <Sentences words={words} units={units} /> : text}
    </p>
  )
}

// ---- every other paragraph: plain text, redrawn only when its place relative to the one being read changes ----

const Plain = memo(function Plain({ index, kind, text, place, seekTo, start }: {
  index: number; kind: string; text: string; place: 'read' | 'next' | 'far'; seekTo: (seconds: number) => void; start: number
}) {
  const head = kind === 'heading' || kind === 'title'
  return (
    <p data-i={index} className={`fp ${place} ${head ? 'head' : ''}`} onClick={() => seekTo(start)}>
      {kind === 'list_item' && '• '}{text}
    </p>
  )
})

// ---- the layer ----------------------------------------------------------------------------------------------

export function AudioFollow({ pdf, chapter, chapters, book, timing, onClose, onPlayChapter, onDeleteAudio, onRenderChapter }: {
  pdf: string
  chapter: { number: number; label: string }
  chapters?: readonly FollowChapter[]
  book: string
  timing: SegmentTiming[]
  onClose: () => void
  onPlayChapter?: (chapter: number) => void
  onDeleteAudio?: (chapter: number) => void
  onRenderChapter?: (chapter: number) => void
}) {
  const { playing, track } = usePlayer()
  const { time } = usePlayerClock()
  const act = usePlayerActions()
  const [paras, setParas] = useState<Para[] | null>(null)
  const [error, setError] = useState('')
  const [following, setFollowing] = useState(true)
  const followingRef = useRef(true)
  const root = useRef<HTMLDivElement>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const lastTop = useRef(-1)
  const opener = useRef<Element | null>(null)

  const [mode, setMode] = useState<'lyrics' | 'page'>(() => store.read(MODE_KEY) === 'page' ? 'page' : 'lyrics')
  const [chaptersOpen, setChaptersOpen] = useState(false)

  const segs = useMemo(() => spokenSegments(timing), [timing])

  // The whole chapter's text, a page at a time (the tool answers in pages).
  useEffect(() => {
    let live = true
    void (async () => {
      try {
        const all: Para[] = []
        let start = 0
        for (let pages = 0; pages < 500; pages++) {
          const page = await call<Page>('audiobook__read_chapter', { pdf, chapter: chapter.number, start })
          all.push(...page.segments)
          if (!page.truncated || page.next_start == null) break
          start = page.next_start
        }
        if (live) setParas(all)
      } catch (e) {
        if (live) setError(message(e))
      }
    })()
    return () => { live = false }
  }, [pdf, chapter.number])

  // The docked player steps aside while this is up; the bar's position is painted into this layer's own line.
  useEffect(() => {
    const el = root.current
    const unshow = act.showFull()
    const unpaint = el ? act.paintInto(el) : undefined
    return () => { unshow(); unpaint?.() }
  }, [act])

  // Focus goes in, and back to what opened it.
  useEffect(() => {
    opener.current = document.activeElement
    root.current?.focus()
    return () => { if (opener.current instanceof HTMLElement) opener.current.focus() }
  }, [])

  // Keep the line being read where the eye is. Called when the word changes; moves only when its line changes.
  const anchor = useCallback((el: HTMLElement, force = false) => {
    const box = scroller.current
    if (!box || (!followingRef.current && !force)) return
    const top = el.offsetTop
    if (top === lastTop.current && !force) return
    lastTop.current = top
    box.scrollTo({ top: top - box.clientHeight * ANCHOR })
  }, [])

  const follow = useCallback(() => {
    followingRef.current = true
    setFollowing(true)
    lastTop.current = -1
    const target = scroller.current?.querySelector<HTMLElement>('.fw.on, .fp.now')
    if (target) anchor(target, true)
  }, [anchor])

  // The reader takes over by scrolling themselves: wheel, touch, a drag on the scrollbar or a key. Programmatic
  // scrolling fires none of these, which is why it is these and not the scroll event.
  const letGo = useCallback(() => {
    if (!followingRef.current) return
    followingRef.current = false
    setFollowing(false)
  }, [])

  const seekTo = useCallback((seconds: number) => { act.seek(seconds); follow() }, [act, follow])

  const toggleMode = useCallback(() => {
    const next = mode === 'lyrics' ? 'page' : 'lyrics'
    setMode(next)
    store.write(MODE_KEY, next)
    follow()
  }, [mode, follow])

  // The paragraph being read follows the audio a frame at a time, like the words (the clock ticks four times a
  // second, which let a paragraph change trail the voice). State changes only when the paragraph does.
  const [active, setActive] = useState(-1)
  useEffect(() => {
    if (!playing) return
    let frame = 0
    const tick = () => { setActive(activeSegment(segs, act.now())); frame = requestAnimationFrame(tick) }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [segs, act, playing])
  // Paused, or sought while paused: where the clock says.
  useEffect(() => { if (!playing) setActive(activeSegment(segs, act.now())) }, [segs, act, playing, time])
  const aligned = paras !== null && paras.length === segs.length

  const go = (to: number) => { const seg = segs[Math.min(Math.max(0, to), segs.length - 1)]; if (seg) seekTo(seg.start) }
  const previous = () => {
    const seg = segs[active]
    go(seg && time - seg.start > RESTART_AFTER ? active : active - 1)
  }
  const next = () => go(active + 1)

  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'Escape') {
      if (chaptersOpen) { e.preventDefault(); setChaptersOpen(false); return }
      e.preventDefault(); onClose(); return
    }
    if (e.key === ' ' && !(e.target as HTMLElement).closest('button')) { e.preventDefault(); act.toggle(); return }
    if (e.key !== 'Tab' || !root.current) return
    const items = Array.from(root.current.querySelectorAll<HTMLElement>('button:not(:disabled), [tabindex="0"]'))
    const first = items[0]
    const end = items[items.length - 1]
    if (!first || !end) return
    if (e.shiftKey && (document.activeElement === first || document.activeElement === root.current)) { e.preventDefault(); end.focus() }
    else if (!e.shiftKey && document.activeElement === end) { e.preventDefault(); first.focus() }
  }

  const hasChapters = !!chapters?.length && chapters.length > 1

  return createPortal(
    <div
      ref={root}
      className="follow"
      role="dialog"
      aria-modal="true"
      aria-label={`Following along: ${chapter.label}`}
      tabIndex={-1}
      data-state={playing ? 'playing' : 'paused'}
      data-mode={mode}
      style={{ '--pa': toolColor('audiobook') } as CSSProperties}
      onKeyDown={onKey}
    >
      <div className="fo-top">
        <button className="ghost icon" aria-label="Close follow along" title="Close" onClick={onClose}><IconClose size={18} aria-hidden /></button>
        <div className="fo-title"><b>{chapter.label}</b><small>{track?.album ?? book}</small></div>
        <div className="fo-top-act">
          <button className="ghost icon" aria-label={mode === 'lyrics' ? 'Page view' : 'Lyrics view'} title={mode === 'lyrics' ? 'Page view' : 'Lyrics view'} onClick={toggleMode}>
            <IconPage size={18} aria-hidden />
          </button>
          {hasChapters && (
            <button className="ghost icon" aria-label="Chapters" title="Chapters" aria-expanded={chaptersOpen} onClick={() => setChaptersOpen(!chaptersOpen)}>
              <IconList size={18} aria-hidden />
            </button>
          )}
        </div>
      </div>

      {chaptersOpen && chapters && (
        <ChapterSheet
          chapters={chapters}
          current={chapter.number}
          onSelect={(num) => { if (num !== chapter.number) onPlayChapter?.(num) }}
          onClose={() => setChaptersOpen(false)}
          onDelete={onDeleteAudio}
          onRender={onRenderChapter}
        />
      )}

      <div
        className="fo-scroll"
        ref={scroller}
        role="region"
        aria-label={`Text of ${chapter.label}`}
        tabIndex={0}
        onWheel={letGo}
        onTouchMove={letGo}
        onPointerDown={(e) => { if (e.target === e.currentTarget) letGo() }}
        onKeyDown={(e) => { if (e.target === e.currentTarget && SCROLL_KEYS.has(e.key)) letGo() }}
      >
        <div className="fo-text">
          {!paras && !error && <p className="fo-note" role="status">Opening the text…</p>}
          {error && <p className="error" role="alert">{error}</p>}
          {paras && !aligned && (
            <p className="fo-note" role="status">
              The text no longer matches this recording ({paras.length} paragraphs now, {segs.length} when it was made), so it cannot be followed. Render the chapter again to follow along.
            </p>
          )}
          {aligned && paras!.map((p, i) => {
            const seg = segs[i]!
            if (i === active) {
              return <Spoken key={i} text={p.text} seg={seg} bullet={p.kind === 'list_item'} playing={playing} time={time} anchor={anchor} seekTo={seekTo} />
            }
            return <Plain key={i} index={i} kind={p.kind} text={p.text} start={seg.start} seekTo={seekTo} place={i < active ? 'read' : i === active + 1 ? 'next' : 'far'} />
          })}
        </div>
      </div>

      <div className="fo-bottom">
        {!following && (
          <button className="fo-pill" onClick={follow}><IconDown size={16} aria-hidden />Back to now</button>
        )}
        <FoWave onSeek={() => follow()} />
        <div className="fo-controls">
          <button className="pskip" aria-label="Previous paragraph" title="Previous paragraph" disabled={!aligned} onClick={previous}><IconPrevious size={20} aria-hidden /></button>
          <button className="pskip" aria-label={`Back ${BACK} seconds`} title={`Back ${BACK} seconds`} onClick={() => { act.skip(-BACK); follow() }}>
            <IconRewind size={24} strokeWidth={1.7} aria-hidden /><b>{BACK}</b>
          </button>
          <button className="pplay" aria-label={playing ? 'Pause' : 'Play'} onClick={act.toggle}>
            <span key={playing ? 'pause' : 'play'} className="pplay-icon">
              {playing ? <IconPause size={22} fill="currentColor" strokeWidth={0} aria-hidden /> : <IconPlay size={22} fill="currentColor" strokeWidth={0} aria-hidden />}
            </span>
          </button>
          <button className="pskip" aria-label={`Forward ${FORWARD} seconds`} title={`Forward ${FORWARD} seconds`} onClick={() => { act.skip(FORWARD); follow() }}>
            <IconForward size={24} strokeWidth={1.7} aria-hidden /><b>{FORWARD}</b>
          </button>
          <button className="pskip" aria-label="Next paragraph" title="Next paragraph" disabled={!aligned} onClick={next}><IconNext size={20} aria-hidden /></button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
