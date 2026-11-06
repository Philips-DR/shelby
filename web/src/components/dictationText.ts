// Words for the chat box's microphone, kept apart from the hook so they can be tested without a browser.

/** The dictated words added to what is already in the message box, with one space between. */
export function withDictated(draft: string, said: string): string {
  const words = said.trim()
  if (!words) return draft
  if (!draft.trim()) return words
  return /\s$/.test(draft) ? draft + words : `${draft} ${words}`
}

/** Why the microphone could not start, in words a person can act on. */
export function micProblem(error: unknown): string {
  const name = error instanceof DOMException ? error.name : ''
  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return 'The microphone is blocked for this page. Allow it in the browser’s site settings, then try again.'
  }
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return 'No microphone was found.'
  if (name === 'NotReadableError') return 'The microphone is in use by another program.'
  return error instanceof Error ? error.message : String(error)
}

/** 0:07, 1:45: how long the clip is so far. */
export function clock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}
