// Where you are is the URL hash, so back, bookmarks and a link to one page all work. The old
// forms (#chat, #buttons/mail) still land in the right place.

import { useCallback, useEffect, useState } from 'react'
import { SECTIONS, type Section } from './sections'

const ids = new Set<string>(SECTIONS.map((s) => s.id))

export function parseHash(hash: string): Section {
  const raw = hash.replace(/^#\/?/, '').replace(/^buttons\/?/, '')
  if (hash.startsWith('#buttons') && raw === '') return 'overview'
  return ids.has(raw) ? (raw as Section) : 'overview'
}

export function useRoute(): [Section, (to: Section) => void] {
  const [section, setSection] = useState<Section>(() => parseHash(location.hash))

  useEffect(() => {
    const follow = () => setSection(parseHash(location.hash))
    window.addEventListener('hashchange', follow)
    return () => window.removeEventListener('hashchange', follow)
  }, [])

  const go = useCallback((to: Section) => {
    if (location.hash !== `#${to}`) {
      // Chosen from a sheet or the search box: that replaces its entry (see useLayer.ts), so Back leaves it behind.
      if ((history.state as { modal?: boolean } | null)?.modal) location.replace(`#${to}`)
      else location.hash = to
    } else setSection(to)
    window.scrollTo({ top: 0 })
  }, [])

  return [section, go]
}
