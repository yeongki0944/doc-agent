import { create } from 'zustand'

// --- Task 2.1: FieldStatus and FieldValue ---

export type FieldStatus = 'empty' | 'draft' | 'confirmed'

export interface FieldValue {
  user_input: any
  ai_recommended: any
  calculated: any
  status: FieldStatus
  user_edited?: boolean
}

export type ServiceCategory = 'genai_core' | 'data' | 'compute' | 'network' | 'security' | 'monitoring'

// --- Task 2.2: New interfaces ---

export interface ContactEntry {
  name: FieldValue
  title: FieldValue
  description: FieldValue
  stakeholder_for: FieldValue
  role: FieldValue
  contact: FieldValue
}

export interface TeamMember {
  role: FieldValue
  name: FieldValue
}

export type BulletLevel = 1 | 2

export interface StructuredBullet {
  text: FieldValue
  level: BulletLevel
}

export interface Phase {
  phase: FieldValue
  completion_date: FieldValue
  deliverables: StructuredBullet[]
}

export interface AcceptanceStep {
  heading: FieldValue
  content: FieldValue
  bullets: StructuredBullet[]
}

export interface CostBreakdownRow {
  category: FieldValue
  mrr: FieldValue
  arr: FieldValue
  note: FieldValue
}

export interface ContributionEntry {
  amount: FieldValue
  pct: FieldValue
}

export interface Contribution {
  customer: ContributionEntry
  partner: ContributionEntry
  aws: ContributionEntry
}

export interface PhaseHours {
  phase: FieldValue
  sa_hours: number
  eng_hours: number
  other_hours: number
  total: number
}

export interface RoleRate {
  role: string
  rate: FieldValue
}

export interface RoleHours {
  role: string
  hours: number
}

export interface ResourcePhaseHours {
  phase: FieldValue
  role_hours: RoleHours[]
  total: number
}

export interface TotalsRow {
  sa: string
  eng: string
  other: string
  total: string
}

export interface StakeholdersSection {
  executive_sponsors: ContactEntry[]
  stakeholders: ContactEntry[]
  project_team: ContactEntry[]
  escalation_contacts: ContactEntry[]
}

export interface ResourcesCostEstimatesSection {
  role_rates: RoleRate[]
  phase_hours_table: ResourcePhaseHours[]
  total_hours: TotalsRow
  total_cost: TotalsRow
  contribution: Contribution
  client_signature_customer_name: FieldValue
  client_signature_person_name: FieldValue
  client_signature_designation: FieldValue
  client_signature_date: FieldValue
}

export interface AcceptanceSectionData {
  steps: AcceptanceStep[]
}

export interface MilestonesSectionData {
  phases: Phase[]
}

// --- Task 2.3: Updated existing interfaces ---

export interface CategoryGroup {
  category_name: FieldValue
  bullets: StructuredBullet[]
}

export interface BusinessCase {
  problem_definition: FieldValue
  roi_calculation: FieldValue
  executive_sponsor: FieldValue
  production_commitment: FieldValue
}

export interface ExecutiveSummarySection {
  groups: CategoryGroup[]
}

export interface ScopeTask {
  task_category: FieldValue
  schedule: FieldValue
  details: StructuredBullet[]
  personnel: StructuredBullet[]
}

export interface ScopeOfWorkSection {
  items?: FieldValue[]
  tasks: ScopeTask[]
  out_of_scope?: FieldValue[]
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
  overview: FieldValue
  diagram_image_s3_key: FieldValue
  services: ArchitectureService[]
  tools_list: FieldValue[]
  preview_url?: string | null
  drawio_url?: string | null
}

export interface CostBreakdownSection {
  calculator_url: FieldValue
  mrr: FieldValue
  arr: FieldValue
  breakdown_table: CostBreakdownRow[]
  bedrock_extra: FieldValue
  funding_calculation: Record<string, any>
}

// --- Task 2.4: Removed legacy types ---
// Removed: ClientSignatureSection, StaffingRole, RoleCategory

// --- Task 2.5: Updated DocumentSections ---

export interface DocumentSections {
  cover?: Record<string, any>
  executive_summary?: ExecutiveSummarySection
  stakeholders?: StakeholdersSection
  success_criteria?: SuccessCriteriaSection
  assumptions?: AssumptionsSection
  scope_of_work?: ScopeOfWorkSection
  architecture?: ArchitectureSection
  milestones?: MilestonesSectionData
  cost_breakdown?: CostBreakdownSection
  resources_cost_estimates?: ResourcesCostEstimatesSection
  acceptance?: AcceptanceSectionData
}

// --- Task 2.4 / 2.6: Updated DocumentState (no staffing_plan) ---

export interface DocumentState {
  document_id: string
  mode: string
  version: number
  completion_score: number
  meta: { customer: FieldValue; partner: FieldValue; date: FieldValue }
  sections: DocumentSections
  sections_en?: Partial<DocumentSections>
  blocking_issues: any[]
  warnings: any[]
}

export type AgentStatus = 'processing' | 'idle' | 'error' | 'degraded'

const emptyField = (): FieldValue => ({ user_input: null, ai_recommended: null, calculated: null, status: 'empty', user_edited: false })

export const createFieldValue = (
  aiRecommended: any = null,
  userInput: any = null,
  calculated: any = null,
  status: FieldStatus = 'empty',
): FieldValue => ({
  user_input: userInput,
  ai_recommended: aiRecommended,
  calculated,
  status,
})

// --- Task 2.6: Updated INITIAL_STATE ---

const INITIAL_STATE: DocumentState = {
  document_id: '',
  mode: 'architecture_absent',
  version: 0,
  completion_score: 0,
  meta: {
    customer: emptyField(),
    partner: {
      user_input: null,
      ai_recommended: null,
      calculated: "MegazoneCloud",
      status: "confirmed" as FieldStatus,
      user_edited: false,
    },
    date: emptyField(),
  },
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
  /** Set agent status from AppSync status channel */
  setAgentStatus: (status: AgentStatus) => void
  /** Set AppSync connection state */
  setAppsyncConnected: (connected: boolean) => void
}

/**
 * Set a nested value in an object using a JSON Pointer path (e.g. "/sections/architecture/overview/user_input").
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
    // Map DynamoDB agent_status to store agentStatus
    const incomingAgentStatus = (doc as any).agent_status as AgentStatus | undefined
    const agentStatus = incomingAgentStatus || s.agentStatus

    return { ...s, ...doc, meta: safeMeta, agentStatus, agent_active: (doc as any).agent_active || '', agent_message: (doc as any).agent_message || '' }
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

  setAgentStatus: (status) => set({ agentStatus: status }),
  setAppsyncConnected: (connected) => set({ appsyncConnected: connected }),
}))
