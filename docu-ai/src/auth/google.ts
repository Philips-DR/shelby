import { spawn } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { createServer } from 'node:http'
import { homedir } from 'node:os'
import { dirname, join } from 'node:path'
import { Auth } from 'googleapis'
import type { AuthProvider, LoginCheck } from './types.js'

/**
 * `drive.file` is deliberately the narrowest scope that works: it grants access only to files this
 * app created, which covers creating documents and exporting them to PDF for verification.
 */
export const SCOPES = [
  'https://www.googleapis.com/auth/documents',
  'https://www.googleapis.com/auth/drive.file',
]

interface ClientSecrets {
  clientId: string
  clientSecret: string
}

/**
 * Everything this provider needs, supplied by the caller. Nothing here is discovered.
 *
 * The point is not ceremony: as long as a tool reaches into the environment for its own
 * credentials, "where identity lives" is a fact every tool has to agree on, and the second tool
 * either duplicates the lookup or imports the first one to borrow it. That second option is
 * exactly the cross-module auth import that made the old monolith's modules non-independent.
 * Config in, and the question never arises.
 */
export interface GoogleAuthConfig {
  /** Set both, or leave both unset and point `credentialsPath` at the client JSON. */
  clientId?: string
  clientSecret?: string
  credentialsPath: string
  tokenPath: string
}

/**
 * The one place the environment is read, and a deliberately named act rather than a default that
 * happens silently inside a constructor. Front doors call this; library code does not.
 */
export function authConfigFromEnvironment(): GoogleAuthConfig {
  const base = process.env.XDG_CONFIG_HOME ?? join(homedir(), '.config')
  return {
    clientId: process.env.DOCU_AI_CLIENT_ID,
    clientSecret: process.env.DOCU_AI_CLIENT_SECRET,
    credentialsPath: process.env.DOCU_AI_CREDENTIALS ?? 'credentials.json',
    tokenPath: process.env.DOCU_AI_TOKEN ?? join(base, 'docu-ai', 'token.json'),
  }
}

/** The default token location. Kept for callers that only want to report where it would be. */
export function tokenPath(): string {
  return authConfigFromEnvironment().tokenPath
}

async function loadClientSecrets(config: GoogleAuthConfig): Promise<ClientSecrets> {
  const { clientId: id, clientSecret: secret } = config
  if (id && secret) return { clientId: id, clientSecret: secret }

  const path = config.credentialsPath
  let raw: string
  try {
    raw = await readFile(path, 'utf8')
  } catch {
    throw new Error(
      'No OAuth client credentials found.\n' +
        '  Either set DOCU_AI_CLIENT_ID and DOCU_AI_CLIENT_SECRET,\n' +
        `  or save the OAuth client JSON from Google Cloud as ${path}\n` +
        '  (or point DOCU_AI_CREDENTIALS at it). See SETUP.md.',
    )
  }

  const parsed = JSON.parse(raw) as {
    installed?: { client_id?: string; client_secret?: string }
    web?: { client_id?: string; client_secret?: string }
  }
  const node = parsed.installed ?? parsed.web
  if (!node?.client_id || !node.client_secret) {
    throw new Error(`${path} is not a Google OAuth client JSON (no installed.client_id).`)
  }
  return { clientId: node.client_id, clientSecret: node.client_secret }
}

async function saveCredentials(creds: Auth.Credentials, path: string): Promise<void> {
  await mkdir(dirname(path), { recursive: true })
  // The refresh token is a long-lived secret: keep it owner-only.
  await writeFile(path, JSON.stringify(creds, null, 2), { mode: 0o600 })
}

function openBrowser(url: string): void {
  const cmd =
    process.platform === 'darwin' ? 'open' : process.platform === 'win32' ? 'start' : 'xdg-open'
  try {
    spawn(cmd, [url], { stdio: 'ignore', detached: true }).unref()
  } catch {
    // Not fatal: the URL is printed for the user to open by hand.
  }
}

/**
 * Desktop OAuth: spin up a loopback listener on an ephemeral port, send the user to Google, and
 * catch the redirect. Desktop client types permit any localhost port, so nothing is hardcoded.
 */
function authorizeInteractively(
  secrets: ClientSecrets,
  tokenFile: string,
): Promise<Auth.OAuth2Client> {
  return new Promise<Auth.OAuth2Client>((resolve, reject) => {
    const state = randomBytes(16).toString('hex')
    const server = createServer()
    server.on('error', reject)

    server.listen(0, '127.0.0.1', () => {
      const addr = server.address()
      if (addr === null || typeof addr === 'string') {
        server.close()
        reject(new Error('could not bind a loopback port for the OAuth redirect'))
        return
      }

      const redirectUri = `http://localhost:${addr.port}/oauth2callback`
      const client = new Auth.OAuth2Client({
        clientId: secrets.clientId,
        clientSecret: secrets.clientSecret,
        redirectUri,
      })
      const authUrl = client.generateAuthUrl({
        access_type: 'offline',
        prompt: 'consent', // force a refresh_token even if this client was authorised before
        scope: SCOPES,
        state,
      })

      server.on('request', (req, res) => {
        void (async () => {
          try {
            const url = new URL(req.url ?? '/', redirectUri)
            if (url.pathname !== '/oauth2callback') {
              res.writeHead(404).end()
              return
            }
            const failure = url.searchParams.get('error')
            if (failure) throw new Error(`Google returned an error: ${failure}`)
            if (url.searchParams.get('state') !== state) {
              throw new Error('OAuth state mismatch — aborting rather than trusting this callback')
            }
            const code = url.searchParams.get('code')
            if (!code) throw new Error('no authorisation code in the callback')

            const { tokens } = await client.getToken(code)
            client.setCredentials(tokens)
            await saveCredentials(tokens, tokenFile)

            res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' })
            res.end('<h2>docu-ai is authorised.</h2><p>You can close this tab.</p>')
            server.close()
            resolve(client)
          } catch (err) {
            res.writeHead(500, { 'content-type': 'text/plain; charset=utf-8' })
            res.end(String(err))
            server.close()
            reject(err instanceof Error ? err : new Error(String(err)))
          }
        })()
      })

      process.stdout.write(
        `\nOpening a browser to authorise docu-ai.\nIf it does not open, visit:\n\n  ${authUrl}\n\n`,
      )
      openBrowser(authUrl)
    })
  })
}

export class GoogleOAuthProvider implements AuthProvider {
  readonly kind = 'oauth-desktop'
  private cached: Auth.OAuth2Client | undefined

  constructor(private readonly config: GoogleAuthConfig) {}

  /** The escape hatch, named so it is visible at the call site. Front doors only. */
  static fromEnvironment(): GoogleOAuthProvider {
    return new GoogleOAuthProvider(authConfigFromEnvironment())
  }

  /** Is the saved login still accepted? Asked of Google, written nowhere; see `checkLogin`. */
  login(): Promise<LoginCheck> {
    return checkLogin(this.config)
  }

  /**
   * The MCP server holds one provider for its whole life, so a client cached forever meant a fresh
   * `npm run auth` did nothing until the backend restarted: every build kept failing with the dead
   * refresh token held in memory. The cache is kept only while the token file still carries the
   * refresh token it was built from — one small local read per call, no network.
   */
  async client(): Promise<Auth.OAuth2Client> {
    if (this.cached) {
      // Only a different refresh token on disk replaces the cache. A missing or unreadable file
      // keeps it: falling through would open a consent screen from inside a tool call.
      const onDisk = await this.cachedRefreshToken()
      if (!onDisk || onDisk === this.cached.credentials.refresh_token) return this.cached
    }
    const secrets = await loadClientSecrets(this.config)
    const client =
      (await this.fromCache(secrets)) ??
      (await authorizeInteractively(secrets, this.config.tokenPath))
    this.cached = client
    return client
  }

  /**
   * Always runs the browser flow, ignoring whatever is cached. This is what `npm run auth` needs and
   * `client()` cannot provide: `fromCache` hands back a client whenever the token file merely
   * CONTAINS a refresh_token, without ever checking that the token still works — which is correct
   * for the common path (validating on every command would cost a round trip) but meant that once a
   * refresh token went stale, `auth` short-circuited to the dead one and printed "Authorised"
   * without opening a browser. Re-authorising was impossible short of deleting the file by hand.
   *
   * Google expires refresh tokens after 7 days while the OAuth app is in "Testing" (SETUP.md), so a
   * stale token is the normal state here, not an edge case.
   */
  async authorize(): Promise<Auth.OAuth2Client> {
    const client = await authorizeInteractively(
      await loadClientSecrets(this.config),
      this.config.tokenPath,
    )
    this.cached = client
    return client
  }

  private async cachedRefreshToken(): Promise<string | null | undefined> {
    try {
      return (JSON.parse(await readFile(this.config.tokenPath, 'utf8')) as Auth.Credentials)
        .refresh_token
    } catch {
      return undefined
    }
  }

  private async fromCache(secrets: ClientSecrets): Promise<Auth.OAuth2Client | undefined> {
    let raw: string
    try {
      raw = await readFile(this.config.tokenPath, 'utf8')
    } catch {
      return undefined
    }
    const creds = JSON.parse(raw) as Auth.Credentials
    if (!creds.refresh_token) return undefined // an access token alone is useless once it expires

    const client = new Auth.OAuth2Client({
      clientId: secrets.clientId,
      clientSecret: secrets.clientSecret,
    })
    client.setCredentials(creds)
    // Persist rotated access tokens. The library folds the existing refresh_token into
    // client.credentials, so writing the whole object keeps it intact.
    client.on('tokens', () => {
      void saveCredentials(client.credentials, this.config.tokenPath)
    })
    return client
  }
}

const TOKEN_URL = 'https://oauth2.googleapis.com/token'

/**
 * Offer Google the refresh token. '' when it is accepted, otherwise the error word Google gave ('invalid_grant'). A
 * network failure is thrown: that is "could not ask", which is not the same as "refused".
 */
async function askGoogle(body: URLSearchParams): Promise<string> {
  const response = await fetch(TOKEN_URL, { method: 'POST', body, signal: AbortSignal.timeout(15_000) })
  if (response.ok) return ''
  try {
    return String(((await response.json()) as { error?: string }).error ?? response.status)
  } catch {
    return String(response.status)
  }
}

/**
 * Ask Google once whether the saved refresh token still works, which every call to Docs does anyway.
 *
 * Reads the token file and writes nothing: the answer is thrown away, so a check never rewrites the token, and a
 * login that is good stays exactly as it was. Only `invalid_grant` is "dead": any other answer says something is
 * wrong without saying the login is gone, so it is "unknown" with Google's word attached.
 */
export async function checkLogin(
  config: GoogleAuthConfig,
  ask: (body: URLSearchParams) => Promise<string> = askGoogle,
): Promise<LoginCheck> {
  let raw: string
  try {
    raw = await readFile(config.tokenPath, 'utf8')
  } catch (error) {
    return (error as NodeJS.ErrnoException).code === 'ENOENT'
      ? { state: 'missing', detail: `no token at ${config.tokenPath}` }
      : { state: 'dead', detail: `unreadable token at ${config.tokenPath}` }
  }
  let token: Auth.Credentials | null
  try {
    token = JSON.parse(raw) as Auth.Credentials | null
  } catch {
    return { state: 'dead', detail: `unreadable token at ${config.tokenPath}` }
  }
  if (!token || typeof token !== 'object' || !token.refresh_token) {
    return { state: 'dead', detail: 'the saved login has no refresh token' }
  }
  let secrets: ClientSecrets
  try {
    secrets = await loadClientSecrets(config)
  } catch {
    return { state: 'unknown', detail: `no OAuth client at ${config.credentialsPath}` }
  }
  let answer: string
  try {
    answer = await ask(
      new URLSearchParams({
        grant_type: 'refresh_token',
        refresh_token: token.refresh_token,
        client_id: secrets.clientId,
        client_secret: secrets.clientSecret,
      }),
    )
  } catch (error) {
    return { state: 'unknown', detail: `could not reach Google: ${error instanceof Error ? error.message : String(error)}` }
  }
  if (!answer) return { state: 'ok', detail: '' }
  return { state: answer === 'invalid_grant' ? 'dead' : 'unknown', detail: answer }
}

export async function hasCachedToken(path: string = tokenPath()): Promise<boolean> {
  try {
    const creds = JSON.parse(await readFile(path, 'utf8')) as Auth.Credentials
    return Boolean(creds.refresh_token)
  } catch {
    return false
  }
}
