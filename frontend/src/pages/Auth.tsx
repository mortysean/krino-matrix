import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../api'
import { useAuth } from '../auth'
import { Demo } from '../components/Demo'
import { Logo } from '../components/Logo'
import { errorText, t } from '../i18n'

function codeOf(e: unknown) {
  return e instanceof ApiError ? (e.status === 0 ? 'network' : e.message) : 'generic'
}

export function AuthPage({ mode }: { mode: 'login' | 'register' }) {
  const { setUser } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      setUser(await (mode === 'login' ? api.login(email, password) : api.register(email, password)))
      navigate('/', { replace: true })
    } catch (err) {
      setError(errorText(codeOf(err)))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth">
      <div style={{ width: 'min(1040px, 100%)', display: 'grid', gap: 32, gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 380px), 1fr))', alignItems: 'center' }}>
        <div className="stack" style={{ gap: 22 }}>
          <Logo />
          <h1 className="h1">{t('app.tagline')}</h1>
          <Demo />
        </div>
        <form className="panel auth-card auth-form" onSubmit={submit} style={{ justifySelf: 'center' }}>
          <h2 className="h2">{mode === 'login' ? t('auth.login') : t('auth.register')}</h2>
          <div className="field">
            <label htmlFor="email">{t('auth.email')}</label>
            <input id="email" className="input" type="email" autoComplete="email" required value={email} onChange={e => setEmail(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="password">{t('auth.password')}</label>
            <input id="password" className="input" type="password" required minLength={mode === 'register' ? 8 : undefined}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'} value={password} onChange={e => setPassword(e.target.value)} />
            {mode === 'register' && <span className="muted small">{t('auth.passwordHint')}</span>}
          </div>
          {error && <p className="form-error" role="alert">{error}</p>}
          <button className="btn primary lg" disabled={busy}>{mode === 'login' ? t('auth.login') : t('auth.register')}</button>
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <Link className="small" to={mode === 'login' ? '/register' : '/login'}>{mode === 'login' ? t('auth.toRegister') : t('auth.toLogin')}</Link>
            {mode === 'login' && <Link className="small muted" to="/reset">{t('auth.forgot')}</Link>}
          </div>
        </form>
      </div>
    </div>
  )
}

export function ResetPage() {
  const [params] = useSearchParams()
  const token = params.get('token')
  const { setUser } = useAuth()
  const navigate = useNavigate()
  const [value, setValue] = useState('')
  const [sent, setSent] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (token) {
        setUser(await api.resetConfirm(token, value))
        navigate('/', { replace: true })
      } else {
        await api.resetRequest(value)
        setSent(true)
      }
    } catch (err) {
      setError(errorText(codeOf(err)))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth">
      <form className="panel auth-card" onSubmit={submit}>
        <Logo />
        <h2 className="h2">{t('auth.resetTitle')}</h2>
        {sent ? <p>{t('auth.resetSent')}</p> : (
          <>
            <div className="field">
              <label htmlFor="v">{token ? t('auth.newPassword') : t('auth.email')}</label>
              <input id="v" className="input" type={token ? 'password' : 'email'} required minLength={token ? 8 : undefined}
                autoComplete={token ? 'new-password' : 'email'} value={value} onChange={e => setValue(e.target.value)} />
            </div>
            {error && <p className="form-error" role="alert">{error}</p>}
            <button className="btn primary lg" disabled={busy}>{token ? t('auth.setPassword') : t('auth.resetSend')}</button>
          </>
        )}
        {!token && <p className="muted small">{t('auth.resetMailNote')}</p>}
        <Link className="small" to="/login">{t('auth.back')}</Link>
      </form>
    </div>
  )
}
