import { mkdir, writeFile } from 'node:fs/promises'
import { extname, join, resolve } from 'node:path'
import type { ExportFormat, ExportResult } from './drive.js'

/**
 * Saving an export as a file, for another tool to take it from (2026-10-30).
 *
 * A file cannot travel through a model. A Word CV is ~650 KB, which is at least 217,000 tokens as base64, and one
 * model reply holds 16,000: the model would have to copy the bytes into its next call, and cannot. So Shelby
 * gives docu-ai one folder (`DOCU_AI_EXPORTS`), this writes the file there and hands back only its path, and
 * mail-ai, given the same folder, attaches from it. The folder is injected; docu-ai never chooses or finds one.
 */

export interface SavedExport {
  documentId: string
  format: ExportFormat
  filename: string
  path: string
  size: number
}

const EXTENSION: Record<ExportFormat, string> = { pdf: '.pdf', docx: '.docx' }
// The marks that reverse how a name reads (an "exe.docx" that shows as "xcod.exe"). Written as escapes: the
// characters themselves are invisible, and must not sit in source code either.
const REVERSING = /[\u202a-\u202e\u2066-\u2069]/
const MAX_NAME = 120

/** A control character, either slash, or a reversing mark: none has a place in a name a recipient will see. */
function unsafe(name: string): boolean {
  for (const ch of name) {
    const code = ch.codePointAt(0) ?? 0
    if (code < 0x20 || code === 0x7f || ch === '/' || ch === '\\') return true
  }
  return REVERSING.test(name)
}

/**
 * The file's name: the one asked for, or the document's own, always ending in the format's extension. A name that
 * ends in the other format's extension is refused rather than given a second one ("cv.pdf.docx").
 */
export function exportName(requested: string | undefined, fallback: string, format: ExportFormat): string {
  const ext = EXTENSION[format]
  let name = (requested ?? '').trim() || fallback.trim()
  const given = extname(name).toLowerCase()
  if (given === '.pdf' || given === '.docx') {
    if (given !== ext) throw new Error(`"${name}" ends in ${given}, but the export is ${ext}: name it ${ext}, or ask for the other format.`)
  } else {
    name += ext
  }
  const stem = name.slice(0, -ext.length)
  if (!stem || stem.startsWith('.') || unsafe(name) || name.length > MAX_NAME) {
    throw new Error(`"${name}" is not a name a file can be saved under: no slash, no hidden or control character, no leading dot, at most ${MAX_NAME} characters.`)
  }
  return name
}

/** `name.docx`, then `name (2).docx`: what is already there is never overwritten. */
async function writeNew(folder: string, name: string, bytes: Buffer): Promise<string> {
  const ext = extname(name)
  const stem = name.slice(0, name.length - ext.length)
  for (let n = 1; n < 1000; n++) {
    const candidate = n === 1 ? name : `${stem} (${n})${ext}`
    try {
      await writeFile(join(folder, candidate), bytes, { flag: 'wx' }) // fails if it exists: no check-then-write race
      return candidate
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'EEXIST') throw error
    }
  }
  throw new Error(`Too many files called ${name} in the exports folder already.`)
}

export async function saveExport(folder: string | undefined, result: ExportResult, requested?: string): Promise<SavedExport> {
  if (!folder) {
    throw new Error('No exports folder: Shelby gives docu-ai one in DOCU_AI_EXPORTS. Run on its own, use the CLI\'s export instead.')
  }
  const root = resolve(folder)
  const name = exportName(requested, result.filename, result.format)
  await mkdir(root, { recursive: true })
  const filename = await writeNew(root, name, result.bytes)
  return { documentId: result.documentId, format: result.format, filename, path: join(root, filename), size: result.bytes.length }
}
