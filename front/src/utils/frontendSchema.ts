import rolePool from '../data/role_pool.json'
import type { ArchitectureService, FieldValue, RoleCategory, StaffingRole } from '../store/documentStore'

type RolePoolOption = {
  role_id: string
  display_name: string
  rate_default: number
}

type RolePool = Record<RoleCategory, RolePoolOption[]>

export const ROLE_POOL = rolePool as RolePool

const makeFieldValue = (aiRecommended: any = null, status = 'recommended'): FieldValue => ({
  user_input: null,
  ai_recommended: aiRecommended,
  calculated: null,
  status,
})

const resolve = (value: any): string => {
  if (value && typeof value === 'object') {
    return String(value.user_input ?? value.ai_recommended ?? value.calculated ?? '')
  }
  return String(value ?? '')
}

export function resolveDisplayText(value: any, fallback = ''): string {
  const text = resolve(value)
  return text || fallback
}

export function getRoleOptions(category: RoleCategory): RolePoolOption[] {
  return ROLE_POOL[category] ?? []
}

export function createRoleDraft(category: RoleCategory, roleTypeId: string): StaffingRole {
  const option = getRoleOptions(category).find(item => item.role_id === roleTypeId) || {
    role_id: roleTypeId,
    display_name: roleTypeId,
    rate_default: 0,
  }

  return {
    role_id: roleTypeId,
    display_name: option.display_name,
    category,
    role_type: makeFieldValue(option.role_id),
    rate_default: makeFieldValue(option.rate_default),
    count: makeFieldValue(1),
    allocation_pct: makeFieldValue(100),
    rate_per_hour: makeFieldValue(option.rate_default),
    phase_hours: {
      discovery: makeFieldValue(0),
      development: makeFieldValue(0),
      testing: makeFieldValue(0),
    },
    total_hours: { calculated: 0 },
    total_cost: { calculated: 0 },
    reason: 'role_pool default',
  }
}

export function buildStaffingEditPath(roleId: string, field: string, subfield?: string) {
  const tail = subfield ? `${field}.${subfield}` : field
  return `staffing_plan.roles.${roleId}.${tail}.user_input`
}

export function sortStaffingRoles(roles: Record<string, StaffingRole>): StaffingRole[] {
  return Object.values(roles).sort((a, b) => resolveDisplayText(a.display_name).localeCompare(resolveDisplayText(b.display_name)))
}

export function sortArchitectureServices(services: ArchitectureService[]): ArchitectureService[] {
  return [...services].sort((a, b) => (a.priority ?? 99) - (b.priority ?? 99) || resolve(a.service_name).localeCompare(resolve(b.service_name)))
}

export function isBedrockService(service: ArchitectureService | Record<string, any>): boolean {
  const name = resolve((service as ArchitectureService).service_name ?? service.service_name).toLowerCase()
  const id = String((service as ArchitectureService).service_id ?? service.service_id ?? '').toLowerCase()
  return name.includes('bedrock') || id.includes('bedrock')
}

export function formatMoney(value: any): string {
  const resolved = resolve(value)
  if (resolved === '' || resolved === 'null' || resolved === 'undefined') return '—'
  const num = Number(resolved.replace(/,/g, ''))
  if (Number.isNaN(num)) return resolved
  return num.toLocaleString()
}

export function getFundingEligibility(blockingIssues: any[], funding: any): 'eligible' | 'ineligible' | 'pending' {
  if (blockingIssues.length > 0) return 'ineligible'
  const eligible = resolve(funding?.eligible_amount)
  if (!eligible) return 'pending'
  return Number(eligible.replace(/,/g, '')) > 0 ? 'eligible' : 'ineligible'
}
