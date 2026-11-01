import { describe, expect, it } from 'vitest'
import { same, step } from './useLayer'

describe('step: what the history needs when a layer changes', () => {
  it('pushes an entry when something opens over a page that had nothing open', () => {
    expect(step('book.pdf', null, null)).toBe('push')
  })
  it('replaces the entry, not stacking another, when one thing is swapped for another', () => {
    expect(step('b.pdf', 'a.pdf', 'a.pdf')).toBe('replace')
  })
  it('goes Back when the page closes it itself, so a button and the phone\'s Back leave the same history', () => {
    expect(step(null, 'book.pdf', 'book.pdf')).toBe('back')
  })
  it('does nothing when Back already closed it: the entry is gone and the page only caught up', () => {
    expect(step(null, 'book.pdf', null)).toBe('none')
  })
  it('does nothing when the entry already says what the page shows', () => {
    expect(step('book.pdf', null, 'book.pdf')).toBe('none')
    expect(step(null, null, null)).toBe('none')
  })
  it('does not take an entry away on arriving at one that has the layer open (the page is about to open it)', () => {
    expect(step(null, null, 'book.pdf')).toBe('none')
  })
  it('compares what is held by value, as the browser copies it', () => {
    expect(step({ kind: 'thread', id: '7' }, { kind: 'thread', id: '7' }, { kind: 'thread', id: '7' })).toBe('none')
    expect(step({ kind: 'thread', id: '8' }, { kind: 'thread', id: '7' }, { kind: 'thread', id: '7' })).toBe('replace')
  })
})

describe('same', () => {
  it('treats nothing and undefined alike, and objects by what they hold', () => {
    expect(same(null, undefined)).toBe(true)
    expect(same({ a: 1 }, { a: 1 })).toBe(true)
    expect(same({ a: 1 }, { a: 2 })).toBe(false)
    expect(same('x', null)).toBe(false)
  })
})
