import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, ApiError, type Decision } from '../api'
import { DecisionView } from '../components/DecisionView'
import { Progress } from '../components/Progress'
import { Empty, Toast, useToast } from '../components/States'
import { errorText, getLocale, t } from '../i18n'

export function DecisionPage() {
  const { id } = useParams()
  const [decision, setDecision] = useState<Decision | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [toast, showToast] = useToast()

  useEffect(() => {
    if (id) api.decision(id).then(setDecision, e => setError(errorText(e instanceof ApiError && e.status === 404 ? 'not_found' : 'generic')))
  }, [id])

  if (error) return <div className="page narrow"><Empty><p>{error}</p><Link className="btn" to="/">{t('nav.today')}</Link></Empty></div>
  if (!decision) return <div className="page narrow"><Progress stage={null} /></div>

  return (
    <div className="page narrow stack" style={{ gap: 20 }}>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <Link to={`/c/${decision.conversation_id}`} className="small muted">← {t('nav.chats')}</Link>
        <span className="small muted">{new Date(decision.created_at).toLocaleString(getLocale() === 'zh' ? 'zh-CN' : 'en')}</span>
      </div>
      <div className="bubble-user" style={{ justifySelf: 'start' }}>{decision.objective_input}</div>
      {decision.answers.length > 0 && (
        <div className="stack" style={{ gap: 4 }}>
          {decision.answers.map(a => (
            <p key={a.question_id} className="small muted">{a.question} → {a.skipped ? t('q.skipped') : [...a.values, a.text].filter(Boolean).join('；')}</p>
          ))}
        </div>
      )}
      <DecisionView decision={decision} onChange={setDecision} onToast={showToast} />
      <Toast text={toast} />
    </div>
  )
}
