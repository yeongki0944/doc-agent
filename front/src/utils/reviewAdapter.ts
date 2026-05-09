/**
 * Review Adapter
 *
 * Converts a backend `run_submission_lint` response (which only surfaces
 * triggered issues) into a full rule evaluation matrix suitable for the
 * new Review Panel. If the backend later starts returning
 * `rule_evaluations[]` directly, that payload is preferred and the
 * catalog is used only to enrich display metadata.
 */

import type { ReviewIssue, ReviewResult } from './api'
import {
  CATEGORIES,
  REVIEW_RULES,
  RULE_BY_ISSUE_CODE,
  RULES_BY_ID,
  type CategoryKey,
  type RuleDefinition,
  type RuleSeverity,
  type RuleStatus,
} from '../constants/reviewRules'

export interface EvidenceItem {
  section: string
  snippet: string
  fieldPath?: string
}

export interface SuggestedPatchRef {
  op: string
  path: string
  value?: any
  reason?: string
}

export interface RuleEvaluation {
  ruleId: string
  rule: RuleDefinition
  status: RuleStatus
  severity: RuleSeverity
  /** Short LLM-style judgment sentence explaining the verdict. */
  judgment: string
  /** Free-form summary shown in the detail drawer. */
  judgmentDetail: string
  /** Evidence found in the document that supports the verdict. */
  evidenceFound: EvidenceItem[]
  /** Missing information / evidence. */
  missingEvidence: string[]
  /** Document sections referenced by this rule. */
  referencedSections: string[]
  /** Recommendation when status is not PASS. */
  recommendation: string
  /** Optional suggested patch (only populated when triggered by backend). */
  suggestedPatch?: SuggestedPatchRef
  /** Raw backend issue, if any. */
  backendIssue?: ReviewIssue & { severity?: string }
  /** Whether this rule matched a backend rule_evaluations entry. */
  fromBackend: boolean
}

export interface CategoryCoverage {
  key: CategoryKey
  label: string
  total: number
  pass: number
  warning: number
  fail: number
  notChecked: number
}

export interface ReviewMatrix {
  readinessScore: number
  evaluations: RuleEvaluation[]
  categories: CategoryCoverage[]
  summary: {
    total: number
    pass: number
    warning: number
    fail: number
    notChecked: number
  }
  /** True when the backend did not return rule_evaluations and we adapted from issues[]. */
  adapted: boolean
}

/**
 * Backend may one day return rule_evaluations[] on the review result. Shape
 * is kept permissive — unknown fields are preserved.
 */
interface BackendRuleEvaluation {
  rule_id: string
  status?: string
  severity?: string
  judgment?: string
  judgment_detail?: string
  evidence?: Array<{ section?: string; snippet?: string; field_path?: string } | string>
  missing_evidence?: string[]
  recommendation?: string
  suggested_patch?: SuggestedPatchRef
}

interface ReviewResultWithEvaluations extends ReviewResult {
  rule_evaluations?: BackendRuleEvaluation[]
}

const SEVERITY_MAP: Record<string, RuleSeverity> = {
  critical: 'Critical',
  high: 'High',
  medium: 'Medium',
  low: 'Low',
  info: 'Info',
}

function normalizeStatus(raw: string | undefined): RuleStatus | null {
  if (!raw) return null
  const v = String(raw).toUpperCase()
  if (v === 'PASS' || v === 'WARNING' || v === 'FAIL' || v === 'NOT_CHECKED') {
    return v
  }
  return null
}

function normalizeSeverity(raw: string | undefined, fallback: RuleSeverity): RuleSeverity {
  if (!raw) return fallback
  const k = String(raw).toLowerCase()
  return SEVERITY_MAP[k] || fallback
}

/**
 * Flatten backend issues into a single map keyed by issue code so we can
 * quickly look up whether a given rule tripped.
 */
function flattenIssues(issues: ReviewResult['issues']): Map<string, ReviewIssue & { severity: string }> {
  const out = new Map<string, ReviewIssue & { severity: string }>()
  if (!issues) return out
  for (const sev of ['critical', 'high', 'medium', 'low'] as const) {
    const list = issues[sev] || []
    for (const iss of list) {
      if (!iss?.code) continue
      out.set(iss.code, { ...iss, severity: sev })
    }
  }
  return out
}

/**
 * Derive judgment text for a rule that did NOT produce a backend issue.
 * This is a deterministic string — we do not fabricate LLM reasoning.
 */
function derivePassJudgment(rule: RuleDefinition): { judgment: string; detail: string } {
  return {
    judgment: '해당 규칙을 트리거하는 이슈가 감지되지 않았습니다.',
    detail: `문서에서 ${rule.title}에 해당하는 결함이 발견되지 않았습니다. 백엔드 submission lint가 이 규칙에 대한 이슈를 생성하지 않았습니다.`,
  }
}

function deriveFailJudgment(
  rule: RuleDefinition,
  issue: ReviewIssue & { severity: string },
): { judgment: string; detail: string } {
  return {
    judgment: issue.message || `${rule.title} — 평가 결과 이슈가 감지되었습니다.`,
    detail: [
      issue.message,
      issue.question ? `열린 질문: ${issue.question}` : '',
      issue.section ? `관련 섹션: ${issue.section}` : '',
    ]
      .filter(Boolean)
      .join('\n\n'),
  }
}

function deriveStatusFromSeverity(severity: string): RuleStatus {
  // critical/high → FAIL, medium/low → WARNING
  const k = severity.toLowerCase()
  if (k === 'critical' || k === 'high') return 'FAIL'
  return 'WARNING'
}

/**
 * Scan suggested_patches[] for a patch that relates to a rule's section
 * references. Used to surface a "Create Change Request" action on FAIL rows.
 */
function matchSuggestedPatch(
  rule: RuleDefinition,
  patches: NonNullable<ReviewResult['suggested_patches']>,
): SuggestedPatchRef | undefined {
  if (!patches || patches.length === 0) return undefined
  const sections = new Set(rule.sectionRefs)
  for (const p of patches) {
    if (!p?.path) continue
    const parts = p.path.replace(/^\//, '').split('/')
    const section = parts[0] === 'sections' && parts[1] ? parts[1] : parts[0]
    if (sections.has(section)) {
      return { op: p.op, path: p.path, value: p.value, reason: p.reason }
    }
  }
  return undefined
}

/**
 * Build a full evaluation matrix from a backend review result. Uses
 * rule_evaluations[] when present, otherwise adapts from issues[].
 */
export function buildReviewMatrix(result: ReviewResult | null | undefined): ReviewMatrix {
  const res = (result || {}) as ReviewResultWithEvaluations
  const suggested = res.suggested_patches || []
  const backendEvals = Array.isArray(res.rule_evaluations) ? res.rule_evaluations : null

  let evaluations: RuleEvaluation[] = []
  let adapted = false

  if (backendEvals && backendEvals.length > 0) {
    // Prefer backend-provided rule_evaluations
    const seen = new Set<string>()
    for (const be of backendEvals) {
      if (!be?.rule_id) continue
      const rule = RULES_BY_ID[be.rule_id]
      if (!rule) continue
      seen.add(rule.id)
      const status = normalizeStatus(be.status) || 'NOT_CHECKED'
      const severity = normalizeSeverity(be.severity, rule.severity)
      evaluations.push({
        ruleId: rule.id,
        rule,
        status,
        severity,
        judgment: be.judgment || derivePassJudgment(rule).judgment,
        judgmentDetail: be.judgment_detail || be.judgment || '',
        evidenceFound: normalizeEvidence(be.evidence),
        missingEvidence: Array.isArray(be.missing_evidence) ? be.missing_evidence : [],
        referencedSections: rule.sectionRefs,
        recommendation: be.recommendation || rule.recommendation,
        suggestedPatch: be.suggested_patch || matchSuggestedPatch(rule, suggested),
        fromBackend: true,
      })
    }
    // Add catalog rules that backend didn't evaluate as NOT_CHECKED
    for (const rule of REVIEW_RULES) {
      if (seen.has(rule.id)) continue
      evaluations.push(notCheckedEvaluation(rule))
    }
  } else {
    // Adapt from issues[]
    adapted = true
    const issueMap = flattenIssues(res.issues)
    for (const rule of REVIEW_RULES) {
      const hit = rule.issueCodes.map(c => issueMap.get(c)).find(Boolean)
      if (hit) {
        const status = deriveStatusFromSeverity(hit.severity)
        const severity = normalizeSeverity(hit.severity, rule.severity)
        const { judgment, detail } = deriveFailJudgment(rule, hit)
        evaluations.push({
          ruleId: rule.id,
          rule,
          status,
          severity,
          judgment,
          judgmentDetail: detail,
          evidenceFound: [],
          missingEvidence: buildMissingFromIssue(rule, hit),
          referencedSections: rule.sectionRefs,
          recommendation: rule.recommendation,
          suggestedPatch: matchSuggestedPatch(rule, suggested),
          backendIssue: hit,
          fromBackend: false,
        })
      } else if (rule.id === 'RULE_ARCH_COST_ALIGNMENT') {
        // Derived rule: FAIL only if both architecture and cost issues triggered
        const archMissing = issueMap.has('ARCHITECTURE_INCOMPLETE') || issueMap.has('ARCHITECTURE_OVERVIEW_MISSING')
        const costMissing = issueMap.has('COST_BREAKDOWN_INCOMPLETE')
        if (archMissing && costMissing) {
          evaluations.push({
            ruleId: rule.id,
            rule,
            status: 'FAIL',
            severity: 'Medium',
            judgment: 'Architecture와 Cost Breakdown 모두 채워지지 않아 비용 정합성을 판정할 수 없습니다.',
            judgmentDetail:
              'Architecture 섹션과 Cost Breakdown 섹션이 모두 불완전합니다. 아키텍처 서비스가 비용에 반영되는지 확인할 수 없습니다.',
            evidenceFound: [],
            missingEvidence: ['Architecture services', 'Cost Breakdown aws_service_cost'],
            referencedSections: rule.sectionRefs,
            recommendation: rule.recommendation,
            fromBackend: false,
          })
        } else if (archMissing || costMissing) {
          evaluations.push({
            ruleId: rule.id,
            rule,
            status: 'WARNING',
            severity: 'Medium',
            judgment: archMissing
              ? 'Architecture가 불완전하여 비용 정합성을 완전히 판정할 수 없습니다.'
              : 'Cost Breakdown이 불완전하여 비용 정합성을 완전히 판정할 수 없습니다.',
            judgmentDetail: '아키텍처 또는 비용 섹션 중 하나가 비어 있어 두 섹션 간 정합성 검증이 제한됩니다.',
            evidenceFound: [],
            missingEvidence: archMissing ? ['Architecture services'] : ['Cost Breakdown aws_service_cost'],
            referencedSections: rule.sectionRefs,
            recommendation: rule.recommendation,
            fromBackend: false,
          })
        } else {
          const { judgment, detail } = derivePassJudgment(rule)
          evaluations.push({
            ruleId: rule.id,
            rule,
            status: 'PASS',
            severity: rule.severity,
            judgment,
            judgmentDetail: detail,
            evidenceFound: [],
            missingEvidence: [],
            referencedSections: rule.sectionRefs,
            recommendation: rule.recommendation,
            fromBackend: false,
          })
        }
      } else {
        const { judgment, detail } = derivePassJudgment(rule)
        evaluations.push({
          ruleId: rule.id,
          rule,
          status: 'PASS',
          severity: rule.severity,
          judgment,
          judgmentDetail: detail,
          evidenceFound: [],
          missingEvidence: [],
          referencedSections: rule.sectionRefs,
          recommendation: rule.recommendation,
          fromBackend: false,
        })
      }
    }
  }

  // If result is completely empty (no issues, no patches, no rule_evals),
  // mark every rule as NOT_CHECKED so the UI makes clear nothing was evaluated.
  if (!result) {
    evaluations = REVIEW_RULES.map(notCheckedEvaluation)
    adapted = false
  }

  const summary = {
    total: evaluations.length,
    pass: evaluations.filter(e => e.status === 'PASS').length,
    warning: evaluations.filter(e => e.status === 'WARNING').length,
    fail: evaluations.filter(e => e.status === 'FAIL').length,
    notChecked: evaluations.filter(e => e.status === 'NOT_CHECKED').length,
  }

  const categories: CategoryCoverage[] = CATEGORIES.map(cat => {
    const inCat = evaluations.filter(e => e.rule.category === cat.key)
    return {
      key: cat.key,
      label: cat.label,
      total: inCat.length,
      pass: inCat.filter(e => e.status === 'PASS').length,
      warning: inCat.filter(e => e.status === 'WARNING').length,
      fail: inCat.filter(e => e.status === 'FAIL').length,
      notChecked: inCat.filter(e => e.status === 'NOT_CHECKED').length,
    }
  })

  const readinessScore =
    typeof res.readiness_score === 'number'
      ? res.readiness_score
      : summary.total > 0
        ? Math.round((summary.pass / summary.total) * 100)
        : 0

  return {
    readinessScore,
    evaluations,
    categories,
    summary,
    adapted,
  }
}

function notCheckedEvaluation(rule: RuleDefinition): RuleEvaluation {
  return {
    ruleId: rule.id,
    rule,
    status: 'NOT_CHECKED',
    severity: rule.severity,
    judgment: '아직 평가되지 않았습니다.',
    judgmentDetail: '이 규칙은 현재 리뷰 실행에서 평가되지 않았습니다.',
    evidenceFound: [],
    missingEvidence: [],
    referencedSections: rule.sectionRefs,
    recommendation: rule.recommendation,
    fromBackend: false,
  }
}

function normalizeEvidence(
  evidence: BackendRuleEvaluation['evidence'] | undefined,
): EvidenceItem[] {
  if (!Array.isArray(evidence)) return []
  const out: EvidenceItem[] = []
  for (const e of evidence) {
    if (!e) continue
    if (typeof e === 'string') {
      out.push({ section: '', snippet: e })
    } else {
      out.push({
        section: e.section || '',
        snippet: e.snippet || '',
        fieldPath: e.field_path,
      })
    }
  }
  return out
}

function buildMissingFromIssue(
  rule: RuleDefinition,
  issue: ReviewIssue & { severity: string },
): string[] {
  const out: string[] = []
  if (issue.question) out.push(issue.question)
  // Heuristic: for *_INCOMPLETE rules, missing = the section itself
  if (rule.id.endsWith('_INCOMPLETE') || rule.id.endsWith('_MISSING')) {
    for (const s of rule.sectionRefs) {
      if (!out.some(o => o.toLowerCase().includes(s))) {
        out.push(`${s} 섹션 내용`)
      }
    }
  }
  return out
}
