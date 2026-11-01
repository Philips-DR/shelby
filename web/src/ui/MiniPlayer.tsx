// The docked player: what keeps an audiobook in reach once you leave the Audiobooks page. It shows only
// while something is loaded and no full player is on screen (the full one is the same player, bigger).

import { useEffect, useRef, type CSSProperties } from 'react'
import { BACK, FORWARD, usePlayer, usePlayerActions, usePlayerClock } from '../player/engine'
import { clock, spoken } from '../player/format'
import { askToShow } from '../player/showing'
import { IconAudiobooks, IconClose, IconForward, IconPause, IconPlay, IconRewind } from './icons'
import { toolColor } from '../charts/palette'
import '../styles/player.css'

export function MiniPlayer({ goToBooks }: { goToBooks: () => void }) {
  const { track, playing, waiting, failed, fullViews } = usePlayer()
  const { time, duration } = usePlayerClock()
  const act = usePlayerActions()
  const visible = track !== null && fullViews === 0
  const root = useRef<HTMLDivElement>(null)

  useEffect(() => (visible && root.current ? act.paintInto(root.current) : undefined), [act, visible])

  if (!track || !visible) return null
  // Tapping it goes to where the audio is playing: the book, with that chapter in view. A file with no book of its
  // own (the whole-book audio) has nowhere more particular than the page.
  const show = () => {
    if (track.home) askToShow(track.home)
    goToBooks()
  }
  const where = track.home ? 'Show it playing in its book' : 'Open the audiobooks page'
  const loading = waiting && !playing && !failed
  return (
    <div
      className="mini"
      ref={root}
      role="region"
      aria-label="Now playing"
      data-state={failed ? 'failed' : loading ? 'loading' : playing ? 'playing' : 'paused'}
      style={{ '--pa': toolColor('audiobook') } as CSSProperties}
    >
      <span className="mini-line" aria-hidden><i /></span>
      <button className="mini-info" onClick={show} title={where} aria-label={`${track.title}. ${where}`}>
        <span className="mini-tile" aria-hidden>
          {playing ? <span className="mini-eq"><i /><i /><i /></span> : <IconAudiobooks size={17} strokeWidth={2} />}
        </span>
        <span className="mini-text">
          <b>{track.title}</b>
          <small aria-label={failed ? 'This browser cannot play this file' : `${spoken(time)} of ${spoken(duration)}`}>
            {failed ? 'Cannot play this file' : `${clock(time)} / ${clock(duration)}`}
          </small>
        </span>
      </button>
      <button className="pskip mini-skip" aria-label={`Back ${BACK} seconds`} title={`Back ${BACK} seconds`} onClick={() => act.skip(-BACK)}>
        <IconRewind size={22} strokeWidth={1.7} aria-hidden /><b>{BACK}</b>
      </button>
      <button className="pplay mini-play" aria-label={playing ? 'Pause' : 'Play'} onClick={act.toggle} disabled={loading || failed}>
        <span key={playing ? 'pause' : 'play'} className="pplay-icon">
          {playing ? <IconPause size={20} fill="currentColor" strokeWidth={0} aria-hidden /> : <IconPlay size={20} fill="currentColor" strokeWidth={0} aria-hidden />}
        </span>
        {loading && <i className="pspin" aria-hidden />}
      </button>
      <button className="pskip mini-skip mini-forward" aria-label={`Forward ${FORWARD} seconds`} title={`Forward ${FORWARD} seconds`} onClick={() => act.skip(FORWARD)}>
        <IconForward size={22} strokeWidth={1.7} aria-hidden /><b>{FORWARD}</b>
      </button>
      <button className="ghost icon mini-close" aria-label="Stop and hide the player" title="Stop and hide the player" onClick={act.close}>
        <IconClose size={16} aria-hidden />
      </button>
    </div>
  )
}
