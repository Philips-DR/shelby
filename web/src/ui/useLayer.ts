// Something that opens on top of a page (a book, a message, a sheet) and that Back should close, as it does in a
// phone's own apps. A page is the URL hash (useRoute.ts); a layer is not part of it, so Back skipped every layer
// and went to the page before: from an open book to Chat, if that was where you had come from.
//
// The history entry is the record of what is open. A layer's value is kept in `history.state` under its key, and
// the page follows the entry whichever way it moves: Back closes the layer, Forward or a reload brings it back.
// Opening pushes an entry, changing to another value replaces it, and closing from inside the page (an "All
// books" button) goes Back, so the button and the phone's Back do the same thing and leave no entry behind.
//
// A `modal` layer (a sheet, the search box) is not somewhere to come back to: choosing a page from it replaces its
// entry instead of stacking on it (useRoute.ts), so Back from that page goes to the page you were on, not the sheet.

import { useEffect, useRef } from 'react'

export type Step = 'none' | 'push' | 'replace' | 'back'

export const same = (a: unknown, b: unknown): boolean => JSON.stringify(a ?? null) === JSON.stringify(b ?? null)

/** What the history needs, given what the layer is now, what it was a moment ago, and what the current entry says. */
export function step<T>(now: T | null, was: T | null, recorded: T | null): Step {
  if (same(now, recorded)) return 'none'
  if (now !== null) return recorded === null ? 'push' : 'replace'
  // Closed from inside the page: take its entry away. (Closed by Back, the entry is already gone and nothing differs;
  // never opened, there is nothing to take away.)
  return was !== null ? 'back' : 'none'
}

const recordedUnder = <T,>(key: string): T | null => ((history.state as Record<string, unknown> | null)?.[key] ?? null) as T | null

/** `value` is what is open (null: nothing); `set` changes it. Both are the page's own state; the history follows. */
export function useLayer<T>(key: string, value: T | null, set: (to: T | null) => void, modal = false): void {
  const latest = useRef({ value, set })
  latest.current = { value, set }
  const was = useRef<T | null>(null)

  // Arriving at an entry that has the layer open (a reload, or Back or Forward to it): open it. After that, follow
  // the entry as it moves.
  useEffect(() => {
    const open = recordedUnder<T>(key)
    if (open !== null && latest.current.value === null) latest.current.set(open)
    const follow = () => {
      const now = recordedUnder<T>(key)
      if (!same(now, latest.current.value)) latest.current.set(now)
    }
    window.addEventListener('popstate', follow)
    return () => window.removeEventListener('popstate', follow)
  }, [key])

  // The page opened, changed or closed the layer: make the history say so.
  useEffect(() => {
    const action = step(value, was.current, recordedUnder<T>(key))
    was.current = value
    const entry = { ...(history.state as object | null), [key]: value, ...(modal ? { modal: true } : {}) }
    if (action === 'push') history.pushState(entry, '')
    else if (action === 'replace') history.replaceState(entry, '')
    else if (action === 'back') history.back()
  }, [value, key, modal])
}
