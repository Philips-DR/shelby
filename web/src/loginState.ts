// Which logins are out, in words a person reads. Pure: the sidebar, Settings and the tests share it.

import type { LoginState, Status } from './api'
import { toolName } from './charts/palette'

type ToolStatus = Status['tools'][number]

/**
 * The model as the sidebar and Settings tell it. `signed-out` is the AWS login lapsing (`./auth` fixes it); `key-refused` and
 * `model-missing` are an Anthropic API key's two ways to fail (a key is replaced in `.env`, so the fix is different);
 * `unreachable` is anything else (no setting fixes it); `not-set-up` is no model at all, which is information, not a fault,
 * because every page but Chat and meeting notes works without one. Null until a check has said anything.
 */
export type ModelLogin = 'ok' | 'signed-out' | 'key-refused' | 'model-missing' | 'unreachable' | 'not-set-up' | null

export function loginOf(model: Status['model']): ModelLogin {
  if (model.level === undefined) return null
  if (model.configured === false) return 'not-set-up'
  if (model.level === 'error') {
    if (model.key_refused) return 'key-refused'
    if (model.model_missing) return 'model-missing'
    return model.signed_out ? 'signed-out' : 'unreachable'
  }
  return 'ok'
}

/** The model has a fault a person can act on or should know of (not "no model set up", which they may have chosen). */
export const modelNeedsAttention = (login: ModelLogin): boolean =>
  login === 'signed-out' || login === 'key-refused' || login === 'model-missing' || login === 'unreachable'

/** Refused, or never signed in: both are fixed the same way. "Could not tell" is neither. */
export const isSignedOut = (state: LoginState | undefined): boolean => state === 'dead' || state === 'missing'

/** The tool's own name for the service ("Gmail"), else ours ("Mail"). */
export const serviceOf = (tool: ToolStatus): string => tool.login?.service || toolName(tool.name)

/** What is signed out, by name, model first: ["the model", "Gmail"]. */
export function signedOutNames(status: Status): string[] {
  const names: string[] = []
  if (loginOf(status.model) === 'signed-out') names.push('the model')
  for (const tool of status.tools) if (isSignedOut(tool.login?.state)) names.push(serviceOf(tool))
  return names
}

/** "a", "a and b", "a, b and c". */
export function joinNames(names: string[]): string {
  if (names.length <= 1) return names.join('')
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
}
