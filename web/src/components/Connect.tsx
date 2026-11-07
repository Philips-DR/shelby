import { useState } from 'react'
import { API_URL, connect, signInUrl } from '../api'
import { BrandMark } from '../ui/Shell'

export function Connect({ checking }: { checking?: boolean }) {
  const [showToken, setShowToken] = useState(false)
  const [value, setValue] = useState('')
  const [error, setError] = useState('')
  const [trying, setTrying] = useState(false)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setTrying(true)
    setError('')
    try {
      await connect(value)
      window.location.reload()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setTrying(false)
    }
  }

  return (
    <div className="login" role="dialog" aria-labelledby="login-title">
      <div className="login-card">
        <BrandMark size={48} />
        <h1 id="login-title">Shelby</h1>
        <p className="login-tagline">My personal AI assistant</p>
        {checking ? (
          <p className="login-status">Signing in&#x2026;</p>
        ) : (
          <>
            <a className="login-google" href={signInUrl()}>
              <GoogleLogo />
              Sign in with Google
            </a>

            {!showToken ? (
              <button
                type="button"
                className="login-alt"
                onClick={() => setShowToken(true)}
              >
                Use an access token instead
              </button>
            ) : (
              <form className="login-token" onSubmit={(e) => void submit(e)}>
                <div className="login-divider"><span>or</span></div>
                <label className="login-label" htmlFor="login-token-input">
                  Paste the token from the backend&#x2019;s terminal
                </label>
                <input
                  id="login-token-input"
                  autoFocus
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                  placeholder="access token"
                  spellCheck={false}
                  autoComplete="off"
                />
                <button className="login-connect" type="submit" disabled={!value.trim() || trying}>
                  {trying ? 'Connecting…' : 'Connect'}
                </button>
              </form>
            )}

            {error && <p className="login-error">{error}</p>}
            <p className="login-backend">
              Backend at <span>{API_URL}</span>
            </p>
          </>
        )}
      </div>
    </div>
  )
}

function GoogleLogo() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden>
      <path d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844a4.14 4.14 0 01-1.796 2.716v2.259h2.908c1.702-1.567 2.684-3.875 2.684-6.615z" fill="#4285F4" />
      <path d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 009 18z" fill="#34A853" />
      <path d="M3.964 10.71A5.41 5.41 0 013.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 000 9c0 1.452.348 2.827.957 4.042l3.007-2.332z" fill="#FBBC05" />
      <path d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 00.957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z" fill="#EA4335" />
    </svg>
  )
}
