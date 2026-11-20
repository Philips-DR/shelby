import { describe, expect, it } from 'vitest'
import { seeing, shown, type JobView } from './audiobookJobs'

const job = (kind: string, state: string, id = `${kind}-1`) => ({ id, kind, state })
const none: JobView = { hiddenId: '', watchedSampleId: '' }

/** What the page does on each poll: look at the job, then decide what to show. */
const poll = (view: JobView, j: ReturnType<typeof job> | null) => {
  const next = seeing(j, view)
  return { view: next, card: shown(j, next) }
}

describe('which job gets a card', () => {
  it('shows a job that is running, and hides a finished render or reading at once', () => {
    for (const kind of ['render', 'analyse', 'voice']) {
      let step = poll(none, job(kind, 'running'))
      expect(step.card).not.toBeNull()
      step = poll(step.view, job(kind, 'done'))
      expect(step.card).toBeNull()
    }
  })

  it('keeps a sample this page watched run on screen once it is done', () => {
    let step = poll(none, job('sample', 'running'))
    expect(step.card?.state).toBe('running')
    step = poll(step.view, job('sample', 'done'))
    expect(step.card?.state).toBe('done')
    // and it is still there on the next polls
    step = poll(step.view, job('sample', 'done'))
    expect(step.card?.state).toBe('done')
  })

  it('does not show an old finished sample to someone who has just opened the page', () => {
    const step = poll(none, job('sample', 'done', 'sample-from-last-week'))
    expect(step.card).toBeNull()
  })

  it('lets the next job take the card: a render after a sample is shown, and hidden when it is done', () => {
    let step = poll(none, job('sample', 'running'))
    step = poll(step.view, job('sample', 'done'))
    step = poll(step.view, job('render', 'running', 'render-1'))
    expect(step.card?.kind).toBe('render')
    step = poll(step.view, job('render', 'done', 'render-1'))
    expect(step.card).toBeNull()
  })

  it('shows a second sample, and the first one’s watched mark does not carry over to an old one', () => {
    let step = poll(none, job('sample', 'running', 's1'))
    step = poll(step.view, job('sample', 'done', 's1'))
    step = poll(step.view, job('sample', 'running', 's2'))
    expect(step.card?.id).toBe('s2')
    step = poll(step.view, job('sample', 'done', 's2'))
    expect(step.card?.id).toBe('s2')
    // the page is opened again: nothing watched, the last sample is old news
    expect(poll(none, job('sample', 'done', 's2')).card).toBeNull()
  })

  it('shows a failed or cancelled sample, as it always did', () => {
    for (const state of ['failed', 'cancelled', 'interrupted']) expect(poll(none, job('sample', state)).card?.state).toBe(state)
  })

  it('shows nothing when there is no job', () => {
    expect(poll(none, null).card).toBeNull()
  })
})
