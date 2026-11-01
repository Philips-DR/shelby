// The app: a shell (sidebar, rail, top bar, tab bar) around one page at a time, chosen by the URL
// hash. Chat and the tool pages share one state, so something started in chat shows on the page for
// it and the other way round; and an approval waiting on you shows wherever you are.

import { lazy, Suspense, useCallback, useEffect, useState } from 'react'
import { ApprovalCard } from './components/ApprovalCard'
import { Connect } from './components/Connect'
import { Notices } from './components/Notices'
import { getMe, hasToken } from './api'
import { Overview } from './pages/Overview'
import { useAppState } from './state'
import { CommandPalette } from './ui/CommandPalette'
import { IconAlert } from './ui/icons'
import { PageHead } from './ui/PageHead'
import type { Section } from './ui/sections'
import { usePlayer } from './player/engine'
import { MiniPlayer } from './ui/MiniPlayer'
import { MoreSheet, Sidebar, TabBar, TopBar } from './ui/Shell'
import { useLayer } from './ui/useLayer'
import { useRoute } from './ui/useRoute'
import { useTheme } from './ui/useTheme'

// Every page but the first is fetched when it is opened, so the app starts on a phone with only what the
// Overview needs (the markdown renderer behind Chat alone is a large part of the code).
const page = <K extends string>(load: () => Promise<Record<K, React.ComponentType>>, name: K) =>
  lazy(() => load().then((m) => ({ default: m[name] })))
const Chat = page(() => import('./components/Chat'), 'Chat')
const Documents = page(() => import('./components/Documents'), 'Documents')
const History = page(() => import('./components/History'), 'History')
const Mail = page(() => import('./components/Mail'), 'Mail')
const Meetings = page(() => import('./components/Meetings'), 'Meetings')
const Memory = page(() => import('./components/Memory'), 'Memory')
const Audiobooks = page(() => import('./components/Audiobooks'), 'Audiobooks')
const Settings = page(() => import('./components/Settings'), 'Settings')

function Loading() {
  return <div className="panel" aria-busy="true" aria-label="Loading the page"><div className="skeleton" style={{ height: 160 }} /><div className="skeleton" style={{ height: 240 }} /></div>
}

function Page({ section, go }: { section: Section; go: (to: Section) => void }) {
  switch (section) {
    case 'overview': return <Overview go={go} />
    case 'chat': return <Chat />
    case 'meetings': return <><PageHead section="meetings" /><Meetings /></>
    case 'documents': return <><PageHead section="documents" /><Documents /></>
    case 'audiobooks': return <><PageHead section="audiobooks" /><Audiobooks /></>
    case 'mail': return <><PageHead section="mail" /><Mail /></>
    case 'memory': return <><PageHead section="memory" /><Memory /></>
    case 'history': return <><PageHead section="history" /><History /></>
    case 'settings': return <><PageHead section="settings" /><Settings /></>
  }
}

export function App() {
  const { pending } = useAppState()
  const [section, go] = useRoute()
  const [theme, cycleTheme, setTheme] = useTheme()
  // The More sheet and the search box are one slot: only one is open at a time, going from one to the other is a swap,
  // and Back closes whichever is open before it leaves the page (useLayer.ts).
  const [overlay, setOverlay] = useState<'more' | 'palette' | null>(null)
  useLayer('overlay', overlay, setOverlay, true)
  const palette = overlay === 'palette'
  const more = overlay === 'more'
  const closeOverlay = useCallback(() => setOverlay(null), [])

  // Not authenticated yet: the whole app waits behind the Connect / Sign-in screen.
  // Always check /api/me first: when Google auth is configured, a session cookie is required
  // even if a page token exists. When Google auth is off, the token alone is enough.
  const [authState, setAuthState] = useState<'ok' | 'checking' | 'needs_auth'>('checking')
  useEffect(() => {
    if (authState !== 'checking') return
    getMe()
      .then((info) => {
        if (info.email || hasToken()) {
          setAuthState('ok')
        } else {
          setAuthState('needs_auth')
        }
      })
      .catch(() => setAuthState(hasToken() ? 'ok' : 'needs_auth'))
  }, [authState])
  useEffect(() => {
    const onNeedsAuth = () => {
      if (hasToken()) {
        setAuthState('needs_auth')
      } else {
        setAuthState('checking')
      }
    }
    window.addEventListener('assistant-needs-token', onNeedsAuth)
    return () => window.removeEventListener('assistant-needs-token', onNeedsAuth)
  }, [])

  // Ctrl+K (or Cmd+K) from anywhere.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setOverlay((now) => (now === 'palette' ? null : 'palette'))
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const openPalette = useCallback(() => setOverlay('palette'), [])
  const inChat = section === 'chat'
  // While anything is loaded the shell keeps room at the foot of the page for the docked player, whether or
  // not it is showing: room that came and went as the dock did would shift the page under your finger.
  const loaded = usePlayer().track !== null

  // Mail is synced by the backend on the schedule in tools.yaml, open page or not: a timer here only ran while a
  // tab was open, and two tabs synced twice.

  return (
    <div className="shell" data-section={section} data-mini={loaded ? '' : undefined}>
      {authState !== 'ok' && <Connect checking={authState === 'checking'} />}
      <Sidebar section={section} go={go} theme={theme} setTheme={setTheme} openPalette={openPalette} />
      <div className="content">
        <TopBar section={section} openPalette={openPalette} cycleTheme={cycleTheme} theme={theme} />
        <main className={`page ${inChat ? 'page-chat' : ''}`} key={section} id="main">
          {pending.length > 0 && !inChat && (
            <div className="tray" role="region" aria-label="Waiting for your answer">
              <span className="tray-label"><IconAlert size={16} aria-hidden />The assistant is waiting for your answer</span>
              {pending.map((p) => <ApprovalCard key={p.id} approval={p} />)}
            </div>
          )}
          <Suspense fallback={<Loading />}><Page section={section} go={go} /></Suspense>
        </main>
      </div>
      <MiniPlayer goToBooks={() => go('audiobooks')} />
      <TabBar section={section} go={go} openMore={() => setOverlay('more')} />
      <MoreSheet open={more} onClose={closeOverlay} section={section} go={go} theme={theme} setTheme={setTheme} onSearch={openPalette} />
      <CommandPalette open={palette} onClose={closeOverlay} go={go} setTheme={setTheme} pending={pending.length} />
      <Notices />
    </div>
  )
}
