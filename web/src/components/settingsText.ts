// The words on the Settings page, apart from the page, so they can be tested. Everything here is plain: a state is
// said as a person would say it, and the tool's own wording ("mail-ai · sync") stays out of sight.

import type { Level, Status } from '../api'
import { toolName } from '../charts/palette'
import { isSignedOut, loginOf, serviceOf } from '../loginState'
import { humanise } from '../ui/toolMeta'

type Net = NonNullable<Status['network']>[number]

export const NET_WORDS: Record<Level, string> = { ok: 'Reachable', warning: 'Slow or partial', error: 'Unreachable' }

/** One short phrase per thing that needs a look, for the chips in the banner: what, then how it is. */
export function issueChips(status: Status): string[] {
  const chips: string[] = []
  const model = loginOf(status.model)
  if (model === 'signed-out') chips.push('Model: signed out')
  else if (model === 'key-refused') chips.push('Model: key refused')
  else if (model === 'model-missing') chips.push('Model: not available to this key')
  else if (model === 'unreachable') chips.push('Model: not reachable')
  else if (model !== 'not-set-up' && status.model.level === 'warning') chips.push('Model: check')
  for (const n of status.network ?? []) if (n.level !== 'ok') chips.push(`${n.name}: ${NET_WORDS[n.level].toLowerCase()}`)
  for (const t of status.tools) {
    if (isSignedOut(t.login?.state)) chips.push(`${serviceOf(t)}: signed out`)
    else if (t.level !== 'ok') chips.push(`${toolName(t.name)}: last action failed`)
  }
  return chips
}

/** True when no service answered over IPv6: said once, not once per service. A mixed result is a real finding and stays per row. */
export const ipv6Absent = (network: Net[]): boolean => network.length > 0 && network.every((n) => n.ipv6_ms == null)

/** How one service's connection is, as a word or two. */
export const netVerdict = (n: Net): string => (n.verdict === 'ok' ? NET_WORDS.ok : `${NET_WORDS[n.level]}: ${n.verdict}`)

/** The table view: the IPv6 column only when it says something. */
export function networkTable(network: Net[]): { head: string[]; rows: string[][] } {
  const v6 = !ipv6Absent(network)
  const answer = (ms: number | null, error: string) => (ms != null ? `${ms} ms` : `No answer${error ? `: ${error}` : ''}`)
  return {
    head: ['Service', 'IPv4', ...(v6 ? ['IPv6'] : []), 'Verdict'],
    rows: network.map((n) => [
      `${n.name} (${n.host})`,
      answer(n.ipv4_ms, n.ipv4_error),
      ...(v6 ? [answer(n.ipv6_ms, n.ipv6_error)] : []),
      netVerdict(n),
    ]),
  }
}

/** A tool's last action, as the tool itself titles it ("Bring the local mailbox level with Gmail"), else made readable. */
export function actionTitle(qualified: string, titles: Record<string, string>): string {
  return titles[qualified] || humanise((qualified.split('__')[1] ?? qualified).replace(/_/g, ' '))
}
