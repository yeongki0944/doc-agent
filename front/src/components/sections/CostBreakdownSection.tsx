import { useCallback, useMemo } from 'react'
import { useDocumentStore, type CostBreakdownSection as CostBreakdownSectionData, type CostBreakdownRow, type FieldValue } from '../../store/documentStore'
import { useSessionStore } from '../../store/sessionStore'
import { FieldValueEditor } from '../editors/FieldValueEditor'
import { SaveStatusIndicator } from '../SaveStatusIndicator'
import { useSaveStatus } from '../../hooks/useSaveStatus'
import { saveUserInput } from '../../utils/api'
import { resolveFieldValue } from '../AiBadge'
import { useDocLang } from '../LangContext'
import { color } from '../../styles/tokens'
import { formatMoney } from '../../utils/frontendSchema'

const emptyField = (): FieldValue => ({
  user_input: null,
  ai_recommended: null,
  calculated: null,
  status: 'empty',
  user_edited: false,
})

function createEmptyCostBreakdownRow(): CostBreakdownRow {
  return {
    category: emptyField(),
    mrr: emptyField(),
    arr: emptyField(),
    note: emptyField(),
  }
}

export function CostBreakdownSection() {
  const lang = useDocLang()
  const koData = useDocumentStore(s => s.sections?.cost_breakdown) as CostBreakdownSectionData | undefined
  const enData = useDocumentStore(s => s.sections_en?.cost_breakdown) as CostBreakdownSectionData | undefined
  const sectionData = lang === 'en' ? enData : koData
  const setDocument = useDocumentStore(s => s.setDocument)
  const docId = useSessionStore(s => s.currentDocId) || ''
  const { saveStatus: arraySaveStatus, doSave: doArraySave } = useSaveStatus()

  const breakdownRows: CostBreakdownRow[] = useMemo(() => sectionData?.breakdown_table ?? [], [sectionData?.breakdown_table])
  const fundingCalc = useMemo(() => sectionData?.funding_calculation ?? {}, [sectionData?.funding_calculation])

  // --- Scalar field updates (via FieldValueEditor) ---
  const updateScalarField = useCallback((field: 'calculator_url' | 'mrr' | 'arr' | 'bedrock_extra') => (newField: FieldValue) => {
    const sections = useDocumentStore.getState().sections || {}
    const current = (sections.cost_breakdown || {}) as CostBreakdownSectionData
    setDocument({ sections: { ...sections, cost_breakdown: { ...current, [field]: newField } } } as any)
  }, [setDocument])

  // --- Breakdown row field updates (via FieldValueEditor) ---
  const updateRowField = useCallback((index: number, field: keyof CostBreakdownRow) => (newField: FieldValue) => {
    const sections = useDocumentStore.getState().sections || {}
    const current = (sections.cost_breakdown || {}) as CostBreakdownSectionData
    const currentRows = [...(current.breakdown_table ?? [])]
    const oldRow = currentRows[index] || createEmptyCostBreakdownRow()
    currentRows[index] = { ...oldRow, [field]: newField }
    setDocument({ sections: { ...sections, cost_breakdown: { ...current, breakdown_table: currentRows } } } as any)
  }, [setDocument])

  // --- Add/remove breakdown rows (persist full array) ---
  const addRow = useCallback(() => {
    const sections = useDocumentStore.getState().sections || {}
    const current = (sections.cost_breakdown || {}) as CostBreakdownSectionData
    const updated = [...(current.breakdown_table ?? []), createEmptyCostBreakdownRow()]
    setDocument({ sections: { ...sections, cost_breakdown: { ...current, breakdown_table: updated } } } as any)
    doArraySave(() => saveUserInput(docId, 'sections.cost_breakdown.breakdown_table', updated))
  }, [setDocument, docId, doArraySave])

  const removeRow = useCallback((index: number) => {
    const sections = useDocumentStore.getState().sections || {}
    const current = (sections.cost_breakdown || {}) as CostBreakdownSectionData
    const updated = (current.breakdown_table ?? []).filter((_, i) => i !== index)
    setDocument({ sections: { ...sections, cost_breakdown: { ...current, breakdown_table: updated } } } as any)
    doArraySave(() => saveUserInput(docId, 'sections.cost_breakdown.breakdown_table', updated))
  }, [setDocument, docId, doArraySave])

  // --- Funding calculation entries (read-only) ---
  const fundingEntries = useMemo(() => {
    return Object.entries(fundingCalc).map(([key, value]) => ({
      key,
      label: key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
      value: formatFundingValue(value),
    }))
  }, [fundingCalc])

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>Cost Breakdown</h2>

      {/* --- Editable scalar fields --- */}
      <div style={fieldGrid}>
        <FieldRow label="Calculator URL">
          <FieldValueEditor
            field={sectionData?.calculator_url}
            dotPath="sections.cost_breakdown.calculator_url.user_input"
            docId={docId}
            placeholder="Calculator URL"
            onLocalUpdate={updateScalarField('calculator_url')}
          />
        </FieldRow>
        <FieldRow label="MRR">
          <FieldValueEditor
            field={sectionData?.mrr}
            dotPath="sections.cost_breakdown.mrr.user_input"
            docId={docId}
            placeholder="MRR"
            onLocalUpdate={updateScalarField('mrr')}
          />
        </FieldRow>
        <FieldRow label="ARR">
          <FieldValueEditor
            field={sectionData?.arr}
            dotPath="sections.cost_breakdown.arr.user_input"
            docId={docId}
            placeholder="ARR"
            onLocalUpdate={updateScalarField('arr')}
          />
        </FieldRow>
        <FieldRow label="Bedrock Extra">
          <FieldValueEditor
            field={sectionData?.bedrock_extra}
            dotPath="sections.cost_breakdown.bedrock_extra.user_input"
            docId={docId}
            placeholder="Bedrock Extra"
            onLocalUpdate={updateScalarField('bedrock_extra')}
          />
        </FieldRow>
      </div>

      {/* --- Breakdown Table (editable) --- */}
      <h3 style={{ marginTop: 24, marginBottom: 8 }}>Breakdown Table</h3>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <button type="button" onClick={addRow} style={addButton}>+ Add Row</button>
        <SaveStatusIndicator status={arraySaveStatus} />
      </div>

      {breakdownRows.length > 0 ? (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
          <thead>
            <tr style={{ background: color.bgPrimary }}>
              {['Category', 'MRR', 'ARR', 'Note', ''].map(h => (
                <th key={h} style={th}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {breakdownRows.map((row, index) => (
              <tr key={index}>
                <td style={td}>
                  <FieldValueEditor
                    field={row.category}
                    dotPath={`sections.cost_breakdown.breakdown_table.${index}.category.user_input`}
                    docId={docId}
                    placeholder="Category"
                    onLocalUpdate={updateRowField(index, 'category')}
                  />
                </td>
                <td style={td}>
                  <FieldValueEditor
                    field={row.mrr}
                    dotPath={`sections.cost_breakdown.breakdown_table.${index}.mrr.user_input`}
                    docId={docId}
                    placeholder="MRR"
                    onLocalUpdate={updateRowField(index, 'mrr')}
                  />
                </td>
                <td style={td}>
                  <FieldValueEditor
                    field={row.arr}
                    dotPath={`sections.cost_breakdown.breakdown_table.${index}.arr.user_input`}
                    docId={docId}
                    placeholder="ARR"
                    onLocalUpdate={updateRowField(index, 'arr')}
                  />
                </td>
                <td style={td}>
                  <FieldValueEditor
                    field={row.note}
                    dotPath={`sections.cost_breakdown.breakdown_table.${index}.note.user_input`}
                    docId={docId}
                    placeholder="Note"
                    onLocalUpdate={updateRowField(index, 'note')}
                  />
                </td>
                <td style={td}>
                  <button type="button" onClick={() => removeRow(index)} style={deleteButton}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p style={{ color: color.textMuted }}>비용 항목이 아직 없습니다. 위 버튼으로 추가하세요.</p>
      )}

      {/* --- Funding Calculation (read-only) --- */}
      <h3 style={{ marginTop: 24, marginBottom: 8 }}>Funding Calculation</h3>
      {fundingEntries.length > 0 ? (
        <div style={fundingCard}>
          <div style={fundingGrid}>
            {fundingEntries.map(entry => (
              <FundingMetric key={entry.key} label={entry.label} value={entry.value} />
            ))}
          </div>
        </div>
      ) : (
        <p style={{ color: color.textMuted }}>펀딩 계산 결과가 아직 없습니다.</p>
      )}
    </div>
  )
}

/** Format a funding_calculation value for display */
function formatFundingValue(value: any): string {
  if (value == null) return '—'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  // If it's a FieldValue-like object, resolve it
  if (typeof value === 'object' && ('user_input' in value || 'ai_recommended' in value || 'calculated' in value)) {
    const resolved = resolveFieldValue(value)
    return resolved != null ? formatMoney(resolved) : '—'
  }
  if (typeof value === 'number') return value.toLocaleString()
  const str = String(value)
  const num = Number(str.replace(/,/g, ''))
  if (!Number.isNaN(num) && str.trim() !== '') return num.toLocaleString()
  return str || '—'
}

function FieldRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
      <span style={{ minWidth: 120, fontWeight: 600, fontSize: 13, color: color.textSecondary }}>{label}</span>
      {children}
    </div>
  )
}

function FundingMetric({ label, value }: { label: string; value: string }) {
  return (
    <div style={metricCard}>
      <div style={{ fontSize: 11, fontWeight: 700, color: color.textMuted, marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 600 }}>{value}</div>
    </div>
  )
}

const fieldGrid: React.CSSProperties = {
  marginBottom: 16,
}

const fundingCard: React.CSSProperties = {
  padding: 12,
  border: `1px solid ${color.border}`,
  borderRadius: 8,
  background: color.bgPrimary,
}

const fundingGrid: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))',
  gap: 8,
}

const metricCard: React.CSSProperties = {
  padding: 12,
  borderRadius: 8,
  background: color.bgSurface,
  border: `1px solid ${color.border}`,
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
