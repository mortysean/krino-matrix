// Types mirror decision_core/types.py: every turn ends in a clarification, a decision or an error.

export type Stage = 'understand' | 'clarify' | 'compare'

export interface Constraint { id: string; text: string; hard: boolean }

export interface ProblemView {
  state: Record<string, unknown>
  objective: string
  constraints: Constraint[]
}

export interface Question {
  id: string
  text: string
  kind: 'single' | 'multi' | 'text'
  options: string[]
  allow_other: boolean
  required: boolean
  why: string
}

export interface ClarificationResponse {
  type: 'clarification'
  question: Question
  problem: ProblemView
  asked: number
  max_questions: number | null
}

export interface ActionCard {
  id: string
  title: string
  description: string
  why: string
  difference: string
  risks: string[]
  say?: string        // one line Krino says when handing over this action, in her personality
  excluded_by: string[]
  requires_confirmation: boolean
}

export interface EvaluatorInfo {
  name: string
  version: string
  experimental: boolean
  score_meaning: string
}

export interface DecisionResponse {
  type: 'decision'
  headline: string
  explanation: string
  best_action: string | null
  actions: ActionCard[]
  action_scores: Record<string, number> | null
  confidence: number | null
  warnings: string[]
  problem: ProblemView
  evidence: string[]
  evaluator: EvaluatorInfo
  model_version: string
  core_version: string
}

export type ErrorCode = 'model_unavailable' | 'call_failed' | 'quota_exceeded' | 'invalid_input' | 'no_actions'

export interface ErrorResponse {
  type: 'error'
  code: ErrorCode
  message: string
  retryable: boolean
  suggestions: ('retry' | 'edit' | 'later')[]
}

export type CoreResponse = ClarificationResponse | DecisionResponse | ErrorResponse

export interface Answer {
  question_id: string
  question?: string
  values: string[]
  text: string
  skipped: boolean
}

export interface Feedback {
  chosen_action: string | null
  chose_recommended: boolean | null
  reason: string
  status: 'chosen' | 'later' | 'unsuitable' | 'done' | null
  executed: 'yes' | 'no' | null
  helpful: 'yes' | 'partly' | 'no' | null
  outcome: string
  updated_at: string
}

export interface Decision {
  id: string
  conversation_id: string
  created_at: string
  objective_input: string
  answers: Answer[]
  model_version: string
  response: DecisionResponse
  feedback: Feedback | null
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  kind: 'objective' | 'answer' | 'clarification' | 'decision' | 'error'
  text: string
  created_at: string
  decision?: Decision
  response?: ClarificationResponse | ErrorResponse
  answer?: Answer
}

export interface ConversationSummary {
  id: string
  title: string
  created_at: string
  updated_at: string
  preview: string
}

export interface Conversation extends ConversationSummary {
  messages: Message[]
  pending_question: Question | null
}

export interface User { id: string; email: string; created_at: string }

export interface Memory { id: string; text: string; source_decision_id: string | null; updated_at: string }

export type Tone = 'pilot' | 'chat' | 'detailed'
export type Persona = 'calm' | 'genki' | 'gentle' | 'tsundere'
export type Pace = 'direct' | 'balanced' | 'thorough'
export interface Style { tone: Tone; persona: Persona; pace: Pace }

export interface Status {
  model: { configured: boolean; name: string | null }
  evaluator: { experimental: boolean }
  usage: {
    turns_today: number; daily_quota: number; calls: number; failed_calls: number
    avg_latency_ms: number | null; input_tokens: number; output_tokens: number
  }
  billing: { live: boolean }
}

export class ApiError extends Error {
  status: number
  constructor(status: number, code: string) {
    super(code)
    this.status = status
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, {
      method,
      credentials: 'same-origin',
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, 'network')
  }
  if (!res.ok) {
    let code = 'error'
    try { code = (await res.json()).detail ?? code } catch { /* not JSON */ }
    if (res.status === 401) window.dispatchEvent(new Event('krino:unauthorized'))
    throw new ApiError(res.status, typeof code === 'string' ? code : 'invalid')
  }
  return res.json() as Promise<T>
}

export const api = {
  me: () => request<User>('GET', '/api/auth/me'),
  login: (email: string, password: string) => request<User>('POST', '/api/auth/login', { email, password }),
  register: (email: string, password: string) => request<User>('POST', '/api/auth/register', { email, password }),
  logout: () => request('POST', '/api/auth/logout'),
  resetRequest: (email: string) => request('POST', '/api/auth/reset/request', { email }),
  resetConfirm: (token: string, password: string) => request<User>('POST', '/api/auth/reset/confirm', { token, password }),

  conversations: (q = '') => request<ConversationSummary[]>('GET', `/api/conversations?q=${encodeURIComponent(q)}`),
  conversation: (id: string) => request<Conversation>('GET', `/api/conversations/${id}`),
  deleteConversation: (id: string) => request('DELETE', `/api/conversations/${id}`),

  decisions: (limit = 5) => request<Decision[]>('GET', `/api/decisions?limit=${limit}`),
  decision: (id: string) => request<Decision>('GET', `/api/decisions/${id}`),
  feedback: (id: string, body: Partial<Feedback>) => request<Decision>('PUT', `/api/decisions/${id}/feedback`, body),

  memories: () => request<Memory[]>('GET', '/api/memories'),
  addMemory: (text: string, source_decision_id?: string) => request<Memory>('POST', '/api/memories', { text, source_decision_id }),
  editMemory: (id: string, text: string) => request<Memory>('PATCH', `/api/memories/${id}`, { text }),
  deleteMemory: (id: string) => request('DELETE', `/api/memories/${id}`),

  status: () => request<Status>('GET', '/api/account/status'),
  style: () => request<Style>('GET', '/api/account/style'),
  setStyle: (style: Style) => request<Style>('PUT', '/api/account/style', style),
  changePassword: (current: string, next: string) => request('POST', '/api/account/password', { current, new: next }),
  deleteHistory: () => request('DELETE', '/api/account/history'),
  deleteAccount: (password: string) => request('DELETE', '/api/account', { password }),
}

export interface TurnInput {
  conversation_id?: string
  text?: string
  answer?: Omit<Answer, 'question'>
  retry?: boolean
  decide_now?: boolean
}

export type TurnEvent =
  | { type: 'conversation'; id: string; title: string }
  | { type: 'stage'; stage: Stage }
  | (CoreResponse & { message_id?: string; decision_id?: string })

/** Run one turn; events arrive as the core works. Resolves with the final response. */
export async function streamTurn(body: TurnInput, onEvent: (e: TurnEvent) => void): Promise<void> {
  let res: Response
  try {
    res = await fetch('/api/turns', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, 'network')
  }
  if (!res.ok || !res.body) {
    if (res.status === 401) window.dispatchEvent(new Event('krino:unauthorized'))
    throw new ApiError(res.status, 'turn_failed')
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (value) buffer += decoder.decode(value, { stream: true })
    let nl: number
    while ((nl = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, nl).trim()
      buffer = buffer.slice(nl + 1)
      if (line) onEvent(JSON.parse(line) as TurnEvent)
    }
    if (done) break
  }
  if (buffer.trim()) onEvent(JSON.parse(buffer) as TurnEvent)
}
