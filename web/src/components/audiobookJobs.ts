// Which job the Audiobooks page shows a card for, kept apart from the page so it can be tested.
//
// The tool reports one job: the latest, running or finished. A finished one is hidden at once, so an old
// "done" card does not greet someone who opens the page. A voice sample is the exception: it is something a
// person just asked for, and its card is where they play it, so a sample this page watched run stays on screen
// after it finishes (as a failed job's card already does) until another job takes its place.

export interface JobView {
  /** A finished job the page has hidden. */
  hiddenId: string
  /** The last sample job this page saw running. */
  watchedSampleId: string
}

/** The parts of a job this needs: the page's own `BookJob` has them. */
interface Seen { id: string; kind: string; state: string }

/** What `hiddenId` and `watchedSampleId` become when the page sees this job. */
export function seeing(job: Seen | null, view: JobView): JobView {
  if (!job) return view
  if (job.state === 'running') return { hiddenId: '', watchedSampleId: job.kind === 'sample' ? job.id : view.watchedSampleId }
  if (job.state === 'done') return { ...view, hiddenId: job.id }
  return view
}

/** The job to show a card for: any job that has not been hidden, and a sample this page watched run. */
export function shown<J extends Seen>(job: J | null, view: JobView): J | null {
  if (!job) return null
  if (job.id !== view.hiddenId) return job
  return job.kind === 'sample' && job.id === view.watchedSampleId ? job : null
}
