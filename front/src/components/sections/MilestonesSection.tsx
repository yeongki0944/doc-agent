import { useCallback } from 'react'
import { useDocumentStore } from '../../store/documentStore'
import { useSessionStore } from '../../store/sessionStore'
import { EditableField } from '../EditableField'
import { saveUserInput } from '../../utils/api'
import { emitUserEdit } from '../../utils/userEditEvent'
import { color } from '../../styles/tokens'
import { resolveDisplayText } from '../../utils/frontendSchema'

const PHASES = [
  { id: 'discovery', name: 'Discovery', deliverables: '요구사항 문서, 아키텍처 초안' },
  { id: 'development', name: 'Development', deliverables: '에이전트 구현, API, UI' },
  { id: 'testing', name: 'Testing', deliverables: '통합 테스트, UAT, 최종 문서' },
]

export function MilestonesSection() {
  const roles = useDocumentStore(s => s.staffing_plan?.roles ?? {})
  const sectionData = useDocumentStore(s => s.sections?.milestones) as Record<string, any> | undefined
  const setDocument = useDocumentStore(s => s.setDocument)
  const docId = useSessionStore(s => s.currentDocId) || ''
  const hasRoles = Object.keys(roles).length > 0
  const hasSectionData = sectionData && Object.keys(sectionData).some(k => sectionData[k])

  const handleEdit = useCallback((key: string, newValue: string) => {
    const oldValue = sectionData?.[key] ?? ''
    const sections = useDocumentStore.getState().sections || {}
    const updated = { ...(sections.milestones || {}), [key]: newValue }
    setDocument({ sections: { ...sections, milestones: updated } } as any)
    saveUserInput(docId, `sections.milestones.${key}`, newValue).catch(() => {})
    emitUserEdit('Milestones', key, String(oldValue), newValue)
  }, [sectionData, docId, setDocument])

  if (!hasRoles && !hasSectionData) {
    return (
      <div>
        <h2 style={{ marginBottom: 16 }}>Milestones & Deliverables</h2>
        <p style={{ color: color.textMuted }}>팀 구성과 범위가 설정되면 마일스톤이 자동 생성됩니다. 채팅에서 "Milestones 작성해줘"라고 요청하세요.</p>
      </div>
    )
  }

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>Milestones & Deliverables</h2>

      {hasSectionData && (
        <div style={{ marginBottom: 16 }}>
          {Object.entries(sectionData!).map(([key, val]) =>
            val ? (
              <div key={key} style={{ marginBottom: 8, padding: 8, borderRadius: 4, border: `1px solid ${color.border}` }}>
                <span style={{ fontWeight: 600, marginRight: 4 }}>{key}: </span>
                <EditableField
                  value={String(val)}
                  isAi={true}
                  onSave={v => handleEdit(key, v)}
                  multiline={String(val).length > 60}
                />
              </div>
            ) : null
          )}
        </div>
      )}

      {hasRoles && (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
          <thead>
            <tr style={{ background: color.bgPrimary }}>
              {['Phase', 'Deliverables', '담당 역할'].map(h => (
                <th key={h} style={{ padding: '8px 6px', borderBottom: `2px solid ${color.border}`, textAlign: 'left' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {PHASES.map(p => (
              <tr key={p.id}>
                <td style={td}>{p.name}</td>
                <td style={td}>{p.deliverables}</td>
                <td style={td}>{Object.values(roles).map(r => resolveDisplayText(r.display_name, r.role_id)).join(', ')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

const td: React.CSSProperties = { padding: '8px 6px', borderBottom: `1px solid ${color.border}` }
