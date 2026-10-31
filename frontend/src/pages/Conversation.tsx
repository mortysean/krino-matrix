import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import {
  api, ApiError, streamTurn, type Conversation, type Decision, type ErrorResponse, type Message, type Stage, type TurnInput,
} from '../api'
import { DecisionView } from '../components/DecisionView'
import { GoalInput } from '../components/GoalInput'
import { Progress } from '../components/Progress'
import { QuestionCard } from '../components/QuestionCard'
import { Empty, ErrorBox, Toast, useToast } from '../components/States'
import { errorText, t } from '../i18n'

const NETWORK_ERROR = (): ErrorResponse => ({
  type: 'error', code: 'call_failed', message: t('err.network'), retryable: true, suggestions: ['retry'],
})

// the prefix of a follow-up sent by the buttons under a decision; the older wording stays so past chats still show their question
const REPLAN_PREFIXES = ['还是关于：', 'Still about:', '目的地仍然是：', 'Destination unchanged:']

function shownDestination(messages: Message[], title: string) {
  const goals = messages.filter(m => m.kind === 'objective').map(m => m.text)
  for (let i = goals.length - 1; i >= 0; i--) {
    if (!REPLAN_PREFIXES.some(prefix => goals[i].startsWith(prefix))) return goals[i]
  }
  return title
}

export function ConversationPage() {
  const { id } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const [conv, setConv] = useState<Conversation | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [stage, setStage] = useState<Stage | null>(null)
  const [running, setRunning] = useState(false)
  const [localError, setLocalError] = useState<ErrorResponse | null>(null)
  const [retarget, setRetarget] = useState(false)
  const [toast, showToast] = useToast()
  const started = useRef<string | null>(null)

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

  const updateDecision = (d: Decision) =>
    setConv(c => c && { ...c, messages: c.messages.map(m => m.decision?.id === d.id ? { ...m, decision: d } : m) })

  if (loadError) return <div className="page narrow"><Empty><p>{loadError}</p><Link className="btn" to="/">{t('nav.today')}</Link></Empty></div>
  if (!conv) return <div className="page narrow"><Progress stage={null} /></div>

  const destination = shownDestination(conv.messages, conv.title)
  const cidNow = conv.id || undefined
  const replan = (note: string) => {
    if (running || !cidNow) return
    setRetarget(false)
    run({ conversation_id: cidNow, text: t('c.replan', { goal: destination, note }) })
  }
  const changeGoal = (text: string) => {
    setRetarget(false)
    run({ conversation_id: cidNow, text })
  }

  const messages = conv.messages
  const latest = [...messages].reverse().find(m => m.kind === 'decision' && m.decision)
  const last = messages[messages.length - 1]
  const pendingQuestion = !running && last?.kind === 'clarification' && last.response?.type === 'clarification' && conv.pending_question
    ? last.response : null
  const lastError = !running && last?.kind === 'error' && last.response?.type === 'error' ? last.response : null

  return (
    <div className="page narrow trip">
      <header className="trip-head">
        <span className="kicker">// {t('c.destination')}</span>
        <p className="trip-dest">{destination}</p>
        <button className="link-btn" disabled={running} onClick={() => setRetarget(v => !v)}>{t('c.changeGoal')}</button>
        {retarget && <GoalInput initial={destination} onSubmit={changeGoal} busy={running} autoFocus />}
      </header>

      {running && <Progress stage={stage} />}
      {pendingQuestion && (
        <QuestionCard question={pendingQuestion.question} busy={running}
          onAnswer={a => run({ conversation_id: cidNow, answer: a })}
          onDecideNow={() => run({ conversation_id: cidNow, decide_now: true })} />
      )}
      {!running && !pendingQuestion && !lastError && !localError && latest?.decision && (
        <DecisionView decision={latest.decision} onChange={updateDecision} onToast={showToast}
          onAskNow={() => replan(t('c.noteNow'))}
          onDetour={() => replan(t('c.noteDetour'))}
          onRest={() => replan(t('c.noteRest'))} />
      )}
      {(lastError || localError) && (
        <ErrorBox error={(localError ?? lastError)!} active
          onRetry={() => run({ conversation_id: cidNow, retry: true })}
          onEdit={() => setRetarget(true)} />
      )}
      <Toast text={toast} />
    </div>
  )
}

