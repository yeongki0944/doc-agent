import { useDocumentStore } from '../../store/documentStore'
import { AiHighlight, resolveFieldValue } from '../AiBadge'

export function CostSection() {
  const roles = useDocumentStore(s => s.staffing_plan?.roles ?? {})
  const grandTotal = useDocumentStore(s => s.staffing_plan?.grand_total_cost?.calculated ?? null)
  const costBreakdown = useDocumentStore(s => s.sections?.cost_breakdown)
  const entries = Object.values(roles)

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>Cost Breakdown</h2>

      <h3 style={{ marginBottom: 8 }}>인건비 요약</h3>
      {entries.length > 0 ? (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14, marginBottom: 16 }}>
          <thead>
            <tr style={{ background: '#f9fafb' }}>
              {['역할', '총시간', '시급($)', '소계($)'].map(h => (
                <th key={h} style={{ padding: '8px 6px', borderBottom: '2px solid #eee', textAlign: 'left' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {entries.map(r => (
              <tr key={r.role_id}>
                <td style={td}>{r.display_name}</td>
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
      ) : <p style={{ color: '#999', marginBottom: 16 }}>팀 구성 후 인건비가 계산됩니다.</p>}

      <h3 style={{ marginBottom: 8 }}>AWS 서비스 비용</h3>
      <div style={{ padding: 16, background: '#f9fafb', borderRadius: 8, marginBottom: 16 }}>
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
                style={{ color: '#3b82f6', fontSize: 13 }}
              >
                calculator.aws에서 상세 보기
              </a>
            )}
          </>
        ) : (
          <>
            <p style={{ color: '#999' }}>AWS 비용 추정이 아직 수행되지 않았습니다.</p>
            <p style={{ color: '#bbb', fontSize: 12, marginTop: 4 }}>calculator.aws 링크가 여기에 표시됩니다.</p>
          </>
        )}
      </div>

      <h3 style={{ marginBottom: 8 }}>Resources & Cost Estimates</h3>
      {costBreakdown?.document_local_summary ? (
        <div style={{ padding: 16, background: '#f9fafb', borderRadius: 8 }}>
          <p>총 인건비: ${costBreakdown.document_local_summary.total_staffing_cost?.toLocaleString() ?? '—'}</p>
          <p>총 AWS 월간 비용: ${costBreakdown.document_local_summary.total_aws_monthly_cost?.toLocaleString() ?? '—'}</p>
          <p style={{ fontWeight: 600 }}>총 프로젝트 비용: ${costBreakdown.document_local_summary.total_project_cost?.toLocaleString() ?? '—'}</p>
        </div>
      ) : (
        <p style={{ color: '#999' }}>리소스 비용 추정이 아직 수행되지 않았습니다.</p>
      )}
    </div>
  )
}

const td: React.CSSProperties = { padding: '8px 6px', borderBottom: '1px solid #eee' }
