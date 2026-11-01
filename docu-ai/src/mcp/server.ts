import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'
import { z } from 'zod'
import { GoogleOAuthProvider } from '../auth/google.js'
import type { AuthProvider } from '../auth/types.js'
import {
  THEMES,
  buildDocument,
  documentInfo,
  exportDocument,
  layoutDocument,
  lintDocument,
  listDocuments,
  preview,
  renameDocument,
  saveExport,
  trashDocument,
  type ThemeName,
} from '../operations.js'
import { tolerateSlowConnections } from '../network.js'

/**
 * docu-ai's second front door: the same operations the CLI exposes, reachable by a model.
 *
 * Both doors sit directly on `operations.ts`; neither wraps the other. A model calling `build` and
 * a person typing `npm start -- build` run identical code and differ only in how the result is
 * formatted — JSON here, prose there.
 *
 * `zod` is a direct dependency on purpose, pinned to the range the MCP SDK itself resolves so npm
 * dedupes to ONE copy. This is the same hazard CLAUDE.md records for google-auth-library: two
 * copies of a schema library yield two nominally distinct types, and `registerTool` then rejects
 * a schema built with the wrong one. Check `npm ls zod` shows a single deduped entry before
 * bumping either package.
 */

const VERSION = '0.0.1'

function ok(payload: unknown) {
  return { content: [{ type: 'text' as const, text: JSON.stringify(payload, null, 2) }] }
}

function failed(error: unknown) {
  return {
    isError: true,
    content: [{ type: 'text' as const, text: error instanceof Error ? error.message : String(error) }],
  }
}

/** Where `save_export` writes. Injected like auth; unset, that one tool says so and the rest work. */
export interface ServerPaths {
  exportsDir?: string
}

/**
 * Auth comes in, exactly as it does for every other caller of `operations.ts`. The server does not
 * resolve credentials, which is what lets a test drive it with a stub and a future service account
 * drop in without touching this file.
 */
export function createDocuAiServer(auth: AuthProvider, paths: ServerPaths = {}): McpServer {
  const server = new McpServer({ name: 'docu-ai', version: VERSION })

  server.registerTool(
    'preview',
    {
      title: 'Preview a markdown folder',
      description:
        'Parse and plan a folder of markdown files, or a single file, and report the structure that would be built: ' +
        'one chapter per file, with a tally of block kinds. Touches no network and creates nothing, ' +
        'so it is the safe way to check a folder before spending a build on it.',
      inputSchema: {
        path: z
          .string()
          .describe('A folder of .md files (one file becomes one chapter), or a single .md file.'),
      },
      // No network, no document, nothing to undo. This is the approval surface.
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    async ({ path }) => {
      try {
        return ok(await preview(path))
      } catch (error) {
        return failed(error)
      }
    },
  )

  server.registerTool(
    'build',
    {
      title: 'Build a Google Doc from a markdown folder',
      description:
        'Compile a folder of markdown into a real Google Doc: one tab per chapter, a cover with a ' +
        'clickable table of contents, real Docs styling, and no markdown residue. Returns the ' +
        'document id and URL, a paragraph count, the residue lint findings, and `layout`: the page ' +
        'count and a warning for any heading stranded at the foot of a page, a page target missed, or ' +
        'a stray last page. Creates a document in the user\'s Drive and spends write quota — run ' +
        'preview first. If `layout.warnings` is not empty, the document is not finished: shorten or ' +
        'adjust the markdown (cut the least relevant points first, never invent or drop facts to ' +
        'fit), build again, and then trash the earlier Doc with `trash` — every build makes a new ' +
        'one, and a stack of superseded copies is clutter. `layout.measured: false` means the pages ' +
        'could not be read (the reason is given): say so rather than calling the layout fine.',
      inputSchema: {
        path: z
          .string()
          .describe(
            'A folder of .md files, or a single .md file. A folder gets one tab per chapter and a ' +
              'cover with a table of contents; a single file becomes one tab with no cover.',
          ),
        title: z
          .string()
          .optional()
          .describe(
            "The document's title: its name in Drive and, for a folder, the title on the cover. Defaults to " +
              "the folder's name, or for a single .md file its first heading. Give one to tell two documents " +
              'by the same person apart in Drive, such as a CV and a cover letter, which would otherwise ' +
              'both be named after the sender.',
          ),
        theme: z
          .enum(Object.keys(THEMES) as [ThemeName, ...ThemeName[]])
          .optional()
          .describe(
            "How it looks. 'technical' (the default): a specification or handbook style. " +
              "'resume': a CV — one or two packed pages, tighter type, no cover. 'letter': a cover letter " +
              'or any business letter — 11pt, one-inch margins, room between the blocks of the letter. ' +
              "For 'resume' and 'letter' the path must be a single .md file whose heading is the sender's " +
              "name. Use 'letter' for a letter, not 'resume': the CV look is too small and cramped for one, " +
              "and 'technical' is for reports.",
          ),
        maxPages: z
          .number()
          .int()
          .positive()
          .optional()
          .describe(
            'The most pages the document should run to — a CV is usually one or two. Going over is ' +
              'reported in layout.warnings, with how little spilled onto the last page.',
          ),
      },
      annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: true },
    },
    async ({ path, title, theme, maxPages }) => {
      try {
        return ok(
          await buildDocument(auth, { path, title, theme: theme ? THEMES[theme] : undefined, maxPages }),
        )
      } catch (error) {
        return failed(error)
      }
    },
  )

  server.registerTool(
    'lint',
    {
      title: 'Check a built document for markdown residue',
      description:
        'Read an already-built Google Doc back and assert no literal markdown survived in it — no ' +
        'asterisk pairs, backticks or table pipes in prose, and no line starting with an ' +
        'unconverted heading or list marker. Code-styled runs are exempt, because real code ' +
        'legitimately contains all of them.',
      inputSchema: {
        documentId: z.string().describe('The Google Docs document id, as returned by build.'),
      },
      annotations: { readOnlyHint: true, openWorldHint: true },
    },
    async ({ documentId }) => {
      try {
        return ok(await lintDocument(auth, documentId))
      } catch (error) {
        return failed(error)
      }
    },
  )

  server.registerTool(
    'layout',
    {
      title: 'Where a built document\'s pages break',
      description:
        'Export an already-built Google Doc as the PDF Docs itself lays out and report its page count and ' +
        'any warning: a heading stranded at the foot of a page, more pages than maxPages, a stray last ' +
        'page. Use it after the user has edited a Doc by hand, or to recheck one. Reads only. A ' +
        'document of several tabs is not measured (Docs adds a title page per tab to its PDF).',
      inputSchema: {
        documentId: z.string().describe('The Google Docs document id, as returned by build.'),
        maxPages: z.number().int().positive().optional().describe('The most pages it should run to.'),
      },
      annotations: { readOnlyHint: true, openWorldHint: true },
    },
    async ({ documentId, maxPages }) => {
      try {
        return ok(await layoutDocument(auth, documentId, { maxPages }))
      } catch (error) {
        return failed(error)
      }
    },
  )

  server.registerTool(
    'login_status',
    {
      title: 'Check the Google login',
      description:
        'Is the Google Docs login still accepted? Asks Google once whether the saved login still works. `state` is ' +
        'ok; dead (Google refuses it, so it must be signed in again); missing (never signed in); or unknown (Google ' +
        'could not be reached, so nothing is known). Changes nothing: no file is written and no document is touched.',
      annotations: { readOnlyHint: true, openWorldHint: true },
    },
    async () => {
      try {
        return ok({ service: 'Google Docs', ...(auth.login ? await auth.login() : { state: 'unknown', detail: 'this sign-in cannot be checked' }) })
      } catch (error) {
        return failed(error)
      }
    },
  )

  server.registerTool(
    'info',
    {
      title: 'What a built document is',
      description:
        'Say which Google Doc a document id is: its title, when it was created and last edited, whether it ' +
        'is already in the Trash, and its link. Reads only; use it to be sure which Doc is meant before ' +
        'trashing one. Only documents docu-ai itself built can be seen.',
      inputSchema: { documentId: z.string().describe('The Google Docs document id, as returned by build.') },
      annotations: { readOnlyHint: true, openWorldHint: true },
    },
    async ({ documentId }) => {
      try {
        return ok(await documentInfo(auth, documentId))
      } catch (error) {
        return failed(error)
      }
    },
  )

  server.registerTool(
    'trash',
    {
      title: 'Move a built document to the Trash',
      description:
        'Move a Google Doc docu-ai built to Drive\'s Trash, where it stays for 30 days and can be restored. ' +
        'For a superseded build only, and only AFTER its replacement has been built and measured: trash the ' +
        'one it replaced, never before. Never trash a Doc the user has not been told is superseded, and ' +
        'never one whose link they were just given as the result. Can touch only documents docu-ai ' +
        'itself built, never other files in Drive.',
      inputSchema: { documentId: z.string().describe('The Google Docs document id, as returned by build.') },
      annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: true },
      // The id alone cannot be approved. The gate shows what `info` says about it, which names the Doc.
      _meta: { approval: { preview_tool: 'info', argument_map: { documentId: 'documentId' }, field: 'summary' } },
    },
    async ({ documentId }) => {
      try {
        return ok(await trashDocument(auth, documentId))
      } catch (error) {
        return failed(error)
      }
    },
  )

  server.registerTool(
    'rename',
    {
      title: 'Rename a built document',
      description:
        "Give a Google Doc docu-ai built a new name in Drive. Its content is not changed. Use it when the user asks, or " +
        'to tell apart documents with the same name (a CV and a cover letter are both named after the sender unless ' +
        'built with a title). Say which document it is by its current name and date before renaming. Only documents ' +
        'docu-ai built can be renamed, and not one in the Trash.',
      inputSchema: {
        documentId: z.string().describe('The Google Docs document id, as returned by build or list.'),
        name: z.string().describe('The new name, as it should read in Drive, for example "CV - ML Engineer".'),
      },
      // Not destructive: renaming it back undoes it, and the arguments name the new title in full.
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: true },
    },
    async ({ documentId, name }) => {
      try {
        return ok(await renameDocument(auth, documentId, name))
      } catch (error) {
        return failed(error)
      }
    },
  )

  server.registerTool(
    'list',
    {
      title: 'List documents docu-ai has built',
      description:
        'All Google Docs this tool has created — CVs, cover letters, meeting notes, and other documents — ' +
        'sorted by last modified. Only documents docu-ai built appear (the Drive scope is drive.file). ' +
        'Reads only. Returns a nextPageToken when more pages exist.',
      inputSchema: {
        limit: z
          .number()
          .int()
          .positive()
          .max(100)
          .optional()
          .describe('How many to return per page (default 10, max 100).'),
        pageToken: z
          .string()
          .optional()
          .describe('Token from a previous response to fetch the next page.'),
      },
      annotations: { readOnlyHint: true, openWorldHint: true },
    },
    async ({ limit, pageToken }) => {
      try {
        return ok(await listDocuments(auth, limit, pageToken))
      } catch (error) {
        return failed(error)
      }
    },
  )

  server.registerTool(
    'export',
    {
      title: 'Export a built document as PDF or DOCX',
      description:
        'Download a Google Doc docu-ai built as a file. Returns the raw bytes base64-encoded, with a ' +
        'suggested filename: this is what the web app\'s download button uses. Never use it to attach a CV or ' +
        'letter to an email: the whole file comes back as text, far more than you can carry into another call. ' +
        'Use save_export for that. Only documents docu-ai built can be exported (drive.file scope).',
      inputSchema: {
        documentId: z.string().describe('The Google Docs document id, as returned by build or list.'),
        format: z
          .enum(['pdf', 'docx'])
          .describe("'pdf' for a PDF, 'docx' for a Word document."),
      },
      annotations: { readOnlyHint: true, openWorldHint: true },
    },
    async ({ documentId, format }) => {
      try {
        const result = await exportDocument(auth, documentId, format)
        return ok({
          documentId: result.documentId,
          format: result.format,
          filename: result.filename,
          size: result.bytes.length,
          data: result.bytes.toString('base64'),
        })
      } catch (error) {
        return failed(error)
      }
    },
  )

  server.registerTool(
    'save_export',
    {
      title: 'Save a built document as a Word or PDF file, to attach to an email',
      description:
        'Export a Google Doc docu-ai built and save it as a file in the exports folder the suite gave docu-ai. ' +
        'Returns the file\'s path, name and size, never its bytes. This is how a CV or cover letter is attached ' +
        'to an email: pass the returned `path` to mail_ai__draft_new in `attachments`, as {path}. Do not use ' +
        '`export` for that: it returns the whole file as text (a Word CV is about 650 KB), far more than you ' +
        'can copy into another call. `filename` is the name the recipient will see, for example ' +
        '"Philip_Baah_Afriyie_CV.docx"; it is given the format\'s extension, and a file already there is never ' +
        'overwritten (a number is added, and the returned name says so). Use the format the recipient asked ' +
        'for. Only documents docu-ai built can be saved.',
      inputSchema: {
        documentId: z.string().describe('The Google Docs document id, as returned by build or list.'),
        format: z.enum(['pdf', 'docx']).describe("'docx' for a Word document, 'pdf' for a PDF."),
        filename: z
          .string()
          .optional()
          .describe('The file name the recipient will see. Default: the document\'s title.'),
      },
      annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: true },
      // The approval names the document, not just its id.
      _meta: { approval: { preview_tool: 'info', argument_map: { documentId: 'documentId' }, field: 'summary' } },
    },
    async ({ documentId, format, filename }) => {
      try {
        if (!paths.exportsDir) return failed(new Error('No exports folder: the suite gives docu-ai one in DOCU_AI_EXPORTS.'))
        return ok(await saveExport(paths.exportsDir, await exportDocument(auth, documentId, format), filename))
      } catch (error) {
        return failed(error)
      }
    },
  )

  return server
}

async function main(): Promise<void> {
  tolerateSlowConnections()
  // The one place this entry point reaches for the environment, and named so it is visible.
  const server = createDocuAiServer(GoogleOAuthProvider.fromEnvironment(), { exportsDir: process.env.DOCU_AI_EXPORTS || undefined })
  await server.connect(new StdioServerTransport())
}

// stdout is the MCP transport here: anything written to it that is not a protocol message corrupts
// the stream, so errors go to stderr and nowhere else.
main().catch((error: unknown) => {
  process.stderr.write(`${error instanceof Error ? error.stack : String(error)}\n`)
  process.exitCode = 1
})
