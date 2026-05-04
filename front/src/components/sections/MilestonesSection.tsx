import { useCallback, useMemo } from 'react'
import { useDocumentStore, type MilestonesSectionData, type Phase, type FieldValue } from '../../store/documentStore'
import { useSessionStore } from '../../store/sessionStore'
import { FieldValueEditor } from '../editors/FieldValueEditor'
import { EditableComboField } from '../editors/EditableComboField'
import { SaveStatusIndicator } from '../SaveStatusIndicator'
import { SectionGuideButton } from '../SectionGuideButton'
import { useSaveStatus } from '../../hooks/useSaveStatus'
import { saveUserInput } from '../../utils/api'
import { useDocLang } from '../LangContext'
import { color, font, size, space } from '../../styles/tokens'
import {
  PROJECT_PHASE_PRESETS,
  MILESTONE_DELIVERABLE_PRESETS,
} from '../../constants/documentPresets'

const emptyField = (): FieldValue => ({
  user_input: null,
  ai_recommended: null,
  calculated: null,
  status: 'empty',
  user_edited: false,
})

function createEmptyPhase(): Phase {
  return {
    phase: emptyField(),
    completion_date: emptyField(),
    deliverables: emptyField(),
  }
}

export function MilestonesSection() {
  const lang = useDocLang()
  const koData = useDocumentStore(s => s.sections?.milestones) as MilestonesSectionData | undefined
  const enData = useDocumentStore(s => s.sections_en?.milestones) as MilestonesSectionData | undefined
  const sectionData = lang === 'en' ? enData : koData
  const setDocument = useDocumentStore(s => s.setDocument)
  const docId = useSessionStore(s => s.currentDocId) || ''
  const { saveStatus: arraySaveStatus, doSave: doArraySave } = useSaveStatus()

  const phases: Phase[] = useMemo(() => sectionData?.phases ?? [], [sectionData?.phases])
  const hasContent = phases.length > 0

  // --- Phase field updates (via EditableComboField / FieldValueEditor) ---
  const updatePhaseField = useCallback((index: number, field: keyof Phase) => (newField: FieldValue) => {
    const sections = useDocumentStore.getState().sections || {}
    const current = (sections.milestones || {}) as MilestonesSectionData
    const currentPhases = [...(current.phases ?? [])]
    const oldPhase = currentPhases[index] || createEmptyPhase()
    currentPhases[index] = { ...oldPhase, [field]: newField }
    setDocument({ sections: { ...sections, milestones: { ...current, phases: currentPhases } } } as any)
  }, [setDocument])

  // --- Add/remove phases (persist full array) ---
  const addPhase = useCallback(() => {
    const sections = useDocumentStore.getState().sections || {}
    const current = (sections.milestones || {}) as MilestonesSectionData
    const updated = [...(current.phases ?? []), createEmptyPhase()]
    setDocument({ sections: { ...sections, milestones: { ...current, phases: updated } } } as any)
    doArraySave(() => saveUserInput(docId, 'sections.milestones.phases', updated))
  }, [setDocument, docId, doArraySave])

  const removePhase = useCallback((index: number) => {
    const sections = useDocumentStore.getState().sections || {}
    const current = (sections.milestones || {}) as MilestonesSectionData
    const updated = (current.phases ?? []).filter((_, i) => i !== index)
    setDocument({ sections: { ...sections, milestones: { ...current, phases: updated } } } as any)
    doArraySave(() => saveUserInput(docId, 'sections.milestones.phases', updated))
  }, [setDocument, docId, doArraySave])

  if (!hasContent) {
    return (
      <div>
        <h2 style={headingStyle}>
          2.7 Milestones
          <SectionGuideButton sectionKey="milestones" />
        </h2>
        <div style={emptyContainer}>
          <p style={emptyMainText}>
            마일스톤이 아직 설정되지 않았습니다.
            자주 사용하는 형식을 선택하여 시작하거나, 직접 입력할 수 있습니다.
          </p>
          <div style={actionRow}>
            <button style={actionBtn} onClick={addPhase}>
              ✏️ 직접 행 추가
            </button>
            <button style={{ ...actionBtn, ...actionBtnMuted }}>
              🤖 AI에게 초안 요청
            </button>
          </div>
          <p style={emptyAiHint}>
            AI 요청 예시: Milestones 초안 작성해줘
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12 }}>
          <button type="button" onClick={addPhase} style={addButton}>+ Add Phase</button>
          <SaveStatusIndicator status={arraySaveStatus} />
        </div>
      </div>
    )
  }

  return (
    <div>
      <h2 style={headingStyle}>
        2.7 Milestones
        <SectionGuideButton sectionKey="milestones" />
      </h2>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <button type="button" onClick={addPhase} style={addButton}>+ Add Phase</button>
        <SaveStatusIndicator status={arraySaveStatus} />
      </div>

      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
        <thead>
          <tr style={{ background: color.bgPrimary }}>
            {['Phase', 'Completion Date', 'Deliverables', ''].map(h => (
              <th key={h} style={th}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {phases.map((p, index) => (
            <tr key={index}>
              <td style={td}>
                <EditableComboField
                  field={p.phase}
                  dotPath={`sections.milestones.phases.${index}.phase.user_input`}
                  docId={docId}
                  placeholder="Phase"
                  presets={PROJECT_PHASE_PRESETS}
                  onLocalUpdate={updatePhaseField(index, 'phase')}
                />
              </td>
              <td style={td}>
                <FieldValueEditor
                  field={p.completion_date}
                  dotPath={`sections.milestones.phases.${index}.completion_date.user_input`}
                  docId={docId}
                  placeholder="Completion Date"
                  onLocalUpdate={updatePhaseField(index, 'completion_date')}
                />
              </td>
              <td style={td}>
                <EditableComboField
                  field={p.deliverables}
                  dotPath={`sections.milestones.phases.${index}.deliverables.user_input`}
                  docId={docId}
                  placeholder="Deliverables"
                  multiline
                  presets={MILESTONE_DELIVERABLE_PRESETS}
                  onLocalUpdate={updatePhaseField(index, 'deliverables')}
                />
              </td>
              <td style={td}>
                <button type="button" onClick={() => removePhase(index)} style={deleteButton}>Delete</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
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

const th: React.CSSProperties = { padding: '8px 6px', borderBottom: `2px solid ${color.border}`, textAlign: 'left' }
const td: React.CSSProperties = { padding: '6px', borderBottom: `1px solid ${color.border}`, verticalAlign: 'top' }
const addButton: React.CSSProperties = {
  background: 'none', border: `1px dashed ${color.border}`,
  borderRadius: 4, padding: '4px 10px', cursor: 'pointer',
  color: color.textSecondary, fontSize: 12,
}
const deleteButton: React.CSSProperties = {
  border: 'none', borderRadius: 6, padding: '6px 10px',
  background: '#fee2e2', color: '#b91c1c', cursor: 'pointer', fontWeight: 600,
}
