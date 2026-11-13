// Timing data for synchronized transcript highlighting during audiobook playback.
//
// Produced by the render (audiobook/render.py) and stored two ways:
// - in the sidecar JSON beside each MP3 (with text, in playback seconds);
// - in the kept record's labels (compact, no text — matched to the chapter's segments by index).

import { fetchFileJSON, type Kept } from '../api'
import type { AudioEntry } from './audiobookKept'

/** Where one sentence of a chunk starts, and how many words it has: its words run to the next sentence's start. */
export interface SentenceTiming { words: number; start: number }
/** `text` is there in the sidecar; `words` (how many) in the kept record's compact form, which has no text.
 *  `sentences` is there for a chapter rendered since they were worked out (audiobook/sentences.py). */
export interface ChunkTiming { text?: string; words?: number; sentences?: SentenceTiming[]; start: number; end: number }
export interface SegmentTiming { kind: string; text?: string; start: number; end: number; chunks: ChunkTiming[] }

interface Sidecar { segments?: SegmentTiming[] }
interface CompactChunk { start: number; end: number; words?: number; sentences?: SentenceTiming[] }
interface CompactSegment { kind: string; start: number; end: number; chunks: CompactChunk[] }

/** Get timing for a chapter's audio. Tries the kept record's labels first (survives release),
 *  then the sidecar JSON beside the MP3 (still in the tool's output folder). Returns null if
 *  neither has timing (rendered before this feature, or the file is gone). */
export async function fetchTiming(audio: AudioEntry, kept: Kept[]): Promise<SegmentTiming[] | null> {
  // Kept record: compact timing in labels, no text.
  if (audio.id) {
    const record = kept.find((r) => r.files.audio?.id === audio.id)
    const raw = record?.labels?.timing
    if (Array.isArray(raw) && raw.length > 0) return (raw as CompactSegment[]).map(fromCompact)
  }

  // Tool output: the sidecar JSON beside the MP3.
  if (audio.path) {
    const jsonPath = audio.path.replace(/\.mp3$/i, '.json')
    try {
      const data = await fetchFileJSON<Sidecar>(jsonPath)
      if (data?.segments?.length) return data.segments
    } catch {
      // no sidecar, or not JSON: no timing
    }
  }
  return null
}

function fromCompact(seg: CompactSegment): SegmentTiming {
  return {
    kind: seg.kind, start: seg.start, end: seg.end,
    chunks: seg.chunks.map((c) => ({
      start: c.start, end: c.end,
      ...(typeof c.words === 'number' ? { words: c.words } : {}),
      ...(Array.isArray(c.sentences) ? { sentences: c.sentences } : {}),
    })),
  }
}

/** The timing entries for the chapter's text: the announcement ("Chapter 6.", the title) is spoken first and is not
 *  among the text's segments, so the rest line up with them by index. */
export function spokenSegments(timing: SegmentTiming[]): SegmentTiming[] {
  const first = timing.findIndex((t) => t.kind !== 'announcement')
  return first < 0 ? [] : timing.slice(first)
}

/** The segment whose time bracket contains `time`, or -1. */
export function activeSegment(timing: SegmentTiming[], time: number): number {
  for (let i = 0; i < timing.length; i++) {
    if (time >= timing[i]!.start && time <= timing[i]!.end) return i
  }
  // In a silence gap between segments: the one just passed.
  for (let i = timing.length - 1; i >= 0; i--) {
    if (time > timing[i]!.end) return i
  }
  return -1
}
