import { describe, expect, it } from 'vitest'
import type { UsageRow } from '../api'
import { bySource, costCell, formatUsd, priceNote, sourceColor, sourceLabel, totals, usagePeriod, usageTable } from './usageData'

// A fixed "now" in the middle of a day, so a bug in day boundaries shows up.
const NOW = new Date(2026, 10, 20, 14, 30) // Fri 20 Nov 2026, 14:30 local
const at = (day: number, hour = 12, month = 10, minute = 0) => new Date(2026, month, day, hour, minute).toISOString()
const row = (over: Partial<UsageRow> = {}): UsageRow => ({
  at: at(20), source: 'chat', model: 'claude-opus-5-5', provider: 'anthropic', input_tokens: 1000, output_tokens: 200, cost_usd: 0.008, ...over,
})

describe('totals', () => {
  it('adds tokens and priced dollars, and counts what has no price apart', () => {
    const t = totals([row(), row({ input_tokens: 500, output_tokens: 100, cost_usd: 0.004 }), row({ model: 'mystery', cost_usd: null })])
    expect(t.calls).toBe(3)
    expect(t.input).toBe(2500)
    expect(t.output).toBe(500)
    expect(t.cost).toBeCloseTo(0.012, 6) // the unpriced call adds tokens but never a guessed price
    expect(t.unpriced).toBe(1)
  })

  it('is all zero for nothing', () => {
    expect(totals([])).toEqual({ calls: 0, input: 0, output: 0, cost: 0, unpriced: 0 })
  })
})

describe('the period', () => {
  it('keeps the last n local days and compares them with the n before', () => {
    const rows = [
      row({ at: at(20), cost_usd: 1 }), // today
      row({ at: at(14), cost_usd: 2 }), // first day of a 7-day period
      row({ at: at(13), cost_usd: 4 }), // last day of the period before
      row({ at: at(7), cost_usd: 8 }), // first day of the period before
      row({ at: at(6), cost_usd: 16 }), // older than both: in neither
      row({ at: new Date(2026, 10, 21, 0, 0, 1).toISOString(), cost_usd: 32 }), // tomorrow
    ]
    const p = usagePeriod(rows, 7, NOW)
    expect(p.current.cost).toBe(3)
    expect(p.before.cost).toBe(12)
    expect(p.rows).toHaveLength(2)
  })

  it('puts a late-evening call on its own local day, not the next', () => {
    const late = row({ at: at(19, 23, 10, 59), cost_usd: 5 })
    const p = usagePeriod([late], 3, NOW)
    expect(p.dailyCost).toEqual([0, 5, 0]) // 18th, 19th, 20th
  })

  it('has a zero for every day with nothing, so the line has the right shape', () => {
    const p = usagePeriod([row({ at: at(20), cost_usd: 2 })], 14, NOW)
    expect(p.dailyCost).toHaveLength(14)
    expect(p.dailyCost.slice(0, 13).every((n) => n === 0)).toBe(true)
    expect(p.dailyCost[13]).toBe(2)
  })

  it('crosses a month boundary', () => {
    const p = usagePeriod([row({ at: at(31, 12, 9), cost_usd: 3 }), row({ at: at(1, 12, 10), cost_usd: 1 })], 3, new Date(2026, 10, 2, 9))
    expect(p.dailyCost).toEqual([3, 1, 0]) // 31 Oct, 1 Nov, 2 Nov
  })

  it('counts calls and tokens per day for the table', () => {
    const p = usagePeriod([row({ at: at(20), input_tokens: 10 }), row({ at: at(20), input_tokens: 5 })], 2, NOW)
    expect(p.daily[1]).toMatchObject({ calls: 2, input: 15 })
    expect(p.daily[0]).toMatchObject({ calls: 0, input: 0 })
  })
})

describe('money', () => {
  it('never shows an amount under a cent as zero', () => {
    expect(formatUsd(0)).toBe('$0.00')
    expect(formatUsd(0.0004)).toBe('<$0.01')
    expect(formatUsd(0.01)).toBe('$0.01')
    expect(formatUsd(4.267)).toBe('$4.27')
    expect(formatUsd(99.994)).toBe('$99.99')
    expect(formatUsd(1234.4)).toBe('$1,234')
  })
})

describe('sources', () => {
  it('names where a row came from in the words the page already uses', () => {
    expect(sourceLabel('chat')).toBe('Chat')
    expect(sourceLabel('meet_ai__generate_notes')).toBe('Meeting notes')
    expect(sourceLabel('meet_ai__generate_minutes')).toBe('Meeting minutes')
    expect(sourceLabel('docu_ai__build')).toBe('Documents: build')
    expect(sourceLabel('unknown__thing')).toBe('unknown__thing')
  })

  it('gives each source its tool\'s fixed colour', () => {
    expect(sourceColor('chat')).toBe(sourceColor('assistant__remember'))
    expect(sourceColor('meet_ai__generate_notes')).toBe(sourceColor('meet_ai__generate_minutes'))
    expect(sourceColor('chat')).not.toBe(sourceColor('meet_ai__generate_notes'))
  })

  it('sorts by cost, with a source that has no price after the priced ones', () => {
    const shares = bySource([
      row({ source: 'chat', cost_usd: 0.5 }),
      row({ source: 'meet_ai__generate_notes', cost_usd: 2 }),
      row({ source: 'meet_ai__generate_minutes', cost_usd: null, input_tokens: 90_000 }),
    ])
    expect(shares.map((s) => s.label)).toEqual(['Meeting notes', 'Chat', 'Meeting minutes'])
    expect(shares[2]).toMatchObject({ unpriced: 1, calls: 1, cost: 0 })
  })
})

describe('the table view', () => {
  it('lists every day, oldest first, and says plainly when a day has no price or no calls', () => {
    const p = usagePeriod([row({ at: at(20), cost_usd: null }), row({ at: at(19), cost_usd: 0.0004 }), row({ at: at(19), cost_usd: null })], 3, NOW)
    const lines = usageTable(p.days, p.daily, NOW)
    expect(lines).toHaveLength(3)
    expect(lines[0]![1]).toBe(0)
    expect(lines[0]![4]).toBe('—') // the 18th: nothing happened
    expect(lines[1]![4]).toBe('<$0.01 (1 unpriced)') // the 19th: one priced call and one not
    expect(lines[2]![4]).toBe('No price') // today: every call on an unlisted model
    expect(String(lines[2]![0])).toMatch(/^Today, /)
  })
})

describe('the footnote', () => {
  it('always says it is an estimate, and adds only what is true of these rows', () => {
    const plain = priceNote([row()], '2026-11-03', 0)
    expect(plain).toMatch(/Estimated at Anthropic's list prices \(checked .*2026\), not a bill\./)
    expect(plain).toMatch(/Tokens out include the model's thinking\./)
    expect(plain).not.toMatch(/Bedrock/)
    expect(plain).not.toMatch(/no listed price/)
    const full = priceNote([row({ provider: 'bedrock' })], '2026-11-03', 2)
    expect(full).toMatch(/Amazon Bedrock/)
    expect(full).toMatch(/2 calls on a model with no listed price are in the token counts but not the cost/)
    expect(priceNote([row()], '2026-11-03', 1)).toMatch(/1 call on a model with no listed price is in/)
  })
})

describe('a cost cell', () => {
  it('says when some calls on the line are not in the dollars', () => {
    const t = { calls: 4, input: 0, output: 0, cost: 1.5, unpriced: 0 }
    expect(costCell(t)).toBe('$1.50')
    expect(costCell({ ...t, unpriced: 1 })).toBe('$1.50 (1 unpriced)')
    expect(costCell({ ...t, cost: 0, unpriced: 4 })).toBe('No price')
  })
})
