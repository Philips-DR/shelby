// Record audio from the browser's microphone using MediaRecorder. The audio is uploaded to the
// backend as a file, landing in the same place a file upload does — so the existing Transcribe
// flow picks it up unchanged.

import { useCallback, useEffect, useRef, useState } from 'react'
import { uploadAudio } from './api'

export type RecState = 'idle' | 'requesting' | 'recording' | 'stopping' | 'uploading' | 'done' | 'error'

export interface RecResult { path: string; name: string; seconds: number }

export interface BrowserRecorder {
  state: RecState
  elapsed: number
  error: string
  result: RecResult | null
  start(): void
  stop(): void
  reset(): void
  uploadProgress: number
}

export const preferredMime = (): string => {
  for (const mime of ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4']) {
    if (typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(mime)) return mime
  }
  return ''
}

export const extFor = (mime: string): string => {
  if (mime.startsWith('audio/webm')) return '.webm'
  if (mime.startsWith('audio/ogg')) return '.ogg'
  if (mime.startsWith('audio/mp4')) return '.m4a'
  return '.webm'
}

export const canRecordInBrowser = (): boolean =>
  typeof navigator !== 'undefined' &&
  typeof navigator.mediaDevices?.getUserMedia === 'function' &&
  typeof MediaRecorder !== 'undefined' &&
  preferredMime() !== ''

const timestamp = () => {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`
}

export function useBrowserRecorder(): BrowserRecorder {
  const [state, setState] = useState<RecState>('idle')
  const [elapsed, setElapsed] = useState(0)
  const [error, setError] = useState('')
  const [result, setResult] = useState<RecResult | null>(null)
  const [uploadProgress, setUploadProgress] = useState(0)

  const recorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const startTimeRef = useRef(0)
  const timerRef = useRef(0)

  const cleanup = useCallback(() => {
    if (timerRef.current) { window.clearInterval(timerRef.current); timerRef.current = 0 }
    if (streamRef.current) {
      for (const track of streamRef.current.getTracks()) track.stop()
      streamRef.current = null
    }
    recorderRef.current = null
    chunksRef.current = []
  }, [])

  useEffect(() => cleanup, [cleanup])

  const start = useCallback(() => {
    if (state === 'recording' || state === 'requesting') return
    setError('')
    setResult(null)
    setState('requesting')

    const mime = preferredMime()
    if (!mime) { setError('This browser does not support audio recording.'); setState('error'); return }

    navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: true } })
      .then((stream) => {
        streamRef.current = stream
        const recorder = new MediaRecorder(stream, { mimeType: mime })
        recorderRef.current = recorder
        chunksRef.current = []

        recorder.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data) }

        recorder.onstop = () => {
          const blob = new Blob(chunksRef.current, { type: mime })
          const seconds = (Date.now() - startTimeRef.current) / 1000
          const name = `recording_${timestamp()}${extFor(mime)}`

          for (const track of stream.getTracks()) track.stop()
          streamRef.current = null

          if (blob.size === 0) {
            setError('Recording produced no audio.')
            setState('error')
            return
          }

          setState('uploading')
          setUploadProgress(0)
          const file = new File([blob], name, { type: mime })
          uploadAudio(file, (frac) => setUploadProgress(frac))
            .then((uploaded) => {
              setResult({ path: uploaded.path, name: uploaded.name, seconds })
              setState('done')
            })
            .catch((e: unknown) => {
              setError(e instanceof Error ? e.message : String(e))
              setState('error')
            })
        }

        recorder.onerror = () => {
          setError('Recording failed.')
          setState('error')
          cleanup()
        }

        recorder.start(1000) // collect a chunk every second
        startTimeRef.current = Date.now()
        setElapsed(0)
        setState('recording')
        timerRef.current = window.setInterval(() => {
          setElapsed(Math.floor((Date.now() - startTimeRef.current) / 1000))
        }, 1000)
      })
      .catch((e: unknown) => {
        const msg = e instanceof DOMException && e.name === 'NotAllowedError'
          ? 'Microphone access was denied. Allow it in your browser settings.'
          : e instanceof Error ? e.message : String(e)
        setError(msg)
        setState('error')
      })
  }, [state, cleanup])

  const stop = useCallback(() => {
    if (timerRef.current) { window.clearInterval(timerRef.current); timerRef.current = 0 }
    const recorder = recorderRef.current
    if (recorder && recorder.state === 'recording') {
      setState('stopping')
      recorder.stop()
    }
  }, [])

  const reset = useCallback(() => {
    cleanup()
    setState('idle')
    setElapsed(0)
    setError('')
    setResult(null)
    setUploadProgress(0)
  }, [cleanup])

  return { state, elapsed, error, result, start, stop, reset, uploadProgress }
}
