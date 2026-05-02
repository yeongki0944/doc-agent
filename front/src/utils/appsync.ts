/**
 * AppSync Events API — Singleton WebSocket client with dynamic subscriptions.
 *
 * One WebSocket connection for the entire app lifetime.
 * Document switches only send unsubscribe/subscribe messages (no reconnect).
 * Auto-reconnect with exponential backoff restores all active subscriptions.
 */

import { useDocumentStore, type AgentStatus, type PatchOperation } from '../store/documentStore'

// ---------------------------------------------------------------------------
// Message types
// ---------------------------------------------------------------------------

export interface ChatChunkMessage { type: 'chat_chunk'; text: string }
export interface ChatDoneMessage { type: 'chat_done'; text?: string; actions?: string[]; document?: any; status?: string }
export interface StatusMessage { type: 'status'; status: AgentStatus; message?: string }
export interface PatchMessage { type: 'patch'; operations: PatchOperation[] }
export type ChatMessage = ChatChunkMessage | ChatDoneMessage
export type AppSyncMessage = ChatMessage | StatusMessage | PatchMessage

type MessageHandler = (msg: AppSyncMessage) => void
type Unsubscribe = () => void

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const APPSYNC_HTTP_URL = (import.meta.env.VITE_APPSYNC_HTTP_URL as string) || ''
const APPSYNC_WS_URL = (import.meta.env.VITE_APPSYNC_WS_URL as string) || ''
const APPSYNC_API_KEY = (import.meta.env.VITE_APPSYNC_API_KEY as string) || ''

const HTTP_HOST = APPSYNC_HTTP_URL ? new URL(APPSYNC_HTTP_URL).host : ''

function base64url(obj: object): string {
  return btoa(JSON.stringify(obj)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

// ---------------------------------------------------------------------------
// Singleton WebSocket Manager
// ---------------------------------------------------------------------------

interface Subscription {
  channel: string
  handler: MessageHandler
}

class AppSyncClient {
  private ws: WebSocket | null = null
  private connected = false
  private intentionallyClosed = false
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private reconnectDelay = 1000
  private subscriptions = new Map<string, Subscription>() // subId → {channel, handler}
  private pendingSubscribes: string[] = [] // subIds to subscribe after connection_ack

  connect(): void {
    if (!APPSYNC_WS_URL || !APPSYNC_API_KEY || this.ws) return
    this.intentionallyClosed = false
    this._doConnect()
  }

  private _doConnect(): void {
    try {
      const authHeader = base64url({ host: HTTP_HOST, 'x-api-key': APPSYNC_API_KEY })
      let wsUrl = APPSYNC_WS_URL
      if (!wsUrl.endsWith('/event/realtime')) {
        wsUrl = wsUrl.replace(/\/$/, '') + '/event/realtime'
      }

      this.ws = new WebSocket(wsUrl, [`header-${authHeader}`, 'aws-appsync-event-ws'])

      this.ws.onopen = () => {
        this.reconnectDelay = 1000 // reset backoff
        this.ws?.send(JSON.stringify({ type: 'connection_init' }))
      }

      this.ws.onmessage = (evt) => {
        try {
          const data = JSON.parse(evt.data)
          this._handleMessage(data)
        } catch { /* ignore */ }
      }

      this.ws.onclose = () => {
        this.ws = null
        this._setConnected(false)
        if (!this.intentionallyClosed) {
          // Exponential backoff reconnect
          this.reconnectTimer = setTimeout(() => {
            this.reconnectDelay = Math.min(this.reconnectDelay * 1.5, 10000)
            this._doConnect()
          }, this.reconnectDelay)
        }
      }

      this.ws.onerror = () => { this.ws?.close() }
    } catch {
      if (!this.intentionallyClosed) {
        setTimeout(() => this._doConnect(), this.reconnectDelay)
      }
    }
  }

  private _handleMessage(data: any): void {
    if (data.type === 'connection_ack') {
      this._setConnected(true)
      // Re-subscribe all active subscriptions
      for (const [subId, sub] of this.subscriptions) {
        this._sendSubscribe(subId, sub.channel)
      }
      // Subscribe any pending
      for (const subId of this.pendingSubscribes) {
        const sub = this.subscriptions.get(subId)
        if (sub) this._sendSubscribe(subId, sub.channel)
      }
      this.pendingSubscribes = []
    }

    if (data.type === 'subscribe_success') {
      console.log('[appsync] subscribed:', data.id)
    }

    if (data.type === 'data') {
      // Find which subscription this data belongs to
      const subId = data.id as string
      const sub = this.subscriptions.get(subId)
      if (!sub) return

      // Parse event payload
      const raw = data.event
      const events: string[] = Array.isArray(raw) ? raw : typeof raw === 'string' ? [raw] : []
      for (const e of events) {
        try {
          const parsed = typeof e === 'string' ? JSON.parse(e) : e
          sub.handler(parsed)
        } catch { /* skip */ }
      }
    }

    // keep-alive — no action needed
  }

  private _sendSubscribe(subId: string, channel: string): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return
    this.ws.send(JSON.stringify({
      type: 'subscribe',
      id: subId,
      channel: `/docs/${channel}`,
      authorization: { 'x-api-key': APPSYNC_API_KEY, host: HTTP_HOST },
    }))
  }

  private _sendUnsubscribe(subId: string): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return
    try {
      this.ws.send(JSON.stringify({ type: 'unsubscribe', id: subId }))
    } catch { /* ignore */ }
  }

  subscribe(channel: string, handler: MessageHandler): Unsubscribe {
    const subId = `sub-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`
    this.subscriptions.set(subId, { channel, handler })

    if (this.connected && this.ws?.readyState === WebSocket.OPEN) {
      this._sendSubscribe(subId, channel)
    } else {
      this.pendingSubscribes.push(subId)
    }

    return () => {
      this._sendUnsubscribe(subId)
      this.subscriptions.delete(subId)
    }
  }

  private _setConnected(value: boolean): void {
    this.connected = value
    useDocumentStore.getState().setAppsyncConnected(value)
  }

  destroy(): void {
    this.intentionallyClosed = true
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    this.subscriptions.clear()
    this.ws?.close()
    this.ws = null
    this._setConnected(false)
  }
}

// Singleton instance
const client = new AppSyncClient()

// Auto-connect on module load
if (APPSYNC_WS_URL && APPSYNC_API_KEY) {
  client.connect()
}

// ---------------------------------------------------------------------------
// Public API (unchanged interface for consumers)
// ---------------------------------------------------------------------------

export function subscribeToChannel(channel: string, onMessage: MessageHandler): Unsubscribe {
  return client.subscribe(channel, onMessage)
}

function isPatchMessage(msg: AppSyncMessage): msg is PatchMessage {
  return msg.type === 'patch' && Array.isArray((msg as PatchMessage).operations)
}

export function handleDocumentEvent(
  msg: AppSyncMessage,
  onChat?: (msg: AppSyncMessage) => void,
): void {
  const store = useDocumentStore.getState()

  if (isPatchMessage(msg)) {
    store.applyPatches(msg.operations)
    return
  }

  if (onChat) onChat(msg)

  if (msg.type === 'status') {
    const statusMsg = msg as StatusMessage
    store.setAgentStatus(statusMsg.status)
    // Update agent_active and agent_message from status event
    const extra = msg as any
    if (extra.agent_active !== undefined || extra.message !== undefined) {
      store.setDocument({
        agent_active: extra.agent_active || '',
        agent_message: extra.message || '',
      } as any)
    }
  }
}

export function initDocumentSubscription(
  docId: string,
  onChat?: (msg: AppSyncMessage) => void,
): Unsubscribe {
  const handler = (msg: AppSyncMessage) => handleDocumentEvent(msg, onChat)

  const unsubs = [
    client.subscribe(`${docId}/chat`, handler),
    client.subscribe(`${docId}/status`, handler),
    client.subscribe(`${docId}/patch`, handler),
  ]

  return () => { unsubs.forEach(fn => fn()) }
}
