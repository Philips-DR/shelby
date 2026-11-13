import { describe, expect, it } from 'vitest'
import { unitAt, unitsFor, wordsByChunk, wordsOf } from './audiobookSentences'

describe('wordsByChunk', () => {
  const words = wordsOf('One two three.  Four five\nsix seven.')

  it('splits at any whitespace', () => {
    expect(words).toEqual(['One', 'two', 'three.', 'Four', 'five', 'six', 'seven.'])
  })

  it('shares the words out by each chunk’s word count, in order', () => {
    const chunks = [{ start: 0, end: 1, words: 3 }, { start: 2, end: 3, words: 4 }]
    expect(wordsByChunk(words, chunks)).toEqual([['One', 'two', 'three.'], ['Four', 'five', 'six', 'seven.']])
  })

  it('counts a chunk’s own text when it has it (the sidecar), whatever its count says', () => {
    const chunks = [{ start: 0, end: 1, text: 'One two three.' }, { start: 2, end: 3, text: 'Four five six seven.' }]
    expect(wordsByChunk(words, chunks)?.map((c) => c.length)).toEqual([3, 4])
  })

  it('is null when a count is missing, or the counts do not add up to the paragraph', () => {
    expect(wordsByChunk(words, [{ start: 0, end: 1 }, { start: 2, end: 3, words: 4 }])).toBeNull()
    expect(wordsByChunk(words, [{ start: 0, end: 1, words: 3 }, { start: 2, end: 3, words: 3 }])).toBeNull()
    expect(wordsByChunk(words, [{ start: 0, end: 1, words: 9 }])).toBeNull()
  })
})

describe('unitsFor', () => {
  // 12 words: sentences of 3, 2, 4 and 3; the chunks are the first two sentences (5 words) and the last two (7)
  const words = wordsOf('A b c. D e. F g h i. J k l.')

  it('cuts a chunk by its sentences, each running to the next one\u2019s start and the last to the chunk\u2019s end', () => {
    const chunks = [
      { start: 10, end: 20, words: 5, sentences: [{ words: 3, start: 10 }, { words: 2, start: 16.5 }] },
      { start: 21, end: 30, words: 7, sentences: [{ words: 4, start: 21 }, { words: 3, start: 27 }] },
    ]
    expect(unitsFor(words, chunks)).toEqual([
      { first: 0, last: 3, start: 10, end: 16.5 },
      { first: 3, last: 5, start: 16.5, end: 20 },
      { first: 5, last: 9, start: 21, end: 27 },
      { first: 9, last: 12, start: 27, end: 30 },
    ])
  })

  it('cuts by chunk where a chunk has no sentences (a chapter rendered before they were found)', () => {
    const chunks = [{ start: 0, end: 5, words: 5 }, { start: 6, end: 12, words: 7 }]
    expect(unitsFor(words, chunks)).toEqual([{ first: 0, last: 5, start: 0, end: 5 }, { first: 5, last: 12, start: 6, end: 12 }])
  })

  it('mixes the two: sentences where a chunk has them, the chunk where it does not', () => {
    const chunks = [
      { start: 0, end: 5, words: 5, sentences: [{ words: 3, start: 0 }, { words: 2, start: 2.5 }] },
      { start: 6, end: 12, words: 7 },
    ]
    expect(unitsFor(words, chunks)?.map((u) => [u.first, u.last])).toEqual([[0, 3], [3, 5], [5, 12]])
  })

  it('ignores sentences whose words do not add up to their chunk', () => {
    const chunks = [{ start: 0, end: 12, words: 12, sentences: [{ words: 3, start: 0 }, { words: 2, start: 5 }] }]
    expect(unitsFor(words, chunks)).toEqual([{ first: 0, last: 12, start: 0, end: 12 }])
  })

  it('is null when the words cannot be shared out among the chunks', () => {
    expect(unitsFor(words, [{ start: 0, end: 5 }])).toBeNull()
    expect(unitsFor(words, [{ start: 0, end: 5, words: 4 }])).toBeNull()
  })
})

describe('unitAt', () => {
  const units = [
    { first: 0, last: 3, start: 2, end: 4 },
    { first: 3, last: 5, start: 4.5, end: 6 },
    { first: 5, last: 9, start: 8, end: 12 },
  ]

  it('is -1 before the first unit and the last unit after the end', () => {
    expect(unitAt(units, 1.9)).toBe(-1)
    expect(unitAt(units, 99)).toBe(2)
  })

  it('finds the unit whose time it is, on its first instant too, and holds one through the rest after it', () => {
    expect(unitAt(units, 2)).toBe(0)
    expect(unitAt(units, 4.4)).toBe(0)       // the rest between the first and second: still the first
    expect(unitAt(units, 4.5)).toBe(1)
    expect(unitAt(units, 7)).toBe(1)
    expect(unitAt(units, 8)).toBe(2)
  })

  it('is -1 with no units', () => {
    expect(unitAt([], 1)).toBe(-1)
  })
})
