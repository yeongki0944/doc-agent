import { useState, useRef, useEffect } from 'react'
import { color, radius } from '../styles/tokens'
import { resolveDisplayText } from '../utils/frontendSchema'

interface EditableFieldProps {
  value: any
  isAi?: boolean
  onSave: (newValue: string) => void
  placeholder?: string
  multiline?: boolean
  type?: 'text' | 'date'
  onDraftChange?: (value: string) => void
  onKeyDown?: (event: React.KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>) => void
}

/**
 * Inline editable field. Double-click to edit, Enter/blur to save, Esc to cancel.
 * Shows a pencil icon on hover. AI values get yellow background + badge.
 * type="date" renders a native date picker.
 */
export function EditableField({ value, isAi, onSave, placeholder, multiline, type = 'text', onDraftChange, onKeyDown }: EditableFieldProps) {
  const textValue = resolveDisplayText(value)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(textValue)
  const [hover, setHover] = useState(false)
  const inputRef = useRef<HTMLInputElement | HTMLTextAreaElement>(null)

  useEffect(() => { setDraft(textValue) }, [textValue])
  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus()
      inputRef.current.select()
    }
  }, [editing])

  const save = () => {
    const trimmed = draft.trim()
    setEditing(false)
    if (trimmed && trimmed !== textValue) {
      onSave(trimmed)
    } else {
      setDraft(textValue)
    }
  }

  const cancel = () => { setDraft(textValue); setEditing(false) }

  if (editing) {
    const style: React.CSSProperties = {
      width: '100%', padding: '4px 8px', border: `2px solid ${color.mzRed}`,
      borderRadius: 4, fontSize: 14, outline: 'none', background: color.bgSurface,
      fontFamily: 'inherit', resize: multiline ? 'vertical' : 'none',
    }
    if (type === 'date') {
      return (
        <input
          ref={inputRef as React.RefObject<HTMLInputElement>}
          type="date"
          value={draft}
          onChange={e => {
            setDraft(e.target.value)
            onDraftChange?.(e.target.value)
            // Auto-save on date selection
            if (e.target.value && e.target.value !== textValue) {
              onSave(e.target.value)
            }
            setEditing(false)
          }}
          onBlur={save}
          onKeyDown={e => {
            onKeyDown?.(e)
            if (e.defaultPrevented) return
            if (e.key === 'Escape') cancel()
          }}
          style={style}
        />
      )
    }
    if (multiline) {
      return (
        <textarea
          ref={inputRef as React.RefObject<HTMLTextAreaElement>}
          value={draft}
          onChange={e => { setDraft(e.target.value); onDraftChange?.(e.target.value) }}
          onBlur={save}
          onKeyDown={e => {
            onKeyDown?.(e)
            if (e.defaultPrevented) return
            if (e.key === 'Escape') cancel()
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); save() }
          }}
          rows={3}
          style={style}
        />
      )
    }
    return (
      <input
        ref={inputRef as React.RefObject<HTMLInputElement>}
        value={draft}
        onChange={e => { setDraft(e.target.value); onDraftChange?.(e.target.value) }}
        onBlur={save}
        onKeyDown={e => {
          onKeyDown?.(e)
          if (e.defaultPrevented) return
          if (e.key === 'Escape') cancel()
          if (e.key === 'Enter') save()
        }}
        style={style}
      />
    )
  }

  const displayValue = textValue || placeholder || '-'

  return (
    <span
      onDoubleClick={() => setEditing(true)}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 4,
        background: isAi ? color.aiBadgeBg : 'transparent',
        padding: isAi ? '2px 6px' : '2px 4px',
        borderRadius: 4, cursor: 'text', minHeight: 24,
        border: hover ? `1px dashed ${color.mzRed}` : '1px dashed transparent',
        transition: 'border-color 0.15s',
      }}
      title="더블클릭하여 수정"
    >
      <span style={{ color: textValue ? 'inherit' : color.textMuted }}>{displayValue}</span>
      {isAi && (
        <span style={{
          padding: '1px 5px', borderRadius: 4, fontSize: 9, fontWeight: 700,
          color: color.aiBadgeText, background: color.aiBadgeBg, border: `1px solid ${color.aiBadgeBorder}`,
        }}>AI</span>
      )}
      {hover && (
        <span style={{ fontSize: 12, color: color.mzRed, marginLeft: 2, flexShrink: 0 }}>✎</span>
      )}
    </span>
  )
}
