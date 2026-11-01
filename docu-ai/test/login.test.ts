import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { checkLogin, type GoogleAuthConfig } from '../src/auth/google.js'
import type { AuthProvider, LoginCheck } from '../src/auth/types.js'
import { createDocuAiServer } from '../src/mcp/server.js'

/**
 * Is a saved Google login still accepted? Asked of Google once, and nothing written. Google is never called: `ask`
 * is the one seam, replaced by a function that answers as Google would. The token file is compared byte for byte,
 * because "a check must not change what it checks" is the rule this exists under.
 */

let dir: string
const CLIENT = JSON.stringify({ installed: { client_id: 'id-from-file', client_secret: 's-from-file' } })

beforeEach(async () => {
  dir = await mkdtemp(join(tmpdir(), 'docu-ai-login-'))
})
afterEach(async () => {
  await rm(dir, { recursive: true, force: true })
})

async function config(token: string | null, client: string | null = CLIENT): Promise<GoogleAuthConfig> {
  if (token !== null) await writeFile(join(dir, 'token.json'), token)
  if (client !== null) await writeFile(join(dir, 'credentials.json'), client)
  return { credentialsPath: join(dir, 'credentials.json'), tokenPath: join(dir, 'token.json') }
}

const GOOD = JSON.stringify({ access_token: 'a-1', refresh_token: 'r-1' })
const says = (answer: string, seen: string[] = []) => async (body: URLSearchParams) => {
  seen.push(body.toString())
  return answer
}
const unreachable = async (): Promise<string> => {
  throw new Error('fetch failed')
}

describe('checkLogin', () => {
  it('calls a refresh token Google accepts ok', async () => {
    expect(await checkLogin(await config(GOOD), says(''))).toEqual({ state: 'ok', detail: '' })
  })

  it('takes invalid_grant as the one answer that means signed out', async () => {
    expect(await checkLogin(await config(GOOD), says('invalid_grant'))).toEqual({ state: 'dead', detail: 'invalid_grant' })
  })

  it('says any other answer without calling the login gone', async () => {
    // a wrong client secret is a fault in the setup, and signing in again would not fix it
    expect(await checkLogin(await config(GOOD), says('invalid_client'))).toEqual({ state: 'unknown', detail: 'invalid_client' })
  })

  it('treats Google out of reach as unknown, not dead', async () => {
    const check = await checkLogin(await config(GOOD), unreachable)
    expect(check.state).toBe('unknown')
    expect(check.detail).toContain('fetch failed')
  })

  it('calls no token missing', async () => {
    expect((await checkLogin(await config(null), says(''))).state).toBe('missing')
  })

  it.each(['{not json', 'null', '[]', JSON.stringify({ access_token: 'a' }), JSON.stringify({ refresh_token: '' })])(
    'calls a token that cannot be used dead: %s',
    async (token) => {
      expect((await checkLogin(await config(token), says(''))).state).toBe('dead')
    },
  )

  it('is unknown when there is no OAuth client to ask with', async () => {
    expect((await checkLogin(await config(GOOD, null), says(''))).state).toBe('unknown')
  })

  it('offers the refresh token with the client from credentials.json', async () => {
    const seen: string[] = []
    await checkLogin(await config(GOOD), says('', seen))
    expect(seen[0]).toContain('grant_type=refresh_token')
    expect(seen[0]).toContain('refresh_token=r-1')
    expect(seen[0]).toContain('client_id=id-from-file')
  })

  it.each(['', 'invalid_grant', 'invalid_client'])('never changes the token file (answer %j)', async (answer) => {
    const cfg = await config(GOOD)
    const before = await readFile(cfg.tokenPath)
    await checkLogin(cfg, says(answer))
    expect((await readFile(cfg.tokenPath)).equals(before)).toBe(true)
  })

  it('never puts a secret in its detail', async () => {
    for (const ask of [says('invalid_grant'), unreachable, says('')]) {
      const check = await checkLogin(await config(GOOD), ask)
      expect(check.detail).not.toContain('r-1')
      expect(check.detail).not.toContain('s-from-file')
    }
  })
})

describe('the login_status tool', () => {
  async function connect(auth: AuthProvider): Promise<Client> {
    const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair()
    const client = new Client({ name: 'test', version: '0.0.0' })
    await Promise.all([createDocuAiServer(auth).connect(serverTransport), client.connect(clientTransport)])
    return client
  }
  const refusing = (login?: () => Promise<LoginCheck>): AuthProvider => ({
    kind: 'test',
    client() {
      throw new Error('a login check must not need a client')
    },
    login,
  })
  const text = (result: unknown) => (result as { content: { text: string }[] }).content.map((b) => b.text).join('')

  it('is read-only', async () => {
    const tool = (await (await connect(refusing())).listTools()).tools.find((t) => t.name === 'login_status')
    expect(tool?.annotations?.readOnlyHint).toBe(true)
  })

  it('says what the provider found', async () => {
    const client = await connect(refusing(async () => ({ state: 'dead', detail: 'invalid_grant' })))
    expect(JSON.parse(text(await client.callTool({ name: 'login_status', arguments: {} })))).toEqual({ service: 'Google Docs', state: 'dead', detail: 'invalid_grant' })
  })

  it('says unknown, not ok, for a sign-in that cannot be checked', async () => {
    const out = JSON.parse(text(await (await connect(refusing())).callTool({ name: 'login_status', arguments: {} })))
    expect(out.state).toBe('unknown')
  })

  it('reports its own failure as a failure', async () => {
    const client = await connect(refusing(async () => { throw new Error('boom') }))
    const result = (await client.callTool({ name: 'login_status', arguments: {} })) as { isError?: boolean }
    expect(result.isError).toBe(true)
  })
})
