/**
 * AppSync Events API WebSocket client.
 * Protocol: https://docs.aws.amazon.com/appsync/latest/eventapi/event-api-websocket-protocol.html
 */

import { useDocumentStore, type AgentStatus } from '../store/documentStore'

export interface ChatChunkMessage { type: 'chat_chunk'; text: string }
export interface ChatDoneMessage { type: 'chat_done'; actions: string[]; document: any }
export interface StatusMessage { type: 'status'; status: AgentStatus; message?: string }
export type AppSyncMessage = ChatChunkMessage | ChatDoneMessage | StatusMessage

type MessageHandler = (msg: AppSyncMessage) => void
type Unsubscribe = () => void

const APPSYNC_HTTP_URL = (import.meta.env.VITE_APPSYNC_HTTP_URL as string) || ''
const APPSYNC_WS_URL = (import.meta.env.VITE_APPSYNC_WS_URL as string) || ''
const APPSYNC_API_KEY = (import.meta.env.VITE_APPSYNC_API_KEY as string) || ''

function base64url(obj: object): string {
  return btoa(JSON.stringify(obj))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '')
}

export function subscribeToChannel(channel: string, onMessage: MessageHandler): Unsubscribe {
  if (!APPSYNC_WS_URL || !APPSYNC_API_KEY) {
    console.warn('[appsync] Missing config, stub mode')
    return () => {}
  }

  let ws: WebSocket | null = null
  let closed = false
  let subId: string | null = null

  // Derive HTTP host for auth headers
  const httpHost = APPSYNC_HTTP_URL
    ? new URL(APPSYNC_HTTP_URL).host
    : APPSYNC_WS_URL.replace('wss://', '').replace('/event/realtime', '').replace('realtime-api', 'api')

  const connect = () => {
    if (closed) return
    try {
      const authHeader = base64url({ host: httpHost, 'x-api-key': APPSYNC_API_KEY })
      // URL must end with /event/realtime
      let wsUrl = APPSYNC_WS_URL
      if (!wsUrl.endsWith('/event/realtime')) {
        wsUrl = wsUrl.replace(/\/$/, '') + '/event/realtime'
      }

      ws = new WebSocket(wsUrl, [`header-${authHeader}`, 'aws-appsync-event-ws'])

      ws.onopen = () => {
        ws?.send(JSON.stringify({ type: 'connection_init' }))
      }

      ws.onmessage = (evt) => {
        try {
          const data = JSON.parse(evt.data)

          if (data.type === 'connection_ack') {
            subId = `sub-${Date.now()}`
            ws?.send(JSON.stringify({
              type: 'subscribe',
              id: subId,
              channel: `/docs/${channel}`,
              authorization: {
                'x-api-key': APPSYNC_API_KEY,
                host: httpHost,
              },
            }))
          }

          if (data.type === 'subscribe_success') {
            console.log('[appsync] subscribed:', channel)
            useDocumentStore.getState().setAppsyncConnected(true)
          }

          if (data.type === 'data') {
            // Events API uses "event" (array of stringified JSON)
            const events: string[] = data.event || data.events || []
            for (const e of events) {
              try {
                onMessage(typeof e === 'string' ? JSON.parse(e) : e)
              } catch { /* skip */ }
            }
          }

          // keep-alive — no action needed
        } catch { /* ignore */ }
      }

      ws.onclose = () => {
        useDocumentStore.getState().setAppsyncConnected(false)
        if (!closed) setTimeout(connect, 3000)
      }

      ws.onerror = () => { ws?.close() }
    } catch (e) {
      console.error('[appsync] connect error:', e)
      if (!closed) setTimeout(connect, 5000)
    }
  }

  connect()

  return () => {
    closed = true
    if (ws && subId) {
      try { ws.send(JSON.stringify({ type: 'unsubscribe', id: subId })) } catch { /* */ }
    }
    try { ws?.close() } catch { /* */ }
    useDocumentStore.getState().setAppsyncConnected(false)
  }
}

export function initDocumentSubscription(
  docId: string,
  onChat?: (msg: AppSyncMessage) => void,
): Unsubscribe {
  return subscribeToChannel(`${docId}/chat`, (msg) => {
    if (msg.type === 'status') {
      useDocumentStore.getState().setAgentStatus(msg.status)
    }
    if (onChat) onChat(msg)
  })
}
