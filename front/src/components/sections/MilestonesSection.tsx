import { useDocumentStore } from '../../store/documentStore'

const PHASES = [
  { id: 'discovery', name: 'Discovery', deliverables: '요구사항 문서, 아키텍처 초안' },
  { id: 'development', name: 'Development', deliverables: '에이전트 구현, API, UI' },
  { id: 'testing', name: 'Testing', deliverables: '통합 테스트, UAT, 최종 문서' },
]

export function MilestonesSection() {
  const roles = useDocumentStore(s => s.staffing_plan?.roles ?? {})
  const sectionData = useDocumentStore(s => s.sections?.milestones) as Record<string, any> | undefined
  const hasRoles = Object.keys(roles).length > 0
  const hasSectionData = sectionData && Object.keys(sectionData).some(k => sectionData[k])

  if (!hasRoles && !hasSectionData) {
    return (
      <div>
        <h2 style={{ marginBottom: 16 }}>Milestones & Deliverables</h2>
        <p style={{ color: '#999' }}>팀 구성과 범위가 설정되면 마일스톤이 자동 생성됩니다. 채팅에서 "Milestones 작성해줘"라고 요청하세요.</p>
      </div>
    )
  }

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>Milestones & Deliverables</h2>

      {hasSectionData && (
        <div style={{ marginBottom: 16 }}>
          {Object.entries(sectionData).map(([key, val]) =>
            val ? (
              <div key={key} style={{ marginBottom: 8, padding: 8, background: '#fef9c3', borderRadius: 4 }}>
                <span style={{ fontWeight: 600 }}>{key}: </span>
                {String(val)}
                <span style={{ padding: '1px 5px', borderRadius: 4, fontSize: 9, fontWeight: 700, color: '#d97706', background: '#fef3c7', border: '1px solid #fde68a', marginLeft: 8 }}>AI</span>
              </div>
            ) : null
          )}
        </div>
      )}

      {hasRoles && (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
          <thead>
            <tr style={{ background: '#f9fafb' }}>
              {['Phase', 'Deliverables', '담당 역할'].map(h => (
                <th key={h} style={{ padding: '8px 6px', borderBottom: '2px solid #eee', textAlign: 'left' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {PHASES.map(p => (
              <tr key={p.id}>
                <td style={td}>{p.name}</td>
                <td style={td}>{p.deliverables}</td>
                <td style={td}>{Object.values(roles).map(r => r.display_name).join(', ')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

const td: React.CSSProperties = { padding: '8px 6px', borderBottom: '1px solid #eee' }
