import { afterEach, describe, expect, it, vi } from 'vitest'
import { askToShow, onRequest, takeRequest } from './showing'

const home = { book: '/books/a.pdf', chapter: 6 }

afterEach(() => { takeRequest() }) // a test must not leave a request for the next

describe('asking to be shown where something is playing', () => {
  it('waits for a page that does not exist yet, which is where the docked player is on every other page', () => {
    askToShow(home)
    expect(takeRequest()).toEqual(home)
  })

  it('is used once: asking again gives nothing', () => {
    askToShow(home)
    takeRequest()
    expect(takeRequest()).toBeNull()
  })

  it('is told at once to a page that is already open', () => {
    const heard = vi.fn()
    const stop = onRequest(heard)
    askToShow(home)
    expect(heard).toHaveBeenCalledTimes(1)
    expect(takeRequest()).toEqual(home)
    stop()
  })

  it('is not told once the page has gone', () => {
    const heard = vi.fn()
    onRequest(heard)()
    askToShow(home)
    expect(heard).not.toHaveBeenCalled()
  })

  it('keeps only the latest when it is asked twice before anyone answers', () => {
    askToShow(home)
    askToShow({ book: '/books/b.pdf', chapter: 2 })
    expect(takeRequest()).toEqual({ book: '/books/b.pdf', chapter: 2 })
  })
})
