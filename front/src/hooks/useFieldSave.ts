import type { FieldValue } from '../store/documentStore'
import { useSaveStatus } from './useSaveStatus'
import { saveUserInput } from '../utils/api'
import { useCallback } from 'react'

/**
 * Shared save helper that encapsulates the optimistic-update + saveUserInput + useSaveStatus pattern.
 * Both FieldValueEditor and EditableComboField use this hook — no independent save implementations.
 */
export function useFieldSave(docId: string) {
  const { saveStatus, doSave } = useSaveStatus()

  const handleSave = useCallback(
    (
      dotPath: string,
      newValue: string,
      field: FieldValue | undefined | null,
      onLocalUpdate: (f: FieldValue) => void,
    ) => {
      // 1. Optimistic update — must set user_edited: true
      onLocalUpdate({
        user_input: newValue,
        ai_recommended: field?.ai_recommended ?? null,
        calculated: field?.calculated ?? null,
        status: 'draft',
        user_edited: true,
      })
      // 2. Persist via API (dot-path)
      doSave(() => saveUserInput(docId, dotPath, newValue))
    },
    [docId, doSave],
  )

  return { saveStatus, handleSave }
}
