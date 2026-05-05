import { useCallback } from 'react'
import type { AcceptanceStep, FieldValue } from '../../store/documentStore'
import { FieldValueEditor } from './FieldValueEditor'
import { StructuredBulletListEditor } from './StructuredBulletListEditor'
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

function createEmptyAcceptanceStep(): AcceptanceStep {
  return {
    heading: emptyField(),
    content: emptyField(),
    bullets: [],
  }
}

export interface AcceptanceStepEditorProps {
  steps: AcceptanceStep[]
  sectionDotPath: string       // "sections.acceptance.steps"
  docId: string
  onStepsChange: (steps: AcceptanceStep[]) => void
}

/**
 * Renders a list of AcceptanceStep entries with editable heading, content, and bullets[].
 * Used by AcceptanceSection.
 *
 * - Edit heading:  dot-path `{sectionDotPath}.{index}.heading.user_input`
 * - Edit content:  dot-path `{sectionDotPath}.{index}.content.user_input`
 * - Edit bullet:   dot-path `{sectionDotPath}.{index}.bullets.{bulletIndex}.user_input`
 * - Add step:      append createEmptyAcceptanceStep(), persist full array
 * - Add bullet:    append empty FieldValue to step.bullets, persist full array
 * - Remove step/bullet: splice, persist full array
 */
export function AcceptanceStepEditor({
  steps, sectionDotPath, docId, onStepsChange,
}: AcceptanceStepEditorProps) {
  const { saveStatus: arraySaveStatus, doSave: doArraySave } = useSaveStatus()

  const handleAddStep = useCallback(() => {
    const updated = [...steps, createEmptyAcceptanceStep()]
    onStepsChange(updated)
    doArraySave(() => saveUserInput(docId, sectionDotPath, updated))
  }, [steps, onStepsChange, doArraySave, docId, sectionDotPath])

  const handleRemoveStep = useCallback((stepIndex: number) => {
    const updated = steps.filter((_, i) => i !== stepIndex)
    onStepsChange(updated)
    doArraySave(() => saveUserInput(docId, sectionDotPath, updated))
  }, [steps, onStepsChange, doArraySave, docId, sectionDotPath])

  const handleAddBullet = useCallback((stepIndex: number) => {
    const updated = steps.map((s, i) => i === stepIndex ? { ...s, bullets: [...s.bullets, { text: emptyField(), level: 1 as const }] } : s)
    onStepsChange(updated)
    doArraySave(() => saveUserInput(docId, sectionDotPath, updated))
  }, [steps, onStepsChange, doArraySave, docId, sectionDotPath])

  const handleHeadingUpdate = useCallback((stepIndex: number, newField: FieldValue) => {
    const updated = steps.map((s, i) =>
      i === stepIndex ? { ...s, heading: newField } : s,
    )
    onStepsChange(updated)
  }, [steps, onStepsChange])

  const handleContentUpdate = useCallback((stepIndex: number, newField: FieldValue) => {
    const updated = steps.map((s, i) =>
      i === stepIndex ? { ...s, content: newField } : s,
    )
    onStepsChange(updated)
  }, [steps, onStepsChange])

  const handleBulletsChange = useCallback((stepIndex: number, bullets: AcceptanceStep['bullets']) => {
    const updated = steps.map((s, i) =>
      i === stepIndex ? { ...s, bullets } : s,
    )
    onStepsChange(updated)
  }, [steps, onStepsChange])

  return (
    <div>
      {steps.map((step, stepIndex) => (
        <div key={stepIndex} style={stepCard}>
          <div style={stepHeader}>
            <span style={stepLabel}>Step {stepIndex + 1}</span>
            <button
              onClick={() => handleRemoveStep(stepIndex)}
              style={removeBtnStyle}
              title="단계 삭제"
            >
              ✕
            </button>
          </div>

          <div style={fieldRow}>
            <span style={fieldLabel}>제목</span>
            <FieldValueEditor
              field={step.heading}
              dotPath={`${sectionDotPath}.${stepIndex}.heading.user_input`}
              docId={docId}
              placeholder="단계 제목"
              onLocalUpdate={(newField) => handleHeadingUpdate(stepIndex, newField)}
            />
          </div>

          <div style={fieldRow}>
            <span style={fieldLabel}>내용</span>
            <FieldValueEditor
              field={step.content}
              dotPath={`${sectionDotPath}.${stepIndex}.content.user_input`}
              docId={docId}
              placeholder="단계 내용"
              multiline
              onLocalUpdate={(newField) => handleContentUpdate(stepIndex, newField)}
            />
          </div>

          <div style={bulletsContainer}>
            <span style={fieldLabel}>항목</span>
            <StructuredBulletListEditor
              items={step.bullets ?? []}
              listDotPath={`${sectionDotPath}.${stepIndex}.bullets`}
              docId={docId}
              placeholder="항목 입력"
              onItemsChange={(bullets) => handleBulletsChange(stepIndex, bullets)}
            />
            <button
              onClick={() => handleAddBullet(stepIndex)}
              style={{ display: 'none' }}
            >
              + 항목 추가
            </button>
          </div>
        </div>
      ))}

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
        <button onClick={handleAddStep} style={addStepBtn}>
          + 단계 추가
        </button>
        <SaveStatusIndicator status={arraySaveStatus} />
      </div>
    </div>
  )
}

const stepCard: React.CSSProperties = {
  marginBottom: 16,
  padding: 12,
  border: `1px solid ${color.border}`,
  borderRadius: 8,
  background: color.bgSurface,
}

const stepHeader: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  marginBottom: 8,
}

const stepLabel: React.CSSProperties = {
  fontWeight: 600,
  fontSize: 14,
  color: color.textPrimary,
}

const fieldRow: React.CSSProperties = {
  display: 'flex',
  alignItems: 'flex-start',
  gap: 8,
  marginBottom: 6,
}

const fieldLabel: React.CSSProperties = {
  fontSize: 12,
  color: color.textMuted,
  minWidth: 36,
  paddingTop: 4,
}

const bulletsContainer: React.CSSProperties = {
  paddingLeft: 0,
  marginTop: 4,
}

const removeBtnStyle: React.CSSProperties = {
  background: 'none',
  border: 'none',
  cursor: 'pointer',
  color: color.textMuted,
  fontSize: 14,
  padding: '2px 4px',
}

const addStepBtn: React.CSSProperties = {
  background: 'none',
  border: `1px dashed ${color.border}`,
  borderRadius: 4,
  padding: '6px 14px',
  cursor: 'pointer',
  color: color.textSecondary,
  fontSize: 12,
}
