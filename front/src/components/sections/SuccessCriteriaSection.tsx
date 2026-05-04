import { useCallback, useState, useRef, useEffect } from 'react'
import { useDocumentStore, type SuccessCriteriaSection as SuccessCriteriaModel, type CategoryGroup } from '../../store/documentStore'
import { useSessionStore } from '../../store/sessionStore'
import { CategoryGroupEditor } from '../editors/CategoryGroupEditor'
import { SectionGuideButton } from '../SectionGuideButton'
import { useDocLang } from '../LangContext'
import { color, font, size, space, radius, shadow } from '../../styles/tokens'
import { useSaveStatus } from '../../hooks/useSaveStatus'
import { saveUserInput } from '../../utils/api'
import {
  SUCCESS_CRITERIA_PRESET_GROUPS,
  presetGroupToCategoryGroup,
} from '../../constants/documentPresets'

export function SuccessCriteriaSection() {
  const lang = useDocLang()
  const koData = useDocumentStore(s => s.sections?.success_criteria) as SuccessCriteriaModel | undefined
  const enData = useDocumentStore(s => s.sections_en?.success_criteria) as SuccessCriteriaModel | undefined
  const sectionData = lang === 'en' ? enData : koData
  const setDocument = useDocumentStore(s => s.setDocument)
  const docId = useSessionStore(s => s.currentDocId) || ''
  const { doSave } = useSaveStatus()

  const handleGroupsChange = useCallback((groups: CategoryGroup[]) => {
    const sections = useDocumentStore.getState().sections || {}
    const current = (sections.success_criteria || {}) as SuccessCriteriaModel
    const updated = { ...current, groups }
    setDocument({ sections: { ...sections, success_criteria: updated } } as any)
  }, [setDocument])

  const handleAddPresetGroup = useCallback((presetIndex: number) => {
    const preset = SUCCESS_CRITERIA_PRESET_GROUPS[presetIndex]
    if (!preset) return
    const newGroup = presetGroupToCategoryGroup(preset)
    const sections = useDocumentStore.getState().sections || {}
    const current = (sections.success_criteria || {}) as SuccessCriteriaModel
    const currentGroups = current.groups ?? []
    const updatedGroups = [...currentGroups, newGroup]
    const updated = { ...current, groups: updatedGroups }
    setDocument({ sections: { ...sections, success_criteria: updated } } as any)
    doSave(() => saveUserInput(docId, 'sections.success_criteria.groups', updatedGroups))
  }, [setDocument, doSave, docId])

  const handleAddEmptyGroup = useCallback(() => {
    const emptyField = () => ({ user_input: null, ai_recommended: null, calculated: null, status: 'empty' as const, user_edited: false })
    const newGroup: CategoryGroup = { category_name: emptyField(), bullets: [] }
    const sections = useDocumentStore.getState().sections || {}
    const current = (sections.success_criteria || {}) as SuccessCriteriaModel
    const currentGroups = current.groups ?? []
    const updatedGroups = [...currentGroups, newGroup]
    const updated = { ...current, groups: updatedGroups }
    setDocument({ sections: { ...sections, success_criteria: updated } } as any)
    doSave(() => saveUserInput(docId, 'sections.success_criteria.groups', updatedGroups))
  }, [setDocument, doSave, docId])

  const groups = sectionData?.groups ?? []

  if (groups.length === 0) {
    return (
      <div>
        <h2 style={headingStyle}>
          2.3 Success Criteria / KPIs
          <SectionGuideButton sectionKey="success_criteria" />
        </h2>
        <div style={emptyContainer}>
          <p style={emptyMainText}>
            성공 기준이 아직 정의되지 않았습니다.
            자주 사용하는 형식을 선택하여 시작하거나, 직접 입력할 수 있습니다.
          </p>
          <div style={actionRow}>
            <PresetGroupPicker onSelect={handleAddPresetGroup} />
            <button style={actionBtn} onClick={handleAddEmptyGroup}>
              ✏️ 직접 그룹 추가
            </button>
            <button style={{ ...actionBtn, ...actionBtnMuted }}>
              🤖 AI에게 초안 요청
            </button>
          </div>
          <p style={emptyAiHint}>
            AI 요청 예시: Success Criteria 초안 작성해줘
          </p>
        </div>
      </div>
    )
  }

  return (
    <div>
      <h2 style={headingStyle}>
        2.3 Success Criteria / KPIs
        <SectionGuideButton sectionKey="success_criteria" />
      </h2>
      <div style={{ marginBottom: space.md, display: 'flex', gap: space.sm }}>
        <PresetGroupPicker onSelect={handleAddPresetGroup} />
      </div>
      <CategoryGroupEditor
        groups={groups}
        sectionDotPath="sections.success_criteria.groups"
        docId={docId}
        onGroupsChange={handleGroupsChange}
      />
    </div>
  )
}

/* --- Preset Group Picker --- */

function PresetGroupPicker({ onSelect }: { onSelect: (index: number) => void }) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [open])

  return (
    <div ref={containerRef} style={{ position: 'relative', display: 'inline-block' }}>
      <button style={presetPickerBtn} onClick={() => setOpen(prev => !prev)}>
        📋 프리셋 그룹 추가
      </button>
      {open && (
        <div style={presetDropdown}>
          {SUCCESS_CRITERIA_PRESET_GROUPS.map((group, idx) => (
            <div
              key={idx}
              onClick={() => { onSelect(idx); setOpen(false) }}
              style={presetDropdownItem}
              onMouseEnter={e => { (e.currentTarget as HTMLDivElement).style.background = color.bgSubtle }}
              onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.background = 'transparent' }}
            >
              <div style={{ fontWeight: 600, fontSize: size.sm }}>{group.category_name}</div>
              <div style={{ fontSize: size.xs, color: color.textMuted, marginTop: 2 }}>
                {group.bullets.slice(0, 2).join(', ')}{group.bullets.length > 2 ? '…' : ''}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/* --- Styles --- */

const headingStyle: React.CSSProperties = {
  marginBottom: 16,
  fontSize: size.lg,
  fontWeight: 600,
  fontFamily: font.heading,
  display: 'flex',
  alignItems: 'center',
  gap: space.xs,
}

const emptyContainer: React.CSSProperties = {
  padding: space.xl,
  border: `1px dashed ${color.border}`,
  borderRadius: 8,
  background: color.bgPrimary,
  textAlign: 'center',
}

const emptyMainText: React.CSSProperties = {
  color: color.textSecondary,
  fontSize: size.base,
  lineHeight: 1.6,
  marginBottom: space.md,
}

const emptyAiHint: React.CSSProperties = {
  color: color.info,
  fontSize: size.sm,
  fontStyle: 'italic',
  marginTop: space.md,
}

const actionRow: React.CSSProperties = {
  display: 'flex',
  gap: space.sm,
  justifyContent: 'center',
  flexWrap: 'wrap',
}

const actionBtn: React.CSSProperties = {
  padding: `${space.sm}px ${space.md}px`,
  border: `1px solid ${color.border}`,
  borderRadius: 6,
  background: color.bgSurface,
  cursor: 'pointer',
  fontSize: size.sm,
  color: color.textPrimary,
}

const actionBtnMuted: React.CSSProperties = {
  color: color.textMuted,
  borderStyle: 'dashed',
}

const presetPickerBtn: React.CSSProperties = {
  padding: `${space.sm}px ${space.md}px`,
  border: `1px solid ${color.border}`,
  borderRadius: 6,
  background: color.bgSurface,
  cursor: 'pointer',
  fontSize: size.sm,
  color: color.textPrimary,
}

const presetDropdown: React.CSSProperties = {
  position: 'absolute',
  top: '100%',
  left: 0,
  zIndex: 1000,
  background: color.bgSurface,
  border: `1px solid ${color.border}`,
  borderRadius: radius.sm,
  boxShadow: shadow.elevated,
  maxHeight: 300,
  overflowY: 'auto',
  minWidth: 320,
  marginTop: 2,
}

const presetDropdownItem: React.CSSProperties = {
  padding: `${space.sm}px ${space.md}px`,
  cursor: 'pointer',
  borderBottom: `1px solid ${color.border}`,
}
