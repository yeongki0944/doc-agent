import { create } from 'zustand'
import { recalculateAll } from '../utils/staffingCalc'

export interface FieldValue {
  user_input: any
  ai_recommended: any
  calculated: any
  status: string
  user_edited?: boolean
  reason?: string
}

export type ServiceCategory = 'genai_core' | 'data' | 'compute' | 'network' | 'security' | 'monitoring'
export type RoleCategory = 'solution_architect' | 'engineer' | 'other'

export interface CategoryGroup {
  category_name: FieldValue
  items: FieldValue[]
}

export interface BusinessCase {
  problem_definition: FieldValue
  roi_calculation: FieldValue
  executive_sponsor: FieldValue
  production_commitment: FieldValue
}

export interface ExecutiveSummarySection {
  text?: FieldValue
  summary?: FieldValue
  customer_intro: FieldValue
  problem_statement: FieldValue
  proposed_solution: FieldValue
  phases_overview: FieldValue[]
  business_case: BusinessCase
}

export interface ScopeTask {
  task_category: FieldValue
  schedule: FieldValue
  details: FieldValue[]
  personnel: FieldValue
}

export interface ScopeOfWorkSection {
  items?: FieldValue[]
  tasks: ScopeTask[]
}

export interface SuccessCriteriaSection {
  items?: FieldValue[]
  groups: CategoryGroup[]
}

export interface AssumptionsSection {
  items?: FieldValue[]
  groups: CategoryGroup[]
}

export interface ArchitectureService {
  service_name: FieldValue
  service_id?: string
  priority: number
  category: ServiceCategory
  description: FieldValue
  sizing_rationale: FieldValue
  is_required_for_funding: boolean
}

export interface ArchitectureSection {
  overview?: FieldValue
  description?: FieldValue
  services: ArchitectureService[]
  diagram_image_s3_key?: string | null
  preview_url?: string | null
  drawio_url?: string | null
  tools?: any
  [key: string]: any
}

export interface FundingCalculation {
  yr1_arr: FieldValue
  sow_cost: FieldValue
  funding_25pct_arr: FieldValue
  funding_cap: number
  eligible_amount: FieldValue
  bedrock_included: boolean
  funding_type: string
}

export interface CostBreakdownSection {
  funding_calculation: FundingCalculation
  aws_service_cost?: Record<string, any>
  staffing_cost?: Record<string, any>
  document_local_summary?: Record<string, any>
  [key: string]: any
}

export interface ClientSignatureSection {
  customer_name: FieldValue
  authorized_person_name: FieldValue
  designation: FieldValue
  sign_date: FieldValue
}

export interface DocumentSections extends Record<string, any> {
  cover?: Record<string, any>
  executive_summary?: ExecutiveSummarySection
  success_criteria?: SuccessCriteriaSection
  assumptions?: AssumptionsSection
  scope_of_work?: ScopeOfWorkSection
  architecture?: ArchitectureSection
  milestones?: Record<string, any>
  cost_breakdown?: CostBreakdownSection
  acceptance?: Record<string, any>
  stakeholders?: Record<string, any>
  resources_cost_estimates?: Record<string, any>
  client_signatures?: ClientSignatureSection
}

export interface StaffingRole {
  role_id: string
  display_name: string | FieldValue
  category: RoleCategory
  role_type: FieldValue
  rate_default: FieldValue
  count: FieldValue
  allocation_pct: FieldValue
  rate_per_hour: FieldValue
  phase_hours: { discovery: FieldValue; development: FieldValue; testing: FieldValue }
  total_hours: { calculated: number | null }
  total_cost: { calculated: number | null }
  reason?: string
  source_patterns?: string[]
  user_edited?: boolean
}

export interface DocumentState {
  document_id: string
  mode: string
  version: number
  completion_score: number
  meta: { customer: FieldValue; partner: FieldValue; date: FieldValue }
  staffing_plan: { roles: Record<string, StaffingRole>; grand_total_hours: { calculated: number | null }; grand_total_cost: { calculated: number | null } }
  sections: DocumentSections
  sections_en?: Partial<DocumentSections>
  blocking_issues: any[]
  warnings: any[]
}

export type AgentStatus = 'processing' | 'idle' | 'error' | 'degraded'

const emptyField = (): FieldValue => ({ user_input: null, ai_recommended: null, calculated: null, status: 'empty' })

export const createFieldValue = (
  aiRecommended: any = null,
  userInput: any = null,
  calculated: any = null,
  status = 'empty',
): FieldValue => ({
  user_input: userInput,
  ai_recommended: aiRecommended,
  calculated,
  status,
})

const INITIAL_STATE: DocumentState = {
  document_id: '',
  mode: 'architecture_absent',
  version: 0,
  completion_score: 0.15,
  meta: { customer: { ...emptyField(), user_input: 'ABC Corp', status: 'confirmed' }, partner: { ...emptyField(), user_input: 'MZC', status: 'confirmed' }, date: { ...emptyField(), user_input: '2025-07-15', status: 'confirmed' } },
  staffing_plan: { roles: {}, grand_total_hours: { calculated: null }, grand_total_cost: { calculated: null } },
  sections: {},
  blocking_issues: [],
  warnings: [],
}

export interface PatchOperation {
  op: 'replace' | 'add' | 'remove'
  path: string
  value?: any
}

interface DocumentStore extends DocumentState {
  /** Agent status from AppSync status channel */
  agentStatus: AgentStatus
  /** Whether AppSync connection is active */
  appsyncConnected: boolean

  /** Full document replace — used only for REST fallback reload */
  setDocument: (doc: Partial<DocumentState>) => void
  /** Apply JSON Patch operations from AppSync patch channel (authoritative) */
  applyPatches: (operations: PatchOperation[]) => void
  /** Update a staffing role inline and recalculate */
  updateStaffingRole: (roleId: string, updates: Partial<StaffingRole>) => void
  /** Add a staffing role and recalculate totals */
  addStaffingRole: (roleId: string, role: StaffingRole) => void
  /** Set agent status from AppSync status channel */
  setAgentStatus: (status: AgentStatus) => void
  /** Set AppSync connection state */
  setAppsyncConnected: (connected: boolean) => void
}

/**
 * Set a nested value in an object using a JSON Pointer path (e.g. "/staffing_plan/roles/pm/count/ai_recommended").
 */
function setNestedValue(obj: any, path: string, value: any): any {
  const parts = path.split('/').filter(Boolean)
  if (parts.length === 0) return obj

  // Clone top-level
  const result = Array.isArray(obj) ? [...obj] : { ...obj }
  let current: any = result

  for (let i = 0; i < parts.length - 1; i++) {
    const key = parts[i]
    if (current[key] === undefined || current[key] === null) {
      current[key] = {}
    } else {
      current[key] = Array.isArray(current[key]) ? [...current[key]] : { ...current[key] }
    }
    current = current[key]
  }

  current[parts[parts.length - 1]] = value
  return result
}

/**
 * Remove a nested value in an object using a JSON Pointer path.
 */
function removeNestedValue(obj: any, path: string): any {
  const parts = path.split('/').filter(Boolean)
  if (parts.length === 0) return obj

  const result = Array.isArray(obj) ? [...obj] : { ...obj }
  let current: any = result

  for (let i = 0; i < parts.length - 1; i++) {
    const key = parts[i]
    if (current[key] === undefined) return result
    current[key] = Array.isArray(current[key]) ? [...current[key]] : { ...current[key] }
    current = current[key]
  }

  delete current[parts[parts.length - 1]]
  return result
}

export const useDocumentStore = create<DocumentStore>((set) => ({
  ...INITIAL_STATE,
  agentStatus: 'idle',
  appsyncConnected: false,

  setDocument: (doc) => set((s) => {
    // Full document replacement is intentionally limited to REST fallback
    // reloads. Agent-authored document mutations must arrive as patch events.
    const incomingMeta = doc.meta as DocumentState['meta'] | undefined
    const safeMeta = {
      customer: incomingMeta?.customer || s.meta.customer,
      partner: incomingMeta?.partner || s.meta.partner,
      date: incomingMeta?.date || s.meta.date,
    }
    const incomingSp = doc.staffing_plan as DocumentState['staffing_plan'] | undefined
    const safeSp = {
      roles: incomingSp?.roles || s.staffing_plan.roles,
      grand_total_hours: incomingSp?.grand_total_hours || s.staffing_plan.grand_total_hours,
      grand_total_cost: incomingSp?.grand_total_cost || s.staffing_plan.grand_total_cost,
    }
    return { ...s, ...doc, meta: safeMeta, staffing_plan: safeSp }
  }),

  applyPatches: (operations) => set((s) => {
    let state: any = { ...s }
    for (const op of operations) {
      switch (op.op) {
        case 'replace':
        case 'add':
          state = setNestedValue(state, op.path, op.value)
          break
        case 'remove':
          state = removeNestedValue(state, op.path)
          break
      }
    }
    return state
  }),

  updateStaffingRole: (roleId, updates) =>
    set((s) => {
      const newRoles = {
        ...s.staffing_plan.roles,
        [roleId]: { ...s.staffing_plan.roles[roleId], ...updates },
      }
      const recalculated = recalculateAll(newRoles)
      return { staffing_plan: recalculated }
    }),

  addStaffingRole: (roleId, role) =>
    set((s) => {
      const newRoles = {
        ...s.staffing_plan.roles,
        [roleId]: role,
      }
      const recalculated = recalculateAll(newRoles)
      return { staffing_plan: recalculated }
    }),

  setAgentStatus: (status) => set({ agentStatus: status }),
  setAppsyncConnected: (connected) => set({ appsyncConnected: connected }),
}))
