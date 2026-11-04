import { useState } from 'react'
import { api, type ActionCard, type Decision, type Feedback } from '../api'
import { t } from '../i18n'
import { IconAlert, IconCheck, IconChevron } from './icons'
import { KrinoFace } from './Krino'
import { Reveal } from './Reveal'

interface Props {
  decision: Decision
  onChange: (d: Decision) => void
  onToast: (text: string) => void
  onAskNow?: () => void
  onDetour?: () => void
  onRest?: () => void
}

function fmt(v: unknown): string {
  if (typeof v === 'boolean') return v ? '✓' : '✗'
  if (v === null || v === undefined) return '—'
  return typeof v === 'object' ? JSON.stringify(v) : String(v)
}

/** Sentences of a description, so the next step reads as a short numbered list. */
function steps(text: string): string[] {
  return text.split(/(?<=[。！？；!?])\s*|(?<=\.)\s+/).map(s => s.trim()).filter(Boolean)
}

/** One recommendation and one button; the alternatives fold into a numbered list, the basis stays closed. */
export function DecisionView({ decision, onChange, onToast, onAskNow, onDetour, onRest }: Props) {
  const r = decision.response
  const fb = decision.feedback
  const [open, setOpen] = useState<string | null>(null)
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
    try {
      await api.addMemory(`${key}: ${fmt(value)}`, decision.id)
      setRemembered(m => [...m, key])
      onToast(t('d.remembered'))
    } catch {
      onToast(t('err.generic'))
    }
  }

  const scores = r.action_scores
  const alerts = r.warnings.filter(w => !/KRINO Matrix/.test(w))
  const modeNotes = r.warnings.filter(w => /KRINO Matrix/.test(w))
  const constraintText = Object.fromEntries(r.problem.constraints.map(c => [c.id, c.text]))
  const best = r.actions.find(a => a.id === r.best_action)
  const others = r.actions.filter(a => a !== best)
  const chosen = fb?.chosen_action

  return (
    <div className="ai decision">
      <KrinoFace />
      <div className="decision-body">
        <div className="row between">
          <span className="kicker">// {t('d.next')}</span>
        </div>
        {best?.say && <p className="say">{best.say}</p>}
        <Reveal as="h2" className="display headline" text={best ? r.headline.replace(/[。.]$/, '') : t('d.noRecommendation')} />
        {!best && r.explanation && <p className="why">{r.explanation}</p>}

        {alerts.map(w => <p key={w} className="alert"><IconAlert size={15} />{w}</p>)}

        {best && (
          <div className="best">
            {(() => {
              const s = steps(best.description)
              return s.length > 1
                ? <ol className="steps">{s.map((x, i) => <li key={i} style={{ '--i': i } as React.CSSProperties}>{x}</li>)}</ol>
                : <p className="desc">{best.description}</p>
            })()}
            {(best.risks.length > 0 || best.requires_confirmation) && (
              <p className="watch">
                {best.requires_confirmation && <span className="tag solid">{t('d.confirm')}</span>}
                {best.requires_confirmation && " "}{best.risks.length > 0 && <><span className="kicker">{t('d.watch')}</span>&ensp;{best.risks.join(' · ')}</>}
              </p>
            )}
            <div>
              <button className={`btn primary lg go ${chosen === best.id ? 'done' : ''}`} disabled={busy}
                onClick={() => choose(best)} aria-pressed={chosen === best.id}>
                {chosen === best.id ? <><IconCheck size={18} className="draw" />{t('d.chosen')}</> : <>{t('d.go')}<span className="arrow">→</span></>}
              </button>
            </div>
            {(onAskNow || onDetour || onRest) && (
              <div className="detours">
                <span className="muted">{t('d.notFit')}</span>
                {onAskNow && <button className="link-btn" disabled={busy} onClick={onAskNow}>{t('d.askNow')}</button>}
                {onDetour && <button className="link-btn" disabled={busy} onClick={onDetour}>{t('d.detour')}</button>}
                {onRest && <button className="link-btn" disabled={busy} onClick={onRest}>{t('d.later')}</button>}
              </div>
            )}
          </div>
        )}

        <div className="decision-more">

        {others.length > 0 && (
          <details className="alts-fold">
            <summary><span className="kicker">// {t('d.others')} · {others.length}</span><IconChevron size={14} className="chev" /></summary>
            <div className="alts">
            {others.map((a, i) => {
              const excluded = a.excluded_by.length > 0
              const isOpen = open === a.id
              return (
                <div key={a.id} className={`alt ${excluded ? 'excluded' : ''} ${chosen === a.id ? 'chosen' : ''} ${isOpen ? 'open' : ''}`}
                  style={{ '--i': i } as React.CSSProperties}>
                  <button className="alt-head" onClick={() => setOpen(isOpen ? null : a.id)} aria-expanded={isOpen}>
                    <span className="n">{String(i + (best ? 2 : 1)).padStart(2, '0')}</span>
                    <span className="grow">{a.title}</span>
                    {chosen === a.id && <IconCheck size={15} />}
                    {scores && a.id in scores && <span className="meter" title={r.evaluator.score_meaning}><i style={{ width: `${scores[a.id] * 100}%` }} /></span>}
                    <IconChevron size={15} className="chev" />
                  </button>
                  {isOpen && (
                    <div className="alt-body">
                      <p className="desc">{a.description}</p>
                      {excluded && <p className="alert">{t('d.excluded', { items: a.excluded_by.map(c => constraintText[c] ?? c).join('；') })}</p>}
                      {(a.risks.length > 0 || a.requires_confirmation) && (
                        <div className="tags">
                          {a.requires_confirmation && <span className="tag solid">{t('d.confirm')}</span>}
                          {a.risks.map(x => <span key={x} className="tag">{x}</span>)}
                        </div>
                      )}
                      {chosen !== a.id && <button className="btn sm" disabled={busy} onClick={() => choose(a)}>{t('d.choose')}</button>}
                    </div>
                  )}
                  {reasonFor === a.id && (
                    <div className="ask-input">
                      <input className="input line" value={reason} autoFocus placeholder={t('d.reasonPlaceholder')}
                        onChange={e => setReason(e.target.value)}
                        onKeyDown={e => { if (e.key === 'Enter' && !e.nativeEvent.isComposing) { save({ reason }); setReasonFor(null) } }} />
                      <button className="btn sm" disabled={busy} onClick={() => { save({ reason }); setReasonFor(null) }}>{t('d.save')}</button>
                    </div>
                  )}
                </div>
              )
            })}
            </div>
          </details>
        )}

        <details className="basis">
          <summary><span className="kicker">// {t('d.evidence')}</span><IconChevron size={14} className="chev" /></summary>
          <div className="basis-body">
            {best && r.explanation && <p><span className="kicker">{t('d.why')}</span><br />{r.explanation}</p>}
            <div className="kv">
              <span className="k">{t('d.objective')}</span><span className="v">{r.problem.objective}</span><span />
              {Object.entries(r.problem.state).filter(([k]) => k !== 'observations').map(([k, v]) => (
                <div key={k} style={{ display: 'contents' }}>
                  <span className="k">{k}</span>
                  <span className="v">{fmt(v)}</span>
                  <button className="link-btn" disabled={remembered.includes(k)} onClick={() => remember(k, v)}>
                    {remembered.includes(k) ? t('d.remembered') : t('d.remember')}
                  </button>
                </div>
              ))}
            </div>
            {r.problem.constraints.length > 0 && (
              <div className="tags">
                {r.problem.constraints.map(c => (
                  <span key={c.id} className={`tag ${c.hard ? 'solid' : ''}`}>{c.hard ? t('d.hard') : t('d.preference')} · {c.text}</span>
                ))}
              </div>
            )}
            {scores && (
              <div className="bars">
                {r.actions.map(a => (
                  <div key={a.id} className={`bar-row ${a.id === r.best_action ? 'best' : ''}`}>
                    <span className="ellipsis">{a.title}</span>
                    <span className="mono">{(scores[a.id] ?? 0).toFixed(2)}</span>
                    <div className="track"><div className="fill" style={{ width: `${(scores[a.id] ?? 0) * 100}%` }} /></div>
                  </div>
                ))}
                <p className="muted small">{r.evaluator.score_meaning}</p>
              </div>
            )}
            {r.evidence.length > 0 && <ul className="evidence">{r.evidence.map(e => <li key={e}>{e}</li>)}</ul>}
            {modeNotes.map(w => <p key={w} className="muted small">{w}</p>)}
            <p className="kicker">{t('d.version')} · {r.model_version}</p>
          </div>
        </details>
        </div>
      </div>
    </div>
  )
}
