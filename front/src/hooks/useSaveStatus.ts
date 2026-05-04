import { useState, useCallback, useRef } from 'react'

export type SaveStatus = 'idle' | 'saving' | 'saved' | 'failed'

/**
 * Lightweight per-field save status tracker.
 * On success: sets 'saved', auto-resets to 'idle' after resetDelay ms.
 * On failure: sets 'failed' and does NOT auto-reset (user must see the error).
 */
export function useSaveStatus(resetDelay = 2000) {
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle')
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const doSave = useCallback(async (saveFn: () => Promise<void>) => {
    // Clear any pending reset timer
    if (timerRef.current) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }

    setSaveStatus('saving')
    try {
      await saveFn()
      setSaveStatus('saved')
      timerRef.current = setTimeout(() => setSaveStatus('idle'), resetDelay)
    } catch {
      setSaveStatus('failed')
      // Do NOT reset to idle on failure — user must see the error
    }
  }, [resetDelay])

  return { saveStatus, doSave }
}
