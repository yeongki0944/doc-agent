import { apiFetch } from '../auth/api'

export async function saveUserInput(docId: string, path: string, value: any): Promise<void> {
  await apiFetch(`/documents/${docId}/user-input`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, value, edited_by: 'user' }),
  })
}

export async function getDocument(docId: string): Promise<any> {
  const res = await apiFetch(`/documents/${docId}`)
  if (!res.ok) throw new Error(`Failed to fetch document: ${res.status}`)
  return res.json()
}

/**
 * Request a submission readiness review. Uses the document_api
 * `run_submission_lint` endpoint which returns readiness_score, issues,
 * missing_questions, and suggested_patches.
 */
export async function requestReview(docId: string): Promise<ReviewResult> {
  const res = await apiFetch(`/documents/${docId}/run_submission_lint`, { method: 'POST' })
  if (!res.ok) {
    // Fallback to legacy /review for older deployments
    try {
      const legacy = await apiFetch(`/documents/${docId}/review`, { method: 'POST' })
      if (legacy.ok) return legacy.json()
    } catch { /* ignore */ }
    throw new Error(`Review request failed: ${res.status}`)
  }
  return res.json()
}

export async function requestExport(docId: string): Promise<any> {
  const res = await apiFetch(`/documents/${docId}/export`, { method: 'POST' })
  return res.json()
}

export interface ReviewIssue {
  code: string
  message: string
  section: string
  severity?: string
  question?: string
}

export interface ReviewResult {
  readiness_score?: number
  issues?: {
    critical?: ReviewIssue[]
    high?: ReviewIssue[]
    medium?: ReviewIssue[]
    low?: ReviewIssue[]
  }
  missing_questions?: string[]
  suggested_patches?: Array<{ op: string; path: string; value?: any; reason?: string }>
  kb_retrieval?: any
  error?: string
}

export interface ResourcePlanInput {
  target_funding_amount?: number
  mrr?: number
  arr?: number
  sow_cost?: number
  assumptions?: string[]
}

export interface ResourcePlanResult {
  target_funding_amount: number
  required_arr: number
  sow_cost_requirement: number
  cap_check: { cap: number; cap_limited: boolean }
  eligible_funding_amount: number
  formula: string
  draft_resource_matrix?: {
    role_rates: Array<{ role: string; rate: any }>
    phase_hours_table: Array<{ phase: any; role_hours: Array<{ role: string; hours: number }>; total: number }>
    matrix_orientation?: string
  }
  contribution_distribution?: Record<string, { amount: any; pct: any }>
  warnings?: string[]
  assumptions?: string[]
  error?: string
}

export async function calculateResourcePlan(
  docId: string,
  body: ResourcePlanInput,
): Promise<ResourcePlanResult> {
  const res = await apiFetch(`/documents/${docId}/calculate_resource_plan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`Resource plan failed: ${res.status}`)
  return res.json()
}

export interface ChangeRequestChange {
  section?: string
  as_is?: any
  to_be?: any
  reason?: string
  json_patch?: any[]
}

export interface ChangeRequest {
  change_request_id: string
  document_id?: string
  requester?: string
  status: 'pending' | 'approved' | 'rejected'
  summary?: string
  changes?: ChangeRequestChange[]
  json_patch?: any[]
  created_at?: string
  updated_at?: string
  reviewed_by?: string
  reviewed_at?: string
}

export async function approveChangeRequest(docId: string, changeRequestId: string): Promise<any> {
  const res = await apiFetch(`/documents/${docId}/approve_change_request`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ change_request_id: changeRequestId }),
  })
  if (!res.ok) throw new Error(`approve failed: ${res.status}`)
  return res.json()
}

export async function rejectChangeRequest(docId: string, changeRequestId: string): Promise<any> {
  const res = await apiFetch(`/documents/${docId}/reject_change_request`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ change_request_id: changeRequestId }),
  })
  if (!res.ok) throw new Error(`reject failed: ${res.status}`)
  return res.json()
}
