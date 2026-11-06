// A reply read aloud in Pocket TTS (audiobook's speak, through /api/speak), when its speaker button is pressed. It is
// said a sentence at a time (speechText.ts): the next is fetched while the one before plays, and at the 8-bit model's
// 2x real time it is ready long before it is needed, so only the first sentence is waited for. One audio element for
// the page's life, started with a moment of silence by the press itself: a phone's browser (Safari) plays sound only
// from an element a press has started, and the first sentence arrives after the press is over.

import { useCallback, useEffect, useRef, useState } from 'react'
import { speakText } from './api'
import { pieces, speakable } from './components/speechText'
import { usePlayer, usePlayerActions } from './player/engine'

export interface Speech {
  /** The reply being read, by its key, or null. */
  reading: string | null
  /** Waiting for its first sentence. */
  starting: boolean
  error: string
  /** Read this reply now, instead of whatever is being read. Call it from the press itself. */
  read: (key: string, markdown: string) => void
  stop: () => void
}

interface Item { key: string; parts: string[] }

/** A tenth of a second of silence, as a WAV: what unlock plays. */
function silence(): Blob {
  const rate = 8000
  const samples = rate / 10
  const view = new DataView(new ArrayBuffer(44 + samples * 2))
  const text = (at: number, s: string) => [...s].forEach((c, i) => view.setUint8(at + i, c.charCodeAt(0)))
  text(0, 'RIFF'); view.setUint32(4, 36 + samples * 2, true); text(8, 'WAVEfmt ')
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true)
  view.setUint32(24, rate, true); view.setUint32(28, rate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true)
  text(36, 'data'); view.setUint32(40, samples * 2, true)
  return new Blob([view], { type: 'audio/wav' })
}

export function useSpeech(): Speech {
  const audio = useRef<HTMLAudioElement | null>(null)
  const [reading, setReading] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState('')
  const items = useRef<Item[]>([])
  const run = useRef(0) // a new number stops the reading in progress
  const owner = useRef<number | null>(null) // the run now reading, if any
  const requests = useRef(new Set<AbortController>())
  const finishPlaying = useRef<(() => void) | null>(null)
  const player = usePlayer()
  const actions = usePlayerActions()
  const book = useRef({ playing: player.playing, toggle: actions.toggle })
  book.current = { playing: player.playing, toggle: actions.toggle }

  const element = () => (audio.current ??= new Audio())

  const fetchPart = (text: string): Promise<Blob> => {
    const control = new AbortController()
    requests.current.add(control)
    return speakText(text, control.signal).finally(() => requests.current.delete(control))
  }

  const play = (blob: Blob): Promise<void> => new Promise((resolve, reject) => {
    const el = element()
    const url = URL.createObjectURL(blob)
    const done = () => { el.onended = null; el.onerror = null; finishPlaying.current = null; URL.revokeObjectURL(url) }
    finishPlaying.current = () => { done(); resolve() }
    el.onended = () => { done(); resolve() }
    el.onerror = () => { done(); reject(new Error('This browser could not play the spoken reply.')) }
    el.src = url
    el.play().catch((e: unknown) => { done(); reject(e) })
  })

  const pump = useCallback(async () => {
    const id = ++run.current
    owner.current = id
    const live = () => run.current === id
    try {
      while (items.current.length && live()) {
        const item = items.current.shift()!
        setReading(item.key)
        setStarting(true)
        if (book.current.playing) book.current.toggle() // an audiobook pauses while a reply is read
        let next: Promise<Blob> | null = fetchPart(item.parts[0]!) // queue() never adds an empty item
        for (let i = 0; i < item.parts.length && live(); i++) {
          const blob = await next!
          next = i + 1 < item.parts.length ? fetchPart(item.parts[i + 1]!) : null
          next?.catch(() => {}) // a stop abandons it; its rejection is not an error
          if (!live()) break
          setStarting(false)
          await play(blob)
        }
      }
    } catch (e) {
      if (live()) {
        items.current = []
        if (e instanceof DOMException && e.name === 'NotAllowedError') {
          setError('The browser would not play sound yet. Press Read aloud on the reply to hear it.')
        } else if (!(e instanceof DOMException && e.name === 'AbortError')) {
          setError(e instanceof Error ? e.message : String(e))
        }
      }
    } finally {
      if (owner.current === id) {
        owner.current = null
        setReading(null)
        setStarting(false)
      }
    }
  }, [])

  const stop = useCallback(() => {
    run.current++
    owner.current = null
    items.current = []
    requests.current.forEach((c) => c.abort())
    requests.current.clear()
    audio.current?.pause()
    finishPlaying.current?.()
    setReading(null)
    setStarting(false)
  }, [])

  const queue = useCallback((key: string, markdown: string) => {
    const parts = pieces(speakable(markdown))
    if (!parts.length) return
    setError('')
    items.current.push({ key, parts })
    if (owner.current === null) void pump()
  }, [pump])

  /** From the press: a moment of silence, so a phone's browser lets this element play the reply when it arrives. */
  const unlock = useCallback(() => {
    const el = element()
    const url = URL.createObjectURL(silence())
    el.src = url
    el.play().catch(() => {}).finally(() => URL.revokeObjectURL(url))
  }, [])

  const read = useCallback((key: string, markdown: string) => { stop(); unlock(); queue(key, markdown) }, [stop, unlock, queue])

  useEffect(() => stop, [stop]) // leaving Chat stops the reading

  return { reading, starting, error, read, stop }
}
