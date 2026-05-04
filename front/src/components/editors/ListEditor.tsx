import type { FieldValue } from '../../store/documentStore'
import { FieldValueEditor } from './FieldValueEditor'
import { SaveStatusIndicator } from '../SaveStatusIndicator'
import { useSaveStatus } from '../../hooks/useSaveStatus'
import { saveUserInput } from '../../utils/api'
import { color } from '../../styles/tokens'

interface ListEditorProps {
  items: FieldValue[]
  listDotPath: string          // e.g. "sections.architecture.tools_list"
  docId: string
  onItemsChange: (items: FieldValue[]) => void  // Zustand updater
  placeholder?: string
  multiline?: boolean
}

const emptyField = (): FieldValue => ({
  user_input: null,
  ai_recommended: null,
  calculated: null,
  status: 'empty',
  user_edited: false,
})

/**
 * Generic editor for FieldValue[] lists (tools_list, out_of_scope, items,
 * phases_overview, poc_objectives, current_pain_points).
 *
 * - Edit item: dot-path `{listDotPath}.{index}.user_input`
 * - Add item: append empty FieldValue, persist full array to listDotPath
 * - Remove item: splice, persist full array to listDotPath
 */
export function ListEditor({
  items, listDotPath, docId, onItemsChange, placeholder, multiline,
}: ListEditorProps) {
  const { saveStatus: arraySaveStatus, doSave: doArraySave } = useSaveStatus()

  const handleAdd = () => {
    const updated = [...items, emptyField()]
    onItemsChange(updated)
    doArraySave(() => saveUserInput(docId, listDotPath, updated))
  }

  const handleRemove = (index: number) => {
    const updated = items.filter((_, i) => i !== index)
    onItemsChange(updated)
    doArraySave(() => saveUserInput(docId, listDotPath, updated))
  }

  const handleLocalUpdate = (index: number, newField: FieldValue) => {
    const updated = items.map((item, i) => (i === index ? newField : item))
    onItemsChange(updated)
  }

  return (
    <div>
      {items.map((item, index) => (
        <div key={index} style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 4 }}>
          <span style={{ color: color.textMuted, fontSize: 12, minWidth: 18 }}>{index + 1}.</span>
          <FieldValueEditor
            field={item}
            dotPath={`${listDotPath}.${index}.user_input`}
            docId={docId}
            placeholder={placeholder ?? '항목 입력'}
            multiline={multiline}
            onLocalUpdate={(newField) => handleLocalUpdate(index, newField)}
          />
          <button
            onClick={() => handleRemove(index)}
            style={{
              background: 'none', border: 'none', cursor: 'pointer',
              color: color.textMuted, fontSize: 14, padding: '2px 4px',
            }}
            title="삭제"
          >
            ✕
          </button>
        </div>
      ))}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
        <button
          onClick={handleAdd}
          style={{
            background: 'none', border: `1px dashed ${color.border}`,
            borderRadius: 4, padding: '4px 10px', cursor: 'pointer',
            color: color.textSecondary, fontSize: 12,
          }}
        >
          + 추가
        </button>
        <SaveStatusIndicator status={arraySaveStatus} />
      </div>
    </div>
  )
}
