import { useCallback } from 'react'
import { useDocumentStore, type SuccessCriteriaSection as SuccessCriteriaModel, type CategoryGroup } from '../../store/documentStore'
import { useSessionStore } from '../../store/sessionStore'
import { CategoryGroupEditor } from '../editors/CategoryGroupEditor'
import { useDocLang } from '../LangContext'
import { color } from '../../styles/tokens'

export function SuccessCriteriaSection() {
  const lang = useDocLang()
  const koData = useDocumentStore(s => s.sections?.success_criteria) as SuccessCriteriaModel | undefined
  const enData = useDocumentStore(s => s.sections_en?.success_criteria) as SuccessCriteriaModel | undefined
  const sectionData = lang === 'en' ? enData : koData
  const setDocument = useDocumentStore(s => s.setDocument)
  const docId = useSessionStore(s => s.currentDocId) || ''

  const handleGroupsChange = useCallback((groups: CategoryGroup[]) => {
    const sections = useDocumentStore.getState().sections || {}
    const current = (sections.success_criteria || {}) as SuccessCriteriaModel
    const updated = { ...current, groups }
    setDocument({ sections: { ...sections, success_criteria: updated } } as any)
  }, [setDocument])

  const groups = sectionData?.groups ?? []

  if (groups.length === 0) {
    return (
      <div>
        <h2 style={{ marginBottom: 16 }}>Success Criteria / KPIs</h2>
        <p style={{ color: color.textMuted }}>
          성공 기준이 아직 정의되지 않았습니다. 채팅에서 "Success Criteria 작성해줘"라고 요청하거나 아래에서 직접 추가하세요.
        </p>
        <CategoryGroupEditor
          groups={[]}
          sectionDotPath="sections.success_criteria.groups"
          docId={docId}
          onGroupsChange={handleGroupsChange}
        />
      </div>
    )
  }

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>Success Criteria / KPIs</h2>
      <CategoryGroupEditor
        groups={groups}
        sectionDotPath="sections.success_criteria.groups"
        docId={docId}
        onGroupsChange={handleGroupsChange}
      />
    </div>
  )
}
