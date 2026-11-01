// The only module that talks to the server.
//
// The web app is its own program: it is served from its own port and reaches the backend
// across origins. ./start gives both programs the same random token, and the web app's own
// server writes it into this page as it serves it -- so normally nothing is typed. When the
// two are run separately with no shared token, the Connect screen asks for it instead.

const metaContent = (name: string) =>
  document.querySelector<HTMLMetaElement>(`meta[name="${name}"]`)?.content ?? ''

/**
 * Where the backend is. Decided in the browser, at run time, so one build serves every host:
 *  - VITE_API_URL, if a build was made for one place (development);
 *  - assistant-api-url meta tag: a full URL when the API is on a different host entirely
 *    (ngrok gives each tunnel its own hostname, so same-host-different-port does not apply);
 *  - on localhost, 127.0.0.1:8750, as ever;
 *  - on any other name (a tailnet address), the SAME host the page came from, at the port the web
 *    server was told the backend answers on. Same host means same site, which a login cookie
 *    will need; a different port is a different origin, which is why the backend lists origins.
 */
function apiUrl(): string {
  const built = import.meta.env.VITE_API_URL as string | undefined
  if (built) return built
  const full = metaContent('assistant-api-url')
  if (full) return full
  const { protocol, hostname } = location
  if (hostname === '127.0.0.1' || hostname === 'localhost' || hostname === '[::1]') {
    return `http://${hostname === '[::1]' ? 'localhost' : hostname}:8750`
  }
  return `${protocol}//${hostname}:${metaContent('assistant-api-port') || '8750'}`
}

export const API_URL = apiUrl().replace(/\/$/, '')

// ngrok's free tier shows an interstitial page to browser User-Agents. This header bypasses it.
// Harmless when not behind ngrok.
const NGROK_HEADER = { 'ngrok-skip-browser-warning': 'true' }

const TOKEN_KEY = 'assistant-token'

const fromPage = (doc: Document) => doc.querySelector<HTMLMetaElement>('meta[name="assistant-token"]')?.content ?? ''

function stored(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? ''
  } catch {
    return '' // storage blocked: the Connect screen asks every time instead
  }
}

// The page's own token wins: it is this launch's. A stored one is from the Connect screen;
// VITE_ASSISTANT_TOKEN is a development convenience for a fixed ASSISTANT_TOKEN.
let token = fromPage(document) || stored() || (import.meta.env.VITE_ASSISTANT_TOKEN ?? '')

/**
 * The backend refused our token -- almost always because it restarted with a new one. The
 * web app's server knows the new one, so ask it for a fresh copy of this page and take the
 * token from there. Reload only if it changed; otherwise it is genuinely unknown.
 */
let recovering: Promise<boolean> | null = null
function recoverToken(): Promise<boolean> {
  recovering ??= (async () => {
    try {
      const page = await fetch(location.pathname, { cache: 'no-store' })
      const fresh = fromPage(new DOMParser().parseFromString(await page.text(), 'text/html'))
      if (fresh && fresh !== token) {
        location.reload() // every part of the app, the event stream included, starts clean
        return true
      }
    } catch {
      // the web app's own server is gone too; nothing to recover from
    }
    return false
  })().finally(() => {
    recovering = null // one attempt per burst of refusals, but a later restart gets its own
  })
  return recovering
}

export const hasToken = () => token !== ''

/** Try a token against the backend before keeping it, so a typo is caught on the spot. */
export async function connect(candidate: string): Promise<void> {
  const trimmed = candidate.trim()
  let response: Response
  try {
    response = await fetch(`${API_URL}/api/tools`, { headers: { 'x-assistant-token': trimmed } })
  } catch {
    throw new Error(`Can't reach the backend at ${API_URL}. Is ./start running?`)
  }
  if (response.status === 401) throw new Error('That token was not accepted. Copy it again from the backend’s terminal.')
  if (!response.ok) throw new Error(`The backend answered ${response.status}.`)
  token = trimmed
  try {
    localStorage.setItem(TOKEN_KEY, trimmed)
  } catch {
    // kept for this tab only
  }
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message)
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: 'include',
    headers: {
      'content-type': 'application/json',
      ...NGROK_HEADER,
      ...(token ? { 'x-assistant-token': token } : {}),
      ...init.headers,
    },
  })
  if (response.status === 401 && !(await recoverToken())) {
    // No token, and none to be had from this page's server: ask the person, rather than
    // leaving the page quietly frozen.
    window.dispatchEvent(new Event('assistant-needs-token'))
  }
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = (await response.json()) as { detail?: string; error?: string }
      detail = body.detail ?? body.error ?? detail
    } catch {
      // not JSON; keep the status text
    }
    throw new ApiError(response.status, detail)
  }
  return (await response.json()) as T
}

export type EventType =
  | 'user_message'
  | 'assistant_text'
  | 'tool_started'
  | 'tool_finished'
  | 'approval_needed'
  | 'approval_resolved'
  | 'turn_done'
  | 'turn_error'
  | 'turn_stopped'
  | 'notice'
  | 'upload'
  | 'upload_deleted'
  | 'records_changed'
  | 'chat_cleared'

export interface AssistantEvent {
  seq: number
  at: number
  type: EventType
  text?: string
  tool?: string
  outcome?: string
  origin?: 'chat' | 'button'
  arguments?: Record<string, unknown>
  result?: string
  error?: string
  /** On a failed turn: the raw error, kept beside the plain one in `error`. */
  detail?: string
  /** On a failed turn: the model is the trouble, and Settings has the fix. */
  settings?: boolean
  id?: string
  approved?: boolean
  server?: string
  name?: string
  preview?: string | null
  preview_expected?: boolean
  read_only?: boolean
  level?: 'success' | 'warning' | 'error'
  title?: string
  body?: string
  kind?: 'audio' | 'docs' | 'book' | 'voice'
  path?: string
}

export interface Approval {
  id: string
  tool: string
  server: string
  name: string
  title?: string
  arguments: Record<string, unknown>
  preview: string | null
  preview_expected: boolean
}

export interface ServerState {
  busy: boolean
  pending: Approval[]
  history: AssistantEvent[]
  notes: string[]
  model: string
}

export interface ActionResult<T = unknown> {
  outcome?: string
  output?: T
  needs_confirmation?: boolean
  preview?: string | null
}

export interface ToolInfo {
  qualified_name: string
  server: string
  name: string
  /** What the tool calls itself for a person ("Write a new draft"); empty when it gives none. */
  title?: string
  read_only: boolean
  has_preview: boolean
}

export interface AuthInfo { email: string | null; google_auth: boolean }

export const getMe = () =>
  fetch(`${API_URL}/api/me`, { credentials: 'include', headers: NGROK_HEADER }).then(r => r.json() as Promise<AuthInfo>)

export const signInUrl = () =>
  `${API_URL}/auth/login?redirect=${encodeURIComponent(location.origin)}`

export const signOut = () =>
  fetch(`${API_URL}/auth/logout`, { method: 'POST', credentials: 'include', headers: NGROK_HEADER })

export const getState = () => request<ServerState>('/api/state')

export const getTools = () => request<ToolInfo[]>('/api/tools')

export interface AuditRow {
  at: string
  tool: string
  outcome: string
  origin?: string
  duration_ms?: number
  error?: string | null
}

export const getHistory = (limit = 200) => request<AuditRow[]>(`/api/history?limit=${limit}`)

export type Level = 'ok' | 'warning' | 'error'
/** What a tool's own check of its login found: ok; dead (refused, sign in again); missing (never signed in); unknown (could not tell). */
export type LoginState = 'ok' | 'dead' | 'missing' | 'unknown'

export interface Status {
  tools: {
    name: string
    tools: number
    level: Level
    last_call: { at: string; tool: string; outcome: string; error: string } | null
    /** Null until a check has asked; `service` is what the tool calls it ("Gmail"). */
    login?: { state: LoginState; detail: string; service: string; checked_at?: number } | null
  }[]
  model: {
    provider: string
    model: string
    profile: string | null
    region: string | null
    level?: Level
    account?: string
    role?: string
    detail?: string
    hint?: string
    /** The AWS login has expired (as opposed to the model being out of reach for another reason). */
    signed_out?: boolean
    /** An API key is in use and Anthropic refused it. */
    key_refused?: boolean
    /** An API key is in use and the model asked for is not one it can use; `available` names what it can. */
    model_missing?: boolean
    available?: string[]
    /** False when there is no model to try at all (no key, no AWS login): information, not a fault. */
    configured?: boolean
    checked_at?: number
  }
  mail_compose: boolean
  network?: {
    name: string
    host: string
    ipv4_ms: number | null
    ipv4_error: string
    ipv6_ms: number | null
    ipv6_error: string
    verdict: string
    level: Level
  }[]
}

export const getStatus = (live = false) => request<Status>(`/api/status${live ? '?live=true' : ''}`)

export const sendChat = (message: string) =>
  request<{ accepted: boolean }>('/api/chat', { method: 'POST', body: JSON.stringify({ message }) })

/** Delete the conversation (the model's memory of it and what Chat shows). Refused while a message is being worked on. */
export const clearChat = () => request<{ cleared: number }>('/api/chat/clear', { method: 'POST' })
/** Stop the reply being worked on, at its next safe point: a tool already running finishes, nothing after it starts. */
export const stopChat = () => request<{ stopping: boolean }>('/api/chat/stop', { method: 'POST' })

export type UploadKind = 'audio' | 'book' | 'voice' | 'docs'
export interface DeletedUpload { id: string; kind: UploadKind; name: string; files: number; bytes: number }

/** Delete one upload, by the id the listing gave it (two uploads may share a name). Only buttons can: no tool offers it. */
export const deleteUpload = (id: string) =>
  request<DeletedUpload>('/api/uploads/delete', { method: 'POST', body: JSON.stringify({ id }) })

export const answerApproval = (id: string, approve: boolean) =>
  request<{ approved: boolean }>(`/api/approvals/${encodeURIComponent(id)}`, {
    method: 'POST',
    body: JSON.stringify({ approve }),
  })

/** A button press: a tool you chose, called without a model. */
export const runAction = <T = unknown>(
  tool: string,
  args: Record<string, unknown> = {},
  confirmed = false,
) =>
  request<ActionResult<T>>('/api/actions', {
    method: 'POST',
    body: JSON.stringify({ tool, arguments: args, confirmed }),
  })

export interface EventStream {
  onopen: ((ev: Event) => void) | null
  onmessage: ((ev: MessageEvent) => void) | null
  onerror: ((ev: Event) => void) | null
  close(): void
}

/**
 * SSE via fetch, not EventSource — because EventSource cannot set custom headers and ngrok's
 * free tier blocks browser requests without `ngrok-skip-browser-warning`. Exposes the same
 * onopen / onmessage / onerror surface the caller already uses, and retries on disconnect.
 */
export function openEvents(): EventStream {
  let closed = false
  const self: EventStream = {
    onopen: null, onmessage: null, onerror: null,
    close() { closed = true },
  }
  const headers: Record<string, string> = { ...NGROK_HEADER }
  if (token) headers['x-assistant-token'] = token
  const url = token && !headers['x-assistant-token']
    ? `${API_URL}/api/events?token=${encodeURIComponent(token)}`
    : `${API_URL}/api/events`

  async function connect() {
    while (!closed) {
      try {
        const res = await fetch(url, { credentials: 'include', headers })
        if (!res.ok || !res.body) { throw new Error(`${res.status}`) }
        self.onopen?.(new Event('open') as any)
        const reader = res.body.getReader()
        const decoder = new TextDecoder()
        let buf = ''
        for (;;) {
          const { done, value } = await reader.read()
          if (done || closed) break
          buf += decoder.decode(value, { stream: true })
          const parts = buf.split('\n\n')
          buf = parts.pop()!
          for (const part of parts) {
            const dataLine = part.split('\n').find(l => l.startsWith('data:'))
            if (dataLine) {
              self.onmessage?.({ data: dataLine.slice(5).trimStart() } as MessageEvent)
            }
          }
        }
      } catch { /* reconnect below */ }
      if (!closed) {
        self.onerror?.(new Event('error'))
        await new Promise(r => setTimeout(r, 2000))
      }
    }
  }
  connect()
  return self
}

/** "meet_ai__start_recording" → "meet-ai · start recording" */
export function toolLabel(qualified: string | undefined): string {
  if (!qualified) return ''
  const [server, name] = qualified.split('__')
  return `${(server ?? '').replace(/_/g, '-')} · ${(name ?? '').replace(/_/g, ' ')}`
}

// ---------------------------------------------------------------------------
// Uploads. The file is the request body, so nothing is held in memory on either side, and
// XMLHttpRequest rather than fetch because only it reports upload progress -- a two-hour
// recording is over 100 MB.
// ---------------------------------------------------------------------------

export const AUDIO_EXTS = ['.m4a', '.mp3', '.wav', '.flac', '.ogg', '.opus', '.webm', '.mp4', '.aac', '.wma']
const ext = (name: string) => name.slice(name.lastIndexOf('.')).toLowerCase()
export const isAudio = (name: string) => AUDIO_EXTS.includes(ext(name))
export const isMarkdown = (name: string) => ext(name) === '.md'

// `id` is the upload's in the file store: what deleting goes by, since the same name may be uploaded twice.
export interface UploadedAudio { id: string; name: string; path: string; bytes: number }
export interface UploadedDocs { id: string; name: string; path: string; files: string[] }
export interface Uploads {
  audio: (UploadedAudio & { at: number })[]
  docs: (UploadedDocs & { at: number })[]
  books: (UploadedAudio & { at: number })[]
  voices: (UploadedAudio & { at: number })[]
}

function put<T>(path: string, file: Blob, onProgress?: (sent: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('PUT', `${API_URL}${path}`)
    xhr.withCredentials = true
    if (token) xhr.setRequestHeader('x-assistant-token', token)
    xhr.setRequestHeader('content-type', 'application/octet-stream')
    xhr.setRequestHeader('ngrok-skip-browser-warning', 'true')
    xhr.upload.onprogress = (e) => onProgress?.(e.loaded)
    xhr.onerror = () => reject(new Error(`Can't reach the backend at ${API_URL}.`))
    xhr.onload = () => {
      if (xhr.status === 401) {
        void recoverToken().then((ok) => ok || window.dispatchEvent(new Event('assistant-needs-token')))
      }
      let body: { error?: string } & T
      try {
        body = JSON.parse(xhr.responseText) as { error?: string } & T
      } catch {
        return reject(new Error(`Upload failed (${xhr.status}).`))
      }
      if (xhr.status >= 400 || body.error) return reject(new Error(body.error ?? `Upload failed (${xhr.status}).`))
      resolve(body)
    }
    xhr.send(file)
  })
}

export const getUploads = () => request<Uploads>('/api/uploads')

export const uploadAudio = (file: File, onProgress?: (fraction: number) => void) =>
  put<UploadedAudio>(`/api/uploads/audio?name=${encodeURIComponent(file.name)}`, file,
    (sent) => onProgress?.(file.size ? sent / file.size : 1))

/** A PDF to make into an audiobook. */
export const uploadBook = (file: File, onProgress?: (fraction: number) => void) =>
  put<UploadedAudio>(`/api/uploads/book?name=${encodeURIComponent(file.name)}`, file,
    (sent) => onProgress?.(file.size ? sent / file.size : 1))

/** A recording to clone a voice from. Kept apart from meetings' audio on the server. */
export const uploadVoice = (file: File, onProgress?: (fraction: number) => void) =>
  put<UploadedAudio>(`/api/uploads/voice?name=${encodeURIComponent(file.name)}`, file,
    (sent) => onProgress?.(file.size ? sent / file.size : 1))

/**
 * Audio a tool made. The token travels in a header like every other call, so the bytes are
 * fetched here and handed to the player as a blob, rather than an <audio> tag being pointed at a
 * URL -- which would mean putting the token in the URL, where it is kept in logs and history.
 */
export const fetchMedia = (path: string): Promise<Blob> => fetchBlob(`/api/files?path=${encodeURIComponent(path)}`)

/** A file the suite keeps, by its id: an upload, or audio a tool made and handed over (assistant/collect.py). */
export const fetchStored = (id: string): Promise<Blob> => fetchBlob(`/api/files/${encodeURIComponent(id)}`)

/**
 * What a tool made that the suite keeps, filed under the tool's own labels (assistant/records.py). The server does
 * not know what any of it is; the page that shows it does (Audiobooks knows a chapter).
 */
export interface KeptFile { id: string; name: string; bytes: number }
export interface Kept {
  id: string
  tool: string
  kind: string
  key: string
  labels: Record<string, unknown>
  files: Record<string, KeptFile>
  created: number
  updated: number
}

export const getKept = (tool: string) => request<{ records: Kept[] }>(`/api/records?tool=${encodeURIComponent(tool)}`)

/** Delete kept records and their files. Only a button reaches this; the server audits it. */
export const deleteKept = (ids: string[]) =>
  request<{ deleted: number; bytes: number }>('/api/records/delete', { method: 'POST', body: JSON.stringify({ ids }) })

async function fetchBlob(path: string): Promise<Blob> {
  const response = await fetch(`${API_URL}${path}`, {
    credentials: 'include',
    headers: { ...NGROK_HEADER, ...(token ? { 'x-assistant-token': token } : {}) },
  })
  if (response.status === 401 && !(await recoverToken())) {
    window.dispatchEvent(new Event('assistant-needs-token'))
  }
  if (!response.ok) {
    throw new ApiError(response.status, response.status === 404 ? 'That file is no longer there.' : response.statusText)
  }
  return response.blob()
}

/** docu-ai reads only the top level of a folder, so that is all that is sent; anything
 * deeper, or not markdown, is reported as skipped rather than uploaded to do nothing. */
export function splitDocs(files: File[]): { top: File[]; skipped: string[]; name: string } {
  const top: File[] = []
  const skipped: string[] = []
  const folder = files[0]?.webkitRelativePath.split('/')[0] ?? ''
  for (const f of files) {
    const rel = f.webkitRelativePath ? f.webkitRelativePath.split('/').slice(1).join('/') : f.name
    if (!isMarkdown(f.name)) skipped.push(`${rel} (not markdown)`)
    else if (rel.includes('/')) skipped.push(`${rel} (in a subfolder)`)
    else top.push(f)
  }
  const name = folder || (top.length === 1 ? top[0]!.name : 'Documents')
  return { top, skipped, name }
}

export async function uploadDocs(files: File[], name: string, onProgress?: (fraction: number) => void) {
  const total = files.reduce((n, f) => n + f.size, 0) || 1
  const { batch } = await request<{ batch: string; error?: string }>('/api/uploads/docs', {
    method: 'POST', body: JSON.stringify({ name }),
  })
  let done = 0
  for (const f of files) {
    await put(`/api/uploads/docs/${encodeURIComponent(batch)}?name=${encodeURIComponent(f.name)}`, f,
      (sent) => onProgress?.((done + sent) / total))
    done += f.size
  }
  return request<UploadedDocs>(`/api/uploads/docs/${encodeURIComponent(batch)}/done`, { method: 'POST' })
}
