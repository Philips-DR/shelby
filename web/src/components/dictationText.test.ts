import { describe, expect, it } from 'vitest'
import { clock, micProblem, withDictated } from './dictationText'

describe('withDictated', () => {
  it('fills an empty box', () => {
    expect(withDictated('', ' Draft a reply to Ama. ')).toBe('Draft a reply to Ama.')
    expect(withDictated('   ', 'Hello')).toBe('Hello')
  })
  it('adds to what is there with one space', () => {
    expect(withDictated('Tell Kwame', 'the budget is fine.')).toBe('Tell Kwame the budget is fine.')
    expect(withDictated('Tell Kwame ', 'the budget is fine.')).toBe('Tell Kwame the budget is fine.')
    expect(withDictated('Line one\n', 'line two')).toBe('Line one\nline two')
  })
  it('leaves the box alone when nothing was said', () => {
    expect(withDictated('Tell Kwame', '  ')).toBe('Tell Kwame')
  })
})

describe('micProblem', () => {
  it('says what to do about a blocked microphone', () => {
    expect(micProblem(new DOMException('denied', 'NotAllowedError'))).toMatch(/blocked for this page/)
    expect(micProblem(new DOMException('none', 'NotFoundError'))).toBe('No microphone was found.')
    expect(micProblem(new DOMException('busy', 'NotReadableError'))).toMatch(/in use/)
  })
  it('passes anything else through', () => {
    expect(micProblem(new Error('odd'))).toBe('odd')
  })
})

describe('clock', () => {
  it('reads as minutes and seconds', () => {
    expect(clock(0)).toBe('0:00')
    expect(clock(7.9)).toBe('0:07')
    expect(clock(105)).toBe('1:45')
  })
})
