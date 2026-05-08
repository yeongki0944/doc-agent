import { useState, useEffect, useRef, useCallback } from 'react'
import { useDocumentStore } from '../store/documentStore'
import { initDocumentSubscription, type AppSyncMessage } from '../utils/appsync'
import {
  type HistoryMessage,
  toBoundedApiHistory,
  loadHistory,
} from '../utils/conversationHistory'
import { apiFetch } from '../auth/api'
import { getDocument } from '../utils/api'
import { onUserEdit } from '../utils/userEditEvent'
import { useSessionStore } from '../store/sessionStore'
import { color, space } from '../styles/tokens'
import { AgentResultCard, parseAgentResult, type AgentResultSummary } from './AgentResultCard'

const API_BASE = import.meta.env.VITE_API_URL || 'https://7wejbdujd6.execute-api.ap-northeast-2.amazonaws.com'
const SESSION_ID = 'default'
const BOUNDED_WINDOW = 20

interface ChatPanelProps {
  docId: string
}

/** One entry inside the live thinking timeline. */
interface ThinkingEntry {
  kind: 'step' | 'model' | 'tool' | 'reasoning' | 'token'
  agent?: string
  text: string
  status?: 'start' | 'end' | 'error'
  reasoning?: string          // accumulated reasoning (for kind='reasoning')
  tokens?: string             // accumulated response tokens (for kind='token')
  model_id?: string
  tool_name?: string
  duration_ms?: number
}

interface Message {
  id: string
  role: 'user' | 'agent'
  text: string
  thinking?: string[]         // legacy flat steps from DynamoDB history
  thinkingLive?: ThinkingEntry[]  // live entries built from AppSync events
  status?: 'thinking' | 'done'
  agentResult?: AgentResultSummary
}

function toHistoryMessage(m: Message): HistoryMessage {
  return { id: m.id, role: m.role, content: m.text, timestamp: new Date().toISOString() }
}

// ---------------------------------------------------------------------------
// ThinkingBlock — Claude-style collapsible reasoning UI
// ---------------------------------------------------------------------------

function ThinkingBlock({
  steps,
  entries,
  latestStep,
  status,
}: {
  steps?: string[]
  entries?: ThinkingEntry[]
  latestStep: string
  status?: 'thinking' | 'done'
}) {
  const [expanded, setExpanded] = useState(true)
  const bodyRef = useRef<HTMLDivElement>(null)
  const isDone = status === 'done' || latestStep.includes('✅')
  const count = entries?.length ?? steps?.length ?? 0

  // Auto-collapse once done (after 2s) so the chat stays clean.
  useEffect(() => {
    if (!isDone) return
    const t = setTimeout(() => setExpanded(false), 2000)
    return () => clearTimeout(t)
  }, [isDone])

  // Keep the body scrolled to the latest entry.
  useEffect(() => {
    if (expanded && bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight
    }
  }, [expanded, count])

  return (
    <div style={{
      marginBottom: 8,
      padding: '8px 12px',
      borderRadius: 8,
      background: color.bgPrimary,
      border: `1px solid ${color.border}`,
      maxWidth: '92%',
      fontSize: 13,
    }}>
      <div
        onClick={() => setExpanded(!expanded)}
        style={{
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          color: color.textSecondary,
        }}
      >
        <span style={{ fontSize: 10 }}>{expanded ? '▼' : '▶'}</span>
        <span style={{ fontWeight: 500 }}>
          {isDone ? '✅ Thinking 완료' : (
            <>
              <ThinkingDot /> {latestStep || 'Thinking...'}
            </>
          )}
        </span>
        <span style={{ fontSize: 11, color: color.textMuted, marginLeft: 'auto' }}>
          {count}단계
        </span>
      </div>
      {expanded && (
        <div
          ref={bodyRef}
          style={{
            marginTop: 6,
            paddingLeft: 14,
            borderLeft: `2px solid ${color.border}`,
            maxHeight: 260,
            overflow: 'auto',
          }}
        >
          {entries
            ? entries.map((e, i) => <EntryLine key={i} entry={e} />)
            : (steps || []).map((s, i) => (
              <div key={i} style={lineStyle}>{s}</div>
            ))}
        </div>
      )}
    </div>
  )
}

const lineStyle: React.CSSProperties = {
  fontSize: 12,
  color: color.textMuted,
  padding: '3px 0',
  lineHeight: 1.5,
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-word',
}

function EntryLine({ entry }: { entry: ThinkingEntry }) {
  // Render depending on kind; adds hierarchy and subtle colour.
  switch (entry.kind) {
    case 'model':
      return (
        <div style={lineStyle}>
          <span style={{ color: '#4f46e5', fontWeight: 600 }}>
            {entry.status === 'end' ? '🧠→' : '🧠'}
          </span>{' '}
          {entry.text}
          {entry.duration_ms ? (
            <span style={{ color: color.textMuted, fontSize: 11 }}> · {entry.duration_ms}ms</span>
          ) : null}
        </div>
      )
    case 'tool':
      return (
        <div style={lineStyle}>
          <span style={{
            color: entry.status === 'error' ? color.error : '#0891b2',
            fontWeight: 600,
          }}>
            {entry.status === 'end' ? '🔧←' : '🔧'}
          </span>{' '}
          {entry.text}
        </div>
      )
    case 'reasoning':
      return (
        <div style={{
          ...lineStyle,
          background: '#fffbea',
          border: '1px solid #fef3c7',
          borderRadius: 6,
          padding: '6px 8px',
          marginTop: 4,
          color: '#78350f',
          fontStyle: 'italic',
        }}>
          <div style={{ fontSize: 10, fontWeight: 700, marginBottom: 2, letterSpacing: 0.5 }}>
            REASONING
          </div>
          {entry.reasoning || entry.text}
        </div>
      )
    case 'token':
      return (
        <div style={{
          ...lineStyle,
          color: color.textSecondary,
          background: color.bgSurface,
          border: `1px solid ${color.border}`,
          borderRadius: 6,
          padding: '6px 8px',
          marginTop: 4,
        }}>
          <div style={{ fontSize: 10, fontWeight: 700, marginBottom: 2, letterSpacing: 0.5, color: color.textMuted }}>
            RESPONSE
          </div>
          {entry.tokens || entry.text}
        </div>
      )
    default:
      return <div style={lineStyle}>{entry.text}</div>
  }
}

function ThinkingDot() {
  return (
    <span
      aria-label="thinking"
      style={{
        display: 'inline-block',
        width: 8,
        height: 8,
        borderRadius: '50%',
        background: color.textMuted,
        marginRight: 6,
        animation: 'thinking-pulse 1.4s ease-in-out infinite',
      }}
    />
  )
}

// Keyframe declaration once
const STYLE_ONCE_ID = '__doc_agent_thinking_style'
if (typeof document !== 'undefined' && !document.getElementById(STYLE_ONCE_ID)) {
  const style = document.createElement('style')
  style.id = STYLE_ONCE_ID
  style.textContent = `
    @keyframes thinking-pulse {
      0%, 80%, 100% { opacity: 0.3; transform: scale(0.9); }
      40% { opacity: 1; transform: scale(1.2); }
    }
  `
  document.head.appendChild(style)
}

// ---------------------------------------------------------------------------
// ChatPanel
// ---------------------------------------------------------------------------

export function ChatPanel({ docId }: ChatPanelProps) {
  const [messages, setMessages] = useState<Message[]>([
    { id: '0', role: 'agent', text: '안녕하세요! APN PoC Project Plan 문서 생성을 도와드리겠습니다. 프로젝트에 대해 알려주세요.' },
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [historyLoaded, setHistoryLoaded] = useState(false)
  const setAgentStatus = useDocumentStore(s => s.setAgentStatus)
  const appsyncConnected = useDocumentStore(s => s.appsyncConnected)
  const scrollRef = useRef<HTMLDivElement>(null)

  // The live thinking message id for the currently-running turn.
  const activeThinkingIdRef = useRef<string | null>(null)
  const loadingRef = useRef(false)

  useEffect(() => { loadingRef.current = loading }, [loading])

  // Auto-scroll to bottom on new messages.
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages])

  // Initialize AppSync subscription — refresh signal triggers history re-fetch.
  const fetchHistory = useCallback(() => {
    loadHistory(API_BASE, docId, SESSION_ID).then(data => {
      if (data && data.messages && data.messages.length > 0) {
        setMessages(prev => {
          // Preserve any live-thinking entries built since the last fetch.
          const liveThinking = new Map<string, Message>()
          for (const m of prev) {
            if (m.thinkingLive && m.thinkingLive.length > 0) {
              liveThinking.set(m.id, m)
            }
          }
          const restored: Message[] = data.messages.map((m: any) => {
            if (m.type === 'thinking' && m.thinking_steps) {
              const live = liveThinking.get(m.id)
              return {
                id: m.id,
                role: m.role as 'user' | 'agent',
                text: m.content,
                thinking: m.thinking_steps,
                thinkingLive: live?.thinkingLive,
                status: live?.status,
              }
            }
            return { id: m.id, role: m.role as 'user' | 'agent', text: m.content }
          })
          return restored
        })
      }
      getDocument(docId).then(doc => {
        if (doc) {
          useDocumentStore.getState().setDocument(doc)
          const status = (doc as any).agent_status || 'idle'
          setAgentStatus(status as any)
          if (status === 'idle') setLoading(false)
        }
      }).catch(() => {})
    }).catch(() => {})
  }, [docId, setAgentStatus])

  // --- AppSync live events ---
  const handleLiveEvent = useCallback((msg: AppSyncMessage) => {
    const type = (msg as any).type as string

    // Helpers to append entries to the active thinking message.
    const ensureThinking = (): string => {
      let id = activeThinkingIdRef.current
      if (id) return id
      id = `thinking-live-${Date.now()}`
      activeThinkingIdRef.current = id
      setMessages(prev => [
        ...prev,
        { id, role: 'agent', text: '시작…', thinkingLive: [], status: 'thinking' },
      ])
      return id
    }

    const appendEntry = (entry: ThinkingEntry) => {
      const id = ensureThinking()
      setMessages(prev => prev.map(m => {
        if (m.id !== id) return m
        const existing = m.thinkingLive || []
        let merged = existing
        // Coalesce consecutive reasoning/token deltas from the same agent.
        const last = existing[existing.length - 1]
        if (
          last &&
          (entry.kind === 'reasoning' || entry.kind === 'token') &&
          last.kind === entry.kind &&
          last.agent === entry.agent
        ) {
          merged = [...existing.slice(0, -1), {
            ...last,
            reasoning: entry.kind === 'reasoning' ? (last.reasoning || '') + (entry.reasoning || '') : last.reasoning,
            tokens: entry.kind === 'token' ? (last.tokens || '') + (entry.tokens || '') : last.tokens,
            text: entry.text || last.text,
          }]
        } else {
          merged = [...existing, entry]
        }
        return {
          ...m,
          thinkingLive: merged,
          text: entry.text || m.text,
        }
      }))
    }

    const finishThinking = () => {
      const id = activeThinkingIdRef.current
      if (!id) return
      setMessages(prev => prev.map(m => m.id === id ? { ...m, status: 'done' } : m))
      activeThinkingIdRef.current = null
    }

    switch (type) {
      case 'progress': {
        const m = msg as any
        const step: string = m.step || m.message || ''
        const agent: string = m.agent || ''
        const message: string = m.message || step || ''
        if (!message && !step) return
        // 'complete' step or explicit 'done' finishes the timeline.
        if (step === 'complete' || /✅ 완료/.test(message) || /작업 완료/.test(message)) {
          appendEntry({ kind: 'step', agent, text: message, status: 'end' })
          finishThinking()
          // Also trigger history re-fetch to load the final agent reply
          fetchHistory()
          return
        }
        appendEntry({ kind: 'step', agent, text: message })
        return
      }
      case 'model_call_start': {
        const m = msg as any
        appendEntry({
          kind: 'model',
          agent: m.agent,
          model_id: m.model_id,
          text: `${m.agent || 'model'} — 모델 호출 시작${m.model_id ? ` (${shortModelId(m.model_id)})` : ''}`,
          status: 'start',
        })
        return
      }
      case 'model_call_end': {
        const m = msg as any
        appendEntry({
          kind: 'model',
          agent: m.agent,
          model_id: m.model_id,
          duration_ms: m.duration_ms,
          text: `${m.agent || 'model'} — 모델 응답 완료`,
          status: 'end',
        })
        return
      }
      case 'tool_call_start': {
        const m = msg as any
        appendEntry({
          kind: 'tool',
          agent: m.agent,
          tool_name: m.tool_name,
          text: `${m.agent || 'agent'} → '${m.tool_name}' 도구 호출${m.tool_input_preview ? ` · ${m.tool_input_preview}` : ''}`,
          status: 'start',
        })
        return
      }
      case 'tool_call_end': {
        const m = msg as any
        appendEntry({
          kind: 'tool',
          agent: m.agent,
          tool_name: m.tool_name,
          text: m.success
            ? `${m.agent || 'agent'} ← '${m.tool_name}' 완료${m.tool_output_preview ? ` · ${m.tool_output_preview}` : ''}`
            : `${m.agent || 'agent'} ← '${m.tool_name}' 실패${m.error ? ` · ${m.error}` : ''}`,
          status: m.success ? 'end' : 'error',
        })
        return
      }
      case 'reasoning_delta': {
        const m = msg as any
        appendEntry({
          kind: 'reasoning',
          agent: m.agent,
          text: '',
          reasoning: m.delta || '',
        })
        return
      }
      case 'token_delta': {
        const m = msg as any
        appendEntry({
          kind: 'token',
          agent: m.agent,
          text: '',
          tokens: m.delta || '',
        })
        return
      }
      case 'status': {
        const s = (msg as any).status as string
        if (s === 'idle') setLoading(false)
        return
      }
      case 'refresh':
      case 'chat_done': {
        finishThinking()
        fetchHistory()
        return
      }
    }
  }, [fetchHistory])

  useEffect(() => {
    const unsubscribe = initDocumentSubscription(docId, handleLiveEvent)
    return unsubscribe
  }, [docId, handleLiveEvent])

  // Polling fallback when WebSocket is not connected — keeps thinking visible
  // even if AppSync is unreachable.
  useEffect(() => {
    if (appsyncConnected) return
    if (!loadingRef.current) return
    const iv = setInterval(() => {
      if (loadingRef.current) fetchHistory()
    }, 3000)
    return () => clearInterval(iv)
  }, [appsyncConnected, fetchHistory])

  // Reset state when docId changes
  useEffect(() => {
    setMessages([
      { id: '0', role: 'agent', text: '안녕하세요! APN PoC Project Plan 문서 생성을 도와드리겠습니다. 프로젝트에 대해 알려주세요.' },
    ])
    setHistoryLoaded(false)
    setLoading(false)
    activeThinkingIdRef.current = null
  }, [docId])

  // Listen for user direct edits on document fields → inject as user message for LLM context
  useEffect(() => {
    return onUserEdit((section, field, oldValue, newValue) => {
      const editMsg: Message = {
        id: `edit-${Date.now()}`,
        role: 'user',
        text: `[직접 수정] ${section} > ${field}: "${oldValue}" → "${newValue}"`,
      }
      setMessages(prev => [...prev, editMsg])
    })
  }, [])

  // Listen for suggestion prompts pushed from ReviewDrawer's SectionSuggestions tab
  useEffect(() => {
    const handler = (ev: Event) => {
      const ce = ev as CustomEvent<{ prompt: string }>
      const prompt = ce.detail?.prompt
      if (typeof prompt === 'string' && prompt.trim()) {
        setInput(prev => (prev ? `${prev}\n${prompt}` : prompt))
      }
    }
    window.addEventListener('doc-agent:chat-prompt', handler as EventListener)
    return () => window.removeEventListener('doc-agent:chat-prompt', handler as EventListener)
  }, [])

  // Load history from server on mount (document reopen)
  useEffect(() => {
    if (historyLoaded) return
    let cancelled = false

    loadHistory(API_BASE, docId, SESSION_ID).then(data => {
      if (cancelled) return
      if (data && data.messages && data.messages.length > 0) {
        const restored: Message[] = data.messages.map((m: any) => {
          if (m.type === 'thinking' && m.thinking_steps) {
            return {
              id: m.id,
              role: m.role as 'user' | 'agent',
              text: m.content,
              thinking: m.thinking_steps,
            }
          }
          return {
            id: m.id,
            role: m.role as 'user' | 'agent',
            text: m.content,
          }
        })
        setMessages(restored)
      }
      setHistoryLoaded(true)
    })

    return () => { cancelled = true }
  }, [historyLoaded, docId])

  const handleSend = async () => {
    const text = input.trim()
    if (!text || loading) return

    const userMsg: Message = { id: Date.now().toString(), role: 'user', text }
    const updatedMessages = [...messages, userMsg]
    setMessages(updatedMessages)
    setInput('')
    setLoading(true)
    setAgentStatus('processing')
    activeThinkingIdRef.current = null  // new turn

    try {
      const historyMsgs = updatedMessages
        .filter(m => m.id !== '0')
        .map(toHistoryMessage)
      const boundedHistory = toBoundedApiHistory(historyMsgs, BOUNDED_WINDOW)

      const res = await apiFetch(`/documents/${docId}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, history: boundedHistory }),
      })

      if (res.status === 202) {
        setTimeout(() => {
          if (loadingRef.current) {
            setMessages(prev => [...prev, {
              id: (Date.now() + 1).toString(),
              role: 'agent',
              text: '응답 대기 시간이 초과되었습니다. 다시 시도해주세요.',
            }])
            setAgentStatus('error')
            setLoading(false)
          }
        }, 90000)
        return
      }

      const data = await res.json()
      const agentResultSummary = parseAgentResult(data)
      const agentMsg: Message = {
        id: (Date.now() + 1).toString(),
        role: 'agent',
        text: data.agent_response || (agentResultSummary ? '' : '처리 완료'),
        agentResult: agentResultSummary ?? undefined,
      }
      const finalMessages = [...updatedMessages, agentMsg]
      setMessages(finalMessages)

      if (data.document) {
        useDocumentStore.getState().setDocument(data.document)
      }
      useSessionStore.getState().fetchDocuments()
      setAgentStatus('idle')
    } catch {
      const errorMsg: Message = {
        id: (Date.now() + 1).toString(),
        role: 'agent',
        text: 'API 연결 오류가 발생했습니다.',
      }
      setMessages(prev => [...prev, errorMsg])
      setAgentStatus('error')
    } finally {
      if (!loadingRef.current) return
      setLoading(false)
    }
  }

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      minHeight: 0,
      flex: 1,
    }}>
      <div
        ref={scrollRef}
        style={{
          flex: 1,
          minHeight: 0,
          overflow: 'auto',
          overscrollBehavior: 'contain',
          padding: 12,
        }}
      >
        {messages.map(m => (
          (m.thinkingLive && m.thinkingLive.length > 0) || m.thinking ? (
            <ThinkingBlock
              key={m.id}
              entries={m.thinkingLive}
              steps={m.thinking}
              latestStep={m.text}
              status={m.status}
            />
          ) : (
            <div key={m.id} style={{ marginBottom: 8 }}>
              <div style={{
                padding: '8px 12px', borderRadius: 8,
                background: m.role === 'user' ? color.bgSubtle : color.bgSurface,
                border: m.role === 'agent' ? `1px solid ${color.border}` : undefined,
                maxWidth: '85%', marginLeft: m.role === 'user' ? 'auto' : 0,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
              }}>
                <div style={{ fontSize: 11, color: color.textMuted, marginBottom: 2 }}>
                  {m.role === 'user' ? '나' : 'Agent'}
                </div>
                {m.text || (m.agentResult ? null : '—')}
              </div>
              {m.agentResult && (
                <div style={{ marginTop: 4, marginLeft: m.role === 'user' ? 'auto' : 0 }}>
                  <AgentResultCard result={m.agentResult} />
                </div>
              )}
            </div>
          )
        ))}
        {loading && !messages.some(m => m.status === 'thinking') && (
          <div style={{ padding: '8px 12px', color: color.textMuted, fontSize: 13 }}>
            <ThinkingDot /> 분석 중...
          </div>
        )}
      </div>
      <div style={{
        display: 'flex',
        padding: 8,
        borderTop: `1px solid ${color.border}`,
        gap: 8,
        flexShrink: 0,
      }}>
        <input
          style={{
            flex: 1,
            padding: '8px 12px',
            border: `1px solid ${color.border}`,
            borderRadius: 6,
            fontSize: 14,
          }}
          placeholder="프로젝트 정보를 입력하세요..."
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSend()}
          disabled={loading}
        />
        <button
          onClick={handleSend}
          disabled={loading}
          style={{
            padding: '8px 16px',
            background: loading ? '#F09090' : color.mzRed,
            color: color.bgSurface,
            border: 'none',
            borderRadius: 6,
            cursor: loading ? 'wait' : 'pointer',
          }}
        >
          전송
        </button>
      </div>
    </div>
  )
}

function shortModelId(id: string): string {
  // Trim inference-profile prefix and version for compact display.
  const last = id.split('.').slice(-2).join('.')
  return last.replace(/-v\d+:\d+$/, '').replace(/-\d{8}/, '')
}
