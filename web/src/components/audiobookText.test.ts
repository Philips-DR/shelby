import { describe, expect, it } from 'vitest'
import { renderLabel, unrendered } from './audiobookText'

const ch = (number: number, rendered: boolean) => ({ number, audio: rendered ? [{ path: `/a/${number}.mp3` }] : [] })

describe('unrendered', () => {
  it('ticks only the chapters with no audio: a finished chapter is not offered for rendering again', () => {
    // Dreams and Visions on 2026-10-31: everything but the foreword (2) and the introduction (3)
    const book = [ch(1, true), ch(2, false), ch(3, false), ...Array.from({ length: 16 }, (_, i) => ch(i + 4, true))]
    expect([...unrendered(book)]).toEqual([2, 3])
  })

  it('ticks every chapter of a book never rendered, and none of a finished one', () => {
    expect([...unrendered([ch(1, false), ch(2, false)])]).toEqual([1, 2])
    expect(unrendered([ch(1, true), ch(2, true)]).size).toBe(0)
    expect(unrendered([{ number: 1 }]).size).toBe(1) // no audio listed at all
  })
})

describe('renderLabel', () => {
  it('says what pressing it would do', () => {
    expect(renderLabel(2, 19, 17)).toBe('Render 2 chapters')
    expect(renderLabel(1, 19, 18)).toBe('Render 1 chapter')
    expect(renderLabel(19, 19, 0)).toBe('Render all chapters')
    expect(renderLabel(0, 19, 19)).toBe('Every chapter is rendered')
    expect(renderLabel(0, 19, 5)).toBe('Render') // nothing ticked: the button is off and says nothing more
  })
})
