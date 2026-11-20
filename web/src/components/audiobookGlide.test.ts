import { describe, expect, it } from 'vitest'
import { ARRIVED, GLIDE_MS, glideBy } from './audiobookGlide'

/** Run a glide the way the view does, on a screen whose scrollTop is whole pixels, with a frame every `frameMs`.
 *  Returns how many frames it took and how many milliseconds, or null if it had not arrived after a minute. */
function glide(gap: number, frameMs: number) {
  let top = 0
  let ms = 0
  let frames = 0
  while (ms < 60_000) {
    const diff = gap - top
    if (Math.abs(diff) < ARRIVED) return { frames, ms }
    top = Math.round(top + glideBy(diff, frameMs)) // the browser keeps whole pixels
    ms += frameMs
    frames += 1
  }
  return null
}

describe('the text glides by the clock', () => {
  it('closes a fifth of the way in one 60 Hz frame, as it did when it was a fifth a frame', () => {
    expect(glideBy(1000, 1000 / 60) / 1000).toBeCloseTo(0.2, 2)
  })

  it('goes as far in two short steps as in one long one', () => {
    const one = glideBy(1000, 40)
    const first = glideBy(1000, 20)
    const second = glideBy(1000 - first, 20)
    expect(first + second).toBeCloseTo(one, 6)
  })

  it('goes the way of the gap, up or down', () => {
    expect(glideBy(500, 16)).toBeGreaterThan(0)
    expect(glideBy(-500, 16)).toBeLessThan(0)
  })

  it('catches up after a long frame instead of crawling', () => {
    expect(glideBy(1000, 1000)).toBeGreaterThan(999)
  })

  it('never takes a step the browser would round away', () => {
    expect(glideBy(3, 16)).toBe(1)
    expect(glideBy(-3, 16)).toBe(-1)
    expect(glideBy(1.5, 1)).toBe(1)
  })
})

describe('the glide ends', () => {
  // Every gap, on a whole-pixel screen, at 60 frames a second and at 5: it arrives, and by the clock not the frame.
  it.each([1, 2, 3, 7, 50, 333, 4000, 25_000])('arrives across %i px', (gap) => {
    const fast = glide(gap, 1000 / 60)
    const slow = glide(gap, 200)
    expect(fast).not.toBeNull()
    expect(slow).not.toBeNull()
    // 60 frames a second takes about as long as 5 a second, give or take the frame it ends on
    expect(slow!.ms).toBeLessThanOrEqual(fast!.ms + 400)
    expect(fast!.ms).toBeLessThan(GLIDE_MS * 14) // a 25,000 px jump is still there in about a second
  })
})
