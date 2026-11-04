import type { Stage } from '../api'
import { t } from '../i18n'
import { KrinoFace } from './Krino'

const STAGES: Stage[] = ['understand', 'clarify', 'compare']

/** The real stage the core reports, in one line. No percentages: it only says which stage is running. */
export function Progress({ stage }: { stage: Stage | null }) {
  const current = stage ? STAGES.indexOf(stage) : 0
  return (
    <div className="ai thinking-row" role="status" aria-live="polite">
      <KrinoFace mood="thinking" />
      <div className="stages">
        {STAGES.map((s, i) => (
          <span key={s} className={`stage ${i < current ? 'done' : i === current ? 'active' : ''}`}>
            {t(`stage.${s}`)}{i === current && <i className="dots"><b>.</b><b>.</b><b>.</b></i>}
          </span>
        ))}
        <span className="scanbar" />
      </div>
    </div>
  )
}
