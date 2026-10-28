import type { Stage } from '../api'
import { t } from '../i18n'
import { Mark } from './Logo'

const STAGES: Stage[] = ['understand', 'clarify', 'compare']

/** The real stage the core reports. No percentages: the track only says which stage is running. */
export function Progress({ stage }: { stage: Stage | null }) {
  const current = stage ? STAGES.indexOf(stage) : 0
  return (
    <div className="panel progress" role="status" aria-live="polite">
      <div className="row">
        <Mark size={22} spinning />
        <span className="muted small">{t('stage.working')} · {t(`stage.${STAGES[current]}`)}</span>
      </div>
      <div className="progress-track">
        {STAGES.map((s, i) => (
          <div key={s} className={`progress-step ${i < current ? 'done' : i === current ? 'active' : ''}`}>
            <div className="bar" />
            <span>{t(`stage.${s}`)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
