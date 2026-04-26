import { useCallback } from 'react'
import { useDocumentStore } from '../../store/documentStore'
import { useSessionStore } from '../../store/sessionStore'
import { EditableField } from '../EditableField'
import { saveUserInput } from '../../utils/api'
import { emitUserEdit } from '../../utils/userEditEvent'
import { useDocLang } from '../LangContext'
import { color } from '../../styles/tokens'

interface GenericSectionProps {
  title: string
  sectionKey: string
  emptyMessage: string
  chatHint: string
}

/**
 * Generic editable section for key-value data (Overview, Scope, Assumptions, etc.)
 * All fields are inline-editable via double-click.
 */
export function GenericSection({ title, sectionKey, emptyMessage, chatHint }: GenericSectionProps) {
  const lang = useDocLang()
  const koData = useDocumentStore(s => s.sections?.[sectionKey]) as Record<string, any> | undefined
  const enData = useDocumentStore(s => s.sections_en?.[sectionKey]) as Record<string, any> | undefined
  const sectionData = lang === 'en' ? enData : koData
  const hasKoContent = koData && Object.keys(koData).some(k => koData[k])
  const setDocument = useDocumentStore(s => s.setDocument)
  const docId = useSessionStore(s => s.currentDocId) || ''

  const hasContent = sectionData && Object.keys(sectionData).some(k => sectionData[k])

  const handleEdit = useCallback((key: string, newValue: string) => {
    const oldValue = koData?.[key] ?? ''
    const sections = useDocumentStore.getState().sections || {}
    const updated = { ...(sections[sectionKey] || {}), [key]: newValue }
    setDocument({ sections: { ...sections, [sectionKey]: updated } } as any)
    saveUserInput(docId, `sections.${sectionKey}.${key}`, newValue).catch(() => {})
    emitUserEdit(title, key, String(oldValue), newValue)
  }, [koData, sectionKey, docId, setDocument, title])

  if (!hasKoContent) {
    return (
      <div>
        <h2 style={{ marginBottom: 16 }}>{title}</h2>
        <p style={{ color: color.textMuted }}>{emptyMessage} 채팅에서 "{chatHint}"라고 요청하세요.</p>
      </div>
    )
  }

  if (lang === 'en' && !enData) {
    return (
      <div>
        <h2 style={{ marginBottom: 16 }}>{title}</h2>
        <p style={{ color: '#f59e0b', fontSize: 13 }}>⏳ 영어 번역이 아직 생성되지 않았습니다. 섹션을 다시 작성하면 자동 번역됩니다.</p>
      </div>
    )
  }

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>{title}</h2>
      {Object.entries(sectionData!).map(([key, val]) =>
        val ? (
          <div key={key} style={{ marginBottom: 8, padding: 8, borderRadius: 4, border: `1px solid ${color.border}` }}>
            <span style={{ fontWeight: 600, marginRight: 4 }}>{key}: </span>
            <EditableField
              value={String(val)}
              isAi={true}
              onSave={v => handleEdit(key, v)}
              multiline={String(val).length > 60}
            />
          </div>
        ) : null
      )}
    </div>
  )
}
