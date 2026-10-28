import { useState } from 'react'
import { api, type ActionCard, type Decision, type Feedback } from '../api'
import { t } from '../i18n'
import { IconAlert, IconCheck, IconChevron, IconInfo } from './icons'

interface Props {
  decision: Decision
  onChange: (d: Decision) => void
  onToast: (text: string) => void
}

function fmt(v: unknown): string {
  if (typeof v === 'boolean') return v ? '✓' : '✗'
  if (v === null || v === undefined) return '—'
  return typeof v === 'object' ? JSON.stringify(v) : String(v)
}

export function DecisionView({ decision, onChange, onToast }: Props) {
  const r = decision.response
  const fb = decision.feedback
  const [reasonFor, setReasonFor] = useState<string | null>(null)
  const [reason, setReason] = useState(fb?.reason ?? '')
  const [busy, setBusy] = useState(false)
  const [remembered, setRemembered] = useState<string[]>([])

  const save = async (body: Partial<Feedback>, toast = t('d.statusSaved')) => {
    setBusy(true)
    try {
      onChange(await api.feedback(decision.id, body))
      onToast(toast)
    } catch {
      onToast(t('err.generic'))
    } finally {
      setBusy(false)
    }
  }

  const choose = (card: ActionCard) => {
    if (card.id !== r.best_action) setReasonFor(card.id)
    save({ chosen_action: card.id, status: 'chosen' })
  }

  const remember = async (key: string, value: unknown) => {
    const text = `${key}: ${fmt(value)}`
    try {
      await api.addMemory(text, decision.id)
      setRemembered(m => [...m, key])
      onToast(t('d.remembered'))
    } catch {
      onToast(t('err.generic'))
    }
  }

  const scores = r.action_scores
  const strongWarnings = r.warnings.filter(w => !/Baseline|KRINO Matrix/.test(w))
  const modeNotes = r.warnings.filter(w => /Baseline|KRINO Matrix/.test(w))
  const constraintText = Object.fromEntries(r.problem.constraints.map(c => [c.id, c.text]))

  return (
    <div className="decision">
      <header className="decision-top">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <span className="eyebrow">{t('d.next')}</span>
          <span className={`chip ${r.evaluator.mode === 'baseline' ? 'warn' : 'accent'}`}>{r.evaluator.name}</span>
        </div>
        <h2 className="h2">{r.best_action ? r.headline : t('d.noRecommendation')}</h2>
        {r.explanation && <p className="why">{r.explanation}</p>}
      </header>

      {strongWarnings.length > 0 && (
        <div className="warnings">
          {strongWarnings.map(w => <div key={w} className="warning strong"><IconAlert size={16} style={{ flex: 'none', marginTop: 3 }} />{w}</div>)}
        </div>
      )}

      <div className="cards">
        {r.actions.map(card => {
          const best = card.id === r.best_action
          const selected = fb?.chosen_action === card.id
          return (
            <article key={card.id} className={`card ${best ? 'best' : ''} ${selected ? 'selected' : ''} ${card.excluded_by.length ? 'excluded' : ''}`}>
              <div className="card-head">
                <span className={`chip ${best ? 'accent' : ''}`}>{best ? t('d.recommended') : t('d.alternative')}</span>
                {card.requires_confirmation && <span className="chip warn">{t('d.confirm')}</span>}
              </div>
              <h3 className="h3">{card.title}</h3>
              <p className="desc">{card.description}</p>
              <div className="meta">
                {card.difference && <span><b>{t('d.difference')}：</b>{card.difference}</span>}
                {card.risks.length > 0 && <span><b>{t('d.risks')}：</b>{card.risks.join('；')}</span>}
                {card.excluded_by.length > 0 && (
                  <span className="chip danger" style={{ justifySelf: 'start', whiteSpace: 'normal' }}>
                    {t('d.excluded', { items: card.excluded_by.map(c => constraintText[c] ?? c).join('；') })}
                  </span>
                )}
              </div>
              <div className="foot">
                {scores && card.id in scores
                  ? <span className="score" title={r.evaluator.score_meaning}>{t('d.scoreLabel')} <span className="num">{scores[card.id].toFixed(2)}</span><IconInfo size={13} /></span>
                  : <span />}
                <button className={`btn sm ${selected ? 'on' : best ? 'primary' : ''}`} disabled={busy}
                  onClick={() => choose(card)} aria-pressed={selected}>
                  {selected ? <><IconCheck size={15} />{t('d.chosen')}</> : t('d.choose')}
                </button>
              </div>
              {reasonFor === card.id && (
                <div className="stack" style={{ gap: 8 }}>
                  <label className="small muted" htmlFor={`reason-${card.id}`}>{t('d.reasonPrompt')}</label>
                  <textarea id={`reason-${card.id}`} className="textarea" rows={2} value={reason}
                    placeholder={t('d.reasonPlaceholder')} onChange={e => setReason(e.target.value)} />
                  <div className="row">
                    <button className="btn sm" disabled={busy} onClick={() => { save({ reason }); setReasonFor(null) }}>{t('d.save')}</button>
                    <button className="btn ghost sm" onClick={() => setReasonFor(null)}>{t('s.cancel')}</button>
                  </div>
                </div>
              )}
            </article>
          )
        })}
      </div>

      <div className="status-row">
        {(['later', 'unsuitable', 'done'] as const).map(s => (
          <button key={s} className={`btn sm ${fb?.status === s ? 'on' : ''}`} disabled={busy}
            onClick={() => save({ status: s })} aria-pressed={fb?.status === s}>
            {t(`d.${s}`)}
          </button>
        ))}
      </div>

      {(fb?.chosen_action || fb?.status === 'done') && <FeedbackForm feedback={fb} busy={busy} onSave={b => save(b, t('fb.saved'))} />}

      <details className="evidence">
        <summary><IconChevron size={15} className="chev" />{t('d.evidence')}</summary>
        <div className="evidence-body">
          <div className="stack" style={{ gap: 8 }}>
            <span className="eyebrow">{t('d.objective')}</span>
            <p>{r.problem.objective}</p>
          </div>
          <div className="stack" style={{ gap: 8 }}>
            <span className="eyebrow">{t('d.state')}</span>
            {Object.keys(r.problem.state).length === 0 ? <p className="muted small">{t('d.none')}</p> : (
              <div className="kv">
                {Object.entries(r.problem.state).filter(([k]) => k !== 'observations').map(([k, v]) => (
                  <div key={k} style={{ display: 'contents' }}>
                    <span className="k">{k}</span>
                    <span className="v">{fmt(v)}</span>
                    <button className="btn ghost sm" disabled={remembered.includes(k)} onClick={() => remember(k, v)}>
                      {remembered.includes(k) ? t('d.remembered') : t('d.remember')}
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="stack" style={{ gap: 8 }}>
            <span className="eyebrow">{t('d.constraints')}</span>
            {r.problem.constraints.length === 0 ? <p className="muted small">{t('d.none')}</p> : (
              <div className="row">
                {r.problem.constraints.map(c => (
                  <span key={c.id} className={`chip ${c.hard ? 'solid' : ''}`} style={{ whiteSpace: 'normal' }}>
                    {c.hard ? t('d.hard') : t('d.preference')} · {c.text}
                  </span>
                ))}
              </div>
            )}
          </div>
          {r.evidence.length > 0 && (
            <div className="stack" style={{ gap: 8 }}>
              <span className="eyebrow">{t('d.reasoning')}</span>
              <ul style={{ margin: 0, paddingLeft: 18, display: 'grid', gap: 6 }}>
                {r.evidence.map(e => <li key={e} className="small">{e}</li>)}
              </ul>
            </div>
          )}
          {scores && (
            <div className="stack" style={{ gap: 10 }}>
              <span className="eyebrow">{t('d.scores')}</span>
              <div className="bars">
                {r.actions.map(a => (
                  <div key={a.id} className={`bar-row ${a.id === r.best_action ? 'best' : ''}`}>
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.title}</span>
                    <span className="mono" style={{ textAlign: 'right' }}>{(scores[a.id] ?? 0).toFixed(2)}</span>
                    <div className="track"><div className="fill" style={{ width: `${(scores[a.id] ?? 0) * 100}%` }} /></div>
                  </div>
                ))}
              </div>
              {r.confidence !== null && <p className="small">{t('d.confidence')}：<span className="mono">{r.confidence.toFixed(2)}</span></p>}
              <p className="muted small">{r.evaluator.score_meaning}</p>
            </div>
          )}
          <div className="stack" style={{ gap: 6 }}>
            {modeNotes.map(w => <div key={w} className="warning"><IconInfo size={16} style={{ flex: 'none', marginTop: 3 }} />{w}</div>)}
            <p className="muted small">{t('d.version')}：<span className="mono">{r.model_version}</span></p>
          </div>
        </div>
      </details>
    </div>
  )
}

function FeedbackForm({ feedback, busy, onSave }: { feedback: Feedback; busy: boolean; onSave: (b: Partial<Feedback>) => void }) {
  const [outcome, setOutcome] = useState(feedback.outcome)
  return (
    <section className="panel section feedback" aria-label={t('fb.title')}>
      <div className="stack" style={{ gap: 4 }}>
        <h3 className="h3">{t('fb.title')}</h3>
        <p className="muted small">{t('fb.note')}</p>
      </div>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <span>{t('fb.executed')}</span>
        <div className="seg">
          {(['yes', 'no'] as const).map(v => (
            <button key={v} className={feedback.executed === v ? 'on' : ''} disabled={busy} onClick={() => onSave({ executed: v })}>
              {t(v === 'yes' ? 'fb.yes' : 'fb.no')}
            </button>
          ))}
        </div>
      </div>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <span>{t('fb.helpful')}</span>
        <div className="seg">
          {(['yes', 'partly', 'no'] as const).map(v => (
            <button key={v} className={feedback.helpful === v ? 'on' : ''} disabled={busy} onClick={() => onSave({ helpful: v })}>
              {t(v === 'yes' ? 'fb.helpYes' : v === 'partly' ? 'fb.helpPartly' : 'fb.helpNo')}
            </button>
          ))}
        </div>
      </div>
      <div className="field">
        <label htmlFor="outcome">{t('fb.outcome')}</label>
        <textarea id="outcome" className="textarea" rows={2} value={outcome} onChange={e => setOutcome(e.target.value)} />
      </div>
      {outcome !== feedback.outcome && (
        <div><button className="btn sm" disabled={busy} onClick={() => onSave({ outcome })}>{t('d.save')}</button></div>
      )}
    </section>
  )
}
