import { useCallback } from 'react'
import { useDocumentStore, type AcceptanceSectionData, type AcceptanceStep } from '../../store/documentStore'
import { useSessionStore } from '../../store/sessionStore'
import { AcceptanceStepEditor } from '../editors/AcceptanceStepEditor'
import { useDocLang } from '../LangContext'
import { color } from '../../styles/tokens'

export function AcceptanceSection() {
  const lang = useDocLang()
  const koData = useDocumentStore(s => s.sections?.acceptance) as AcceptanceSectionData | undefined
  const enData = useDocumentStore(s => s.sections_en?.acceptance) as AcceptanceSectionData | undefined
  const sectionData = lang === 'en' ? enData : koData
  const setDocument = useDocumentStore(s => s.setDocument)
  const docId = useSessionStore(s => s.currentDocId) || ''

  const handleStepsChange = useCallback((steps: AcceptanceStep[]) => {
    const sections = useDocumentStore.getState().sections || {}
    const current = (sections.acceptance || {}) as AcceptanceSectionData
    const updated = { ...current, steps }
    setDocument({ sections: { ...sections, acceptance: updated } } as any)
  }, [setDocument])

  const steps = sectionData?.steps ?? []

  if (steps.length === 0) {
    return (
      <div>
        <h2 style={{ marginBottom: 16 }}>Acceptance Criteria</h2>
        <p style={{ color: color.textMuted }}>
          인수 기준이 아직 정의되지 않았습니다. 채팅에서 "Acceptance Criteria 작성해줘"라고 요청하거나 아래에서 직접 추가하세요.
        </p>
        <AcceptanceStepEditor
          steps={[]}
          sectionDotPath="sections.acceptance.steps"
          docId={docId}
          onStepsChange={handleStepsChange}
        />
      </div>
    )
  }

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>Acceptance Criteria</h2>
      <AcceptanceStepEditor
        steps={steps}
        sectionDotPath="sections.acceptance.steps"
        docId={docId}
        onStepsChange={handleStepsChange}
      />
    </div>
  )
}
