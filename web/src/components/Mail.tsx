// Buttons for mail. Reading, searching and syncing always; writing, drafts and sending only when mail-ai has
// been given them -- the page asks the server what exists rather than assuming.
//
// A list on the left (the inbox, or the drafts in Gmail) and what is open on the right: a conversation, a
// draft, or a new email. On a phone the list comes first and what is open takes the whole screen, with a
// Back button. Writing is a short, visible ladder: write, save as a draft in Gmail, then review the whole
// email and confirm. Nothing is sent until the second press, and that press is only offered after the full
// email has been shown; discarding a draft is asked about the same way, with the draft shown.

import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactElement, type ReactNode, type RefObject } from 'react'
import { runAction } from '../api'
import { ask, call } from '../call'
import { toolColor } from '../charts/palette'
import { useAppState } from '../state'
import { ConfirmDelete } from '../ui/ConfirmDelete'
import { Empty } from '../ui/Empty'
import { useLayer } from '../ui/useLayer'
import {
  IconAlert, IconBack, IconCheck, IconChevron, IconDocuments, IconMail, IconOk, IconPlus, IconRefresh, IconSearch, IconSend, IconTrash,
} from '../ui/icons'
import { ago } from '../ui/time'
import { usePoll } from '../usePoll'
import { cleanBody, firstWords } from './mailText'
import '../styles/panels/mail.css'

interface Status { messages: number; threads: number; newest: string; full_sync_complete: boolean; synced_at?: string }
interface Thread { thread_id: string; subject: string; started_by: string; messages: number; last: string }
interface Message { id: string; from: string; to: string; at: string; body: string }
interface ThreadDetail { thread_id: string; subject: string; messages: Message[] }
interface Found { id: string; thread_id: string; from_addr: string; subject: string; at: string }
/** A draft in Gmail as the list shows it. */
interface DraftSummary { draft_id: string; thread_id: string; to: string; cc: string; subject: string; snippet: string; updated: string }
/** What sending or discarding a draft needs: which draft, who it goes to, and the token for what was read. */
interface DraftRef { draft_id: string; to: string; confirmation: string }
interface Review { draft_id: string; thread_id: string; rendered: string; confirmation: string }

/** What is open on the right. */
type Pane = { kind: 'thread'; id: string } | { kind: 'draft'; id: string } | { kind: 'compose' }

/** One line in the list: a conversation, a message a search found, or a draft. */
interface Item { key: string; open: Pane; title: string; who: string; count: number; when: string; line?: string }

const PAGE = 40
const DAY = 86_400_000

const when = (iso: string) => (iso ? new Date(iso).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : '')
const who = (address: string) => address.replace(/<.*>/, '').replace(/"/g, '').trim() || address
const message = (e: unknown) => (e instanceof Error ? e.message : String(e))
const same = (a: Pane | null, b: Pane) => !!a && a.kind === b.kind && (a.kind === 'compose' || (b.kind !== 'compose' && a.id === b.id))

/** "3 h ago" for the last week, then a date: the way a mail list reads. */
function short(iso: string): string {
  if (!iso) return ''
  const t = new Date(iso)
  if (Number.isNaN(t.getTime())) return ''
  if (Date.now() - t.getTime() < 7 * DAY) return ago(t)
  const sameYear = t.getFullYear() === new Date().getFullYear()
  return t.toLocaleDateString([], { day: 'numeric', month: 'short', ...(sameYear ? {} : { year: 'numeric' }) })
}

const initial = (name: string) => (name.match(/[\p{L}\p{N}]/u)?.[0] ?? '?').toUpperCase()
const tintOf = (name: string) => [...name].reduce((n, c) => n + c.charCodeAt(0), 0) % 4

/** A sender as a small circle with their initial: a neutral tint from the name, so a person keeps theirs. */
function Avatar({ name }: { name: string }) {
  return <span className="mbox-avatar" data-tint={tintOf(name)} aria-hidden>{initial(name)}</span>
}

// ---- one email body: text only, its empty runs folded, and folded itself when it is long -----------------

const URL_RE = /https?:\/\/[^\s<>"')\]]+/g

function linkify(text: string): (string | ReactElement)[] {
  const parts: (string | ReactElement)[] = []
  let last = 0
  for (const m of text.matchAll(URL_RE)) {
    const at = m.index!
    let url = m[0]
    // Strip trailing punctuation that is almost certainly not part of the URL.
    while (url.length > 8 && /[.,;:!?)>\]}]$/.test(url)) url = url.slice(0, -1)
    if (at > last) parts.push(text.slice(last, at))
    parts.push(<a key={at} href={url} target="_blank" rel="noopener noreferrer">{url}</a>)
    last = at + url.length
  }
  if (last === 0) return [text]
  if (last < text.length) parts.push(text.slice(last))
  return parts
}

function Body({ text }: { text: string }) {
  const shown = cleanBody(text)
  const long = shown.length > 1400 || shown.split('\n').length > 20
  const [expanded, setExpanded] = useState(false)
  return (
    <div className="mbox-body">
      {/* Email written by someone else: text only, never markup. Links are React elements, not innerHTML. */}
      <pre className={long && !expanded ? 'is-folded' : ''}>{shown ? linkify(shown) : '(no text)'}</pre>
      {long && (
        <button className="ghost" aria-expanded={expanded} onClick={() => setExpanded((x) => !x)}>
          {expanded ? 'Show less' : 'Show the whole message'}
        </button>
      )}
    </div>
  )
}

// ---- the last step: the whole email, then one deliberate press ---------------------------------------

/** Sending is the one thing here that cannot be undone, so it is shown in full first. */
function SendConfirm({ preview, to, onSend, onCancel, sending }: {
  preview: string | null; to: string; onSend: () => void; onCancel: () => void; sending: boolean
}) {
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    box.current?.focus({ preventScroll: true })
    box.current?.scrollIntoView({ block: 'nearest' })
  }, [])
  return (
    <div
      ref={box}
      className="mbox-confirm"
      role="group"
      aria-labelledby="mbox-confirm-title"
      aria-describedby="mbox-confirm-warning"
      tabIndex={-1}
      onKeyDown={(e) => { if (e.key === 'Escape' && !sending) onCancel() }}
    >
      <div className="mbox-confirm-head">
        <span className="mbox-confirm-kicker" id="mbox-confirm-title"><IconSend size={15} aria-hidden />This will send</span>
        <span className="mbox-confirm-sub">and cannot be undone</span>
      </div>
      <p className="mbox-confirm-to">To <b>{to}</b></p>
      {preview
        ? <pre className="mbox-preview">{preview}</pre>
        : <p className="approval-warning">The email could not be shown. Sending means sending it unseen.</p>}
      <p className="mbox-confirm-warning" id="mbox-confirm-warning"><IconAlert size={16} aria-hidden />Sending cannot be undone. Check who it goes to and what it says.</p>
      <div className="mbox-confirm-actions">
        <button className="primary" disabled={sending} onClick={onSend}><IconSend size={16} aria-hidden />{sending ? 'Sending…' : 'Send'}</button>
        <button disabled={sending} onClick={onCancel}>Cancel</button>
      </div>
    </div>
  )
}

/** A saved draft's two ways out: send it (shown whole, then a second press) or discard it (shown, then asked).
 *  Both go through the server's own preview, which is the draft as Gmail holds it now. A button's first press
 *  of either returns that preview and does nothing else; the page once took that answer for done, and said
 *  "Draft discarded." over a draft still in Gmail (2026-10-30). */
function DraftActions({ draft, onSent, onDiscarded, saved = true, children }: {
  draft: DraftRef
  onSent: () => void
  onDiscarded: () => void
  /** Just saved here, rather than an existing draft opened from the list. */
  saved?: boolean
  children?: ReactNode
}) {
  const [sendPreview, setSendPreview] = useState<string | null | undefined>(undefined)
  const [discardPreview, setDiscardPreview] = useState<string | null | undefined>(undefined)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const lock = useRef(false) // one send or discard in flight, however fast the presses

  const run = async (label: string, fn: () => Promise<void>) => {
    if (lock.current) return
    lock.current = true
    setBusy(label)
    setError('')
    try {
      await fn()
    } catch (e) {
      setError(message(e))
    } finally {
      lock.current = false
      setBusy('')
    }
  }
  const args = { draft_id: draft.draft_id, confirmation: draft.confirmation }

  // First press: the server returns the rendered email instead of sending.
  const askSend = () => run('send', async () => {
    const r = await runAction('mail_ai__send_draft', args)
    setSendPreview(r.needs_confirmation ? (r.preview ?? null) : null)
  })
  // Second, confirmed press: the gate re-checks the draft still says what was shown.
  const send = () => run('send', async () => {
    const r = await runAction<{ error?: string }>('mail_ai__send_draft', args, true)
    if (r.outcome && r.outcome !== 'ok') throw new Error(String(r.output))
    if (r.output && typeof r.output === 'object' && 'error' in r.output && r.output.error) throw new Error(String(r.output.error))
    setSendPreview(undefined)
    onSent()
  })
  const askDiscard = () => run('discard', async () => {
    const r = await ask('mail_ai__discard_draft', { draft_id: draft.draft_id })
    if (r.confirm) setDiscardPreview(r.preview)
    else onDiscarded() // a server that does not ask has already done it
  })
  const discard = () => run('discard', async () => {
    await ask('mail_ai__discard_draft', { draft_id: draft.draft_id }, true)
    setDiscardPreview(undefined)
    onDiscarded()
  })

  return (
    <>
      {sendPreview === undefined && (
        <div className="mbox-draft">
          <p className="mbox-draftline">
            <IconOk size={18} aria-hidden />
            <span>{saved ? `Draft to ${who(draft.to)} saved in Gmail.` : `Draft to ${who(draft.to) || 'nobody yet'}.`}</span>
            <span className="badge">Not sent</span>
          </p>
          {children}
          <div className="mbox-actions">
            <button disabled={!!busy} onClick={() => void askSend()}><IconSend size={16} aria-hidden />{busy === 'send' ? 'Loading…' : 'Send…'}</button>
            <button className="ghost" disabled={!!busy} onClick={() => void askDiscard()}><IconTrash size={16} aria-hidden />{busy === 'discard' ? 'Loading…' : 'Discard…'}</button>
            <span className="hint">Both show you the whole email first.</span>
          </div>
        </div>
      )}
      {sendPreview !== undefined && (
        <SendConfirm preview={sendPreview} to={draft.to} sending={busy === 'send'}
          onSend={() => void send()} onCancel={() => setSendPreview(undefined)} />
      )}
      {discardPreview !== undefined && (
        <ConfirmDelete
          title="Discard this draft?"
          facts={[['To', draft.to]]}
          keeps="Nothing is sent. The draft is deleted from Gmail."
          verb="Discard"
          busy={busy === 'discard'}
          error={error}
          onConfirm={() => void discard()}
          onCancel={() => { setDiscardPreview(undefined); setError('') }}
        >
          {discardPreview ? <pre className="confirm-preview">{discardPreview}</pre> : <p className="approval-warning">The draft could not be shown.</p>}
        </ConfirmDelete>
      )}
      {error && discardPreview === undefined && <p className="mbox-note bad" role="alert"><IconAlert size={16} aria-hidden /><span>{error}</span></p>}
    </>
  )
}

// ---- writing: the steps, a reply, a new email --------------------------------------------------------

function Steps({ step }: { step: number }) {
  return (
    <ol className="mbox-steps" aria-label="Steps to send">
      {['Write', 'Saved as a draft', 'Review and send'].map((label, i) => (
        <li key={label} aria-current={step === i + 1 ? 'step' : undefined} className={step > i + 1 ? 'is-done' : step === i + 1 ? 'is-now' : ''}>
          <span className="mbox-step-dot">{step > i + 1 ? <IconCheck size={13} strokeWidth={3} aria-hidden /> : i + 1}</span>
          {label}
        </li>
      ))}
    </ol>
  )
}

/** What happened last, said beside the box it happened in. */
function Said({ ok, bad }: { ok?: string; bad?: string }) {
  return (
    <>
      {ok && <p className="mbox-note ok" role="status"><IconOk size={16} aria-hidden /><span>{ok}</span></p>}
      {bad && <p className="mbox-note bad" role="alert"><IconAlert size={16} aria-hidden /><span>{bad}</span></p>}
    </>
  )
}

function ReplyBox({ thread, onDraftsChanged }: { thread: ThreadDetail; onDraftsChanged: () => void }) {
  const [text, setText] = useState('')
  const [draft, setDraft] = useState<DraftRef | null>(null)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const [error, setError] = useState('')

  const save = async () => {
    setBusy(true)
    setError('')
    setNote('')
    try {
      setDraft(await call<DraftRef>('mail_ai__draft_reply', { thread_id: thread.thread_id, body: text.trim() }))
      onDraftsChanged()
    } catch (e) {
      setError(message(e))
    } finally {
      setBusy(false)
    }
  }
  const done = (what: string) => { setDraft(null); setText(''); setNote(what); onDraftsChanged() }

  return (
    <section className="mbox-reply" aria-label="Reply" data-step={draft ? 2 : 1}>
      <Steps step={draft ? 2 : 1} />
      {!draft ? (
        <div className="stack">
          <label className="mbox-label" htmlFor="mbox-reply">Your reply</label>
          <textarea id="mbox-reply" value={text} onChange={(e) => setText(e.target.value)} rows={5} placeholder="Write a reply" />
          <div className="mbox-actions">
            <button className="primary" disabled={!text.trim() || busy} onClick={() => void save()}>{busy ? 'Saving…' : 'Save as draft'}</button>
            <span className="hint">A draft is kept in Gmail. Nothing is sent.</span>
          </div>
        </div>
      ) : (
        <DraftActions draft={draft} onSent={() => done('Sent.')} onDiscarded={() => done('Draft discarded.')}>
          {text.trim() && <pre className="mbox-quote">{text.trim()}</pre>}
        </DraftActions>
      )}
      <Said ok={note} bad={error} />
    </section>
  )
}

function Compose({ heading, onBack, onDraftsChanged, onFinished }: {
  heading: RefObject<HTMLHeadingElement | null>
  onBack: () => void
  onDraftsChanged: () => void
  onFinished: (what: string) => void
}) {
  const [to, setTo] = useState('')
  const [cc, setCc] = useState('')
  const [withCc, setWithCc] = useState(false)
  const [subject, setSubject] = useState('')
  const [text, setText] = useState('')
  const [draft, setDraft] = useState<DraftRef | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const addressed = /\S+@\S+\.\S+/.test(to)

  const save = async () => {
    setBusy(true)
    setError('')
    try {
      const made = await call<DraftRef>('mail_ai__draft_new', { to: to.trim(), subject: subject.trim(), body: text.trim(), cc: cc.trim() })
      setDraft({ draft_id: made.draft_id, to: made.to || to.trim(), confirmation: made.confirmation })
      onDraftsChanged()
    } catch (e) {
      setError(message(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <header className="mbox-thread-head">
        <button className="mbox-back" onClick={onBack}><IconBack size={16} aria-hidden />Back to the list</button>
        <h2 ref={heading} tabIndex={-1}>New email</h2>
        <p className="muted small">Saved as a draft in Gmail first; nothing is sent until you have read it whole.</p>
      </header>
      <section className="mbox-reply mbox-compose" aria-label="Write and send" data-step={draft ? 2 : 1}>
        <Steps step={draft ? 2 : 1} />
        {!draft ? (
          <form className="stack" onSubmit={(e) => { e.preventDefault(); if (addressed && text.trim() && !busy) void save() }}>
            <label className="mbox-field-row">
              <span className="mbox-label">To</span>
              <input type="email" multiple value={to} onChange={(e) => setTo(e.target.value)} placeholder="name@example.com" autoComplete="email" required />
            </label>
            {withCc ? (
              <label className="mbox-field-row">
                <span className="mbox-label">Cc</span>
                <input type="email" multiple value={cc} onChange={(e) => setCc(e.target.value)} placeholder="Optional" />
              </label>
            ) : (
              <button type="button" className="ghost mbox-addcc" onClick={() => setWithCc(true)}><IconPlus size={14} aria-hidden />Add Cc</button>
            )}
            <label className="mbox-field-row">
              <span className="mbox-label">Subject</span>
              <input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="What it is about" />
            </label>
            <label className="mbox-label" htmlFor="mbox-compose-body">Message</label>
            <textarea id="mbox-compose-body" value={text} onChange={(e) => setText(e.target.value)} rows={8} placeholder="Write your email" />
            <div className="mbox-actions">
              <button type="submit" className="primary" disabled={!addressed || !text.trim() || busy}>{busy ? 'Saving…' : 'Save as draft'}</button>
              <span className="hint">{!addressed && to.trim() ? 'Who is it to? An address like name@example.com.' : 'A draft is kept in Gmail. Nothing is sent.'}</span>
            </div>
          </form>
        ) : (
          <DraftActions draft={draft} onSent={() => onFinished('Sent.')} onDiscarded={() => onFinished('Draft discarded.')}>
            <pre className="mbox-quote">{subject.trim() ? `${subject.trim()}\n\n` : ''}{text.trim()}</pre>
          </DraftActions>
        )}
        <Said bad={error} />
      </section>
    </>
  )
}

// ---- what is open: a conversation, or a draft --------------------------------------------------------

function ThreadView({ id, canDraft, heading, onBack, onDraftsChanged }: {
  id: string
  canDraft: boolean
  heading: RefObject<HTMLHeadingElement | null>
  onBack: () => void
  onDraftsChanged: () => void
}) {
  const [detail, setDetail] = useState<ThreadDetail | null>(null)
  const [error, setError] = useState('')
  // Only the newest message is open; the earlier ones are a line each until asked for.
  const [shown, setShown] = useState<Set<string>>(new Set())

  useEffect(() => {
    let live = true // an earlier, slower answer must not replace the one asked for last
    setDetail(null)
    setError('')
    call<ThreadDetail>('mail_ai__read_thread', { thread_id: id }).then(
      (d) => { if (live) { setDetail(d); setShown(new Set(d.messages.slice(-1).map((m) => m.id))) } },
      (e) => { if (live) setError(message(e)) },
    )
    return () => { live = false }
  }, [id])

  if (error) return <Said bad={error} />
  if (!detail) {
    return <div className="mbox-opening" aria-busy="true"><span className="skeleton" /><span className="skeleton" /><span className="skeleton" /></div>
  }
  const folded = detail.messages.filter((m) => !shown.has(m.id)).length
  const toggle = (mid: string) => setShown((old) => { const next = new Set(old); if (next.has(mid)) next.delete(mid); else next.add(mid); return next })

  return (
    <>
      <header className="mbox-thread-head">
        <button className="mbox-back" onClick={onBack}><IconBack size={16} aria-hidden />Back to the list</button>
        <h2 ref={heading} tabIndex={-1}>{detail.subject || '(no subject)'}</h2>
        <p className="mbox-thread-facts muted small">
          <span>{detail.messages.length} message{detail.messages.length === 1 ? '' : 's'}</span>
          {folded > 1 && <button className="ghost" onClick={() => setShown(new Set(detail.messages.map((m) => m.id)))}>Open all</button>}
        </p>
      </header>

      <div className="mbox-messages">
        {detail.messages.map((m) => (
          shown.has(m.id) ? (
            <article key={m.id} className="mbox-msg">
              <header>
                <Avatar name={who(m.from)} />
                <div className="mbox-msg-who">
                  <strong>{who(m.from)}</strong>
                  {m.to && <span className="muted small" title={m.to}>to {who(m.to)}</span>}
                </div>
                <time className="muted small" title={ago(m.at)}>{when(m.at)}</time>
              </header>
              <Body text={m.body} />
              {detail.messages.length > 1 && (
                <button className="ghost mbox-fold" aria-expanded="true" onClick={() => toggle(m.id)}>Fold this message</button>
              )}
            </article>
          ) : (
            <button key={m.id} className="mbox-msg-line" aria-expanded="false" onClick={() => toggle(m.id)}>
              <Avatar name={who(m.from)} />
              <span className="mbox-msg-line-main">
                <span className="mbox-item-top">
                  <span className="mbox-from">{who(m.from)}</span>
                  <time className="mbox-when" title={when(m.at)}>{short(m.at)}</time>
                </span>
                <span className="mbox-subject">{firstWords(m.body, 160) || '(no text)'}</span>
              </span>
            </button>
          )
        ))}
      </div>

      {canDraft
        ? <ReplyBox key={detail.thread_id} thread={detail} onDraftsChanged={onDraftsChanged} />
        : <p className="mbox-off hint"><IconAlert size={16} aria-hidden />Replying is off. Drafting and sending appear here once they are switched on for mail-ai.</p>}
    </>
  )
}

function DraftView({ id, heading, onBack, onFinished }: {
  id: string
  heading: RefObject<HTMLHeadingElement | null>
  onBack: () => void
  onFinished: (what: string) => void
}) {
  const [review, setReview] = useState<Review | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let live = true
    setReview(null)
    setError('')
    call<Review>('mail_ai__review_draft', { draft_id: id }).then(
      (r) => {
        if (!live) return
        setReview(r)
      },
      (e) => { if (live) setError(message(e)) },
    )
    return () => { live = false }
  }, [id])

  // The rendered draft is its header lines, a blank line, then the body: read To and Subject from the header
  // block only, so a body line that happens to start "Subject:" is never taken for one.
  const head = (review?.rendered ?? '').split('\n\n')[0] ?? ''
  const field = (name: string) => head.match(new RegExp(`^${name}:[ \\t]*(.*)$`, 'm'))?.[1]?.trim() ?? ''
  const to = field('To')

  return (
    <>
      <header className="mbox-thread-head">
        <button className="mbox-back" onClick={onBack}><IconBack size={16} aria-hidden />Back to the list</button>
        <h2 ref={heading} tabIndex={-1}>{field('Subject') || (review ? '(no subject)' : 'Draft')}</h2>
        <p className="muted small">A draft in Gmail{to ? `, to ${who(to)}` : ''}. Read as it stands now.</p>
      </header>
      {error && <div className="mbox-messages"><Said bad={error} /></div>}
      {!review && !error && <div className="mbox-opening" aria-busy="true"><span className="skeleton" /><span className="skeleton" /><span className="skeleton" /></div>}
      {review && (
        <>
          <div className="mbox-messages">
            <pre className="mbox-preview mbox-draft-text">{review.rendered}</pre>
          </div>
          <section className="mbox-reply" aria-label="Send or discard">
            <DraftActions
              saved={false}
              draft={{ draft_id: review.draft_id, to, confirmation: review.confirmation }}
              onSent={() => onFinished('Sent.')}
              onDiscarded={() => onFinished('Draft discarded.')}
            />
          </section>
        </>
      )}
    </>
  )
}

// ---- the page ----------------------------------------------------------------------------------------

type Note = { text: string; tone: 'ok' | 'bad' }

export function Mail() {
  const { tools } = useAppState()
  const canDraft = tools.has('mail_ai__draft_reply') && tools.has('mail_ai__send_draft')
  const canCompose = tools.has('mail_ai__draft_new') && tools.has('mail_ai__send_draft')
  const canDrafts = tools.has('mail_ai__list_drafts') && tools.has('mail_ai__review_draft')

  const [pages, setPages] = useState(1)
  const status = usePoll(() => call<Status>('mail_ai__status'), 30000)
  // "Load more" asks for a longer list rather than the next page: new mail arriving between two pages would
  // otherwise move a conversation from one page to the other, and it would show twice or not at all.
  const threads = usePoll(() => call<{ threads: Thread[] }>('mail_ai__list_threads', { limit: PAGE * pages }), 30000)
  useEffect(() => { if (pages > 1) void threads.reload() }, [pages])

  const [tab, setTab] = useState<'inbox' | 'drafts'>('inbox')
  const [drafts, setDrafts] = useState<DraftSummary[] | null>(null)
  const [draftsError, setDraftsError] = useState('')
  const [query, setQuery] = useState('')
  const [searched, setSearched] = useState('')
  const [found, setFound] = useState<Found[] | null>(null)
  const [pane, setPane] = useState<Pane | null>(null)
  const [view, setView] = useState<'list' | 'pane'>('list') // matters only where the two cannot sit side by side
  const [busy, setBusy] = useState('')
  const [note, setNote] = useState<Note | null>(null)

  const listCard = useRef<HTMLElement>(null)
  const paneCard = useRef<HTMLElement>(null)
  const heading = useRef<HTMLHeadingElement>(null)

  // Drafts are read from Gmail itself, so only when there is reason to: on opening the page, and after a
  // draft is made, sent or discarded here. Not polled.
  const loadDrafts = async () => {
    if (!canDrafts) return
    try {
      setDrafts((await call<{ drafts: DraftSummary[] }>('mail_ai__list_drafts')).drafts)
      setDraftsError('')
    } catch (e) {
      setDraftsError(message(e))
    }
  }
  useEffect(() => { void loadDrafts() }, [canDrafts])

  const sync = async () => {
    setBusy('sync')
    setNote(null)
    try {
      const r = await call<{ added: number }>('mail_ai__sync')
      setNote({ text: `${r.added} new message${r.added === 1 ? '' : 's'}`, tone: 'ok' })
      await Promise.all([status.reload(), threads.reload()])
    } catch (e) {
      setNote({ text: message(e), tone: 'bad' })
    } finally {
      setBusy('')
    }
  }

  const search = async () => {
    if (!query.trim()) { setFound(null); return }
    setBusy('search')
    try {
      setFound((await call<{ messages: Found[] }>('mail_ai__search', { text: query.trim() })).messages)
      setSearched(query.trim())
    } catch (e) {
      setNote({ text: message(e), tone: 'bad' })
    } finally {
      setBusy('')
    }
  }

  const openPane = (next: Pane) => { setPane(next); setView('pane') }
  // Back from a message or the composer closes it (useLayer.ts). Where the list is hidden behind it, that shows the list;
  // where the two sit side by side nothing else would change, so the pane is emptied too.
  useLayer('mail-pane', view === 'pane' ? pane : null, (to) => {
    if (to) { setPane(to); setView('pane') }
    else {
      setView('list')
      if ((listCard.current?.getClientRects().length ?? 1) > 0) setPane(null)
    }
  })
  const back = () => {
    setView('list')
    requestAnimationFrame(() => listCard.current?.querySelector<HTMLElement>('[aria-current="true"]')?.focus())
  }
  // A draft sent or discarded closes what was open and says so above the list.
  const finished = (what: string) => {
    setPane(null)
    setView('list')
    setNote({ text: what, tone: 'ok' })
    void loadDrafts()
  }

  // Where the two panes cannot sit side by side, opening something brings it to the top and into focus.
  const paneKey = pane ? (pane.kind === 'compose' ? 'compose' : `${pane.kind}:${pane.id}`) : ''
  useEffect(() => {
    if (view !== 'pane' || !pane) return
    const hidden = (listCard.current?.getClientRects().length ?? 1) === 0
    if (!hidden) return
    paneCard.current?.scrollIntoView({ block: 'start' })
    requestAnimationFrame(() => heading.current?.focus({ preventScroll: true }))
  }, [view, paneKey])

  const items: Item[] = tab === 'drafts'
    ? (drafts ?? []).map((d) => ({
      key: d.draft_id, open: { kind: 'draft', id: d.draft_id }, title: d.subject || '(no subject)',
      who: d.to ? `To ${who(d.to)}` : 'No recipient yet', count: 0, when: d.updated, line: firstWords(d.snippet, 120),
    }))
    : found
      ? found.map((m) => ({ key: m.id, open: { kind: 'thread', id: m.thread_id }, title: m.subject || '(no subject)', who: who(m.from_addr), count: 0, when: m.at }))
      : (threads.data?.threads ?? []).map((t) => ({ key: t.thread_id, open: { kind: 'thread', id: t.thread_id }, title: t.subject || '(no subject)', who: who(t.started_by), count: t.messages, when: t.last }))

  const onListKey = (e: KeyboardEvent<HTMLUListElement>) => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
    const rows = [...e.currentTarget.querySelectorAll<HTMLButtonElement>('button.mbox-item')]
    const at = rows.indexOf(document.activeElement as HTMLButtonElement)
    if (at < 0) return
    e.preventDefault()
    rows[Math.min(rows.length - 1, Math.max(0, at + (e.key === 'ArrowDown' ? 1 : -1)))]?.focus()
  }

  const listLoading = tab === 'drafts' ? drafts === null && !draftsError : threads.data === null && !threads.error
  const listed = threads.data?.threads.length ?? 0
  const more = tab === 'inbox' && !found && listed >= PAGE * pages && (status.data?.threads ?? 0) > listed
  const synced = status.data?.synced_at
  const facts = status.data
    ? `${status.data.messages.toLocaleString()} messages · ${synced ? `synced ${ago(synced)}` : status.data.newest ? `newest ${ago(status.data.newest)}` : 'not synced yet'}`
    : ''

  return (
    <div className="panel mbox-page">
      <div className={`mbox ${pane && view === 'pane' ? 'is-open' : ''}`}>
        {/* ---- the mailbox: how full and how fresh, a way to refresh it, and the list ---- */}
        <aside className="mbox-side">
          <section className="card mbox-head" aria-label="Mailbox">
            <div className="mbox-head-top">
              <span className="navtile" style={{ '--tile': toolColor('mail-ai') } as CSSProperties}><IconMail size={17} strokeWidth={2} aria-hidden /></span>
              <div className="mbox-head-title">
                <h2>Mailbox</h2>
                <p className="sub" title={synced ? `Last synced ${when(synced)}` : undefined}>
                  {facts || <span className="skeleton mbox-skel-line" />}
                </p>
              </div>
              <button disabled={busy === 'sync'} onClick={() => void sync()}>
                <IconRefresh size={16} aria-hidden className={busy === 'sync' ? 'mbox-spin' : undefined} />
                {busy === 'sync' ? 'Syncing…' : 'Sync'}
              </button>
            </div>
            {note && <Said ok={note.tone === 'ok' ? note.text : undefined} bad={note.tone === 'bad' ? note.text : undefined} />}
            {status.error && <Said bad={status.error} />}
          </section>

          <section className="card mbox-listcard" ref={listCard} aria-label={tab === 'drafts' ? 'Drafts' : 'Conversations'}>
            <div className="mbox-searchbar">
              {(canDrafts || canCompose) && (
                <div className="mbox-tabs">
                  {canDrafts && (
                    <div className="seg" role="radiogroup" aria-label="Show">
                      <button role="radio" aria-checked={tab === 'inbox'} onClick={() => setTab('inbox')}>Inbox</button>
                      <button role="radio" aria-checked={tab === 'drafts'} onClick={() => setTab('drafts')}>
                        Drafts{drafts !== null && <b> {drafts.length}</b>}
                      </button>
                    </div>
                  )}
                  {canCompose && (
                    <button className="mbox-new" aria-current={pane?.kind === 'compose' ? 'true' : undefined} onClick={() => openPane({ kind: 'compose' })}>
                      <IconPlus size={16} aria-hidden />New email
                    </button>
                  )}
                </div>
              )}
              {tab === 'inbox' ? (
                <>
                  <form className="mbox-search" role="search" onSubmit={(e) => { e.preventDefault(); void search() }}>
                    <label className="mbox-field">
                      <IconSearch size={16} aria-hidden />
                      <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search mail" aria-label="Search mail" />
                    </label>
                    <button type="submit" disabled={busy === 'search'}>{busy === 'search' ? 'Searching…' : 'Search'}</button>
                  </form>
                  <p className="mbox-meta" role="status">
                    {found ? (
                      <>
                        <span>{found.length} message{found.length === 1 ? '' : 's'} match “{searched}”</span>
                        <button className="ghost" type="button" onClick={() => { setFound(null); setQuery('') }}>Clear</button>
                      </>
                    ) : listLoading ? <span>Loading…</span> : <span>{items.length ? `Latest ${items.length} conversation${items.length === 1 ? '' : 's'}` : ''}</span>}
                  </p>
                </>
              ) : (
                <p className="mbox-meta" role="status">
                  <span>{drafts === null ? 'Reading your drafts from Gmail…' : `${drafts.length} draft${drafts.length === 1 ? '' : 's'} in Gmail`}</span>
                  <button className="ghost" type="button" onClick={() => void loadDrafts()}>Refresh</button>
                </p>
              )}
            </div>

            {listLoading ? (
              <ul className="mbox-list" aria-busy="true" aria-label="Loading">
                {Array.from({ length: 7 }, (_, i) => (
                  <li key={i} className="mbox-skel-item">
                    <span className="skeleton mbox-skel-avatar" />
                    <span className="mbox-skel-lines"><span className="skeleton" /><span className="skeleton" /></span>
                  </li>
                ))}
              </ul>
            ) : tab === 'drafts' && draftsError ? (
              <div className="mbox-listnote"><Said bad={draftsError} /></div>
            ) : items.length === 0 ? (
              tab === 'drafts'
                ? <Empty icon={IconDocuments} title="No drafts.">A reply or a new email saved here, or a draft the assistant writes, shows here until it is sent or discarded.</Empty>
                : <Empty icon={found ? IconSearch : IconMail} title={found ? 'Nothing matches.' : 'No mail synced yet.'}>
                  {found ? 'Try fewer words, or clear the search to see the latest conversations.' : 'Press Sync to bring your mailbox in.'}
                </Empty>
            ) : (
              <ul className="mbox-list stagger" onKeyDown={onListKey}>
                {items.map((item, i) => {
                  const on = same(pane, item.open)
                  return (
                    <li key={`${item.key}-${i}`} style={{ '--i': Math.min(i, 8) } as CSSProperties}>
                      <button className={`mbox-item ${on ? 'is-on' : ''}`} aria-current={on ? 'true' : undefined} onClick={() => openPane(item.open)}>
                        <Avatar name={item.who.replace(/^To /, '')} />
                        <span className="mbox-item-main">
                          <span className="mbox-item-top">
                            <span className="mbox-from">{item.who}</span>
                            <time className="mbox-when" title={when(item.when)}>{short(item.when)}</time>
                          </span>
                          <span className="mbox-item-sub">
                            <span className="mbox-subject">{item.title}</span>
                            {item.count > 1 && <span className="mbox-count" title={`${item.count} messages`}>{item.count}</span>}
                          </span>
                          {item.line && <span className="mbox-line">{item.line}</span>}
                        </span>
                      </button>
                    </li>
                  )
                })}
                {more && (
                  <li className="mbox-more">
                    <button className="ghost" disabled={threads.data === null} onClick={() => setPages((p) => p + 1)}>
                      Load {PAGE} more<IconChevron size={16} aria-hidden className="mbox-more-icon" />
                    </button>
                  </li>
                )}
              </ul>
            )}
          </section>
        </aside>

        {/* ---- what is open ---- */}
        <section className="card mbox-thread" ref={paneCard} aria-label={pane?.kind === 'draft' ? 'Draft' : pane?.kind === 'compose' ? 'New email' : 'Conversation'}>
          {!pane ? (
            <Empty icon={IconMail} title="Pick a conversation">
              Open one from the list to read it here{canCompose ? ', or write a new email' : ''}.
            </Empty>
          ) : pane.kind === 'thread' ? (
            <ThreadView key={pane.id} id={pane.id} canDraft={canDraft} heading={heading} onBack={back} onDraftsChanged={() => void loadDrafts()} />
          ) : pane.kind === 'draft' ? (
            <DraftView key={pane.id} id={pane.id} heading={heading} onBack={back} onFinished={finished} />
          ) : (
            <Compose heading={heading} onBack={back} onDraftsChanged={() => void loadDrafts()} onFinished={finished} />
          )}
        </section>
      </div>
    </div>
  )
}
