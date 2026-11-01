// What the Audiobooks page works out from a book's chapters, kept apart from the page so it can be tested.

interface Rendered { number: number; audio?: readonly unknown[] }

/** The chapters a render starts with: those with no audio yet. A book never rendered gets every chapter, a
 *  finished one none (its chapters are ticked by hand to be made again, in another voice or after a correction). */
export const unrendered = (chapters: readonly Rendered[]): Set<number> =>
  new Set(chapters.filter((c) => !c.audio?.length).map((c) => c.number))

/** What the Render button says. */
export function renderLabel(chosen: number, total: number, rendered: number): string {
  if (chosen === 0) return rendered === total && total > 0 ? 'Every chapter is rendered' : 'Render'
  return chosen === total ? 'Render all chapters' : `Render ${chosen} chapter${chosen === 1 ? '' : 's'}`
}
