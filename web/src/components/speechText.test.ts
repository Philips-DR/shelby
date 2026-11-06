import { describe, expect, it } from 'vitest'
import { pieces, speakable } from './speechText'

describe('speakable', () => {
  it('reads what a person would read, not the markup', () => {
    expect(speakable('## Your inbox\n\nYou have **three** emails from *the bank*.')).toBe('Your inbox. You have three emails from the bank.')
  })
  it('reads a link by its words and a bare address as a link', () => {
    expect(speakable('See [the statement](https://bank.example/s/1) or https://bank.example.')).toBe('See the statement or a link.')
  })
  it('turns a list into sentences', () => {
    expect(speakable('Three things:\n- update your number\n- sign the form\n1. call Ama')).toBe('Three things: update your number. sign the form. call Ama.')
  })
  it('says code and tables are on screen instead of reading them', () => {
    const reply = 'Run this:\n\n```bash\nrm -rf build\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\nDone.'
    expect(speakable(reply)).toBe('Run this: There is code on screen. There is a table on screen. Done.')
  })
  it('keeps the words of inline code and drops tags', () => {
    expect(speakable('Use `./start` then <b>wait</b>.')).toBe('Use ./start then wait.')
  })
  it('leaves snake_case and multiplication alone', () => {
    expect(speakable('Set max_tool_rounds to 3 * 10.')).toBe('Set max_tool_rounds to 3 * 10.')
  })
  it('says nothing for a reply of only a rule or blank lines', () => {
    expect(speakable('---\n\n')).toBe('')
  })
})

describe('pieces', () => {
  it('sends the first sentence alone, then one at a time', () => {
    const text = 'I found three emails from the bank this week. The first confirms your transfer on Monday. The second asks you to update your number.'
    expect(pieces(text)).toEqual([
      'I found three emails from the bank this week.',
      'The first confirms your transfer on Monday.',
      'The second asks you to update your number.',
    ])
  })
  it('joins a short sentence to the next, but never the first', () => {
    expect(pieces('Yes. It went through. Ama signed it on Friday, before the deadline.')).toEqual([
      'Yes.', 'It went through. Ama signed it on Friday, before the deadline.',
    ])
  })
  it('does not split after an abbreviation', () => {
    expect(pieces('Dr. Mensah called about it. She will call again tomorrow morning.')).toEqual([
      'Dr. Mensah called about it.', 'She will call again tomorrow morning.',
    ])
  })
  it('cuts a sentence too long for one call at a comma, never past the limit', () => {
    const long = `${'word '.repeat(30).trim()}, ${'more '.repeat(30).trim()}, ${'last '.repeat(30).trim()}.`
    const out = pieces(long, 200)
    expect(out.length).toBeGreaterThan(1)
    expect(out.every((p) => p.length <= 200)).toBe(true)
    expect(out.join(' ').replace(/\s+/g, ' ')).toBe(long)
  })
  it('gives nothing for nothing', () => {
    expect(pieces('')).toEqual([])
  })
})
