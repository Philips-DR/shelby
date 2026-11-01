// The full audio player: a view of the one player in ../player/engine.tsx (which owns the audio and keeps
// it playing across pages), not a player of its own.
//
//   - A waveform drawn from the real audio, which is also the scrubber: click or drag to seek, hover to
//     see the time. A file too big to decode gets a plain progress track instead, never a fake waveform.
//   - Skip back 15 s and forward 30 s, playback speed, a sleep timer that fades out, volume. Where you
//     stopped is remembered per file, in this browser only.
//   - A chapter of a book also has previous and next buttons (dimmed at the first and last chapter), the
//     same two the headphones and lock screen use.
//   - Keyboard: arrows seek (Shift: more), PageUp/PageDown a minute, Home/End, Space plays and pauses.
//     The seek bar is a real slider to a screen reader, its position said in words.
//   - A chapter of a book says which chapter comes next, with a switch for whether it starts by itself.

import { useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent, type ReactNode } from 'react'
import { useWidth } from '../charts/useWidth'
import { BACK, FORWARD, usePlayer, usePlayerActions, usePlayerClock } from '../player/engine'
import { clock, spoken } from '../player/format'
import { WAVE_BUCKETS } from '../player/waveform'
import { IconClose, IconForward, IconMoon, IconMuted, IconNext, IconPause, IconPlay, IconPrevious, IconRewind, IconVolume } from './icons'
import { toolColor } from '../charts/palette'
import '../styles/player.css'

const RATES = [0.75, 1, 1.25, 1.5, 1.75, 2]
const SLEEPS = [5, 10, 15, 30, 45, 60]
const BAR = 3
const GAP = 2

// ---- a small menu (speed, sleep) --------------------------------------------------------------------------

function Menu({ label, value, children, align = 'left' }: {
  label: string
  value: ReactNode
  children: (close: () => void) => ReactNode
  align?: 'left' | 'right'
}) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const close = (refocus: boolean) => { setOpen(false); if (refocus) trigger.current?.focus() }

  useEffect(() => {
    if (!open) return
    const outside = (e: globalThis.PointerEvent) => { if (!root.current?.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('pointerdown', outside)
    // The chosen item (or the first) takes focus, so the menu is usable from the keyboard.
    const items = Array.from(root.current?.querySelectorAll<HTMLElement>('[role^=menuitem]') ?? [])
    ;(items.find((i) => i.getAttribute('aria-checked') === 'true') ?? items[0])?.focus()
    return () => document.removeEventListener('pointerdown', outside)
  }, [open])

  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'Escape') { e.stopPropagation(); close(true); return }
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp' && e.key !== 'Home' && e.key !== 'End') return
    const items = Array.from(root.current?.querySelectorAll<HTMLElement>('[role^=menuitem]') ?? [])
    if (!items.length) return
    e.preventDefault()
    const at = items.indexOf(document.activeElement as HTMLElement)
    const next = e.key === 'Home' ? 0 : e.key === 'End' ? items.length - 1 : (at + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length
    items[next]?.focus()
  }

  return (
    <div className="pmenu" ref={root} onKeyDown={onKey}>
      <button ref={trigger} className="pchip" aria-haspopup="menu" aria-expanded={open} aria-label={label} onClick={() => setOpen(!open)}>{value}</button>
      {open && <div className={`pmenu-list ${align}`} role="menu" aria-label={label}>{children(() => close(true))}</div>}
    </div>
  )
}

// ---- the player ---------------------------------------------------------------------------------------------

export function AudioPlayer({ onClose }: { onClose?: () => void }) {
  const { track, playing, waiting, failed, rate, volume, muted, resumed, sleep, wave, continues, notice } = usePlayer()
  const { time, duration, sleepLeft } = usePlayerClock()
  const act = usePlayerActions()
  const root = useRef<HTMLDivElement>(null)
  const [waveBox, width] = useWidth<HTMLDivElement>(560)
  const [remaining, setRemaining] = useState(false)
  const [hover, setHover] = useState<number | null>(null) // 0..1 along the bar under the pointer
  const dragging = useRef(false)

  // Keep the bar current, and tell the docked player to step aside while this one is actually in view. It
  // counts as in view from the start (so the dock never flashes up as this one opens), and stops counting if
  // it turns out to be hidden (inside a collapsed group) or scrolled down into the band the dock covers.
  useEffect(() => {
    const el = root.current
    if (!el) return
    const unpaint = act.paintInto(el)
    let unshow: (() => void) | null = act.showFull()
    const watch = new IntersectionObserver(([entry]) => {
      if (entry?.isIntersecting && !unshow) unshow = act.showFull()
      else if (!entry?.isIntersecting && unshow) { unshow(); unshow = null }
    }, { rootMargin: '0px 0px -160px 0px' })
    watch.observe(el)
    return () => { watch.disconnect(); unpaint(); unshow?.() }
  }, [act])

  // ---- pointer and keyboard on the seek bar
  const fraction = (e: { clientX: number }) => {
    const box = waveBox.current?.getBoundingClientRect()
    return box && box.width > 0 ? Math.min(1, Math.max(0, (e.clientX - box.left) / box.width)) : 0
  }
  const onDown = (e: PointerEvent) => {
    dragging.current = true
    act.scrub(true)
    e.currentTarget.setPointerCapture(e.pointerId)
    act.seek(fraction(e) * duration)
  }
  const onMove = (e: PointerEvent) => {
    setHover(fraction(e))
    if (dragging.current) act.seek(fraction(e) * duration)
  }
  const onUp = (e: PointerEvent) => {
    dragging.current = false
    act.scrub(false)
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId)
  }
  const onKey = (e: KeyboardEvent) => {
    const big = e.shiftKey ? 3 : 1
    const go = (to: number) => { e.preventDefault(); act.seek(to) }
    if (e.key === 'ArrowRight' || e.key === 'ArrowUp') go(time + 5 * big)
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') go(time - 5 * big)
    else if (e.key === 'PageUp') go(time + 60)
    else if (e.key === 'PageDown') go(time - 60)
    else if (e.key === 'Home') go(0)
    else if (e.key === 'End') go(duration)
    else if (e.key === ' ') { e.preventDefault(); act.toggle() }
  }

  // ---- the bars, drawn for the width the bar has
  const count = Math.max(24, Math.floor((width + GAP) / (BAR + GAP)))
  const heights = useMemo(() => {
    if (wave.state !== 'ready') return null
    return Array.from({ length: count }, (_, i) => {
      const from = Math.floor((i * WAVE_BUCKETS) / count)
      const to = Math.max(from + 1, Math.floor(((i + 1) * WAVE_BUCKETS) / count))
      let peak = 0
      for (let b = from; b < to; b++) peak = Math.max(peak, wave.peaks[b] ?? 0)
      return Math.max(3, Math.round(peak * 56))
    })
  }, [wave, count])
  const bars = (className: string) => (
    <g className={className}>
      {heights?.map((h, i) => <rect key={i} x={i * (BAR + GAP)} y={32 - h / 2} width={BAR} height={h} rx={1.5} />)}
    </g>
  )

  if (!track) return null
  const state = failed ? 'failed' : waiting && !playing ? 'loading' : playing ? 'playing' : 'paused'
  const level = muted ? 0 : volume
  const hoverTime = hover !== null ? hover * duration : null
  // A chapter of a book has chapters either side; a file with no book has neither, and no buttons to go there.
  const steps = Boolean(track.next || track.previous)

  return (
    <div
      className="player"
      ref={root}
      role="group"
      aria-label={`Audio player: ${track.title}`}
      data-state={state}
      style={{ '--pa': toolColor('audiobook') } as CSSProperties}
    >
      {(resumed !== null || onClose) && (
        <div className="player-top">
          {resumed !== null
            ? <span className="player-resume">Resumed at {clock(resumed)}<button className="plink" onClick={act.startOver}>Start over</button></span>
            : <span />}
          {onClose && <button className="ghost icon player-close" aria-label="Stop and hide the player" title="Stop and hide the player" onClick={onClose}><IconClose size={16} aria-hidden /></button>}
        </div>
      )}

      {failed ? (
        <p className="player-failed" role="alert">This browser cannot play this file. Download it to listen.</p>
      ) : (
        <>
          <div
            className="player-wave"
            ref={waveBox}
            role="slider"
            tabIndex={0}
            aria-label="Seek"
            aria-valuemin={0}
            aria-valuemax={Math.max(1, Math.round(duration))}
            aria-valuenow={Math.round(time)}
            aria-valuetext={`${spoken(time)} of ${spoken(duration)}`}
            onPointerDown={onDown}
            onPointerMove={onMove}
            onPointerUp={onUp}
            onPointerCancel={onUp}
            onPointerLeave={() => setHover(null)}
            onKeyDown={onKey}
          >
            {wave.state === 'ready' && heights ? (
              <svg width="100%" height="64" viewBox={`0 0 ${count * (BAR + GAP) - GAP} 64`} preserveAspectRatio="none" aria-hidden>
                {bars('wave-rest')}
                {bars('wave-played')}
              </svg>
            ) : wave.state === 'loading' ? (
              <div className="wave-loading" aria-hidden>
                {Array.from({ length: 48 }, (_, i) => <i key={i} style={{ '--h': `${18 + ((i * 37) % 40)}%`, '--d': `${i * 24}ms` } as CSSProperties} />)}
              </div>
            ) : (
              <div className="wave-track" aria-hidden><i /></div>
            )}
            <i className="playhead" aria-hidden />
            {hover !== null && <i className="hoverline" style={{ '--x': `${hover * 100}%` } as CSSProperties} aria-hidden />}
            {hoverTime !== null && <span className="hovertime" style={{ '--x': `${hover! * 100}%` } as CSSProperties} aria-hidden>{clock(hoverTime)}</span>}
          </div>

          <div className="player-times">
            <span>{clock(time)}</span>
            <button
              className="plink"
              onClick={() => setRemaining(!remaining)}
              title="Switch between the length and the time left"
              aria-label={remaining ? `${spoken(duration - time)} left` : `${spoken(duration)} long`}
            >
              {remaining ? `−${clock(duration - time)}` : clock(duration)}
            </button>
          </div>

          <div className="player-controls" data-steps={steps || undefined}>
            <div className="pc-side">
              <Menu label="Playback speed" value={<>{rate}×</>}>
                {(close) => RATES.map((r) => (
                  <button key={r} role="menuitemradio" aria-checked={rate === r} onClick={() => { act.setRate(r); close() }}>{r}×</button>
                ))}
              </Menu>
            </div>

            <div className="pc-main">
              {steps && (
                <button
                  className="pskip pstep"
                  aria-label={track.previous ? `Previous chapter: ${track.previous.title}` : 'Previous chapter'}
                  title={track.previous ? `Previous chapter: ${track.previous.title}` : 'This is the first chapter'}
                  disabled={!track.previous}
                  onClick={act.playPrevious}
                >
                  <IconPrevious size={22} strokeWidth={1.8} aria-hidden />
                </button>
              )}
              <button className="pskip" aria-label={`Back ${BACK} seconds`} title={`Back ${BACK} seconds`} onClick={() => act.skip(-BACK)}>
                <IconRewind size={30} strokeWidth={1.6} aria-hidden /><b>{BACK}</b>
              </button>
              <button className="pplay" aria-label={playing ? 'Pause' : 'Play'} onClick={act.toggle} disabled={state === 'loading'}>
                <span key={playing ? 'pause' : 'play'} className="pplay-icon">
                  {playing ? <IconPause size={26} fill="currentColor" strokeWidth={0} aria-hidden /> : <IconPlay size={26} fill="currentColor" strokeWidth={0} aria-hidden />}
                </span>
                {state === 'loading' && <i className="pspin" aria-hidden />}
              </button>
              <button className="pskip" aria-label={`Forward ${FORWARD} seconds`} title={`Forward ${FORWARD} seconds`} onClick={() => act.skip(FORWARD)}>
                <IconForward size={30} strokeWidth={1.6} aria-hidden /><b>{FORWARD}</b>
              </button>
              {steps && (
                <button
                  className="pskip pstep"
                  aria-label={track.next ? `Next chapter: ${track.next.title}` : 'Next chapter'}
                  title={track.next ? `Next chapter: ${track.next.title}` : 'This is the last chapter'}
                  disabled={!track.next}
                  onClick={act.playNext}
                >
                  <IconNext size={22} strokeWidth={1.8} aria-hidden />
                </button>
              )}
            </div>

            <div className="pc-side pc-right">
              <Menu
                align="right"
                label={sleep ? `Sleep timer: ${Math.ceil(sleepLeft / 60)} minutes left` : 'Sleep timer'}
                value={<><IconMoon size={15} aria-hidden />{sleep && <span>{clock(sleepLeft)}</span>}</>}
              >
                {(close) => (
                  <>
                    <button role="menuitemradio" aria-checked={sleep === null} onClick={() => { act.setSleep(null); close() }}>Off</button>
                    {SLEEPS.map((m) => (
                      <button key={m} role="menuitemradio" aria-checked={sleep?.minutes === m} onClick={() => { act.setSleep(m); close() }}>{m} minutes</button>
                    ))}
                  </>
                )}
              </Menu>
              <span className="pc-volume">
                <button className="ghost icon" aria-label={muted || volume === 0 ? 'Unmute' : 'Mute'} onClick={() => act.setMuted(!muted)}>
                  {muted || volume === 0 ? <IconMuted size={18} aria-hidden /> : <IconVolume size={18} aria-hidden />}
                </button>
                <input
                  className="pvolume"
                  type="range"
                  min={0}
                  max={1}
                  step={0.02}
                  value={level}
                  aria-label="Volume"
                  style={{ '--level': `${level * 100}%` } as CSSProperties}
                  onChange={(e) => act.setVolume(Number(e.target.value))}
                />
              </span>
            </div>
          </div>
        </>
      )}

      {(track.next || track.previous) && (
        <div className="player-next">
          <span className="player-next-text">
            {track.next ? <><span className="player-next-label">Up next</span> <b>{track.next.title}</b></> : <span className="player-next-label">The last chapter</span>}
          </span>
          <label className="pswitch">
            <input type="checkbox" role="switch" checked={continues} onChange={(e) => act.setContinues(e.target.checked)} />
            <span>Play the next chapter</span>
          </label>
        </div>
      )}
      {notice && <p className="player-notice" role="status">{notice}</p>}
    </div>
  )
}
