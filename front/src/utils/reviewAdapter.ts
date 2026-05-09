/**
 * Review Adapter
 *
 * Converts a backend `run_submission_lint` response into a full rule
 * evaluation matrix suitable for the bilingual Review Panel. The panel
 * consumes the output regardless of whether the backend already returns
 * `rule_evaluations[]` and `categories[]`, or only the legacy `issues[]`
 * shape.
 */

import type { ReviewIssue, ReviewResult } from './api'
import {
  LEGACY_ISSUE_TO_RULE_ID,
  REVIEW_RULES_SEED,
  type RuleDefinition,
  type RuleSeverity,
  type RuleStatus,
} from '../constants/reviewRulesSeed'

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
  /** Short judgment sentences (bilingual). Each side falls back to the other if empty. */
  judgment: { kr: string; en: string }
  judgmentDetail: { kr: string; en: string }
  evidenceFound: EvidenceItem[]
  missingEvidence: { kr: string[]; en: string[] }
  referencedSections: string[]
  recommendation: { kr: string; en: string }
  suggestedPatch?: SuggestedPatchRef
  backendIssue?: ReviewIssue & { severity?: string }
  evaluationType?: string
  evaluationSource?: string
  agentcoreStatus?: string
  /** True if this entry was produced directly from a backend rule_evaluation. */
  fromBackend: boolean
}

export interface CategoryCoverage {
  key: string
  label_kr: string
  label_en: string
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
  /** True when backend did not emit rule_evaluations[] and we adapted from issues[]. */
  adapted: boolean
}

interface BackendRuleEvaluation {
  rule_id: string
  status?: string
  severity?: string
  // Accept multiple naming conventions from the backend.
  judgment?: string
  judgment_kr?: string
  judgment_en?: string
  llm_judgment?: string
  llm_judgment_kr?: string
  llm_judgment_en?: string
  judgment_detail?: string
  judgment_detail_kr?: string
  judgment_detail_en?: string
  evidence?: Array<{ section?: string; snippet?: string; text?: string; field_path?: string } | string>
  evidence_found?: Array<{ section?: string; snippet?: string; text?: string; field_path?: string } | string>
  missing_evidence?: string[]
  missing_evidence_kr?: string[]
  missing_evidence_en?: string[]
  recommendation?: string
  recommendation_kr?: string
  recommendation_en?: string
  suggested_patch?: SuggestedPatchRef
  referenced_sections?: string[]
  evaluation_type?: string
  evaluation_source?: string
  agentcore_status?: string
}

interface BackendCategory {
  key?: string
  category?: string
  category_kr?: string
  category_en?: string
  label_kr?: string
  label_en?: string
  total?: number
  pass?: number
  warning?: number
  fail?: number
  not_checked?: number
}

interface ReviewResultWithEvaluations extends ReviewResult {
  rule_evaluations?: BackendRuleEvaluation[]
  categories?: BackendCategory[]
  rules?: RuleDefinition[]
  rule_catalog?: RuleDefinition[]
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
  if (v === 'PASS' || v === 'WARNING' || v === 'FAIL' || v === 'NOT_CHECKED') return v
  return null
}

function normalizeSeverity(raw: string | undefined, fallback: RuleSeverity): RuleSeverity {
  if (!raw) return fallback
  return SEVERITY_MAP[String(raw).toLowerCase()] || fallback
}

function flattenIssues(
  issues: ReviewResult['issues'],
): Map<string, ReviewIssue & { severity: string }> {
  const out = new Map<string, ReviewIssue & { severity: string }>()
  if (!issues) return out
  for (const sev of ['critical', 'high', 'medium', 'low'] as const) {
    for (const iss of issues[sev] || []) {
      if (!iss?.code) continue
      out.set(iss.code, { ...iss, severity: sev })
    }
  }
  return out
}

function deriveStatusFromSeverity(severity: string): RuleStatus {
  const k = severity.toLowerCase()
  if (k === 'critical' || k === 'high') return 'FAIL'
  return 'WARNING'
}

function matchSuggestedPatch(
  rule: RuleDefinition,
  patches: NonNullable<ReviewResult['suggested_patches']>,
): SuggestedPatchRef | undefined {
  if (!patches || patches.length === 0) return undefined
  const sections = new Set(rule.related_sections)
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

function buildRulesById(rules: RuleDefinition[]): Record<string, RuleDefinition> {
  return rules.reduce((acc, r) => {
    acc[r.rule_id] = r
    return acc
  }, {} as Record<string, RuleDefinition>)
}

/**
 * Build a full evaluation matrix from a backend review result. `catalog`
 * lets callers inject an up-to-date rules catalog (e.g. loaded from
 * `/review_rules`). When omitted, the seeded catalog is used.
 */
export function buildReviewMatrix(
  result: ReviewResult | null | undefined,
  catalog?: RuleDefinition[],
): ReviewMatrix {
  const res = (result || {}) as ReviewResultWithEvaluations
  // Prefer the backend-attached catalog — it reflects the live enabled/disabled
  // and custom-rule state. Fall back to caller-provided catalog, then seed.
  const sourceCatalog =
    (Array.isArray(res.rule_catalog) && res.rule_catalog.length > 0 ? res.rule_catalog
      : (Array.isArray(res.rules) && res.rules.length > 0 ? res.rules
        : (catalog && catalog.length > 0 ? catalog : REVIEW_RULES_SEED.rules)))
  const rules = sourceCatalog.filter(r => r.enabled !== false)
  const byId = buildRulesById(rules)
  const suggested = res.suggested_patches || []
  const backendEvals = Array.isArray(res.rule_evaluations) ? res.rule_evaluations : null

  let evaluations: RuleEvaluation[] = []
  let adapted = false

  if (backendEvals && backendEvals.length > 0) {
    const seen = new Set<string>()
    for (const be of backendEvals) {
      if (!be?.rule_id) continue
      const rule = byId[be.rule_id]
      if (!rule) continue
      seen.add(rule.rule_id)
      const status = normalizeStatus(be.status) || 'NOT_CHECKED'
      const severity = normalizeSeverity(be.severity, rule.severity)
      const judgmentKr = be.judgment_kr || be.llm_judgment_kr || be.judgment || be.llm_judgment || ''
      const judgmentEn = be.judgment_en || be.llm_judgment_en || be.judgment || be.llm_judgment || ''
      const evidenceRaw = be.evidence_found ?? be.evidence
      evaluations.push({
        ruleId: rule.rule_id,
        rule,
        status,
        severity,
        judgment: { kr: judgmentKr, en: judgmentEn },
        judgmentDetail: {
          kr: be.judgment_detail_kr || be.judgment_detail || judgmentKr,
          en: be.judgment_detail_en || be.judgment_detail || judgmentEn,
        },
        evidenceFound: normalizeEvidence(evidenceRaw),
        missingEvidence: {
          kr: be.missing_evidence_kr || be.missing_evidence || [],
          en: be.missing_evidence_en || be.missing_evidence || [],
        },
        referencedSections: Array.isArray(be.referenced_sections) && be.referenced_sections.length > 0
          ? be.referenced_sections
          : rule.related_sections,
        recommendation: {
          kr: be.recommendation_kr || be.recommendation || rule.recommendation_template_kr,
          en: be.recommendation_en || be.recommendation || rule.recommendation_template_en,
        },
        suggestedPatch: be.suggested_patch || matchSuggestedPatch(rule, suggested),
        evaluationType: be.evaluation_type || rule.evaluation_type,
        evaluationSource: be.evaluation_source,
        agentcoreStatus: be.agentcore_status,
        fromBackend: true,
      })
    }
    for (const rule of rules) {
      if (!seen.has(rule.rule_id)) evaluations.push(notCheckedEvaluation(rule))
    }
  } else {
    // Adapt from legacy issues[]
    adapted = true
    const issueMap = flattenIssues(res.issues)

    // Keep track of which legacy codes already consumed by a rule
    const matchedByRule = new Map<string, ReviewIssue & { severity: string }>()
    for (const [code, iss] of issueMap.entries()) {
      const rid = LEGACY_ISSUE_TO_RULE_ID[code]
      if (rid && byId[rid]) {
        const existing = matchedByRule.get(rid)
        // Prefer more severe hit
        if (!existing || severityRank(iss.severity) > severityRank(existing.severity)) {
          matchedByRule.set(rid, iss)
        }
      }
    }

    for (const rule of rules) {
      const hit = matchedByRule.get(rule.rule_id)
      if (hit) {
        const status = deriveStatusFromSeverity(hit.severity)
        const severity = normalizeSeverity(hit.severity, rule.severity)
        evaluations.push({
          ruleId: rule.rule_id,
          rule,
          status,
          severity,
          judgment: {
            kr: hit.message || `${rule.title_kr} — 관련 이슈가 감지되었습니다.`,
            en: hit.message || `${rule.title_en} — related issue detected.`,
          },
          judgmentDetail: {
            kr: buildLegacyDetailKr(rule, hit),
            en: buildLegacyDetailEn(rule, hit),
          },
          evidenceFound: [],
          missingEvidence: {
            kr: buildMissingFromIssueKr(rule, hit),
            en: buildMissingFromIssueEn(rule, hit),
          },
          referencedSections: rule.related_sections,
          recommendation: {
            kr: rule.recommendation_template_kr,
            en: rule.recommendation_template_en,
          },
          suggestedPatch: matchSuggestedPatch(rule, suggested),
          backendIssue: hit,
          evaluationType: rule.evaluation_type,
          evaluationSource: 'legacy_issue_adapter',
          fromBackend: false,
        })
      } else {
        evaluations.push({
          ruleId: rule.rule_id,
          rule,
          status: 'PASS',
          severity: rule.severity,
          judgment: {
            kr: '해당 규칙을 트리거하는 이슈가 감지되지 않았습니다.',
            en: 'No issue triggering this rule was detected.',
          },
          judgmentDetail: {
            kr: `문서에서 ${rule.title_kr}에 해당하는 결함이 발견되지 않았습니다.`,
            en: `No issue related to "${rule.title_en}" was detected in the document.`,
          },
          evidenceFound: [],
          missingEvidence: { kr: [], en: [] },
          referencedSections: rule.related_sections,
          recommendation: {
            kr: rule.recommendation_template_kr,
            en: rule.recommendation_template_en,
          },
          evaluationType: rule.evaluation_type,
          evaluationSource: 'legacy_issue_adapter',
          fromBackend: false,
        })
      }
    }
  }

  if (!result) {
    evaluations = rules.map(notCheckedEvaluation)
    adapted = false
  }

  // Categories: prefer backend-supplied counts if present and non-empty.
  let categories: CategoryCoverage[]
  if (Array.isArray(res.categories) && res.categories.length > 0) {
    categories = res.categories.map(c => ({
      key: c.key || c.category_en || c.category || c.label_en || '',
      label_kr: c.label_kr || c.category_kr || c.category || c.key || '',
      label_en: c.label_en || c.category_en || c.category || c.key || '',
      total: c.total ?? 0,
      pass: c.pass ?? 0,
      warning: c.warning ?? 0,
      fail: c.fail ?? 0,
      notChecked: c.not_checked ?? 0,
    }))
  } else {
    const byCategory = new Map<string, CategoryCoverage>()
    for (const e of evaluations) {
      const key = e.rule.category_en
      const existing = byCategory.get(key)
      const entry: CategoryCoverage =
        existing || {
          key,
          label_kr: e.rule.category_kr,
          label_en: e.rule.category_en,
          total: 0,
          pass: 0,
          warning: 0,
          fail: 0,
          notChecked: 0,
        }
      entry.total += 1
      if (e.status === 'PASS') entry.pass += 1
      else if (e.status === 'WARNING') entry.warning += 1
      else if (e.status === 'FAIL') entry.fail += 1
      else entry.notChecked += 1
      byCategory.set(key, entry)
    }
    categories = Array.from(byCategory.values())
  }

  const summary = {
    total: evaluations.length,
    pass: evaluations.filter(e => e.status === 'PASS').length,
    warning: evaluations.filter(e => e.status === 'WARNING').length,
    fail: evaluations.filter(e => e.status === 'FAIL').length,
    notChecked: evaluations.filter(e => e.status === 'NOT_CHECKED').length,
  }

  const readinessScore =
    typeof res.readiness_score === 'number'
      ? res.readiness_score
      : summary.total > 0
        ? Math.round((summary.pass / summary.total) * 100)
        : 0

  return { readinessScore, evaluations, categories, summary, adapted }
}

function notCheckedEvaluation(rule: RuleDefinition): RuleEvaluation {
  return {
    ruleId: rule.rule_id,
    rule,
    status: 'NOT_CHECKED',
    severity: rule.severity,
    judgment: {
      kr: '아직 평가되지 않았습니다.',
      en: 'Not evaluated yet.',
    },
    judgmentDetail: {
      kr: '이 규칙은 현재 리뷰 실행에서 평가되지 않았습니다.',
      en: 'This rule was not evaluated in the current review run.',
    },
    evidenceFound: [],
    missingEvidence: { kr: [], en: [] },
    referencedSections: rule.related_sections,
    recommendation: {
      kr: rule.recommendation_template_kr,
      en: rule.recommendation_template_en,
    },
    evaluationType: rule.evaluation_type,
    evaluationSource: 'not_checked',
    fromBackend: false,
  }
}

function severityRank(sev: string): number {
  const k = sev.toLowerCase()
  if (k === 'critical') return 4
  if (k === 'high') return 3
  if (k === 'medium') return 2
  if (k === 'low') return 1
  return 0
}

function normalizeEvidence(
  evidence: BackendRuleEvaluation['evidence'] | undefined,
): EvidenceItem[] {
  if (!Array.isArray(evidence)) return []
  const out: EvidenceItem[] = []
  for (const e of evidence) {
    if (!e) continue
    if (typeof e === 'string') out.push({ section: '', snippet: e })
    else out.push({ section: e.section || '', snippet: e.snippet || e.text || '', fieldPath: e.field_path })
  }
  return out
}

function buildLegacyDetailKr(rule: RuleDefinition, issue: ReviewIssue & { severity: string }): string {
  const lines = [
    issue.message || `${rule.title_kr}이(가) 충족되지 않았습니다.`,
    issue.question ? `열린 질문: ${issue.question}` : '',
    issue.section ? `관련 섹션: ${issue.section}` : '',
    rule.fail_criteria_kr?.[0] ? `FAIL 기준: ${rule.fail_criteria_kr[0]}` : '',
  ].filter(Boolean)
  return lines.join('\n\n')
}

function buildLegacyDetailEn(rule: RuleDefinition, issue: ReviewIssue & { severity: string }): string {
  const lines = [
    issue.message || `${rule.title_en} is not satisfied.`,
    issue.question ? `Open question: ${issue.question}` : '',
    issue.section ? `Related section: ${issue.section}` : '',
    rule.fail_criteria_en?.[0] ? `FAIL criterion: ${rule.fail_criteria_en[0]}` : '',
  ].filter(Boolean)
  return lines.join('\n\n')
}

function buildMissingFromIssueKr(rule: RuleDefinition, issue: ReviewIssue & { severity: string }): string[] {
  const out: string[] = []
  if (issue.question) out.push(issue.question)
  for (const s of rule.related_sections) {
    if (!out.some(o => o.toLowerCase().includes(s))) out.push(`${s} 섹션 보강`)
  }
  return out
}

function buildMissingFromIssueEn(rule: RuleDefinition, issue: ReviewIssue & { severity: string }): string[] {
  const out: string[] = []
  if (issue.question) out.push(issue.question)
  for (const s of rule.related_sections) {
    if (!out.some(o => o.toLowerCase().includes(s))) out.push(`Strengthen ${s} section`)
  }
  return out
}
