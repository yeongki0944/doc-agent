import { useCallback } from 'react'
import type { CategoryGroup, FieldValue } from '../../store/documentStore'
import { FieldValueEditor } from './FieldValueEditor'
import { StructuredBulletListEditor, createStructuredBullet } from './StructuredBulletListEditor'
import { SaveStatusIndicator } from '../SaveStatusIndicator'
import { useSaveStatus } from '../../hooks/useSaveStatus'
import { saveUserInput } from '../../utils/api'
import { color } from '../../styles/tokens'

const emptyField = (): FieldValue => ({
  user_input: null,
  ai_recommended: null,
  calculated: null,
  status: 'empty',
  user_edited: false,
})

function createEmptyCategoryGroup(): CategoryGroup {
  return {
    category_name: emptyField(),
    bullets: [],
  }
}

export interface CategoryGroupEditorProps {
  groups: CategoryGroup[]
  sectionDotPath: string       // e.g. "sections.success_criteria.groups"
  docId: string
  onGroupsChange: (groups: CategoryGroup[]) => void  // Zustand updater
}

/**
 * Renders a list of CategoryGroup entries with editable category_name and StructuredBullet[].
 *
 * - Edit category_name: dot-path `{sectionDotPath}.{groupIndex}.category_name.user_input`
 * - Edit bullet: dot-path `{sectionDotPath}.{groupIndex}.bullets.{bulletIndex}.user_input`
 * - Add bullet: append empty FieldValue, persist full groups array to sectionDotPath
 * - Add group: append createEmptyCategoryGroup(), persist full groups array
 * - Remove group/bullet: splice, persist full groups array
 */
export function CategoryGroupEditor({
  groups, sectionDotPath, docId, onGroupsChange,
}: CategoryGroupEditorProps) {
  const { saveStatus: arraySaveStatus, doSave: doArraySave } = useSaveStatus()

  const handleAddGroup = useCallback(() => {
    const updated = [...groups, createEmptyCategoryGroup()]
    onGroupsChange(updated)
    doArraySave(() => saveUserInput(docId, sectionDotPath, updated))
  }, [groups, onGroupsChange, doArraySave, docId, sectionDotPath])

  const handleRemoveGroup = useCallback((groupIndex: number) => {
    const updated = groups.filter((_, i) => i !== groupIndex)
    onGroupsChange(updated)
    doArraySave(() => saveUserInput(docId, sectionDotPath, updated))
  }, [groups, onGroupsChange, doArraySave, docId, sectionDotPath])

  const handleAddBullet = useCallback((groupIndex: number) => {
    const updated = groups.map((g, i) =>
      i === groupIndex ? { ...g, bullets: [...g.bullets, createStructuredBullet()] } : g,
    )
    onGroupsChange(updated)
    doArraySave(() => saveUserInput(docId, sectionDotPath, updated))
  }, [groups, onGroupsChange, doArraySave, docId, sectionDotPath])

  const handleCategoryNameUpdate = useCallback((groupIndex: number, newField: FieldValue) => {
    const updated = groups.map((g, i) =>
      i === groupIndex ? { ...g, category_name: newField } : g,
    )
    onGroupsChange(updated)
  }, [groups, onGroupsChange])

  const handleBulletsChange = useCallback((groupIndex: number, bullets: CategoryGroup['bullets']) => {
    const updated = groups.map((g, i) =>
      i === groupIndex ? { ...g, bullets } : g,
    )
    onGroupsChange(updated)
  }, [groups, onGroupsChange])

  return (
    <div>
      {groups.map((group, groupIndex) => (
        <div key={groupIndex} style={groupCard}>
          <div style={groupHeader}>
            <span style={groupNumber}>({groupIndex + 1})</span>
            <FieldValueEditor
              field={group.category_name}
              dotPath={`${sectionDotPath}.${groupIndex}.category_name.user_input`}
              docId={docId}
              placeholder="카테고리 이름"
              onLocalUpdate={(newField) => handleCategoryNameUpdate(groupIndex, newField)}
            />
            <button
              onClick={() => handleRemoveGroup(groupIndex)}
              style={removeBtnStyle}
              title="그룹 삭제"
            >
              ✕
            </button>
          </div>

          <div style={bulletsContainer}>
            <StructuredBulletListEditor
              items={group.bullets ?? []}
              listDotPath={`${sectionDotPath}.${groupIndex}.bullets`}
              docId={docId}
              placeholder="항목 입력"
              onItemsChange={(bullets) => handleBulletsChange(groupIndex, bullets)}
            />
            <button
              onClick={() => handleAddBullet(groupIndex)}
              style={{ display: 'none' }}
            >
              + 항목 추가
            </button>
          </div>
        </div>
      ))}

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
        <button onClick={handleAddGroup} style={addGroupBtn}>
          + 그룹 추가
        </button>
        <SaveStatusIndicator status={arraySaveStatus} />
      </div>
    </div>
  )
}

const groupCard: React.CSSProperties = {
  marginBottom: 16,
  padding: 12,
  border: `1px solid ${color.border}`,
  borderRadius: 8,
  background: color.bgSurface,
}

const groupHeader: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  gap: 6,
  marginBottom: 8,
  fontWeight: 600,
}

const groupNumber: React.CSSProperties = {
  color: color.textMuted,
  fontSize: 13,
  flexShrink: 0,
}

const bulletsContainer: React.CSSProperties = {
  paddingLeft: 8,
}

const removeBtnStyle: React.CSSProperties = {
  background: 'none',
  border: 'none',
  cursor: 'pointer',
  color: color.textMuted,
  fontSize: 14,
  padding: '2px 4px',
}

const addGroupBtn: React.CSSProperties = {
  background: 'none',
  border: `1px dashed ${color.border}`,
  borderRadius: 4,
  padding: '6px 14px',
  cursor: 'pointer',
  color: color.textSecondary,
  fontSize: 12,
}
