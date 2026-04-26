/**
 * Conversation history management with bounded window + localStorage cache.
 *
 * Canonical store: server (POST/GET /documents/{docId}/history)
 * Client cache: localStorage (fast restore on document reopen)
 * API calls include only the most recent N messages (bounded window).
 */

const DEFAULT_BOUNDED_WINDOW = 20

export interface HistoryMessage {
  id: string
  role: 'user' | 'agent'
  content: string
  timestamp: string
}

export interface ConversationHistory {
  document_id: string
  session_id: string
  messages: HistoryMessage[]
  bounded_window: number
  total_count: number
}

// ---------------------------------------------------------------------------
// localStorage cache helpers
// ---------------------------------------------------------------------------

function cacheKey(docId: string): string {
  return `doc-agent-history-${docId}`
}

export function getCachedHistory(docId: string): ConversationHistory | null {
  try {
    const raw = localStorage.getItem(cacheKey(docId))
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export function setCachedHistory(docId: string, history: ConversationHistory): void {
  try {
    localStorage.setItem(cacheKey(docId), JSON.stringify(history))
  } catch {
    // localStorage full or unavailable — ignore
  }
}

export function clearCachedHistory(docId: string): void {
  try {
    localStorage.removeItem(cacheKey(docId))
  } catch {
    // ignore
  }
}

// ---------------------------------------------------------------------------
// Bounded window helpers
// ---------------------------------------------------------------------------

/**
 * Return only the most recent `boundedWindow` messages for API calls.
 */
export function getBoundedMessages(
  messages: HistoryMessage[],
  boundedWindow: number = DEFAULT_BOUNDED_WINDOW,
): HistoryMessage[] {
  return messages.slice(-boundedWindow)
}

/**
 * Convert bounded messages to the format expected by the chat API
 * (role: user/assistant, content: string).
 */
export function toBoundedApiHistory(
  messages: HistoryMessage[],
  boundedWindow: number = DEFAULT_BOUNDED_WINDOW,
): Array<{ role: string; content: string }> {
  return getBoundedMessages(messages, boundedWindow).map(m => ({
    role: m.role === 'user' ? 'user' : 'assistant',
    content: m.content,
  }))
}

// ---------------------------------------------------------------------------
// Server API calls
// ---------------------------------------------------------------------------

import { apiFetch } from '../auth/api'

export async function saveHistoryToServer(
  _apiBase: string,
  docId: string,
  sessionId: string,
  messages: HistoryMessage[],
  boundedWindow: number = DEFAULT_BOUNDED_WINDOW,
): Promise<void> {
  try {
    await apiFetch(`/documents/${docId}/history`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: sessionId,
        messages,
        bounded_window: boundedWindow,
      }),
    })
    // Also update localStorage cache
    setCachedHistory(docId, {
      document_id: docId,
      session_id: sessionId,
      messages,
      bounded_window: boundedWindow,
      total_count: messages.length,
    })
  } catch {
    // Server save failed — localStorage cache still available
  }
}

export async function loadHistoryFromServer(
  _apiBase: string,
  docId: string,
  sessionId?: string,
): Promise<ConversationHistory | null> {
  try {
    const qs = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ''
    const res = await apiFetch(`/documents/${docId}/history${qs}`)
    if (!res.ok) return null
    const data: ConversationHistory = await res.json()
    // Update localStorage cache with server data
    if (data && data.messages && data.messages.length > 0) {
      setCachedHistory(docId, data)
    }
    return data
  } catch {
    // Server unavailable — fall back to localStorage cache
    return getCachedHistory(docId)
  }
}

/**
 * Load history: try server first, fall back to localStorage cache.
 */
export async function loadHistory(
  apiBase: string,
  docId: string,
  sessionId?: string,
): Promise<ConversationHistory | null> {
  const serverData = await loadHistoryFromServer(apiBase, docId, sessionId)
  if (serverData && serverData.messages && serverData.messages.length > 0) {
    return serverData
  }
  // Fall back to cache
  return getCachedHistory(docId)
}
