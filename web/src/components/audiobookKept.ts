// What Shelby keeps of audiobook's work (assistant/records.py), put back with its book and its chapter: kept apart
// from the page so it can be tested.
//
// The server files a render's chapters, a book's M4B and a voice's sample under the tool's own labels, and the tool
// lets go of its copies. Putting them back with their book and chapter is this page's job, by the tool's own rules:
// the server does not know what a chapter is.

import type { Kept } from '../api'
import { fileName } from '../usePoll'

/** A file of audio: kept in Shelby's store (`id`), or still at the tool's bench (`path`), where a render leaves it
 *  until Shelby has taken it (assistant/collect.py). */
export interface AudioEntry { name: string; id?: string; path?: string; megabytes: number; modified: number; speed?: number }

export const audioKey = (a: AudioEntry) => a.id ?? a.path ?? ''

/** A book with audio, as the tool lists them (operations.list_audiobooks). */
export interface BookAudio { book: string; title?: string; author?: string | null; files: AudioEntry[] }

/** A book's overview, as far as matching audio to its chapters needs it (operations.book_overview). */
interface Overview {
  analysed: boolean
  pdf?: string
  chapters?: { stem?: string; audio?: AudioEntry[] }[]
  other_audio?: AudioEntry[]
}

const label = (r: Kept | undefined, key: string) => (typeof r?.labels[key] === 'string' ? (r.labels[key] as string) : undefined)
/** The book a kept record belongs to: the tool's folder for it, which is named for the PDF. */
export const bookOf = (r: Kept) => label(r, 'book')

/** Everything Shelby keeps of one book that goes when its audio does: its chapters, its whole-book file, and the
 *  record that names it (the tool's folder for it is deleted with it). */
export const goesWithBook = (r: Kept, book: string) =>
  (r.kind === 'chapter' || r.kind === 'audiobook' || r.kind === 'book') && bookOf(r) === book
const isAudioEntry = (a: AudioEntry | null): a is AudioEntry => a !== null
const pdfStem = (path: string) => fileName(path).replace(/\.pdf$/i, '')

/** A kept record's audio, as this page lists audio (megabytes as the tool counts them). */
export function keptEntry(r: Kept): AudioEntry | null {
  const f = r.files.audio
  if (!f) return null
  return {
    name: f.name, id: f.id, megabytes: Math.round(f.bytes / 1e5) / 10, modified: r.updated,
    ...(typeof r.labels.speed === 'number' ? { speed: r.labels.speed } : {}),
  }
}

/** Newest first. Between Shelby filing a file and the tool letting go of it, both have it: the kept one stands. */
export function merged(...lists: AudioEntry[][]): AudioEntry[] {
  const byName = new Map<string, AudioEntry>()
  for (const a of lists.flat()) {
    const had = byName.get(a.name)
    if (!had || (a.id && !had.id)) byName.set(a.name, a)
  }
  return [...byName.values()].sort((a, b) => b.modified - a.modified)
}

const byName = (a: AudioEntry, b: AudioEntry) => a.name.localeCompare(b.name)

/** Books with audio: the tool's own list (what it has not yet handed over) with what Shelby keeps. */
export function withKeptBooks(own: BookAudio[], kept: Kept[]): BookAudio[] {
  const books = new Map(own.filter((b) => b.book !== 'voices').map((b) => [b.book, b]))
  // A book's title and author as the tool names them: what its own listing said before it handed its audio over.
  // Better than a chapter's embedded tag, which an early reading of the book may have got wrong.
  const named = new Map(kept.filter((r) => r.kind === 'book').map((r) => [r.key, r]))
  for (const r of kept) {
    const book = bookOf(r)
    const entry = r.kind === 'chapter' || r.kind === 'audiobook' ? keptEntry(r) : null
    if (!book || !entry) continue
    const had = books.get(book)
    books.set(book, {
      book,
      title: had?.title ?? label(named.get(book), 'title') ?? label(r, 'album') ?? label(r, 'title'),
      author: had?.author ?? label(named.get(book), 'author') ?? label(r, 'author') ?? null,
      files: merged(had?.files ?? [], [entry]).sort(byName),
    })
  }
  const newest = (b: BookAudio) => Math.max(0, ...b.files.map((f) => f.modified))
  return [...books.values()].sort((a, b) => newest(b) - newest(a))
}

/** Voice samples: the tool's own, with the ones Shelby keeps. */
export function withKeptSamples(own: AudioEntry[], kept: Kept[]): AudioEntry[] {
  return merged(own, kept.filter((r) => r.kind === 'sample').map(keptEntry).filter(isAudioEntry)).sort(byName)
}

// After a chapter's stem, only its speed may follow, as the tool matches its own files (names.chapter_audio): so
// "01-chapter-1" never claims "01-chapter-10-…".
const SPEED_AND_SUFFIX = /^(?:-\d+(?:\.\d+)?x)?\.mp3$/

/** The tool's chapters, each with the audio Shelby keeps for it. What matches no chapter of this reading -- the
 *  whole-book M4B, or chapters of an earlier reading that were found differently -- is the book's other audio. */
export function withKept<O extends Overview>(o: O, kept: Kept[]): O {
  if (!o.analysed || !o.pdf) return o
  const book = pdfStem(o.pdf)
  const mine = kept.filter((r) => (r.kind === 'chapter' || r.kind === 'audiobook') && bookOf(r) === book)
  const claimed = new Set<string>()
  const chapters = (o.chapters ?? []).map((c) => {
    const found = mine.filter((r) => {
      const name = r.files.audio?.name
      return r.kind === 'chapter' && !!c.stem && !!name && name.startsWith(c.stem) && SPEED_AND_SUFFIX.test(name.slice(c.stem.length))
    })
    found.forEach((r) => claimed.add(r.id))
    return { ...c, audio: merged(c.audio ?? [], found.map(keptEntry).filter(isAudioEntry)) }
  })
  const others = mine.filter((r) => !claimed.has(r.id)).map(keptEntry).filter(isAudioEntry)
  return { ...o, chapters, other_audio: merged(o.other_audio ?? [], others) }
}
