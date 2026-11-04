import { useState } from 'react'
import { t } from '../i18n'
import { IconArrow } from './icons'

interface Props {
  onSubmit: (text: string) => void
  initial?: string
  busy?: boolean
  autoFocus?: boolean
  onTyping?: (typing: boolean) => void
}

export function GoalInput({ onSubmit, initial = '', busy = false, autoFocus = false, onTyping }: Props) {
  const [text, setText] = useState(initial)
  const submit = () => { if (text.trim() && !busy) onSubmit(text.trim()) }
  return (
    <div className="goal">
      <label htmlFor="goal" className="sr-only">{t('app.question')}</label>
      <textarea id="goal" value={text} placeholder={t('app.placeholder')} autoFocus={autoFocus} rows={2} maxLength={4000}
        onChange={e => { setText(e.target.value); onTyping?.(e.target.value.trim().length > 0) }}
        onBlur={() => onTyping?.(false)}
        onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit() } }} />
      <button className="btn primary round" onClick={submit} disabled={!text.trim() || busy} aria-label={t('app.start')}>
        <IconArrow size={20} />
      </button>
      <span className="goal-line" aria-hidden="true" />
    </div>
  )
}
