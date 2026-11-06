// Chat: the same conversation the buttons see, in a calmer frame. A reply's tool calls fold into one line that opens
// to what each was asked and what came back; what you did on other pages folds into one line too; an approval
// waiting on you is impossible to miss; a reply can be stopped; and a page with no conversation offers things to ask.

import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent, type MouseEvent, type ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { AUDIO_EXTS, clearChat, getConversation, isAudio, isMarkdown, sendChat, splitDocs, stopChat, uploadAudio, uploadDocs, type AssistantEvent } from '../api'
import { useAppState } from '../state'
import { BrandMark } from '../ui/Shell'
import { DropZone } from '../ui/DropZone'
import { useLayer } from '../ui/useLayer'
import { IconAttach, IconCheck, IconChevron, IconClose, IconCopy, IconMic, IconPanelOpen, IconSend, IconSpark, IconSpeak, IconStop, IconTrash } from '../ui/icons'
import { ConfirmDelete } from '../ui/ConfirmDelete'
import { PickFiles, UploadProgress } from './Upload'
import { canRecordInBrowser } from '../useBrowserRecorder'
import { useDictation } from '../useDictation'
import { useSpeech } from '../useSpeech'
import { clock, withDictated } from './dictationText'
import { ChatHistory } from './ChatHistory'
import { ApprovalCard } from './ApprovalCard'
import { StepGroup } from './StepDetails'
import { pairSteps, type Step } from './toolSteps'
import '../styles/panels/chat.css'

// What sits over Chat or takes its place, kept in the history (useLayer.ts): the history panel, or a past
// conversation by its id. Back closes the panel, and from a past conversation returns to the current one.
type ChatLayer = { panel?: 'history'; viewing?: string } | null

// The microphone needs a secure page (https, or localhost) and a browser that records; without one there is no
// button rather than one that fails.
const HAS_MIC = canRecordInBrowser()
// The two speech tools, page-only (their _meta): the controls show only when the tool is there to answer.
const DICTATE = 'meet_ai__dictate'
const SPEAK = 'audiobook__speak'

const CONVERSATION = new Set(['user_message', 'assistant_text', 'approval_needed', 'turn_error', 'turn_stopped'])

const SUGGESTIONS = [
  'What is in my inbox?',
  'What is running right now?',
  'Write up my latest meeting as a Google Doc',
  'Turn my newest PDF into an audiobook',
]

/** Read one reply aloud, or stop it while it is being read. */
function ReadAloud({ reading, starting, onRead, onStop }: { reading: boolean; starting: boolean; onRead: () => void; onStop: () => void }) {
  return (
    <button
      className={`ghost read-aloud${reading ? ' reading' : ''}`}
      aria-label={reading ? (starting ? 'Getting ready to read this reply; press to stop' : 'Stop reading this reply') : 'Read this reply aloud'}
      aria-pressed={reading}
      title={reading ? 'Stop reading' : 'Read aloud'}
      onClick={reading ? onStop : onRead}
    >
      {reading ? (starting ? <span className="mic-spinner" aria-hidden /> : <IconStop size={12} aria-hidden />) : <IconSpeak size={14} aria-hidden />}
    </button>
  )
}

function Copy({ text }: { text: string }) {
  const [done, setDone] = useState(false)
  return (
    <button
      className="ghost copy"
      aria-label={done ? 'Copied' : 'Copy this reply'}
      title={done ? 'Copied' : 'Copy'}
      onClick={() => {
        navigator.clipboard?.writeText(text).then(
          () => { setDone(true); window.setTimeout(() => setDone(false), 1600) },
          () => {}, // refused (an insecure page, an older browser): nothing to do, the text is selectable
        )
      }}
    >
      {done ? <IconCheck size={14} aria-hidden /> : <IconCopy size={14} aria-hidden />}
    </button>
  )
}

export function Chat() {
  const { events, pending, busy, connected, titles, tools } = useAppState()
  const canDictate = HAS_MIC && tools.has(DICTATE)
  const canSpeak = tools.has(SPEAK)
  const [draft, setDraft] = useState('')
  const [error, setError] = useState('')
  const [attached, setAttached] = useState<string[]>([])
  const [uploading, setUploading] = useState<{ name: string; fraction: number } | null>(null)
  const [atBottom, setAtBottom] = useState(true)
  const [clearing, setClearing] = useState(false)
  const [clearBusy, setClearBusy] = useState(false)
  const [clearError, setClearError] = useState('')
  const [stopping, setStopping] = useState(false)
  const [layer, setLayer] = useState<ChatLayer>(null)
  useLayer('chat', layer, setLayer)
  const [opened, setOpened] = useState<{ id: string; events: AssistantEvent[]; title: string } | null>(null)
  const historyOpen = layer?.panel === 'history'
  const viewingId = layer?.viewing ?? null
  const viewing = viewingId !== null && opened?.id === viewingId ? opened : null
  const historyButton = useRef<HTMLButtonElement>(null)
  // Arrived at a past conversation by Forward or a reload: the history holds only its id, so it is fetched again.
  // One that is gone (deleted elsewhere) closes, back to the current chat.
  useEffect(() => {
    if (viewingId === null || opened?.id === viewingId) return
    let live = true
    getConversation(viewingId)
      .then((c) => { if (live) setOpened({ id: c.id, events: c.events, title: c.title }) })
      .catch(() => { if (live) setLayer(null) })
    return () => { live = false }
  }, [viewingId, opened?.id])
  // The panel closed: focus goes back to the button that opened it, not to the top of the page.
  const wasOpen = useRef(false)
  useEffect(() => {
    if (wasOpen.current && !historyOpen) historyButton.current?.focus()
    wasOpen.current = historyOpen
  }, [historyOpen])
  const scroller = useRef<HTMLDivElement>(null)
  const bottom = useRef<HTMLDivElement>(null)
  const field = useRef<HTMLTextAreaElement>(null)
  // Dictation: the words land in the message box, to be read and sent by hand, never sent by themselves.
  const dictation = useDictation((said) => {
    setDraft((d) => withDictated(d, said))
    // With a mouse, the box takes focus, ready to edit. On a touch screen it does not: focus would open the
    // on-screen keyboard over half the page, when the next thing is often just Send.
    if (window.matchMedia('(pointer: coarse)').matches) return
    requestAnimationFrame(() => {
      const box = field.current
      if (box) { box.focus(); box.setSelectionRange(box.value.length, box.value.length) }
    })
  })
  // A press on a microphone button keeps focus where it was. On a phone, focus anywhere in the chat box hides the tab
  // bar (chat.css), which moved the box 64px between press and release, so the release missed the button and nothing
  // happened (found in Chrome as a phone). The keyboard still reaches them with Tab.
  const keepFocus = (e: MouseEvent) => e.preventDefault()
  // A reply is read aloud only when its speaker button is pressed (the user's choice, 2026-11-06): never by itself.
  const speech = useSpeech()
  const listening = dictation.state === 'recording'
  const writing = dictation.state === 'transcribing'
  const { cancel: cancelDictation } = dictation
  useEffect(() => {
    if (!listening) return
    const onKey = (e: globalThis.KeyboardEvent) => { if (e.key === 'Escape') cancelDictation() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [listening, cancelDictation])

  // An attachment is an upload like any other: the server tells the model about it with the
  // next message, so "transcribe this" or "make this a Doc" needs no path typed out.
  const attach = async (files: File[]) => {
    setError('')
    const audio = files.filter((f) => isAudio(f.name))
    const docs = files.filter((f) => isMarkdown(f.name))
    const other = files.filter((f) => !isAudio(f.name) && !isMarkdown(f.name))
    if (other.length) setError(`Not attached — only audio or markdown: ${other.map((f) => f.name).join(', ')}`)
    try {
      for (const f of audio) {
        setUploading({ name: f.name, fraction: 0 })
        const saved = await uploadAudio(f, (fraction) => setUploading({ name: f.name, fraction }))
        setAttached((a) => [...a, saved.name])
      }
      if (docs.length) {
        const { top, name } = splitDocs(docs)
        setUploading({ name, fraction: 0 })
        const saved = await uploadDocs(top, name, (fraction) => setUploading({ name, fraction }))
        setAttached((a) => [...a, ...saved.files])
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setUploading(null)
    }
  }

  // Follow the conversation while you are at the bottom; leave you alone if you scrolled up to read.
  useEffect(() => {
    if (atBottom) bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [events.length, pending.length, busy, atBottom])

  useEffect(() => {
    const el = bottom.current
    const root = scroller.current
    if (!el || !root) return
    const watch = new IntersectionObserver(([entry]) => setAtBottom(entry?.isIntersecting ?? true), { root, threshold: 0.9 })
    watch.observe(el)
    return () => watch.disconnect()
  }, [])

  const submit = async (e?: FormEvent) => {
    e?.preventDefault()
    const message = draft.trim()
    if (!message || busy) return
    setError('')
    speech.stop() // a new message: the old reply stops being read
    try {
      await sendChat(message)
      setDraft('')
      setAttached([])
      setAtBottom(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  // Stop, at the reply's next safe point (the server's rule): the button says so until the reply has ended.
  useEffect(() => { if (!busy) setStopping(false) }, [busy])
  const stop = async () => {
    setStopping(true)
    setError('')
    try {
      await stopChat()
    } catch (err) {
      setStopping(false)
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  // A cleared chat starts empty. The server keeps a button's own result, which Overview and Activity list, but
  // Chat shows nothing from before the last clear (found live: a "You pressed" chip outlived Clear chat).
  const clearedAt = Math.max(0, ...events.filter((e) => e.type === 'chat_cleared').map((e) => e.seq))
  const liveVisible = events.filter((e) => e.seq > clearedAt)
  const visible = viewing ? viewing.events : liveVisible
  const asked = visible.filter((e) => e.type === 'user_message').length
  const talked = visible.some((e) => CONVERSATION.has(e.type) || (e.type === 'tool_finished' && e.origin !== 'button'))
  const canClear = connected && !busy && pending.length === 0

  const doClear = async () => {
    setClearBusy(true)
    setClearError('')
    try {
      await clearChat()
      setClearing(false)
    } catch (err) {
      setClearError(err instanceof Error ? err.message : String(err))
    } finally {
      setClearBusy(false)
    }
  }

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      void submit()
    }
  }

  // A reply's tool calls fold into one line; so do the changes made with buttons on other pages, which the model is
  // told about but which are not the conversation. One group per run of the same kind.
  const steps = pairSteps(visible)
  const rows: ReactNode[] = []
  let cluster: Step[] = []
  const flush = (key: string) => {
    if (cluster.length) {
      const fromButtons = cluster[0]!.origin === 'button'
      rows.push(fromButtons
        ? <StepGroup key={key} steps={cluster} titles={titles} summary={cluster.length === 1 ? 'You did this on another page' : `You did ${cluster.length} things on other pages`} />
        : <StepGroup key={key} steps={cluster} titles={titles} />)
    }
    cluster = []
  }
  for (const event of visible) {
    switch (event.type) {
      case 'tool_finished': {
        // Read-only button presses are status polls; they would flood the transcript.
        if (event.origin === 'button' && event.read_only) break
        const step = steps.get(event.seq)
        if (!step) break
        if (cluster.length && cluster[0]!.origin !== step.origin) flush(`c${event.seq}`)
        cluster.push(step)
        break
      }
      case 'user_message':
        flush(`c${event.seq}`)
        rows.push(<div key={event.seq} className="bubble user">{event.text}</div>)
        break
      case 'assistant_text':
        flush(`c${event.seq}`)
        rows.push(
          <div key={event.seq} className="msg assistant-msg">
            <span className="avatar" aria-hidden><BrandMark size={26} /></span>
            <div className="bubble assistant">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{event.text ?? ''}</ReactMarkdown>
              {canSpeak && (
                <ReadAloud
                  reading={speech.reading === `a${event.seq}`}
                  starting={speech.starting}
                  onRead={() => speech.read(`a${event.seq}`, event.text ?? '')}
                  onStop={speech.stop}
                />
              )}
              <Copy text={event.text ?? ''} />
            </div>
          </div>,
        )
        break
      case 'approval_needed': {
        flush(`c${event.seq}`)
        const live = pending.find((p) => p.id === event.id)
        if (live) rows.push(<ApprovalCard key={event.seq} approval={live} />)
        break
      }
      case 'turn_error':
        flush(`c${event.seq}`)
        rows.push(
          <div key={event.seq} className="chat-error" role="alert">
            {event.settings ? <>{event.error} <a href="#settings">Open Settings</a></> : <>Something went wrong: {event.error}</>}
          </div>,
        )
        break
      case 'turn_stopped':
        flush(`c${event.seq}`)
        rows.push(<p key={event.seq} className="chat-stopped muted small">You stopped this reply.</p>)
        break
      default:
        break
    }
  }
  flush('end')

  const typeSuggestion = (text: string) => {
    setDraft(text)
    field.current?.focus()
  }

  return (
    <DropZone
      className="chat"
      accepts={(f) => isAudio(f.name) || isMarkdown(f.name)}
      label="Drop audio or markdown to attach"
      onRefuse={(names) => setError(`Not attached — only audio or markdown: ${names.join(', ')}`)}
      onFiles={(files) => void attach(files)}
      disabled={!connected || uploading !== null}
    >
      <h1 className="sr-only">Chat</h1>
      <div className="chat-tools">
        <button ref={historyButton} className="ghost" onClick={() => setLayer({ panel: 'history' })} aria-label="Chat history" title="Chat history">
          <IconPanelOpen size={15} aria-hidden /><span className="chat-tools-label">History</span>
        </button>
        {viewing && (
          <span className="chat-viewing-title">{viewing.title || 'Untitled'}</span>
        )}
        <span className="chat-tools-spacer" />
        {viewing ? (
          <button className="ghost" onClick={() => setLayer(null)}>
            Back to chat
          </button>
        ) : asked > 0 ? (
          <button className="ghost" onClick={() => { setClearError(''); setClearing(true) }} disabled={!canClear} title={busy ? 'Wait for the reply to finish' : undefined}>
            <IconTrash size={14} aria-hidden />Clear chat
          </button>
        ) : null}
      </div>
      <ChatHistory
        open={historyOpen}
        onClose={() => setLayer(null)}
        busy={busy}
        onLoad={(id, evts, title) => { setOpened({ id, events: evts, title }); setLayer({ viewing: id }) }}
        onNewChat={() => setLayer(null)}
      />
      <div className="transcript" aria-live="polite" ref={scroller}>
        {/* Empty means no conversation, not no events: a background notice, or a button pressed on another page,
            is an event too, and once hid the suggestions behind four chips. */}
        {!talked && !busy && pending.length === 0 && (
          <div className="chat-empty">
            <BrandMark size={48} />
            <h2>What can I do for you?</h2>
            <p className="muted">Ask in your own words. Anything that changes something asks you first.</p>
            <div className="suggestions">
              {SUGGESTIONS.map((s) => (
                <button key={s} onClick={() => typeSuggestion(s)}><IconSpark size={14} aria-hidden />{s}</button>
              ))}
            </div>
          </div>
        )}

        {rows}

        {!viewing && busy && pending.length === 0 && (
          <div className="msg assistant-msg">
            <span className="avatar working" aria-hidden><BrandMark size={26} /></span>
            <div className="thinking" role="status" aria-label={stopping ? 'Stopping' : 'Working'}>
              {stopping ? <span className="small muted">Stopping…</span> : <><i /><i /><i /></>}
            </div>
          </div>
        )}
        {!viewing && pending
          .filter((p) => !events.some((e) => e.type === 'approval_needed' && e.id === p.id))
          .map((p) => <ApprovalCard key={p.id} approval={p} />)}
        <div ref={bottom} className="chat-end" />
      </div>

      {!atBottom && (
        <button className="to-latest" aria-label="Jump to latest" onClick={() => bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })}>
          <IconChevron size={18} aria-hidden style={{ transform: 'rotate(90deg)' }} /><span>Jump to latest</span>
        </button>
      )}

      {!viewing && (attached.length > 0 || uploading) && (
        <div className="attachments">
          {attached.map((name, i) => <span key={`${name}-${i}`} className="chip"><IconAttach size={13} aria-hidden />{name}</span>)}
          {uploading && <UploadProgress name={uploading.name} fraction={uploading.fraction} />}
        </div>
      )}

      {viewing ? (
        <div className="viewing-footer">
          <button className="primary" onClick={() => setLayer(null)}>Back to current chat</button>
        </div>
      ) : (
        <>
          <form className={`composer${listening ? ' listening' : ''}`} onSubmit={(e) => void submit(e)}>
            {!listening && <PickFiles
              label=""
              ariaLabel="Attach a recording or a markdown file"
              icon={<IconAttach size={18} aria-hidden />}
              accept={[...AUDIO_EXTS, '.md'].join(',') + ',audio/*'}
              multiple
              disabled={!connected || uploading !== null}
              onPick={(files) => void attach(files)}
              className="ghost attach"
            />}
            <textarea
              ref={field}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKey}
              placeholder={!connected ? 'Reconnecting…' : listening ? 'Listening…' : writing ? 'Writing down what you said…' : busy ? 'Working…' : 'Message the assistant'}
              disabled={!connected}
              rows={1}
              aria-label="Message"
            />
            {canDictate && (listening
              ? (
                <>
                  <span className="dictation-time" aria-hidden>{clock(dictation.elapsed)}</span>
                  <button className="ghost mic-cancel" type="button" onMouseDown={keepFocus} onClick={dictation.cancel} aria-label="Throw the recording away" title="Throw it away (Esc)">
                    <IconClose size={16} aria-hidden />
                  </button>
                  <button className="mic listening" type="button" onMouseDown={keepFocus} onClick={dictation.finish} aria-label="Stop and write down what you said" aria-pressed="true" title="Stop and write it down">
                    <IconMic size={18} aria-hidden />
                  </button>
                </>
              )
              : (
                <button className="ghost mic" type="button" onMouseDown={keepFocus} onClick={() => { speech.stop(); dictation.start() }} disabled={!connected || writing || dictation.state === 'starting'}
                  aria-label={writing ? 'Writing down what you said' : 'Dictate a message'} aria-pressed="false" title="Dictate">
                  {writing ? <span className="mic-spinner" aria-hidden /> : <IconMic size={18} aria-hidden />}
                </button>
              ))}
            {busy
              ? (
                <button className="send stop" type="button" onClick={() => void stop()} disabled={stopping} aria-label={stopping ? 'Stopping the reply' : 'Stop the reply'} title="Stop">
                  <IconStop size={16} aria-hidden />
                </button>
              )
              : (
                <button className="primary send" type="submit" disabled={!draft.trim() || !connected} aria-label="Send">
                  <IconSend size={18} aria-hidden />
                </button>
              )}
          </form>
          <p className="sr-only" role="status">{listening ? 'Recording. Press the microphone again to stop.' : writing ? 'Writing down what you said.' : ''}</p>
          <p className="composer-hint muted small">{listening ? `Recording ${clock(dictation.elapsed)} of up to 2 minutes · press the microphone to stop · Esc throws it away` : writing ? 'Writing down what you said' : busy ? 'Stop ends the reply: a step already running finishes, nothing after it starts' : 'Enter to send · Shift+Enter for a new line · drop a recording or a markdown file to attach it'}</p>
        </>
      )}
      {error && <p className="error composer-error">{error}</p>}
      {!viewing && dictation.error && <p className="error composer-error">{dictation.error}</p>}
      {speech.error && <p className="error composer-error">{speech.error}</p>}
      {clearing && (
        <ConfirmDelete
          title="Clear this conversation?"
          facts={[['Your messages', String(asked)]]}
          keeps="The assistant forgets this conversation. What it remembers about you (Memory), your uploads and documents, and History are not touched."
          verb="Clear chat"
          busy={clearBusy}
          error={clearError}
          onConfirm={() => void doClear()}
          onCancel={() => setClearing(false)}
        />
      )}
    </DropZone>
  )
}
