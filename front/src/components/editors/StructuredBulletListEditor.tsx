import { useCallback, useState } from 'react'
import type { FieldValue, StructuredBullet } from '../../store/documentStore'
import { FieldValueEditor } from './FieldValueEditor'
import { SaveStatusIndicator } from '../SaveStatusIndicator'
import { useSaveStatus } from '../../hooks/useSaveStatus'
import { saveUserInput } from '../../utils/api'
import { sanitizeListPasteText } from '../../utils/textSanitizer'
import { moveItem, normalizeStructuredBulletLevels } from '../../utils/reorder'
import { color } from '../../styles/tokens'

const emptyField = (): FieldValue => ({
  user_input: null,
  ai_recommended: null,
  calculated: null,
  status: 'empty',
  user_edited: false,
})

export const createStructuredBullet = (text?: string, level: 1 | 2 = 1): StructuredBullet => ({
  text: text
    ? { user_input: sanitizeListPasteText(text), ai_recommended: null, calculated: null, status: 'draft', user_edited: true }
    : emptyField(),
  level,
})

function canIndent(items: StructuredBullet[], index: number): boolean {
  return index > 0 && items[index]?.level === 1 && items.slice(0, index).some(item => item.level === 1)
}

export interface StructuredBulletListEditorProps {
  items: StructuredBullet[]
  listDotPath: string
  docId: string
  onItemsChange: (items: StructuredBullet[]) => void
  placeholder?: string
  compact?: boolean
}

export function StructuredBulletListEditor({
  items, listDotPath, docId, onItemsChange, placeholder, compact,
}: StructuredBulletListEditorProps) {
  const { saveStatus: arraySaveStatus, doSave: doArraySave } = useSaveStatus()
  const [dragIndex, setDragIndex] = useState<number | null>(null)

  const persist = useCallback((updated: StructuredBullet[]) => {
    onItemsChange(updated)
    doArraySave(() => saveUserInput(docId, listDotPath, updated))
  }, [docId, doArraySave, listDotPath, onItemsChange])

  const handleAdd = useCallback(() => {
    persist([...items, createStructuredBullet()])
  }, [items, persist])

  const handleRemove = useCallback((index: number) => {
    persist(normalizeStructuredBulletLevels(items.filter((_, i) => i !== index)))
  }, [items, persist])

  const handleTextUpdate = useCallback((index: number, newField: FieldValue) => {
    onItemsChange(items.map((item, i) => (i === index ? { ...item, text: newField } : item)))
  }, [items, onItemsChange])

  const setLevel = useCallback((index: number, level: 1 | 2) => {
    if (level === 2 && !canIndent(items, index)) return
    persist(items.map((item, i) => (i === index ? { ...item, level } : item)))
  }, [items, persist])

  const handleDrop = useCallback((index: number) => {
    if (dragIndex === null || dragIndex === index) {
      setDragIndex(null)
      return
    }
    persist(normalizeStructuredBulletLevels(moveItem(items, dragIndex, index)))
    setDragIndex(null)
  }, [dragIndex, items, persist])

  const handleItemKeyDown = useCallback((index: number) => (event: React.KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    if (event.key !== 'Tab') return
    event.preventDefault()
    setLevel(index, event.shiftKey ? 1 : 2)
  }, [setLevel])

  return (
    <div>
      {items.map((item, index) => (
        <div
          key={index}
          style={{ ...rowStyle, marginLeft: item.level === 2 ? 24 : 0, opacity: dragIndex === index ? 0.55 : 1 }}
          onDragOver={event => event.preventDefault()}
          onDrop={() => handleDrop(index)}
        >
          <button
            type="button"
            draggable
            onDragStart={() => setDragIndex(index)}
            onDragEnd={() => setDragIndex(null)}
            style={dragHandle}
            title="Drag to reorder"
          >
            ↕
          </button>
          <span style={markerStyle}>{item.level === 2 ? '◦' : '•'}</span>
          <FieldValueEditor
            field={item.text}
            dotPath={`${listDotPath}.${index}.text.user_input`}
            docId={docId}
            placeholder={placeholder ?? 'Item'}
            multiline={compact ? false : true}
            transformValue={sanitizeListPasteText}
            onKeyDown={handleItemKeyDown(index)}
            onLocalUpdate={(newField) => handleTextUpdate(index, newField)}
          />
          <button type="button" onClick={() => setLevel(index, 1)} disabled={item.level === 1} style={toolBtn} title="Outdent">←</button>
          <button type="button" onClick={() => setLevel(index, 2)} disabled={!canIndent(items, index)} style={toolBtn} title="Indent">→</button>
          <button type="button" onClick={() => handleRemove(index)} style={removeBtn} title="Remove">✕</button>
        </div>
      ))}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
        <button type="button" onClick={handleAdd} style={addBtn}>+ item</button>
        <SaveStatusIndicator status={arraySaveStatus} />
      </div>
    </div>
  )
}

const rowStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 4,
  marginBottom: 4,
}

const markerStyle: React.CSSProperties = {
  color: color.textMuted,
  fontSize: 14,
  minWidth: 14,
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

const toolBtn: React.CSSProperties = {
  border: `1px solid ${color.border}`,
  borderRadius: 4,
  background: color.bgSurface,
  color: color.textSecondary,
  cursor: 'pointer',
  fontSize: 12,
  padding: '2px 5px',
}

const removeBtn: React.CSSProperties = {
  background: 'none',
  border: 'none',
  cursor: 'pointer',
  color: color.textMuted,
  fontSize: 14,
  padding: '2px 4px',
}

const addBtn: React.CSSProperties = {
  background: 'none',
  border: `1px dashed ${color.border}`,
  borderRadius: 4,
  padding: '4px 10px',
  cursor: 'pointer',
  color: color.textSecondary,
  fontSize: 12,
}
