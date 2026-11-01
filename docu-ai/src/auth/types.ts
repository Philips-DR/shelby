/**
 * The auth type comes from googleapis rather than a direct google-auth-library dependency on purpose.
 * Two copies of that package produce two nominally different OAuth2Client types (they differ by a
 * private field), and google.docs({auth}) then rejects the client we built. Sourcing it here cannot
 * drift. Do not add google-auth-library to package.json.
 */
import type { Auth } from 'googleapis'

/**
 * Auth sits behind this seam so a service account (domain-wide delegation, for unattended runs)
 * can be added later without touching any caller. Widen the return type when that lands.
 */
export interface AuthProvider {
  readonly kind: string
  /** An authorised client, ready to hand to google.docs({auth}) / google.drive({auth}). */
  client(): Promise<Auth.OAuth2Client>
  /** Is the saved login still accepted? Reads and asks; never opens a browser and never writes. Optional: a provider
   * that cannot tell is reported as unknown. */
  login?(): Promise<LoginCheck>
}

/**
 * `ok`; `dead` (Google refuses the login, so it must be signed in again); `missing` (never signed in); or `unknown`
 * (could not tell: Google was out of reach, or there is no OAuth client to ask with). `detail` is Google's own word
 * or ours, never a secret.
 */
export type LoginState = 'ok' | 'dead' | 'missing' | 'unknown'
export interface LoginCheck {
  state: LoginState
  detail: string
}
