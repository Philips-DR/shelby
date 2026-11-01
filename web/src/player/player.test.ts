import { afterEach, describe, expect, it, vi } from 'vitest'
import { clock, spoken } from './format'
import { adjacent, continuesFrom } from './queue'
import { numeric, store } from './storage'
import { peaksOf } from './waveform'

describe('clock', () => {
  it('reads as minutes and seconds, then hours', () => {
    expect(clock(0)).toBe('0:00')
    expect(clock(5)).toBe('0:05')
    expect(clock(75)).toBe('1:15')
    expect(clock(3599)).toBe('59:59')
    expect(clock(3725)).toBe('1:02:05')
    expect(clock(14798)).toBe('4:06:38')
  })
  it('never prints nonsense for a length that is not known yet', () => {
    expect(clock(NaN)).toBe('0:00')
    expect(clock(Infinity)).toBe('0:00')
    expect(clock(-3)).toBe('0:00')
  })
  it('drops the fraction rather than rounding up past a boundary', () => {
    expect(clock(59.99)).toBe('0:59')
  })
})

describe('spoken', () => {
  it('says the units and gets the plurals right', () => {
    expect(spoken(0)).toBe('0 seconds')
    expect(spoken(1)).toBe('1 second')
    expect(spoken(75)).toBe('1 minute 15 seconds')
    expect(spoken(3600)).toBe('1 hour')
    expect(spoken(3725)).toBe('1 hour 2 minutes 5 seconds')
  })
  it('copes with a length that is not a number', () => {
    expect(spoken(NaN)).toBe('0 seconds')
  })
})

describe('peaksOf', () => {
  it('scales the loudest slice to 1 and keeps quieter ones below it, in order', () => {
    const data = new Float32Array([0.1, -0.1, 0.5, -0.5, 0.25, 0.25, 0, 0])
    const peaks = peaksOf(data, 4)
    expect(peaks).toHaveLength(4)
    expect(peaks[1]).toBeCloseTo(1)
    expect(peaks[0]!).toBeLessThan(peaks[2]!)
    expect(peaks[2]!).toBeLessThan(peaks[1]!)
    expect(peaks[3]).toBe(0)
  })
  it('measures the size of a swing, not its direction', () => {
    expect(Array.from(peaksOf(new Float32Array([-1, -1, 1, 1]), 2))).toEqual([1, 1])
  })
  it('gives silence and an empty signal a flat line, not NaN', () => {
    expect(Array.from(peaksOf(new Float32Array(100), 5))).toEqual([0, 0, 0, 0, 0])
    expect(Array.from(peaksOf(new Float32Array(0), 3))).toEqual([0, 0, 0])
  })
  it('still yields every bucket when there are fewer samples than buckets', () => {
    const peaks = peaksOf(new Float32Array([0.5, 1]), 6)
    expect(peaks).toHaveLength(6)
    expect(peaks.every((p) => Number.isFinite(p))).toBe(true)
  })
})

describe('what the player remembers', () => {
  afterEach(() => { vi.unstubAllGlobals() })

  it('round-trips a number and falls back when there is nothing', () => {
    const memory = new Map<string, string>()
    vi.stubGlobal('localStorage', {
      getItem: (k: string) => memory.get(k) ?? null,
      setItem: (k: string, v: string) => { memory.set(k, v) },
      removeItem: (k: string) => { memory.delete(k) },
    })
    expect(numeric('rate', 1)).toBe(1)
    store.write('rate', '1.5')
    expect(numeric('rate', 1)).toBe(1.5)
    store.write('rate', 'fast')
    expect(numeric('rate', 1)).toBe(1) // garbage is not a speed
    store.write('rate', null)
    expect(store.read('rate')).toBeNull()
  })

  it('never throws when storage is blocked', () => {
    const blocked = () => { throw new Error('blocked') }
    vi.stubGlobal('localStorage', { getItem: blocked, setItem: blocked, removeItem: blocked })
    expect(store.read('x')).toBeNull()
    expect(() => store.write('x', '1')).not.toThrow()
    expect(() => store.write('x', null)).not.toThrow()
    expect(numeric('x', 7)).toBe(7)
  })
})

describe('adjacent', () => {
  const ch = (number: number, rendered = true) => ({ number, label: `Chapter ${number}`, audio: rendered ? [{ path: `/a/${number}.mp3` }] : [] })

  it('goes to the next and the previous chapter that has audio, passing over any that has none', () => {
    // a book whose foreword (2) and introduction (3) were never rendered
    const book = [ch(1), ch(2, false), ch(3, false), ch(4), ch(5)]
    expect(adjacent(book, 1, 1)?.number).toBe(4)
    expect(adjacent(book, 4, -1)?.number).toBe(1)
    expect(adjacent(book, 4, 1)?.number).toBe(5)
  })

  it('has nothing past either end, nor for a chapter it does not know', () => {
    const book = [ch(1), ch(2), ch(3, false)]
    expect(adjacent(book, 2, 1)).toBeNull() // the last one with audio
    expect(adjacent(book, 1, -1)).toBeNull()
    expect(adjacent(book, 9, 1)).toBeNull()
  })

  it('follows the chapter numbers, not the order the list arrived in', () => {
    // chapter 1 arrives last: read in that order it would have nothing after it
    expect(adjacent([ch(2), ch(3), ch(1)], 1, 1)?.number).toBe(2)
    expect(adjacent([ch(2), ch(3), ch(1)], 3, -1)?.number).toBe(2)
  })
})

describe('continuesFrom', () => {
  it('plays on by default, and stops only when told to', () => {
    expect(continuesFrom(null)).toBe(true)
    expect(continuesFrom('1')).toBe(true)
    expect(continuesFrom('0')).toBe(false)
  })
})
