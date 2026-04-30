import { useMemo } from 'react'
import { useDocumentStore } from '../../store/documentStore'
import { AiHighlight, resolveFieldValue } from '../AiBadge'
import { color } from '../../styles/tokens'
import { formatMoney, isBedrockService, resolveDisplayText } from '../../utils/frontendSchema'

export function CostSection() {
  const roles = useDocumentStore(s => s.staffing_plan?.roles ?? {})
  const grandTotal = useDocumentStore(s => s.staffing_plan?.grand_total_cost?.calculated ?? null)
  const costBreakdown = useDocumentStore(s => s.sections?.cost_breakdown)
  const architecture = useDocumentStore(s => s.sections?.architecture)
  const entries = Object.values(roles)

  const funding = useMemo(() => {
    const calc = (costBreakdown?.funding_calculation ?? {}) as Record<string, any>
    const annual = resolveFieldValue(calc.yr1_arr)
    const sow = resolveFieldValue(calc.sow_cost)
    const eligible = resolveFieldValue(calc.eligible_amount)
    return {
      yr1_arr: formatMoney(annual),
      sow_cost: formatMoney(sow),
      eligible_amount: formatMoney(eligible),
      bedrock_included: architecture?.services ? architecture.services.some(service => isBedrockService(service as any)) : Boolean(resolveFieldValue(calc.bedrock_included)),
    }
  }, [architecture?.services, costBreakdown?.funding_calculation])

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>Cost Breakdown</h2>

      <div style={fundingCard}>
        <div style={fundingGrid}>
          <FundingMetric label="Year 1 ARR" value={funding.yr1_arr} />
          <FundingMetric label="SOW Cost" value={funding.sow_cost} />
          <FundingMetric label="Eligible funding" value={funding.eligible_amount} />
          <FundingMetric label="Bedrock included" value={funding.bedrock_included ? 'Yes' : 'No'} />
        </div>
      </div>

      <h3 style={{ marginBottom: 8 }}>인건비 요약</h3>
      {entries.length > 0 ? (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14, marginBottom: 16 }}>
          <thead>
            <tr style={{ background: color.bgPrimary }}>
              {['역할', '총시간', '시급($)', '소계($)'].map(h => (
                <th key={h} style={{ padding: '8px 6px', borderBottom: `2px solid ${color.border}`, textAlign: 'left' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {entries.map(r => (
              <tr key={r.role_id}>
                <td style={td}>{resolveDisplayText(r.display_name, r.role_id)}</td>
                <td style={td}>{r.total_hours?.calculated ?? '—'}</td>
                <td style={td}>
                  <AiHighlight field={r.rate_per_hour}>
                    {resolveFieldValue(r.rate_per_hour) ?? '—'}
                  </AiHighlight>
                </td>
                <td style={td}>{r.total_cost?.calculated != null ? `${r.total_cost.calculated.toLocaleString()}` : '—'}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr style={{ fontWeight: 700 }}>
              <td colSpan={3} style={td}>Grand Total</td>
              <td style={td}>{grandTotal != null ? `${grandTotal.toLocaleString()}` : '—'}</td>
            </tr>
          </tfoot>
        </table>
      ) : <p style={{ color: color.textMuted, marginBottom: 16 }}>팀 구성 후 인건비가 계산됩니다.</p>}

      <h3 style={{ marginBottom: 8 }}>AWS 서비스 비용</h3>
      <div style={{ padding: 16, background: color.bgPrimary, borderRadius: 8, marginBottom: 16 }}>
        {costBreakdown?.aws_service_cost?.monthly_cost_summary?.calculated ? (
          <>
            <p style={{ fontWeight: 600 }}>
              월간 예상 비용: ${costBreakdown.aws_service_cost.monthly_cost_summary.calculated.toLocaleString()}
            </p>
            {costBreakdown.aws_service_cost.calculator_share_url && (
              <a
                href={costBreakdown.aws_service_cost.calculator_share_url}
                target="_blank"
                rel="noopener noreferrer"
                style={{ color: color.info, fontSize: 13 }}
              >
                calculator.aws에서 상세 보기
              </a>
            )}
          </>
        ) : (
          <>
            <p style={{ color: color.textMuted }}>AWS 비용 추정이 아직 수행되지 않았습니다.</p>
            <p style={{ color: '#bbb', fontSize: 12, marginTop: 4 }}>calculator.aws 링크가 여기에 표시됩니다.</p>
          </>
        )}
      </div>

      <h3 style={{ marginBottom: 8 }}>Resources & Cost Estimates</h3>
      {costBreakdown?.document_local_summary ? (
        <div style={{ padding: 16, background: color.bgPrimary, borderRadius: 8 }}>
          <p>총 인건비: ${costBreakdown.document_local_summary.total_staffing_cost?.toLocaleString() ?? '—'}</p>
          <p>총 AWS 월간 비용: ${costBreakdown.document_local_summary.total_aws_monthly_cost?.toLocaleString() ?? '—'}</p>
          <p style={{ fontWeight: 600 }}>총 프로젝트 비용: ${costBreakdown.document_local_summary.total_project_cost?.toLocaleString() ?? '—'}</p>
        </div>
      ) : (
        <p style={{ color: color.textMuted }}>리소스 비용 추정이 아직 수행되지 않았습니다.</p>
      )}
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

const fundingCard: React.CSSProperties = {
  padding: 12,
  marginBottom: 16,
  border: `1px solid ${color.border}`,
  borderRadius: 8,
  background: color.bgPrimary,
}

const fundingGrid: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
  gap: 8,
}

const metricCard: React.CSSProperties = {
  padding: 12,
  borderRadius: 8,
  background: color.bgSurface,
  border: `1px solid ${color.border}`,
}

const td: React.CSSProperties = { padding: '8px 6px', borderBottom: `1px solid ${color.border}` }
