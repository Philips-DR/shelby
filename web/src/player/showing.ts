// "Show me where this is playing": the docked player asks, the Audiobooks page answers. A request has to survive
// the page not existing yet (the docked player is on every other page), so it waits here until the page takes it,
// and a page that is already open hears of it at once. Nothing is stored: a request is used once, or dropped.

import type { Home } from './engine'

let pending: Home | null = null
const listeners = new Set<() => void>()

export const askToShow = (home: Home): void => {
  pending = home
  listeners.forEach((listen) => listen())
}

/** The waiting request, if any; asking again gives nothing. */
export const takeRequest = (): Home | null => {
  const request = pending
  pending = null
  return request
}

/** Called whenever a request arrives; returns how to stop listening. */
export const onRequest = (listen: () => void): (() => void) => {
  listeners.add(listen)
  return () => { listeners.delete(listen) }
}
