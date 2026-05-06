import { useCallback, useState } from 'react'
import type { ContactEntry, FieldValue } from '../../store/documentStore'
import { FieldValueEditor } from './FieldValueEditor'
import { EditableComboField } from './EditableComboField'
import { SaveStatusIndicator } from '../SaveStatusIndicator'
import { useSaveStatus } from '../../hooks/useSaveStatus'
import { saveUserInput } from '../../utils/api'
import { color } from '../../styles/tokens'
import { moveItem } from '../../utils/reorder'

const COLUMN_LABELS: Record<keyof ContactEntry, string> = {
  name: 'Name',
  title: 'Title',
  description: 'Description',
  stakeholder_for: 'Stakeholder For',
  role: 'Role',
  contact: 'Email / Contact',
}

const DEFAULT_COLUMNS: (keyof ContactEntry)[] = ['name', 'title', 'description', 'role', 'contact', 'stakeholder_for']

const emptyField = (): FieldValue => ({
  user_input: null,
  ai_recommended: null,
  calculated: null,
  status: 'empty',
  user_edited: false,
})

function createEmptyContactEntry(): ContactEntry {
  return {
    name: emptyField(),
    title: emptyField(),
    description: emptyField(),
    stakeholder_for: emptyField(),
    role: emptyField(),
    contact: emptyField(),
  }
}

export interface ContactTableEditorProps {
  contacts: ContactEntry[]
  listDotPath: string          // e.g. "sections.stakeholders.executive_sponsors"
  docId: string
  onContactsChange: (contacts: ContactEntry[]) => void
  columns?: (keyof ContactEntry)[]  // which columns to show (varies by list type)
  columnPresets?: Partial<Record<keyof ContactEntry, readonly (string | number)[]>>
  enableReorder?: boolean
}

/**
 * Editable table of ContactEntry rows with configurable visible columns.
 * Each cell uses FieldValueEditor for inline editing, or EditableComboField
 * when columnPresets are provided for that column.
 * Add/remove rows persist the full array to listDotPath via saveUserInput.
 */
export function ContactTableEditor({
  contacts, listDotPath, docId, onContactsChange, columns, columnPresets, enableReorder = false,
}: ContactTableEditorProps) {
  const visibleColumns = columns ?? DEFAULT_COLUMNS
  const { saveStatus: arraySaveStatus, doSave: doArraySave } = useSaveStatus()
  const [dragIndex, setDragIndex] = useState<number | null>(null)

  const handleAdd = useCallback(() => {
    const updated = [...contacts, createEmptyContactEntry()]
    onContactsChange(updated)
    doArraySave(() => saveUserInput(docId, listDotPath, updated))
  }, [contacts, onContactsChange, doArraySave, docId, listDotPath])

  const handleRemove = useCallback((index: number) => {
    const updated = contacts.filter((_, i) => i !== index)
    onContactsChange(updated)
    doArraySave(() => saveUserInput(docId, listDotPath, updated))
  }, [contacts, onContactsChange, doArraySave, docId, listDotPath])

  const handleDropRow = useCallback((index: number) => {
    if (!enableReorder || dragIndex === null || dragIndex === index) {
      setDragIndex(null)
      return
    }
    const updated = moveItem(contacts, dragIndex, index)
    onContactsChange(updated)
    doArraySave(() => saveUserInput(docId, listDotPath, updated))
    setDragIndex(null)
  }, [contacts, docId, doArraySave, dragIndex, enableReorder, listDotPath, onContactsChange])

  const handleLocalUpdate = useCallback((index: number, field: keyof ContactEntry, newField: FieldValue) => {
    const updated = contacts.map((entry, i) =>
      i === index ? { ...entry, [field]: newField } : entry,
    )
    onContactsChange(updated)
  }, [contacts, onContactsChange])

  return (
    <div>
      <div style={{ overflowX: 'auto' }}>
        <table style={tableStyle}>
          <thead>
            <tr>
              {enableReorder && <th style={thStyle} />}
              <th style={thStyle}>#</th>
              {visibleColumns.map(col => (
                <th key={col} style={thStyle}>{COLUMN_LABELS[col]}</th>
              ))}
              <th style={thStyle} />
            </tr>
          </thead>
          <tbody>
            {contacts.map((entry, index) => (
              <tr
                key={index}
                style={{ opacity: dragIndex === index ? 0.55 : 1 }}
                onDragOver={event => enableReorder && event.preventDefault()}
                onDrop={() => handleDropRow(index)}
              >
                {enableReorder && (
                  <td style={tdStyle}>
                    <button
                      type="button"
                      draggable
                      onDragStart={() => setDragIndex(index)}
                      onDragEnd={() => setDragIndex(null)}
                      style={dragHandle}
                      title="Drag row to reorder"
                    >
                      ↕
                    </button>
                  </td>
                )}
                <td style={tdStyle}>
                  <span style={{ color: color.textMuted, fontSize: 12 }}>{index + 1}</span>
                </td>
                {visibleColumns.map(col => {
                  const presets = columnPresets?.[col]
                  return (
                    <td key={col} style={tdStyle}>
                      {presets && presets.length > 0 ? (
                        <EditableComboField
                          field={entry[col]}
                          dotPath={`${listDotPath}.${index}.${col}.user_input`}
                          docId={docId}
                          placeholder={COLUMN_LABELS[col]}
                          presets={presets}
                          onLocalUpdate={(newField) => handleLocalUpdate(index, col, newField)}
                        />
                      ) : (
                        <FieldValueEditor
                          field={entry[col]}
                          dotPath={`${listDotPath}.${index}.${col}.user_input`}
                          docId={docId}
                          placeholder={COLUMN_LABELS[col]}
                          onLocalUpdate={(newField) => handleLocalUpdate(index, col, newField)}
                        />
                      )}
                    </td>
                  )
                })}
                <td style={tdStyle}>
                  <button
                    onClick={() => handleRemove(index)}
                    style={removeBtnStyle}
                    title="삭제"
                  >
                    ✕
                  </button>
                </td>
              </tr>
            ))}
            {contacts.length === 0 && (
              <tr>
                <td colSpan={visibleColumns.length + (enableReorder ? 3 : 2)} style={{ ...tdStyle, textAlign: 'center', color: color.textMuted }}>
                  항목이 없습니다
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
        <button onClick={handleAdd} style={addBtnStyle}>
          + 추가
        </button>
        <SaveStatusIndicator status={arraySaveStatus} />
      </div>
    </div>
  )
}

const tableStyle: React.CSSProperties = {
  width: '100%',
  borderCollapse: 'collapse',
  fontSize: 13,
}

const thStyle: React.CSSProperties = {
  textAlign: 'left',
  padding: '6px 8px',
  fontSize: 11,
  fontWeight: 700,
  color: color.textMuted,
  borderBottom: `1px solid ${color.border}`,
  whiteSpace: 'nowrap',
}

const tdStyle: React.CSSProperties = {
  padding: '4px 8px',
  borderBottom: `1px solid ${color.border}`,
  verticalAlign: 'top',
}

const removeBtnStyle: React.CSSProperties = {
  background: 'none',
  border: 'none',
  cursor: 'pointer',
  color: color.textMuted,
  fontSize: 14,
  padding: '2px 4px',
}

const dragHandle: React.CSSProperties = {
  border: 'none',
  background: 'transparent',
  color: color.textMuted,
  cursor: 'grab',
  fontSize: 13,
  padding: '2px 3px',
  lineHeight: 1,
}

const addBtnStyle: React.CSSProperties = {
  background: 'none',
  border: `1px dashed ${color.border}`,
  borderRadius: 4,
  padding: '4px 10px',
  cursor: 'pointer',
  color: color.textSecondary,
  fontSize: 12,
}
