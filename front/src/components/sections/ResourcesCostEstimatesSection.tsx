import { useCallback, useMemo } from 'react'
import { useDocumentStore, type FieldValue, type ResourcesCostEstimatesSection as RCESectionData, type RoleRate } from '../../store/documentStore'
import { useSessionStore } from '../../store/sessionStore'
import { FieldValueEditor } from '../editors/FieldValueEditor'
import { SectionGuideButton } from '../SectionGuideButton'
import { useDocLang } from '../LangContext'
import { color } from '../../styles/tokens'
import { saveUserInput } from '../../utils/api'
import { resolveFieldValue } from '../AiBadge'

const emptyField = (): FieldValue => ({ user_input: null, ai_recommended: null, calculated: null, status: 'empty', user_edited: false })
const rateField = (value = 100): FieldValue => ({ user_input: null, ai_recommended: null, calculated: value, status: 'confirmed', user_edited: false })

function roleText(value: FieldValue | undefined): string {
  return String(resolveFieldValue(value) ?? '').trim()
}

function nameText(value: FieldValue | undefined): string {
  return String(resolveFieldValue(value) ?? '').trim()
}

export function ResourcesCostEstimatesSection() {
  const lang = useDocLang()
  const koData = useDocumentStore(s => s.sections?.resources_cost_estimates) as RCESectionData | undefined
  const enData = useDocumentStore(s => s.sections_en?.resources_cost_estimates) as RCESectionData | undefined
  const sectionData = lang === 'en' ? enData : koData
  const stakeholders = useDocumentStore(s => s.sections?.stakeholders)
  const setDocument = useDocumentStore(s => s.setDocument)
  const docId = useSessionStore(s => s.currentDocId) || ''
  const contribution = sectionData?.contribution

  const projectTeam = useMemo(() => stakeholders?.project_team ?? [], [stakeholders?.project_team])
  const roleSummaries = useMemo(() => {
    const map = new Map<string, { role: string; count: number; names: string[] }>()
    for (const member of projectTeam) {
      const role = roleText(member.role) || 'Unassigned'
      const item = map.get(role) ?? { role, count: 0, names: [] }
      item.count += 1
      const name = nameText(member.name)
      if (name) item.names.push(name)
      map.set(role, item)
    }
    return [...map.values()]
  }, [projectTeam])

  const roleRates = useMemo(() => {
    const current = sectionData?.role_rates ?? []
    return roleSummaries.map(summary => current.find(rate => rate.role === summary.role) ?? { role: summary.role, rate: rateField(100) })
  }, [roleSummaries, sectionData?.role_rates])

  const updateRoleRate = useCallback((role: string, field: FieldValue) => {
    const sections = useDocumentStore.getState().sections || {}
    const current = (sections.resources_cost_estimates || {}) as RCESectionData
    const existing = current.role_rates ?? []
    const next: RoleRate[] = roleSummaries.map(summary => {
      if (summary.role === role) return { role, rate: field }
      return existing.find(item => item.role === summary.role) ?? { role: summary.role, rate: rateField(100) }
    })
    setDocument({ sections: { ...sections, resources_cost_estimates: { ...current, role_rates: next } } } as any)
    saveUserInput(docId, 'sections.resources_cost_estimates.role_rates', next)
  }, [docId, roleSummaries, setDocument])

  const updateContributionField = useCallback(
    (party: 'customer' | 'partner' | 'aws', field: 'amount' | 'pct') => (newField: FieldValue) => {
      const sections = useDocumentStore.getState().sections || {}
      const current = (sections.resources_cost_estimates || {}) as RCESectionData
      const currentContribution = current.contribution || {
        customer: { amount: emptyField(), pct: emptyField() },
        partner: { amount: emptyField(), pct: emptyField() },
        aws: { amount: emptyField(), pct: emptyField() },
      }
      setDocument({
        sections: {
          ...sections,
          resources_cost_estimates: {
            ...current,
            contribution: { ...currentContribution, [party]: { ...currentContribution[party], [field]: newField } },
          },
        },
      } as any)
    },
    [setDocument],
  )

  const updateScalarField = useCallback((field: keyof RCESectionData) => (newField: FieldValue) => {
    const sections = useDocumentStore.getState().sections || {}
    const current = (sections.resources_cost_estimates || {}) as RCESectionData
    setDocument({ sections: { ...sections, resources_cost_estimates: { ...current, [field]: newField } } } as any)
  }, [setDocument])

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>7. Resources &amp; Cost Estimates <SectionGuideButton sectionKey="resources_cost_estimates" /></h2>

      <SectionCard title="Partner Technical Team">
        {projectTeam.length > 0 ? (
          <table style={tableStyle}>
            <thead><tr style={{ background: color.bgPrimary }}>{['Role', 'Name', 'Contact'].map(h => <th key={h} style={th}>{h}</th>)}</tr></thead>
            <tbody>
              {projectTeam.map((member, index) => (
                <tr key={index}>
                  <td style={td}>{roleText(member.role) || '-'}</td>
                  <td style={td}>{nameText(member.name) || '-'}</td>
                  <td style={td}>{String(resolveFieldValue(member.contact) ?? '') || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p style={emptyText}>Partner Project Team rows from Stakeholders will appear here.</p>}
      </SectionCard>

      <SectionCard title="Role Rates">
        {roleRates.length > 0 ? (
          <table style={tableStyle}>
            <thead><tr style={{ background: color.bgPrimary }}>{['Role', 'Count', 'Members', 'Rate / hour'].map(h => <th key={h} style={th}>{h}</th>)}</tr></thead>
            <tbody>
              {roleSummaries.map(summary => {
                const rate = roleRates.find(item => item.role === summary.role)?.rate ?? rateField(100)
                return (
                  <tr key={summary.role}>
                    <td style={td}>{summary.role}</td>
                    <td style={tdNumber}>{summary.count}</td>
                    <td style={td}>{summary.names.join(', ') || '-'}</td>
                    <td style={td}>
                      <input
                        type="number"
                        defaultValue={String(resolveFieldValue(rate) ?? 100)}
                        onBlur={(e) => updateRoleRate(summary.role, { user_input: e.target.value || '100', ai_recommended: null, calculated: null, status: 'draft', user_edited: true })}
                        style={rateInput}
                      />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        ) : <p style={emptyText}>Add Partner Project Team roles in Stakeholders to configure rates.</p>}
      </SectionCard>

      <SectionCard title="Phase Hours Matrix">
        <p style={emptyText}>Dynamic phase-hours editing is prepared in schema and remains a Phase 2 UI task.</p>
      </SectionCard>

      <SectionCard title="Contribution">
        <table style={tableStyle}>
          <thead><tr style={{ background: color.bgPrimary }}>{['Party', 'Amount', 'Percentage'].map(h => <th key={h} style={th}>{h}</th>)}</tr></thead>
          <tbody>
            {(['customer', 'partner', 'aws'] as const).map(party => (
              <tr key={party}>
                <td style={{ ...td, fontWeight: 600, textTransform: 'capitalize' }}>{party}</td>
                <td style={td}><FieldValueEditor field={contribution?.[party]?.amount} dotPath={`sections.resources_cost_estimates.contribution.${party}.amount.user_input`} docId={docId} placeholder="Amount" onLocalUpdate={updateContributionField(party, 'amount')} /></td>
                <td style={td}><FieldValueEditor field={contribution?.[party]?.pct} dotPath={`sections.resources_cost_estimates.contribution.${party}.pct.user_input`} docId={docId} placeholder="%" onLocalUpdate={updateContributionField(party, 'pct')} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </SectionCard>

      <SectionCard title="Client Signatures">
        <FieldRow label="Customer Name"><FieldValueEditor field={sectionData?.client_signature_customer_name} dotPath="sections.resources_cost_estimates.client_signature_customer_name.user_input" docId={docId} placeholder="Customer Name" onLocalUpdate={updateScalarField('client_signature_customer_name')} /></FieldRow>
        <FieldRow label="Person Name"><FieldValueEditor field={sectionData?.client_signature_person_name} dotPath="sections.resources_cost_estimates.client_signature_person_name.user_input" docId={docId} placeholder="Person Name" onLocalUpdate={updateScalarField('client_signature_person_name')} /></FieldRow>
        <FieldRow label="Designation"><FieldValueEditor field={sectionData?.client_signature_designation} dotPath="sections.resources_cost_estimates.client_signature_designation.user_input" docId={docId} placeholder="Designation" onLocalUpdate={updateScalarField('client_signature_designation')} /></FieldRow>
        <FieldRow label="Date"><FieldValueEditor field={sectionData?.client_signature_date} dotPath="sections.resources_cost_estimates.client_signature_date.user_input" docId={docId} placeholder="Date" type="date" onLocalUpdate={updateScalarField('client_signature_date')} /></FieldRow>
      </SectionCard>
    </div>
  )
}

function SectionCard({ title, children }: { title: string; children: React.ReactNode }) {
  return <div style={sectionCard}><h3 style={sectionTitle}>{title}</h3>{children}</div>
}

function FieldRow({ label, children }: { label: string; children: React.ReactNode }) {
  return <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}><span style={{ minWidth: 140, fontWeight: 600, fontSize: 13, color: color.textSecondary }}>{label}</span>{children}</div>
}

const sectionCard: React.CSSProperties = { marginBottom: 20, padding: 16, border: `1px solid ${color.border}`, borderRadius: 8, background: color.bgSurface }
const sectionTitle: React.CSSProperties = { marginTop: 0, marginBottom: 12, fontSize: 14, fontWeight: 700, color: color.textPrimary }
const tableStyle: React.CSSProperties = { width: '100%', borderCollapse: 'collapse', fontSize: 14 }
const th: React.CSSProperties = { padding: '8px 6px', borderBottom: `2px solid ${color.border}`, textAlign: 'left' }
const td: React.CSSProperties = { padding: '6px', borderBottom: `1px solid ${color.border}`, verticalAlign: 'top' }
const tdNumber: React.CSSProperties = { ...td, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }
const emptyText: React.CSSProperties = { color: color.textMuted, fontSize: 13 }
const rateInput: React.CSSProperties = { width: 90, padding: '4px 8px', border: `1px solid ${color.border}`, borderRadius: 4, fontSize: 13 }
