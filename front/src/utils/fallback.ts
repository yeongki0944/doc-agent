/**
 * REST polling fallback for when AppSync connection drops.
 * Detects disconnection and falls back to GET /documents/{docId}.
 */

import { getDocument } from './api'
import { useDocumentStore } from '../store/documentStore'

let pollingInterval: ReturnType<typeof setInterval> | null = null

export function startFallbackPolling(docId: string, intervalMs = 5000): void {
  stopFallbackPolling()
  pollingInterval = setInterval(async () => {
    try {
      const data = await getDocument(docId)
      useDocumentStore.getState().setDocument(data)
    } catch {
      // Silently retry on next interval
    }
  }, intervalMs)
}

export function stopFallbackPolling(): void {
  if (pollingInterval) {
    clearInterval(pollingInterval)
    pollingInterval = null
  }
}
