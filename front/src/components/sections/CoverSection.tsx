import { useCallback } from 'react'
import { useDocumentStore, type FieldValue } from '../../store/documentStore'
import { useSessionStore } from '../../store/sessionStore'
import { resolveFieldValue, isAiRecommended } from '../AiBadge'
import { EditableField } from '../EditableField'
import { saveUserInput } from '../../utils/api'
import { emitUserEdit } from '../../utils/userEditEvent'
import { resolveDisplayText } from '../../utils/frontendSchema'
import { useDocLang } from '../LangContext'
import { color, font, size, space } from '../../styles/tokens'

export function CoverSection() {
  const lang = useDocLang()
  const meta = useDocumentStore(s => s.meta)
  const koCover = useDocumentStore(s => s.sections?.cover) as Record<string, any> | undefined
  const enCover = useDocumentStore(s => s.sections_en?.cover) as Record<string, any> | undefined
  const cover = lang === 'en' && enCover ? enCover : koCover
  const setDocument = useDocumentStore(s => s.setDocument)
  const docId = useSessionStore(s => s.currentDocId) || ''

  const handleMetaEdit = useCallback((field: string, label: string, newValue: string) => {
    const oldValue = resolveFieldValue(meta?.[field as keyof typeof meta]) ?? ''
    // Update store
    setDocument({
      meta: {
        ...meta,
        [field]: { user_input: newValue, ai_recommended: meta?.[field as keyof typeof meta]?.ai_recommended, calculated: null, status: 'user_modified' },
      },
    } as any)
    // Save to API
    saveUserInput(docId, `meta.${field}.user_input`, newValue).catch(() => {})
    // Notify chat
    emitUserEdit('Cover', label, String(oldValue), newValue)
  }, [meta, docId, setDocument])

  const handleCoverEdit = useCallback((field: string, label: string, newValue: string) => {
    const oldValue = cover?.[field] ?? ''
    const sections = useDocumentStore.getState().sections || {}
    const updatedCover = { ...(sections.cover || {}), [field]: newValue }
    setDocument({ sections: { ...sections, cover: updatedCover } } as any)
    saveUserInput(docId, `sections.cover.${field}`, newValue).catch(() => {})
    emitUserEdit('Cover', label, String(oldValue), newValue)
  }, [cover, docId, setDocument])

  const COVER_FIELDS: { key: string; label: string }[] = [
    { key: 'title', label: '프로젝트명' },
    { key: 'goal', label: '목표' },
    { key: 'period', label: '기간' },
    { key: 'budget', label: '예산' },
    { key: 'aws_services', label: 'AWS 서비스' },
    { key: 'version', label: '버전' },
  ]

  return (
    <div>
      <h2 style={{ marginBottom: 16, fontSize: size.lg, fontWeight: 600, fontFamily: font.heading }}>Cover Page</h2>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <tbody>
          <MetaRow label="고객사" field={meta?.customer} onSave={v => handleMetaEdit('customer', '고객사', v)} />
          <MetaRow label="파트너" field={meta?.partner} onSave={v => handleMetaEdit('partner', '파트너', v)} />
          <MetaRow label="날짜" field={meta?.date} onSave={v => handleMetaEdit('date', '날짜', v)} type="date" />
          {COVER_FIELDS.map(({ key, label }) => (
            <CoverRow
              key={key}
              label={label}
              value={cover?.[key] ?? ''}
              onSave={v => handleCoverEdit(key, label, v)}
            />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function MetaRow({ label, field, onSave, type }: { label: string; field: FieldValue | undefined | null; onSave: (v: string) => void; type?: 'text' | 'date' }) {
  const value = resolveFieldValue(field)
  return (
    <tr>
      <td style={tdLabel}>{label}</td>
      <td style={tdValue}>
        <EditableField
          value={value != null ? String(value) : ''}
          isAi={isAiRecommended(field)}
          onSave={onSave}
          placeholder={`${label} 입력`}
          type={type}
        />
      </td>
    </tr>
  )
}

function CoverRow({ label, value, onSave }: { label: string; value: string; onSave: (v: string) => void }) {
  const textValue = resolveDisplayText(value)
  return (
    <tr>
      <td style={tdLabel}>{label}</td>
      <td style={tdValue}>
        <EditableField
          value={textValue}
          isAi={!!textValue}
          onSave={onSave}
          placeholder={`${label} 입력`}
        />
      </td>
    </tr>
  )
}

const tdLabel: React.CSSProperties = { padding: '8px 12px', fontWeight: 600, borderBottom: `1px solid ${color.border}`, width: 120 }
const tdValue: React.CSSProperties = { padding: '8px 12px', borderBottom: `1px solid ${color.border}` }
