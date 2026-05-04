import { useCallback } from 'react'
import { useDocumentStore, type ExecutiveSummarySection as ExecutiveSummaryModel, type FieldValue } from '../../store/documentStore'
import { useSessionStore } from '../../store/sessionStore'
import { FieldValueEditor } from '../editors/FieldValueEditor'
import { ListEditor } from '../editors/ListEditor'
import { useDocLang } from '../LangContext'
import { color } from '../../styles/tokens'
import { resolveFieldValue } from '../AiBadge'

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

  if (!hasContent) {
    return (
      <div>
        <h2 style={{ marginBottom: 16 }}>Executive Summary</h2>
        <p style={{ color: color.textMuted }}>프로젝트 개요가 아직 입력되지 않았습니다. 채팅에서 "Overview 작성해줘"라고 요청하세요.</p>
      </div>
    )
  }

  const es = sectionData || ({} as ExecutiveSummaryModel)

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>Executive Summary</h2>

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
      <div style={{ marginTop: 16 }}>
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

      <div style={{ marginTop: 12, display: 'grid', gap: 12, gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' }}>
        <FieldCard title="Current Pain Points">
          <ListEditor
            items={es.current_pain_points ?? []}
            listDotPath="sections.executive_summary.current_pain_points"
            docId={docId}
            onItemsChange={updateListField('current_pain_points')}
            placeholder="Pain point 입력"
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
        </FieldCard>
      </div>

      {/* Business Case */}
      <div style={{ marginTop: 16, padding: 16, border: `1px solid ${color.border}`, borderRadius: 8, background: color.bgPrimary }}>
        <h3 style={{ marginTop: 0, marginBottom: 12 }}>Business Case</h3>
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

function FieldCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={card}>
      <div style={cardTitle}>{title}</div>
      {children}
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
