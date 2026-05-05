import type { FieldValue } from '../../store/documentStore'
import { EditableField } from '../EditableField'
import { SaveStatusIndicator } from '../SaveStatusIndicator'
import { useFieldSave } from '../../hooks/useFieldSave'
import { resolveFieldValue, isAiRecommended } from '../AiBadge'

export interface FieldValueEditorProps {
  field: FieldValue | undefined | null
  dotPath: string              // e.g. "sections.architecture.overview.user_input"
  docId: string
  placeholder?: string
  multiline?: boolean
  type?: 'text' | 'date'
  transformValue?: (value: string) => string
  onLocalUpdate: (newField: FieldValue) => void  // optimistic Zustand update
}

/**
 * Shared save helper that wraps EditableField with optimistic update + saveUserInput + useSaveStatus.
 * Section editors compose this rather than calling saveUserInput directly.
 */
export function FieldValueEditor({
  field, dotPath, docId, placeholder, multiline, type, transformValue, onLocalUpdate,
}: FieldValueEditorProps) {
  const { saveStatus, handleSave } = useFieldSave(docId)

  const onSave = (newValue: string) => {
    handleSave(dotPath, transformValue ? transformValue(newValue) : newValue, field, onLocalUpdate)
  }

  return (
    <div style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
      <EditableField
        value={resolveFieldValue(field) ?? ''}
        isAi={isAiRecommended(field)}
        onSave={onSave}
        placeholder={placeholder}
        multiline={multiline}
        type={type}
      />
      <SaveStatusIndicator status={saveStatus} />
    </div>
  )
}
