// The chat box's microphone. A short clip is recorded in the browser, sent to meet-ai's dictate through the backend
// (/api/dictate), and its words handed back for the message box. Not the Meetings recorder (useBrowserRecorder.ts):
// nothing is uploaded or kept, the browser's own echo and noise cleanup is on (one voice, close to the microphone),
// and a clip stops by itself just inside the length dictation takes.

import { useCallback, useEffect, useRef, useState } from 'react'
import { dictate } from './api'
import { micProblem } from './components/dictationText'
import { extFor, preferredMime } from './useBrowserRecorder'

export type DictationState = 'idle' | 'starting' | 'recording' | 'transcribing'

/** meet-ai refuses a clip over 120 s (dictation.py); the recorder stops a little before. */
export const DICTATION_LIMIT_S = 118

export interface Dictation {
  state: DictationState
  elapsed: number
  error: string
  start: () => void
  /** Stop, and write down what was said. */
  finish: () => void
  /** Stop, and throw the clip away. */
  cancel: () => void
}

export function useDictation(onText: (said: string) => void): Dictation {
  const [state, setState] = useState<DictationState>('idle')
  const [elapsed, setElapsed] = useState(0)
  const [error, setError] = useState('')
  const recorder = useRef<MediaRecorder | null>(null)
  const media = useRef<MediaStream | null>(null)
  const chunks = useRef<Blob[]>([])
  const keep = useRef(true)
  const timer = useRef(0)
  const latest = useRef(onText)
  latest.current = onText

  const release = useCallback(() => {
    if (timer.current) { window.clearInterval(timer.current); timer.current = 0 }
    media.current?.getTracks().forEach((track) => track.stop())
    media.current = null
  }, [])

  const stop = useCallback((write: boolean) => {
    keep.current = write
    if (recorder.current?.state === 'recording') recorder.current.stop()
  }, [])
  const finish = useCallback(() => stop(true), [stop])
  const cancel = useCallback(() => stop(false), [stop])

  // Leaving Chat mid-clip throws it away and lets go of the microphone.
  useEffect(() => () => { stop(false); release() }, [stop, release])

  const start = useCallback(() => {
    if (state !== 'idle') return
    const mime = preferredMime()
    if (!mime) { setError('This browser cannot record audio.'); return }
    setError('')
    setState('starting')
    navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } })
      .then((stream) => {
        media.current = stream
        const rec = new MediaRecorder(stream, { mimeType: mime })
        recorder.current = rec
        chunks.current = []
        keep.current = true
        rec.ondataavailable = (e) => { if (e.data.size > 0) chunks.current.push(e.data) }
        rec.onstop = () => {
          release()
          recorder.current = null
          const clip = new Blob(chunks.current, { type: mime })
          chunks.current = []
          if (!keep.current) { setState('idle'); return }
          if (clip.size === 0) { setError('Nothing was recorded.'); setState('idle'); return }
          setState('transcribing')
          dictate(clip, `dictation${extFor(mime)}`)
            .then((result) => {
              if (result.text.trim()) latest.current(result.text)
              else setError('Nothing was heard. Try again, a little closer to the microphone.')
            })
            .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
            .finally(() => setState('idle'))
        }
        const began = Date.now()
        setElapsed(0)
        rec.start()
        setState('recording')
        timer.current = window.setInterval(() => {
          const seconds = (Date.now() - began) / 1000
          setElapsed(seconds)
          if (seconds >= DICTATION_LIMIT_S) stop(true)
        }, 250)
      })
      .catch((e: unknown) => { release(); setError(micProblem(e)); setState('idle') })
  }, [state, release, stop])

  return { state, elapsed, error, start, finish, cancel }
}
