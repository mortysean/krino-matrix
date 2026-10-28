import { useState } from 'react'
import { t } from '../i18n'
import { IconArrow } from './icons'

interface Props {
  onSubmit: (text: string) => void
  initial?: string
  busy?: boolean
  autoFocus?: boolean
}

export function GoalInput({ onSubmit, initial = '', busy = false, autoFocus = false }: Props) {
  const [text, setText] = useState(initial)
  const submit = () => { if (text.trim() && !busy) onSubmit(text.trim()) }
  return (
    <div className="panel goal-box">
      <label htmlFor="goal" className="sr-only">{t('app.question')}</label>
      <textarea id="goal" className="textarea" value={text} placeholder={t('app.placeholder')} autoFocus={autoFocus}
        onChange={e => setText(e.target.value)} maxLength={4000}
        onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit() } }} />
      <div className="bar">
        <span className="muted small">{t('app.hint')}</span>
        <button className="btn primary lg" onClick={submit} disabled={!text.trim() || busy}>
          {t('app.start')}<IconArrow size={17} />
        </button>
      </div>
    </div>
  )
}
