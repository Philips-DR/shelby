import { describe, expect, it } from 'vitest'
import { modelName } from './modelName'

describe('the model, as the sidebar names it', () => {
  it('reads a Bedrock profile id and a first-party id alike', () => {
    expect(modelName('us.anthropic.claude-opus-4-6-v1')).toBe('Opus 4.6')
    expect(modelName('claude-opus-5-5')).toBe('Opus 5.5')
    expect(modelName('claude-sonnet-5-5')).toBe('Sonnet 5.5')
  })
  it('has no ".undefined" for an id with no minor version', () => {
    expect(modelName('claude-opus-5')).toBe('Opus 5')
  })
  it('does not take a date for a minor version', () => {
    expect(modelName('claude-opus-4-20250514')).toBe('Opus 4')
  })
  it('falls back to the id, or to "Assistant" when there is none', () => {
    expect(modelName('some-other-model')).toBe('some-other-model')
    expect(modelName('')).toBe('Assistant')
  })
})
