import { useState } from 'react'
import { color, radius, space } from '../../styles/tokens'
import {
  calculateResourcePlan,
  createChangeRequest,
  type ResourcePlanInput,
  type ResourcePlanResult,
} from '../../utils/api'
import { resolveFieldValue } from '../AiBadge'
import { StatusBadge, EnvelopeNotices } from './StatusEnvelope'

const WARNING_TEXT =
  'This is a Resource Planning draft. Final values must be reviewed with AWS Calculator, Bedrock usage assumption, SOW cost, customer scope, and sales owner.'

/**
 * Resource Planning Assistant — inputs funding target / MRR / ARR / SOW Cost
 * and displays required ARR, SOW cost requirement, 125K cap check, resource
 * matrix draft, and warnings.
 */
export function ResourcePlanningPanel({ docId }: { docId: string }) {
  const [target, setTarget] = useState('')
  const [mrr, setMrr] = useState('')
  const [arr, setArr] = useState('')
  const [sowCost, setSowCost] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<ResourcePlanResult | null>(null)
  const [fallback, setFallback] = useState(false)
  const [crState, setCrState] = useState<{
    state: 'idle' | 'submitting' | 'created' | 'failed'
    crId?: string
    message?: string
  }>({ state: 'idle' })

  const handleCalculate = async () => {
    setLoading(true)
    setError(null)
    setFallback(false)
    setCrState({ state: 'idle' })
    try {
      const body: ResourcePlanInput = {
        target_funding_amount: toNumber(target),
        mrr: toNumber(mrr),
        arr: toNumber(arr),
        sow_cost: toNumber(sowCost),
      }
      const data = await calculateResourcePlan(docId, body)
      setResult(data)
    } catch (e: any) {
      setError(e?.message || 'Resource plan 계산 실패')
      setResult(localResourcePlanFallback({
        target_funding_amount: toNumber(target),
        mrr: toNumber(mrr),
        arr: toNumber(arr),
        sow_cost: toNumber(sowCost),
      }))
      setFallback(true)
    } finally {
      setLoading(false)
    }
  }

  const handleCreateChangeRequest = async () => {
    if (!result) return
    setCrState({ state: 'submitting' })
    try {
      const fundingPayload = {
        yr1_arr: result.required_arr,
        sow_cost: result.sow_cost_requirement,
        eligible_amount: result.eligible_funding_amount,
        cap: result.cap_check?.cap ?? 125000,
        cap_limited: !!result.cap_check?.cap_limited,
        formula: result.formula,
        source: 'resource_planning_assistant',
      }
      const patch = {
        op: 'replace',
        path: '/sections/cost_breakdown/funding_calculation',
        value: fundingPayload,
      }
      const resp = await createChangeRequest(docId, {
        summary: 'Resource Planning — update funding_calculation',
        json_patch: [patch],
        changes: [
          {
            section: 'cost_breakdown',
            as_is: null,
            to_be: fundingPayload,
            reason: 'Apply Resource Planning Assistant draft funding numbers',
            json_patch: [patch],
          },
        ],
      })
      setCrState({
        state: 'created',
        crId: resp?.change_request?.change_request_id,
      })
    } catch (e: any) {
      setCrState({ state: 'failed', message: e?.message || 'Change request 생성 실패' })
    }
  }

  return (
    <div style={{ padding: space.md, display: 'flex', flexDirection: 'column', gap: space.md }}>
      <div>
        <h3 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>Resource Planning Assistant</h3>
        <div style={{ fontSize: 11, color: color.textMuted, marginTop: 2 }}>
          Funding target 기반 필요 ARR / SOW cost / 리소스 매트릭스 초안 산출
        </div>
      </div>

      <div style={{
        fontSize: 11,
        padding: space.sm,
        background: '#fff7ed',
        border: '1px solid #fed7aa',
        color: '#9a3412',
        borderRadius: radius.sm,
        lineHeight: 1.5,
      }}>
        ⚠ {WARNING_TEXT}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: space.sm }}>
        <NumberInput label="Target Funding ($)" value={target} onChange={setTarget} placeholder="50000" />
        <NumberInput label="SOW Cost ($)" value={sowCost} onChange={setSowCost} placeholder="selectable" />
        <NumberInput label="MRR ($)" value={mrr} onChange={setMrr} placeholder="optional" />
        <NumberInput label="ARR ($)" value={arr} onChange={setArr} placeholder="optional" />
      </div>

      <button
        onClick={handleCalculate}
        disabled={loading}
        style={{
          padding: '8px 12px',
          borderRadius: radius.sm,
          border: 'none',
          fontSize: 12,
          fontWeight: 600,
          cursor: loading ? 'wait' : 'pointer',
          background: color.mzRed,
          color: color.bgSurface,
        }}
      >
        {loading ? '계산 중...' : 'Calculate Resource Plan'}
      </button>

      {error && (
        <div style={{
          fontSize: 12, color: color.error, padding: space.sm,
          background: '#fef2f2', borderRadius: radius.sm, border: '1px solid #fecaca',
        }}>
          ⚠ {error} (로컬 fallback 결과를 표시합니다)
        </div>
      )}

      {result && (
        <ResultView
          result={result}
          fallback={fallback}
          crState={crState}
          onCreateCr={handleCreateChangeRequest}
        />
      )}
    </div>
  )
}

function NumberInput({
  label, value, onChange, placeholder,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
}) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <span style={{ fontSize: 11, color: color.textSecondary, fontWeight: 500 }}>{label}</span>
      <input
        type="number"
        inputMode="decimal"
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        style={{
          padding: '6px 8px',
          border: `1px solid ${color.border}`,
          borderRadius: radius.sm,
          fontSize: 12,
          background: color.bgSurface,
        }}
      />
    </label>
  )
}

function ResultView({
  result, fallback, crState, onCreateCr,
}: {
  result: ResourcePlanResult
  fallback: boolean
  crState: { state: 'idle' | 'submitting' | 'created' | 'failed'; crId?: string; message?: string }
  onCreateCr: () => void
}) {
  const cap = result.cap_check?.cap ?? 125000
  const capLimited = result.cap_check?.cap_limited
  const matrix = result.draft_resource_matrix
  const contribution = result.contribution_distribution

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: space.md }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: space.sm, flexWrap: 'wrap' }}>
        <StatusBadge status={result.standard_status} message={result.message} />
        {result.message && (
          <span style={{ fontSize: 11, color: color.textSecondary }}>{result.message}</span>
        )}
      </div>

      <EnvelopeNotices
        missing_inputs={result.missing_inputs}
        error_reason={result.error_reason}
      />

      <div style={{
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        gap: 6,
        fontSize: 12,
      }}>
        <Metric label="Required ARR" value={formatUsd(result.required_arr)} />
        <Metric label="SOW Cost Required" value={formatUsd(result.sow_cost_requirement)} />
        <Metric label="$125K Cap" value={capLimited ? `⚠ Cap Limited (${formatUsd(cap)})` : `OK (${formatUsd(cap)})`} warn={capLimited} />
        <Metric label="Eligible Funding" value={formatUsd(result.eligible_funding_amount)} highlight />
      </div>

      {result.formula && (
        <div style={{ fontSize: 10, color: color.textMuted, fontFamily: 'monospace', padding: 6, background: color.bgSubtle, borderRadius: radius.sm }}>
          {result.formula}
        </div>
      )}

      {matrix && <ResourceMatrixView matrix={matrix} />}

      {contribution && <ContributionView contribution={contribution} />}

      {Array.isArray(result.warnings) && result.warnings.length > 0 && (
        <div>
          <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 4 }}>Warnings</div>
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 11, color: '#9a3412', lineHeight: 1.6 }}>
            {result.warnings.map((w, i) => <li key={i}>{w}</li>)}
          </ul>
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <button
          onClick={onCreateCr}
          disabled={fallback || crState.state === 'submitting' || crState.state === 'created'}
          style={{
            padding: '6px 12px',
            fontSize: 12,
            fontWeight: 600,
            borderRadius: radius.sm,
            border: 'none',
            cursor:
              (fallback || crState.state === 'submitting' || crState.state === 'created')
                ? 'not-allowed'
                : 'pointer',
            background:
              crState.state === 'created' ? color.success :
              fallback ? color.border :
              color.mzRed,
            color: color.bgSurface,
          }}
          title={
            fallback
              ? 'Fallback 모드에서는 사용 불가'
              : 'funding_calculation 변경을 change request로 만듭니다'
          }
        >
          {crState.state === 'submitting' ? '생성 중...' :
           crState.state === 'created' ? '✓ Change Request 생성됨' :
           'Create Change Request'}
        </button>
        {crState.state === 'created' && crState.crId && (
          <code style={{ fontSize: 10, color: color.textMuted }}>{crState.crId}</code>
        )}
        {crState.state === 'failed' && (
          <span style={{ fontSize: 10, color: color.error }}>
            ✗ {crState.message || '실패'}
          </span>
        )}
        {fallback && (
          <span style={{ fontSize: 10, color: color.textMuted }}>
            (fallback: 문서를 변경할 수 없습니다)
          </span>
        )}
      </div>
    </div>
  )
}

function Metric({ label, value, highlight, warn }: { label: string; value: string; highlight?: boolean; warn?: boolean }) {
  return (
    <div style={{
      padding: 8,
      borderRadius: radius.sm,
      border: `1px solid ${warn ? '#fed7aa' : color.border}`,
      background: highlight ? '#f0fdf4' : warn ? '#fff7ed' : color.bgSurface,
    }}>
      <div style={{ fontSize: 10, color: color.textMuted, textTransform: 'uppercase', letterSpacing: 0.5 }}>{label}</div>
      <div style={{ fontSize: 13, fontWeight: 600, color: warn ? '#9a3412' : color.textPrimary, marginTop: 2 }}>
        {value}
      </div>
    </div>
  )
}

function ResourceMatrixView({ matrix }: { matrix: NonNullable<ResourcePlanResult['draft_resource_matrix']> }) {
  const rates = new Map<string, number>()
  for (const row of matrix.role_rates) {
    const val = resolveFieldValue(row.rate)
    const num = typeof val === 'number' ? val : Number(val)
    if (!Number.isNaN(num)) rates.set(row.role, num)
  }

  return (
    <div>
      <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 6 }}>Draft Resource Matrix</div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
          <thead>
            <tr>
              <th style={thStyle}>Phase</th>
              {matrix.role_rates.map(r => (
                <th key={r.role} style={thStyle}>
                  {r.role}
                  <div style={{ fontSize: 9, color: color.textMuted, fontWeight: 400 }}>
                    {formatUsd(rates.get(r.role) ?? 0)}/hr
                  </div>
                </th>
              ))}
              <th style={thStyle}>Total hrs</th>
            </tr>
          </thead>
          <tbody>
            {matrix.phase_hours_table.map((row, i) => (
              <tr key={i}>
                <td style={tdStyle}>{resolveFieldValue(row.phase)}</td>
                {matrix.role_rates.map(r => {
                  const entry = row.role_hours.find(h => h.role === r.role)
                  return (
                    <td key={r.role} style={tdStyle}>{entry ? entry.hours : 0}</td>
                  )
                })}
                <td style={{ ...tdStyle, fontWeight: 600 }}>{row.total}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function ContributionView({
  contribution,
}: {
  contribution: NonNullable<ResourcePlanResult['contribution_distribution']>
}) {
  return (
    <div>
      <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 6 }}>Contribution Distribution</div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 6 }}>
        {Object.entries(contribution).map(([party, val]) => (
          <div key={party} style={{
            padding: 8,
            borderRadius: radius.sm,
            border: `1px solid ${color.border}`,
            background: color.bgSurface,
          }}>
            <div style={{ fontSize: 10, color: color.textMuted, textTransform: 'uppercase' }}>{party}</div>
            <div style={{ fontSize: 12, fontWeight: 600, marginTop: 2 }}>
              {formatUsd(toNumber(resolveFieldValue(val?.amount)))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

const thStyle: React.CSSProperties = {
  padding: 6, textAlign: 'left', background: color.bgSubtle,
  borderBottom: `1px solid ${color.border}`, fontSize: 10,
  whiteSpace: 'nowrap',
}

const tdStyle: React.CSSProperties = {
  padding: 6, borderBottom: `1px solid ${color.border}`, fontSize: 11,
}

function toNumber(s: any): number {
  if (s == null) return 0
  const n = Number(typeof s === 'string' ? s.replace(/[$,]/g, '') : s)
  return Number.isFinite(n) ? n : 0
}

function formatUsd(n: number): string {
  if (!Number.isFinite(n) || n === 0) return '$0'
  return `$${Math.round(n).toLocaleString()}`
}

function localResourcePlanFallback(body: ResourcePlanInput): ResourcePlanResult {
  const target = body.target_funding_amount ?? 0
  const mrr = body.mrr ?? 0
  const arr = body.arr ?? 0
  const sow = body.sow_cost ?? 0
  const requiredArr = target > 0 ? Math.round((target / 0.25) * 100) / 100 : 0
  const effectiveArr = arr > 0 ? arr : (mrr > 0 ? mrr * 12 : requiredArr)
  const capLimited = target > 125000
  const eligible = Math.round(Math.min(effectiveArr * 0.25, sow > 0 ? sow : target, 125000) * 100) / 100

  const warnings: string[] = [WARNING_TEXT]
  if (capLimited) warnings.push('$125K cap applies; requested target funding exceeds the maximum formula cap.')
  if (sow > 0 && sow < target) warnings.push('SOW cost is below the target funding amount, so SOW cost limits eligibility.')
  if (effectiveArr * 0.25 < target) warnings.push('ARR is below the amount required to support the target funding amount under the 25% rule.')

  return {
    target_funding_amount: target,
    required_arr: requiredArr,
    sow_cost_requirement: target,
    cap_check: { cap: 125000, cap_limited: capLimited },
    eligible_funding_amount: eligible,
    formula: 'Eligible Funding Amount = min(Year 1 ARR * 25%, SOW Cost, 125000)',
    warnings,
  }
}
