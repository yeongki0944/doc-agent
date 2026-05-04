import { useCallback, useState } from 'react'
import { useDocumentStore, type ExecutiveSummarySection as ExecutiveSummaryModel, type FieldValue } from '../../store/documentStore'
import { useSessionStore } from '../../store/sessionStore'
import { FieldValueEditor } from '../editors/FieldValueEditor'
import { ListEditor } from '../editors/ListEditor'
import { SectionGuideButton } from '../SectionGuideButton'
import { useDocLang } from '../LangContext'
import { color, font, size, space, radius } from '../../styles/tokens'
import { resolveFieldValue } from '../AiBadge'
import { saveUserInput } from '../../utils/api'
import { useSaveStatus } from '../../hooks/useSaveStatus'
import {
  EXEC_SUMMARY_STARTER_BLOCKS,
  PAIN_POINT_PRESETS,
  POC_OBJECTIVE_PRESETS,
  presetToFieldValue,
} from '../../constants/documentPresets'

function resolve(value: FieldValue | undefined | null) {
  return resolveFieldValue(value) ?? ''
}

export function ExecutiveSummarySection() {
  const lang = useDocLang()
  const koData = useDocumentStore(s => s.sections?.executive_summary) as ExecutiveSummaryModel | undefined
  const enData = useDocumentStore(s => s.sections_en?.executive_summary) as ExecutiveSummaryModel | undefined
  const sectionData = lang === 'en' ? enData : koData
  const setDocument = useDocumentStore(s => s.setDocument)
  const docId = useSessionStore(s => s.currentDocId) || ''

  const hasContent = Boolean(sectionData && (
    resolve(sectionData.customer_intro) ||
    resolve(sectionData.problem_statement) ||
    resolve(sectionData.proposed_solution) ||
    (sectionData.phases_overview?.length ?? 0) > 0 ||
    (sectionData.current_pain_points?.length ?? 0) > 0 ||
    (sectionData.poc_objectives?.length ?? 0) > 0 ||
    resolve(sectionData.business_case?.problem_definition) ||
    resolve(sectionData.business_case?.roi_calculation) ||
    resolve(sectionData.business_case?.executive_sponsor) ||
    resolve(sectionData.business_case?.production_commitment)
  ))

  const updateScalarField = useCallback((field: keyof ExecutiveSummaryModel) => (newField: FieldValue) => {
    const sections = useDocumentStore.getState().sections || {}
    const current = (sections.executive_summary || {}) as ExecutiveSummaryModel
    const updated = { ...current, [field]: newField }
    setDocument({ sections: { ...sections, executive_summary: updated } } as any)
  }, [setDocument])

  const updateBusinessCaseField = useCallback((key: keyof ExecutiveSummaryModel['business_case']) => (newField: FieldValue) => {
    const sections = useDocumentStore.getState().sections || {}
    const current = (sections.executive_summary || {}) as ExecutiveSummaryModel
    const updated = {
      ...current,
      business_case: {
        ...current.business_case,
        [key]: newField,
      },
    }
    setDocument({ sections: { ...sections, executive_summary: updated } } as any)
  }, [setDocument])

  const updateListField = useCallback((field: 'phases_overview' | 'current_pain_points' | 'poc_objectives') => (items: FieldValue[]) => {
    const sections = useDocumentStore.getState().sections || {}
    const current = (sections.executive_summary || {}) as ExecutiveSummaryModel
    const updated = { ...current, [field]: items }
    setDocument({ sections: { ...sections, executive_summary: updated } } as any)
  }, [setDocument])

  const handleStartDirectInput = useCallback(() => {
    // Initialize the section with empty fields so the user can start typing
    const sections = useDocumentStore.getState().sections || {}
    const emptyField = (): FieldValue => ({ user_input: null, ai_recommended: null, calculated: null, status: 'empty', user_edited: false })
    const initial: ExecutiveSummaryModel = {
      customer_intro: emptyField(),
      problem_statement: emptyField(),
      proposed_solution: emptyField(),
      phases_overview: [],
      current_pain_points: [],
      poc_objectives: [],
      business_case: {
        problem_definition: emptyField(),
        roi_calculation: emptyField(),
        executive_sponsor: emptyField(),
        production_commitment: emptyField(),
      },
      custom_blocks: [],
    }
    setDocument({ sections: { ...sections, executive_summary: initial } } as any)
  }, [setDocument])

  if (!hasContent) {
    return (
      <div>
        <h2 style={{ marginBottom: space.lg, fontSize: size.lg, fontWeight: 600, fontFamily: font.heading, display: 'flex', alignItems: 'center', gap: space.xs }}>
          2.1 Executive Summary
          <SectionGuideButton sectionKey="executive_summary" />
        </h2>
        <EmptyState onStartDirectInput={handleStartDirectInput} />
      </div>
    )
  }

  const es = sectionData || ({} as ExecutiveSummaryModel)

  return (
    <div>
      <h2 style={{ marginBottom: space.lg, fontSize: size.lg, fontWeight: 600, fontFamily: font.heading, display: 'flex', alignItems: 'center', gap: space.xs }}>
        2.1 Executive Summary
        <SectionGuideButton sectionKey="executive_summary" />
      </h2>

      {/* Scalar fields */}
      <div style={grid}>
        <FieldCard title="Customer Intro">
          <FieldValueEditor
            field={es.customer_intro}
            dotPath="sections.executive_summary.customer_intro.user_input"
            docId={docId}
            placeholder="Customer Intro 입력"
            multiline
            onLocalUpdate={updateScalarField('customer_intro')}
          />
        </FieldCard>
        <FieldCard title="Problem Statement">
          <FieldValueEditor
            field={es.problem_statement}
            dotPath="sections.executive_summary.problem_statement.user_input"
            docId={docId}
            placeholder="Problem Statement 입력"
            multiline
            onLocalUpdate={updateScalarField('problem_statement')}
          />
        </FieldCard>
        <FieldCard title="Proposed Solution">
          <FieldValueEditor
            field={es.proposed_solution}
            dotPath="sections.executive_summary.proposed_solution.user_input"
            docId={docId}
            placeholder="Proposed Solution 입력"
            multiline
            onLocalUpdate={updateScalarField('proposed_solution')}
          />
        </FieldCard>
      </div>

      {/* List fields */}
      <div style={{ marginTop: space.lg }}>
        <FieldCard title="Phases Overview">
          <ListEditor
            items={es.phases_overview ?? []}
            listDotPath="sections.executive_summary.phases_overview"
            docId={docId}
            onItemsChange={updateListField('phases_overview')}
            placeholder="Phase 입력"
          />
        </FieldCard>
      </div>

      <div style={{ marginTop: space.md, display: 'grid', gap: space.md, gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' }}>
        <FieldCard title="Current Pain Points">
          <ListEditor
            items={es.current_pain_points ?? []}
            listDotPath="sections.executive_summary.current_pain_points"
            docId={docId}
            onItemsChange={updateListField('current_pain_points')}
            placeholder="Pain point 입력"
          />
          <PresetPicker
            presets={PAIN_POINT_PRESETS}
            currentItems={es.current_pain_points ?? []}
            listDotPath="sections.executive_summary.current_pain_points"
            docId={docId}
            onItemsChange={updateListField('current_pain_points')}
          />
        </FieldCard>
        <FieldCard title="PoC Objectives">
          <ListEditor
            items={es.poc_objectives ?? []}
            listDotPath="sections.executive_summary.poc_objectives"
            docId={docId}
            onItemsChange={updateListField('poc_objectives')}
            placeholder="Objective 입력"
          />
          <PresetPicker
            presets={POC_OBJECTIVE_PRESETS}
            currentItems={es.poc_objectives ?? []}
            listDotPath="sections.executive_summary.poc_objectives"
            docId={docId}
            onItemsChange={updateListField('poc_objectives')}
          />
        </FieldCard>
      </div>

      {/* Business Case */}
      <div style={{ marginTop: space.lg, padding: space.lg, border: `1px solid ${color.border}`, borderRadius: 8, background: color.bgPrimary }}>
        <h3 style={{ marginTop: 0, marginBottom: space.md }}>Business Case</h3>
        <div style={businessGrid}>
          <FieldCard title="Problem Definition">
            <FieldValueEditor
              field={es.business_case?.problem_definition}
              dotPath="sections.executive_summary.business_case.problem_definition.user_input"
              docId={docId}
              placeholder="Problem Definition 입력"
              multiline
              onLocalUpdate={updateBusinessCaseField('problem_definition')}
            />
          </FieldCard>
          <FieldCard title="ROI Calculation">
            <FieldValueEditor
              field={es.business_case?.roi_calculation}
              dotPath="sections.executive_summary.business_case.roi_calculation.user_input"
              docId={docId}
              placeholder="ROI Calculation 입력"
              multiline
              onLocalUpdate={updateBusinessCaseField('roi_calculation')}
            />
          </FieldCard>
          <FieldCard title="Executive Sponsor">
            <FieldValueEditor
              field={es.business_case?.executive_sponsor}
              dotPath="sections.executive_summary.business_case.executive_sponsor.user_input"
              docId={docId}
              placeholder="Executive Sponsor 입력"
              onLocalUpdate={updateBusinessCaseField('executive_sponsor')}
            />
          </FieldCard>
          <FieldCard title="Production Commitment">
            <FieldValueEditor
              field={es.business_case?.production_commitment}
              dotPath="sections.executive_summary.business_case.production_commitment.user_input"
              docId={docId}
              placeholder="Production Commitment 입력"
              multiline
              onLocalUpdate={updateBusinessCaseField('production_commitment')}
            />
          </FieldCard>
        </div>
      </div>
    </div>
  )
}

/* --- Empty State --- */

function EmptyState({ onStartDirectInput }: { onStartDirectInput: () => void }) {
  const [showStarters, setShowStarters] = useState(false)

  return (
    <div style={emptyContainer}>
      <p style={emptyMainText}>
        Executive Summary가 아직 입력되지 않았습니다. 오른쪽 문서에서 직접 입력하거나, 왼쪽 채팅에서 AI에게 작성을 요청할 수 있습니다.
      </p>
      <p style={emptyHintText}>
        예: 고객사의 현재 과제, PoC 목표, 제안 솔루션을 입력하세요.
      </p>
      <p style={emptyAiHint}>
        AI 요청 예시: Executive Summary 초안 작성해줘
      </p>

      <div style={actionRow}>
        <button style={actionBtn} onClick={() => setShowStarters(prev => !prev)}>
          📋 Starter Block 프리셋
        </button>
        <button style={actionBtn} onClick={onStartDirectInput}>
          ✏️ 직접 입력
        </button>
        <button style={{ ...actionBtn, ...actionBtnMuted }}>
          🤖 AI에게 초안 요청
        </button>
      </div>

      {showStarters && (
        <div style={starterGrid}>
          {EXEC_SUMMARY_STARTER_BLOCKS.map((block, idx) => (
            <button
              key={idx}
              type="button"
              onClick={onStartDirectInput}
              style={starterChipBtn}
              onMouseEnter={e => {
                (e.currentTarget as HTMLButtonElement).style.background = color.bgSubtle
                ;(e.currentTarget as HTMLButtonElement).style.borderColor = color.textMuted
              }}
              onMouseLeave={e => {
                (e.currentTarget as HTMLButtonElement).style.background = color.bgSurface
                ;(e.currentTarget as HTMLButtonElement).style.borderColor = color.border
              }}
            >
              {block}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

/* --- Preset Picker for list fields --- */

function PresetPicker({ presets, currentItems, listDotPath, docId, onItemsChange }: {
  presets: readonly string[]
  currentItems: FieldValue[]
  listDotPath: string
  docId: string
  onItemsChange: (items: FieldValue[]) => void
}) {
  const [open, setOpen] = useState(false)
  const { saveStatus, doSave } = useSaveStatus()

  const handleSelect = (preset: string) => {
    const newItem = presetToFieldValue(preset)
    const updated = [...currentItems, newItem]
    onItemsChange(updated)
    doSave(() => saveUserInput(docId, listDotPath, updated))
    setOpen(false)
  }

  return (
    <div style={{ marginTop: space.xs, position: 'relative' }}>
      <button
        onClick={() => setOpen(prev => !prev)}
        style={presetPickerBtn}
      >
        + 프리셋 추가
      </button>
      {open && (
        <div style={presetDropdown}>
          {presets.map((preset, idx) => (
            <div
              key={idx}
              onClick={() => handleSelect(preset)}
              style={presetDropdownItem}
              onMouseEnter={e => { (e.currentTarget as HTMLDivElement).style.background = color.bgSubtle }}
              onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.background = 'transparent' }}
            >
              {preset}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/* --- Shared sub-components --- */

function FieldCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={card}>
      <div style={cardTitle}>{title}</div>
      {children}
    </div>
  )
}

/* --- Styles --- */

const grid: React.CSSProperties = {
  display: 'grid',
  gap: space.md,
  gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
}

const businessGrid: React.CSSProperties = {
  display: 'grid',
  gap: space.md,
  gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
}

const card: React.CSSProperties = {
  padding: space.md,
  borderRadius: 8,
  border: `1px solid ${color.border}`,
  background: color.bgSurface,
}

const cardTitle: React.CSSProperties = {
  fontSize: size.sm,
  fontWeight: 700,
  color: color.textMuted,
  marginBottom: space.sm,
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
  marginBottom: space.sm,
}

const emptyHintText: React.CSSProperties = {
  color: color.textMuted,
  fontSize: size.sm,
  marginBottom: space.xs,
}

const emptyAiHint: React.CSSProperties = {
  color: color.info,
  fontSize: size.sm,
  fontStyle: 'italic',
  marginBottom: space.lg,
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

const starterGrid: React.CSSProperties = {
  display: 'flex',
  flexWrap: 'wrap',
  gap: space.sm,
  marginTop: space.md,
  justifyContent: 'center',
}

const starterChip: React.CSSProperties = {
  padding: `${space.xs}px ${space.sm}px`,
  border: `1px solid ${color.border}`,
  borderRadius: 16,
  background: color.bgSurface,
  fontSize: size.xs,
  color: color.textSecondary,
  cursor: 'default',
}

const starterChipBtn: React.CSSProperties = {
  padding: `${space.xs}px ${space.sm}px`,
  border: `1px solid ${color.border}`,
  borderRadius: 16,
  background: color.bgSurface,
  fontSize: size.xs,
  color: color.textSecondary,
  cursor: 'pointer',
  fontFamily: 'inherit',
  lineHeight: 1.4,
  transition: 'background 0.15s, border-color 0.15s',
}

const presetPickerBtn: React.CSSProperties = {
  background: 'none',
  border: `1px dashed ${color.border}`,
  borderRadius: 4,
  padding: `${space.xs}px ${space.sm}px`,
  cursor: 'pointer',
  color: color.info,
  fontSize: size.xs,
}

const presetDropdown: React.CSSProperties = {
  position: 'absolute',
  top: '100%',
  left: 0,
  zIndex: 1000,
  background: color.bgSurface,
  border: `1px solid ${color.border}`,
  borderRadius: 6,
  boxShadow: '0 4px 12px rgba(10,37,64,0.08)',
  maxHeight: 200,
  overflowY: 'auto',
  minWidth: 280,
  marginTop: 2,
}

const presetDropdownItem: React.CSSProperties = {
  padding: `${space.xs}px ${space.sm}px`,
  cursor: 'pointer',
  fontSize: size.sm,
  color: color.textPrimary,
  lineHeight: 1.6,
}
