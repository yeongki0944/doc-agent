import { useState, useRef, useEffect, useCallback } from 'react'
import type { FieldValue } from '../../store/documentStore'
import { EditableField } from '../EditableField'
import { SaveStatusIndicator } from '../SaveStatusIndicator'
import { useFieldSave } from '../../hooks/useFieldSave'
import { resolveFieldValue, isAiRecommended } from '../AiBadge'
import { color, radius, shadow, size, space } from '../../styles/tokens'

export interface EditableComboFieldProps {
  field: FieldValue | undefined | null
  dotPath: string
  docId: string
  placeholder?: string
  multiline?: boolean
  presets: readonly (string | number)[]
  onLocalUpdate: (newField: FieldValue) => void
}

/**
 * Combo-box component: text input (via EditableField) + preset dropdown.
 * Uses the shared useFieldSave hook — same save pattern as FieldValueEditor.
 * If presets array is empty, behaves identically to FieldValueEditor.
 */
export function EditableComboField({
  field, dotPath, docId, placeholder, multiline, presets, onLocalUpdate,
}: EditableComboFieldProps) {
  const { saveStatus, handleSave } = useFieldSave(docId)
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const [dropdownPos, setDropdownPos] = useState<{ top: number; left: number; openUp: boolean }>({ top: 0, left: 0, openUp: false })

  const onSave = useCallback((newValue: string) => {
    handleSave(dotPath, newValue, field, onLocalUpdate)
  }, [handleSave, dotPath, field, onLocalUpdate])

  const onPresetSelect = useCallback((preset: string | number) => {
    const value = String(preset)
    onSave(value)
    setDropdownOpen(false)
  }, [onSave])

  // Calculate dropdown position when opening
  useEffect(() => {
    if (!dropdownOpen || !triggerRef.current) return
    const rect = triggerRef.current.getBoundingClientRect()
    const spaceBelow = window.innerHeight - rect.bottom
    const openUp = spaceBelow < 220
    setDropdownPos({
      top: openUp ? rect.top - 2 : rect.bottom + 2,
      left: rect.left,
      openUp,
    })
  }, [dropdownOpen])

  // Close dropdown on click outside
  useEffect(() => {
    if (!dropdownOpen) return
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [dropdownOpen])

  const hasPresets = presets.length > 0

  return (
    <div ref={containerRef} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, position: 'relative' }}>
      <EditableField
        value={resolveFieldValue(field) ?? ''}
        isAi={isAiRecommended(field)}
        onSave={onSave}
        placeholder={placeholder}
        multiline={multiline}
      />
      {hasPresets && (
        <button
          ref={triggerRef}
          type="button"
          onClick={() => setDropdownOpen(prev => !prev)}
          style={{
            background: 'none',
            border: `1px solid ${color.border}`,
            borderRadius: radius.sm,
            cursor: 'pointer',
            padding: '2px 5px',
            fontSize: size.xs,
            color: color.textSecondary,
            lineHeight: 1,
            flexShrink: 0,
          }}
          title="프리셋 선택"
        >
          ▾
        </button>
      )}
      <SaveStatusIndicator status={saveStatus} />
      {dropdownOpen && hasPresets && (
        <div
          style={{
            position: 'fixed',
            top: dropdownPos.openUp ? undefined : dropdownPos.top,
            bottom: dropdownPos.openUp ? (window.innerHeight - dropdownPos.top) : undefined,
            left: dropdownPos.left,
            zIndex: 9999,
            background: color.bgSurface,
            border: `1px solid ${color.border}`,
            borderRadius: radius.sm,
            boxShadow: shadow.elevated,
            maxHeight: 200,
            overflowY: 'auto',
            minWidth: 180,
          }}
        >
          {presets.map((preset, idx) => (
            <div
              key={idx}
              onClick={() => onPresetSelect(preset)}
              style={{
                padding: `${space.xs}px ${space.sm}px`,
                cursor: 'pointer',
                fontSize: size.sm,
                color: color.textPrimary,
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
              onMouseEnter={e => { (e.currentTarget as HTMLDivElement).style.background = color.bgSubtle }}
              onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.background = 'transparent' }}
            >
              {String(preset)}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
