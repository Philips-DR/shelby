import { basename } from 'node:path'
import type { AuthProvider } from './auth/types.js'
import { documentInfo, explainFailureWithDrive, trashDocument, type DocumentInfo } from './drive.js'
import { buildFromPlan } from './emit/document.js'
import { loadChapters } from './parse/loadDir.js'
import { parseMarkdown } from './parse/toAst.js'
import { planChapter, planDocument } from './plan/fromAst.js'
import type { Block } from './plan/types.js'
import { letter } from './theme/presets/letter.js'
import { resume } from './theme/presets/resume.js'
import { technical } from './theme/presets/technical.js'
import type { Theme } from './theme/types.js'
import { measureLayout, type LayoutResult } from './verify/layout.js'
import { countParagraphs, fetchDocument, residueFindings } from './verify/readback.js'

export { documentInfo, exportDocument, listDocuments, renameDocument, trashDocument } from './drive.js'
export { exportName, saveExport, type SavedExport } from './exports.js'
export type { DocumentInfo, ExportFormat, ExportResult, ListDocumentsResult, ListedDocument, TrashResult } from './drive.js'
export type { LayoutResult } from './verify/layout.js'

/**
 * The looks a caller may ask for by name. A front door takes a name, never a Theme object: a
 * model choosing from two words cannot hand over a half-built theme, and a new preset becomes
 * available everywhere by being added here.
 */
export const THEMES = { technical, resume, letter } as const
export type ThemeName = keyof typeof THEMES

/**
 * What docu-ai can be asked to do, as data in and data out.
 *
 * Both front doors sit on this: the CLI formats these results for a person, the MCP server returns
 * them as JSON to a model. Neither wraps the other, which is the point — a front door that
 * delegates to the other one inherits its output format, its exit codes and its assumptions about
 * who is reading, and the two drift the moment either is changed for its own audience.
 *
 * Nothing here writes to stdout or sets an exit code. That is a front door's job.
 */

/** Recursively tallies block kinds — blockquotes aren't a kind of their own here, their contents are. */
export function countBlockKinds(
  blocks: Block[],
  counts: Record<string, number> = {},
): Record<string, number> {
  for (const block of blocks) {
    if (block.kind === 'blockquote') {
      countBlockKinds(block.children, counts)
      continue
    }
    counts[block.kind] = (counts[block.kind] ?? 0) + 1
  }
  return counts
}

export interface ChapterPreview {
  title: string
  file: string
  blocks: Record<string, number>
}

export interface PreviewResult {
  chapters: ChapterPreview[]
  /** A single file: built as one tab with no cover. */
  single: boolean
}

/**
 * Parse + plan only — no network, no API quota spent, nothing created.
 *
 * Every tool in Shelby owes a preview: it is what turns human-in-the-loop from a convention
 * somebody has to remember into a property of the tool. It is also the only operation here that
 * takes no AuthProvider, and that is the whole idea.
 */
export async function preview(path: string): Promise<PreviewResult> {
  const { files, single } = await loadChapters(path)
  if (files.length === 0) throw new Error(`no .md files found in ${path}`)

  return {
    single,
    chapters: files.map((file) => {
      const chapter = planChapter(parseMarkdown(file.source), file.slug, basename(file.path))
      return {
        title: chapter.title,
        file: basename(file.path),
        blocks: countBlockKinds(chapter.blocks),
      }
    }),
  }
}

export interface BuildResult {
  documentId: string
  url: string
  title: string
  chapters: string[]
  paragraphs: number
  residue: string[]
  imageWarnings: string[]
  /**
   * Where Docs put the page breaks — page count, and a warning for a heading stranded at a page foot,
   * a page target missed, or a stray last page. `measured: false` (with a reason) when it could not be
   * read; never absent, so "no warnings" can only mean the layout was looked at and was fine.
   */
  layout: LayoutResult
  /** Present only when `replaces` was given: what became of the document this one supersedes. */
  replaced?: ReplacedResult
}

export interface ReplacedResult {
  documentId: string
  title: string
  /** True only if the document is now in Drive's Trash. */
  trashed: boolean
  /** What happened to it, in a sentence, and if it is still there, why. */
  note: string
}

/**
 * Before a build is spent: is this a document docu-ai may trash? Reads only. A wrong id found here costs
 * nothing; found after the build it would cost a document nobody asked for. `drive.file` is the only Drive
 * scope held, so a document docu-ai did not build cannot be seen at all, and is refused here.
 */
export async function checkReplaceable(auth: AuthProvider, documentId: string): Promise<DocumentInfo> {
  const info = await documentInfo(auth, documentId)
  if (info.trashed) throw new Error(`"${info.title}" is already in the Trash, so there is nothing to replace.`)
  return info
}

/**
 * What is wrong with a finished build, in words: markdown left in it, or a layout warning. Empty means clean.
 * A layout that could not be measured is not a warning found, and says so on its own (`measured: false`).
 */
function problemsWith(built: { residue: string[]; layout: LayoutResult }): string[] {
  const problems: string[] = []
  if (built.residue.length > 0) problems.push(`${built.residue.length} piece(s) of markdown left in it`)
  if (built.layout.measured && built.layout.warnings.length > 0) {
    problems.push(`${built.layout.warnings.length} layout warning(s)`)
  }
  return problems
}

/**
 * After a build has come out clean, move the document it supersedes to the Trash, through the same `trash`
 * every other caller uses. Only a clean build replaces anything: one with leftover markdown or a layout
 * warning is not finished, and the document it was meant to replace is the last good one. Never throws, since
 * the new document exists whatever happens here and the caller must still be told about it.
 */
export async function replaceSuperseded(
  auth: AuthProvider,
  old: DocumentInfo,
  built: { residue: string[]; layout: LayoutResult },
): Promise<ReplacedResult> {
  const base = { documentId: old.documentId, title: old.title }
  const problems = problemsWith(built)
  if (problems.length > 0) {
    return {
      ...base,
      trashed: false,
      note: `Kept "${old.title}": the new document is not finished (${problems.join(', ')}). Fix that and build again.`,
    }
  }
  try {
    const result = await trashDocument(auth, old.documentId)
    return { ...base, trashed: true, note: `Moved "${old.title}" to the Trash. ${result.restore}` }
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error)
    return { ...base, trashed: false, note: `The new document is built, but "${old.title}" could not be moved to the Trash: ${reason}` }
  }
}

/**
 * One chapter per file, one tab per chapter, plus a cover tab with a clickable table of contents.
 *
 * The readback and residue lint are part of the operation rather than a separate step, because a
 * build nobody checked is a build nobody can trust — and the caller has the document id either way.
 */
export async function buildDocument(
  auth: AuthProvider,
  opts: { path: string; title?: string; theme?: Theme; maxPages?: number; replaces?: string },
): Promise<BuildResult> {
  const theme = opts.theme ?? technical
  const { files, single } = await loadChapters(opts.path)
  if (files.length === 0) throw new Error(`no .md files found in ${opts.path}`)
  // The résumé and letter looks are one document by one person, the same rule `npm start -- resume` holds.
  if ((theme === resume || theme === letter) && files.length > 1) {
    throw new Error(
      `a ${theme === letter ? 'letter' : 'résumé'} is one document, but ${opts.path} holds ${files.length} .md files: ` +
        `${files.map((f) => basename(f.path)).join(', ')}. Build it from the one file.`,
    )
  }

  // Checked before anything is built: a wrong id found now costs nothing.
  const superseded = opts.replaces ? await checkReplaceable(auth, opts.replaces) : undefined

  const chapters = files.map((file) =>
    planChapter(parseMarkdown(file.source), file.slug, basename(file.path)),
  )
  // A folder falls back to its own name for the cover title. A single file has no cover, so
  // its own H1 is the natural document title.
  const title = opts.title ?? (single ? (chapters[0]?.title ?? basename(opts.path)) : basename(opts.path))
  const plan = planDocument(chapters, title)

  // A lone file gets no cover: a cover whose table of contents has one entry is a page that
  // says nothing. With one tab and no cover, emit/document.ts also leaves the native tab
  // unrenamed, which keeps Docs from adding a blank first page to the PDF export.
  // A 403 from Docs on a full Drive reads "The caller does not have permission", which says nothing
  // of the cause; explainFailureWithDrive swaps in the real one, and only when the quota shows it.
  const built = await buildFromPlan(auth, { theme, plan, cover: !single }).catch(async (error: unknown) => {
    throw await explainFailureWithDrive(auth, error)
  })
  const doc = await fetchDocument(auth, built.documentId)

  const result: BuildResult = {
    documentId: built.documentId,
    url: built.url,
    title,
    chapters: chapters.map((c) => c.title),
    paragraphs: countParagraphs(doc),
    residue: residueFindings(doc, { codeFont: theme.code.font }),
    imageWarnings: built.imageWarnings,
    layout: await measureLayout(auth, built.documentId, { doc, maxPages: opts.maxPages }),
  }
  if (superseded) result.replaced = await replaceSuperseded(auth, superseded, result)
  return result
}

export interface LayoutReport {
  documentId: string
  layout: LayoutResult
}

/** Where an already-built document's pages break, without rebuilding it — e.g. after a hand edit. */
export async function layoutDocument(
  auth: AuthProvider,
  documentId: string,
  opts: { maxPages?: number } = {},
): Promise<LayoutReport> {
  return { documentId, layout: await measureLayout(auth, documentId, opts) }
}

export interface LintResult {
  documentId: string
  paragraphs: number
  residue: string[]
}

/**
 * Re-run the residue lint against an already-built document.
 *
 * `lint` is given a documentId, not a theme, so it cannot know which one built the document. Both
 * presets use the same mono family, so the code-run exemption resolves identically either way.
 */
export async function lintDocument(
  auth: AuthProvider,
  documentId: string,
  theme: Theme = technical,
): Promise<LintResult> {
  const doc = await fetchDocument(auth, documentId)
  return {
    documentId,
    paragraphs: countParagraphs(doc),
    residue: residueFindings(doc, { codeFont: theme.code.font }),
  }
}
