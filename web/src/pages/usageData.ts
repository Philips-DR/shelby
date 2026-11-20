// What the Overview shows of the model's token use and price, worked out from the rows the backend counted.
// Pure functions over plain rows, so the date arithmetic and the money formatting are tested. The price on a
// row is the backend's estimate (usage.py is the one place prices live); nothing here knows a price.

import type { UsageRow } from '../api'
import { toolColor, toolName, toolOf } from '../charts/palette'
import { compact } from '../charts/scale'
import { dayKey, lastDays } from './overviewData'

export interface Totals {
  calls: number
  input: number
  output: number
  /** Dollars, from the rows that have a price. */
  cost: number
  /** Rows with no price (a model not on the list): counted in tokens and calls, left out of `cost`. */
  unpriced: number
}

const none = (): Totals => ({ calls: 0, input: 0, output: 0, cost: 0, unpriced: 0 })

function add(t: Totals, r: UsageRow): void {
  t.calls += 1
  t.input += r.input_tokens
  t.output += r.output_tokens
  if (r.cost_usd === null) t.unpriced += 1
  else t.cost += r.cost_usd
}

export function totals(rows: UsageRow[]): Totals {
  const t = none()
  for (const r of rows) add(t, r)
  return t
}

export interface UsagePeriod {
  days: Date[]
  rows: UsageRow[]
  current: Totals
  before: Totals
  /** Dollars per local day, oldest first, one entry for every day of the period. */
  dailyCost: number[]
  /** One entry per local day, in the same order. */
  daily: Totals[]
}

/** The last `n` local days, and the `n` before them to compare against. */
export function usagePeriod(all: UsageRow[], n: number, now: Date = new Date()): UsagePeriod {
  const days = lastDays(n, now)
  const start = days[0]!
  const last = days[n - 1]!
  const end = new Date(last.getFullYear(), last.getMonth(), last.getDate() + 1)
  const prevStart = new Date(start.getFullYear(), start.getMonth(), start.getDate() - n)
  const between = (from: Date, to: Date) =>
    all.filter((r) => {
      const t = new Date(r.at).getTime()
      return t >= from.getTime() && t < to.getTime()
    })
  const rows = between(start, end)
  const byDay = new Map<string, Totals>()
  for (const r of rows) {
    const k = dayKey(new Date(r.at))
    const cell = byDay.get(k) ?? none()
    add(cell, r)
    byDay.set(k, cell)
  }
  const daily = days.map((d) => byDay.get(dayKey(d)) ?? none())
  return {
    days,
    rows,
    current: totals(rows),
    before: totals(between(prevStart, start)),
    dailyCost: daily.map((t) => t.cost),
    daily,
  }
}

/** Dollars as a person reads them: $0.00, <$0.01, $4.27, $1,234. A figure under a cent is never shown as zero. */
export function formatUsd(n: number): string {
  if (n <= 0) return '$0.00'
  if (n < 0.01) return '<$0.01'
  if (n < 100) return `$${n.toFixed(2)}`
  return `$${Math.round(n).toLocaleString()}`
}

/** Where a row came from, in the words the rest of the page uses. */
export function sourceLabel(source: string): string {
  if (source === 'chat') return 'Chat'
  if (source === 'meet_ai__generate_notes') return 'Meeting notes'
  if (source === 'meet_ai__generate_minutes') return 'Meeting minutes'
  const tool = toolOf(source)
  const name = toolName(tool)
  return name === tool ? source : `${name}: ${source.split('__')[1] ?? source}`
}

/** A source's colour is its tool's fixed colour: chat is the assistant's, meetings are meet-ai's. */
export const sourceColor = (source: string): string => toolColor(source === 'chat' ? 'assistant' : toolOf(source))

export interface SourceShare extends Totals {
  key: string
  label: string
  color: string
}

/** Cost and tokens by source, most expensive first (a source with no price sorts by its tokens, after the priced ones). */
export function bySource(rows: UsageRow[]): SourceShare[] {
  const groups = new Map<string, Totals>()
  for (const r of rows) {
    const cell = groups.get(r.source) ?? none()
    add(cell, r)
    groups.set(r.source, cell)
  }
  return [...groups.entries()]
    .map(([key, t]) => ({ ...t, key, label: sourceLabel(key), color: sourceColor(key) }))
    .sort((a, b) => b.cost - a.cost || b.input + b.output - (a.input + a.output))
}

/** A cost for a table cell: the dollars, saying so when some calls on the line have no price and so are not in them. */
export function costCell(t: Totals): string {
  if (t.unpriced === t.calls) return 'No price'
  return t.unpriced > 0 ? `${formatUsd(t.cost)} (${t.unpriced} unpriced)` : formatUsd(t.cost)
}

const fullDay = new Intl.DateTimeFormat(undefined, { weekday: 'short', day: 'numeric', month: 'short' })

/** The table view: one line for every day of the period, oldest first. */
export function usageTable(days: Date[], daily: Totals[], now: Date = new Date()): (string | number)[][] {
  const today = dayKey(now)
  return days.map((d, i) => {
    const t = daily[i] ?? none()
    return [
      dayKey(d) === today ? `Today, ${fullDay.format(d)}` : fullDay.format(d),
      t.calls,
      t.input.toLocaleString(),
      t.output.toLocaleString(),
      t.calls === 0 ? '—' : costCell(t),
    ]
  })
}

export const tokens = (n: number): string => compact(n)

const asOf = new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'long', year: 'numeric' })

/** The honest footnote under any price: what it is, what it is not, and anything left out of it. */
export function priceNote(rows: UsageRow[], pricesAsOf: string, unpriced: number): string {
  const parts = [`Estimated at Anthropic's list prices (checked ${asOf.format(new Date(`${pricesAsOf}T12:00:00`))}), not a bill. Tokens out include the model's thinking.`]
  if (rows.some((r) => r.provider === 'bedrock')) parts.push('Calls through Amazon Bedrock are billed by Bedrock, which may price a model differently.')
  if (unpriced > 0) parts.push(`${unpriced} ${unpriced === 1 ? 'call' : 'calls'} on a model with no listed price ${unpriced === 1 ? 'is' : 'are'} in the token counts but not the cost.`)
  return parts.join(' ')
}
