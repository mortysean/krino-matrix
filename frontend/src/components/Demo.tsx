import { useEffect, useRef, useState } from 'react'
import { t, type Key } from '../i18n'
import { useReducedMotion } from '../prefs'
import { IconPause, IconPlay, IconReplay } from './icons'

// A looping product example: goal → state and constraints → compare → recommendation. Demo data only.

const STEPS: Key[] = ['demo.s1', 'demo.s2', 'demo.s3', 'demo.s4']
const DURATION = [2200, 1900, 2100, 3000]    // ms per step; the last one holds the result long enough to read
const TYPE_MS = 1500

export function Demo() {
  const reduced = useReducedMotion()
  const [step, setStep] = useState(reduced ? 3 : 0)
  const [playing, setPlaying] = useState(!reduced)
  const [typed, setTyped] = useState(reduced ? Infinity : 0)
  const [paused, setPaused] = useState(false)      // paused because the demo is off-screen or the tab hidden
  const ref = useRef<HTMLDivElement>(null)
  const goal = t('demo.goal')

  useEffect(() => {
    if (reduced) { setPlaying(false); setStep(3); setTyped(Infinity) }
  }, [reduced])

  // Do not animate what nobody sees
  useEffect(() => {
    const el = ref.current
    if (!el || !('IntersectionObserver' in window)) return
    const io = new IntersectionObserver(([e]) => setPaused(!e.isIntersecting || document.hidden))
    io.observe(el)
    const vis = () => setPaused(document.hidden)
    document.addEventListener('visibilitychange', vis)
    return () => { io.disconnect(); document.removeEventListener('visibilitychange', vis) }
  }, [])

  useEffect(() => {
    if (!playing || paused) return
    const id = window.setTimeout(() => {
      setStep(s => (s + 1) % STEPS.length)
      if (step === STEPS.length - 1) setTyped(0)
    }, DURATION[step])
    return () => window.clearTimeout(id)
  }, [playing, paused, step])

  useEffect(() => {
    if (step !== 0 || !playing || paused || typed >= goal.length) return
    const id = window.setTimeout(() => setTyped(n => n + 1), TYPE_MS / goal.length)
    return () => window.clearTimeout(id)
  }, [step, typed, playing, paused, goal.length])

  const jump = (i: number) => { setStep(i); setTyped(i === 0 && playing ? 0 : Infinity) }
  const replay = () => { setStep(0); setTyped(0); setPlaying(true) }

  const shownGoal = step === 0 ? goal.slice(0, typed) : goal
  const cards = [
    { key: 'demo.a1' as Key, best: true },
    { key: 'demo.a2' as Key, best: false },
    { key: 'demo.a3' as Key, best: false, excluded: true },
  ]

  return (
    <section className="panel demo" ref={ref} aria-label={t('demo.label')}>
      <div className="demo-head">
        <div className="demo-steps" role="tablist">
          {STEPS.map((s, i) => (
            <button key={s} role="tab" aria-selected={i === step} className={i === step ? 'on' : ''} onClick={() => jump(i)}>
              <span className="dot" />{t(s)}
            </button>
          ))}
        </div>
        <div className="row" style={{ gap: 4 }}>
          <span className="chip warn">{t('demo.label')}</span>
          <button className="btn ghost sm" onClick={() => setPlaying(p => !p)} aria-label={playing ? t('demo.pause') : t('demo.play')}>
            {playing ? <IconPause size={15} /> : <IconPlay size={15} />}
          </button>
          <button className="btn ghost sm" onClick={replay} aria-label={t('demo.replay')}><IconReplay size={15} /></button>
        </div>
      </div>
      <div className="demo-body" aria-live="off">
        <div className="demo-goal">
          {shownGoal}{step === 0 && playing && <span className="caret" />}
        </div>
        <div className="demo-chips">
          {step >= 1 && <>
            <span className="chip">{t('demo.state1')}</span>
            <span className="chip" style={{ animationDelay: '80ms' }}>{t('demo.state2')}</span>
            <span className="chip solid" style={{ animationDelay: '160ms' }}>{t('demo.c1')}</span>
            <span className="chip solid" style={{ animationDelay: '240ms' }}>{t('demo.c2')}</span>
          </>}
        </div>
        <div className="demo-cards">
          {step >= 2 && cards.map((c, i) => (
            <div key={c.key} style={{ animationDelay: `${i * 90}ms` }}
              className={`demo-card ${step === 3 && c.best ? 'best' : ''} ${step === 3 && !c.best ? 'dim' : ''}`}>
              <div className="row" style={{ justifyContent: 'space-between' }}>
                {step === 3
                  ? c.best ? <span className="chip accent">{t('d.recommended')}</span>
                    : c.excluded ? <span className="chip danger">{t('demo.a3x')}</span>
                      : <span className="chip">{t('d.alternative')}</span>
                  : <span className="chip">#{i + 1}</span>}
              </div>
              <span>{t(c.key)}</span>
              {step === 2 && <div className="scan"><i style={{ animationDelay: `${i * 150}ms` }} /></div>}
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
