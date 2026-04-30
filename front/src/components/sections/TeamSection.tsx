import { useEffect, useMemo, useState } from 'react'
import { useDocumentStore, type FieldValue, type RoleCategory, type StaffingRole } from '../../store/documentStore'
import { useSessionStore } from '../../store/sessionStore'
import { saveUserInput } from '../../utils/api'
import { createRoleDraft, buildStaffingEditPath, getRoleOptions, resolveDisplayText, sortStaffingRoles } from '../../utils/frontendSchema'
import { emitUserEdit } from '../../utils/userEditEvent'
import { color } from '../../styles/tokens'
import { resolveFieldValue } from '../AiBadge'
const DEFAULT_PHASES = ['discovery', 'development', 'testing'] as const

function resolveValue(f: FieldValue | undefined | null) {
  return resolveFieldValue(f) ?? ''
}

function formatCalculated(value: any) {
  const resolved = resolveFieldValue(value)
  if (resolved == null || resolved === '') return '—'
  const num = Number(resolved)
  return Number.isNaN(num) ? String(resolved) : num.toLocaleString()
}

export function TeamSection() {
  const roles = useDocumentStore(s => s.staffing_plan?.roles ?? {})
  const grandHours = useDocumentStore(s => s.staffing_plan?.grand_total_hours?.calculated ?? null)
  const grandCost = useDocumentStore(s => s.staffing_plan?.grand_total_cost?.calculated ?? null)
  const addStaffingRole = useDocumentStore(s => s.addStaffingRole)
  const updateStaffingRole = useDocumentStore(s => s.updateStaffingRole)
  const docId = useSessionStore(s => s.currentDocId) || ''

  const [selectedCategory, setSelectedCategory] = useState<RoleCategory>('solution_architect')
  const [selectedRoleType, setSelectedRoleType] = useState<string>(getRoleOptions('solution_architect')[0]?.role_id || 'solution_architect')

  const selectedOption = useMemo(
    () => getRoleOptions(selectedCategory).find(option => option.role_id === selectedRoleType) ?? getRoleOptions(selectedCategory)[0],
    [selectedCategory, selectedRoleType],
  )

  const entries = useMemo(() => sortStaffingRoles(roles), [roles])

  const handleCategoryChange = (category: RoleCategory) => {
    setSelectedCategory(category)
    const nextOption = getRoleOptions(category)[0]
    setSelectedRoleType(nextOption?.role_id || category)
  }

  const handleAddRole = () => {
    if (!selectedOption) return
    const baseId = selectedOption.role_id
    let roleId = baseId
    let suffix = 2
    while (roles[roleId]) {
      roleId = `${baseId}_${suffix}`
      suffix += 1
    }

    const draft = createRoleDraft(selectedCategory, selectedOption.role_id)
    const inserted: StaffingRole = { ...draft, role_id: roleId }
    addStaffingRole(roleId, inserted)

    const updates = [
      saveUserInput(docId, buildStaffingEditPath(roleId, 'role_type'), selectedOption.role_id),
      saveUserInput(docId, buildStaffingEditPath(roleId, 'display_name'), selectedOption.display_name),
      saveUserInput(docId, buildStaffingEditPath(roleId, 'rate_default'), String(selectedOption.rate_default)),
      saveUserInput(docId, `staffing_plan.roles.${roleId}.category.user_input`, selectedCategory),
      saveUserInput(docId, buildStaffingEditPath(roleId, 'count'), '1'),
      saveUserInput(docId, buildStaffingEditPath(roleId, 'allocation_pct'), '100'),
      saveUserInput(docId, buildStaffingEditPath(roleId, 'rate_per_hour'), String(selectedOption.rate_default)),
    ]
    for (const phase of DEFAULT_PHASES) {
      updates.push(saveUserInput(docId, buildStaffingEditPath(roleId, 'phase_hours', phase), '0'))
    }
    void Promise.all(updates).catch(() => {})
  }

  if (entries.length === 0) {
    return (
      <div>
        <h2 style={{ marginBottom: 16 }}>Team / Staffing Plan</h2>
        <p style={{ color: color.textMuted }}>아직 팀 구성이 설정되지 않았습니다. 새 역할을 추가하거나 채팅에서 프로젝트 정보를 입력하면 AI가 추천합니다.</p>
        <p style={{ color: '#bbb', fontSize: 12, marginTop: 8 }}>
          ※ stakeholders 섹션은 연락처/조직 정보 전용입니다. 인력 편집은 이 Team 탭에서 수행합니다.
        </p>
        <AddRolePanel
          selectedCategory={selectedCategory}
          selectedRoleType={selectedRoleType}
          onCategoryChange={handleCategoryChange}
          onRoleTypeChange={setSelectedRoleType}
          onAddRole={handleAddRole}
        />
      </div>
    )
  }

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>Team / Staffing Plan</h2>
      <AddRolePanel
        selectedCategory={selectedCategory}
        selectedRoleType={selectedRoleType}
        onCategoryChange={handleCategoryChange}
        onRoleTypeChange={setSelectedRoleType}
        onAddRole={handleAddRole}
      />
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14, marginTop: 16 }}>
        <thead>
          <tr style={{ background: color.bgPrimary }}>
            {['역할', '카테고리', '타입', '인원', '할당(%)', '시급($)', 'Discovery', 'Dev', 'Test', '총시간', '총비용($)'].map(h => (
              <th key={h} style={{ padding: '8px 6px', borderBottom: `2px solid ${color.border}`, textAlign: 'left', fontSize: 12 }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {entries.map(r => <RoleRow key={r.role_id} role={r} docId={docId} onEdit={updateStaffingRole} />)}
        </tbody>
        <tfoot>
          <tr style={{ fontWeight: 700, background: color.bgPrimary }}>
            <td colSpan={9} style={td}>Grand Total</td>
            <td style={td}>{grandHours ?? '—'}</td>
            <td style={td}>{grandCost != null ? grandCost.toLocaleString() : '—'}</td>
          </tr>
        </tfoot>
      </table>
    </div>
  )
}

function AddRolePanel({
  selectedCategory,
  selectedRoleType,
  onCategoryChange,
  onRoleTypeChange,
  onAddRole,
}: {
  selectedCategory: RoleCategory
  selectedRoleType: string
  onCategoryChange: (category: RoleCategory) => void
  onRoleTypeChange: (roleType: string) => void
  onAddRole: () => void
}) {
  const roleOptions = getRoleOptions(selectedCategory)
  const selectedOption = roleOptions.find(option => option.role_id === selectedRoleType) ?? roleOptions[0]

  return (
    <div style={{ padding: 12, border: `1px solid ${color.border}`, borderRadius: 8, background: color.bgPrimary }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr)) auto', gap: 8, alignItems: 'end' }}>
        <label style={labelStyle}>
          <span style={labelText}>Category</span>
          <select
            value={selectedCategory}
            onChange={e => onCategoryChange(e.target.value as RoleCategory)}
            style={selectStyle}
            aria-label="role-category"
          >
            <option value="solution_architect">solution_architect</option>
            <option value="engineer">engineer</option>
            <option value="other">other</option>
          </select>
        </label>
        <label style={labelStyle}>
          <span style={labelText}>Role Type</span>
          <select
            value={selectedRoleType}
            onChange={e => onRoleTypeChange(e.target.value)}
            style={selectStyle}
            aria-label="role-type"
          >
            {roleOptions.map(option => (
              <option key={option.role_id} value={option.role_id}>
                {option.display_name}
              </option>
            ))}
          </select>
        </label>
        <label style={labelStyle}>
          <span style={labelText}>Display Name</span>
          <input value={selectedOption?.display_name ?? ''} readOnly style={inputStyle} aria-label="display-name-preview" />
        </label>
        <label style={labelStyle}>
          <span style={labelText}>Rate Default</span>
          <input value={selectedOption?.rate_default ?? 0} readOnly style={inputStyle} aria-label="rate-default-preview" />
        </label>
        <button type="button" onClick={onAddRole} style={addButtonStyle}>
          Add Role
        </button>
      </div>
    </div>
  )
}

function RoleRow({
  role,
  docId,
  onEdit,
}: {
  role: StaffingRole
  docId: string
  onEdit: (roleId: string, updates: Partial<StaffingRole>) => void
}) {
  const phaseFields = ['discovery', 'development', 'testing'] as const

  const saveField = (field: string, value: string) => {
    const path = field === 'display_name'
      ? buildStaffingEditPath(role.role_id, field)
      : buildStaffingEditPath(role.role_id, field)
    saveUserInput(docId, path, value).catch(() => {})
  }

  const updateNumericField = (field: keyof Pick<StaffingRole, 'count' | 'allocation_pct' | 'rate_per_hour'>, value: string) => {
    const num = Number(value)
    if (Number.isNaN(num)) return
    const roleName = resolveDisplayText(role.display_name, role.role_id)
    onEdit(role.role_id, {
      [field]: {
        ...(role[field] as FieldValue),
        user_input: num,
        status: 'user_modified',
        user_edited: true,
      },
    } as Partial<StaffingRole>)
    saveField(field, value)
    emitUserEdit('Team', `${roleName} > ${field}`, String(resolveValue(role[field] as FieldValue)), value)
  }

  const updatePhaseField = (phase: typeof phaseFields[number], value: string) => {
    const num = Number(value)
    if (Number.isNaN(num)) return
    onEdit(role.role_id, {
      phase_hours: {
        ...role.phase_hours,
        [phase]: {
          ...role.phase_hours[phase],
          user_input: num,
          status: 'user_modified',
          user_edited: true,
        },
      },
    })
    saveField(`phase_hours.${phase}`, value)
    emitUserEdit('Team', `${resolveDisplayText(role.display_name, role.role_id)} > ${phase}`, String(resolveValue(role.phase_hours[phase])), value)
  }

  const updateDisplayName = (value: string) => {
    onEdit(role.role_id, {
      display_name: value,
    })
    saveField('display_name', value)
    emitUserEdit('Team', 'display_name', resolveDisplayText(role.display_name, role.role_id), value)
  }

  const displayName = resolveDisplayText(role.display_name, role.role_id)

  return (
    <tr>
      <td style={td}>
        <EditableTextCell
          value={displayName}
          onSave={updateDisplayName}
          ariaLabel={`${role.role_id}-display-name`}
        />
      </td>
      <td style={td}>
        <span style={pillStyle}>{resolveDisplayText(role.category, 'other')}</span>
      </td>
      <td style={td}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span>{resolveValue(role.role_type)}</span>
          <span style={{ fontSize: 11, color: color.textMuted }}>default {resolveValue(role.rate_default)}</span>
        </div>
      </td>
      <EditableNumberCell value={resolveValue(role.count)} onSave={v => updateNumericField('count', v)} ariaLabel={`${role.role_id}-count`} />
      <EditableNumberCell value={resolveValue(role.allocation_pct)} onSave={v => updateNumericField('allocation_pct', v)} ariaLabel={`${role.role_id}-allocation`} />
      <EditableNumberCell value={resolveValue(role.rate_per_hour)} onSave={v => updateNumericField('rate_per_hour', v)} ariaLabel={`${role.role_id}-rate`} />
      {phaseFields.map(phase => (
        <EditableNumberCell
          key={phase}
          value={resolveValue(role.phase_hours[phase])}
          onSave={v => updatePhaseField(phase, v)}
          ariaLabel={`${role.role_id}-${phase}`}
        />
      ))}
      <td style={td}>{formatCalculated(role.total_hours?.calculated)}</td>
      <td style={td}>{formatCalculated(role.total_cost?.calculated)}</td>
    </tr>
  )
}

function EditableNumberCell({
  value,
  onSave,
  ariaLabel,
}: {
  value: any
  onSave: (v: string) => void
  ariaLabel: string
}) {
  const [draft, setDraft] = useState(String(value ?? ''))

  useEffect(() => {
    setDraft(String(value ?? ''))
  }, [value])

  return (
    <td style={td}>
      <input
        type="number"
        value={draft}
        onChange={e => setDraft(e.target.value)}
        onBlur={() => onSave(draft)}
        onKeyDown={e => {
          if (e.key === 'Enter') {
            e.preventDefault()
            onSave(draft)
          }
        }}
        style={numberInputStyle}
        aria-label={ariaLabel}
      />
    </td>
  )
}

function EditableTextCell({
  value,
  onSave,
  ariaLabel,
}: {
  value: string
  onSave: (v: string) => void
  ariaLabel: string
}) {
  const [draft, setDraft] = useState(value)

  useEffect(() => {
    setDraft(value)
  }, [value])

  return (
    <input
      value={draft}
      onChange={e => setDraft(e.target.value)}
      onBlur={() => {
        if (draft !== value) onSave(draft)
      }}
      onKeyDown={e => {
        if (e.key === 'Enter') {
          e.preventDefault()
          if (draft !== value) onSave(draft)
        }
      }}
      style={textInputStyle}
      aria-label={ariaLabel}
    />
  )
}

const td: React.CSSProperties = { padding: '6px', borderBottom: `1px solid ${color.border}` }
const labelStyle: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: 4 }
const labelText: React.CSSProperties = { fontSize: 11, color: color.textMuted, fontWeight: 600 }
const selectStyle: React.CSSProperties = { border: `1px solid ${color.border}`, borderRadius: 6, padding: '7px 8px', fontSize: 13, background: color.bgSurface }
const inputStyle: React.CSSProperties = { border: `1px solid ${color.border}`, borderRadius: 6, padding: '7px 8px', fontSize: 13, background: color.bgSurface }
const textInputStyle: React.CSSProperties = { border: `1px solid ${color.border}`, borderRadius: 6, padding: '7px 8px', fontSize: 13, width: '100%', background: color.bgSurface }
const numberInputStyle: React.CSSProperties = { border: `1px solid ${color.border}`, borderRadius: 6, padding: '6px 8px', fontSize: 13, width: '100%', background: color.bgSurface }
const addButtonStyle: React.CSSProperties = { border: 'none', borderRadius: 6, padding: '9px 14px', background: color.mzRed, color: color.bgSurface, cursor: 'pointer', fontWeight: 600, height: 36 }
const pillStyle: React.CSSProperties = { display: 'inline-flex', padding: '2px 8px', borderRadius: 999, fontSize: 11, background: color.bgSubtle, color: color.textSecondary }
