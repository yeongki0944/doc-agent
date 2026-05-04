import { useCallback, useMemo } from 'react'
import {
  useDocumentStore,
  type ResourcesCostEstimatesSection as RCESectionData,
  type TeamMember,
  type PhaseHours,
  type TotalsRow,
  type FieldValue,
} from '../../store/documentStore'
import { useSessionStore } from '../../store/sessionStore'
import { FieldValueEditor } from '../editors/FieldValueEditor'
import { EditableComboField } from '../editors/EditableComboField'
import { SaveStatusIndicator } from '../SaveStatusIndicator'
import { useSaveStatus } from '../../hooks/useSaveStatus'
import { saveUserInput } from '../../utils/api'
import { resolveFieldValue } from '../AiBadge'
import { useDocLang } from '../LangContext'
import { color } from '../../styles/tokens'
import { SectionGuideButton } from '../SectionGuideButton'
import { RESOURCE_ROLE_PRESETS, RATE_PRESETS, PROJECT_PHASE_PRESETS } from '../../constants/documentPresets'

const emptyField = (): FieldValue => ({
  user_input: null,
  ai_recommended: null,
  calculated: null,
  status: 'empty',
  user_edited: false,
})

function createEmptyTeamMember(): TeamMember {
  return { role: emptyField(), name: emptyField() }
}

// ─── Component ───────────────────────────────────────────────────────────────

export function ResourcesCostEstimatesSection() {
  const lang = useDocLang()
  const koData = useDocumentStore(s => s.sections?.resources_cost_estimates) as RCESectionData | undefined
  const enData = useDocumentStore(s => s.sections_en?.resources_cost_estimates) as RCESectionData | undefined
  const sectionData = lang === 'en' ? enData : koData
  const setDocument = useDocumentStore(s => s.setDocument)
  const docId = useSessionStore(s => s.currentDocId) || ''

  // Save status for array operations (partner_technical_team)
  const { saveStatus: teamSaveStatus, doSave: doTeamSave } = useSaveStatus()

  // Derived data
  const team: TeamMember[] = useMemo(() => sectionData?.partner_technical_team ?? [], [sectionData?.partner_technical_team])
  const phaseRows: PhaseHours[] = useMemo(() => sectionData?.phase_hours_table ?? [], [sectionData?.phase_hours_table])
  const totalHours: TotalsRow | undefined = sectionData?.total_hours
  const totalCost: TotalsRow | undefined = sectionData?.total_cost
  const contribution = sectionData?.contribution

  // ─── Scalar field updates (rates, client signatures) ───────────────────────

  const updateScalarField = useCallback(
    (field: keyof RCESectionData) => (newField: FieldValue) => {
      const sections = useDocumentStore.getState().sections || {}
      const current = (sections.resources_cost_estimates || {}) as RCESectionData
      setDocument({ sections: { ...sections, resources_cost_estimates: { ...current, [field]: newField } } } as any)
    },
    [setDocument],
  )

  // ─── Contribution field updates ────────────────────────────────────────────

  const updateContributionField = useCallback(
    (party: 'customer' | 'partner' | 'aws', field: 'amount' | 'pct') => (newField: FieldValue) => {
      const sections = useDocumentStore.getState().sections || {}
      const current = (sections.resources_cost_estimates || {}) as RCESectionData
      const currentContribution = current.contribution || {
        customer: { amount: emptyField(), pct: emptyField() },
        partner: { amount: emptyField(), pct: emptyField() },
        aws: { amount: emptyField(), pct: emptyField() },
      }
      const updatedParty = { ...currentContribution[party], [field]: newField }
      const updatedContribution = { ...currentContribution, [party]: updatedParty }
      setDocument({
        sections: { ...sections, resources_cost_estimates: { ...current, contribution: updatedContribution } },
      } as any)
    },
    [setDocument],
  )

  // ─── Partner technical team add/remove ─────────────────────────────────────

  const updateTeamMemberField = useCallback(
    (index: number, field: keyof TeamMember) => (newField: FieldValue) => {
      const sections = useDocumentStore.getState().sections || {}
      const current = (sections.resources_cost_estimates || {}) as RCESectionData
      const currentTeam = [...(current.partner_technical_team ?? [])]
      const oldMember = currentTeam[index] || createEmptyTeamMember()
      currentTeam[index] = { ...oldMember, [field]: newField }
      setDocument({ sections: { ...sections, resources_cost_estimates: { ...current, partner_technical_team: currentTeam } } } as any)
    },
    [setDocument],
  )

  const addTeamMember = useCallback(() => {
    const sections = useDocumentStore.getState().sections || {}
    const current = (sections.resources_cost_estimates || {}) as RCESectionData
    const updated = [...(current.partner_technical_team ?? []), createEmptyTeamMember()]
    setDocument({ sections: { ...sections, resources_cost_estimates: { ...current, partner_technical_team: updated } } } as any)
    doTeamSave(() => saveUserInput(docId, 'sections.resources_cost_estimates.partner_technical_team', updated))
  }, [setDocument, docId, doTeamSave])

  const removeTeamMember = useCallback(
    (index: number) => {
      const sections = useDocumentStore.getState().sections || {}
      const current = (sections.resources_cost_estimates || {}) as RCESectionData
      const updated = (current.partner_technical_team ?? []).filter((_, i) => i !== index)
      setDocument({ sections: { ...sections, resources_cost_estimates: { ...current, partner_technical_team: updated } } } as any)
      doTeamSave(() => saveUserInput(docId, 'sections.resources_cost_estimates.partner_technical_team', updated))
    },
    [setDocument, docId, doTeamSave],
  )

  // ─── Phase hours table: phase is editable FieldValue, hours are read-only ──

  const updatePhaseField = useCallback(
    (index: number) => (newField: FieldValue) => {
      const sections = useDocumentStore.getState().sections || {}
      const current = (sections.resources_cost_estimates || {}) as RCESectionData
      const currentRows = [...(current.phase_hours_table ?? [])]
      const oldRow = currentRows[index]
      if (oldRow) {
        currentRows[index] = { ...oldRow, phase: newField }
        setDocument({ sections: { ...sections, resources_cost_estimates: { ...current, phase_hours_table: currentRows } } } as any)
      }
    },
    [setDocument],
  )

  // ─── Render ────────────────────────────────────────────────────────────────

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>2.9 Resources &amp; Cost Estimates <SectionGuideButton sectionKey="resources_cost_estimates" /></h2>

      {/* ── Partner Technical Team ── */}
      <SectionCard title="Partner Technical Team">
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
          <button type="button" onClick={addTeamMember} style={addButton}>+ Add Member</button>
          <SaveStatusIndicator status={teamSaveStatus} />
        </div>

        {team.length > 0 ? (
          <table style={tableStyle}>
            <thead>
              <tr style={{ background: color.bgPrimary }}>
                {['Role', 'Name', ''].map(h => <th key={h} style={th}>{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {team.map((member, index) => (
                <tr key={index}>
                  <td style={td}>
                    <EditableComboField
                      field={member.role}
                      dotPath={`sections.resources_cost_estimates.partner_technical_team.${index}.role.user_input`}
                      docId={docId}
                      placeholder="Role"
                      presets={RESOURCE_ROLE_PRESETS}
                      onLocalUpdate={updateTeamMemberField(index, 'role')}
                    />
                  </td>
                  <td style={td}>
                    <FieldValueEditor
                      field={member.name}
                      dotPath={`sections.resources_cost_estimates.partner_technical_team.${index}.name.user_input`}
                      docId={docId}
                      placeholder="Name"
                      onLocalUpdate={updateTeamMemberField(index, 'name')}
                    />
                  </td>
                  <td style={td}>
                    <button type="button" onClick={() => removeTeamMember(index)} style={deleteButton}>Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p style={emptyText}>팀 멤버가 아직 없습니다. 위 버튼으로 추가하세요.</p>
        )}
      </SectionCard>

      {/* ── Rate Fields ── */}
      <SectionCard title="Rates">
        <FieldRow label="Solution Architect">
          <EditableComboField
            field={sectionData?.rate_solution_architect}
            dotPath="sections.resources_cost_estimates.rate_solution_architect.user_input"
            docId={docId}
            placeholder="Rate (SA)"
            presets={RATE_PRESETS}
            onLocalUpdate={updateScalarField('rate_solution_architect')}
          />
        </FieldRow>
        <FieldRow label="Engineer">
          <EditableComboField
            field={sectionData?.rate_engineer}
            dotPath="sections.resources_cost_estimates.rate_engineer.user_input"
            docId={docId}
            placeholder="Rate (Engineer)"
            presets={RATE_PRESETS}
            onLocalUpdate={updateScalarField('rate_engineer')}
          />
        </FieldRow>
        <FieldRow label="Other">
          <EditableComboField
            field={sectionData?.rate_other}
            dotPath="sections.resources_cost_estimates.rate_other.user_input"
            docId={docId}
            placeholder="Rate (Other)"
            presets={RATE_PRESETS}
            onLocalUpdate={updateScalarField('rate_other')}
          />
        </FieldRow>
      </SectionCard>

      {/* ── Phase Hours Table ── */}
      <SectionCard title="Phase Hours">
        {phaseRows.length > 0 ? (
          <table style={tableStyle}>
            <thead>
              <tr style={{ background: color.bgPrimary }}>
                {['Phase', 'SA Hours', 'Eng Hours', 'Other Hours', 'Total'].map(h => (
                  <th key={h} style={th}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {phaseRows.map((row, index) => (
                <tr key={index}>
                  <td style={td}>
                    <EditableComboField
                      field={row.phase}
                      dotPath={`sections.resources_cost_estimates.phase_hours_table.${index}.phase.user_input`}
                      docId={docId}
                      placeholder="Phase"
                      presets={PROJECT_PHASE_PRESETS}
                      onLocalUpdate={updatePhaseField(index)}
                    />
                  </td>
                  <td style={tdNumber}>{row.sa_hours ?? 0}</td>
                  <td style={tdNumber}>{row.eng_hours ?? 0}</td>
                  <td style={tdNumber}>{row.other_hours ?? 0}</td>
                  <td style={tdNumber}>{row.total ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p style={emptyText}>Phase hours 데이터가 아직 없습니다.</p>
        )}
      </SectionCard>

      {/* ── Total Hours & Total Cost (read-only) ── */}
      <SectionCard title="Totals">
        <TotalsDisplay label="Total Hours" row={totalHours} />
        <TotalsDisplay label="Total Cost" row={totalCost} />
      </SectionCard>

      {/* ── Contribution ── */}
      <SectionCard title="Contribution">
        <table style={tableStyle}>
          <thead>
            <tr style={{ background: color.bgPrimary }}>
              {['Party', 'Amount', 'Percentage'].map(h => <th key={h} style={th}>{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {(['customer', 'partner', 'aws'] as const).map(party => (
              <tr key={party}>
                <td style={{ ...td, fontWeight: 600, textTransform: 'capitalize' }}>{party}</td>
                <td style={td}>
                  <FieldValueEditor
                    field={contribution?.[party]?.amount}
                    dotPath={`sections.resources_cost_estimates.contribution.${party}.amount.user_input`}
                    docId={docId}
                    placeholder="Amount"
                    onLocalUpdate={updateContributionField(party, 'amount')}
                  />
                </td>
                <td style={td}>
                  <FieldValueEditor
                    field={contribution?.[party]?.pct}
                    dotPath={`sections.resources_cost_estimates.contribution.${party}.pct.user_input`}
                    docId={docId}
                    placeholder="%"
                    onLocalUpdate={updateContributionField(party, 'pct')}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </SectionCard>

      {/* ── Client Signatures ── */}
      <SectionCard title="Client Signatures">
        <FieldRow label="Customer Name">
          <FieldValueEditor
            field={sectionData?.client_signature_customer_name}
            dotPath="sections.resources_cost_estimates.client_signature_customer_name.user_input"
            docId={docId}
            placeholder="Customer Name"
            onLocalUpdate={updateScalarField('client_signature_customer_name')}
          />
        </FieldRow>
        <FieldRow label="Person Name">
          <FieldValueEditor
            field={sectionData?.client_signature_person_name}
            dotPath="sections.resources_cost_estimates.client_signature_person_name.user_input"
            docId={docId}
            placeholder="Person Name"
            onLocalUpdate={updateScalarField('client_signature_person_name')}
          />
        </FieldRow>
        <FieldRow label="Designation">
          <FieldValueEditor
            field={sectionData?.client_signature_designation}
            dotPath="sections.resources_cost_estimates.client_signature_designation.user_input"
            docId={docId}
            placeholder="Designation"
            onLocalUpdate={updateScalarField('client_signature_designation')}
          />
        </FieldRow>
        <FieldRow label="Date">
          <FieldValueEditor
            field={sectionData?.client_signature_date}
            dotPath="sections.resources_cost_estimates.client_signature_date.user_input"
            docId={docId}
            placeholder="Date"
            type="date"
            onLocalUpdate={updateScalarField('client_signature_date')}
          />
        </FieldRow>
      </SectionCard>
    </div>
  )
}

// ─── Sub-components ──────────────────────────────────────────────────────────

function SectionCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={sectionCard}>
      <h3 style={sectionTitle}>{title}</h3>
      {children}
    </div>
  )
}

function FieldRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
      <span style={{ minWidth: 140, fontWeight: 600, fontSize: 13, color: color.textSecondary }}>{label}</span>
      {children}
    </div>
  )
}

function TotalsDisplay({ label, row }: { label: string; row: TotalsRow | undefined }) {
  if (!row) {
    return (
      <div style={{ marginBottom: 12 }}>
        <span style={{ fontWeight: 600, fontSize: 13, color: color.textSecondary }}>{label}: </span>
        <span style={{ color: color.textMuted }}>—</span>
      </div>
    )
  }
  return (
    <div style={{ marginBottom: 12 }}>
      <span style={{ fontWeight: 600, fontSize: 13, color: color.textSecondary, marginRight: 12 }}>{label}</span>
      <span style={totalsChip}>SA: {row.sa || '—'}</span>
      <span style={totalsChip}>Eng: {row.eng || '—'}</span>
      <span style={totalsChip}>Other: {row.other || '—'}</span>
      <span style={{ ...totalsChip, fontWeight: 700 }}>Total: {row.total || '—'}</span>
    </div>
  )
}

// ─── Styles ──────────────────────────────────────────────────────────────────

const sectionCard: React.CSSProperties = {
  marginBottom: 20,
  padding: 16,
  border: `1px solid ${color.border}`,
  borderRadius: 8,
  background: color.bgSurface,
}

const sectionTitle: React.CSSProperties = {
  marginTop: 0,
  marginBottom: 12,
  fontSize: 14,
  fontWeight: 700,
  color: color.textPrimary,
}

const tableStyle: React.CSSProperties = { width: '100%', borderCollapse: 'collapse', fontSize: 14 }
const th: React.CSSProperties = { padding: '8px 6px', borderBottom: `2px solid ${color.border}`, textAlign: 'left' }
const td: React.CSSProperties = { padding: '6px', borderBottom: `1px solid ${color.border}`, verticalAlign: 'top' }
const tdNumber: React.CSSProperties = { ...td, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }

const emptyText: React.CSSProperties = { color: color.textMuted, fontSize: 13 }

const totalsChip: React.CSSProperties = {
  display: 'inline-block',
  padding: '2px 8px',
  marginRight: 8,
  borderRadius: 4,
  fontSize: 13,
  background: color.bgSubtle,
  color: color.textPrimary,
}

const addButton: React.CSSProperties = {
  background: 'none',
  border: `1px dashed ${color.border}`,
  borderRadius: 4,
  padding: '4px 10px',
  cursor: 'pointer',
  color: color.textSecondary,
  fontSize: 12,
}

const deleteButton: React.CSSProperties = {
  border: 'none',
  borderRadius: 6,
  padding: '6px 10px',
  background: '#fee2e2',
  color: '#b91c1c',
  cursor: 'pointer',
  fontWeight: 600,
}
