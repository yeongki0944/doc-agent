import { useState, useEffect, useRef } from 'react'
import { useDocumentStore } from '../store/documentStore'
import { StatusBar } from './StatusBar'
import { initDocumentSubscription, type AppSyncMessage } from '../utils/appsync'
import {
  type HistoryMessage,
  toBoundedApiHistory,
  saveHistoryToServer,
  loadHistory,
} from '../utils/conversationHistory'
import { apiFetch } from '../auth/api'
import { onUserEdit } from '../utils/userEditEvent'
import { useSessionStore } from '../store/sessionStore'

const API_BASE = import.meta.env.VITE_API_URL || 'https://7wejbdujd6.execute-api.ap-northeast-2.amazonaws.com'
const SESSION_ID = 'default'
const BOUNDED_WINDOW = 20

interface ChatPanelProps {
  docId: string
}

interface Message {
  id: string
  role: 'user' | 'agent'
  text: string
}

function toHistoryMessage(m: Message): HistoryMessage {
  return { id: m.id, role: m.role, content: m.text, timestamp: new Date().toISOString() }
}

export function ChatPanel({ docId }: ChatPanelProps) {
  const [messages, setMessages] = useState<Message[]>([
    { id: '0', role: 'agent', text: '안녕하세요! APN PoC Project Plan 문서 생성을 도와드리겠습니다. 프로젝트에 대해 알려주세요.' },
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [historyLoaded, setHistoryLoaded] = useState(false)
  const setAgentStatus = useDocumentStore(s => s.setAgentStatus)
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const streamMsgIdRef = useRef<string | null>(null)

  // Initialize AppSync subscription on mount
  useEffect(() => {
    const unsubscribe = initDocumentSubscription(docId, (msg: AppSyncMessage) => {
      if (msg.type === 'status') {
        setAgentStatus(msg.status as any)
        return
      }

      if (msg.type === 'chat_chunk') {
        // Append text to the current streaming message
        setMessages(prev => {
          const streamId = streamMsgIdRef.current
          if (!streamId) {
            // Create new streaming message
            const newId = `stream-${Date.now()}`
            streamMsgIdRef.current = newId
            return [...prev, { id: newId, role: 'agent', text: msg.text }]
          }
          // Append to existing streaming message
          return prev.map(m =>
            m.id === streamId ? { ...m, text: m.text + msg.text } : m
          )
        })
      }

      if (msg.type === 'chat_done') {
        streamMsgIdRef.current = null
        setLoading(false)
        setAgentStatus('idle')
        // Apply document state
        if (msg.document) {
          useDocumentStore.getState().setDocument(msg.document)
        }
      }
    })
    return unsubscribe
  }, [docId, setAgentStatus])

  // Reset state when docId changes
  useEffect(() => {
    setMessages([
      { id: '0', role: 'agent', text: '안녕하세요! APN PoC Project Plan 문서 생성을 도와드리겠습니다. 프로젝트에 대해 알려주세요.' },
    ])
    setHistoryLoaded(false)
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

  // Load history from server on mount (document reopen)
  useEffect(() => {
    if (historyLoaded) return
    let cancelled = false

    loadHistory(API_BASE, docId, SESSION_ID).then(data => {
      if (cancelled) return
      if (data && data.messages && data.messages.length > 0) {
        const restored: Message[] = data.messages.map(m => ({
          id: m.id,
          role: m.role,
          text: m.content,
        }))
        setMessages(restored)
      }
      setHistoryLoaded(true)
    })

    return () => { cancelled = true }
  }, [historyLoaded, docId])

  // Debounced save to server after messages change
  const scheduleSave = (msgs: Message[]) => {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
    saveTimerRef.current = setTimeout(() => {
      const historyMsgs = msgs
        .filter(m => m.id !== '0')
        .map(toHistoryMessage)
      saveHistoryToServer(API_BASE, docId, SESSION_ID, historyMsgs, BOUNDED_WINDOW)
    }, 1000)
  }

  const handleSend = async () => {
    const text = input.trim()
    if (!text || loading) return

    const userMsg: Message = { id: Date.now().toString(), role: 'user', text }
    const updatedMessages = [...messages, userMsg]
    setMessages(updatedMessages)
    setInput('')
    setLoading(true)
    setAgentStatus('processing')

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
      const data = await res.json()

      // Always use HTTP response to show agent message
      const agentMsg: Message = {
        id: (Date.now() + 1).toString(),
        role: 'agent',
        text: data.agent_response || '처리 완료',
      }
      const finalMessages = [...updatedMessages, agentMsg]
      setMessages(finalMessages)

      if (data.document) {
        useDocumentStore.getState().setDocument(data.document)
      }

      // Refresh sidebar document list (title may have changed)
      useSessionStore.getState().fetchDocuments()

      scheduleSave(finalMessages)
      setAgentStatus('idle')
    } catch {
      const errorMsg: Message = { id: (Date.now() + 1).toString(), role: 'agent', text: 'API 연결 오류가 발생했습니다.' }
      const finalMessages = [...updatedMessages, errorMsg]
      setMessages(finalMessages)
      scheduleSave(finalMessages)
      setAgentStatus('error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <StatusBar />
      <div style={{ flex: 1, overflow: 'auto', padding: 12 }}>
        {messages.map(m => (
          <div key={m.id} style={{
            marginBottom: 8, padding: '8px 12px', borderRadius: 8,
            background: m.role === 'user' ? '#e0f2fe' : '#f3f4f6',
            maxWidth: '85%', marginLeft: m.role === 'user' ? 'auto' : 0,
          }}>
            <div style={{ fontSize: 11, color: '#999', marginBottom: 2 }}>
              {m.role === 'user' ? '나' : 'Agent'}
            </div>
            {m.text}
          </div>
        ))}
        {loading && (
          <div style={{ padding: '8px 12px', color: '#999', fontSize: 13 }}>
            분석 중...
          </div>
        )}
      </div>
      <div style={{ display: 'flex', padding: 8, borderTop: '1px solid #eee', gap: 8 }}>
        <input
          style={{ flex: 1, padding: '8px 12px', border: '1px solid #ddd', borderRadius: 6, fontSize: 14 }}
          placeholder="프로젝트 정보를 입력하세요..."
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSend()}
          disabled={loading}
        />
        <button
          onClick={handleSend}
          disabled={loading}
          style={{ padding: '8px 16px', background: loading ? '#93c5fd' : '#3b82f6', color: '#fff', border: 'none', borderRadius: 6, cursor: loading ? 'wait' : 'pointer' }}
        >
          전송
        </button>
      </div>
    </div>
  )
}
