import { useCallback } from 'react'
import { useDocumentStore, type AssumptionsSection as AssumptionsModel, type CategoryGroup } from '../../store/documentStore'
import { useSessionStore } from '../../store/sessionStore'
import { CategoryGroupEditor } from '../editors/CategoryGroupEditor'
import { useDocLang } from '../LangContext'
import { color } from '../../styles/tokens'

export function AssumptionsSection() {
  const lang = useDocLang()
  const koData = useDocumentStore(s => s.sections?.assumptions) as AssumptionsModel | undefined
  const enData = useDocumentStore(s => s.sections_en?.assumptions) as AssumptionsModel | undefined
  const sectionData = lang === 'en' ? enData : koData
  const setDocument = useDocumentStore(s => s.setDocument)
  const docId = useSessionStore(s => s.currentDocId) || ''

  const handleGroupsChange = useCallback((groups: CategoryGroup[]) => {
    const sections = useDocumentStore.getState().sections || {}
    const current = (sections.assumptions || {}) as AssumptionsModel
    const updated = { ...current, groups }
    setDocument({ sections: { ...sections, assumptions: updated } } as any)
  }, [setDocument])

  const groups = sectionData?.groups ?? []

  if (groups.length === 0) {
    return (
      <div>
        <h2 style={{ marginBottom: 16 }}>Assumptions &amp; Risks</h2>
        <p style={{ color: color.textMuted }}>
          가정 및 리스크가 아직 정의되지 않았습니다. 채팅에서 "Assumptions 작성해줘"라고 요청하거나 아래에서 직접 추가하세요.
        </p>
        <CategoryGroupEditor
          groups={[]}
          sectionDotPath="sections.assumptions.groups"
          docId={docId}
          onGroupsChange={handleGroupsChange}
        />
      </div>
    )
  }

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>Assumptions &amp; Risks</h2>
      <CategoryGroupEditor
        groups={groups}
        sectionDotPath="sections.assumptions.groups"
        docId={docId}
        onGroupsChange={handleGroupsChange}
      />
    </div>
  )
}
