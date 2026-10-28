import { useEffect, useState } from 'react'
import type { ErrorResponse } from '../api'
import { t } from '../i18n'
import { IconAlert } from './icons'

const TITLE: Record<string, Parameters<typeof t>[0]> = {
  model_unavailable: 'e.modelDown',
  quota_exceeded: 'e.quota',
}

interface ErrorProps {
  error: ErrorResponse
  active: boolean          // only the latest error offers actions
  onRetry?: () => void
  onEdit?: () => void
}

/** A failure says what happened and what to do next; it never shows a conclusion. */
export function ErrorBox({ error, active, onRetry, onEdit }: ErrorProps) {
  const kind = error.code === 'quota_exceeded' ? 'quota' : error.code === 'model_unavailable' ? 'model' : ''
  return (
    <div className={`error-box ${kind}`} role="alert">
      <div className="row" style={{ gap: 8 }}>
        <IconAlert size={17} />
        <strong>{t(TITLE[error.code] ?? 'e.failed')}</strong>
      </div>
      <p className="small">{error.message}</p>
      {active && (
        <div className="row">
          {error.suggestions.includes('retry') && error.retryable && onRetry && <button className="btn sm" onClick={onRetry}>{t('e.retry')}</button>}
          {error.suggestions.includes('edit') && onEdit && <button className="btn sm ghost" onClick={onEdit}>{t('e.edit')}</button>}
          {error.suggestions.includes('later') && <span className="muted small">{t('e.later')}</span>}
        </div>
      )}
    </div>
  )
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="empty">{children}</div>
}

export function useToast(): [string | null, (s: string) => void] {
  const [text, setText] = useState<string | null>(null)
  useEffect(() => {
    if (!text) return
    const id = window.setTimeout(() => setText(null), 1800)
    return () => window.clearTimeout(id)
  }, [text])
  return [text, setText]
}

export function Toast({ text }: { text: string | null }) {
  return text ? <div className="toast" role="status">{text}</div> : null
}
