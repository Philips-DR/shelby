// Which chapter plays after (or before) another. A chapter with no audio yet is passed over, so a book
// whose foreword was never rendered goes from its opening straight to chapter 1.

/** A chapter, as far as going on to the next needs it: whether it has audio at all, kept or at the tool's bench. */
export interface Playable { number: number; audio?: readonly unknown[] }

export function adjacent<T extends Playable>(chapters: readonly T[], number: number, step: 1 | -1): T | null {
  const ordered = [...chapters].sort((a, b) => a.number - b.number)
  const at = ordered.findIndex((c) => c.number === number)
  if (at < 0) return null
  for (let i = at + step; i >= 0 && i < ordered.length; i += step) {
    if (ordered[i]!.audio?.length) return ordered[i]!
  }
  return null
}

/** Fetch the next chapter this long before the one playing ends, so the next starts without a gap. */
export const PREFETCH_SECONDS = 90

/** Whether the next chapter starts by itself; on unless this browser was told otherwise. */
export const CONTINUE_KEY = 'assistant-player-continue'
export const continuesFrom = (stored: string | null): boolean => stored !== '0'
