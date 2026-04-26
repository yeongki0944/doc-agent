import { useDocumentStore } from '../../store/documentStore'

export function OverviewSection() {
  const overview = useDocumentStore(s => s.sections?.executive_summary) as Record<string, any> | undefined

  const hasContent = overview && Object.keys(overview).some(k => overview[k])

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>Executive Summary</h2>
      {hasContent ? (
        <div>
          {overview.summary && (
            <div style={{ padding: 16, background: '#fef9c3', borderRadius: 8, marginBottom: 12, lineHeight: 1.6 }}>
              <span style={{ padding: '1px 5px', borderRadius: 4, fontSize: 9, fontWeight: 700, color: '#d97706', background: '#fef3c7', border: '1px solid #fde68a', marginRight: 8 }}>AI</span>
              {overview.summary}
            </div>
          )}
          {Object.entries(overview).filter(([k]) => k !== 'summary').map(([key, val]) => (
            val ? (
              <div key={key} style={{ marginBottom: 8 }}>
                <span style={{ fontWeight: 600 }}>{key}: </span>
                <span>{String(val)}</span>
              </div>
            ) : null
          ))}
        </div>
      ) : (
        <p style={{ color: '#999' }}>프로젝트 개요가 아직 입력되지 않았습니다. 채팅에서 "Overview 작성해줘"라고 요청하세요.</p>
      )}
    </div>
  )
}
