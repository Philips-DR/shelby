// Audiobooks by button: read a PDF, check what will be spoken, pick a voice, render, listen.
// The same audiobook tools the model calls in chat, called directly -- no model.
//
// Reading a book, rendering it and cloning a voice are all background jobs in the tool, one at a
// time, and `job_status` is the one place their progress lives. A render is hours; this page can
// be closed and reopened and the job is still there.
//
// The look: the chapters are a bar chart that is also the chooser (a bar per chapter, sized by its
// words, labelled with its speech time; click one to leave it out of the render). Everything on the
// page is drawn from what the tool returned; nothing is estimated here except the selection's
// speech and render time, which is the tool's own per-chapter figures added up (and says so).

import { useEffect, useMemo, useRef, useState, type ComponentType, type CSSProperties, type ReactNode } from 'react'
import {
  AUDIO_EXTS, deleteKept, deleteUpload, fetchMedia, fetchStored, getKept, getUploads, isAudio, uploadBook, uploadVoice,
  type Kept, type Uploads,
} from '../api'
import { ChartCard } from '../charts/ChartCard'
import { HBars } from '../charts/HBars'
import { toolColor } from '../charts/palette'
import { Ring } from '../charts/Ring'
import { useCountUp } from '../charts/useWidth'
import { ask, call } from '../call'
import { CardHead } from '../ui/CardHead'
import { usePlayer, usePlayerActions, type Track } from '../player/engine'
import { onRequest, takeRequest } from '../player/showing'
import { adjacent } from '../player/queue'
import { renderLabel, unrendered } from './audiobookText'
import { audioKey, goesWithBook, withKept, withKeptBooks, withKeptSamples, type AudioEntry } from './audiobookKept'
import { AudioPlayer } from '../ui/AudioPlayer'
import { useLayer } from '../ui/useLayer'
import { useAppState } from '../state'
import { ConfirmDelete, sizeOf } from '../ui/ConfirmDelete'
import { DropZone } from '../ui/DropZone'
import {
  IconAlert, IconAudiobooks, IconBack, IconCheck, IconChevron, IconClose, IconDocuments, IconDownload, IconFail, IconMeetings,
  IconOk, IconPlay, IconRefresh, IconSpark, IconStop, IconTrash, IconUpload, IconZap,
} from '../ui/icons'
import { Empty } from '../ui/Empty'
import { store } from '../player/storage'
import { fileName, usePoll } from '../usePoll'
import { PickFiles, UploadProgress } from './Upload'
import '../styles/panels/audiobooks.css'

type IconType = ComponentType<{ size?: number; strokeWidth?: number; 'aria-hidden'?: boolean; className?: string }>

interface Voice {
  name: string
  kind: 'cloned' | 'preset'
  source?: string | null
  similarity?: number | null
  consent?: string | null
}

interface BookJob {
  id: string
  kind: 'analyse' | 'render' | 'voice' | 'sample'
  target: string
  state: 'running' | 'done' | 'failed' | 'interrupted' | 'cancelled'
  phase: string
  percent: number | null
  chapter: number | null
  chapter_title: string | null
  chunks_done: number | null
  chunks_total: number | null
  eta: string | null
  outputs: string[]
  detail: string
  /** The book as a person names it; `target` is its file. Absent on jobs from before 2026-10-30. */
  title?: string | null
}

const fetchAudio = (a: AudioEntry) => (a.id ? fetchStored(a.id) : fetchMedia(a.path ?? ''))

interface Chapter {
  number: number
  label: string
  /** How this chapter's audio is named before its speed (the tool's names.chapter_stem): what kept audio is matched by. */
  stem?: string
  appendix: boolean
  words: number
  speech: string
  /** This chapter's rendered files, newest first (one per speed). */
  audio?: AudioEntry[]
}

interface Overview {
  pdf?: string
  analysed: boolean
  hint?: string
  title?: string
  author?: string | null
  chapters?: Chapter[]
  speech?: string
  render_time?: string
  citations_removed?: number
  skipped?: Record<string, number>
  /** The whole-book .m4b, and files from an earlier reading whose chapters were found differently. */
  other_audio?: AudioEntry[]
}

interface ChapterText {
  segments: { kind: string; text: string }[]
  truncated: boolean
  next_start: number | null
  announce: string
}

interface AudioBook {
  /** The output folder's name: the PDF's file name without .pdf. What describe and delete take. */
  book: string
  title?: string
  author?: string | null
  files: AudioEntry[]
}

const VOICES_OPEN = 'ab-voices-open'

/** A chapter to bring into view; a new object each time, so asking twice for the same chapter scrolls twice. */
interface Reveal { chapter: number }

const KIND_LABEL: Record<BookJob['kind'], string> = {
  analyse: 'Reading the book',
  render: 'Rendering',
  voice: 'Cloning a voice',
  sample: 'Speaking a sample',
}

/** What each job state looks like: an icon, a word and a tone. Status colour is never alone. */
const STATE: Record<BookJob['state'], { icon: IconType; tone: 'run' | 'ok' | 'bad' | 'warn' }> = {
  running: { icon: IconRefresh, tone: 'run' },
  done: { icon: IconOk, tone: 'ok' },
  failed: { icon: IconFail, tone: 'bad' },
  interrupted: { icon: IconAlert, tone: 'warn' },
  cancelled: { icon: IconStop, tone: 'warn' },
}

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))
const isPdf = (file: File) => /\.pdf$/i.test(file.name) || file.type === 'application/pdf'
const stem = (path: string) => fileName(path).replace(/\.pdf$/i, '')
const style = (vars: Record<string, string | number>) => vars as CSSProperties

/** [1, 2, 3, 5] → "1-3,5": the form start_render takes. */
function toSelection(numbers: number[]): string {
  const parts: string[] = []
  for (let i = 0; i < numbers.length; i++) {
    let j = i
    while (numbers[j + 1] === numbers[j]! + 1) j++
    parts.push(j > i ? `${numbers[i]}-${numbers[j]}` : `${numbers[i]}`)
    i = j
  }
  return parts.join(',')
}

// ---- the tool's own durations ("2 min", "1 h 18 min") ------------------------------------------------
// The tool writes every duration the same way, so parsing is exact; anything that does not match is
// shown as the tool wrote it and never computed with.

const DURATION = /^(?:(\d+) h )?(\d+) min$/

function parseMinutes(text: string | undefined): number | null {
  const m = DURATION.exec((text ?? '').trim())
  return m ? Number(m[1] ?? 0) * 60 + Number(m[2]) : null
}

function formatMinutes(total: number): string {
  const m = Math.round(total)
  if (m <= 0) return '0 min'
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')} min`
}

/**
 * Speech and render time for the chapters picked. All picked: the tool's own totals. Some picked:
 * the per-chapter figures added up, and only when they agree with the tool's total to within
 * their own rounding (each is rounded to the minute); otherwise nothing is claimed.
 */
function selectionTimes(data: Overview, chosen: Set<number>): { speech: string | null; render: string | null; approx: boolean } {
  const chapters = data.chapters ?? []
  if (chosen.size === chapters.length) return { speech: data.speech ?? null, render: data.render_time ?? null, approx: false }
  const mins = chapters.map((c) => parseMinutes(c.speech))
  const totalSpeech = parseMinutes(data.speech)
  const totalRender = parseMinutes(data.render_time)
  if (mins.some((m) => m === null) || !totalSpeech || totalRender === null) return { speech: null, render: null, approx: true }
  const all = mins.reduce<number>((n, m) => n + (m ?? 0), 0)
  if (Math.abs(all - totalSpeech) > Math.max(2, totalSpeech * 0.05)) return { speech: null, render: null, approx: true }
  const mine = chapters.reduce((n, c, i) => (chosen.has(c.number) ? n + (mins[i] ?? 0) : n), 0)
  return { speech: formatMinutes(mine), render: formatMinutes((mine * totalRender) / totalSpeech), approx: true }
}

/** "4 h 02 min" as big digits with small units; a string the tool wrote any other way is shown as written. */
function Duration({ text }: { text: string | null | undefined }) {
  if (!text) return <>—</>
  const m = DURATION.exec(text.trim())
  if (!m) return <>{text}</>
  return <>{m[1] !== undefined && <>{m[1]}<small>h</small> </>}{m[2]}<small>min</small></>
}

// ---- a figure: one number about the book -------------------------------------------------------------

function Fig({ label, count, suffix, children, foot, index }: {
  label: string
  count?: number
  suffix?: string
  children?: ReactNode
  foot?: ReactNode
  index: number
}) {
  const shown = useCountUp(count ?? 0, 450)
  return (
    <div className="card stat ab-stat" style={style({ '--i': index })}>
      <span className="stat-label">{label}</span>
      <span className="stat-value">
        {count !== undefined ? Math.round(shown).toLocaleString() : children}
        {suffix && <small>{suffix}</small>}
      </span>
      <span className="stat-delta ab-stat-foot">{foot}</span>
    </div>
  )
}

// ---------------------------------------------------------------------------

/** A chapter's newest file, as a track that knows the chapters with audio either side of it, so the player
 *  can go on to the next by itself (player/queue.ts). Each neighbour is fetched only when it is wanted. */
function chapterTrack(pdf: string, chapters: readonly Chapter[], chapter: Chapter, book: string, blob: Blob): Track {
  const near = (step: 1 | -1) => {
    const other = adjacent(chapters, chapter.number, step)
    return other && {
      title: other.label,
      load: async () => chapterTrack(pdf, chapters, other, book, await fetchAudio(other.audio![0]!)),
    }
  }
  return {
    key: audioKey(chapter.audio![0]!), title: `${chapter.label} · ${book}`, blob,
    home: { book: pdf, chapter: chapter.number },
    next: near(1) ?? undefined, previous: near(-1) ?? undefined,
  }
}

/** Play a file a tool made. Fetched with the token and handed to the one player that lives above the pages
 *  (player/engine.tsx), so what you start here keeps playing when you leave this page. */
function usePlay(audio: AudioEntry | undefined, title: string, asTrack?: (blob: Blob) => Track) {
  const { track, playing: audible } = usePlayer()
  const { open, close } = usePlayerActions()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const here = useRef(true)
  useEffect(() => { here.current = true; return () => { here.current = false } }, [])

  const key = audio ? audioKey(audio) : ''
  const current = !!key && track?.key === key
  const play = async () => {
    if (!audio) return
    setBusy(true)
    setError('')
    try {
      const blob = await fetchAudio(audio)
      // Left the page while it downloaded: nothing should start talking from somewhere you are not looking.
      if (here.current) open(asTrack ? asTrack(blob) : { key, title, blob })
    } catch (e) {
      if (here.current) setError(message(e))
    } finally {
      if (here.current) setBusy(false)
    }
  }
  return { current, playing: current && audible, busy, error, play, close }
}

/** Play or download a file a tool made, kept or still at its bench. */
function AudioFile({ audio, label }: { audio: AudioEntry; label?: string }) {
  const { current, playing, busy, error: playError, play, close } = usePlay(audio, label ?? audio.name)
  const [error, setError] = useState('')
  const size = audio.megabytes || null

  const download = async () => {
    setError('')
    try {
      const href = URL.createObjectURL(await fetchAudio(audio))
      const link = document.createElement('a')
      link.href = href
      link.download = audio.name
      link.click()
      window.setTimeout(() => URL.revokeObjectURL(href), 10_000)
    } catch (e) {
      setError(message(e))
    }
  }

  const kind = (audio.name.split('.').pop() ?? '').toUpperCase()
  return (
    <div className={`ab-file ${current ? 'loaded' : ''} ${playing ? 'playing' : ''}`}>
      <div className="ab-file-row">
        <span className="ab-file-tile" aria-hidden>
          {playing ? <span className="ab-eq"><i /><i /><i /></span> : <IconAudiobooks size={17} strokeWidth={2} />}
        </span>
        <span className="ab-file-name">
          <span className="ab-file-title">{label ?? audio.name}</span>
          <span className="muted small">
            {playing && <b className="ab-now">Playing · </b>}
            {size != null && `${size} MB`}{size != null && kind && ' · '}{kind}
          </span>
        </span>
        <span className="ab-file-act">
          {!current && (
            <button className="ab-play" disabled={busy} aria-busy={busy} onClick={() => void play()}>
              {busy ? <IconRefresh size={16} aria-hidden className="ab-spin" /> : <IconPlay size={16} aria-hidden />}
              <span className="ab-btn-label">{busy ? 'Loading…' : 'Play'}</span>
            </button>
          )}
          <button onClick={() => void download()}><IconDownload size={16} aria-hidden /><span className="ab-btn-label">Download</span></button>
        </span>
      </div>
      {current && <AudioPlayer onClose={close} />}
      {(error || playError) && <p className="error">{error || playError}</p>}
    </div>
  )
}

// ---------------------------------------------------------------------------

/** The book a job works on, as a person names it. */
const jobName = (job: BookJob) => job.title || fileName(job.target)

function JobCard({ job, name, samples, reload, openBook }: {
  job: BookJob | null
  /** The book's title as the library knows it, for a job from before jobs carried one. */
  name?: string
  /** The voice samples there are: a finished sample job's file, once the suite has taken it, is played from there. */
  samples: AudioEntry[]
  reload: () => Promise<void>
  /** Open the job's book; absent while that book is the one open. */
  openBook?: () => void
}) {
  // Stopping a render is a click, then a second one: it is hours of work being set down, even though
  // every sentence already spoken is kept.
  const [asking, setAsking] = useState(false)
  const [stopping, setStopping] = useState(false)
  const [error, setError] = useState('')
  if (!job) return null
  const running = job.state === 'running'
  const { icon: StateIcon, tone } = STATE[job.state]

  const cancel = async () => {
    setStopping(true)
    setError('')
    try {
      await call('audiobook__cancel_job', { job_id: job.id })
      setAsking(false)
      await reload()
    } catch (e) {
      setError(message(e))
    } finally {
      setStopping(false)
    }
  }

  // The chapter's own name only: its number in the job is the plan's count, which is not the book's
  // ("4: Chapter 1 God's Purpose…" when a foreword and an introduction come first).
  const facts = [
    job.chapter != null ? job.chapter_title : null,
    job.chapter != null && job.chunks_done != null && job.chunks_total != null ? `${job.chunks_done}/${job.chunks_total}` : null,
    job.percent != null ? `${job.percent.toFixed(0)}%` : job.phase,
    job.eta ? `about ${job.eta} left` : null,
  ].filter((f): f is string => f !== null)

  return (
    <div className={`card job job-${job.state} ab-job`}>
      <div className="ab-job-top">
        {running ? (
          <Ring value={job.percent} size={60} label="Progress">{job.percent !== null ? `${Math.round(job.percent)}%` : ''}</Ring>
        ) : (
          <span className={`ab-state ab-tone-${tone}`}><StateIcon size={22} strokeWidth={2} aria-hidden /></span>
        )}
        <div className="ab-job-title">
          <strong>{KIND_LABEL[job.kind]}: {job.title || name || jobName(job)}</strong>
          {running && <span className="ab-facts muted small">{facts.map((f) => <span key={f}>{f}</span>)}</span>}
        </div>
        <span className={`ab-job-act ${running ? 'with-cancel' : ''}`}>
          <span className={`badge ${tone === 'bad' ? 'bad' : ''}`}>
            <StateIcon size={13} strokeWidth={2.4} aria-hidden className={running ? 'ab-spin' : undefined} />
            {running ? job.phase : job.state}
          </span>
          {running && !asking && <button onClick={() => setAsking(true)}><IconStop size={14} aria-hidden />Cancel</button>}
        </span>
      </div>
      {running && asking && (
        <div className="warn-box ab-confirm">
          <p>
            Stop this {job.kind === 'render' ? 'render' : 'job'}?
            {job.kind === 'render' ? ' Everything already spoken is kept, so starting it again carries on.' : ' It will start over if run again.'}
          </p>
          <div className="row">
            <button className="danger" disabled={stopping} onClick={() => void cancel()}>{stopping ? 'Stopping…' : 'Yes, stop it'}</button>
            <button disabled={stopping} onClick={() => setAsking(false)}>Keep going</button>
          </div>
        </div>
      )}
      {error && <p className="error">{error}</p>}
      {running && (
        <>
          <div className="bar ab-bar" role="progressbar" aria-label="Progress" aria-valuenow={job.percent ?? 0} aria-valuemin={0} aria-valuemax={100}>
            <div style={{ width: `${job.percent ?? 0}%` }} />
          </div>
          {job.kind === 'analyse' && (
            <p className="hint">About 2–4 seconds a page, so minutes for a book; a scan is read with OCR and is much slower.</p>
          )}
          {job.kind === 'render' && (
            <p className="hint">One chapter at a time; each can be played from the book's chapter list as it completes. You can close this page.</p>
          )}
        </>
      )}
      {job.state === 'done' && job.kind === 'sample' && job.outputs.map((o) => (
        <AudioFile key={o} audio={samples.find((s) => s.name === fileName(o)) ?? { name: fileName(o), path: o, megabytes: 0, modified: 0 }} />
      ))}
      {job.state === 'done' && (job.kind === 'render' || job.kind === 'analyse') && (
        <p className="ab-done muted">
          {job.kind === 'render'
            ? `${job.outputs.length} file${job.outputs.length === 1 ? '' : 's'} made.`
            : 'Read: its chapters are ready to choose.'}{' '}
          {openBook && <button className="ghost ab-jump" onClick={openBook}>Open the book</button>}
        </p>
      )}
      {job.state === 'done' && job.kind === 'voice' && <p className="ab-done muted">The voice is ready. Hear a sample before using it.</p>}
      {(job.state === 'failed' || job.state === 'interrupted' || job.state === 'cancelled') && (
        <p className={`ab-detail ab-tone-${tone}`}><StateIcon size={16} aria-hidden /><span>{job.detail}</span></p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------

interface UploadsPoll { data: Uploads | null; error: string; reload: () => Promise<void> }

/** What the library knows of one book: its uploaded PDF, its finished audio, or both, matched by name as the
 *  output folder is (the folder is named for the PDF). */
interface Shelf {
  stem: string
  upload: { id: string; name: string; path: string; bytes: number } | null
  audio: AudioBook | null
}

/** A book to delete, as the library names it: its upload, how many audio files it has, and which of them the suite
 *  keeps (by record id). */
interface Doomed { stem: string; title: string; upload: { id: string; name: string; bytes: number } | null; audio: number; kept: string[] }

/** Delete one book: its uploaded PDF, its finished audio, or both. What goes is read first with the tool that
 * only reads, so the question names it; the delete tool is called only on a confirmed press, never to find out
 * what it would do. With both there, keeping the audio is a choice: it stays in the library, to listen to. */
function DeleteBook({ book, onCancel, onChanged, onDone }: {
  book: Doomed
  onCancel: () => void
  onChanged: () => void
  onDone: () => void
}) {
  // What the tool's own folder still holds for the book (working files, and audio not yet handed over), or null
  // while asking. Once the suite keeps a book's audio the folder is often gone, and then there is nothing to show.
  const [summary, setSummary] = useState<string | null>(null)
  const [folder, setFolder] = useState(false)
  const [keepAudio, setKeepAudio] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const audioGoes = book.audio > 0 && !(book.upload && keepAudio)

  useEffect(() => {
    let live = true
    call<{ summary: string; exists: boolean; running?: string | null }>('audiobook__describe_audiobook', { book: book.stem }).then(
      (r) => { if (live) { setSummary(r.summary); setFolder(r.exists || !!r.running) } },
      (e) => { if (live) setError(message(e)) },
    )
    return () => { live = false }
  }, [book.stem])

  const confirm = async () => {
    setBusy(true)
    setError('')
    // Kept audio keeps its folder; otherwise the audio goes -- the tool's folder, with the working files a reading
    // leaves in it, and what the suite keeps.
    if (!(book.upload && keepAudio && book.audio > 0)) {
      try {
        // The tool first: it refuses while the book is being read or rendered, and then nothing may go.
        await ask('audiobook__delete_audiobook', { book: book.stem }, true)
        if (book.kept.length > 0) await deleteKept(book.kept)
      } catch (e) {
        setError(message(e))
        setBusy(false)
        return
      }
      // The audio is gone from here on, whatever happens to the PDF.
      onChanged()
    }
    if (book.upload) {
      try {
        await deleteUpload(book.upload.id)
      } catch (e) {
        setError(audioGoes ? `The audio is deleted, but the PDF could not be: ${message(e)}` : `The PDF could not be deleted: ${message(e)}`)
        setBusy(false)
        onChanged()
        return
      }
      onChanged()
    }
    setBusy(false)
    onDone()
  }

  const facts: [string, string][] = []
  if (book.upload) facts.push(['Uploaded PDF', `${book.upload.name} (${sizeOf(book.upload.bytes)})`])
  if (book.audio > 0) facts.push(['Audio', `${book.audio} file${book.audio === 1 ? '' : 's'}${audioGoes ? '' : ' — kept'}`])

  return (
    <ConfirmDelete
      title={`Delete “${book.title}”?`}
      facts={facts}
      keeps={book.upload ? (audioGoes || book.audio === 0 ? undefined : 'Its audio stays in your library, to listen to.') : 'The PDF is not an upload, so it stays where it is.'}
      verb={summary === null && !error ? 'Checking…' : 'Delete'}
      ready={summary !== null}
      busy={busy}
      error={error}
      onConfirm={() => void confirm()}
      onCancel={onCancel}
    >
      {book.upload && book.audio > 0 && (
        <label className="check ab-keep">
          <input type="checkbox" checked={keepAudio} onChange={(e) => setKeepAudio(e.target.checked)} />
          Keep its audio, and delete only the PDF
        </label>
      )}
      {summary !== null && audioGoes && folder && <pre className="confirm-preview">{summary}</pre>}
    </ConfirmDelete>
  )
}

/** One book in the library: what it is, how far it has got, and its buttons. A book whose PDF is not an upload
 *  cannot be opened, so its files open here instead. */
function ShelfRow({ shelf, index, overview, running, onOpen, onDelete }: {
  shelf: Shelf
  index: number
  overview: Overview | undefined
  running: BookJob | null
  onOpen: (path: string) => void
  /** Ask to delete a book, by its folder's name; the page knows its upload and its audio. */
  onDelete: (stem: string, title: string) => void
}) {
  const [listening, setListening] = useState(false)
  const title = overview?.title ?? shelf.audio?.title ?? shelf.stem
  const author = overview?.author ?? shelf.audio?.author ?? null
  const files = shelf.audio?.files ?? []
  const megabytes = files.reduce((n, f) => n + f.megabytes, 0)
  const busy = running && shelf.upload && running.target === (overview?.pdf ?? shelf.upload.path) ? running : null
  const state = busy
    ? `${KIND_LABEL[busy.kind]}${busy.percent != null ? ` · ${Math.round(busy.percent)}%` : '…'}`
    : !shelf.upload ? 'The PDF is not uploaded'
      : overview === undefined ? null
        : overview.analysed ? `${overview.chapters?.length ?? 0} chapters · ${overview.speech} of speech`
          : 'Not read yet'
  return (
    <li className="ab-shelf-item" style={style({ '--i': index })}>
      <div className="ab-shelf-row">
        <span className="navtile ab-cover" style={style({ '--tile': toolColor('audiobook') })} aria-hidden>
          <IconAudiobooks size={18} strokeWidth={2} />
        </span>
        <span className="ab-shelf-main">
          <strong className="ab-shelf-title">{title}</strong>
          {author && <span className="small muted">{author}</span>}
          <span className="ab-facts small muted">
            {state && <span>{state}</span>}
            <span>{files.length ? `${files.length} audio file${files.length === 1 ? '' : 's'} · ${megabytes.toFixed(1)} MB` : 'No audio yet'}</span>
          </span>
        </span>
        <span className="ab-shelf-act">
          {shelf.upload
            ? <button onClick={() => onOpen(shelf.upload!.path)}>Open</button>
            : files.length > 0 && (
              <button aria-expanded={listening} onClick={() => setListening(!listening)}>
                <IconPlay size={16} aria-hidden />{listening ? 'Hide' : 'Listen'}
              </button>
            )}
          <button className="ghost icon" aria-label={`Delete ${title}`} title="Delete…" onClick={() => onDelete(shelf.stem, title)}>
            <IconTrash size={16} aria-hidden />
          </button>
        </span>
      </div>
      {listening && (
        <div className="ab-files ab-shelf-files">
          {files.map((f) => <AudioFile key={`${audioKey(f)}:${f.modified}`} audio={f} />)}
        </div>
      )}
    </li>
  )
}

/** Every book: the uploaded PDFs, and finished audio whose PDF is not an upload. Opening one shows only it. */
function Library({ shelves, overviews, job, uploads, onOpen, onDelete }: {
  shelves: Shelf[]
  overviews: Record<string, Overview | undefined>
  job: BookJob | null
  uploads: UploadsPoll
  onOpen: (path: string, readNow?: boolean) => void
  /** Ask to delete a book, by its folder's name; the page knows its upload and its audio. */
  onDelete: (stem: string, title: string) => void
}) {
  const [typed, setTyped] = useState('')
  const [uploading, setUploading] = useState<{ name: string; fraction: number } | null>(null)
  const [error, setError] = useState('')

  const upload = async ([file]: File[]) => {
    if (!file) return
    setError('')
    setUploading({ name: file.name, fraction: 0 })
    try {
      const saved = await uploadBook(file, (fraction) => setUploading({ name: file.name, fraction }))
      await uploads.reload()
      // Straight to the book, which starts reading it: there is nothing to choose until its chapters are found.
      onOpen(saved.path, true)
    } catch (e) {
      setError(message(e))
    } finally {
      setUploading(null)
    }
  }

  const running = job?.state === 'running' ? job : null
  return (
    <DropZone
      accepts={isPdf}
      label="Drop a PDF to upload"
      onRefuse={(names) => setError(`Not uploaded — an audiobook is made from a PDF (.pdf): ${names.join(', ')}`)}
      onFiles={(files) => void upload(files)}
      disabled={uploading !== null}
    >
      <div className="card ab-library">
        <CardHead icon={IconAudiobooks} tool="audiobook" title="Your books" sub="Open a book to choose its chapters, render it and listen.">
          <PickFiles label="Upload a PDF…" icon={<IconUpload size={16} aria-hidden />} accept=".pdf,application/pdf" className="primary" disabled={uploading !== null} onPick={(f) => void upload(f)} />
        </CardHead>
        {uploading && <UploadProgress name={uploading.name} fraction={uploading.fraction} />}
        {uploads.data === null && !uploads.error && <div className="skeleton ab-skel" aria-hidden />}
        {uploads.data !== null && shelves.length === 0 && (
          <Empty icon={IconUpload} title="No books yet">Upload a PDF, or drop one on this card. It is read, and then you choose the chapters to render.</Empty>
        )}
        {shelves.length > 0 && (
          <ul className="ab-shelf stagger">
            {shelves.map((s, i) => (
              <ShelfRow key={s.stem} shelf={s} index={i} overview={s.upload ? overviews[s.upload.path] : undefined} running={running} onOpen={onOpen} onDelete={onDelete} />
            ))}
          </ul>
        )}
        <details className="ab-bypath">
          <summary>Open a PDF by its path</summary>
          <div className="row">
            <input
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && typed.trim()) onOpen(typed.trim()) }}
              placeholder="A PDF on the computer the assistant runs on"
              aria-label="Path of a PDF"
            />
            <button disabled={!typed.trim()} onClick={() => onOpen(typed.trim())}>Open</button>
          </div>
        </details>
        {(error || uploads.error) && <p className="error">{error || uploads.error}</p>}
      </div>
    </DropZone>
  )
}

// ---------------------------------------------------------------------------

function Corrections({ pdf, onSaved }: { pdf: string; onSaved: () => void }) {
  const [text, setText] = useState('')
  const [loaded, setLoaded] = useState(false)
  const [note, setNote] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    call<{ text: string }>('audiobook__get_corrections', { pdf })
      .then((r) => { setText(r.text); setLoaded(true) })
      .catch((e) => setError(message(e)))
  }, [pdf])

  const save = async () => {
    setError('')
    setNote('')
    try {
      const r = await call<{ pairs: number; ignored: string[] }>('audiobook__set_corrections', { pdf, text })
      setNote(`Saved ${r.pairs} correction${r.pairs === 1 ? '' : 's'}.` +
        (r.ignored.length ? ` Not applied — nothing to find, or no “=>” in: ${r.ignored.join(' · ')}` : ''))
      onSaved()
    } catch (e) {
      setError(message(e))
    }
  }

  return (
    <div className="card ab-corrections">
      <CardHead icon={IconSpark} tool="audiobook" title="Corrections" sub="Fix a typo or a name before it is spoken." />
      <p className="hint">
        One per line, <code>find =&gt; replace</code>: for typos in the source, or a name the voice cannot say. Applied to what
        is spoken; only the sentences that change are re-read.
      </p>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={5}
        disabled={!loaded}
        placeholder={'Procedural Graph => PG\ncolour => color'}
        style={{ width: '100%' }}
        aria-label="Corrections"
        spellCheck={false}
      />
      <div className="row">
        <button disabled={!loaded} onClick={() => void save()}>Save corrections</button>
        {note && <span className="ab-note" role="status"><IconCheck size={14} strokeWidth={2.6} aria-hidden /><span>{note}</span></span>}
      </div>
      {error && <p className="error">{error}</p>}
    </div>
  )
}

function Reader({ pdf, chapter, onClose }: { pdf: string; chapter: Chapter; onClose: () => void }) {
  const [text, setText] = useState<ChapterText | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const load = async (start: number) => {
    setBusy(true)
    setError('')
    try {
      const more = await call<ChapterText>('audiobook__read_chapter', { pdf, chapter: chapter.number, start })
      setText((old) => (old && start > 0 ? { ...more, segments: [...old.segments, ...more.segments] } : more))
    } catch (e) {
      setError(message(e))
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => { void load(0) }, [pdf, chapter.number])

  return (
    <div className="card ab-reader">
      <CardHead icon={IconDocuments} tool="audiobook" title={`What will be read — ${chapter.label}`} sub={`The exact text the narrator will speak · ${chapter.words.toLocaleString()} words`}>
        <button className="ghost" onClick={onClose}><IconClose size={16} aria-hidden />Hide</button>
      </CardHead>
      <div className="reader">
        {text && (
          <div className="reader-text">
            <p className="muted small">Announced as: “{text.announce}”</p>
            {text.segments.map((s, i) => s.kind === 'heading' || s.kind === 'title'
              ? <p key={i}><strong>{s.text}</strong></p>
              : <p key={i}>{s.kind === 'list_item' ? '• ' : ''}{s.text}</p>)}
          </div>
        )}
        {text?.truncated && (
          <div className="row"><button disabled={busy} onClick={() => void load(text.next_start ?? 0)}>Show more</button></div>
        )}
        {busy && !text && (
          <>
            <p className="muted">Reading…</p>
            <div className="skeleton ab-skel" aria-hidden />
          </>
        )}
        {error && <p className="error">{error}</p>}
      </div>
    </div>
  )
}

/** One chapter: tick it to render it, play it once it is rendered, read what will be spoken. Its text and its
 *  player open under it: below the whole list, a phone showed nothing where the button was pressed. */
function ChapterRow({ pdf, version, chapter, chapters, chosen, longest, book, reading, onToggle, onRead }: {
  pdf: string
  /** Bumped when corrections are saved, so open text is read again with them applied. */
  version: number
  chapter: Chapter
  /** The whole book's chapters, so the player knows which comes next. */
  chapters: readonly Chapter[]
  chosen: boolean
  longest: number
  book: string
  reading: boolean
  onToggle: () => void
  onRead: () => void
}) {
  // The newest file of this chapter, whatever its speed.
  const audio = chapter.audio?.[0]
  const { current, playing, busy, error, play, close } = usePlay(audio, `${chapter.label} · ${book}`,
    (blob) => chapterTrack(pdf, chapters, chapter, book, blob))
  const width = longest > 0 ? Math.max(2, (chapter.words / longest) * 100) : 0
  return (
    <li id={`ab-ch-${chapter.number}`} className={`ab-ch ${chosen ? '' : 'off'} ${current ? 'loaded' : ''}`}>
      <div className="ab-ch-row">
        <label className="ab-ch-pick">
          <input type="checkbox" checked={chosen} onChange={onToggle} />
          <span className="ab-ch-title">{chapter.label}{chapter.appendix && <span className="muted"> · appendix</span>}</span>
        </label>
        <span className="ab-ch-len" title={`${chapter.words.toLocaleString()} words`}>
          <span className="ab-ch-bar" aria-hidden><i style={{ width: `${width}%` }} /></span>
          <span className="small muted">{chapter.speech}</span>
        </span>
        <span className="ab-ch-act">
          <span className="ab-ch-play">
            {audio && !current && (
              <button className="ab-play" disabled={busy} aria-busy={busy} aria-label={`Play ${chapter.label}`} onClick={() => void play()}>
                {busy ? <IconRefresh size={16} aria-hidden className="ab-spin" /> : <IconPlay size={16} aria-hidden />}
                <span className="ab-btn-label">{busy ? 'Loading…' : 'Play'}</span>
              </button>
            )}
            {audio && current && playing && <span className="ab-eq" role="img" aria-label="Playing"><i /><i /><i /></span>}
          </span>
          <button className="ghost" aria-pressed={reading} aria-label={`${reading ? 'Hide' : 'Read'} the text of ${chapter.label}`} onClick={onRead}>
            <IconDocuments size={16} aria-hidden /><span className="ab-btn-label">{reading ? 'Hide' : 'Text'}</span>
          </button>
        </span>
      </div>
      {current && <AudioPlayer onClose={close} />}
      {error && <p className="error">{error}</p>}
      {reading && <Reader key={`${pdf}:${chapter.number}:${version}`} pdf={pdf} chapter={chapter} onClose={onRead} />}
    </li>
  )
}

function Book({ pdf, readNow, reveal, voices, samples, kept, voicesLoaded, job, reloadJob, onBack, onDelete }: {
  pdf: string
  /** What the suite keeps of this tool's work: the chapters' audio once a render has handed it over. */
  kept: Kept[]
  /** Just uploaded: start reading it as soon as it is open, if nothing else is running. */
  readNow: boolean
  /** The docked player asked to be shown where it is playing: bring that chapter into view once the chapters are drawn. */
  reveal: Reveal | null
  voices: Voice[]
  /** The voice samples made so far, for the Voices card under the chapters. */
  samples: AudioEntry[]
  voicesLoaded: boolean
  job: BookJob | null
  reloadJob: () => Promise<void>
  onBack: () => void
  /** Ask to delete this book; the page knows its upload and its audio. */
  onDelete: (title: string) => void
}) {
  // Planning a long book from its cache takes a moment, so this is not polled: it is read when the
  // book is opened, when a reading of it finishes, and as each chapter of a render of it is made.
  const overview = usePoll(() => call<Overview>('audiobook__preview_book', { pdf }), 3_600_000)
  const [picked, setPicked] = useState<Set<number> | null>(null)
  const [reading, setReading] = useState<number | null>(null)
  // Bumped when corrections are saved, so the open chapter's text is read again with them applied.
  const [version, setVersion] = useState(0)
  const [voice, setVoice] = useState('')
  const [speed, setSpeed] = useState(0.95)
  const [m4b, setM4b] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  // Folded to a line until asked for, and folded again by itself once a render has started: the job's own card
  // shows the progress, and the card is only needed to choose a voice and a speed.
  const [renderShown, setRenderShown] = useState(false)

  const running = job?.state === 'running'
  const data = useMemo(() => (overview.data ? withKept(overview.data, kept) : null), [overview.data, kept])

  const revealed = useRef<Reveal | null>(null)
  useEffect(() => {
    if (!reveal || reveal === revealed.current || !data?.analysed) return
    revealed.current = reveal
    document.getElementById(`ab-ch-${reveal.chapter}`)?.scrollIntoView({ block: 'center' })
  }, [reveal, data?.analysed])

  // A job names the path as the tool resolved it, which is not always what was typed (~, a relative
  // path, a link): compare against the tool's own spelling. And only a read this page saw running
  // counts as news -- one that finished before the book was opened is already in what was just loaded.
  const mine = data?.pdf ?? pdf
  const sawRunning = useRef('')
  useEffect(() => {
    if (!job || job.kind !== 'analyse' || job.target !== mine) return
    if (job.state === 'running') sawRunning.current = job.id
    else if (job.id === sawRunning.current) {
      sawRunning.current = ''
      void overview.reload()
    }
  }, [job?.id, job?.state, mine])
  // A render of this book: each chapter it finishes gets its play button.
  const made = job && job.kind === 'render' && job.target === mine ? `${job.id}:${job.outputs.length}:${job.state}` : ''
  useEffect(() => { if (made) void overview.reload() }, [made])

  const start = async (tool: string, args: Record<string, unknown>): Promise<boolean> => {
    setBusy(true)
    setError('')
    try {
      const started = await call<BookJob>(tool, args)
      await reloadJob()
      // A cached book can be read before the first poll sees it running.
      if (started.kind === 'analyse' && started.state !== 'running') await overview.reload()
      return true
    } catch (e) {
      setError(message(e))
      return false
    } finally {
      setBusy(false)
    }
  }

  // Uploaded a moment ago: read it now. Once only, and not over another job (one at a time).
  const autoRead = useRef(readNow)
  useEffect(() => {
    if (!autoRead.current || !data || data.analysed || running) return
    autoRead.current = false
    void start('audiobook__start_analysis', { pdf })
  }, [data?.analysed, running])

  const chapters = data?.chapters ?? []
  // Until you tick something, the chapters still to render: a finished chapter is not offered again by itself.
  const chosen = picked ?? unrendered(chapters)
  const cloned = voices.filter((v) => v.kind === 'cloned')
  const voiceName = voice || cloned[0]?.name || voices[0]?.name || ''

  const toggle = (n: number) => {
    const next = new Set(chosen)
    if (next.has(n)) next.delete(n)
    else next.add(n)
    setPicked(next)
  }

  const everything = chosen.size === chapters.length
  const render = async () => {
    const started = await start('audiobook__start_render', {
      pdf, voice: voiceName, speed, m4b,
      ...(everything ? {} : { chapters: toSelection([...chosen].sort((a, b) => a - b)) }),
    })
    if (started) setRenderShown(false)
  }
  const canRender = !(busy || running || chosen.size === 0 || !voiceName)
  const rendered = chapters.filter((c) => c.audio?.length).length
  const finished = rendered === chapters.length && chapters.length > 0
  const buttonLabel = renderLabel(chosen.size, chapters.length, rendered)

  const picks = data?.analysed ? chapters.filter((c) => chosen.has(c.number)) : []
  const words = picks.reduce((n, c) => n + c.words, 0)
  const allWords = chapters.reduce((n, c) => n + c.words, 0)
  const longest = chapters.reduce((n, c) => Math.max(n, c.words), 0)
  const times = data?.analysed ? selectionTimes(data, chosen) : null
  const skipped = Object.entries(data?.skipped ?? {})
  const left = skipped.reduce((n, [, count]) => n + count, 0)
  const others = data?.other_audio ?? []
  const whole = others.filter((f) => f.name.endsWith('.m4b'))
  const older = others.filter((f) => !f.name.endsWith('.m4b'))
  const title = data?.title ?? fileName(pdf)
  const readingThis = running && job?.kind === 'analyse' && job.target === mine

  const heading = (
    <header className="ab-bookhead">
      <span className="navtile" style={style({ '--tile': toolColor('audiobook') })}><IconAudiobooks size={20} strokeWidth={2} aria-hidden /></span>
      <div className="ab-booktitle">
        <h2>{title}</h2>
        <p className="ab-facts muted">
          {data?.author && <span>{data.author}</span>}
          {data?.analysed && <span>{chapters.length} chapters</span>}
          {data?.analysed && data.speech && <span>{data.speech} of speech</span>}
          {data?.analysed && !!data.citations_removed && <span>{data.citations_removed} citations removed</span>}
        </p>
      </div>
      <button className="ghost ab-delete" onClick={() => onDelete(title)}>
        <IconTrash size={16} aria-hidden />Delete…
      </button>
    </header>
  )

  return (
    <section className="ab-book" aria-label={title}>
      <div className="ab-bookbar">
        <button className="ghost ab-back" onClick={onBack}><IconBack size={16} aria-hidden />All books</button>
      </div>
      {heading}
      {overview.error && <p className="ab-detail ab-tone-bad" role="alert"><IconFail size={16} aria-hidden /><span>{overview.error}</span></p>}
      {!data && !overview.error && (
        <div className="ab-figs" aria-busy="true" aria-label="Reading the book's plan">
          {[0, 1, 2, 3].map((i) => <div key={i} className="card stat ab-stat"><div className="skeleton ab-skel-stat" /></div>)}
        </div>
      )}

      {data && !data.analysed && (
        <div className="card ab-unread">
          <span className="ab-unread-icon"><IconDocuments size={22} strokeWidth={1.8} aria-hidden /></span>
          <div className="stack">
            {readingThis ? (
              <p>Reading the book to find its chapters. They show here when it is done, to choose which to render.</p>
            ) : (
              <>
                <p>
                  This PDF has not been read yet. Reading finds its chapters, so you can choose which to render: about 2–4 seconds a
                  page, so a few minutes for a book, and much longer for a scan.
                </p>
                <div className="row">
                  <button className="primary" disabled={busy || running} onClick={() => void start('audiobook__start_analysis', { pdf })}>
                    <IconZap size={16} aria-hidden />Read this book
                  </button>
                  {running && <span className="muted">Another job is running — one at a time.</span>}
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {data?.analysed && times && (
        <>
          <div className="ab-figs stagger">
            <Fig index={0} label="Chapters" count={chosen.size} suffix={`of ${chapters.length}`} foot={everything ? 'all will be rendered' : 'chosen to render'} />
            <Fig index={1} label="Words" count={words} foot={everything ? 'in the whole book' : `of ${allWords.toLocaleString()} in all`} />
            <Fig index={2} label="Speech" foot={times.approx ? `about · the whole book is ${data.speech}` : 'the whole book'}><Duration text={times.speech} /></Fig>
            <Fig index={3} label="To render" foot="estimated, on this computer"><Duration text={times.render} /></Fig>
          </div>

          <div className="ab-main">
            <div className="card ab-chapters">
              <CardHead
                icon={IconAudiobooks}
                tool="audiobook"
                title="Chapters"
                sub={finished
                  ? 'Every chapter is rendered: play one here, or tick one to render it again.'
                  : rendered
                    ? `${rendered} of ${chapters.length} rendered: play one here. The rest are ticked to render.`
                    : 'Tick the chapters to render. Bars are words; times are speech.'}
              >
                <button className="ghost" onClick={() => setPicked(everything ? new Set() : new Set(chapters.map((c) => c.number)))}>{everything ? 'Clear all' : 'Select all'}</button>
              </CardHead>
              <ul className="ab-chlist">
                {chapters.map((c) => (
                  <ChapterRow
                    key={c.number}
                    pdf={pdf}
                    version={version}
                    chapter={c}
                    chapters={chapters}
                    chosen={chosen.has(c.number)}
                    longest={longest}
                    book={title}
                    reading={reading === c.number}
                    onToggle={() => toggle(c.number)}
                    onRead={() => setReading(reading === c.number ? null : c.number)}
                  />
                ))}
              </ul>
              <div className="ab-chart-foot">
                <p className="small muted" role="status">
                  {chosen.size === 0
                    ? finished ? 'Every chapter has audio. Tick one to render it again.' : 'No chapter chosen, so there is nothing to render.'
                    : `${chosen.size} of ${chapters.length} chosen · ${words.toLocaleString()} words${times.speech ? ` · ${times.approx ? 'about ' : ''}${times.speech} of speech` : ''}`}
                </p>
              </div>
            </div>

            <div className={`card ab-render ${renderShown ? '' : 'is-folded'}`}>
              <CardHead
                icon={IconZap}
                tool="audiobook"
                title="Render"
                sub={renderShown
                  ? `${everything ? 'The whole book' : `${chosen.size} of ${chapters.length} chapters`}${times.speech ? `, ${times.approx ? 'about ' : ''}${times.speech} of speech` : ''}${times.render ? `; about ${times.render} to render on this computer` : ''}`
                  : `${buttonLabel} · ${voiceName || 'no voice'}, speed ${speed}${running ? ' · another job is running' : ''}`}
              >
                <button className="ghost ab-fold" aria-expanded={renderShown} aria-controls="ab-render-body" onClick={() => setRenderShown(!renderShown)}>
                  {renderShown ? 'Hide' : 'Show'}<IconChevron size={16} aria-hidden className="ab-fold-icon" />
                </button>
              </CardHead>
              <div id="ab-render-body" hidden={!renderShown}>
                <div className="stack">
                  <label className="ab-field">
                    <span>Voice</span>
                    <select value={voiceName} onChange={(e) => setVoice(e.target.value)} aria-label="Voice">
                      {cloned.length > 0 && <optgroup label="Your voices">{cloned.map((v) => <option key={v.name} value={v.name}>{v.name}</option>)}</optgroup>}
                      <optgroup label="Built in">{voices.filter((v) => v.kind === 'preset').map((v) => <option key={v.name} value={v.name}>{v.name}</option>)}</optgroup>
                    </select>
                  </label>
                  <div className="ab-field">
                    <span>Speed</span>
                    <div className="ab-speed">
                      <input type="range" min={0.5} max={2} step={0.05} value={Number.isFinite(speed) ? speed : 0.95} onChange={(e) => setSpeed(Number(e.target.value))} aria-label="Speed, slider" />
                      <input type="number" min={0.5} max={2} step={0.05} value={speed} onChange={(e) => setSpeed(Number(e.target.value))} aria-label="Speed" />
                    </div>
                  </div>
                  <label className="check ab-m4b">
                    <input type="checkbox" checked={m4b} onChange={(e) => setM4b(e.target.checked)} />
                    Also one .m4b file
                  </label>
                  <button className="primary ab-render-go" disabled={!canRender} onClick={() => void render()}>
                    <IconZap size={16} aria-hidden />{buttonLabel}
                  </button>
                </div>
                <p className="hint">
                  Hours of work for a whole book, and nothing is lost if it stops: every sentence spoken is kept, so starting it again
                  carries on. A different speed re-encodes in seconds.{running && ' Another job is running — one at a time.'}
                </p>
              </div>
              {/* Outside the fold: a refusal must show even while the card is folded (the phone's Render bar starts one too). */}
              {error && <p className="error">{error}</p>}
            </div>

            {others.length > 0 && (
              <div className="card ab-listen">
                <CardHead icon={IconAudiobooks} tool="audiobook" title="Listen" sub="The book's other audio." />
                {whole.length > 0 && (
                  <div className="ab-files">
                    {whole.map((f) => <AudioFile key={`${audioKey(f)}:${f.modified}`} audio={f} label={`The whole book · ${f.name}`} />)}
                  </div>
                )}
                {older.length > 0 && (
                  <details className="ab-listen-more">
                    <summary>From an earlier reading ({older.length} file{older.length === 1 ? '' : 's'})</summary>
                    <p className="hint">Made when this book's chapters were found differently. Rendering it again makes files for the chapters above.</p>
                    <div className="ab-files">
                      {older.map((f) => <AudioFile key={`${audioKey(f)}:${f.modified}`} audio={f} />)}
                    </div>
                  </details>
                )}
              </div>
            )}
          </div>

          {/* Under the chapters, the width of the page: the voices are chosen for a book, so they live with it. */}
          <Voices voices={voices} samples={samples} loaded={voicesLoaded} running={running} reloadJob={reloadJob} />

          <div className="grid-2 ab-pair">
            {skipped.length > 0 && (
              <ChartCard
                title="What was left out"
                sub={`${left.toLocaleString()} pieces of the PDF that are not read aloud, by reason.`}
                table={(
                  <table>
                    <thead><tr><th>Reason</th><th className="num">Left out</th></tr></thead>
                    <tbody>{skipped.map(([reason, n]) => <tr key={reason}><td>{reason}</td><td className="num">{n.toLocaleString()}</td></tr>)}</tbody>
                  </table>
                )}
              >
                <HBars
                  label="What was left out of the reading, by reason"
                  color={toolColor('audiobook')}
                  items={skipped.map(([reason, n]) => ({ key: reason, label: reason, value: n, display: n.toLocaleString() }))}
                />
              </ChartCard>
            )}
            <Corrections pdf={pdf} onSaved={() => { setVersion((v) => v + 1); void overview.reload() }} />
          </div>

          <div className="ab-dock" role="group" aria-label="Render the chosen chapters">
            <span className="ab-dock-text">
              <strong>{everything ? 'All chapters' : `${chosen.size} of ${chapters.length} chapters`}</strong>
              <span className="muted small">
                {running ? 'Another job is running' : `${times.speech ? `${times.approx ? 'about ' : ''}${times.speech} · ` : ''}${voiceName || 'no voice'}`}
              </span>
            </span>
            <button className="primary" disabled={!canRender} onClick={() => void render()}><IconZap size={16} aria-hidden />Render</button>
          </div>
        </>
      )}
      {error && !data?.analysed && <p className="error">{error}</p>}
    </section>
  )
}

// ---------------------------------------------------------------------------

function Voices({ voices, samples, loaded, running, reloadJob }: {
  voices: Voice[]
  /** What "Hear a sample" made, newest first. */
  samples: AudioEntry[]
  loaded: boolean
  running: boolean
  reloadJob: () => Promise<void>
}) {
  const [name, setName] = useState('')
  const [clip, setClip] = useState<{ name: string; path: string } | null>(null)
  const [consent, setConsent] = useState('')
  const [adding, setAdding] = useState(false)
  const [uploading, setUploading] = useState<{ name: string; fraction: number } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  // Folded by default, so the books come first; opened or folded, it stays so in this browser.
  const [shown, setShown] = useState(() => store.read(VOICES_OPEN) === '1')
  const show = (open: boolean) => { setShown(open); store.write(VOICES_OPEN, open ? '1' : '0') }

  const upload = async ([file]: File[]) => {
    if (!file) return
    setError('')
    setUploading({ name: file.name, fraction: 0 })
    try {
      setClip(await uploadVoice(file, (fraction) => setUploading({ name: file.name, fraction })))
    } catch (e) {
      setError(message(e))
    } finally {
      setUploading(null)
    }
  }

  const start = async (tool: string, args: Record<string, unknown>) => {
    setBusy(true)
    setError('')
    try {
      await call(tool, args)
      await reloadJob()
    } catch (e) {
      setError(message(e))
    } finally {
      setBusy(false)
    }
  }

  const cloned = voices.filter((v) => v.kind === 'cloned')
  const presets = voices.filter((v) => v.kind === 'preset')
  const missing = [!name.trim() && 'a name', !clip && 'a recording', !consent.trim() && 'who agreed'].filter(Boolean) as string[]
  const steps: { done: boolean }[] = [{ done: !!name.trim() }, { done: !!clip }, { done: !!consent.trim() }]

  return (
    <DropZone
      accepts={(f) => isAudio(f.name)}
      label="Drop a recording to clone"
      onRefuse={(names) => setError(`Not uploaded — a voice is cloned from an audio recording (${AUDIO_EXTS.join(' ')}): ${names.join(', ')}`)}
      onFiles={(files) => { show(true); setAdding(true); void upload(files) }}
      disabled={uploading !== null}
    >
      <div className={`card ab-voices-card ${shown ? '' : 'is-folded'}`}>
        <CardHead
          icon={IconMeetings}
          tool="audiobook"
          title="Voices"
          sub={shown || !loaded ? 'Cloned from a short recording, or built in.'
            : cloned.length ? `${cloned.length} of your own: ${cloned.map((v) => v.name).join(', ')}` : 'None of your own yet.'}
        >
          <button className="ghost ab-fold" aria-expanded={shown} aria-controls="ab-voices-body" onClick={() => show(!shown)}>
            {shown ? 'Hide' : 'Show'}<IconChevron size={16} aria-hidden className="ab-fold-icon" />
          </button>
        </CardHead>
        <div id="ab-voices-body" hidden={!shown}>
        {!loaded && <div className="skeleton ab-skel" aria-hidden />}
        {loaded && cloned.length === 0 && <p className="muted">No cloned voices yet.</p>}
        <ul className="ab-voices stagger">
          {cloned.map((v, i) => (
            <li key={v.name} style={style({ '--i': i })}>
              <div className="ab-voice">
              <span className="ab-avatar" aria-hidden>{v.name.charAt(0).toUpperCase()}</span>
              <div className="ab-voice-main">
                <strong>{v.name}</strong>
                {v.similarity != null && (
                  <div className="ab-meter">
                    <div className="bar" role="meter" aria-label={`${v.name}: similarity to the recording`} aria-valuemin={0} aria-valuemax={1} aria-valuenow={v.similarity} aria-valuetext={`similarity ${v.similarity.toFixed(2)}`}>
                      <div style={{ width: `${Math.max(0, Math.min(1, v.similarity)) * 100}%`, background: toolColor('audiobook') }} />
                    </div>
                    <span className="small muted">similarity {v.similarity.toFixed(2)}</span>
                  </div>
                )}
                {v.consent && <p className="small muted ab-consent">{v.consent}</p>}
              </div>
              <button className="ab-sample" disabled={busy || running} onClick={() => void start('audiobook__start_voice_sample', { voice: v.name })}>
                <IconPlay size={16} aria-hidden />Hear a sample
              </button>
              </div>
            </li>
          ))}
        </ul>

        {presets.length > 0 && (
          <details className="ab-presets">
            <summary>Built-in voices ({presets.length})</summary>
            <p className="hint">Built-in voices work by name too:</p>
            <ul className="ab-chips">{presets.map((v) => <li key={v.name}><span className="badge">{v.name}</span></li>)}</ul>
          </details>
        )}

        {samples.length > 0 && (
          <details className="ab-presets">
            <summary>Samples ({samples.length})</summary>
            <div className="ab-files">
              {samples.map((f) => <AudioFile key={`${audioKey(f)}:${f.modified}`} audio={f} />)}
            </div>
          </details>
        )}

        <details className="ab-add" open={adding} onToggle={(e) => setAdding(e.currentTarget.open)}>
          <summary>Add a voice</summary>
          <ol className="ab-steps">
            <li className={steps[0]!.done ? 'done' : ''}>
              <span className="ab-step-n">{steps[0]!.done ? <IconCheck size={14} strokeWidth={3} aria-hidden /> : 1}</span>
              <div className="ab-step-body">
                <strong>Name it</strong>
                <input value={name} onChange={(e) => setName(e.target.value.toLowerCase())} placeholder="A name — lowercase, e.g. tina" aria-label="Voice name" />
              </div>
            </li>
            <li className={steps[1]!.done ? 'done' : ''}>
              <span className="ab-step-n">{steps[1]!.done ? <IconCheck size={14} strokeWidth={3} aria-hidden /> : 2}</span>
              <div className="ab-step-body">
                <strong>Add a recording</strong>
                <p className="hint">
                  About 30 seconds of one person speaking clearly, with no music or background noise. A longer recording is searched for
                  its best 30 seconds, which takes a minute or more.
                </p>
                <div className="row">
                  <PickFiles label="Upload a recording…" icon={<IconUpload size={16} aria-hidden />} accept={AUDIO_EXTS.join(',') + ',audio/*'} disabled={uploading !== null} onPick={(f) => void upload(f)} />
                  {clip ? <span className="ab-clip"><IconCheck size={14} strokeWidth={2.6} aria-hidden />{clip.name}</span> : <span className="muted small">or drop it on this card</span>}
                </div>
                {uploading && <UploadProgress name={uploading.name} fraction={uploading.fraction} />}
              </div>
            </li>
            <li className={steps[2]!.done ? 'done' : ''}>
              <span className="ab-step-n">{steps[2]!.done ? <IconCheck size={14} strokeWidth={3} aria-hidden /> : 3}</span>
              <div className="ab-step-body">
                <strong>Say who agreed</strong>
                <input
                  value={consent}
                  onChange={(e) => setConsent(e.target.value)}
                  placeholder='Whose voice, and that they agreed — e.g. "my own voice"'
                  aria-label="Consent"
                />
                <p className="hint">Only clone a voice you own or have the speaker’s permission to use. What you write here is kept with the voice.</p>
              </div>
            </li>
          </ol>
          <div className="row ab-clone">
            <button
              className="primary"
              disabled={busy || running || !name.trim() || !clip || !consent.trim()}
              onClick={() => void start('audiobook__start_voice_clone', { name: name.trim(), recording: clip?.path, consent: consent.trim() })}
            >
              <IconMeetings size={16} aria-hidden />Clone this voice
            </button>
            {missing.length > 0 && <span className="muted small">Still needed: {missing.join(', ')}.</span>}
            {missing.length === 0 && running && <span className="muted small">Another job is running — one at a time.</span>}
          </div>
        </details>
        </div>
        {error && <p className="error">{error}</p>}
      </div>
    </DropZone>
  )
}

// ---------------------------------------------------------------------------

/** Each uploaded book's plan (title, author, chapters), read once per change rather than polled: planning a
 *  long book takes a moment, and the library only needs it when a book arrives, goes, or is read. */
function useOverviews(paths: string[], refresh: string): Record<string, Overview | undefined> {
  const [found, setFound] = useState<Record<string, Overview>>({})
  const key = paths.join('\n')
  useEffect(() => {
    let live = true
    void (async () => {
      for (const pdf of paths) {
        try {
          const overview = await call<Overview>('audiobook__preview_book', { pdf })
          if (live) setFound((old) => ({ ...old, [pdf]: overview }))
        } catch {
          // The card shows the file's name instead, and opening the book shows what went wrong.
        }
      }
    })()
    return () => { live = false }
  }, [key, refresh])
  return found
}

export function Audiobooks() {
  // The book open, by its PDF's path; none is the library. Back from a book goes to the library (useLayer.ts).
  const [book, setBook] = useState('')
  useLayer('book', book || null, (to) => setBook(to ?? ''))
  const [readNow, setReadNow] = useState(false)
  const [reveal, setReveal] = useState<Reveal | null>(null)
  const [deleting, setDeleting] = useState<Doomed | null>(null)
  const [changed, setChanged] = useState(0)
  const uploads = usePoll(getUploads, 30000)
  const status = usePoll(() => call<{ job: BookJob | null }>('audiobook__job_status'), 3000)
  const voiceList = usePoll(() => call<{ voices: Voice[] }>('audiobook__list_voices'), 30000)
  // Finished audio is the suite's to keep (assistant/collect.py): the tool lists only what it has not yet handed over.
  const finished = usePoll(() => call<{ audiobooks: AudioBook[] }>('audiobook__list_audiobooks'), 30000)
  const keptPoll = usePoll(() => getKept('audiobook'), 30000)
  const job = status.data?.job ?? null

  // Chapters finish one by one during a render, so the audio follows the job; and the server says when it has taken
  // something in, which is a moment after the tool made it.
  const { events } = useAppState()
  const taken = useMemo(() => events.filter((e) => e.type === 'records_changed' && e.tool === 'audiobook').at(-1)?.seq ?? 0, [events])
  const progressKey = job ? `${job.id}:${job.state}:${job.outputs.length}` : ''
  useEffect(() => { void finished.reload() }, [progressKey, changed, taken])
  useEffect(() => { void keptPoll.reload() }, [progressKey, changed, taken])
  const justFinished = job?.state === 'done' ? job.id : ''
  useEffect(() => { if (justFinished) void voiceList.reload() }, [justFinished])
  const kept = useMemo(() => keptPoll.data?.records ?? [], [keptPoll.data])
  const read = useOverviews((uploads.data?.books ?? []).map((b) => b.path), `${justFinished}:${changed}`)
  const overviews = useMemo(
    () => Object.fromEntries(Object.entries(read).map(([path, o]) => [path, o && withKept(o, kept)])),
    [read, kept],
  )

  // A book is its upload and its audio, matched by name, as the output folder is named for the PDF.
  const audiobooks = useMemo(() => withKeptBooks(finished.data?.audiobooks ?? [], kept), [finished.data, kept])
  const shelves: Shelf[] = [
    ...(uploads.data?.books ?? []).map((u) => ({ stem: stem(u.name), upload: u, audio: audiobooks.find((b) => b.book === stem(u.name)) ?? null })),
    ...audiobooks.filter((b) => !uploads.data?.books.some((u) => stem(u.name) === b.book)).map((b) => ({ stem: b.book, upload: null, audio: b })),
  ]
  const samples = useMemo(
    () => withKeptSamples(finished.data?.audiobooks.find((b) => b.book === 'voices')?.files ?? [], kept),
    [finished.data, kept],
  )

  const open = (path: string, read = false) => {
    setBook(path)
    setReadNow(read)
    window.scrollTo({ top: 0 })
  }
  const close = () => { setBook(''); window.scrollTo({ top: 0 }) }

  // The docked player, tapped from anywhere: open the book it is playing and bring that chapter into view. A request
  // made before this page existed is waiting; one made while it is open arrives at once.
  const openLatest = useRef(open)
  openLatest.current = open
  useEffect(() => {
    const answer = () => {
      const request = takeRequest()
      if (!request) return
      openLatest.current(request.book)
      setReveal({ chapter: request.chapter })
    }
    answer()
    return onRequest(answer)
  }, [])
  const doomedFor = (name: string, title: string): Doomed => {
    const shelf = shelves.find((s) => s.stem === name)
    const ids = kept.filter((r) => goesWithBook(r, name)).map((r) => r.id)
    return { stem: name, title, upload: shelf?.upload ?? null, audio: shelf?.audio?.files.length ?? 0, kept: ids }
  }
  const titleFor = (path: string) => {
    const shelf = shelves.find((s) => s.stem === stem(path))
    return (shelf?.upload && overviews[shelf.upload.path]?.title) || shelf?.audio?.title || undefined
  }
  // The job's book, unless it is the one open: what "Open the book" on the job card opens.
  const jobBook = job && (job.kind === 'analyse' || job.kind === 'render') && stem(job.target) !== stem(book)
    && uploads.data?.books.some((u) => u.path === job.target) ? job.target : ''

  return (
    <div className="panel ab-page" style={style({ '--ab': toolColor('audiobook') })}>
      <JobCard job={job} name={job ? titleFor(job.target) : undefined} samples={samples} reload={status.reload} openBook={jobBook ? () => open(jobBook) : undefined} />
      {book ? (
        <Book
          key={book}
          pdf={book}
          readNow={readNow}
          reveal={reveal}
          voices={voiceList.data?.voices ?? []}
          samples={samples}
          kept={kept}
          voicesLoaded={voiceList.data !== null}
          job={job}
          reloadJob={status.reload}
          onBack={close}
          onDelete={(title) => setDeleting(doomedFor(stem(book), title))}
        />
      ) : (
        <Library shelves={shelves} overviews={overviews} job={job} uploads={uploads} onOpen={open} onDelete={(name, title) => setDeleting(doomedFor(name, title))} />
      )}
      {(status.error || voiceList.error || finished.error) && <p className="error">{status.error || voiceList.error || finished.error}</p>}
      {deleting !== null && (
        <DeleteBook
          key={deleting.stem}
          book={deleting}
          onCancel={() => setDeleting(null)}
          onChanged={() => { setChanged((n) => n + 1); void uploads.reload() }}
          onDone={() => {
            if (book && stem(book) === deleting.stem) setBook('')
            setDeleting(null)
          }}
        />
      )}
    </div>
  )
}
