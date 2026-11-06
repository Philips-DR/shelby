// A reply as the voice should say it, and in what pieces. Kept apart from the player so it can be tested.

const SENTENCE_END = /(?<=[.!?…])["'”’)\]]*\s+(?=["'“‘(\[]?[A-Z0-9])/
// "Dr. Mensah", "e.g. this": a split after one of these is joined again (audiobook's chunk.py does the same).
const ABBREVIATIONS = ['Mr.', 'Mrs.', 'Ms.', 'Dr.', 'St.', 'Prof.', 'Sr.', 'Jr.', 'vs.', 'etc.', 'e.g.', 'i.e.', 'No.']
/** Under this, a sentence goes with the next, so a "Yes." is not a call of its own. Not the first: it starts the sound. */
const SHORT = 40
/** One call says at most this much (audiobook's speak takes 600; a sentence near it is cut at a comma). */
const LONGEST = 400

const ended = (line: string) => (/[.!?…:;]$/.test(line) ? line : `${line}.`)

/** Markdown to plain sentences. Code and tables are said to be on screen, never read out; a link is read by its words. */
export function speakable(markdown: string): string {
  const lines: string[] = []
  let fence = false
  let table = false
  for (const raw of markdown.replace(/\r/g, '').split('\n')) {
    const line = raw.trim()
    if (/^(```|~~~)/.test(line)) {
      if (!fence) lines.push('There is code on screen.')
      fence = !fence
      continue
    }
    if (fence) continue
    if (/^\|.*\|$/.test(line)) {
      if (!table) lines.push('There is a table on screen.')
      table = true
      continue
    }
    table = false
    if (!line || /^([-*_])(\s*\1){2,}$/.test(line)) { lines.push(''); continue }
    const text = line
      .replace(/^#{1,6}\s+/, '')
      .replace(/^>\s?/, '')
      .replace(/^([-*+]|\d+[.)])\s+(\[[ xX]\]\s+)?/, '')
      .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
      .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
      .replace(/<https?:[^>]+>|https?:\/\/\S+/g, 'a link')
      .replace(/`([^`]*)`/g, '$1')
      .replace(/(\*\*|__|~~)(.+?)\1/g, '$2')
      .replace(/(^|[\s(])[*_](\S(?:.*?\S)?)[*_](?=[\s).,!?:;]|$)/g, '$1$2')
      .replace(/<[^>]+>/g, '')
      .trim()
    if (text) lines.push(ended(text))
  }
  return lines.filter(Boolean).join(' ').replace(/\s{2,}/g, ' ').trim()
}

function sentences(text: string): string[] {
  const out: string[] = []
  for (const part of text.split(SENTENCE_END)) {
    const last = out[out.length - 1]
    if (last !== undefined && ABBREVIATIONS.some((a) => last.endsWith(a))) out[out.length - 1] = `${last} ${part}`
    else out.push(part)
  }
  return out.map((s) => s.trim()).filter(Boolean)
}

/** A sentence too long for one call, cut at commas (or, failing that, spaces) into pieces under the limit. */
function cut(sentence: string, limit: number): string[] {
  if (sentence.length <= limit) return [sentence]
  const out: string[] = []
  let rest = sentence
  while (rest.length > limit) {
    const window = rest.slice(0, limit)
    const at = Math.max(window.lastIndexOf(', '), window.lastIndexOf('; '))
    const end = at > limit / 3 ? at + 1 : window.lastIndexOf(' ') > 0 ? window.lastIndexOf(' ') : limit
    out.push(rest.slice(0, end).trim())
    rest = rest.slice(end).trim()
  }
  if (rest) out.push(rest)
  return out
}

/** The pieces sent one call at a time: the first sentence alone (the sound starts sooner), then a sentence each,
 * a short one joined to the next. */
export function pieces(text: string, limit = LONGEST): string[] {
  const out: string[] = []
  for (const sentence of sentences(text).flatMap((s) => cut(s, limit))) {
    const last = out[out.length - 1]
    if (out.length > 1 && last !== undefined && last.length < SHORT && last.length + 1 + sentence.length <= limit) out[out.length - 1] = `${last} ${sentence}`
    else out.push(sentence)
  }
  return out
}
