/**
 * AppSync Events subscription client.
 *
 * Subscribes to docs/{docId}/patch, docs/{docId}/status, docs/{docId}/chat
 * channels. Provides patch application to Zustand store and REST fallback.
 */

import { useDocumentStore, type PatchOperation, type AgentStatus } from '../store/documentStore'
import { getDocument } from './api'

export interface PatchMessage {
  patch_id: string
  doc_id: string
  agent: string
  operations: PatchOperation[]
  version: number
}

export interface StatusMessage {
  doc_id: string
  agent: string
  status: AgentStatus
}

export interface ChatMessage {
  doc_id: string
  agent: string
  text: string
}

type Unsubscribe = () => void

/**
 * Subscribe to AppSync Events channels for a document.
 * Returns an unsubscribe function.
 *
 * Stub: In production, replace with real WebSocket connection.
 */
export function subscribeToDocument(
  docId: string,
  handlers: {
    onPatch?: (msg: PatchMessage) => void
    onStatus?: (msg: StatusMessage) => void
    onChat?: (msg: ChatMessage) => void
  }
): Unsubscribe {
  // Stub — no real WebSocket connection yet.
  // When AppSync Events infra is deployed, this will connect to:
  //   docs/{docId}/patch
  //   docs/{docId}/status
  //   docs/{docId}/chat
  console.log(`[appsync stub] Subscribed to doc ${docId}`)

  const store = useDocumentStore.getState()
  store.setAppsyncConnected(true)

  return () => {
    console.log(`[appsync stub] Unsubscribed from doc ${docId}`)
    useDocumentStore.getState().setAppsyncConnected(false)
  }
}

/**
 * Default patch handler: apply JSON Patch operations to Zustand store.
 * This is the authoritative path for document state changes.
 */
export function handlePatchMessage(msg: PatchMessage): void {
  const store = useDocumentStore.getState()
  store.applyPatches(msg.operations)
  // Update version from patch
  if (msg.version != null) {
    store.applyPatches([{ op: 'replace', path: '/version', value: msg.version }])
  }
}

/**
 * Default status handler: update agent status in Zustand store.
 */
export function handleStatusMessage(msg: StatusMessage): void {
  useDocumentStore.getState().setAgentStatus(msg.status)
}

/**
 * REST fallback: reload full document state when AppSync connection is lost.
 */
export async function restFallbackReload(docId: string): Promise<void> {
  try {
    const doc = await getDocument(docId)
    useDocumentStore.getState().setDocument(doc)
  } catch (err) {
    console.error('[appsync] REST fallback reload failed:', err)
  }
}

/**
 * Initialize AppSync subscription with default handlers.
 * Returns unsubscribe function.
 */
export function initDocumentSubscription(
  docId: string,
  onChat?: (msg: ChatMessage) => void,
): Unsubscribe {
  return subscribeToDocument(docId, {
    onPatch: handlePatchMessage,
    onStatus: handleStatusMessage,
    onChat,
  })
}
