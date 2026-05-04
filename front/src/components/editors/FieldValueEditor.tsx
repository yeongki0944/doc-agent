import type { FieldValue } from '../../store/documentStore'
import { EditableField } from '../EditableField'
import { SaveStatusIndicator } from '../SaveStatusIndicator'
import { useSaveStatus } from '../../hooks/useSaveStatus'
import { resolveFieldValue, isAiRecommended } from '../AiBadge'
import { saveUserInput } from '../../utils/api'

export interface FieldValueEditorProps {
  field: FieldValue | undefined | null
  dotPath: string              // e.g. "sections.architecture.overview.user_input"
  docId: string
  placeholder?: string
  multiline?: boolean
  type?: 'text' | 'date'
  onLocalUpdate: (newField: FieldValue) => void  // optimistic Zustand update
}

/**
 * Shared save helper that wraps EditableField with optimistic update + saveUserInput + useSaveStatus.
 * Section editors compose this rather than calling saveUserInput directly.
 */
export function FieldValueEditor({
  field, dotPath, docId, placeholder, multiline, type, onLocalUpdate,
}: FieldValueEditorProps) {
  const { saveStatus, doSave } = useSaveStatus()

  const handleSave = (newValue: string) => {
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
  }

  return (
    <div style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
      <EditableField
        value={resolveFieldValue(field) ?? ''}
        isAi={isAiRecommended(field)}
        onSave={handleSave}
        placeholder={placeholder}
        multiline={multiline}
        type={type}
      />
      <SaveStatusIndicator status={saveStatus} />
    </div>
  )
}
