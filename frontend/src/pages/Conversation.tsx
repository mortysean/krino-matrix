import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import {
  api, ApiError, streamTurn, type Conversation, type Decision, type ErrorResponse, type Message, type Stage, type TurnInput,
} from '../api'
import { DecisionView } from '../components/DecisionView'
import { IconArrow, IconChevron } from '../components/icons'
import { Progress } from '../components/Progress'
import { QuestionCard } from '../components/QuestionCard'
import { Empty, ErrorBox, Toast, useToast } from '../components/States'
import { errorText, t } from '../i18n'

const NETWORK_ERROR = (): ErrorResponse => ({
  type: 'error', code: 'call_failed', message: t('err.network'), retryable: true, suggestions: ['retry'],
})

export function ConversationPage() {
  const { id } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const [conv, setConv] = useState<Conversation | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [stage, setStage] = useState<Stage | null>(null)
  const [running, setRunning] = useState(false)
  const [localError, setLocalError] = useState<ErrorResponse | null>(null)   // a turn that never reached the server
  const [draft, setDraft] = useState('')
  const [toast, showToast] = useToast()
  const started = useRef<string | null>(null)        // conversation id this page already started or loaded
  const composer = useRef<HTMLTextAreaElement>(null)
  const bottom = useRef<HTMLDivElement>(null)

  const load = useCallback(async (cid: string) => {
    try {
      setConv(await api.conversation(cid))
      setLoadError(null)
    } catch (e) {
      setLoadError(errorText(e instanceof ApiError && e.status === 404 ? 'not_found' : 'generic'))
    }
  }, [])

  const run = useCallback(async (body: TurnInput) => {
    setRunning(true)
    setStage('understand')
    setLocalError(null)
    let cid = body.conversation_id
    try {
      await streamTurn(body, e => {
        if (e.type === 'conversation') {
          cid = e.id
          if (!body.conversation_id) {
            started.current = e.id
            navigate(`/c/${e.id}`, { replace: true })
          }
        } else if (e.type === 'stage') {
          setStage(e.stage)
        }
      })
      if (cid) await load(cid)
    } catch {
      setLocalError(NETWORK_ERROR())
    } finally {
      setRunning(false)
      setStage(null)
    }
  }, [load, navigate])

  // A new conversation starts with the goal typed on Today; an existing one loads
  useEffect(() => {
    if (!id || started.current === id) return
    if (id === 'new') {
      const text = (location.state as { text?: string } | null)?.text
      if (!text) { navigate('/', { replace: true }); return }
      started.current = 'new'
      setConv({ id: '', title: text, created_at: '', updated_at: '', preview: '', pending_question: null,
        messages: [{ id: 'local', role: 'user', kind: 'objective', text, created_at: '' }] })
      run({ text })
      return
    }
    started.current = id
    load(id)
  }, [id, location.state, load, navigate, run])

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [conv?.messages.length, running])

  const cidNow = conv?.id || undefined
  const send = (text: string) => {
    if (!text.trim() || running) return
    setDraft('')
    setConv(c => c && { ...c, messages: [...c.messages, { id: `local-${Date.now()}`, role: 'user', kind: c.pending_question ? 'answer' : 'objective', text, created_at: '' }] })
    run({ conversation_id: cidNow, text })
  }

  const updateDecision = (d: Decision) =>
    setConv(c => c && { ...c, messages: c.messages.map(m => m.decision?.id === d.id ? { ...m, decision: d } : m) })

  const edit = () => {
    const last = [...(conv?.messages ?? [])].reverse().find(m => m.kind === 'objective')
    setDraft(last?.text ?? '')
    composer.current?.focus()
  }

  if (loadError) return <div className="page narrow"><Empty><p>{loadError}</p><Link className="btn" to="/">{t('nav.today')}</Link></Empty></div>
  if (!conv) return <div className="page narrow"><Progress stage={null} /></div>

  const messages = conv.messages
  const lastDecisionIndex = messages.map(m => m.kind).lastIndexOf('decision')

  return (
    <div className="page narrow">
      <div className="thread">
        {messages.map((m, i) => (
          <MessageView key={m.id} m={m} last={i === messages.length - 1} latestDecision={i === lastDecisionIndex}
            busy={running} pending={conv.pending_question} onToast={showToast} onDecision={updateDecision}
            onAnswer={a => run({ conversation_id: cidNow, answer: a })}
            onDecideNow={() => run({ conversation_id: cidNow, decide_now: true })}
            onRetry={() => run({ conversation_id: cidNow, retry: true })} onEdit={edit} />
        ))}
        {running && <Progress stage={stage} />}
        {localError && !running && <ErrorBox error={localError} active onRetry={() => run({ conversation_id: cidNow, retry: true })} onEdit={edit} />}
        <div ref={bottom} />
      </div>

      <div className="panel composer">
        <label htmlFor="composer" className="sr-only">{t('c.continue')}</label>
        <textarea id="composer" ref={composer} className="textarea" rows={1} value={draft} disabled={running}
          placeholder={conv.pending_question ? t('c.answerHere') : t('c.continue')}
          onChange={e => setDraft(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(draft) } }} />
        <button className="btn primary" onClick={() => send(draft)} disabled={running || !draft.trim()} aria-label={t('c.send')}>
          <IconArrow size={17} />
        </button>
      </div>
      <Toast text={toast} />
    </div>
  )
}

interface MessageProps {
  m: Message
  last: boolean
  latestDecision: boolean
  busy: boolean
  pending: Conversation['pending_question']
  onAnswer: Parameters<typeof QuestionCard>[0]['onAnswer']
  onDecideNow: () => void
  onRetry: () => void
  onEdit: () => void
  onToast: (s: string) => void
  onDecision: (d: Decision) => void
}

function MessageView({ m, last, latestDecision, busy, pending, onAnswer, onDecideNow, onRetry, onEdit, onToast, onDecision }: MessageProps) {
  if (m.kind === 'objective') return <div className="bubble-user">{m.text}</div>
  if (m.kind === 'answer') {
    const skipped = m.answer?.skipped
    return <div className={`bubble-user ${skipped ? 'skipped' : ''}`}>{skipped ? t('q.skipped') : m.text}</div>
  }
  if (m.kind === 'clarification' && m.response?.type === 'clarification') {
    if (last && pending) {
      return <QuestionCard question={m.response.question} asked={m.response.asked} max={m.response.max_questions}
        busy={busy} onAnswer={onAnswer} onDecideNow={onDecideNow} />
    }
    return <div className="bubble-note">{m.response.question.text}</div>
  }
  if (m.kind === 'error' && m.response?.type === 'error') {
    return <ErrorBox error={m.response} active={last && !busy} onRetry={onRetry} onEdit={onEdit} />
  }
  if (m.kind === 'decision' && m.decision) {
    if (latestDecision) return <DecisionView decision={m.decision} onChange={onDecision} onToast={onToast} />
    return (
      <Link to={`/d/${m.decision.id}`} className="list-item">
        <div className="grow">
          <div className="sub">{t('d.next')}</div>
          <div className="title">{m.decision.response.headline}</div>
        </div>
        <IconChevron size={16} />
      </Link>
    )
  }
  return null
}
