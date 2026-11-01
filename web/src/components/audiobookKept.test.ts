import { describe, expect, it } from 'vitest'
import type { Kept } from '../api'
import { goesWithBook, merged, withKept, withKeptBooks, withKeptSamples, type AudioEntry } from './audiobookKept'

const kept = (kind: string, name: string, labels: Record<string, unknown>, updated = 100): Kept => ({
  id: `r-${name}`, tool: 'audiobook', kind, key: `${String(labels.book)}/${name}`, labels,
  files: { audio: { id: `f-${name}`, name, bytes: 2_345_678 } }, created: updated, updated,
})

const PDF = '/data/files/abc/Great Expectations.pdf'
const read = (chapters: { number: number; stem: string; audio?: AudioEntry[] }[]) =>
  ({ analysed: true, pdf: PDF, chapters, other_audio: [] as AudioEntry[] })

describe('kept audio is put back with its chapter by the tool’s own naming', () => {
  it('matches a chapter by its stem and a speed, and never a longer stem that starts the same', () => {
    const records = [
      kept('chapter', '01-chapter-1-0.95x.mp3', { book: 'Great Expectations', speed: 0.95 }),
      kept('chapter', '01-chapter-1.mp3', { book: 'Great Expectations', speed: 1 }),
      kept('chapter', '01-chapter-10-the-end-0.95x.mp3', { book: 'Great Expectations' }),
    ]
    const o = withKept(read([{ number: 1, stem: '01-chapter-1' }]), records)
    expect(o.chapters[0]!.audio!.map((a) => a.name).sort()).toEqual(['01-chapter-1-0.95x.mp3', '01-chapter-1.mp3'])
    // An earlier reading's file, found differently, is the book's other audio, not this chapter's.
    expect(o.other_audio!.map((a) => a.name)).toEqual(['01-chapter-10-the-end-0.95x.mp3'])
  })

  it('takes only this book’s audio, and a whole-book M4B is other audio', () => {
    const records = [
      kept('chapter', '01-opening.mp3', { book: 'Another Book' }),
      kept('audiobook', 'great-expectations-0.95x.m4b', { book: 'Great Expectations', title: 'Great Expectations' }),
      kept('sample', 'abigail-test.mp3', { voice: 'abigail' }),
    ]
    const o = withKept(read([{ number: 1, stem: '01-opening' }]), records)
    expect(o.chapters[0]!.audio).toEqual([])
    expect(o.other_audio!.map((a) => a.name)).toEqual(['great-expectations-0.95x.m4b'])
  })

  it('plays a kept file by its id, with its size and speed', () => {
    const o = withKept(read([{ number: 3, stem: '03-chapter-i' }]),
      [kept('chapter', '03-chapter-i-0.95x.mp3', { book: 'Great Expectations', speed: 0.95 }, 500)])
    expect(o.chapters[0]!.audio).toEqual([{ name: '03-chapter-i-0.95x.mp3', id: 'f-03-chapter-i-0.95x.mp3', megabytes: 2.3, modified: 500, speed: 0.95 }])
  })

  it('leaves a book not yet read as it is', () => {
    const o = { analysed: false, pdf: PDF }
    expect(withKept(o, [kept('chapter', '01-x.mp3', { book: 'Great Expectations' })])).toBe(o)
  })
})

describe('the tool’s copy and the kept copy, while both exist', () => {
  it('shows one file once, the kept one, newest first', () => {
    const own: AudioEntry = { name: 'a.mp3', path: '/out/a.mp3', megabytes: 1, modified: 300 }
    const keptCopy: AudioEntry = { name: 'a.mp3', id: 'f1', megabytes: 1, modified: 200 }
    const other: AudioEntry = { name: 'b.mp3', path: '/out/b.mp3', megabytes: 1, modified: 250 }
    expect(merged([own, other], [keptCopy])).toEqual([other, keptCopy])
    expect(merged([keptCopy], [own])).toEqual([keptCopy])
  })

  it('lists a book whose audio is only kept, titled as its chapters were', () => {
    const books = withKeptBooks(
      [{ book: 'voices', files: [] }, { book: 'paper', title: 'A Paper', files: [{ name: '01.mp3', path: '/out/paper/01.mp3', megabytes: 1, modified: 1 }] }],
      [kept('chapter', '02-chapter-ii.mp3', { book: 'novel', album: 'Great Expectations', author: 'Charles Dickens' }, 50),
        kept('chapter', '01-chapter-i.mp3', { book: 'novel', album: 'Great Expectations' }, 40)],
    )
    expect(books.map((b) => [b.book, b.title, b.author, b.files.map((f) => f.name)])).toEqual([
      ['novel', 'Great Expectations', 'Charles Dickens', ['01-chapter-i.mp3', '02-chapter-ii.mp3']],
      ['paper', 'A Paper', undefined, ['01.mp3']],
    ])
  })

  it('adds kept voice samples to the tool’s own', () => {
    const samples = withKeptSamples([{ name: 'tina-test.mp3', path: '/out/voices/tina-test.mp3', megabytes: 0.1, modified: 1 }],
      [kept('sample', 'abigail-test.mp3', { voice: 'abigail' })])
    expect(samples.map((s) => [s.name, s.id ?? s.path])).toEqual([['abigail-test.mp3', 'f-abigail-test.mp3'], ['tina-test.mp3', '/out/voices/tina-test.mp3']])
  })
})

describe('a book is named as the tool names it, not by an old chapter’s tag', () => {
  const named = (book: string, title: string, author: string | null): Kept => ({
    id: `b-${book}`, tool: 'audiobook', kind: 'book', key: book, labels: { book, title, author }, files: {}, created: 1, updated: 1,
  })

  it('uses the tool’s own title and author before a chapter’s album tag', () => {
    const books = withKeptBooks([], [
      kept('chapter', '01-opening.mp3', { book: 'dreams', album: 'Praise for' }),
      named('dreams', 'Dreams and Visions', 'Jane Hamon'),
    ])
    expect(books.map((b) => [b.book, b.title, b.author])).toEqual([['dreams', 'Dreams and Visions', 'Jane Hamon']])
  })

  it('still prefers the tool’s own listing while it has the book, and falls back to the tag with no record', () => {
    const own = [{ book: 'dreams', title: 'From the listing', files: [] }]
    expect(withKeptBooks(own, [kept('chapter', '01.mp3', { book: 'dreams', album: 'A' }), named('dreams', 'Record', null)])[0]!.title)
      .toBe('From the listing')
    expect(withKeptBooks([], [kept('chapter', '01.mp3', { book: 'other', album: 'The Tag' })])[0]!.title).toBe('The Tag')
  })

  it('a title record alone is not a book on the shelf: it has no audio', () => {
    expect(withKeptBooks([], [named('dreams', 'Dreams and Visions', null)])).toEqual([])
  })

  it('goes with the book’s audio when that is deleted, and not with another book’s', () => {
    const records = [kept('chapter', '01.mp3', { book: 'a' }), kept('audiobook', 'a.m4b', { book: 'a' }), named('a', 'A', null),
      named('b', 'B', null), kept('sample', 's.mp3', { book: 'a' }), kept('chapter', '01.mp3', { book: 'b' })]
    expect(records.filter((r) => goesWithBook(r, 'a')).map((r) => r.kind).sort()).toEqual(['audiobook', 'book', 'chapter'])
  })
})
