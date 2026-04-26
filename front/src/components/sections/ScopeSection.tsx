import { useDocumentStore } from '../../store/documentStore'

export function ScopeSection() {
  const sectionData = useDocumentStore(s => s.sections?.scope_of_work) as Record<string, any> | undefined
  const hasContent = sectionData && Object.keys(sectionData).some(k => sectionData[k])

  if (!hasContent) {
    return (
      <div>
        <h2 style={{ marginBottom: 16 }}>Scope of Work</h2>
        <p style={{ color: '#999' }}>프로젝트 범위가 아직 정의되지 않았습니다. 채팅에서 "Scope 작성해줘"라고 요청하세요.</p>
      </div>
    )
  }

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>Scope of Work</h2>
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
  )
}
