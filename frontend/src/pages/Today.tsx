import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, type Decision } from '../api'
import { Demo } from '../components/Demo'
import { GoalInput } from '../components/GoalInput'
import { IconChevron } from '../components/icons'
import { Empty } from '../components/States'
import { t } from '../i18n'

export function TodayPage() {
  const navigate = useNavigate()
  const [recent, setRecent] = useState<Decision[] | null>(null)

  useEffect(() => { api.decisions(5).then(setRecent, () => setRecent([])) }, [])

  const start = (text: string) => navigate('/c/new', { state: { text } })
  // The next step: the latest decision the user chose but has not finished or reported on
  const next = recent?.find(d => d.feedback?.chosen_action && d.feedback.status !== 'done' && !d.feedback.executed)
  const nextTitle = next?.response.actions.find(a => a.id === next.feedback?.chosen_action)?.title

  return (
    <div className="page">
      <section className="hero">
        <div className="stack" style={{ gap: 14 }}>
          <h1 className="h1">{t('app.question')}</h1>
          <p className="lead">{t('app.tagline')}</p>
        </div>
        <GoalInput onSubmit={start} autoFocus />
      </section>

      <div className="home-grid">
        {next && nextTitle && (
          <section className="stack">
            <span className="eyebrow">{t('today.next')}</span>
            <Link to={`/d/${next.id}`} className="list-item">
              <div className="grow">
                <div className="title">{nextTitle}</div>
                <div className="sub">{next.response.problem.objective}</div>
              </div>
              <span className="chip warn">{t('today.pending')}</span>
              <IconChevron size={16} />
            </Link>
          </section>
        )}

        {recent && recent.length === 0 && <Demo />}

        <section className="stack">
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <span className="eyebrow">{t('today.recent')}</span>
            {recent && recent.length > 0 && <Link to="/chats" className="small muted">{t('today.all')}</Link>}
          </div>
          {recent === null ? null : recent.length === 0 ? <Empty>{t('today.empty')}</Empty> : (
            <div className="list">
              {recent.map(d => (
                <Link key={d.id} to={`/d/${d.id}`} className="list-item">
                  <div className="grow">
                    <div className="title">{d.response.headline}</div>
                    <div className="sub">{d.response.problem.objective}</div>
                  </div>
                  {d.feedback?.status && <span className="chip">{t(`d.${d.feedback.status === 'chosen' ? 'chosen' : d.feedback.status}`)}</span>}
                  <IconChevron size={16} />
                </Link>
              ))}
            </div>
          )}
        </section>

        {recent && recent.length > 0 && <Demo />}
      </div>
    </div>
  )
}
