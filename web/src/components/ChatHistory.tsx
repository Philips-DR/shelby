import { useCallback, useEffect, useRef, useState } from 'react'
import {
  type ConversationSummary,
  clearChat,
  deleteConversation,
  getConversation,
  getConversations,
  getCurrentConversation,
  renameConversation,
} from '../api'
import { ConfirmDelete } from '../ui/ConfirmDelete'
import { IconClose, IconMore, IconNewChat, IconRename, IconTrash } from '../ui/icons'
import type { AssistantEvent } from '../api'

interface Props {
  open: boolean
  onClose: () => void
  busy: boolean
  /** A past conversation was chosen. Opening it closes this panel (one layer: Chat.tsx), so no onClose follows. */
  onLoad: (id: string, events: AssistantEvent[], title: string) => void
  onNewChat: () => void
}

function timeLabel(iso: string): string {
  const d = new Date(iso)
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const day = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  const diff = (today.getTime() - day.getTime()) / 86_400_000
  if (diff < 1) return 'Today'
  if (diff < 2) return 'Yesterday'
  if (diff < 7) return 'Previous 7 days'
  if (diff < 30) return 'Previous 30 days'
  return d.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })
}

function groupByDate(items: ConversationSummary[]): [string, ConversationSummary[]][] {
  const groups: Map<string, ConversationSummary[]> = new Map()
  for (const item of items) {
    const label = timeLabel(item.updated_at)
    const list = groups.get(label)
    if (list) list.push(item)
    else groups.set(label, [item])
  }
  return [...groups.entries()]
}

function ConversationItem({ conv, onSelect, onDelete, onRename }: {
  conv: ConversationSummary
  onSelect: () => void
  onDelete: () => void
  onRename: (title: string) => void
}) {
  const [menu, setMenu] = useState(false)
  const [editing, setEditing] = useState(false)
  const [editTitle, setEditTitle] = useState(conv.title)
  const inputRef = useRef<HTMLInputElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!menu) return
    const close = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenu(false)
    }
    window.addEventListener('click', close, true)
    return () => window.removeEventListener('click', close, true)
  }, [menu])

  useEffect(() => {
    if (editing) inputRef.current?.focus()
  }, [editing])

  const commitRename = () => {
    const trimmed = editTitle.trim()
    if (trimmed && trimmed !== conv.title) onRename(trimmed)
    setEditing(false)
  }

  if (editing) {
    return (
      <div className="conv-item editing">
        <input
          ref={inputRef}
          className="conv-rename-input"
          value={editTitle}
          onChange={(e) => setEditTitle(e.target.value)}
          onBlur={commitRename}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commitRename()
            if (e.key === 'Escape') setEditing(false)
          }}
        />
      </div>
    )
  }

  return (
    <div className="conv-item">
      <button className="conv-select" onClick={onSelect}>
        <span className="conv-title">{conv.title || 'Untitled'}</span>
      </button>
      <div className="conv-actions" ref={menuRef}>
        <button className="ghost icon conv-menu-btn" onClick={(e) => { e.stopPropagation(); setMenu(!menu) }} aria-label="More">
          <IconMore size={15} aria-hidden />
        </button>
        {menu && (
          <div className="conv-menu">
            <button onClick={() => { setMenu(false); setEditTitle(conv.title); setEditing(true) }}>
              <IconRename size={14} aria-hidden />Rename
            </button>
            <button className="danger" onClick={() => { setMenu(false); onDelete() }}>
              <IconTrash size={14} aria-hidden />Delete
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

export function ChatHistory({ open, onClose, busy, onLoad, onNewChat }: Props) {
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  // The conversation Chat is in now: deleting it empties Chat too, and the dialog has to say so.
  const [currentId, setCurrentId] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [deleting, setDeleting] = useState<ConversationSummary | null>(null)
  const [deleteBusy, setDeleteBusy] = useState(false)
  const [deleteError, setDeleteError] = useState('')
  const panelRef = useRef<HTMLDivElement>(null)
  const first = useRef<HTMLButtonElement>(null)
  // Closed, the panel is not on the page at all (as the More sheet, ui/Shell.tsx): hidden but present, its buttons
  // were still reached by Tab. It stays for the slide-out, then goes.
  const [mounted, setMounted] = useState(open)
  useEffect(() => {
    if (open) {
      setMounted(true)
      return
    }
    const t = window.setTimeout(() => setMounted(false), 260)
    return () => window.clearTimeout(t)
  }, [open])
  useEffect(() => {
    if (open && mounted) first.current?.focus()
  }, [open, mounted])

  const refresh = useCallback(async () => {
    try {
      const [list, current] = await Promise.all([getConversations(), getCurrentConversation()])
      setConversations(list)
      setCurrentId(current.id)
    } catch {
      // keep what was shown
    }
  }, [])

  useEffect(() => {
    if (open) void refresh()
  }, [open, refresh])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  const select = async (conv: ConversationSummary) => {
    setLoading(true)
    try {
      const full = await getConversation(conv.id)
      onLoad(full.id, full.events, full.title)
    } catch {
      // stay on the list
    } finally {
      setLoading(false)
    }
  }

  const doDelete = async () => {
    if (!deleting) return
    setDeleteBusy(true)
    setDeleteError('')
    try {
      await deleteConversation(deleting.id)
      setConversations((c) => c.filter((x) => x.id !== deleting.id))
      setDeleting(null)
    } catch (e) {
      setDeleteError(e instanceof Error ? e.message : String(e))
    } finally {
      setDeleteBusy(false)
    }
  }

  const doRename = async (id: string, title: string) => {
    try {
      await renameConversation(id, title)
      setConversations((c) => c.map((x) => (x.id === id ? { ...x, title } : x)))
    } catch {
      // keep old name
    }
  }

  const handleNewChat = async () => {
    if (busy) return
    try {
      await clearChat()
      onNewChat()
      onClose()
      void refresh()
    } catch {
      // stay open
    }
  }

  const grouped = groupByDate(conversations)
  if (!mounted) return null

  return (
    <div className={`history-root ${open ? 'open' : ''}`}>
      <div className="history-backdrop" onClick={onClose} />
      <div className="history-panel" ref={panelRef} role="dialog" aria-modal="true" aria-label="Chat history">
        <div className="history-head">
          <h2>History</h2>
          <button className="ghost icon" onClick={onClose} aria-label="Close history"><IconClose size={18} aria-hidden /></button>
        </div>
        <button ref={first} className="history-new" onClick={() => void handleNewChat()} disabled={busy}>
          <IconNewChat size={16} aria-hidden />New chat
        </button>
        <div className="history-list">
          {loading && <p className="muted small history-empty">Loading…</p>}
          {!loading && conversations.length === 0 && (
            <p className="muted small history-empty">No conversations yet.</p>
          )}
          {!loading && grouped.map(([label, items]) => (
            <div key={label} className="history-group">
              <span className="history-group-label">{label}</span>
              {items.map((conv) => (
                <ConversationItem
                  key={conv.id}
                  conv={conv}
                  onSelect={() => void select(conv)}
                  onDelete={() => setDeleting(conv)}
                  onRename={(title) => void doRename(conv.id, title)}
                />
              ))}
            </div>
          ))}
        </div>
      </div>
      {deleting && (
        <ConfirmDelete
          title="Delete this conversation?"
          facts={[['Title', deleting.title || 'Untitled'], ['Messages', String(deleting.message_count)]]}
          keeps={deleting.id === currentId
            ? 'This is the conversation open in Chat now, so Chat will be empty afterwards. It cannot be undone.'
            : 'The conversation and its messages will be permanently deleted.'}
          verb="Delete"
          busy={deleteBusy}
          error={deleteError}
          onConfirm={() => void doDelete()}
          onCancel={() => setDeleting(null)}
        />
      )}
    </div>
  )
}
