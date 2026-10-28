import { useState } from 'react'
import type { Answer, Question } from '../api'
import { t } from '../i18n'

interface Props {
  question: Question
  asked?: number
  max?: number
  busy: boolean
  onAnswer: (answer: Omit<Answer, 'question'>) => void
  onDecideNow: () => void
}

const OTHER = '__other__'

/** One key question at a time: single or multiple choice with "other", or free text. Skippable unless required. */
export function QuestionCard({ question, asked, max, busy, onAnswer, onDecideNow }: Props) {
  const [picked, setPicked] = useState<string[]>([])
  const [other, setOther] = useState('')
  const multi = question.kind === 'multi'
  const hasOther = picked.includes(OTHER) || question.kind === 'text'

  const toggle = (v: string) => setPicked(p => multi ? (p.includes(v) ? p.filter(x => x !== v) : [...p, v]) : [v])
  const values = picked.filter(v => v !== OTHER)
  const ready = values.length > 0 || (hasOther && other.trim().length > 0)

  const submit = () => {
    if (!ready || busy) return
    onAnswer({ question_id: question.id, values, text: hasOther ? other.trim() : '', skipped: false })
  }

  return (
    <div className="panel section question" role="group" aria-labelledby={`q-${question.id}`}>
      {asked && max ? <span className="eyebrow">{t('q.progress', { n: asked, max })}</span> : null}
      <div className="stack" style={{ gap: 6 }}>
        <h3 className="h3" id={`q-${question.id}`}>{question.text}</h3>
        {question.why && <p className="muted small">{question.why}</p>}
      </div>

      {question.kind !== 'text' && (
        <div className="options" role={multi ? 'group' : 'radiogroup'}>
          {[...question.options, OTHER].map(o => (
            <button key={o} type="button" role={multi ? 'checkbox' : 'radio'} aria-checked={picked.includes(o)}
              className={`option ${picked.includes(o) ? 'on' : ''}`} onClick={() => toggle(o)} disabled={busy}>
              <span className={`tick ${multi ? 'square' : 'round'}`} />
              <span>{o === OTHER ? t('q.other') : o}</span>
            </button>
          ))}
        </div>
      )}
      {hasOther && (
        <textarea className="textarea" rows={2} value={other} autoFocus
          placeholder={question.kind === 'text' ? t('q.textPlaceholder') : t('q.otherPlaceholder')}
          onChange={e => setOther(e.target.value)} disabled={busy}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit() } }} />
      )}

      <div className="row" style={{ justifyContent: 'space-between' }}>
        <div className="row">
          <button className="btn primary" onClick={submit} disabled={!ready || busy}>{t('q.submit')}</button>
          {!question.required && (
            <button className="btn ghost" disabled={busy}
              onClick={() => onAnswer({ question_id: question.id, values: [], text: '', skipped: true })}>
              {t('q.skip')}
            </button>
          )}
        </div>
        <button className="btn ghost sm" onClick={onDecideNow} disabled={busy}>{t('q.decideNow')}</button>
      </div>
      {question.required && <p className="muted small">{t('q.required')}</p>}
    </div>
  )
}
