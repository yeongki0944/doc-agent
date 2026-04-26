import type { FieldValue, StaffingRole } from '../store/documentStore'

const resolve = (f: FieldValue): number => {
  const v = f.user_input ?? f.ai_recommended ?? f.calculated
  return typeof v === 'number' ? v : 0
}

export function calculateRoleTotalHours(role: StaffingRole): number {
  return resolve(role.phase_hours.discovery) + resolve(role.phase_hours.development) + resolve(role.phase_hours.testing)
}

export function calculateRoleTotalCost(role: StaffingRole): number {
  const count = resolve(role.count)
  const alloc = resolve(role.allocation_pct) / 100
  const rate = resolve(role.rate_per_hour)
  const hours = calculateRoleTotalHours(role)
  return Math.round(count * alloc * rate * hours * 100) / 100
}

export function recalculateAll(roles: Record<string, StaffingRole>) {
  let grandHours = 0
  let grandCost = 0
  const updated: Record<string, StaffingRole> = {}

  for (const [id, role] of Object.entries(roles)) {
    const totalHours = calculateRoleTotalHours(role)
    const totalCost = calculateRoleTotalCost(role)
    grandHours += totalHours
    grandCost += totalCost
    updated[id] = { ...role, total_hours: { calculated: totalHours }, total_cost: { calculated: totalCost } }
  }

  return { roles: updated, grand_total_hours: { calculated: Math.round(grandHours * 100) / 100 }, grand_total_cost: { calculated: Math.round(grandCost * 100) / 100 } }
}
