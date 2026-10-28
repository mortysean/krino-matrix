import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError, type Memory, type Status } from '../api'
import { useAuth } from '../auth'
import { Toast, useToast } from '../components/States'
import { errorText, getLocale, setLocale, t, type Locale } from '../i18n'
import { setPrefs, usePrefs, type Motion, type Theme } from '../prefs'

function Seg<T extends string>({ value, options, onChange }: { value: T; options: [T, string][]; onChange: (v: T) => void }) {
  return (
    <div className="seg">
      {options.map(([v, label]) => <button key={v} className={value === v ? 'on' : ''} onClick={() => onChange(v)} aria-pressed={value === v}>{label}</button>)}
    </div>
  )
}

export function SettingsPage() {
  const { user, setUser } = useAuth()
  const navigate = useNavigate()
  const prefs = usePrefs()
  const [toast, showToast] = useToast()
  const [status, setStatus] = useState<Status | null>(null)
  const [memories, setMemories] = useState<Memory[]>([])
  const [newMemory, setNewMemory] = useState('')
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(null)
  const [pw, setPw] = useState({ current: '', next: '' })
  const [pwError, setPwError] = useState<string | null>(null)
  const [locale, setLoc] = useState<Locale>(getLocale())

  useEffect(() => {
    api.status().then(setStatus, () => {})
    api.memories().then(setMemories, () => {})
  }, [])

  const fail = (e: unknown) => showToast(errorText(e instanceof ApiError ? e.message : 'generic'))

  const addMemory = async (e: FormEvent) => {
    e.preventDefault()
    if (!newMemory.trim()) return
    try {
      const m = await api.addMemory(newMemory.trim())
      setMemories(list => [m, ...list])
      setNewMemory('')
    } catch (err) { fail(err) }
  }

  const saveMemory = async () => {
    if (!editing) return
    try {
      const m = await api.editMemory(editing.id, editing.text)
      setMemories(list => list.map(x => x.id === m.id ? m : x))
      setEditing(null)
    } catch (err) { fail(err) }
  }

  const removeMemory = async (id: string) => {
    try {
      await api.deleteMemory(id)
      setMemories(list => list.filter(x => x.id !== id))
    } catch (err) { fail(err) }
  }

  const changePassword = async (e: FormEvent) => {
    e.preventDefault()
    setPwError(null)
    try {
      await api.changePassword(pw.current, pw.next)
      setPw({ current: '', next: '' })
      showToast(t('s.saved'))
    } catch (err) {
      setPwError(errorText(err instanceof ApiError ? err.message : 'generic'))
    }
  }

  const deleteHistory = async () => {
    if (!window.confirm(t('s.confirmHistory'))) return
    try { await api.deleteHistory(); showToast(t('s.saved')) } catch (err) { fail(err) }
  }

  const deleteAccount = async () => {
    const password = window.prompt(t('s.confirmAccount'))
    if (!password) return
    try {
      await api.deleteAccount(password)
      setUser(null)
      navigate('/login', { replace: true })
    } catch (err) { fail(err) }
  }

  const u = status?.usage
  return (
    <div className="page narrow settings">
      <h1 className="h2">{t('s.title')}</h1>

      <section className="panel section stack">
        <h2>{t('s.account')}</h2>
        <div className="setting-row"><span className="label">{t('auth.email')}</span><span>{user?.email}</span></div>
        <form className="setting-row" onSubmit={changePassword} style={{ alignItems: 'flex-end' }}>
          <div className="row" style={{ flex: 1 }}>
            <input className="input" style={{ flex: '1 1 160px' }} type="password" autoComplete="current-password" required
              placeholder={t('s.currentPassword')} aria-label={t('s.currentPassword')} value={pw.current} onChange={e => setPw({ ...pw, current: e.target.value })} />
            <input className="input" style={{ flex: '1 1 160px' }} type="password" autoComplete="new-password" required minLength={8}
              placeholder={t('s.newPassword')} aria-label={t('s.newPassword')} value={pw.next} onChange={e => setPw({ ...pw, next: e.target.value })} />
          </div>
          <button className="btn">{t('s.changePassword')}</button>
          {pwError && <p className="form-error" style={{ width: '100%' }}>{pwError}</p>}
        </form>
      </section>

      <section className="panel section stack">
        <h2>{t('s.memories')}</h2>
        <p className="muted small">{t('s.memoriesNote')}</p>
        <form className="row" onSubmit={addMemory} style={{ flexWrap: 'nowrap' }}>
          <input className="input" value={newMemory} placeholder={t('s.memoryAdd')} aria-label={t('s.memoryAdd')} onChange={e => setNewMemory(e.target.value)} />
          <button className="btn" disabled={!newMemory.trim()}>+</button>
        </form>
        <div>
          {memories.length === 0 && <p className="muted small">{t('s.memoryEmpty')}</p>}
          {memories.map(m => (
            <div key={m.id} className="memory">
              {editing?.id === m.id ? (
                <>
                  <input className="input grow" value={editing.text} autoFocus aria-label={t('s.edit')}
                    onChange={e => setEditing({ id: m.id, text: e.target.value })} onKeyDown={e => { if (e.key === 'Enter') saveMemory() }} />
                  <button className="btn sm" onClick={saveMemory}>{t('d.save')}</button>
                  <button className="btn ghost sm" onClick={() => setEditing(null)}>{t('s.cancel')}</button>
                </>
              ) : (
                <>
                  <span className="grow">{m.text}</span>
                  <button className="btn ghost sm" onClick={() => setEditing({ id: m.id, text: m.text })}>{t('s.edit')}</button>
                  <button className="btn ghost sm danger" onClick={() => removeMemory(m.id)}>{t('s.delete')}</button>
                </>
              )}
            </div>
          ))}
        </div>
      </section>

      <section className="panel section stack">
        <h2>{t('s.privacy')}</h2>
        <div className="setting-row"><span className="label">{t('s.deleteHistory')}</span><button className="btn sm danger" onClick={deleteHistory}>{t('s.delete')}</button></div>
        <div className="setting-row"><span className="label">{t('s.deleteAccount')}</span><button className="btn sm danger" onClick={deleteAccount}>{t('s.deleteAccount')}</button></div>
      </section>

      <section className="panel section stack">
        <h2>{t('s.model')}</h2>
        <div className="setting-row"><span className="label">{t('s.modelName')}</span>
          <span className="mono">{status ? (status.model.configured ? status.model.name : t('s.notConfigured')) : '…'}</span></div>
        <div className="setting-row"><span className="label">{t('s.evaluator')}</span>
          <span className={`chip ${status?.evaluator.mode === 'matrix' ? 'accent' : 'warn'}`}>
            {status?.evaluator.mode === 'matrix' ? t('s.evalMatrix') : t('s.evalBaseline')}</span></div>
        <p className="muted small">{t('s.evalNote')}</p>
        <div className="setting-row"><span className="label">{t('s.byok')}</span><span className="chip">{t('s.notLive')}</span></div>
      </section>

      <section className="panel section stack">
        <h2>{t('s.usage')}</h2>
        {u && (
          <div className="stats">
            <div className="stat"><div className="n">{u.turns_today} / {u.daily_quota}</div><div className="l">{t('s.today')}</div></div>
            <div className="stat"><div className="n">{u.calls}</div><div className="l">{t('s.calls')}</div></div>
            <div className="stat"><div className="n">{u.failed_calls}</div><div className="l">{t('s.failed')}</div></div>
            <div className="stat"><div className="n">{u.avg_latency_ms === null ? '—' : `${(u.avg_latency_ms / 1000).toFixed(1)}s`}</div><div className="l">{t('s.latency')}</div></div>
            <div className="stat"><div className="n">{(u.input_tokens + u.output_tokens).toLocaleString()}</div><div className="l">{t('s.tokens')}</div></div>
          </div>
        )}
        <div className="setting-row"><span className="label">{t('s.balance')}</span><span className="chip">{t('s.notLive')}</span></div>
      </section>

      <section className="panel section stack">
        <h2>{t('s.display')}</h2>
        <div className="setting-row"><span className="label">{t('s.theme')}</span>
          <Seg<Theme> value={prefs.theme} onChange={v => setPrefs({ theme: v })}
            options={[['light', t('s.themeLight')], ['dark', t('s.themeDark')], ['system', t('s.themeSystem')]]} /></div>
        <div className="setting-row"><span className="label">{t('s.motion')}</span>
          <Seg<Motion> value={prefs.motion} onChange={v => setPrefs({ motion: v })}
            options={[['auto', t('s.motionAuto')], ['reduced', t('s.motionReduced')], ['full', t('s.motionFull')]]} /></div>
        <div className="setting-row"><span className="label">{t('s.language')}</span>
          <Seg<Locale> value={locale} onChange={v => { setLocale(v); setLoc(v); window.location.reload() }}
            options={[['zh', '中文'], ['en', 'English']]} /></div>
      </section>
      <Toast text={toast} />
    </div>
  )
}
