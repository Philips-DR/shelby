// Something finished while you were elsewhere. Toasts in the page, and a system notification
// when the tab is hidden -- a two-hour transcription is exactly when nobody is watching.

import { useEffect, useRef, useState } from 'react'
import { useAppState } from '../state'
import { IconAlert, IconClose, IconFail, IconOk } from '../ui/icons'

const SHOW_FOR_MS = 20_000

export function Notices() {
  const { events, openedAt } = useAppState()
  const [dismissed, setDismissed] = useState<Set<number>>(new Set())
  const announced = useRef<Set<number>>(new Set())
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 5000)
    return () => clearInterval(timer)
  }, [])

  // Notices from before this page opened are listed in Activity, not popped up again on
  // every reload. Until the first snapshot arrives nothing counts as fresh.
  const fresh = openedAt === null ? [] : events.filter((e) => e.type === 'notice' && e.seq > openedAt)

  useEffect(() => {
    for (const e of fresh) {
      if (announced.current.has(e.seq)) continue
      announced.current.add(e.seq)
      if (document.hidden && 'Notification' in window && Notification.permission === 'granted') {
        new Notification(e.title ?? 'Shelby', { body: e.body })
      }
    }
  }, [fresh])

  const visible = fresh.filter((e) => !dismissed.has(e.seq) && now - e.at * 1000 < SHOW_FOR_MS)
  const canAsk = 'Notification' in window && Notification.permission === 'default'

  return (
    <div className="notices" aria-live="polite">
      {visible.map((e) => (
        <div key={e.seq} className={`notice ${e.level ?? 'success'}`}>
          <span className="notice-icon" aria-hidden>
            {e.level === 'error' ? <IconFail size={17} /> : e.level === 'warning' ? <IconAlert size={17} /> : <IconOk size={17} />}
          </span>
          <div className="notice-body">
            <strong>{e.title}</strong>
            <p>{e.body}</p>
          </div>
          <button className="notice-close ghost" aria-label="Dismiss" onClick={() => setDismissed(new Set([...dismissed, e.seq]))}>
            <IconClose size={16} aria-hidden />
          </button>
        </div>
      ))}
      {canAsk && visible.length > 0 && (
        <button className="notice-ask" onClick={() => void Notification.requestPermission()}>
          Also tell me when this tab is in the background
        </button>
      )}
    </div>
  )
}
