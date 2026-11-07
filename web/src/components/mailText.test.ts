import { describe, expect, it } from 'vitest'
import { cleanBody, firstWords, parseBody, shortLink, type Block, type Line } from './mailText'

describe('cleanBody', () => {
  it('folds a newsletter run of blank lines to one, as the real one with 122 in a row', () => {
    const text = `96                   ${'\n'.repeat(122)}Security Incident Update${'\n'.repeat(17)}Dear Binancian,\n\n\nWe are writing.`
    expect(cleanBody(text)).toBe('96\n\nSecurity Incident Update\n\nDear Binancian,\n\nWe are writing.')
  })

  it('counts a line of spaces or invisible padding as empty', () => {
    expect(cleanBody('a\n   \n ‌͏\n\t\nb')).toBe('a\n\nb')
  })

  it('keeps a single blank line between paragraphs and the indentation inside a line', () => {
    expect(cleanBody('Hi,\n\n  > quoted\nThanks')).toBe('Hi,\n\n  > quoted\nThanks')
  })

  it('turns a newsletter\'s preview padding inside a line into one space, and keeps a joiner inside an emoji', () => {
    expect(cleanBody(`Philips, you follow them on TikTok.${'\u034f\u200c\u00a0'.repeat(98)}\nNext`)).toBe('Philips, you follow them on TikTok.\nNext')
    expect(cleanBody('Family 👨\u200d👩\u200d👧 photo')).toBe('Family 👨\u200d👩\u200d👧 photo')
  })

  it('drops blank lines at the start and the end, and Windows line ends', () => {
    expect(cleanBody('\r\n\r\nHello\r\n\r\n\r\n')).toBe('Hello')
  })

  it('leaves empty text empty', () => {
    expect(cleanBody('')).toBe('')
    expect(cleanBody('\n\n \n')).toBe('')
  })
})

describe('firstWords', () => {
  it('puts the opening on one line', () => {
    expect(firstWords('Dear Ann,\n\n\nThe review moved\nto Tuesday.')).toBe('Dear Ann, The review moved to Tuesday.')
  })

  it('cuts at a word, not inside one, and says it was cut', () => {
    const cut = firstWords('one two three four five six seven', 20)
    expect(cut).toBe('one two three four…')
  })

  it('keeps a short text whole', () => {
    expect(firstWords('Tuesday works.', 140)).toBe('Tuesday works.')
  })
})

// Shaped like the latest 400 real messages (2026-11-07), with invented words: sentences broken at a fixed width,
// tracking links of hundreds of characters, a label with its link on the next line, a blank line between every line.
const TRACK = `https://click.news.example.com/f/a/${'Zx9q'.repeat(80)}~~/AAAAAQA~/RgRn${'k2'.repeat(40)}`

const words = (b: Block): string => {
  const line = (l: Line) => l.map((p) => (typeof p === 'string' ? p : `[${p.label}]`)).join('')
  if (b.kind === 'p') return b.lines.map(line).join(' / ')
  if (b.kind === 'list') return b.items.map(line).join(' | ')
  if (b.kind === 'quote') return `> ${b.blocks.map(words).join(' ')}`
  return '---'
}

describe('parseBody', () => {
  it('joins a sentence the sender\'s program broke at a fixed width into one paragraph', () => {
    const text = 'Thank you for joining the planning meeting yesterday. The notes are\n' +
      'attached, and the decisions we made about the March budget are listed\n' +
      'at the end so nobody has to read the whole thing again.'
    const blocks = parseBody(text)
    expect(blocks).toHaveLength(1)
    expect(blocks[0]).toEqual({ kind: 'p', lines: [[text.replace(/\n/g, ' ')]] })
  })

  it('keeps lines that were meant to be separate, as in a signature or an address', () => {
    expect(parseBody('Best regards,\nAma Mensah\nAccra, Ghana').map(words)).toEqual(['Best regards, / Ama Mensah / Accra, Ghana'])
    // A greeting above a wrapped paragraph keeps its own line; the paragraph under it is joined.
    const mixed = 'Hi Sam,\nThe review moved to Tuesday because two of the people who need to be\nthere are travelling on Monday.'
    expect(parseBody(mixed).map(words)).toEqual([
      'Hi Sam, / The review moved to Tuesday because two of the people who need to be there are travelling on Monday.',
    ])
  })

  it('shows a long link by where it goes, keeping the whole address to open', () => {
    const [p] = parseBody(`Read the full story here: ${TRACK}.`)
    expect(p).toEqual({ kind: 'p', lines: [['Read the full story here: ', { href: TRACK, label: 'click.news.example.com/…' }, '.']] })
  })

  it('puts a link that sits on its own line beside the words it belongs to', () => {
    const text = 'A new reply was posted in the discussion you follow\n' +
      `(${TRACK})`
    expect(parseBody(text).map(words)).toEqual(['A new reply was posted in the discussion you follow ([click.news.example.com/…])'])
  })

  it('makes a list of lines that start with a bullet or a number, an indented line carrying on its item', () => {
    const blocks = parseBody('What changed:\n- the deadline moved to Friday\n- two reviewers instead of one, so the\n  draft goes out earlier\n\n1. Read it\n2. Reply')
    expect(blocks.map((b) => b.kind)).toEqual(['p', 'list', 'list'])
    expect(blocks[1]).toMatchObject({ ordered: false })
    expect(words(blocks[1]!)).toBe('the deadline moved to Friday | two reviewers instead of one, so the draft goes out earlier')
    expect(blocks[2]).toMatchObject({ ordered: true })
    expect(words(blocks[2]!)).toBe('Read it | Reply')
  })

  it('shows quoted lines as a quote, and a line of dashes as a rule', () => {
    const blocks = parseBody('Sounds good.\n\n> On Monday Ama wrote:\n> Can we meet at 3?\n\n-----\nSent from my phone')
    expect(blocks.map(words)).toEqual(['Sounds good.', '> On Monday Ama wrote: / Can we meet at 3?', '---', 'Sent from my phone'])
  })

  it('keeps a blank line between every line as separate short paragraphs, never one wall', () => {
    const blocks = parseBody('Your order\n\n\nhas shipped\n\n\n\nTrack it below')
    expect(blocks.map(words)).toEqual(['Your order', 'has shipped', 'Track it below'])
  })

  it('takes off the indentation a newsletter puts in front of every line', () => {
    expect(parseBody('    Weekly digest\n    Three new posts this week')).toEqual([
      { kind: 'p', lines: [['Weekly digest'], ['Three new posts this week']] },
    ])
  })

  it('does not join a heading to a very long line, and leaves a long line with no sentence end whole', () => {
    const long = 'word '.repeat(2000).trim()
    expect(parseBody(`Today\n${long}`).map(words)).toEqual(['Today', long])
  })

  it('shows an article written on one line as paragraphs of a few sentences, every word kept in order', () => {
    const sentence = (i: number) => `Sentence number ${i} says something about the week, and it goes on for a while.`
    const article = Array.from({ length: 40 }, (_, i) => sentence(i + 1)).join(' ')
    const blocks = parseBody(`Welcome back!\n\n${article}`)
    expect(blocks.length).toBeGreaterThan(5)
    expect(blocks.slice(1).map(words).join(' ')).toBe(article)
    expect(blocks.slice(1).every((b) => words(b).length < 450)).toBe(true)
    expect(blocks.slice(1).every((b) => /[.!?]$/.test(words(b)))).toBe(true)
  })

  it('has nothing to show for empty text', () => {
    expect(parseBody('\n \n')).toEqual([])
  })
})

describe('shortLink', () => {
  it('names the site without www, and says when the link goes deeper', () => {
    expect(shortLink('https://www.example.com/')).toBe('example.com')
    expect(shortLink('https://www.example.com')).toBe('example.com')
    expect(shortLink('https://docs.example.com/a/b?c=1')).toBe('docs.example.com/…')
  })

  it('shortens what is not a link it can read', () => {
    const broken = `https://[${'x'.repeat(60)}`   // a bracket opens an address URL() cannot read
    expect(shortLink(broken)).toBe(`${broken.slice(0, 39)}…`)
  })
})

describe('firstWords with links', () => {
  it('names a link by its site in the one-line opening', () => {
    expect(firstWords(`Your report is ready ${TRACK}`)).toBe('Your report is ready click.news.example.com/…')
  })
})

describe('parseBody, from a real security notice (2026-11-07), words invented', () => {
  const notice = [
    'Hello, sam.', '',
    'Staying secure:', '',
    '*', 'To save your recovery codes, visit account settings', '(https://example.com/account/settings).',
    '*', 'Keep your authenticator app safe.',
    '*', 'Never share your codes.', '',
    'Learn more about account security', '(https://example.com/docs/security).', '',
    ':root { color-scheme: light dark; }', '',
    '.body { background-color: #ffffff; margin: 0; padding: 0; }',
    '.outer-table, .outer-td { background-color: #ffffff; }', '',
    'p {', 'color: #171717;', "font-family: -apple-system,'Segoe", "UI',sans-serif;", 'margin: 0 0 16px 0;', '}',
    '@media (max-width: 600px) {', '.wrapper { width: 100% !important; }', '}',
    '', 'pre {', 'font-family:', "ui-monospace,SFMono-Regular,Menlo,'Liberation", "Mono',monospace;", '}',
    '.block-row .block-button { display:', 'inline-block; box-sizing: border-box; }',
    'li:not(:first-child) { margin-top: 0; }', 'a[href^="tel"] { color: inherit; }',
    '.block-row.block-row--button_set-v1', '.block-row .block-markdown > :first-child', '{ margin-top: 0; }',
    '', '@media (prefers-color-scheme: dark) {', '.block-row.block-row--button_set-v1', '.block-row .block-button {', 'color: #fff;', '}', '}',
    '@media (prefers-color-scheme: dark) {', '', '.vercel-label { color: #ededed !important; }', '}',
    '@media (prefers-color-scheme: dark) {', '.body, .outer-td { background-color:', '#111111 !important; }', '}',
  ].join('\n')

  it('makes a list of bullets that stand alone on their lines, each with the words under it', () => {
    const blocks = parseBody(notice)
    expect(blocks.map((b) => b.kind)).toEqual(['p', 'p', 'list', 'p'])
    expect(words(blocks[2]!)).toBe('To save your recovery codes, visit account settings ([example.com/…]). | Keep your authenticator app safe. | Never share your codes.')
  })

  it('leaves out the style sheet at the end, every rule of it', () => {
    const text = parseBody(notice).map(words).join('\n')
    expect(text).not.toMatch(/[{}]|color|@media|font-family/)
    expect(words(parseBody(notice).at(-1)!)).toBe('Learn more about account security ([example.com/…]).')
  })

  it('keeps braces that hold words, not a rule', () => {
    expect(parseBody('Note {\nSubject: the plan\nMore words follow here.').map((b) => b.kind)).toEqual(['p'])   // never closed: words
    expect(parseBody('const config = {\n  port: 8080,\n}').map(words)).toEqual(['const config = { / port: 8080, / }'])
    expect(parseBody('Thanks\n{ see: below }').map(words)).toEqual(['Thanks'])   // the braces go; the word above stays
    expect(parseBody('#Hiring #Startups #AI\nAll rights reserved.\n.footer { color: #999; }').map(words)).toEqual(['#Hiring #Startups #AI / All rights reserved.'])
    expect(parseBody('Copy the .env file first.\n.footer { color: #999; }').map(words)).toEqual(['Copy the .env file first.'])
    expect(parseBody('Use {name} in the subject line.').map(words)).toEqual(['Use {name} in the subject line.'])
    expect(parseBody('Totals {by region}: see below').map(words)).toEqual(['Totals {by region}: see below'])
  })

  it('does not take a lone dash for a bullet', () => {
    expect(parseBody('Ama\n-\nAccra').map((b) => b.kind)).toEqual(['p'])
  })
})
