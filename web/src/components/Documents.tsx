// Markdown to Google Docs by button: upload files or a folder, choose its name and look, build it, and keep the
// documents it made in order. The same docu-ai tools the model calls in chat, with no model.
//
// docu-ai reads only a folder's top level, so that is all an upload sends; anything deeper or
// not markdown is listed as skipped, never uploaded to silently do nothing.
//
// Every build is named for its upload unless you say otherwise. A single file used to be named for its first
// heading, which for a CV or a letter is the sender: on 2026-10-31, seven of the ten documents in Drive were all
// called "Philip Baah Afriyie". Rename is how the ones already built get their names.

import { useCallback, useEffect, useId, useRef, useState, type CSSProperties } from 'react'
import { deleteUpload, getUploads, isMarkdown, splitDocs, uploadDocs, type UploadedDocs } from '../api'
import { call } from '../call'
import { HBars } from '../charts/HBars'
import { toolColor } from '../charts/palette'
import { useAppState } from '../state'
import { CardHead } from '../ui/CardHead'
import { ConfirmDelete } from '../ui/ConfirmDelete'
import { DropZone } from '../ui/DropZone'
import { Empty } from '../ui/Empty'
import { IconChevron, IconDocuments, IconDownload, IconExternal, IconFolder, IconRefresh, IconTrash, IconUpload } from '../ui/icons'
import { ago } from '../ui/time'
import { usePoll } from '../usePoll'
import { BinButton, Builds, type BuiltDoc } from './builtDoc'
import { lookFor, madeLine, sharingNames, type Look } from './documentText'
import { PickFiles, UploadProgress } from './Upload'
import '../styles/panels/documents.css'

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))
const style = (vars: Record<string, string | number>) => vars as CSSProperties

interface Preview {
  single: boolean
  chapters: { title: string; file: string; blocks: Record<string, number> }[]
}

const blockCount = (blocks: Record<string, number>) => Object.values(blocks).reduce((n, v) => n + v, 0)

// docu-ai's three looks, in the words a person would use. Only one file can take a look: a CV or a letter is one file.
const LOOKS: [Look, string][] = [['technical', 'Document'], ['resume', 'CV'], ['letter', 'Letter']]
const LOOK_LABEL: Record<Look, string> = { technical: 'document', resume: 'CV', letter: 'letter' }
const PAGE_LIMITS: [number, string][] = [[0, 'No limit'], [1, '1 page'], [2, '2 pages']]

// ---- markdown waiting to be built -------------------------------------------------------------------

function UploadRow({ docs, index, startOpen, onBuilt, onDeleted }: {
  docs: UploadedDocs & { at: number }
  index: number
  startOpen: boolean
  onBuilt: () => void
  onDeleted: () => void
}) {
  const single = docs.files.length === 1
  const [open, setOpen] = useState(startOpen)
  const [name, setName] = useState(docs.name)
  const [look, setLook] = useState<Look>(() => lookFor(docs.name))
  const [maxPages, setMaxPages] = useState(0)
  const [preview, setPreview] = useState<Preview | null>(null)
  // Newest first: every Doc built from this upload while the page was open, so an earlier one can be binned.
  const [builds, setBuilds] = useState<BuiltDoc[]>([])
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [asking, setAsking] = useState(false)
  const [removing, setRemoving] = useState(false)
  const [removeError, setRemoveError] = useState('')
  const bodyId = useId()
  const labelId = useId()
  // The same upload sent again keeps its row, so it is opened here rather than only when the row first appears.
  useEffect(() => { if (startOpen) setOpen(true) }, [startOpen])

  const remove = async () => {
    setRemoving(true)
    setRemoveError('')
    try {
      await deleteUpload(docs.id)
      setAsking(false)
      onDeleted()
    } catch (e) {
      setRemoveError(message(e))
    } finally {
      setRemoving(false)
    }
  }

  const run = async (what: string, work: () => Promise<void>) => {
    setBusy(what)
    setError('')
    try {
      await work()
    } catch (e) {
      setError(message(e))
    } finally {
      setBusy('')
    }
  }

  const build = () => run('build', async () => {
    const result = await call<Omit<BuiltDoc, 'at' | 'limit'>>('docu_ai__build', {
      path: docs.path,
      title: name.trim() || docs.name,
      ...(single ? { theme: look } : {}),
      ...(single && maxPages ? { maxPages } : {}),
    })
    setBuilds((b) => [{ ...result, at: Date.now(), limit: single ? maxPages : 0 }, ...b])
    onBuilt()
  })

  const latest = builds[0]
  const facts = single
    ? `1 file · ${LOOK_LABEL[look]}`
    : `${docs.files.length} files · a tab each, with a contents page`

  return (
    <li className="doc-up" style={style({ '--i': index })}>
      <div className="doc-up-row">
        <span className="navtile doc-up-icon" style={style({ '--tile': toolColor('docu-ai') })} aria-hidden>
          <IconDocuments size={18} strokeWidth={2} />
        </span>
        <span className="doc-up-main">
          <strong className="doc-up-title">{docs.name}</strong>
          <span className="small muted">{facts} · uploaded {ago(docs.at * 1000)}</span>
        </span>
        <button className="doc-up-toggle" aria-expanded={open} aria-controls={bodyId} onClick={() => setOpen(!open)}>
          {open ? 'Close' : 'Build…'}
          <IconChevron size={16} aria-hidden style={{ transform: open ? 'rotate(-90deg)' : 'rotate(90deg)' }} />
        </button>
      </div>

      <div id={bodyId} className="doc-up-body" hidden={!open}>
        <div className="doc-form">
          <label className="doc-field doc-field-name">
            <span className="doc-label">Name in Google Drive</span>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder={docs.name} />
          </label>
          {single && (
            <div className="doc-field">
              <span className="doc-label" id={`${labelId}-look`}>Look</span>
              <div className="seg" role="radiogroup" aria-labelledby={`${labelId}-look`}>
                {LOOKS.map(([value, label]) => (
                  <button key={value} role="radio" aria-checked={look === value} onClick={() => setLook(value)}>{label}</button>
                ))}
              </div>
            </div>
          )}
          {single && (
            <div className="doc-field">
              <span className="doc-label" id={`${labelId}-pages`}>Page limit</span>
              <div className="seg" role="radiogroup" aria-labelledby={`${labelId}-pages`}>
                {PAGE_LIMITS.map(([value, label]) => (
                  <button key={value} role="radio" aria-checked={maxPages === value} onClick={() => setMaxPages(value)}>{label}</button>
                ))}
              </div>
            </div>
          )}
        </div>
        {single && <p className="hint">{look === 'resume' ? 'CV: tight type, one or two packed pages.' : look === 'letter' ? 'Letter: larger type, with room between its parts.' : 'Document: a report or handbook style.'}{maxPages ? ` Going over ${maxPages} page${maxPages === 1 ? '' : 's'} is pointed out after the build.` : ''}</p>}

        <div className="row doc-actions">
          <button className="primary" disabled={busy !== ''} onClick={() => void build()}>
            <IconDocuments size={16} aria-hidden />{busy === 'build' ? 'Building the Doc…' : latest ? 'Build again' : 'Make a Google Doc'}
          </button>
          <button disabled={busy !== ''} onClick={() => void run('preview', async () => setPreview(await call<Preview>('docu_ai__preview', { path: docs.path })))}>
            {busy === 'preview' ? 'Reading…' : preview ? 'Read it again' : 'What will be built'}
          </button>
        </div>

        {preview && (
          <div className="batch-preview">
            {preview.chapters.length > 1 ? (
              <HBars
                label="Blocks per tab"
                color={toolColor('docu-ai')}
                items={preview.chapters.map((c) => ({
                  key: c.file,
                  label: c.title,
                  value: blockCount(c.blocks),
                  display: `${blockCount(c.blocks)}`,
                  sub: `${c.file}: ${Object.entries(c.blocks).map(([k, n]) => `${n} ${k}`).join(', ')}`,
                }))}
              />
            ) : (
              <ul className="chips">
                {preview.chapters[0] && Object.entries(preview.chapters[0].blocks).map(([kind, n]) => <li key={kind} className="badge">{n} {kind}</li>)}
              </ul>
            )}
            <p className="hint">
              {preview.chapters.length > 1
                ? 'A tab for each file, named for its first heading. Bars count its paragraphs, headings, lists, tables and code blocks.'
                : `“${preview.chapters[0]?.title ?? docs.name}”: its paragraphs, headings, lists, tables and code blocks.`}
            </p>
          </div>
        )}

        <Builds builds={builds} onBinned={onBuilt} />
        {error && <p className="error">{error}</p>}

        <div className="row doc-actions doc-actions-end">
          <button className="ghost" disabled={busy !== ''} onClick={() => { setRemoveError(''); setAsking(true) }}>
            <IconTrash size={14} aria-hidden />Delete this upload
          </button>
        </div>
      </div>
      {asking && (
        <ConfirmDelete
          title={`Delete “${docs.name}”?`}
          facts={[['Files', docs.files.join(', ')], ['Uploaded', ago(docs.at * 1000)]]}
          keeps="The markdown is removed from this computer. Google Docs already built from it are not touched."
          verb="Delete"
          busy={removing}
          error={removeError}
          onConfirm={() => void remove()}
          onCancel={() => setAsking(false)}
        />
      )}
    </li>
  )
}

// ---- documents already built on Google Drive --------------------------------------------------------

interface DriveDoc {
  documentId: string
  title: string
  url: string
  createdTime: string
  modifiedTime: string
}

interface ExportResult {
  filename: string
  data: string
  size: number
}

function downloadBase64(data: string, filename: string, mime: string) {
  const bytes = Uint8Array.from(atob(data), (c) => c.charCodeAt(0))
  const blob = new Blob([bytes], { type: mime })
  const href = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = href
  link.download = filename
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(href), 10_000)
}

function DriveDocRow({ doc, onTrashed, onRenamed }: {
  doc: DriveDoc
  onTrashed: () => void
  onRenamed: (title: string) => void
}) {
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [renaming, setRenaming] = useState(false)
  const [name, setName] = useState(doc.title)

  const download = async (format: 'pdf' | 'docx') => {
    setBusy(format)
    setError('')
    try {
      const result = await call<ExportResult>('docu_ai__export', { documentId: doc.documentId, format })
      const mime = format === 'pdf' ? 'application/pdf' : 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
      downloadBase64(result.data, result.filename, mime)
    } catch (e) {
      setError(message(e))
    } finally {
      setBusy('')
    }
  }

  const rename = async () => {
    const wanted = name.trim()
    if (!wanted || wanted === doc.title) { setRenaming(false); return }
    setBusy('rename')
    setError('')
    try {
      const result = await call<{ title: string }>('docu_ai__rename', { documentId: doc.documentId, name: wanted })
      onRenamed(result.title)
      setRenaming(false)
    } catch (e) {
      setError(message(e))
    } finally {
      setBusy('')
    }
  }

  return (
    <li className="drive-doc">
      <div className="drive-doc-main">
        {renaming ? (
          <form className="drive-rename" onSubmit={(e) => { e.preventDefault(); void rename() }}>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Escape') { setName(doc.title); setRenaming(false) } }}
              aria-label={`New name for “${doc.title}”`}
              autoFocus
            />
            <button type="submit" className="primary" disabled={busy !== '' || !name.trim()}>{busy === 'rename' ? 'Saving…' : 'Save'}</button>
            <button type="button" disabled={busy === 'rename'} onClick={() => { setName(doc.title); setRenaming(false) }}>Cancel</button>
          </form>
        ) : (
          <a href={doc.url} target="_blank" rel="noreferrer" className="drive-doc-title">
            {doc.title}
            <IconExternal size={13} aria-hidden />
          </a>
        )}
        <span className="muted small" title={`Made ${new Date(doc.createdTime).toLocaleString()} · last edited ${new Date(doc.modifiedTime).toLocaleString()}`}>
          {madeLine(doc.createdTime, doc.modifiedTime, ago)}
        </span>
      </div>
      {!renaming && (
        <div className="drive-doc-actions">
          <button disabled={busy !== ''} onClick={() => void download('pdf')} aria-label={`Download “${doc.title}” as PDF`}>
            <IconDownload size={14} aria-hidden />
            {busy === 'pdf' ? 'Exporting…' : 'PDF'}
          </button>
          <button disabled={busy !== ''} onClick={() => void download('docx')} aria-label={`Download “${doc.title}” as Word`}>
            <IconDownload size={14} aria-hidden />
            {busy === 'docx' ? 'Exporting…' : 'Word'}
          </button>
          <button disabled={busy !== ''} onClick={() => { setName(doc.title); setError(''); setRenaming(true) }} aria-label={`Rename “${doc.title}”`}>
            Rename
          </button>
          <BinButton doc={doc} label="Bin" onTrashed={onTrashed} onError={setError} />
        </div>
      )}
      {error && <p className="error small">{error}</p>}
    </li>
  )
}

interface ListPage {
  documents: DriveDoc[]
  nextPageToken?: string
}

const PAGE_SIZE = 10

function DriveDocuments({ version }: { version: number }) {
  const { tools } = useAppState()
  const hasList = tools.has('docu_ai__list')
  const [page, setPage] = useState<ListPage | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [tokenStack, setTokenStack] = useState<string[]>([])
  const mountRef = useRef(true)
  useEffect(() => () => { mountRef.current = false }, [])

  const load = useCallback(async (pageToken?: string) => {
    setLoading(true)
    setError('')
    try {
      const result = await call<ListPage>('docu_ai__list', { limit: PAGE_SIZE, ...(pageToken ? { pageToken } : {}) })
      if (mountRef.current) setPage(result)
    } catch (e) {
      if (mountRef.current) setError(message(e))
    } finally {
      if (mountRef.current) setLoading(false)
    }
  }, [])

  // A build or a bin elsewhere on the page changes the list: back to its first page, where a new one appears.
  useEffect(() => {
    if (!hasList) return
    setTokenStack([])
    void load()
  }, [hasList, load, version])

  if (!hasList) return null

  const pageNum = tokenStack.length + 1
  const hasNext = !!page?.nextPageToken
  const hasPrev = tokenStack.length > 0
  const shared = sharingNames((page?.documents ?? []).map((d) => d.title))

  const goNext = () => {
    if (!page?.nextPageToken) return
    setTokenStack((s) => [...s, page.nextPageToken!])
    void load(page.nextPageToken)
  }

  const goPrev = () => {
    if (tokenStack.length === 0) return
    const prev = [...tokenStack]
    prev.pop()
    const token = prev[prev.length - 1]
    setTokenStack(prev)
    void load(token)
  }

  const renamed = (documentId: string, title: string) =>
    setPage((p) => p && { ...p, documents: p.documents.map((d) => (d.documentId === documentId ? { ...d, title } : d)) })

  return (
    <section className="card" aria-label="Documents on Google Drive">
      <CardHead icon={IconDocuments} tool="docu-ai" title="Your documents" sub="CVs, cover letters and other documents built by docu-ai, on your Google Drive.">
        <button disabled={loading} onClick={() => { setTokenStack([]); void load() }}>
          <IconRefresh size={16} aria-hidden />
          Refresh
        </button>
      </CardHead>

      {page === null && !error ? (
        <div aria-busy="true">
          <ul className="drive-list">
            {Array.from({ length: 3 }, (_, i) => (
              <li key={i} className="drive-doc">
                <div className="drive-doc-main"><span className="skeleton" style={{ width: '60%', height: 18 }} /><span className="skeleton" style={{ width: 120, height: 14 }} /></div>
              </li>
            ))}
          </ul>
        </div>
      ) : page && page.documents.length === 0 && tokenStack.length === 0 ? (
        <Empty icon={IconDocuments} title="No documents yet">
          Build a markdown file into a Google Doc and it will appear here.
        </Empty>
      ) : (
        <>
          {shared > 1 && (
            <p className="hint drive-shared">
              {shared} of these share a name with another. Open one to see which it is, then Rename gives it a name of its own.
            </p>
          )}
          <ul className="drive-list stagger">
            {(page?.documents ?? []).map((d) => (
              <DriveDocRow
                key={d.documentId}
                doc={d}
                onTrashed={() => void load(tokenStack[tokenStack.length - 1])}
                onRenamed={(title) => renamed(d.documentId, title)}
              />
            ))}
          </ul>
          {(hasPrev || hasNext) && (
            <nav className="drive-pager" aria-label="Document pages">
              <button disabled={!hasPrev || loading} onClick={goPrev} aria-label="Previous page">
                <IconChevron size={16} style={{ transform: 'rotate(180deg)' }} aria-hidden />
                Prev
              </button>
              <span className="muted small">Page {pageNum}</span>
              <button disabled={!hasNext || loading} onClick={goNext} aria-label="Next page">
                Next
                <IconChevron size={16} aria-hidden />
              </button>
            </nav>
          )}
        </>
      )}
      {error && <p className="error">{error}</p>}
    </section>
  )
}

export function Documents() {
  const uploads = usePoll(getUploads, 30000)
  const [uploading, setUploading] = useState<{ name: string; fraction: number } | null>(null)
  const [skipped, setSkipped] = useState<string[]>([])
  const [error, setError] = useState('')
  // The upload just made opens by itself: there is nothing else to do with it but build it.
  const [justUploaded, setJustUploaded] = useState('')
  const [version, setVersion] = useState(0)

  const upload = async (picked: File[]) => {
    const { top, skipped: left, name } = splitDocs(picked)
    setSkipped(left)
    setError('')
    if (top.length === 0) {
      setError('Nothing to upload: docu-ai builds from the markdown (.md) files at the top of a folder.')
      return
    }
    setUploading({ name, fraction: 0 })
    try {
      const saved = await uploadDocs(top, name, (fraction) => setUploading({ name, fraction }))
      setJustUploaded(saved.path)
      await uploads.reload()
    } catch (e) {
      setError(message(e))
    } finally {
      setUploading(null)
    }
  }

  const batches = [...(uploads.data?.docs ?? [])].sort((a, b) => b.at - a.at)
  return (
    <div className="panel">
      <DropZone
        accepts={(f) => isMarkdown(f.name)}
        label="Drop markdown to upload"
        onRefuse={(names) => setError(`Not uploaded — docu-ai builds from markdown (.md): ${names.join(', ')}`)}
        onFiles={(files) => void upload(files)}
        disabled={uploading !== null}
      >
        <section className="card doc-uploads" aria-label="Markdown to build">
          <CardHead icon={IconDocuments} tool="docu-ai" title="Make a Google Doc" sub="Upload markdown, or drop it here. One file makes a Doc of one tab; a folder makes a tab per file, with a contents page.">
            <PickFiles label="Upload .md files…" icon={<IconUpload size={16} aria-hidden />} accept=".md,text/markdown" multiple disabled={uploading !== null} onPick={(f) => void upload(f)} className="primary" />
            <PickFiles label="Upload a folder…" icon={<IconFolder size={16} aria-hidden />} folder disabled={uploading !== null} onPick={(f) => void upload(f)} />
          </CardHead>
          {uploading && <UploadProgress name={uploading.name} fraction={uploading.fraction} />}
          {skipped.length > 0 && <p className="muted small">Not uploaded, because docu-ai would not use them: {skipped.join(', ')}</p>}
          {error && <p className="error">{error}</p>}
          {batches.length > 0 ? (
            <>
              <ul className="doc-up-list stagger">
                {batches.map((d, i) => (
                  <UploadRow key={d.path} docs={d} index={i} startOpen={d.path === justUploaded} onBuilt={() => setVersion((v) => v + 1)} onDeleted={() => void uploads.reload()} />
                ))}
              </ul>
              <p className="hint doc-order">A folder's tabs follow its file names, or the order its SUMMARY.md gives.</p>
            </>
          ) : uploads.data && (
            <Empty icon={IconDocuments} title="Nothing uploaded yet">Markdown you upload waits here, ready to build into a formatted Google Doc.</Empty>
          )}
        </section>
      </DropZone>

      <DriveDocuments version={version} />

      {uploads.error && <p className="error">{uploads.error}</p>}
    </div>
  )
}
