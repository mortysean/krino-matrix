import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, type Decision } from '../api'
import { GoalInput } from '../components/GoalInput'
import { IconArrow } from '../components/icons'
import { KrinoFigure } from '../components/Krino'
import { Reveal } from '../components/Reveal'
import { t } from '../i18n'

export function TodayPage() {
  const navigate = useNavigate()
  const [recent, setRecent] = useState<Decision[] | null>(null)
  const [typing, setTyping] = useState(false)

  useEffect(() => { api.decisions(4).then(setRecent, () => setRecent([])) }, [])

  const start = (text: string) => navigate('/c/new', { state: { text } })

  return (
    <div className="today">
      <section className="hero">
        <div className="hero-text">
          <span className="kicker">// {t('app.assistant')}</span>
          <Reveal as="h1" className="display" text={t('app.question')} />
          <p className="lede">{t('app.tagline')}</p>
          <GoalInput onSubmit={start} autoFocus onTyping={setTyping} />
        </div>
        <KrinoFigure mood={typing ? 'thinking' : 'idle'} className="hero-figure" />
      </section>

      {recent && recent.length > 0 && (
        <section className="recent">
          <div className="row between">
            <span className="kicker">// {t('today.recent')}</span>
            <Link to="/chats" className="kicker link">{t('today.all')} →</Link>
          </div>
          <ol className="rows">
            {recent.map((d, i) => (
              <li key={d.id} style={{ '--i': i } as React.CSSProperties}>
                <Link to={`/c/${d.conversation_id}`} className="row-link">
                  <span className="n">{String(i + 1).padStart(2, '0')}</span>
                  <span className="grow ellipsis">{d.objective_input}</span>
                  <IconArrow size={16} className="go" />
                </Link>
              </li>
            ))}
          </ol>
        </section>
      )}
    </div>
  )
}
