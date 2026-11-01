import { describe, expect, it } from 'vitest'
import type { Status } from '../api'
import { actionTitle, ipv6Absent, issueChips, netVerdict, networkTable } from './settingsText'

type Net = NonNullable<Status['network']>[number]
const net = (over: Partial<Net> = {}): Net => ({
  name: 'Google', host: 'oauth2.googleapis.com', ipv4_ms: 90, ipv4_error: '', ipv6_ms: null, ipv6_error: 'no address', verdict: 'ok', level: 'ok', ...over,
})
const status = (over: Partial<Status> = {}): Status => ({
  model: { provider: 'bedrock', model: 'm', profile: null, region: null, level: 'ok' }, tools: [], mail_compose: false, ...over,
})

describe('the chips in the banner', () => {
  it('say what and how, in words, one per thing that needs a look', () => {
    const s = status({
      model: { provider: 'bedrock', model: 'm', profile: null, region: null, level: 'error', signed_out: true },
      network: [net({ level: 'error', verdict: 'unreachable' })],
      tools: [
        { name: 'mail-ai', tools: 9, level: 'error', last_call: null, login: { state: 'dead', detail: 'invalid_grant', service: 'Gmail' } },
        { name: 'meet-ai', tools: 9, level: 'warning', last_call: null },
        { name: 'docu-ai', tools: 9, level: 'ok', last_call: null },
      ],
    })
    expect(issueChips(s)).toEqual(['Model: signed out', 'Google: unreachable', 'Gmail: signed out', 'Meetings: last action failed'])
  })
  it('are empty when nothing needs a look', () => {
    expect(issueChips(status({ network: [net()] }))).toEqual([])
  })
  it('say what is wrong with an API key in its own words, and say nothing about having no model', () => {
    const m = (extra: Partial<Status['model']>): Status['model'] => ({ provider: 'anthropic', model: 'x', profile: null, region: null, ...extra })
    expect(issueChips(status({ model: m({ level: 'error', key_refused: true }) }))).toEqual(['Model: key refused'])
    expect(issueChips(status({ model: m({ level: 'error', model_missing: true }) }))).toEqual(['Model: not available to this key'])
    // no model set up is information: the pages that do not need one all work
    expect(issueChips(status({ model: m({ level: 'warning', configured: false }) }))).toEqual([])
  })
  it('tell a model that is out of reach from one that is signed out', () => {
    expect(issueChips(status({ model: { provider: 'b', model: 'm', profile: null, region: null, level: 'error' } }))).toEqual(['Model: not reachable'])
  })
})

describe('IPv6, said once', () => {
  it('is absent only when no service answered over it', () => {
    expect(ipv6Absent([net(), net({ name: 'AWS Bedrock' })])).toBe(true)
    expect(ipv6Absent([net(), net({ ipv6_ms: 40, ipv6_error: '' })])).toBe(false)
    expect(ipv6Absent([])).toBe(false)
  })
  it('drops the IPv6 column from the table when it would only repeat "no answer"', () => {
    const t = networkTable([net(), net({ name: 'AWS Bedrock', host: 'b.example.org', ipv4_ms: 140 })])
    expect(t.head).toEqual(['Service', 'IPv4', 'Verdict'])
    expect(t.rows).toEqual([['Google (oauth2.googleapis.com)', '90 ms', 'Reachable'], ['AWS Bedrock (b.example.org)', '140 ms', 'Reachable']])
  })
  it('keeps the column, per row, when only some services answered over IPv6', () => {
    const t = networkTable([net(), net({ name: 'AWS Bedrock', ipv6_ms: 40, ipv6_error: '' })])
    expect(t.head).toEqual(['Service', 'IPv4', 'IPv6', 'Verdict'])
    expect(t.rows[0]![2]).toBe('No answer: no address')
    expect(t.rows[1]![2]).toBe('40 ms')
  })
})

describe('a service\'s verdict', () => {
  it('is a word, with the reason when it is not fine', () => {
    expect(netVerdict(net())).toBe('Reachable')
    expect(netVerdict(net({ level: 'warning', verdict: 'slow, IPv4 only' }))).toBe('Slow or partial: slow, IPv4 only')
  })
})

describe('a last action', () => {
  it('uses the title the tool gave it', () => {
    expect(actionTitle('mail_ai__sync', { mail_ai__sync: 'Bring the local mailbox level with Gmail' })).toBe('Bring the local mailbox level with Gmail')
  })
  it('is made readable when the tool gave none', () => {
    expect(actionTitle('meet_ai__generate_notes', {})).toBe('Generate notes')
  })
})
