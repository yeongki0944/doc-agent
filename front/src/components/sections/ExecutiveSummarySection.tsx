import { useCallback, useState, useRef, useEffect } from 'react'
import { useDocumentStore, type ExecutiveSummarySection as ExecutiveSummaryModel, type CategoryGroup } from '../../store/documentStore'
import { useSessionStore } from '../../store/sessionStore'
import { CategoryGroupEditor } from '../editors/CategoryGroupEditor'
import { SectionGuideButton } from '../SectionGuideButton'
import { useDocLang } from '../LangContext'
import { color, font, size, space, radius, shadow } from '../../styles/tokens'
import { useSaveStatus } from '../../hooks/useSaveStatus'
import { saveUserInput } from '../../utils/api'
import { EXEC_SUMMARY_PRESET_GROUPS, presetGroupToCategoryGroup } from '../../constants/documentPresets'

const emptyField = () => ({ user_input: null, ai_recommended: null, calculated: null, status: 'empty' as const, user_edited: false })

function createEmptyGroup(): CategoryGroup {
  return { category_name: emptyField(), bullets: [] }
}

export function ExecutiveSummarySection() {
  const lang = useDocLang()
  const koData = useDocumentStore(s => s.sections?.executive_summary) as ExecutiveSummaryModel | undefined
  const enData = useDocumentStore(s => s.sections_en?.executive_summary) as ExecutiveSummaryModel | undefined
  const sectionData = lang === 'en' ? enData : koData
  const setDocument = useDocumentStore(s => s.setDocument)
  const docId = useSessionStore(s => s.currentDocId) || ''
  const { doSave } = useSaveStatus()

  const updateGroups = useCallback((groups: CategoryGroup[]) => {
    const sections = useDocumentStore.getState().sections || {}
    const current = (sections.executive_summary || {}) as ExecutiveSummaryModel
    setDocument({ sections: { ...sections, executive_summary: { ...current, groups } } } as any)
  }, [setDocument])

  const addPresetGroup = useCallback((presetIndex: number) => {
    const preset = EXEC_SUMMARY_PRESET_GROUPS[presetIndex]
    if (!preset) return
    const currentGroups = useDocumentStore.getState().sections?.executive_summary?.groups ?? []
    const updated = [...currentGroups, presetGroupToCategoryGroup(preset)]
    updateGroups(updated)
    doSave(() => saveUserInput(docId, 'sections.executive_summary.groups', updated))
  }, [docId, doSave, updateGroups])

  const addCustomGroup = useCallback(() => {
    const currentGroups = useDocumentStore.getState().sections?.executive_summary?.groups ?? []
    const updated = [...currentGroups, createEmptyGroup()]
    updateGroups(updated)
    doSave(() => saveUserInput(docId, 'sections.executive_summary.groups', updated))
  }, [docId, doSave, updateGroups])

  const groups = sectionData?.groups ?? []

  return (
    <div>
      <h2 style={headingStyle}>
        2.1 Executive Summary
        <SectionGuideButton sectionKey="executive_summary" />
      </h2>
      {groups.length === 0 && (
        <div style={emptyContainer}>
          <p style={emptyMainText}>Executive Summary content is organized as editable groups and bullet items.</p>
          <div style={actionRow}>
            <PresetGroupPicker onSelect={addPresetGroup} />
            <button style={actionBtn} onClick={addCustomGroup}>Custom group</button>
          </div>
        </div>
      )}
      {groups.length > 0 && (
        <div style={{ marginBottom: space.md, display: 'flex', gap: space.sm }}>
          <PresetGroupPicker onSelect={addPresetGroup} />
        </div>
      )}
      <CategoryGroupEditor
        groups={groups}
        sectionDotPath="sections.executive_summary.groups"
        docId={docId}
        onGroupsChange={updateGroups}
      />
    </div>
  )
}

function PresetGroupPicker({ onSelect }: { onSelect: (index: number) => void }) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [open])

  return (
    <div ref={containerRef} style={{ position: 'relative', display: 'inline-block' }}>
      <button style={actionBtn} onClick={() => setOpen(prev => !prev)}>Preset group</button>
      {open && (
        <div style={presetDropdown}>
          {EXEC_SUMMARY_PRESET_GROUPS.map((group, idx) => (
            <div key={idx} onClick={() => { onSelect(idx); setOpen(false) }} style={presetDropdownItem}>
              <div style={{ fontWeight: 600, fontSize: size.sm }}>{group.category_name}</div>
              <div style={{ fontSize: size.xs, color: color.textMuted, marginTop: 2 }}>
                {group.bullets.slice(0, 2).join(', ')}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

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
  marginBottom: space.lg,
}

const emptyMainText: React.CSSProperties = {
  color: color.textSecondary,
  fontSize: size.base,
  lineHeight: 1.6,
  marginBottom: space.md,
}

const actionRow: React.CSSProperties = { display: 'flex', gap: space.sm, flexWrap: 'wrap' }

const actionBtn: React.CSSProperties = {
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
  maxHeight: 320,
  overflowY: 'auto',
  minWidth: 320,
  marginTop: 2,
}

const presetDropdownItem: React.CSSProperties = {
  padding: `${space.sm}px ${space.md}px`,
  cursor: 'pointer',
  borderBottom: `1px solid ${color.border}`,
}
