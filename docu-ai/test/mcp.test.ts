import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { AuthProvider } from '../src/auth/types.js'
import { createDocuAiServer } from '../src/mcp/server.js'

/**
 * A real client-to-server round trip over an in-memory transport. No network, no stdio, no
 * credentials — which is the point: the door itself is testable without any of them, and the one
 * tool that genuinely needs auth (`build`) is never reached here.
 */

let dir: string

/**
 * Deliberately explodes if touched. Auth is injected into the server, so a test can prove that
 * `preview` reaches the network-free path by making any other path fail loudly.
 */
const refusingAuth: AuthProvider = {
  kind: 'test-refusing',
  client() {
    throw new Error('auth must not be used by a read-only operation')
  },
}

async function connect(): Promise<Client> {
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair()
  const server = createDocuAiServer(refusingAuth)
  const client = new Client({ name: 'test', version: '0.0.0' })
  await Promise.all([server.connect(serverTransport), client.connect(clientTransport)])
  return client
}

function textOf(result: unknown): string {
  const content = (result as { content: { type: string; text: string }[] }).content
  return content.map((block) => block.text).join('\n')
}

beforeEach(async () => {
  dir = await mkdtemp(join(tmpdir(), 'docu-ai-mcp-'))
})

afterEach(async () => {
  await rm(dir, { recursive: true, force: true })
})

describe('the MCP front door', () => {
  it('advertises exactly the eleven operations, and no more', async () => {
    const client = await connect()
    const names = (await client.listTools()).tools.map((t) => t.name).sort()
    expect(names).toEqual(['build', 'export', 'info', 'layout', 'lint', 'list', 'login_status', 'preview', 'rename', 'save_export', 'trash'])
  })

  it('marks only build, rename, save_export and trash as writes, and only trash as destructive', async () => {
    const tools = (await (await connect()).listTools()).tools
    const writes = tools.filter((t) => t.annotations?.readOnlyHint !== true).map((t) => t.name).sort()
    expect(writes).toEqual(['build', 'rename', 'save_export', 'trash'])
    const destructive = tools.filter((t) => t.annotations?.destructiveHint === true).map((t) => t.name)
    expect(destructive).toEqual(['trash'])
  })

  // A rename is undone by renaming back, and its arguments carry the new name in full, so a button press is
  // its approval: no preview, which would make the web app ask twice for something that can be undone.
  it('lets rename run on one press: no preview declared', async () => {
    const rename = (await (await connect()).listTools()).tools.find((t) => t.name === 'rename')
    expect((rename?._meta as { approval?: unknown } | undefined)?.approval).toBeUndefined()
    expect(rename?.inputSchema.required?.sort()).toEqual(['documentId', 'name'])
  })

  // The assistant's gate shows what the named tool says instead of raw arguments, and refuses a
  // "preview" that is not read-only. A document id alone cannot be approved: it names no document.
  it('has trash show what info says about the document, and info is read-only', async () => {
    const tools = (await (await connect()).listTools()).tools
    const trash = tools.find((t) => t.name === 'trash')
    const approval = (trash?._meta as { approval?: Record<string, unknown> } | undefined)?.approval
    expect(approval).toEqual({
      preview_tool: 'info',
      argument_map: { documentId: 'documentId' },
      field: 'summary',
    })
    expect(tools.find((t) => t.name === approval?.preview_tool)?.annotations?.readOnlyHint).toBe(true)
  })

  // A letter built in the résumé look came out cramped: the description has to steer a model to the right one.
  it('tells the model which look is for a letter, and not to use the CV look for one', async () => {
    const build = (await (await connect()).listTools()).tools.find((t) => t.name === 'build')
    const theme = (build?.inputSchema.properties as Record<string, { description?: string }>).theme
    expect(theme?.description).toContain("'letter': a cover letter")
    expect(theme?.description).toContain("Use 'letter' for a letter, not 'resume'")
  })

  it('lets a caller set a page target on a build', async () => {
    const build = (await (await connect()).listTools()).tools.find((t) => t.name === 'build')
    const props = build?.inputSchema.properties as Record<string, { type?: string }>
    expect(props.maxPages?.type).toBe('integer')
  })

  it('tells the model what to do with a layout warning, and that a missing measurement is not a pass', async () => {
    const build = (await (await connect()).listTools()).tools.find((t) => t.name === 'build')
    expect(build?.description).toContain('layout.warnings')
    expect(build?.description).toContain('trash')
    expect(build?.description).toContain('measured: false')
  })

  it('marks preview read-only so a caller can tell which tool is safe to run unattended', async () => {
    const client = await connect()
    const tools = (await client.listTools()).tools
    const preview = tools.find((t) => t.name === 'preview')
    const build = tools.find((t) => t.name === 'build')
    expect(preview?.annotations?.readOnlyHint).toBe(true)
    expect(build?.annotations?.readOnlyHint).toBe(false)
  })

  it('lets a caller choose the résumé and letter looks by name', async () => {
    const client = await connect()
    const build = (await client.listTools()).tools.find((t) => t.name === 'build')
    const theme = (build?.inputSchema.properties as Record<string, { enum?: string[] }>).theme
    expect(theme?.enum).toEqual(['technical', 'resume', 'letter'])
  })

  it('previews a folder without ever touching auth', async () => {
    await writeFile(join(dir, '01-intro.md'), '# Intro\n\nBody text.\n', 'utf8')
    await writeFile(join(dir, '02-next.md'), '# Next\n\n- one\n- two\n', 'utf8')

    const client = await connect()
    const result = await client.callTool({ name: 'preview', arguments: { path: dir } })

    const parsed = JSON.parse(textOf(result)) as {
      chapters: { title: string; file: string; blocks: Record<string, number> }[]
    }
    expect(parsed.chapters.map((c) => c.title)).toEqual(['Intro', 'Next'])
    expect(parsed.chapters[1]?.blocks).toMatchObject({ heading: 1, list: 1 })
  })

  it('reports a bad folder as a tool error rather than throwing the connection down', async () => {
    const client = await connect()
    const result = await client.callTool({ name: 'preview', arguments: { path: join(dir, 'nope') } })
    expect((result as { isError?: boolean }).isError).toBe(true)
  })

  it('rejects an empty folder, rather than building a document with no chapters', async () => {
    const client = await connect()
    const result = await client.callTool({ name: 'preview', arguments: { path: dir } })
    expect((result as { isError?: boolean }).isError).toBe(true)
    expect(textOf(result)).toContain('no .md files found')
  })
})

describe('the MCP front door — single files', () => {
  it('previews one file as a single-tab document', async () => {
    await writeFile(join(dir, 'x.notes.md'), '# Notes\n\nbody\n', 'utf8')
    await writeFile(join(dir, 'other.md'), '# Not this one\n', 'utf8')
    const client = await connect()
    const result = await client.callTool({ name: 'preview', arguments: { path: join(dir, 'x.notes.md') } })
    const parsed = JSON.parse(textOf(result)) as { single: boolean; chapters: { title: string }[] }
    expect(parsed.single).toBe(true)
    expect(parsed.chapters.map((c) => c.title)).toEqual(['Notes'])
  })

  it('has save_export name the document in its approval, return a path, and say not to carry bytes', async () => {
    const tools = (await (await connect()).listTools()).tools
    const save = tools.find((t) => t.name === 'save_export')
    const approval = (save?._meta as { approval?: Record<string, unknown> } | undefined)?.approval
    expect(approval).toEqual({ preview_tool: 'info', argument_map: { documentId: 'documentId' }, field: 'summary' })
    expect(save?.annotations?.destructiveHint).toBe(false)
    expect(save?.description).toMatch(/mail_ai__draft_new/)
    expect(save?.description).toMatch(/never its bytes/)
    // and export, which does return the bytes, is the button's: the model is pointed away from it for attaching
    expect(save?.description).toMatch(/Do not use\s+`export`/)
    expect(tools.find((t) => t.name === 'export')?.description).toMatch(/Use save_export for that/)
  })

  it('refuses save_export with no exports folder, before touching auth', async () => {
    const client = await connect() // no folder given, and auth that explodes if used
    const result = await client.callTool({ name: 'save_export', arguments: { documentId: 'abc', format: 'docx' } })
    expect((result as { isError?: boolean }).isError).toBe(true)
    expect(textOf(result)).toMatch(/No exports folder/)
  })
})
