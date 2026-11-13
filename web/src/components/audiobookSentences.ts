// Which words of a paragraph are spoken between which two times, for the follow-along view and the text beside the
// player: a sentence at a time where the render worked sentences out, a chunk at a time (up to a few sentences)
// where it only has chunks, and the whole paragraph where it has neither.
//
// The render times chunks and, since 2026-11-13, finds where each sentence of a chunk starts (audiobook/sentences.py:
// a guess from the text moved to the nearest pause in the audio). The voice itself gives back only audio, so a
// sentence start can be a few tenths of a second out. Nothing here invents a time: what is not known is not split.

import type { ChunkTiming } from './audiobookTiming'

/** Words [first, last) of a paragraph are spoken from `start` to `end`, in playback seconds. */
export interface Unit { first: number; last: number; start: number; end: number }

/** The words of a paragraph, split at whitespace: the same split the render's chunks keep (chunking joins and
 *  re-splits only at whitespace, so a paragraph's chunks hold exactly its words, in order). */
export const wordsOf = (text: string): string[] => text.split(/\s+/).filter(Boolean)

/** Share a paragraph's own words out among its chunks, in order, by how many words each chunk had. `null` when a
 *  chunk's count is missing or the counts do not add up to the paragraph's words (the text was corrected after
 *  the render, or the timing is from before the counts were kept): the page then shows the paragraph whole. */
export function wordsByChunk(words: string[], chunks: ChunkTiming[]): string[][] | null {
  const counts = chunks.map((c) => (c.text !== undefined ? wordsOf(c.text).length : c.words))
  if (counts.some((n) => n === undefined || n < 0)) return null
  if ((counts as number[]).reduce((a, b) => a + b, 0) !== words.length) return null
  const shared: string[][] = []
  let at = 0
  for (const n of counts as number[]) {
    shared.push(words.slice(at, at + n))
    at += n
  }
  return shared
}

/** The paragraph cut where the render knows it was spoken: by sentence where a chunk has its sentences, else by
 *  chunk. `null` when the words cannot be shared out among the chunks at all. */
export function unitsFor(words: string[], chunks: ChunkTiming[]): Unit[] | null {
  const shared = wordsByChunk(words, chunks)
  if (!shared) return null
  const units: Unit[] = []
  let at = 0
  chunks.forEach((chunk, i) => {
    const n = shared[i]!.length
    const sentences = chunk.sentences
    if (sentences && sentences.length > 0 && sentences.reduce((sum, s) => sum + s.words, 0) === n) {
      let first = at
      sentences.forEach((s, k) => {
        const end = k + 1 < sentences.length ? sentences[k + 1]!.start : chunk.end
        if (s.words > 0) units.push({ first, last: first + s.words, start: k === 0 ? chunk.start : s.start, end })
        first += s.words
      })
    } else if (n > 0) {
      units.push({ first: at, last: at + n, start: chunk.start, end: chunk.end })
    }
    at += n
  })
  return units
}

/** The unit being spoken at `time`: the last whose start has passed (so a rest between two stays with the one before).
 *  -1 before the first begins. */
export function unitAt(units: readonly Unit[], time: number): number {
  let low = 0
  let high = units.length - 1
  let found = -1
  while (low <= high) {
    const mid = (low + high) >> 1
    if (units[mid]!.start <= time) { found = mid; low = mid + 1 } else high = mid - 1
  }
  return found
}
