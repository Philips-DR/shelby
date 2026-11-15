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

import { Fragment, memo, useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore, type CSSProperties, type KeyboardEvent } from 'react'
import { createPortal } from 'react-dom'
import { call } from '../call'
import { useWidth } from '../charts/useWidth'
import { BACK, FORWARD, usePlayer, usePlayerActions, usePlayerClock } from '../player/engine'
import { clock } from '../player/format'
import { store } from '../player/storage'
import { WAVE_BUCKETS } from '../player/waveform'
import { IconAudiobooks, IconClose, IconForward, IconList, IconNext, IconPage, IconPause, IconPlay, IconPrevious, IconRewind, IconSpeak, IconTrash } from '../ui/icons'
import { activeSegment, spokenSegments, type SegmentTiming } from './audiobookTiming'
import { unitAt, unitsFor, wordsOf, type Unit } from './audiobookSentences'
import '../styles/player.css'
import '../styles/panels/follow.css'

interface Para { kind: string; text: string }
interface Page { segments: Para[]; truncated: boolean; next_start: number | null }

/** A chapter as far as the chapter list needs it. */
export interface FollowChapter { number: number; label: string; speech: string; audio?: { name: string }[] }

/** Where the highlighted text sits, as a share of the scroller's visible height.
 * Slightly above center so the active sentence stays clear of the bottom fade mask. */
const ANCHOR = 0.42
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

// ---- the sentence spans inside the paragraph being read -------------------------------------------------------

const Sentences = memo(function Sentences({ words, units }: { words: string[]; units: Unit[] }) {
  return <>{units.map((u, i) => <Fragment key={i}>{i > 0 ? ' ' : ''}<span className="fs">{words.slice(u.first, u.last).join(' ')}</span></Fragment>)}</>
})

// ---- sentence painting: renderless, subscribed to the player clock, paints the spans via the DOM. Only
//      mounted for the paragraph being read, so its clock subscription does not re-render the others. ----------

function Highlighter({ para, units, anchor }: {
  para: React.RefObject<HTMLParagraphElement | null>
  units: Unit[]
  anchor: (el: HTMLElement) => void
}) {
  const { playing } = usePlayer()
  const { time } = usePlayerClock()
  const act = usePlayerActions()
  const spans = useRef<HTMLElement[]>([])
  const last = useRef(-2)

  const paint = useCallback((t: number) => {
    const i = unitAt(units, t)
    if (i === last.current) return
    const prev = last.current
    last.current = i
    const list = spans.current
    if (prev >= 0 && i === prev + 1 && prev < list.length) {
      if (list[prev]) list[prev]!.className = 'fs read'
      if (list[i]) list[i]!.className = 'fs on'
    } else {
      list.forEach((el, k) => { el.className = k < i ? 'fs read' : k === i ? 'fs on' : 'fs' })
    }
    const here = list[i]
    if (here) anchor(here)
  }, [units, anchor])

  useEffect(() => {
    spans.current = Array.from(para.current?.querySelectorAll<HTMLElement>('.fs') ?? [])
    last.current = -2
    paint(act.now())
  }, [paint, act, para])

  useEffect(() => {
    if (!playing) return
    let frame = 0
    const tick = () => { paint(act.now()); frame = requestAnimationFrame(tick) }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [playing, paint, act])

  useEffect(() => { if (!playing) paint(act.now()) }, [playing, paint, act, time])

  return null
}

// ---- every paragraph: the same DOM element whether active or not, so CSS transitions fire on the change ------

const Paragraph = memo(function Paragraph({ index, kind, text, seg, bullet, anchor, seekTo, subscribe, getActive }: {
  index: number; kind: string; text: string; seg: SegmentTiming
  bullet: boolean
  anchor: (el: HTMLElement) => void; seekTo: (seconds: number) => void
  subscribe: (l: () => void) => () => void; getActive: () => number
}) {
  const place = useSyncExternalStore(subscribe, () => {
    const a = getActive()
    return a === index ? 'now' : index < a ? 'read' : a + 1 === index ? 'next' : 'far'
  })
  const isActive = place === 'now'
  const root = useRef<HTMLParagraphElement>(null)
  const words = useMemo(() => wordsOf(text), [text])
  const units = useMemo(() => isActive ? unitsFor(words, seg.chunks) : null, [isActive, words, seg])
  const head = kind === 'heading' || kind === 'title'

  useEffect(() => {
    if (isActive && !units && root.current) anchor(root.current)
  }, [isActive, units, anchor])

  const onClick = (e: React.MouseEvent) => {
    if (isActive && units) {
      const hit = (e.target as HTMLElement).closest('.fs')
      if (hit && root.current) {
        const all = root.current.querySelectorAll('.fs')
        const at = Array.prototype.indexOf.call(all, hit)
        if (at >= 0 && units[at]) { seekTo(units[at]!.start); return }
      }
    }
    seekTo(seg.start)
  }

  return (
    <p
      ref={root}
      data-i={index}
      className={`fp ${place} ${isActive && units ? 'units' : isActive ? 'whole' : ''} ${head ? 'head' : ''}`}
      aria-current={isActive || undefined}
      onClick={onClick}
    >
      {bullet && '• '}
      {isActive && units
        ? <><Sentences words={words} units={units} /><Highlighter para={root} units={units} anchor={anchor} /></>
        : text}
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
  const { time, duration } = usePlayerClock()
  const act = usePlayerActions()
  const [paras, setParas] = useState<Para[] | null>(null)
  const [error, setError] = useState('')
  const root = useRef<HTMLDivElement>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const lastTop = useRef(-1)
  const scrollFrame = useRef(0)
  const scrollGoal = useRef<number | null>(null)
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

  useEffect(() => () => cancelAnimationFrame(scrollFrame.current), [])

  // Reset scroll state when the chapter changes so the first scroll is instant.
  useEffect(() => { scrollGoal.current = null; lastTop.current = -1 }, [chapter.number])

  // Keep the highlighted element at ANCHOR of the scroller's visible height, using a per-frame
  // lerp instead of CSS scroll-behavior so the text tracks the voice without the browser's
  // uncontrollable smooth-scroll lag. First scroll is instant (the view is still fading in).
  const anchor = useCallback((el: HTMLElement) => {
    const box = scroller.current
    if (!box) return
    const elMid = el.offsetTop + el.offsetHeight / 2
    if (Math.abs(elMid - lastTop.current) < 2) return
    lastTop.current = elMid
    const goal = elMid - box.clientHeight * ANCHOR

    if (scrollGoal.current === null) {
      box.scrollTop = goal
      scrollGoal.current = goal
      return
    }

    scrollGoal.current = goal
    if (scrollFrame.current) return

    const step = () => {
      const target = scrollGoal.current!
      const diff = target - box.scrollTop
      if (Math.abs(diff) < 0.5) {
        box.scrollTop = target
        scrollFrame.current = 0
        return
      }
      box.scrollTop += diff * 0.2
      scrollFrame.current = requestAnimationFrame(step)
    }
    scrollFrame.current = requestAnimationFrame(step)
  }, [])

  const follow = useCallback(() => {
    lastTop.current = -1
    const target = scroller.current?.querySelector<HTMLElement>('.fs.on, .fp.now')
    if (target) anchor(target)
  }, [anchor])

  const seekTo = useCallback((seconds: number) => { act.seek(seconds); follow() }, [act, follow])

  const toggleMode = useCallback(() => {
    const next = mode === 'lyrics' ? 'page' : 'lyrics'
    setMode(next)
    store.write(MODE_KEY, next)
    follow()
  }, [mode, follow])

  // The paragraph being read: tracked outside React state so a change re-renders only the 2-4 paragraphs whose
  // place actually changes (via useSyncExternalStore in Paragraph), not the entire list.
  const activeRef = useRef(-1)
  const activeListeners = useRef(new Set<() => void>())
  const subscribeActive = useCallback((l: () => void) => { activeListeners.current.add(l); return () => { activeListeners.current.delete(l) } }, [])
  const getActive = useCallback(() => activeRef.current, [])
  const setActiveVal = useCallback((v: number) => {
    if (v === activeRef.current) return
    activeRef.current = v
    for (const l of activeListeners.current) l()
  }, [])

  useEffect(() => {
    if (!playing) return
    let frame = 0
    const tick = () => { setActiveVal(activeSegment(segs, act.now())); frame = requestAnimationFrame(tick) }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [segs, act, playing, setActiveVal])
  useEffect(() => { if (!playing) setActiveVal(activeSegment(segs, act.now())) }, [segs, act, playing, time, setActiveVal])
  const aligned = paras !== null && paras.length === segs.length

  const go = (to: number) => { const seg = segs[Math.min(Math.max(0, to), segs.length - 1)]; if (seg) seekTo(seg.start) }
  const previous = () => {
    const a = activeRef.current
    const seg = segs[a]
    go(seg && time - seg.start > RESTART_AFTER ? a : a - 1)
  }
  const next = () => go(activeRef.current + 1)

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
      style={{ '--pa': '#06b6d4' } as CSSProperties}
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
      >
        <div className="fo-text">
          {!paras && !error && <p className="fo-note" role="status">Opening the text…</p>}
          {error && <p className="error" role="alert">{error}</p>}
          {paras && !aligned && (
            <p className="fo-note" role="status">
              The text no longer matches this recording ({paras.length} paragraphs now, {segs.length} when it was made), so it cannot be followed. Render the chapter again to follow along.
            </p>
          )}
          {aligned && paras!.map((p, i) => (
            <Paragraph
              key={i}
              index={i}
              kind={p.kind}
              text={p.text}
              seg={segs[i]!}
              bullet={p.kind === 'list_item'}
              anchor={anchor}
              seekTo={seekTo}
              subscribe={subscribeActive}
              getActive={getActive}
            />
          ))}
        </div>
      </div>

      <div className="fo-bottom">
        <div className="fo-now-playing">
          <span className="fo-np-tile" aria-hidden><IconAudiobooks size={18} strokeWidth={2} /></span>
          <span className="fo-np-info">
            <b>{chapter.label}</b>
            <small>{track?.album ?? book}</small>
          </span>
          <span className="fo-np-time">
            <span>{clock(time)}</span>
            <span className="fo-np-sep">/</span>
            <span>{clock(duration)}</span>
          </span>
        </div>
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
