import { Fragment, useMemo, useState } from 'react'
import { color, radius, space } from '../../styles/tokens'
import {
  requestReview,
  createChangeRequest,
  type ReviewResult,
} from '../../utils/api'
import { useDocumentStore } from '../../store/documentStore'
import { StatusBadge, EnvelopeNotices } from './StatusEnvelope'
import {
  CATEGORIES,
  SECTION_LABELS,
  type CategoryKey,
  type RuleSeverity,
  type RuleStatus,
} from '../../constants/reviewRules'
import {
  buildReviewMatrix,
  type RuleEvaluation,
  type ReviewMatrix,
} from '../../utils/reviewAdapter'

type PatchState = 'idle' | 'submitting' | 'created' | 'failed'

const STATUS_FILTER_VALUES: Array<RuleStatus | 'ALL'> = ['ALL', 'PASS', 'WARNING', 'FAIL', 'NOT_CHECKED']
const SEVERITY_FILTER_VALUES: Array<RuleSeverity | 'ALL'> = ['ALL', 'Critical', 'High', 'Medium', 'Low', 'Info']

/**
 * Submission Review Panel — runs `run_submission_lint` and presents a full
 * rule evaluation matrix similar to Dynatrace / AWS Security Hub style
 * posture tools. Shows PASS/WARNING/FAIL/NOT_CHECKED for every rule in the
 * catalog, not just triggered findings.
 */
export function ReviewPanel({ docId }: { docId: string }) {
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<ReviewResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [fallback, setFallback] = useState(false)
  const [patchStates, setPatchStates] = useState<Record<string, { state: PatchState; message?: string; crId?: string }>>({})
  const [openRuleId, setOpenRuleId] = useState<string | null>(null)

  const [statusFilter, setStatusFilter] = useState<RuleStatus | 'ALL'>('ALL')
  const [severityFilter, setSeverityFilter] = useState<RuleSeverity | 'ALL'>('ALL')
  const [categoryFilter, setCategoryFilter] = useState<CategoryKey | 'ALL'>('ALL')
  const [searchText, setSearchText] = useState('')

  const completionScore = useDocumentStore(s => s.completion_score ?? 0)
  const blockingIssues = useDocumentStore(s => s.blocking_issues ?? [])

  const matrix = useMemo<ReviewMatrix>(() => buildReviewMatrix(result), [result])

  const filtered = useMemo(() => {
    const q = searchText.trim().toLowerCase()
    return matrix.evaluations.filter(e => {
      if (statusFilter !== 'ALL' && e.status !== statusFilter) return false
      if (severityFilter !== 'ALL' && e.severity !== severityFilter) return false
      if (categoryFilter !== 'ALL' && e.rule.category !== categoryFilter) return false
      if (q) {
        const hay = `${e.rule.title} ${e.rule.id} ${e.judgment} ${e.rule.definition}`.toLowerCase()
        if (!hay.includes(q)) return false
      }
      return true
    })
  }, [matrix.evaluations, statusFilter, severityFilter, categoryFilter, searchText])

  const handleRun = async () => {
    setLoading(true)
    setError(null)
    setFallback(false)
    setPatchStates({})
    setOpenRuleId(null)
    try {
      const data = await requestReview(docId)
      setResult(data)
    } catch (e: any) {
      setError(e?.message || 'Review 요청에 실패했습니다.')
      setResult(buildLocalFallback(completionScore, blockingIssues))
      setFallback(true)
    } finally {
      setLoading(false)
    }
  }

  const handleCreateCr = async (evalItem: RuleEvaluation) => {
    const patch = evalItem.suggestedPatch
    if (!patch || !patch.op || !patch.path) return
    const key = evalItem.ruleId
    setPatchStates(prev => ({ ...prev, [key]: { state: 'submitting' } }))
    try {
      const body = {
        summary: patch.reason || `Suggested ${patch.op} ${patch.path}`,
        json_patch: [{ op: patch.op, path: patch.path, value: patch.value }],
        changes: [
          {
            section: deriveSection(patch.path),
            as_is: null,
            to_be: patch.value,
            reason: patch.reason || evalItem.recommendation,
            json_patch: [{ op: patch.op, path: patch.path, value: patch.value }],
          },
        ],
      }
      const resp = await createChangeRequest(docId, body)
      setPatchStates(prev => ({
        ...prev,
        [key]: { state: 'created', crId: resp?.change_request?.change_request_id },
      }))
    } catch (e: any) {
      setPatchStates(prev => ({
        ...prev,
        [key]: { state: 'failed', message: e?.message || 'Change request 생성 실패' },
      }))
    }
  }

  return (
    <div style={{ padding: space.md, display: 'flex', flexDirection: 'column', gap: space.md }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <h3 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>Submission Readiness</h3>
          <div style={{ fontSize: 11, color: color.textMuted, marginTop: 2 }}>
            APN / GenAI IC / SOW 기준 전체 규칙 매트릭스로 검토합니다.
          </div>
        </div>
        <button
          onClick={handleRun}
          disabled={loading}
          className="mzc-btn mzc-btn-primary"
          style={{ fontSize: 12 }}
        >
          {loading ? '리뷰 중...' : 'Run Review'}
        </button>
      </div>

      {!result && !loading && (
        <div style={{
          fontSize: 12,
          color: color.textMuted,
          padding: space.md,
          background: color.bgSubtle,
          borderRadius: radius.sm,
          textAlign: 'center',
          border: `1px dashed ${color.border}`,
        }}>
          <div style={{ fontSize: 20, marginBottom: 4 }}>📋</div>
          <div>Run Review 버튼을 눌러 현재 문서의 submission readiness를 검사합니다.</div>
        </div>
      )}

      {error && (
        <div style={{ fontSize: 12, color: color.error, padding: space.sm, background: '#fef2f2', borderRadius: radius.sm, border: '1px solid #fecaca' }}>
          ⚠ {error} (로컬 fallback 결과를 표시합니다)
        </div>
      )}

      {result && (
        <>
          <TopSummary matrix={matrix} result={result} />

          <EnvelopeNotices
            warnings={result.warnings}
            missing_inputs={result.missing_inputs}
            error_reason={result.error_reason}
          />

          {matrix.adapted && (
            <div className="review-fallback-notice">
              Full rule evaluation is not available yet. Showing issue-based review result adapted to the rule catalog.
            </div>
          )}

          <CategoryCoverageView matrix={matrix} onPickCategory={setCategoryFilter} />

          <FilterBar
            statusFilter={statusFilter}
            severityFilter={severityFilter}
            categoryFilter={categoryFilter}
            searchText={searchText}
            onStatus={setStatusFilter}
            onSeverity={setSeverityFilter}
            onCategory={setCategoryFilter}
            onSearch={setSearchText}
          />

          <RuleTable
            evaluations={filtered}
            openRuleId={openRuleId}
            onToggle={id => setOpenRuleId(prev => (prev === id ? null : id))}
            patchStates={patchStates}
            onCreateCr={handleCreateCr}
            fallbackMode={fallback}
          />
        </>
      )}
    </div>
  )
}

/* ---------- Top summary ---------- */

function TopSummary({ matrix, result }: { matrix: ReviewMatrix; result: ReviewResult }) {
  const score = matrix.readinessScore
  const hint =
    score >= 80 ? 'Ready for submission' :
    score >= 50 ? 'Needs review before submission' :
    'Blocking issues to resolve'
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div className="review-score-card" style={{ width: '100%' }}>
        <div className="label">Submission Readiness</div>
        <div className="value">{score}%</div>
        <div className="hint">{hint}</div>
      </div>
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <StatusBadge status={result.standard_status} message={result.message} />
      </div>
      <div className="review-summary-grid">
        <MetricCard label="Total" value={matrix.summary.total} />
        <MetricCard label="Pass" value={matrix.summary.pass} tone="success" />
        <MetricCard label="Warning" value={matrix.summary.warning} tone="warning" />
        <MetricCard label="Fail" value={matrix.summary.fail} tone="danger" />
        <MetricCard label="Not Checked" value={matrix.summary.notChecked} />
      </div>
    </div>
  )
}

function MetricCard({ label, value, tone }: { label: string; value: number; tone?: 'success' | 'warning' | 'danger' }) {
  const cls =
    tone === 'success' ? 'metric-card is-success' :
    tone === 'warning' ? 'metric-card is-warning' :
    tone === 'danger' ? 'metric-card' :
    'metric-card'
  const valueColor =
    tone === 'danger' ? color.error :
    tone === 'warning' ? '#b54708' :
    tone === 'success' ? color.success :
    undefined
  return (
    <div className={cls}>
      <div className="label">{label}</div>
      <div className="metric-value" style={valueColor ? { color: valueColor } : undefined}>{value}</div>
    </div>
  )
}

/* ---------- Category coverage ---------- */

function CategoryCoverageView({
  matrix,
  onPickCategory,
}: {
  matrix: ReviewMatrix
  onPickCategory: (k: CategoryKey | 'ALL') => void
}) {
  return (
    <div>
      <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.08, color: color.textMuted, marginBottom: 6 }}>
        Category Coverage
      </div>
      <div className="review-coverage-grid">
        {matrix.categories.map(cat => (
          <button
            key={cat.key}
            className="review-coverage-row"
            style={{ cursor: 'pointer', border: '1px solid ' + color.border, textAlign: 'left' }}
            onClick={() => onPickCategory(cat.key)}
            title={`${cat.label} 필터 적용`}
          >
            <span className="label">{cat.label}</span>
            <span className="counts">
              <span className="chip pass" title="Pass">{cat.pass}</span>
              <span className="chip warn" title="Warning">{cat.warning}</span>
              <span className="chip fail" title="Fail">{cat.fail}</span>
              <span className="chip unknown" title="Not Checked">{cat.notChecked}</span>
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}

/* ---------- Filter bar ---------- */

function FilterBar({
  statusFilter, severityFilter, categoryFilter, searchText,
  onStatus, onSeverity, onCategory, onSearch,
}: {
  statusFilter: RuleStatus | 'ALL'
  severityFilter: RuleSeverity | 'ALL'
  categoryFilter: CategoryKey | 'ALL'
  searchText: string
  onStatus: (v: RuleStatus | 'ALL') => void
  onSeverity: (v: RuleSeverity | 'ALL') => void
  onCategory: (v: CategoryKey | 'ALL') => void
  onSearch: (v: string) => void
}) {
  return (
    <div className="review-filter-bar">
      <select
        className="mzc-select"
        value={statusFilter}
        onChange={e => onStatus(e.target.value as any)}
        aria-label="Status filter"
      >
        {STATUS_FILTER_VALUES.map(v => (
          <option key={v} value={v}>{v === 'ALL' ? 'Status: All' : `Status: ${v}`}</option>
        ))}
      </select>
      <select
        className="mzc-select"
        value={severityFilter}
        onChange={e => onSeverity(e.target.value as any)}
        aria-label="Severity filter"
      >
        {SEVERITY_FILTER_VALUES.map(v => (
          <option key={v} value={v}>{v === 'ALL' ? 'Severity: All' : `Severity: ${v}`}</option>
        ))}
      </select>
      <select
        className="mzc-select"
        value={categoryFilter}
        onChange={e => onCategory(e.target.value as any)}
        aria-label="Category filter"
      >
        <option value="ALL">Category: All</option>
        {CATEGORIES.map(cat => (
          <option key={cat.key} value={cat.key}>{cat.label}</option>
        ))}
      </select>
      <input
        className="mzc-input"
        type="text"
        placeholder="규칙 검색..."
        value={searchText}
        onChange={e => onSearch(e.target.value)}
        aria-label="Search rules"
      />
    </div>
  )
}

/* ---------- Rule table ---------- */

function RuleTable({
  evaluations,
  openRuleId,
  onToggle,
  patchStates,
  onCreateCr,
  fallbackMode,
}: {
  evaluations: RuleEvaluation[]
  openRuleId: string | null
  onToggle: (id: string) => void
  patchStates: Record<string, { state: PatchState; message?: string; crId?: string }>
  onCreateCr: (e: RuleEvaluation) => void
  fallbackMode: boolean
}) {
  if (evaluations.length === 0) {
    return (
      <div style={{
        fontSize: 12, color: color.textMuted, padding: space.md,
        background: color.bgSubtle, borderRadius: radius.sm,
        border: `1px dashed ${color.border}`, textAlign: 'center',
      }}>
        필터에 맞는 규칙이 없습니다.
      </div>
    )
  }
  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="review-rule-table">
        <thead>
          <tr>
            <th style={{ width: 80 }}>Status</th>
            <th style={{ width: 70 }}>Severity</th>
            <th>Rule</th>
            <th style={{ width: 120 }}>Category</th>
          </tr>
        </thead>
        <tbody>
          {evaluations.map(e => {
            const isOpen = openRuleId === e.ruleId
            const cat = CATEGORIES.find(c => c.key === e.rule.category)
            return (
              <Fragment key={e.ruleId}>
                <tr
                  className={`rule-row${isOpen ? ' is-open' : ''}`}
                  onClick={() => onToggle(e.ruleId)}
                >
                  <td><StatusPill status={e.status} /></td>
                  <td><SeverityPill severity={e.severity} /></td>
                  <td>
                    <div style={{ fontWeight: 600, color: color.textPrimary }}>
                      {e.rule.title}
                    </div>
                    <div style={{ fontSize: 11, color: color.textMuted, marginTop: 2, lineHeight: 1.45 }}>
                      {e.judgment}
                    </div>
                  </td>
                  <td>
                    <span style={{ fontSize: 11, color: color.textSecondary }}>
                      {cat?.label || e.rule.category}
                    </span>
                  </td>
                </tr>
                {isOpen && (
                  <tr className="rule-detail">
                    <td colSpan={4}>
                      <RuleDetail
                        evaluation={e}
                        patchState={patchStates[e.ruleId]}
                        onCreateCr={() => onCreateCr(e)}
                        fallbackMode={fallbackMode}
                      />
                    </td>
                  </tr>
                )}
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function StatusPill({ status }: { status: RuleStatus }) {
  const label = status === 'NOT_CHECKED' ? 'Not Checked' : status[0] + status.slice(1).toLowerCase()
  const cls = status.toLowerCase()
  const icon =
    status === 'PASS' ? '✓' :
    status === 'WARNING' ? '!' :
    status === 'FAIL' ? '✗' :
    '–'
  return (
    <span className={`status-badge ${cls}`}>
      <span>{icon}</span>
      <span>{label}</span>
    </span>
  )
}

function SeverityPill({ severity }: { severity: RuleSeverity }) {
  return <span className={`severity-badge ${severity.toLowerCase()}`}>{severity}</span>
}

/* ---------- Rule detail (expandable row) ---------- */

function RuleDetail({
  evaluation,
  patchState,
  onCreateCr,
  fallbackMode,
}: {
  evaluation: RuleEvaluation
  patchState?: { state: PatchState; message?: string; crId?: string }
  onCreateCr: () => void
  fallbackMode: boolean
}) {
  const e = evaluation
  const s = patchState?.state || 'idle'
  const hasPatch = !!e.suggestedPatch
  const actionLabel =
    e.status === 'PASS' ? 'View' :
    e.status === 'WARNING' ? (hasPatch ? 'Create Change Request' : 'Fix') :
    e.status === 'FAIL' ? 'Create Change Request' :
    'Ask Agent'
  const actionDisabled =
    (e.status === 'NOT_CHECKED') ||
    (e.status === 'PASS') ||
    (!hasPatch && (e.status === 'FAIL' || e.status === 'WARNING')) ||
    (hasPatch && (s === 'submitting' || s === 'created' || fallbackMode))
  const actionTitle =
    e.status === 'PASS' ? '이 규칙은 PASS 상태입니다.' :
    e.status === 'NOT_CHECKED' ? '아직 평가되지 않은 규칙입니다.' :
    !hasPatch ? '자동 생성된 suggested_patch가 없어 Change Request를 자동으로 만들 수 없습니다.' :
    fallbackMode ? 'Fallback 모드에서는 Change Request 생성이 불가합니다.' :
    undefined

  return (
    <div className="review-detail-grid">
      <div>
        <div className="block-label">Rule</div>
        <div className="block-body">
          <div style={{ fontSize: 13, fontWeight: 600, color: color.textPrimary }}>{e.rule.title}</div>
          <div style={{ fontSize: 10, color: color.textMuted, fontFamily: 'monospace', marginTop: 2 }}>
            {e.rule.id}
          </div>
        </div>
      </div>

      <div>
        <div className="block-label">Definition</div>
        <div className="block-body">{e.rule.definition}</div>
      </div>

      <div>
        <div className="block-label">Pass / Warning / Fail Criteria</div>
        <div className="criteria-list">
          <span className="tag pass">PASS</span><span>{e.rule.passCriteria}</span>
          <span className="tag warn">WARN</span><span>{e.rule.warningCriteria}</span>
          <span className="tag fail">FAIL</span><span>{e.rule.failCriteria}</span>
        </div>
      </div>

      <div>
        <div className="block-label">LLM Judgment</div>
        <div className="block-body" style={{ whiteSpace: 'pre-wrap' }}>
          {e.judgmentDetail || e.judgment}
        </div>
      </div>

      <div>
        <div className="block-label">Evidence found ({e.evidenceFound.length})</div>
        {e.evidenceFound.length === 0 ? (
          <div className="block-body" style={{ color: color.textMuted, fontSize: 11 }}>
            문서에서 추출된 근거가 없습니다.
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {e.evidenceFound.map((ev, i) => (
              <div key={i} className="evidence-card">
                {ev.section && <div className="section">{SECTION_LABELS[ev.section] || ev.section}</div>}
                {ev.snippet && <div className="snippet">{ev.snippet}</div>}
                {ev.fieldPath && <div className="field-path">{ev.fieldPath}</div>}
              </div>
            ))}
          </div>
        )}
      </div>

      <div>
        <div className="block-label">Missing evidence ({e.missingEvidence.length})</div>
        {e.missingEvidence.length === 0 ? (
          <div className="block-body" style={{ color: color.textMuted, fontSize: 11 }}>
            누락된 근거가 없습니다.
          </div>
        ) : (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {e.missingEvidence.map((m, i) => (
              <span key={i} className="missing-chip">▢ {m}</span>
            ))}
          </div>
        )}
      </div>

      <div>
        <div className="block-label">Referenced sections</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          {e.referencedSections.map(sec => (
            <span key={sec} className="mzc-badge">{SECTION_LABELS[sec] || sec}</span>
          ))}
        </div>
      </div>

      <div>
        <div className="block-label">Recommendation</div>
        <div className="block-body">{e.recommendation}</div>
      </div>

      {e.suggestedPatch && (
        <div>
          <div className="block-label">Suggested fix</div>
          <div style={{
            fontFamily: 'monospace', fontSize: 11, padding: '6px 8px',
            background: color.bgSurface, border: `1px solid ${color.border}`,
            borderRadius: 6, color: color.info,
          }}>
            {e.suggestedPatch.op} {e.suggestedPatch.path}
          </div>
          {e.suggestedPatch.reason && (
            <div style={{ fontSize: 11, color: color.textSecondary, marginTop: 4 }}>
              {e.suggestedPatch.reason}
            </div>
          )}
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
        <button
          onClick={onCreateCr}
          disabled={actionDisabled}
          className="mzc-btn mzc-btn-primary"
          style={{ fontSize: 12 }}
          title={actionTitle}
        >
          {s === 'submitting' ? '생성 중...' :
           s === 'created' ? '✓ Change Request 생성됨' :
           actionLabel}
        </button>
        {s === 'created' && patchState?.crId && (
          <code style={{ fontSize: 10, color: color.textMuted }}>{patchState.crId}</code>
        )}
        {s === 'failed' && (
          <span style={{ fontSize: 10, color: color.error }}>
            ✗ {patchState?.message || '실패'}
          </span>
        )}
      </div>
    </div>
  )
}

/* ---------- Local fallback (backend down) ---------- */

function buildLocalFallback(completionScore: number, blockingIssues: any[]): ReviewResult {
  const score = Math.round((completionScore || 0) * 100)
  const critical = (blockingIssues || []).map((b: any, i: number) => ({
    code: b.code || `BLOCKING_${i}`,
    message: b.message || JSON.stringify(b),
    section: b.section || '',
  }))
  return {
    readiness_score: score,
    issues: { critical, high: [], medium: [], low: [] },
    missing_questions: [],
    suggested_patches: [],
  }
}

function deriveSection(pointerPath: string): string {
  const parts = pointerPath.replace(/^\//, '').split('/').filter(Boolean)
  if (parts[0] === 'sections' && parts[1]) return parts[1]
  return parts[0] || ''
}
