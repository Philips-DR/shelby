// One state for both modes. Chat and buttons are two views of it, which is what lets a
// recording stopped with a button be the one the model writes up in chat.

import { createContext, useCallback, useContext, useEffect, useReducer, type ReactNode } from 'react'
import { getState, getStatus, getTools, openEvents, type Approval, type AssistantEvent } from './api'
import { loginOf, type ModelLogin } from './loginState'

interface State {
  events: AssistantEvent[]
  pending: Approval[]
  busy: boolean
  connected: boolean
  model: string
  /** Whether the model can be reached, as the last check found it; null before any check. */
  login: ModelLogin
  tools: Set<string>
  /** Each tool's own title for a person, by qualified name: what Chat and an approval call it. */
  titles: Record<string, string>
  /** Highest event seq in the first snapshot, or null before it arrives. Events at or below
   * it happened before this page opened. */
  openedAt: number | null
}

type Action =
  | { type: 'snapshot'; events: AssistantEvent[]; pending: Approval[]; busy: boolean; model: string }
  | { type: 'event'; event: AssistantEvent }
  | { type: 'connected'; value: boolean }
  | { type: 'tools'; names: string[]; titles: Record<string, string> }
  | { type: 'login'; value: ModelLogin }

const initial: State = { events: [], pending: [], busy: false, connected: false, model: '', login: null, tools: new Set(), titles: {}, openedAt: null }

function reduce(state: State, action: Action): State {
  switch (action.type) {
    case 'snapshot':
      return {
        ...state,
        events: action.events,
        pending: action.pending,
        busy: action.busy,
        model: action.model,
        // Only the first snapshot sets it; a reconnect's snapshot must not swallow notices
        // that arrived while this page was open.
        openedAt: state.openedAt ?? Math.max(0, ...action.events.map((e) => e.seq)),
      }
    case 'connected':
      return { ...state, connected: action.value }
    case 'tools':
      return { ...state, tools: new Set(action.names), titles: action.titles }
    case 'login':
      return state.login === action.value ? state : { ...state, login: action.value }
    case 'event': {
      const event = action.event
      // A reconnect replays from a fresh snapshot; drop anything already held.
      if (state.events.some((e) => e.seq === event.seq)) return state
      const events = [...state.events, event]
      switch (event.type) {
        case 'user_message':
          return { ...state, events, busy: true }
        case 'turn_done':
        case 'turn_error':
        case 'turn_stopped':
          return { ...state, events, busy: false }
        case 'approval_needed':
          return {
            ...state,
            events,
            pending: [
              ...state.pending.filter((p) => p.id !== event.id),
              {
                id: event.id ?? '',
                tool: event.tool ?? '',
                server: event.server ?? '',
                name: event.name ?? '',
                title: event.title ?? '',
                arguments: event.arguments ?? {},
                preview: event.preview ?? null,
                preview_expected: event.preview_expected ?? false,
              },
            ],
          }
        case 'approval_resolved':
          return { ...state, events, pending: state.pending.filter((p) => p.id !== event.id) }
        default:
          return { ...state, events }
      }
    }
  }
}

interface Context extends State {
  refresh: () => Promise<void>
  /** Ask what the last login check found (cheap: the server remembers it) and update the sidebar. */
  refreshLogin: () => Promise<void>
}

const AppState = createContext<Context | null>(null)

export function StateProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reduce, initial)

  const refresh = useCallback(async () => {
    const [snapshot, tools] = await Promise.all([getState(), getTools()])
    // Views adapt to what the server actually offers -- mail drafting, for instance, only
    // exists when it has been switched on for mail-ai.
    dispatch({ type: 'tools', names: tools.map((t) => t.qualified_name), titles: Object.fromEntries(tools.filter((t) => t.title).map((t) => [t.qualified_name, t.title!])) })
    dispatch({
      type: 'snapshot',
      events: snapshot.history,
      pending: snapshot.pending,
      busy: snapshot.busy,
      model: snapshot.model,
    })
  }, [])

  // The sidebar says whether the model can be reached. The server checks every ten minutes (every minute while the
  // login is out) and remembers; this reads what it found, so it is cheap and needs no event of its own.
  const refreshLogin = useCallback(async () => {
    try {
      dispatch({ type: 'login', value: loginOf((await getStatus(false)).model) })
    } catch {
      // keep what was shown: a failed read says nothing about the login
    }
  }, [])
  useEffect(() => {
    if (!state.connected) return
    void refreshLogin()
    const timer = window.setInterval(() => void refreshLogin(), 60_000)
    return () => window.clearInterval(timer)
  }, [state.connected, refreshLogin])

  useEffect(() => {
    let source: import('./api').EventStream | null = null
    let cancelled = false

    const connect = () => {
      source = openEvents()
      source.onopen = () => {
        dispatch({ type: 'connected', value: true })
        // Anything that happened while disconnected arrives in the snapshot. A refusal here
        // means a stale token, which has already raised the Connect screen.
        refresh().catch(() => {})
      }
      source.onmessage = (message: MessageEvent<string>) => {
        const event = JSON.parse(message.data) as AssistantEvent
        dispatch({ type: 'event', event })
        // The server decides what counts as conversation; this page takes its pruned history rather than
        // keeping a second copy of that rule.
        if (event.type === 'chat_cleared') refresh().catch(() => {})
        // A login going bad, or coming back, is announced as a notice: look at once rather than wait for the minute.
        if (event.type === 'notice') void refreshLogin()
      }
      source.onerror = () => {
        dispatch({ type: 'connected', value: false })
        // EventSource retries on its own; nothing else to do.
      }
    }

    // Try to connect: a token or a session cookie may be present.
    refresh()
      .catch(() => {
        // A 401 has already raised the auth screen; anything else, the event stream's
        // own reconnect will retry.
      })
      .finally(() => {
        if (!cancelled) connect()
      })
    return () => {
      cancelled = true
      source?.close()
    }
  }, [refresh, refreshLogin])

  return <AppState.Provider value={{ ...state, refresh, refreshLogin }}>{children}</AppState.Provider>
}

export function useAppState(): Context {
  const context = useContext(AppState)
  if (!context) throw new Error('useAppState outside StateProvider')
  return context
}
