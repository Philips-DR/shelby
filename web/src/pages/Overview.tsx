// The front page: what has been happening and what needs you. Summary first, then the detail;
// every number and chart is drawn from the real audit log and the live status of the tools. The range
// is one filter, above everything it scopes. Picking a day on the activity chart narrows the cards
// beside it to that day, and says so.

import { useMemo, useState, type CSSProperties } from 'react'
import { getHistory, getStatus, toolLabel as qualifiedLabel } from '../api'
import { ChartCard, DataTable } from '../charts/ChartCard'
import { HBars } from '../charts/HBars'
import { toolColor, toolName as displayTool, TOOLS, toolOf } from '../charts/palette'
import { Ring } from '../charts/Ring'
import { duration } from '../charts/scale'
import { ShareBar } from '../charts/ShareBar'
import { Sparkline } from '../charts/Sparkline'
import { StackedColumns } from '../charts/StackedColumns'
import { useCountUp } from '../charts/useWidth'
import { useAppState } from '../state'
import { IconAlert, IconAudiobooks, IconChat, IconCheck, IconChevron, IconDocuments, IconFail, IconMeetings, IconOk } from '../ui/icons'
import { PageHead } from '../ui/PageHead'
import { SECTIONS, type Section } from '../ui/sections'
import { TOOL_ICON, TOOL_SECTION } from '../ui/toolMeta'
import { ago, clock } from '../ui/time'
import { usePoll, fileName } from '../usePoll'
import { change, columns, dayKey, medianByTool, period, seriesFor, summarise, type Row } from './overviewData'
import { useLiveJobs } from './useLiveJobs'

const RANGES = [7, 14, 30]

// ---- a stat tile: label, value, change against the period before, and the shape of the period ----

function Stat({ label, value, format = (n) => Math.round(n).toLocaleString(), suffix, deltaText, deltaTone, spark, sparkLabel, hero = false, children, index }: {
  label: string
  value: number | null
  format?: (n: number) => string
  suffix?: string
  deltaText?: string
  deltaTone?: 'good' | 'bad' | 'flat'
  spark?: number[]
  sparkLabel?: string
  hero?: boolean
  children?: React.ReactNode
  index: number
}) {
  const shown = useCountUp(value ?? 0)
  return (
    <div className={`card stat ${hero ? 'hero' : ''}`} style={{ '--i': index } as CSSProperties}>
      <span className="stat-label">{label}</span>
      <span className="stat-value">
        {value === null ? '—' : format(shown)}
        {suffix && value !== null && <small>{suffix}</small>}
      </span>
      <div className="stat-foot">
        {deltaText ? <span className={`stat-delta ${deltaTone ?? 'flat'}`}>{deltaText}</span> : <span />}
        {spark && <Sparkline values={spark} label={sparkLabel ?? label} width={hero ? 150 : 96} />}
        {children}
      </div>
    </div>
  )
}

/** A change as a person reads it: 12%, and past a tenfold change a multiple, since "3388%" says less than "36x". */
const arrow = (pct: number | null) => {
  if (pct === null) return 'New'
  if (pct === 0) return 'No change'
  const size = Math.abs(pct) >= 1000 ? `${Math.round(1 + Math.abs(pct) / 100)}×` : `${Math.abs(pct)}%`
  return `${pct > 0 ? '▲' : '▼'} ${size}`
}

// ---- what is running right now ------------------------------------------------------------------

function RunningNow({ go }: { go: (to: Section) => void }) {
  const { book, transcription, recording } = useLiveJobs()
  const items: React.ReactNode[] = []

  if (recording?.state === 'recording') {
    items.push(
      <li key="rec" className="run-item">
        <span className="rec-dot" aria-hidden />
        <div className="run-main"><strong>Recording a meeting</strong><span className="muted small">{clock(recording.recorded_seconds)} so far</span></div>
        <button onClick={() => go('meetings')}>Open</button>
      </li>,
    )
  }
  if (transcription?.state === 'running') {
    items.push(
      <li key="tr" className="run-item">
        <Ring value={transcription.percent} label="Transcription progress">{transcription.percent !== null ? `${Math.round(transcription.percent)}%` : ''}</Ring>
        <div className="run-main">
          <strong>Transcribing {fileName(transcription.audio)}</strong>
          <span className="muted small">{transcription.phase}{transcription.eta ? ` · about ${transcription.eta} left` : ''}</span>
        </div>
        <button onClick={() => go('meetings')}>Open</button>
      </li>,
    )
  }
  if (book?.state === 'running') {
    const what = { analyse: 'Reading', render: 'Rendering', voice: 'Cloning a voice from', sample: 'A sample of' }[book.kind]
    items.push(
      <li key="bk" className="run-item">
        <Ring value={book.percent} label="Progress">{book.percent !== null ? `${Math.round(book.percent)}%` : ''}</Ring>
        <div className="run-main">
          <strong>{what} {book.title || fileName(book.target)}</strong>
          <span className="muted small">
            {book.chapter !== null && book.chapter_title ? `${book.chapter_title} · ` : ''}{book.phase}{book.eta ? ` · about ${book.eta} left` : ''}
          </span>
        </div>
        <button onClick={() => go('audiobooks')}>Open</button>
      </li>,
    )
  }

  return (
    <div className="card">
      <div className="card-head"><div><h2>Running now</h2><p className="sub">Long jobs keep going when you close this page.</p></div></div>
      {items.length === 0 ? (
        <div className="empty compact"><strong>Nothing is running</strong><span>A render, a transcription or a recording will show up here, with how far along it is.</span></div>
      ) : (
        <ul className="runlist">{items}</ul>
      )}
    </div>
  )
}

// ---- recent activity -----------------------------------------------------------------------------

function Feed() {
  const { events } = useAppState()
  const shown = events
    .filter((e) => (e.type === 'tool_finished' && !e.read_only) || e.type === 'user_message' || e.type === 'turn_error' || e.type === 'notice' || e.type === 'upload')
    .slice(-7)
    .reverse()
  return (
    <div className="card">
      <div className="card-head"><div><h2>Recent</h2><p className="sub">Whatever you or the assistant changed, in either mode.</p></div></div>
      {shown.length === 0 ? (
        <div className="empty compact"><strong>Quiet so far</strong><span>Things you or the assistant do will be listed here as they happen.</span></div>
      ) : (
        <ul className="feed">
          {shown.map((e) => {
            const bad = e.type === 'turn_error' || (e.type === 'tool_finished' && e.outcome !== 'ok') || (e.type === 'notice' && e.level && e.level !== 'success')
            return (
              <li key={e.seq}>
                <span className={`feed-icon ${bad ? 'bad' : ''}`}>{bad ? <IconAlert size={14} aria-hidden /> : <IconCheck size={14} strokeWidth={2.6} aria-hidden />}</span>
                <span className="feed-text">
                  {e.type === 'user_message' && <>You asked: <em>{(e.text ?? '').slice(0, 70)}</em></>}
                  {e.type === 'turn_error' && <>A chat turn failed</>}
                  {e.type === 'notice' && <>{e.title}</>}
                  {e.type === 'upload' && <>You uploaded <strong>{e.name}</strong></>}
                  {e.type === 'tool_finished' && <>{e.origin === 'button' ? 'You' : 'The assistant'} ran <strong className="mono">{qualifiedLabel(e.tool)}</strong>{e.outcome !== 'ok' ? ` (${e.outcome})` : ''}</>}
                </span>
                <span className="muted small feed-time">{ago(e.at * 1000)}</span>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

// ---- one card per tool ---------------------------------------------------------------------------

function ToolRows({ rows, days, go, levels }: {
  rows: Row[]
  days: Date[]
  go: (to: Section) => void
  levels: Record<string, 'ok' | 'warning' | 'error' | undefined>
}) {
  return (
    <div className="card toolrows">
      {TOOLS.map((tool) => {
        const mine = rows.filter((r) => toolOf(r.tool) === tool)
        const section = SECTIONS.find((s) => s.id === TOOL_SECTION[tool])
        // A tool with no page of its own (Applications, Web) is listed only when it did something in this period: its
        // health is on Settings, and a row that leads nowhere and says "not used" is noise.
        if (!section && mine.length === 0) return null
        const daily = days.map((d) => mine.filter((r) => dayKey(new Date(r.at)) === dayKey(d)).length)
        const last = mine.length ? mine.reduce((a, b) => (new Date(a.at) > new Date(b.at) ? a : b)) : null
        const level = levels[tool]
        const Icon = TOOL_ICON[tool]
        const Row = section ? 'button' : 'div'
        return (
          <Row key={tool} className="toolrow" style={{ '--tile': toolColor(tool) } as CSSProperties} onClick={section ? () => go(section.id) : undefined}>
            <span className="navtile"><Icon size={18} strokeWidth={2} aria-hidden /></span>
            <span className="toolrow-name">
              <b>{displayTool(tool)}</b>
              <span className="muted small">{last ? `Last: ${qualifiedLabel(last.tool)}, ${ago(last.at)}` : 'Not used in this period'}</span>
            </span>
            {level ? <span className={`badge toolrow-status ${level === 'ok' ? 'ok' : level === 'warning' ? 'warn' : 'bad'}`}>{level === 'ok' ? 'Healthy' : level === 'warning' ? 'Check' : 'Needs a login'}</span> : <span className="toolrow-status" />}
            <span className="toolrow-count"><b>{mine.length}</b> <span className="muted small">action{mine.length === 1 ? '' : 's'}</span></span>
            <span className="toolrow-spark"><Sparkline values={daily} color={toolColor(tool)} width={110} height={32} label={`${displayTool(tool)} actions per day`} /></span>
            {section ? <IconChevron size={16} aria-hidden className="toolrow-go" /> : <span aria-hidden />}
          </Row>
        )
      })}
    </div>
  )
}

// ---- the page --------------------------------------------------------------------------------------

export function Overview({ go }: { go: (to: Section) => void }) {
  const { pending } = useAppState()
  const [range, setRange] = useState(14)
  const [day, setDay] = useState<string | null>(null)
  const history = usePoll(() => getHistory(2000), 30000)
  const status = usePoll(() => getStatus(false), 30000)

  const loaded = history.data !== null
  const rows = useMemo(() => (history.data ?? []) as Row[], [history.data])
  const p = useMemo(() => period(rows, range), [rows, range])
  const cols = useMemo(() => columns(p.days, p.rows), [p.days, p.rows])
  const series = useMemo(() => seriesFor(p.rows), [p.rows])

  // The cards beside the chart follow a picked day; the tiles and the chart itself keep the range.
  const scoped = useMemo(() => (day ? p.rows.filter((r) => dayKey(new Date(r.at)) === day) : p.rows), [p.rows, day])
  const scopedSummary = useMemo(() => summarise(scoped), [scoped])
  const dayLabel = day ? cols.find((c) => c.key === day)?.label : null

  const rate = (s: ReturnType<typeof summarise>) => (s.ok + s.failed > 0 ? Math.round((s.ok / (s.ok + s.failed)) * 100) : null)
  const rateNow = rate(p.current)
  const rateBefore = rate(p.before)
  const medianBetter = p.current.medianMs !== null && p.before.medianMs !== null ? Math.round(((p.current.medianMs - p.before.medianMs) / Math.max(1, p.before.medianMs)) * 100) : null

  const levels = Object.fromEntries((status.data?.tools ?? []).map((t) => [t.name, t.level])) as Record<string, 'ok' | 'warning' | 'error' | undefined>
  const slow = medianByTool(scoped)
  const today = new Date().toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' })
  const rangeLabel = `the last ${range} days`

  return (
    <>
      <PageHead section="overview" blurb={`${today}. What has been happening, and what needs you.`}>
        <div className="seg" role="radiogroup" aria-label="Period">
          {RANGES.map((r) => (
            <button key={r} role="radio" aria-checked={range === r} onClick={() => { setRange(r); setDay(null) }}>{r} days</button>
          ))}
        </div>
      </PageHead>

      <div className="quick">
        <button className="primary" onClick={() => go('chat')}><IconChat size={16} aria-hidden />Ask the assistant</button>
        <button onClick={() => go('meetings')}><IconMeetings size={16} aria-hidden />Record a meeting</button>
        <button onClick={() => go('audiobooks')}><IconAudiobooks size={16} aria-hidden />Make an audiobook</button>
        <button onClick={() => go('documents')}><IconDocuments size={16} aria-hidden />Build a Google Doc</button>
      </div>

      <div className="kpis stagger">
        <Stat index={0} hero label={`Actions in ${rangeLabel}`} value={loaded ? p.current.count : null}
          deltaText={loaded ? `${arrow(change(p.current.count, p.before.count))} vs the ${range} days before` : undefined}
          spark={p.daily} sparkLabel={`Actions per day over ${rangeLabel}`} />
        <Stat index={1} label="Success rate" value={rateNow} format={(n) => String(Math.round(n))} suffix="%"
          deltaText={rateNow !== null && rateBefore !== null ? (rateNow === rateBefore ? 'No change' : `${rateNow > rateBefore ? '▲' : '▼'} ${Math.abs(rateNow - rateBefore)} pts`) : undefined}
          deltaTone={rateNow !== null && rateBefore !== null ? (rateNow > rateBefore ? 'good' : rateNow < rateBefore ? 'bad' : 'flat') : 'flat'} />
        <Stat index={2} label="Median action time" value={p.current.medianMs} format={(n) => duration(n)}
          deltaText={medianBetter === null ? undefined : arrow(medianBetter)}
          deltaTone={medianBetter === null || medianBetter === 0 ? 'flat' : medianBetter < 0 ? 'good' : 'bad'} />
        <Stat index={3} label="Waiting on you" value={pending.length} deltaText={pending.length === 0 ? 'All clear' : 'Answer in Chat or below'} deltaTone={pending.length === 0 ? 'good' : 'bad'}>
          {pending.length > 0 && <button className="primary" onClick={() => go('chat')}>Review</button>}
        </Stat>
      </div>

      <div className="grid-split">
        <ChartCard
          title="Activity"
          sub={`Actions per day, by tool, over ${rangeLabel}. Pick a day to look closer.`}
          table={<DataTable head={['Day', ...series.map((s) => s.label), 'Total']} rows={cols.map((c) => [c.label, ...series.map((s) => c.values[s.key] ?? 0), series.reduce((n, s) => n + (c.values[s.key] ?? 0), 0)])} />}
        >
          <StackedColumns columns={cols} series={series} label={`Actions per day, by tool, over ${rangeLabel}`} selected={day} onSelect={setDay} dimmed={!loaded} />
        </ChartCard>

        <div className="stack-cards">
          <ChartCard title="How it went" sub={dayLabel ? `For ${dayLabel}` : `Across ${rangeLabel}`}
            actions={day ? <button className="ghost" onClick={() => setDay(null)}>Show all days</button> : undefined}>
            <ShareBar label="Outcomes" parts={[
              { key: 'ok', label: 'Succeeded', value: scopedSummary.ok, color: 'var(--ok-fill)', icon: IconOk },
              { key: 'failed', label: 'Failed', value: scopedSummary.failed, color: 'var(--bad-fill)', icon: IconFail },
              { key: 'declined', label: 'Declined', value: scopedSummary.declined, color: 'var(--warn-fill)', icon: IconAlert },
            ]} />
          </ChartCard>
          <ChartCard title="Time per action" sub="Median, by tool">
            {slow.length === 0 ? (
              <div className="empty compact"><strong>No timings yet</strong><span>Each tool's typical time shows here once it has run.</span></div>
            ) : (
              <HBars label="Median time per action, by tool" items={slow.map((s) => ({ key: s.key, label: s.label, value: s.ms, display: duration(s.ms), color: toolColor(s.key) }))} />
            )}
          </ChartCard>
        </div>
      </div>

      <h2 className="section-title">Your tools</h2>
      <ToolRows rows={p.rows} days={p.days} go={go} levels={levels} />

      <div className="grid-2 section-gap">
        <RunningNow go={go} />
        <Feed />
      </div>
    </>
  )
}
