import { useCallback } from 'react'
import { useDocumentStore, type FieldValue, type StaffingRole } from '../../store/documentStore'
import { useSessionStore } from '../../store/sessionStore'
import { AiBadge, isAiRecommended } from '../AiBadge'
import { saveUserInput } from '../../utils/api'
import { emitUserEdit } from '../../utils/userEditEvent'
import { color } from '../../styles/tokens'

const resolve = (f: FieldValue | undefined | null) => f?.user_input ?? f?.ai_recommended ?? f?.calculated ?? ''

export function TeamSection() {
  const roles = useDocumentStore(s => s.staffing_plan?.roles ?? {})
  const grandHours = useDocumentStore(s => s.staffing_plan?.grand_total_hours?.calculated ?? null)
  const grandCost = useDocumentStore(s => s.staffing_plan?.grand_total_cost?.calculated ?? null)
  const entries = Object.values(roles)

  if (entries.length === 0) {
    return (
      <div>
        <h2 style={{ marginBottom: 16 }}>Team / Staffing Plan</h2>
        <p style={{ color: color.textMuted }}>아직 팀 구성이 설정되지 않았습니다. 채팅에서 프로젝트 정보를 입력하면 AI가 추천합니다.</p>
        <p style={{ color: '#bbb', fontSize: 12, marginTop: 8 }}>
          ※ stakeholders 섹션은 연락처/조직 정보 전용입니다. 인력 편집은 이 Team 탭에서 수행합니다.
        </p>
      </div>
    )
  }

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>Team / Staffing Plan</h2>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
        <thead>
          <tr style={{ background: color.bgPrimary }}>
            {['역할','인원','할당(%)','시급($)','Discovery','Dev','Test','총시간','총비용($)'].map(h => (
              <th key={h} style={{ padding: '8px 6px', borderBottom: `2px solid ${color.border}`, textAlign: 'left', fontSize: 12 }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {entries.map(r => <RoleRow key={r.role_id} role={r} />)}
        </tbody>
        <tfoot>
          <tr style={{ fontWeight: 700, background: color.bgPrimary }}>
            <td colSpan={7} style={td}>Grand Total</td>
            <td style={td}>{grandHours ?? '—'}</td>
            <td style={td}>{grandCost != null ? `${grandCost.toLocaleString()}` : '—'}</td>
          </tr>
        </tfoot>
      </table>
    </div>
  )
}

function RoleRow({ role }: { role: StaffingRole }) {
  const updateRole = useDocumentStore(s => s.updateStaffingRole)
  const docId = useSessionStore(s => s.currentDocId) || ''

  /**
   * Inline edit handler: writes to staffing_plan.roles[roleId].{field}.user_input only.
   * Then triggers recalculateAll() locally and sends to REST API.
   */
  const handleChange = useCallback((field: string, value: string) => {
    const num = parseFloat(value)
    if (isNaN(num)) return

    // Build the user_input path for REST API
    let apiPath: string

    if (['discovery', 'development', 'testing'].includes(field)) {
      apiPath = `staffing_plan.roles.${role.role_id}.phase_hours.${field}.user_input`
      updateRole(role.role_id, {
        phase_hours: {
          ...role.phase_hours,
          [field]: {
            ...role.phase_hours[field as keyof typeof role.phase_hours],
            user_input: num,
            status: 'user_modified',
            user_edited: true,
          },
        },
      } as any)
    } else {
      apiPath = `staffing_plan.roles.${role.role_id}.${field}.user_input`
      updateRole(role.role_id, {
        [field]: {
          ...(role as any)[field],
          user_input: num,
          status: 'user_modified',
          user_edited: true,
        },
      } as any)
    }

    // Notify chat about user edit
    const oldVal = resolve((role as any)[field] ?? (role.phase_hours as any)[field])
    emitUserEdit('Team', `${role.display_name} > ${field}`, String(oldVal), value)

    // Send user_input change to REST API (fire-and-forget)
    saveUserInput(docId, apiPath, num).catch(() => {})
  }, [role, updateRole, docId])

  return (
    <tr>
      <td style={td}>
        {role.display_name}
        {role.reason && (
          <div style={{ fontSize: 11, color: color.textMuted, marginTop: 2 }}>{role.reason}</div>
        )}
      </td>
      <EditableCell field="count" value={resolve(role.count)} fieldValue={role.count} onChange={v => handleChange('count', v)} />
      <EditableCell field="allocation_pct" value={resolve(role.allocation_pct)} fieldValue={role.allocation_pct} onChange={v => handleChange('allocation_pct', v)} />
      <EditableCell field="rate_per_hour" value={resolve(role.rate_per_hour)} fieldValue={role.rate_per_hour} onChange={v => handleChange('rate_per_hour', v)} />
      <EditableCell field="discovery" value={resolve(role.phase_hours.discovery)} fieldValue={role.phase_hours.discovery} onChange={v => handleChange('discovery', v)} />
      <EditableCell field="development" value={resolve(role.phase_hours.development)} fieldValue={role.phase_hours.development} onChange={v => handleChange('development', v)} />
      <EditableCell field="testing" value={resolve(role.phase_hours.testing)} fieldValue={role.phase_hours.testing} onChange={v => handleChange('testing', v)} />
      <td style={td}>{role.total_hours.calculated ?? '—'}</td>
      <td style={td}>{role.total_cost.calculated != null ? `${role.total_cost.calculated.toLocaleString()}` : '—'}</td>
    </tr>
  )
}

function EditableCell({
  field,
  value,
  fieldValue,
  onChange,
}: {
  field: string
  value: any
  fieldValue: FieldValue | undefined | null
  onChange: (v: string) => void
}) {
  const isAi = isAiRecommended(fieldValue)

  return (
    <td style={td}>
      <div style={{ position: 'relative' }}>
        <input
          type="number"
          defaultValue={value}
          onBlur={e => onChange(e.target.value)}
          style={{
            width: '100%', border: '1px solid transparent', padding: '4px 6px', borderRadius: 4, fontSize: 14,
            background: isAi ? color.aiBadgeBg : 'transparent',
          }}
          onFocus={e => { e.target.style.borderColor = color.mzRed; e.target.style.background = color.bgSurface }}
          aria-label={field}
        />
        {isAi && (
          <span style={{ position: 'absolute', top: -6, right: 0 }}>
            <AiBadge />
          </span>
        )}
      </div>
    </td>
  )
}

const td: React.CSSProperties = { padding: '6px', borderBottom: `1px solid ${color.border}` }
