// What an email's text looks like on the page. mail-ai turns HTML mail into text, and a newsletter's layout
// tables become hundreds of empty lines: one real message was 431 blank lines of 462, with 122 in a row, so
// the page showed "96" and a screen of nothing. Shown, not changed: the stored text is untouched.
//
// Read as structure since 2026-11-07 (the user: "no paragraphs, no structure"). Measured on the latest 400
// messages in the mailbox: 40% of all their text was links (median 364 characters, 1,672 of 2,345 over 200),
// 99 had sentences broken at a fixed width by the sender's mail program, and about 80 had a blank line between
// every line. So a paragraph's wrapped lines are joined again, lists, quotes and rules are found, and a link
// shows where it goes in a few characters instead of its whole address. Text only: nothing becomes markup.

// Characters that render as nothing but keep a line from counting as empty (layout padding in HTML mail).
const INVISIBLE = /[ ͏᠎​-‏⁠﻿]/g

// A run of them inside a line is a newsletter's preview padding: a real one put 174 joiners, 105 zero-width
// non-joiners and 98 no-break spaces after its first sentence, and the spaces wrapped into lines that looked empty
// (63 of the latest 400 messages had such runs, 2026-11-07). A run becomes one space; one alone stays, as the
// joiner inside an emoji such as a family does.
const PADDING_RUN = /(?:[\u00a0\u00ad\u034f\u180e\u200b-\u200f\u2060\ufeff][ \t]*){2,}/g

/** Lines that hold only spaces or invisible characters become empty; runs of empty lines become one; preview
 *  padding inside a line becomes a space. */
export function cleanBody(text: string): string {
  const lines = text.replace(/\r\n?/g, '\n').split('\n')
    .map((line) => (line.replace(INVISIBLE, '').trim() === '' ? '' : line.replace(PADDING_RUN, ' ').replace(/\s+$/, '')))
  const kept: string[] = []
  for (const line of lines) {
    if (line === '' && (kept.length === 0 || kept[kept.length - 1] === '')) continue
    kept.push(line)
  }
  while (kept.length && kept[kept.length - 1] === '') kept.pop()
  return kept.join('\n')
}

export const URL_RE = /https?:\/\/[^\s<>"')\]]+/g

/** Where a link goes, short enough to read: its site, and "/…" when it goes deeper than the front page. */
export function shortLink(url: string): string {
  try {
    const u = new URL(url)
    const host = u.hostname.replace(/^www\./, '')
    const deeper = (u.pathname && u.pathname !== '/') || u.search || u.hash
    return `${host}${deeper ? '/…' : ''}`
  } catch {
    return url.length > 40 ? `${url.slice(0, 39)}…` : url
  }
}

/** The opening of a message on one line, for a folded message or a list row: whole words, then "…". */
export function firstWords(text: string, max = 140): string {
  const flat = cleanBody(text).replace(URL_RE, (url) => shortLink(url)).replace(/\s+/g, ' ').trim()
  if (flat.length <= max) return flat
  const cut = flat.slice(0, max)
  const space = cut.lastIndexOf(' ')
  return `${(space > max * 0.6 ? cut.slice(0, space) : cut).replace(/[\s,;:.–—-]+$/, '')}…`
}

// ---- a body as blocks -----------------------------------------------------------------------------------

/** Text, or a link shown by where it goes. */
export type Inline = string | { href: string; label: string }
/** One line of a block: its text and links in order. */
export type Line = Inline[]
export type Block =
  | { kind: 'p'; lines: Line[] }   // lines that were really separate (a signature, an address) stay separate
  | { kind: 'list'; ordered: boolean; items: Line[] }
  | { kind: 'quote'; blocks: Block[] }
  | { kind: 'rule' }

const RULE = /^\s*([-=_*~•·]\s*){3,}$/
const ITEM = /^\s*(?:[-*•·–]|\d{1,3}[.)])\s+(.*)$/
/** A bullet alone on its line, its item's words on the lines under it (a real security notice, 2026-11-07). A lone
 *  dash is not one: it separates as often as it lists. */
const LONE_BULLET = /^\s*[*•·]\s*$/
const ORDERED = /^\s*\d{1,3}[.)]\s/
const QUOTED = /^\s*>/

/** A line's text and its links, each link without the punctuation that ends the sentence around it. */
export function inlines(text: string): Line {
  const parts: Line = []
  let last = 0
  for (const m of text.matchAll(URL_RE)) {
    const at = m.index!
    let url = m[0]
    while (url.length > 8 && /[.,;:!?)>\]}]$/.test(url)) url = url.slice(0, -1)
    if (at > last) parts.push(text.slice(last, at))
    parts.push({ href: url, label: shortLink(url) })
    last = at + url.length
  }
  if (last < text.length) parts.push(text.slice(last))
  return parts.length ? parts : ['']
}

/** A line that is only a link, bare or in brackets: what a mail program writes after a link's words. */
const LINK_ONLY = /^\s*[(<[]?https?:\/\/\S+?[)>\]]?[.,;:!?]?\s*$/

/** A wrapped paragraph's lines joined again, where the sender's program broke them and only there. A break is
 *  the program's when the next word would not have fitted on the line: the width is the longest line of the
 *  paragraph that could have been wrapped (100 characters or fewer), and below 40 nothing was wrapped at all.
 *  A line that is only a link always joins the words above it, whatever the width ("Unsubscribe (link)"). */
export function reflow(lines: string[]): string[] {
  const width = Math.max(0, ...lines.filter((l) => l.length <= 100).map((l) => l.length))
  const out: string[] = [lines[0]!]
  for (let i = 1; i < lines.length; i++) {
    const before = lines[i - 1]!
    const next = lines[i]!.trimStart()
    const word = next.split(/\s/, 1)[0] ?? ''
    const wrapped = width >= 40 && before.length <= 100 && before.length + 1 + word.length > width
    if (wrapped || (LINK_ONLY.test(next) && before.trim())) out[out.length - 1] += ` ${next}`
    else out.push(lines[i]!)
  }
  return out
}

/** A line longer than this, never broken by its sender, is an article on one line: a real LinkedIn digest put
 *  10,502 characters on one (2026-11-07). It is shown as paragraphs of a few sentences each, broken only where a
 *  sentence ends; the words and their order are the sender's. */
const ONE_LINE_ARTICLE = 700
const PARAGRAPH = 320

/** An article written on one line, as paragraphs. Without a sentence ending in it, it stays whole. */
export function paragraphsOf(line: string): string[] {
  const sentences = line.split(/(?<=[.!?…]["”’)]?)\s+(?=["“(]?[A-Z0-9])/)
  const out: string[] = []
  let current = ''
  for (const sentence of sentences) {
    current = current ? `${current} ${sentence}` : sentence
    if (current.length >= PARAGRAPH) { out.push(current); current = '' }
  }
  if (current) out.push(current)
  return out
}

const shownLength = (line: string) => line.replace(URL_RE, 'x'.repeat(20)).length

function dedent(lines: string[]): string[] {
  const indent = Math.min(...lines.filter((l) => l.trim()).map((l) => l.match(/^\s*/)![0].length))
  return Number.isFinite(indent) && indent > 0 ? lines.map((l) => l.slice(indent)) : lines
}

/** One group of lines with no blank line between them, as blocks. */
function group(raw: string[]): Block[] {
  const lines = dedent(raw)
  const blocks: Block[] = []
  let text: string[] = []
  let quote: string[] = []
  let list: { ordered: boolean; items: string[]; loose: boolean } | null = null

  const flushText = () => {
    if (!text.length) return
    let lines: string[] = []
    const push = () => { if (lines.length) blocks.push({ kind: 'p', lines: lines.map((l) => inlines(l)) }); lines = [] }
    for (const line of reflow(text).map((l) => l.trim())) {
      if (shownLength(line) <= ONE_LINE_ARTICLE) { lines.push(line); continue }
      push()
      for (const part of paragraphsOf(line)) blocks.push({ kind: 'p', lines: [inlines(part)] })
    }
    push()
    text = []
  }
  const flushQuote = () => {
    if (quote.length) blocks.push({ kind: 'quote', blocks: parseBody(quote.map((l) => l.replace(/^\s*>\s?/, '')).join('\n')) })
    quote = []
  }
  const flushList = () => {
    if (list) {
      const items = list.items.filter((t) => t)
      if (items.length) blocks.push({ kind: 'list', ordered: list.ordered, items: items.map((t) => inlines(t)) })
    }
    list = null
  }

  for (const line of lines) {
    if (QUOTED.test(line)) { flushText(); flushList(); quote.push(line); continue }
    flushQuote()
    if (RULE.test(line)) { flushText(); flushList(); blocks.push({ kind: 'rule' }); continue }
    if (LONE_BULLET.test(line)) {
      flushText()
      if (!list || list.ordered) { flushList(); list = { ordered: false, items: [], loose: true } }
      list.items.push('')
      list.loose = true
      continue
    }
    const item = line.match(ITEM)
    if (item) {
      flushText()
      const ordered = ORDERED.test(line)
      if (!list || list.ordered !== ordered) { flushList(); list = { ordered, items: [], loose: false } }
      list.items.push(item[1]!.trim())
      list.loose = false
      continue
    }
    // An indented line under an item carries on that item, and so does any line under a bullet that stood alone;
    // anything else ends the list.
    if (list && (list.loose || /^\s/.test(line))) {
      const last = list.items.length - 1
      list.items[last] = `${list.items[last]} ${line.trim()}`.trim()
      continue
    }
    flushList()
    text.push(line)
  }
  flushText()
  flushQuote()
  flushList()
  return blocks
}

// A style sheet left in a message's plain text: a real security notice (2026-11-07) ended with 135 lines of the
// HTML version's CSS. A rule is a selector and "{", with "name: value" inside; it runs to its matching "}". Braces
// with no declaration inside ("use {name} here") are words, and stay.
// A selector: names, classes and ids, [attribute] and (argument) groups, and the spaces and >+~ between them. No
// bare "=", so "const config = {" in a code sample is not one.
const CSS_OPEN = /^\s*(?:@[\w-]+[^{}]*|(?:[.#:*\w-]|\[[^\]]*\]|\([^)]*\)|[\s,>+~])*)\{/
/** A line of selector only, its "{" on a line below: a real one ran over three lines (2026-11-07). It must hold a
 *  .class, a :pseudo-class, a child ">" or an [attribute], and not end as a sentence does, so a word ("Thanks"), a
 *  sentence ("All rights reserved.") and hashtags ("#Hiring #AI", in real LinkedIn mail) never are one. */
const SELECTOR_ONLY = /^\s*(?:[.#:*\w-]|\[[^\]]*\]|\([^)]*\)|[\s,>+~])+$/
const looksSelector = (line: string) =>
  SELECTOR_ONLY.test(line) && !/[.!?]\s*$/.test(line) && /(?:^|[\s>+~,])\.[\w-]|[\w)\]]:[\w-]|>|\[/.test(line)
const CSS_DECL = /[\w-]+\s*:\s*[^;{}\s][^;{}]*/

/** "name:" with its value on the next line. */
const PROP_ONLY = /^\s*[\w-]+\s*:\s*$/

function cssStarts(lines: string[], i: number): boolean {
  const line = lines[i]!
  if (!CSS_OPEN.test(line)) return false
  const after = line.slice(line.indexOf('{') + 1)
  if (CSS_DECL.test(after) || PROP_ONLY.test(after)) return true
  // "pre {" with "font-family:" under it, or "@media (…) {" with a rule under it (real messages, 2026-11-07)
  const next = lines.slice(i + 1).find((l) => l.trim()) ?? ''   // a blank line may come between (a real @media did)
  return after.trim() === '' && (CSS_DECL.test(next) || PROP_ONLY.test(next) || looksSelector(next) || CSS_OPEN.test(next))
}

/** Where a rule that opens on line i closes, or -1 when it does not close within 400 lines: then it was words with a
 *  brace in them, and leaving out everything after it would hide the rest of the message. */
function ruleEnd(lines: string[], i: number): number {
  let depth = 0
  for (let k = i; k < Math.min(lines.length, i + 400); k++) {
    depth += (lines[k]!.match(/\{/g)?.length ?? 0) - (lines[k]!.match(/\}/g)?.length ?? 0)
    if (depth <= 0) return k
  }
  return -1
}

/** The lines, without any style-sheet rules in them. */
export function withoutCss(lines: string[]): string[] {
  const out: string[] = []
  for (let i = 0; i < lines.length; i++) {
    if (cssStarts(lines, i)) {
      const end = ruleEnd(lines, i)
      if (end >= 0) {
        // the rest of its selector, on the lines just above
        while (out.length && looksSelector(out[out.length - 1]!)) out.pop()
        i = end
        continue
      }
    }
    out.push(lines[i]!)
  }
  return out
}

/** A message's text as paragraphs, lists, quotes and rules. A blank line always separates. */
export function parseBody(text: string): Block[] {
  const cleaned = cleanBody(withoutCss(cleanBody(text).split('\n')).join('\n'))
  if (!cleaned) return []
  return cleaned.split(/\n\n/).flatMap((chunk) => group(chunk.split('\n')))
}
