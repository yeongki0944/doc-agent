import { useCallback } from 'react'
import { useDocumentStore, type AcceptanceSectionData, type AcceptanceStep } from '../../store/documentStore'
import { useSessionStore } from '../../store/sessionStore'
import { AcceptanceStepEditor } from '../editors/AcceptanceStepEditor'
import { useDocLang } from '../LangContext'
import { color } from '../../styles/tokens'
import { SectionGuideButton } from '../SectionGuideButton'
import { ACCEPTANCE_STEP_PRESETS, presetToFieldValue } from '../../constants/documentPresets'
import { saveUserInput } from '../../utils/api'

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

  const handleApplyStandardProcess = useCallback(() => {
    const presetSteps: AcceptanceStep[] = ACCEPTANCE_STEP_PRESETS.map(preset => ({
      heading: presetToFieldValue(preset.heading),
      content: presetToFieldValue(preset.content),
      bullets: preset.bullets.map(bullet => ({ text: presetToFieldValue(bullet), level: 1 as const })),
    }))
    const sections = useDocumentStore.getState().sections || {}
    const current = (sections.acceptance || {}) as AcceptanceSectionData
    const currentSteps = current.steps ?? []
    const updatedSteps = [...currentSteps, ...presetSteps]
    const updated = { ...current, steps: updatedSteps }
    setDocument({ sections: { ...sections, acceptance: updated } } as any)
    saveUserInput(docId, 'sections.acceptance.steps', updatedSteps)
  }, [setDocument, docId])

  const steps = sectionData?.steps ?? []

  if (steps.length === 0) {
    return (
      <div>
        <h2 style={{ marginBottom: 16 }}>6. Acceptance <SectionGuideButton sectionKey="acceptance" /></h2>
        <p style={{ color: color.textMuted, marginBottom: 12 }}>
          인수 기준이 아직 정의되지 않았습니다.
        </p>
        <p style={{ color: color.textMuted, fontSize: 13, marginBottom: 16 }}>
          자주 사용하는 형식을 선택하여 시작하거나, 직접 입력할 수 있습니다.
        </p>
        <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
          <button type="button" onClick={handleApplyStandardProcess} style={presetActionBtn}>
            표준 인수 프로세스 적용
          </button>
          <button type="button" onClick={() => {
            handleStepsChange([{
              heading: { user_input: null, ai_recommended: null, calculated: null, status: 'empty', user_edited: false },
              content: { user_input: null, ai_recommended: null, calculated: null, status: 'empty', user_edited: false },
              bullets: [],
            }])
          }} style={secondaryActionBtn}>
            직접 단계 추가
          </button>
          <span style={{ fontSize: 12, color: color.textMuted, alignSelf: 'center' }}>
            AI 요청 예시: Acceptance Criteria 초안 작성해줘
          </span>
        </div>
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
        <h2 style={{ marginBottom: 16 }}>6. Acceptance <SectionGuideButton sectionKey="acceptance" /></h2>
      <div style={{ marginBottom: 12 }}>
        <button type="button" onClick={handleApplyStandardProcess} style={presetActionBtn}>
          표준 인수 프로세스 적용
        </button>
      </div>
      <AcceptanceStepEditor
        steps={steps}
        sectionDotPath="sections.acceptance.steps"
        docId={docId}
        onStepsChange={handleStepsChange}
      />
    </div>
  )
}

const presetActionBtn: React.CSSProperties = {
  background: color.bgSubtle,
  border: `1px solid ${color.border}`,
  borderRadius: 6,
  padding: '6px 14px',
  cursor: 'pointer',
  color: color.textPrimary,
  fontSize: 12,
  fontWeight: 600,
}

const secondaryActionBtn: React.CSSProperties = {
  background: 'none',
  border: `1px dashed ${color.border}`,
  borderRadius: 6,
  padding: '6px 14px',
  cursor: 'pointer',
  color: color.textSecondary,
  fontSize: 12,
}
