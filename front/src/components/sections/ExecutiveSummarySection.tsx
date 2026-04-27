import { useCallback } from 'react'
import { useDocumentStore, createFieldValue, type ExecutiveSummarySection as ExecutiveSummaryModel, type FieldValue } from '../../store/documentStore'
import { useSessionStore } from '../../store/sessionStore'
import { EditableField } from '../EditableField'
import { saveUserInput } from '../../utils/api'
import { emitUserEdit } from '../../utils/userEditEvent'
import { useDocLang } from '../LangContext'
import { color } from '../../styles/tokens'
import { isAiRecommended, resolveFieldValue } from '../AiBadge'

function resolve(value: FieldValue | undefined | null) {
  return resolveFieldValue(value) ?? ''
}

function toLines(value: any): string[] {
  if (Array.isArray(value)) {
    return value.map(item => String(resolveFieldValue(item) ?? '')).filter(Boolean)
  }
  const text = String(resolveFieldValue(value) ?? '')
  return text.split('\n').map(line => line.trim()).filter(Boolean)
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
    resolve(sectionData.business_case?.problem_definition) ||
    resolve(sectionData.business_case?.roi_calculation) ||
    resolve(sectionData.business_case?.executive_sponsor) ||
    resolve(sectionData.business_case?.production_commitment)
  ))

  const updateField = useCallback((field: keyof ExecutiveSummaryModel | `business_case.${string}`, newValue: string) => {
    const sections = useDocumentStore.getState().sections || {}
    const current = (sections.executive_summary || {}) as ExecutiveSummaryModel
    const updated = { ...current }
    let oldValue = ''

    if (field === 'phases_overview') {
      oldValue = toLines(current.phases_overview).join('\n')
      const phases = toLines(newValue).map(line => createFieldValue(line, null, null, 'user_modified'))
      updated.phases_overview = phases
      setDocument({ sections: { ...sections, executive_summary: updated } } as any)
      saveUserInput(docId, 'sections.executive_summary.phases_overview.user_input', toLines(newValue)).catch(() => {})
      emitUserEdit('Executive Summary', 'phases_overview', oldValue, newValue)
      return
    }

    if (field.startsWith('business_case.')) {
      const key = field.split('.')[1] as keyof ExecutiveSummaryModel['business_case']
      oldValue = resolve(current.business_case?.[key] as FieldValue)
      updated.business_case = {
        ...current.business_case,
        [key]: createFieldValue(newValue, null, null, 'user_modified'),
      }
      setDocument({ sections: { ...sections, executive_summary: updated } } as any)
      saveUserInput(docId, `sections.executive_summary.business_case.${key}.user_input`, newValue).catch(() => {})
      emitUserEdit('Executive Summary', key, oldValue, newValue)
      return
    }

    oldValue = resolve(current[field as keyof ExecutiveSummaryModel] as FieldValue)
    ;(updated as any)[field] = createFieldValue(newValue, null, null, 'user_modified')
    setDocument({ sections: { ...sections, executive_summary: updated } } as any)
    saveUserInput(docId, `sections.executive_summary.${field}.user_input`, newValue).catch(() => {})
    emitUserEdit('Executive Summary', field, oldValue, newValue)
  }, [docId, setDocument])

  if (!hasContent) {
    return (
      <div>
        <h2 style={{ marginBottom: 16 }}>Executive Summary</h2>
        <p style={{ color: color.textMuted }}>프로젝트 개요가 아직 입력되지 않았습니다. 채팅에서 "Overview 작성해줘"라고 요청하세요.</p>
      </div>
    )
  }

  const executiveSummary = sectionData || ({} as ExecutiveSummaryModel)

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>Executive Summary</h2>
      <div style={grid}>
        <SummaryCard
          title="Customer Intro"
          field={executiveSummary.customer_intro}
          multiline
          onSave={v => updateField('customer_intro', v)}
        />
        <SummaryCard
          title="Problem Statement"
          field={executiveSummary.problem_statement}
          multiline
          onSave={v => updateField('problem_statement', v)}
        />
        <SummaryCard
          title="Proposed Solution"
          field={executiveSummary.proposed_solution}
          multiline
          onSave={v => updateField('proposed_solution', v)}
        />
        <SummaryCard
          title="Phases Overview"
          field={executiveSummary.phases_overview}
          multiline
          onSave={v => updateField('phases_overview', v)}
        />
      </div>

      <div style={{ marginTop: 16, padding: 16, border: `1px solid ${color.border}`, borderRadius: 8, background: color.bgPrimary }}>
        <h3 style={{ marginTop: 0, marginBottom: 12 }}>Business Case</h3>
        <div style={businessGrid}>
          <SummaryCard title="Problem Definition" field={executiveSummary.business_case?.problem_definition} multiline onSave={v => updateField('business_case.problem_definition', v)} />
          <SummaryCard title="ROI Calculation" field={executiveSummary.business_case?.roi_calculation} multiline onSave={v => updateField('business_case.roi_calculation', v)} />
          <SummaryCard title="Executive Sponsor" field={executiveSummary.business_case?.executive_sponsor} onSave={v => updateField('business_case.executive_sponsor', v)} />
          <SummaryCard title="Production Commitment" field={executiveSummary.business_case?.production_commitment} multiline onSave={v => updateField('business_case.production_commitment', v)} />
        </div>
      </div>
    </div>
  )
}

function SummaryCard({
  title,
  field,
  onSave,
  multiline = false,
}: {
  title: string
  field: FieldValue | FieldValue[] | undefined | null
  onSave: (value: string) => void
  multiline?: boolean
}) {
  const value = Array.isArray(field) ? toLines(field).join('\n') : resolve(field as FieldValue | undefined | null)
  const isAi = !Array.isArray(field) && isAiRecommended(field as FieldValue | undefined | null)

  return (
    <div style={card}>
      <div style={cardTitle}>{title}</div>
      <EditableField
        value={String(value ?? '')}
        isAi={isAi}
        onSave={onSave}
        multiline={multiline}
        placeholder={`${title} 입력`}
      />
    </div>
  )
}

const grid: React.CSSProperties = {
  display: 'grid',
  gap: 12,
  gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
}

const businessGrid: React.CSSProperties = {
  display: 'grid',
  gap: 12,
  gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
}

const card: React.CSSProperties = {
  padding: 12,
  borderRadius: 8,
  border: `1px solid ${color.border}`,
  background: color.bgSurface,
}

const cardTitle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 700,
  color: color.textMuted,
  marginBottom: 8,
}
