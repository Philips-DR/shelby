import { describe, expect, it } from 'vitest'
import type { Status } from './api'
import { isSignedOut, joinNames, loginOf, modelNeedsAttention, signedOutNames } from './loginState'

const model = (extra: Partial<Status['model']> = {}): Status['model'] => ({ provider: 'bedrock', model: 'm', profile: null, region: null, ...extra })
const tool = (name: string, login: NonNullable<Status['tools'][number]['login']> | null = null): Status['tools'][number] =>
  ({ name, tools: 3, level: 'ok', last_call: null, login })
const status = (m: Status['model'], tools: Status['tools'] = []): Status => ({ model: m, tools, mail_compose: false })

describe('the model login, as the sidebar shows it', () => {
  it('knows nothing until a check has said something', () => {
    expect(loginOf(model())).toBeNull()
  })
  it('is ok when the check passed', () => {
    expect(loginOf(model({ level: 'ok' }))).toBe('ok')
  })
  it('tells an API key that was refused, a model the key cannot use, and no model at all, each its own thing', () => {
    expect(loginOf(model({ level: 'error', key_refused: true }))).toBe('key-refused')
    expect(loginOf(model({ level: 'error', model_missing: true }))).toBe('model-missing')
    expect(loginOf(model({ level: 'warning', configured: false }))).toBe('not-set-up')
  })
  it('does not count "no model set up" as a fault, because every page but Chat and meeting notes works without one', () => {
    expect(modelNeedsAttention('not-set-up')).toBe(false)
    expect(modelNeedsAttention('ok')).toBe(false)
    expect(modelNeedsAttention(null)).toBe(false)
    for (const fault of ['signed-out', 'key-refused', 'model-missing', 'unreachable'] as const) expect(modelNeedsAttention(fault)).toBe(true)
  })
  it('says signed out only when the login has expired, and unreachable for any other failure', () => {
    expect(loginOf(model({ level: 'error', signed_out: true }))).toBe('signed-out')
    expect(loginOf(model({ level: 'error', signed_out: false }))).toBe('unreachable')
    expect(loginOf(model({ level: 'error' }))).toBe('unreachable')
  })
})

describe('isSignedOut', () => {
  it('counts a refused login and one never signed in, and nothing that is merely unknown', () => {
    expect(isSignedOut('dead')).toBe(true)
    expect(isSignedOut('missing')).toBe(true)
    expect(isSignedOut('unknown')).toBe(false)
    expect(isSignedOut('ok')).toBe(false)
    expect(isSignedOut(undefined)).toBe(false)
  })
})

describe('what is signed out', () => {
  it('names the model first, then each service by the name its tool gave', () => {
    const s = status(model({ level: 'error', signed_out: true }), [
      tool('docu-ai', { state: 'dead', detail: '', service: 'Google Docs' }),
      tool('mail-ai', { state: 'ok', detail: '', service: 'Gmail' }),
    ])
    expect(signedOutNames(s)).toEqual(['the model', 'Google Docs'])
  })
  it('falls back to our own name for a tool that gave none, and ignores a login nobody could check', () => {
    const s = status(model({ level: 'ok' }), [tool('mail-ai', { state: 'missing', detail: '', service: '' }), tool('docu-ai', { state: 'unknown', detail: 'x', service: 'Google Docs' })])
    expect(signedOutNames(s)).toEqual(['Mail'])
  })
  it('leaves a refused API key out: ./auth would not fix it, a key is replaced in .env', () => {
    expect(signedOutNames(status(model({ level: 'error', key_refused: true })))).toEqual([])
  })
  it('is empty when nothing is out', () => {
    expect(signedOutNames(status(model({ level: 'ok' }), [tool('mail-ai')]))).toEqual([])
  })
})

describe('joinNames', () => {
  it('reads as a sentence', () => {
    expect(joinNames([])).toBe('')
    expect(joinNames(['Gmail'])).toBe('Gmail')
    expect(joinNames(['the model', 'Gmail'])).toBe('the model and Gmail')
    expect(joinNames(['the model', 'Gmail', 'Google Docs'])).toBe('the model, Gmail and Google Docs')
  })
})
