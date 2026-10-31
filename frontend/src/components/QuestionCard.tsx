import { useState } from 'react'
import type { Answer, Question } from '../api'
import { t } from '../i18n'
import { IconArrow } from './icons'
import { KrinoFace } from './Krino'
import { Reveal } from './Reveal'

interface Props {
  question: Question
  asked?: number
  max?: number
  busy: boolean
  onAnswer: (answer: Omit<Answer, 'question'>) => void
  onDecideNow: () => void
}

const OTHER = '__other__'

/** One key question. A single choice answers on click; multiple choice and free text confirm with the arrow. */
export function QuestionCard({ question, busy, onAnswer, onDecideNow }: Props) {
  const [picked, setPicked] = useState<string[]>([])
  const [other, setOther] = useState('')
  const multi = question.kind === 'multi'
  const typing = picked.includes(OTHER) || question.kind === 'text'

  const values = picked.filter(v => v !== OTHER)
  const ready = values.length > 0 || (typing && other.trim().length > 0)
  const answer = (vals: string[], text: string) =>
    onAnswer({ question_id: question.id, values: vals, text, skipped: false })

  const pick = (o: string) => {
    if (busy) return
    if (!multi && o !== OTHER) { answer([o], ''); return }
    setPicked(p => multi ? (p.includes(o) ? p.filter(x => x !== o) : [...p, o]) : [o])
  }
  const submit = () => { if (ready && !busy) answer(values, typing ? other.trim() : '') }

  return (
    <div className="ai ask" role="group" aria-label={question.text}>
      <KrinoFace />
      <div className="ask-body">
        <span className="kicker">// {t('q.where')}</span>
        <Reveal as="h3" className="ask-q" text={question.text} />

        {question.kind !== 'text' && (
          <div className="opts" role={multi ? 'group' : 'radiogroup'}>
            {[...question.options, OTHER].map((o, i) => (
              <button key={o} type="button" role={multi ? 'checkbox' : 'radio'} aria-checked={picked.includes(o)}
                className={`opt ${picked.includes(o) ? 'on' : ''}`} style={{ '--i': i } as React.CSSProperties}
                onClick={() => pick(o)} disabled={busy}>
                {o === OTHER ? t('q.other') : o}
              </button>
            ))}
          </div>
        )}

        {(typing || (multi && values.length > 0)) && (
          <div className="ask-input">
            {typing && (
              <input className="input line" value={other} autoFocus disabled={busy}
                placeholder={question.kind === 'text' ? t('q.textPlaceholder') : t('q.otherPlaceholder')}
                onChange={e => setOther(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && !e.nativeEvent.isComposing) { e.preventDefault(); submit() } }} />
            )}
            <button className="btn primary round sm" onClick={submit} disabled={!ready || busy} aria-label={t('q.submit')}>
              <IconArrow size={16} />
            </button>
          </div>
        )}

        <div className="ask-foot">
          {!question.required && (
            <button className="link-btn" disabled={busy}
              onClick={() => onAnswer({ question_id: question.id, values: [], text: '', skipped: true })}>
              {t('q.skip')}
            </button>
          )}
          <button className="link-btn" onClick={onDecideNow} disabled={busy}>{t('q.decideNow')} →</button>
        </div>
      </div>
    </div>
  )
}
