// Is everything working? Shows, never acts: fixing a login means a terminal and a browser,
// and the page says which command. Each thing is checked at the level that owns it -- the
// model login and the network here, a tool's health from how its own calls have gone.
//
// A banner says the verdict first; the model, the network and each tool follow as cards, so the
// thing that needs attention is found by its state (icon and word), not by reading.

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { getHistory, getMe, getStatus, signOut, type AuditRow, type AuthInfo, type Level, type Status } from '../api'
import { DataTable } from '../charts/ChartCard'
import { isTool, toolColor, toolName } from '../charts/palette'
import { Sparkline } from '../charts/Sparkline'
import { isSignedOut, joinNames, loginOf, serviceOf, signedOutNames } from '../loginState'
import { dayKey, lastDays } from '../pages/overviewData'
import { useAppState } from '../state'
import { CardHead } from '../ui/CardHead'
import { Empty } from '../ui/Empty'
import { IconAlert, IconChart, IconCheck, IconClock, IconCopy, IconFail, IconOk, IconRefresh, IconSend, IconSettings, IconSpark, IconSystem, IconTable } from '../ui/icons'
import { ago } from '../ui/time'
import { TOOL_ICON } from '../ui/toolMeta'
import { NET_WORDS, actionTitle, ipv6Absent, issueChips, networkTable } from './settingsText'
import '../styles/panels/settings.css'

type ToolStatus = Status['tools'][number]
type Net = NonNullable<Status['network']>[number]

const USAGE_DAYS = 14
const USAGE_LIMIT = 2000

const stamp = (when: string | number | Date) => new Date(when).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' })

/** The same two-step as the badges on Overview: a state is an icon and a word, never a colour alone. */
function Health({ level, words }: { level: Level | undefined; words: Record<Level, string> }) {
  if (level === 'ok') return <span className="badge ok"><IconOk size={14} aria-hidden />{words.ok}</span>
  if (level === 'warning') return <span className="badge warn"><IconAlert size={14} aria-hidden />{words.warning}</span>
  if (level === 'error') return <span className="badge bad"><IconFail size={14} aria-hidden />{words.error}</span>
  return <span className="badge"><IconClock size={14} aria-hidden />Not checked</span>
}

const TOOL_WORDS: Record<Level, string> = { ok: 'Healthy', warning: 'Check', error: 'Needs attention' }
const SIGNED_OUT_WORDS: Record<Level, string> = { ...TOOL_WORDS, error: 'Signed out' }
const MODEL_WORDS: Record<Level, string> = { ok: 'Signed in', warning: 'Check', error: 'Not reachable' }

function Outcome({ outcome }: { outcome: string }) {
  if (outcome === 'ok') return <span className="badge ok"><IconOk size={14} aria-hidden />Succeeded</span>
  if (outcome === 'failed') return <span className="badge bad"><IconFail size={14} aria-hidden />Failed</span>
  if (outcome === 'declined') return <span className="badge warn"><IconAlert size={14} aria-hidden />Declined</span>
  return <span className="badge">{outcome}</span>
}

// ---- copying a command ---------------------------------------------------------------------------

/** A page served over plain http (a tailnet address) has no clipboard API; this still works there. */
function legacyCopy(text: string): boolean {
  try {
    const box = document.createElement('textarea')
    box.value = text
    box.setAttribute('readonly', '')
    box.style.position = 'fixed'
    box.style.opacity = '0'
    document.body.appendChild(box)
    box.select()
    const ok = document.execCommand('copy')
    box.remove()
    return ok
  } catch {
    return false
  }
}

function CopyButton({ text, label = 'Copy' }: { text: string; label?: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle')
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(timer.current), [])

  const settle = (next: 'copied' | 'failed') => {
    setState(next)
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setState('idle'), 2600)
  }
  const copy = () => {
    if (!navigator.clipboard?.writeText) return settle(legacyCopy(text) ? 'copied' : 'failed')
    navigator.clipboard.writeText(text).then(
      () => settle('copied'),
      () => settle(legacyCopy(text) ? 'copied' : 'failed'),
    )
  }

  return (
    <span className="set-copy">
      <button onClick={copy} aria-label={`${label}: ${text}`}>
        {state === 'copied' ? <IconCheck size={16} aria-hidden /> : <IconCopy size={16} aria-hidden />}
        {state === 'copied' ? 'Copied' : label}
      </button>
      <span className="small muted" role="status">{state === 'failed' ? 'Could not copy. Select the command and copy it by hand.' : ''}</span>
    </span>
  )
}

/** The raw error, folded away: it is for someone reporting a problem, not for the person reading the page. */
function Details({ text }: { text: string | undefined }) {
  if (!text) return null
  return (
    <details className="set-fold">
      <summary>Technical detail</summary>
      <p className="small mono">{text}</p>
    </details>
  )
}

// ---- the verdict -----------------------------------------------------------------------------------

/** The one fix for every login that is out, where it cannot be missed: the same command whichever login it is. */
function SignInAgain({ names }: { names: string[] }) {
  return (
    <div className="set-fix" role="group" aria-label="How to sign in again">
      <p><b>Signed out of {joinNames(names)}.</b> Run this in the suite folder. It opens a browser for each login that needs it and leaves the others alone.</p>
      <div className="set-fix-run">
        <code>./auth</code>
        <CopyButton text="./auth" />
      </div>
      <p className="muted small">Then press Check now.</p>
    </div>
  )
}

/** An API key is replaced in `.env`, not renewed by a browser, so its fix is its own: what to change, then the one command. */
function ModelFix({ model }: { model: Status['model'] }) {
  const kind = loginOf(model)
  if (kind !== 'key-refused' && kind !== 'model-missing') return null
  return (
    <div className="set-fix" role="group" aria-label="How to fix the model">
      {kind === 'key-refused' ? (
        <p><b>The Anthropic API key was refused.</b> Put a working key in <code>.env</code> as <code>ANTHROPIC_API_KEY=…</code>, then run this in the suite folder:</p>
      ) : (
        <p>
          <b>This API key cannot use the model {model.model}.</b> {model.available?.length ? <>It can use {joinNames(model.available)}. </> : ''}
          Set <code>SUITE_MODEL=…</code> in <code>.env</code> to one it can, then run this in the suite folder:
        </p>
      )}
      <div className="set-fix-run">
        <code>./start-docker up</code>
        <CopyButton text="./start-docker up" />
      </div>
      <p className="muted small">Then press Check now.</p>
    </div>
  )
}

function Verdict({ status, checking, checkedAt, error, onCheck }: {
  status: Status
  checking: boolean
  checkedAt: number | null
  error: string
  onCheck: () => void
}) {
  const issues = issueChips(status)
  const signedOut = signedOutNames(status)
  const noModel = loginOf(status.model) === 'not-set-up'

  const settled = status.model.level !== undefined || status.network !== undefined
  // The instant view and the live check run back to back: until one has answered, say so rather than "not checked".
  const waiting = !settled && !error && (checking || checkedAt === null)
  const state = waiting ? 'busy' : issues.length > 0 ? 'bad' : settled ? 'ok' : 'idle'
  const headline = {
    busy: 'Checking every connection…',
    bad: `${issues.length} thing${issues.length === 1 ? '' : 's'} need${issues.length === 1 ? 's' : ''} attention`,
    ok: 'Everything is working',
    idle: 'Not checked yet',
  }[state]
  const Mark = state === 'bad' ? IconAlert : state === 'ok' ? IconOk : state === 'busy' ? IconRefresh : IconClock

  return (
    <section className={`card set-verdict is-${state}`} aria-busy={checking} aria-label="Overall health">
      <span className="set-verdict-mark">
        <Mark size={22} strokeWidth={2.2} aria-hidden className={state === 'busy' ? 'set-spin' : undefined} />
      </span>
      <div className="set-verdict-text">
        <h2>{headline}</h2>
        {issues.length > 0 ? (
          <ul className="set-issues" aria-label="Needs attention">
            {issues.map((chip) => <li key={chip} className="badge bad"><IconAlert size={14} aria-hidden />{chip}</li>)}
          </ul>
        ) : (
          <p className="muted small">
            {state === 'ok'
              ? `Every login, the network and every tool answered.${noModel ? ' No model is set up, so Chat and meeting notes are off; everything else works.' : ''}`
              : 'Press Check now to test every login and the network.'}
          </p>
        )}
        {signedOut.length > 0 && <SignInAgain names={signedOut} />}
        <ModelFix model={status.model} />
        {error && <p className="error small" role="alert">{error}</p>}
      </div>
      <div className="set-verdict-side">
        <button className="primary" disabled={checking} onClick={onCheck}>
          <IconRefresh size={16} aria-hidden className={checking ? 'set-spin' : undefined} />
          {checking ? 'Checking…' : 'Check now'}
        </button>
        <span className="muted small set-checked">
          {checkedAt === null
            ? 'Not checked yet'
            : <>Last checked <time dateTime={new Date(checkedAt).toISOString()}>{new Date(checkedAt).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' })}</time>, {ago(checkedAt)}</>}
        </span>
      </div>
    </section>
  )
}

// ---- the model ------------------------------------------------------------------------------------

function ModelCard({ model, checking }: { model: Status['model']; checking: boolean }) {
  const kind = loginOf(model)
  const words: Record<Level, string> =
    kind === 'signed-out' ? SIGNED_OUT_WORDS
      : kind === 'key-refused' ? { ...MODEL_WORDS, error: 'Key refused' }
        : kind === 'model-missing' ? { ...MODEL_WORDS, error: 'Model unavailable' }
          : MODEL_WORDS
  return (
    <section className="card set-model">
      <CardHead icon={IconSpark} tool="assistant" title="Model" sub="What the assistant thinks with. Only Chat and meeting notes need it.">
        {kind === 'not-set-up'
          ? <span className="badge"><IconClock size={14} aria-hidden />Not set up</span>
          : <Health level={model.level} words={words} />}
      </CardHead>

      <dl className="set-facts">
        <div><dt>Model</dt><dd className="mono">{model.model}</dd></div>
        <div><dt>Provider</dt><dd>{model.provider}</dd></div>
        {model.profile && <div><dt>Profile</dt><dd className="mono">{model.profile}</dd></div>}
        {model.region && <div><dt>Region</dt><dd className="mono">{model.region}</dd></div>}
      </dl>

      {model.level === 'ok' && (
        <p className="set-note ok">
          <IconOk size={16} aria-hidden />
          <span>{model.account ? `Signed in to account ${model.account}${model.role ? ` as ${model.role}` : ''}.` : (model.detail ?? 'Working.')}</span>
        </p>
      )}
      {kind === 'not-set-up' && (
        <p className="set-note">
          <IconClock size={16} aria-hidden />
          <span>
            <b>No model is set up.</b> Chat and meeting notes need one; every other page works without. To add one, put <code>ANTHROPIC_API_KEY=…</code> in <code>.env</code> and run <code>./start-docker up</code>.
          </span>
        </p>
      )}
      {model.level === 'error' && (
        <div className="set-note bad">
          <IconFail size={16} aria-hidden />
          <div>
            {kind === 'signed-out'
              ? <p><b>Signed out.</b> The model’s login has expired, so the assistant cannot answer until you sign in again. The fix is at the top of this page.</p>
              : kind === 'key-refused'
                ? <p><b>Key refused.</b> Anthropic did not accept the API key, so the assistant cannot answer until it is replaced. The fix is at the top of this page.</p>
                : kind === 'model-missing'
                  ? <p><b>Model not available.</b> This key cannot use {model.model}. The fix is at the top of this page.</p>
                  : <p><b>Cannot reach the model.</b> Check the network connection, then press Check now.</p>}
            <Details text={model.detail} />
          </div>
        </div>
      )}
      {!model.level && (
        <p className="set-note"><IconClock size={16} aria-hidden /><span>{checking ? 'Checking the login…' : 'Not checked yet.'}</span></p>
      )}
    </section>
  )
}

// ---- the network ---------------------------------------------------------------------------------

function Pair({ label, ms, error, color, top }: { label: string; ms: number | null; error: string; color: string; top: number }) {
  if (ms == null) {
    return (
      <div className="set-pair">
        <span className="set-pair-label">{label}</span>
        <span className="set-noanswer">No answer{error ? `: ${error}` : ''}</span>
      </div>
    )
  }
  const pct = Math.max(1.5, (ms / top) * 100)
  return (
    <div className="set-pair">
      <span className="set-pair-label">{label}</span>
      <span className="hbar-plot" role="img" aria-label={`${label}: ${ms} milliseconds`}>
        <span className="hbar-fill" style={{ width: `${pct}%`, background: color }} />
        <span className="hbar-value" style={{ left: `calc(${pct}% + 8px)` }}>{ms} ms</span>
      </span>
    </div>
  )
}

function NetworkCard({ network, checking }: { network: Net[] | undefined; checking: boolean }) {
  const [view, setView] = useState<'chart' | 'table'>('chart')
  const top = useMemo(() => {
    const values = (network ?? []).flatMap((n) => [n.ipv4_ms, n.ipv6_ms]).filter((v): v is number => v != null)
    return Math.max(1, ...values) * 1.18 // room for the value at the end of the longest bar
  }, [network])
  // No service answered over IPv6: say so once, and draw only what answered, rather than a "no answer" line per service.
  const noV6 = !!network && ipv6Absent(network)

  const table = networkTable(network ?? [])

  return (
    <section className="card set-network">
      <CardHead icon={IconSystem} title="Network" sub="How long a connection takes to open, in milliseconds.">
        {network && network.length > 0 && (
          <button className="ghost" onClick={() => setView(view === 'chart' ? 'table' : 'chart')} aria-pressed={view === 'table'}>
            {view === 'chart' ? <IconTable size={16} aria-hidden /> : <IconChart size={16} aria-hidden />}
            {view === 'chart' ? 'Table' : 'Chart'}
          </button>
        )}
      </CardHead>

      {!network && (
        <p className="set-note"><IconClock size={16} aria-hidden /><span>{checking ? 'Testing connections…' : 'Not checked yet.'}</span></p>
      )}
      {network && network.length === 0 && <p className="muted">No services are being tested.</p>}
      {network && network.length > 0 && view === 'table' && (
        // Focusable, so a keyboard can scroll it when a narrow window makes it wider than the card.
        <div className="table-wrap" tabIndex={0} role="region" aria-label="Connection times, as a table">
          <DataTable head={table.head} rows={table.rows} />
        </div>
      )}
      {network && network.length > 0 && view === 'chart' && (
        <div className="set-net">
          <ul className="set-legend" aria-label="Legend">
            <li><i className="swatch" style={{ background: 'var(--seq-strong)' }} aria-hidden />IPv4</li>
            {!noV6 && <li><i className="swatch" style={{ background: 'var(--seq-soft)' }} aria-hidden />IPv6</li>}
            <li className="muted">Shorter is faster</li>
          </ul>
          {noV6 && <p className="small muted set-no6">No IPv6 on this connection, so every service is reached over IPv4. That is normal.</p>}
          <ul className="set-services">
            {network.map((n) => (
              <li key={n.host} className="set-service">
                <div className="set-service-head">
                  <div className="set-service-name">
                    <b>{n.name}</b>
                    <span className="mono muted small">{n.host}</span>
                  </div>
                  <div className="set-service-state">
                    <Health level={n.level} words={NET_WORDS} />
                    {n.verdict && n.verdict.toLowerCase() !== 'ok' && <span className="muted small">{n.verdict}</span>}
                  </div>
                </div>
                <Pair label="IPv4" ms={n.ipv4_ms} error={n.ipv4_error} color="var(--seq-strong)" top={top} />
                {!noV6 && <Pair label="IPv6" ms={n.ipv6_ms} error={n.ipv6_error} color="var(--seq-soft)" top={top} />}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}

// ---- the tools -----------------------------------------------------------------------------------

function ToolRow({ tool, mailCompose, daily, perUse, index }: { tool: ToolStatus; mailCompose: boolean; daily: number[] | null; perUse: boolean; index: number }) {
  const { titles } = useAppState()
  const Glyph = isTool(tool.name) ? TOOL_ICON[tool.name] : IconSettings
  const last = tool.last_call
  const out = isSignedOut(tool.login?.state)
  const service = serviceOf(tool)
  return (
    <li className="set-tool" style={{ '--tile': toolColor(tool.name), '--i': index } as CSSProperties}>
      <span className="navtile"><Glyph size={18} strokeWidth={2} aria-hidden /></span>
      <div className="set-tool-name">
        <b>{toolName(tool.name)}</b>
        <span className="muted small"><span className="mono">{tool.name}</span> · {tool.tools} tools</span>
      </div>
      <div className="set-tool-badges">
        <Health level={tool.level} words={out ? SIGNED_OUT_WORDS : TOOL_WORDS} />
        {tool.name === 'mail-ai' && (
          <span className={`badge ${mailCompose ? 'chip' : ''}`}><IconSend size={13} aria-hidden />Drafting {mailCompose ? 'on' : 'off'}</span>
        )}
      </div>
      <div className="set-tool-last">
        {out && (
          <div className="set-login bad">
            <p className="set-login-line"><IconFail size={14} aria-hidden /><span>{tool.login!.state === 'missing' ? `${service} has not been signed in yet.` : `${service} refused the saved login.`}</span></p>
            <Details text={tool.login!.detail} />
          </div>
        )}
        {tool.login?.state === 'unknown' && (
          <div className="set-login">
            <p className="set-login-line muted"><IconClock size={14} aria-hidden /><span>Could not check the {service} login just now.</span></p>
            <Details text={tool.login.detail} />
          </div>
        )}
        {last ? (
          <>
            <span className="set-eyebrow">Last action</span>
            <p className="set-last-line">
              <span>{actionTitle(last.tool, titles)}</span>
              <Outcome outcome={last.outcome} />
              <time dateTime={new Date(last.at).toISOString()} className="muted small" title={ago(last.at)}>{stamp(last.at)}</time>
            </p>
            {last.error && <Details text={last.error} />}
          </>
        ) : (
          <p className="muted">Not used yet.</p>
        )}
      </div>
      <div className="set-tool-spark">
        {daily ? (
          <>
            <Sparkline values={daily} color={toolColor(tool.name)} width={112} height={34} label={`${toolName(tool.name)} actions per day over the last ${USAGE_DAYS} days`} />
            <span className="muted small">last {USAGE_DAYS} days</span>
          </>
        ) : perUse ? (
          <span className="muted small">No actions in {USAGE_DAYS} days</span>
        ) : null}
      </div>
    </li>
  )
}

/** Actions per day for each tool over the last two weeks, or null where the loaded log cannot say so honestly. */
function usageByTool(rows: AuditRow[] | null): Record<string, number[]> | null {
  if (!rows) return null
  const days = lastDays(USAGE_DAYS)
  // A capped log that does not reach back to the first day would undercount it: say nothing instead.
  const oldest = rows.reduce((m, r) => Math.min(m, new Date(r.at).getTime()), Infinity)
  if (rows.length >= USAGE_LIMIT && oldest > days[0]!.getTime()) return null
  const index = new Map(days.map((d, i) => [dayKey(d), i]))
  const out: Record<string, number[]> = {}
  for (const r of rows) {
    const i = index.get(dayKey(new Date(r.at)))
    if (i === undefined) continue
    const tool = (r.tool.split('__')[0] ?? '').replace(/_/g, '-')
    const series = (out[tool] ??= Array.from({ length: USAGE_DAYS }, () => 0))
    series[i] = (series[i] ?? 0) + 1
  }
  return out
}

// ---- the page -------------------------------------------------------------------------------------

export function Settings() {
  const [status, setStatus] = useState<Status | null>(null)
  const [checking, setChecking] = useState(false)
  const [error, setError] = useState('')
  const [checkedAt, setCheckedAt] = useState<number | null>(null)
  const [usage, setUsage] = useState<AuditRow[] | null>(null)
  const [auth, setAuth] = useState<AuthInfo | null>(null)
  const [, tick] = useState(0)
  const { refreshLogin } = useAppState()

  const check = useCallback(async (live: boolean) => {
    setChecking(live)
    setError('')
    try {
      setStatus(await getStatus(live))
      if (live) {
        setCheckedAt(Date.now())
        void refreshLogin() // the sidebar reads what this check just found
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setChecking(false)
    }
  }, [refreshLogin])

  // Instant view first, then the live checks, which each cost a round trip.
  useEffect(() => {
    void check(false).then(() => check(true))
  }, [check])

  // The activity sparklines come from the audit log; without it the rows simply have none.
  useEffect(() => {
    let current = true
    getHistory(USAGE_LIMIT).then((rows) => { if (current) setUsage(rows) }, () => undefined)
    return () => { current = false }
  }, [])

  useEffect(() => {
    let current = true
    getMe().then((info) => { if (current) setAuth(info) }, () => undefined)
    return () => { current = false }
  }, [])

  // "3 min ago" keeps itself true.
  useEffect(() => {
    const timer = window.setInterval(() => tick((n) => n + 1), 30000)
    return () => window.clearInterval(timer)
  }, [])

  const perTool = useMemo(() => usageByTool(usage), [usage])

  if (!status) {
    if (error) {
      return (
        <div className="panel">
          <div className="card">
            <Empty icon={IconAlert} title="Could not check" action={<button onClick={() => void check(true)}><IconRefresh size={16} aria-hidden />Try again</button>}>
              <span className="error">{error}</span>
            </Empty>
          </div>
        </div>
      )
    }
    return (
      <div className="panel" aria-busy="true" aria-label="Loading the connection checks">
        <div className="card skeleton set-skel-banner" />
        <div className="grid-2 set-grid">
          <div className="card skeleton set-skel-card" />
          <div className="card skeleton set-skel-card" />
        </div>
        <div className="card skeleton set-skel-tools" />
      </div>
    )
  }

  return (
    <div className="panel set">
      <Verdict status={status} checking={checking} checkedAt={checkedAt} error={error} onCheck={() => void check(true)} />

      <div className="set-grid stagger">
        <div style={{ '--i': 0 } as CSSProperties}><ModelCard model={status.model} checking={checking} /></div>
        <div style={{ '--i': 1 } as CSSProperties}><NetworkCard network={status.network} checking={checking} /></div>
      </div>

      <section className="card set-tools" aria-label="Tools">
        <CardHead icon={IconSettings} title="Tools" sub="Whether each tool's login still works, and how its last action went.">
          <span className="muted small">{status.tools.length} connected</span>
        </CardHead>
        {status.tools.length === 0 ? (
          <p className="muted">No tools reported.</p>
        ) : (
          <ul className="set-toollist stagger">
            {status.tools.map((t, i) => (
              <ToolRow key={t.name} tool={t} mailCompose={status.mail_compose} daily={perTool?.[t.name]?.some((n) => n > 0) ? perTool[t.name]! : null} perUse={perTool !== null} index={i} />
            ))}
          </ul>
        )}
      </section>

      {auth?.email && (
        <aside className="set-account" aria-label="Signed-in account">
          <div className="set-account-info">
            <span className="set-account-label">Signed in as</span>
            <span className="set-account-email">{auth.email}</span>
          </div>
          <button className="ghost" onClick={() => { void signOut().then(() => window.location.reload()) }}>
            Sign out
          </button>
        </aside>
      )}

      {/* When a login is out the fix is in the banner above; this is for the times nothing says so. */}
      {signedOutNames(status).length === 0 && (
        <aside className="set-auth" aria-label="Signing back in">
          <IconAlert size={18} aria-hidden />
          <p className="hint">
            Signed out of something? Run <code>./auth</code> in the suite folder: it checks every login and renews only the dead ones.
          </p>
          <CopyButton text="./auth" />
        </aside>
      )}
    </div>
  )
}
