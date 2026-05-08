import { useState } from 'react'
import { color, radius, space } from '../../styles/tokens'
import {
  requestReview,
  createChangeRequest,
  type ReviewResult,
  type ReviewIssue,
} from '../../utils/api'
import { useDocumentStore } from '../../store/documentStore'

type Severity = 'critical' | 'high' | 'medium' | 'low'

const SEVERITY_META: Record<Severity, { label: string; color: string; bg: string; border: string }> = {
  critical: { label: 'Critical', color: '#ffffff', bg: '#DC2626', border: '#B91C1C' },
  high: { label: 'High', color: '#ffffff', bg: '#EA580C', border: '#C2410C' },
  medium: { label: 'Medium', color: '#78350F', bg: '#FEF3C7', border: '#FDE68A' },
  low: { label: 'Low', color: '#1E3A8A', bg: '#DBEAFE', border: '#BFDBFE' },
}

type SuggestedPatch = NonNullable<ReviewResult['suggested_patches']>[number]
type PatchState = 'idle' | 'submitting' | 'created' | 'failed'

/**
 * Submission Review Panel — runs run_submission_lint and displays
 * readiness_score, grouped issues, missing_questions, and suggested_patches.
 */
export function ReviewPanel({ docId }: { docId: string }) {
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<ReviewResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [fallback, setFallback] = useState(false)
  const [patchStates, setPatchStates] = useState<Record<number, { state: PatchState; message?: string; crId?: string }>>({})
  const completionScore = useDocumentStore(s => s.completion_score ?? 0)
  const blockingIssues = useDocumentStore(s => s.blocking_issues ?? [])

  const handleRun = async () => {
    setLoading(true)
    setError(null)
    setFallback(false)
    setPatchStates({})
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

  const handleCreateCr = async (index: number, patch: SuggestedPatch) => {
    if (!patch || !patch.op || !patch.path) return
    setPatchStates(prev => ({ ...prev, [index]: { state: 'submitting' } }))
    try {
      const body = {
        summary: patch.reason || `Suggested ${patch.op} ${patch.path}`,
        json_patch: [{ op: patch.op, path: patch.path, value: patch.value }],
        changes: [
          {
            section: deriveSection(patch.path),
            as_is: null,
            to_be: patch.value,
            reason: patch.reason || 'Suggested by submission review',
            json_patch: [{ op: patch.op, path: patch.path, value: patch.value }],
          },
        ],
      }
      const resp = await createChangeRequest(docId, body)
      setPatchStates(prev => ({
        ...prev,
        [index]: {
          state: 'created',
          crId: resp?.change_request?.change_request_id,
        },
      }))
    } catch (e: any) {
      setPatchStates(prev => ({
        ...prev,
        [index]: { state: 'failed', message: e?.message || 'Change request 생성 실패' },
      }))
    }
  }

  return (
    <div style={{ padding: space.md, display: 'flex', flexDirection: 'column', gap: space.md }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <h3 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>Submission Review</h3>
        <button
          onClick={handleRun}
          disabled={loading}
          style={{
            padding: '6px 12px',
            borderRadius: radius.sm,
            border: 'none',
            fontSize: 12,
            cursor: loading ? 'wait' : 'pointer',
            background: color.mzRed,
            color: color.bgSurface,
            fontWeight: 600,
          }}
        >
          {loading ? '리뷰 중...' : 'Run Review'}
        </button>
      </div>

      {!result && !loading && (
        <div style={{ fontSize: 12, color: color.textMuted, padding: space.sm, background: color.bgSubtle, borderRadius: radius.sm }}>
          Run Review 버튼을 눌러 현재 문서의 submission readiness를 검사합니다.
        </div>
      )}

      {error && (
        <div style={{ fontSize: 12, color: color.error, padding: space.sm, background: '#fef2f2', borderRadius: radius.sm, border: '1px solid #fecaca' }}>
          ⚠ {error} (로컬 fallback 결과를 표시합니다)
        </div>
      )}

      {result && (
        <ReviewResultView
          result={result}
          fallback={fallback}
          patchStates={patchStates}
          onCreateCr={handleCreateCr}
        />
      )}
    </div>
  )
}

function ReviewResultView({
  result, fallback, patchStates, onCreateCr,
}: {
  result: ReviewResult
  fallback: boolean
  patchStates: Record<number, { state: PatchState; message?: string; crId?: string }>
  onCreateCr: (index: number, patch: SuggestedPatch) => void
}) {
  const score = typeof result.readiness_score === 'number' ? result.readiness_score : 0
  const issues = result.issues || {}
  const missing = result.missing_questions || []
  const suggested = result.suggested_patches || []

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: space.md }}>
      <ScoreBadge score={score} />

      {(['critical', 'high', 'medium', 'low'] as Severity[]).map(sev => {
        const list = issues[sev] || []
        if (list.length === 0) return null
        return <IssueGroup key={sev} severity={sev} issues={list} />
      })}

      {missing.length > 0 && (
        <div>
          <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>누락된 질문 ({missing.length})</div>
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12, color: color.textSecondary, lineHeight: 1.6 }}>
            {missing.map((q, i) => <li key={i}>{q}</li>)}
          </ul>
        </div>
      )}

      {suggested.length > 0 && (
        <div>
          <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>제안된 패치 ({suggested.length})</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {suggested.map((p, i) => (
              <SuggestedPatchCard
                key={i}
                index={i}
                patch={p}
                state={patchStates[i]}
                disabledCreate={fallback}
                onCreate={() => onCreateCr(i, p)}
              />
            ))}
          </div>
          {fallback && (
            <div style={{ fontSize: 11, color: color.textMuted, marginTop: 4 }}>
              로컬 fallback 결과에서는 change request 생성을 사용할 수 없습니다.
            </div>
          )}
        </div>
      )}

      {(Object.values(issues).every(v => !v || v.length === 0) && missing.length === 0 && suggested.length === 0) && (
        <div style={{ fontSize: 12, color: color.success, padding: space.sm, background: '#f0fdf4', borderRadius: radius.sm, border: '1px solid #bbf7d0' }}>
          ✓ 이슈가 발견되지 않았습니다.
        </div>
      )}
    </div>
  )
}

function SuggestedPatchCard({
  index, patch, state, disabledCreate, onCreate,
}: {
  index: number
  patch: SuggestedPatch
  state?: { state: PatchState; message?: string; crId?: string }
  disabledCreate: boolean
  onCreate: () => void
}) {
  const s = state?.state || 'idle'
  return (
    <div
      style={{
        fontSize: 11,
        padding: 8,
        border: `1px solid ${color.border}`,
        borderRadius: radius.sm,
        background: color.bgSurface,
      }}
    >
      <div style={{ fontFamily: 'monospace', color: color.info, marginBottom: 2 }}>
        #{index + 1} {patch.op} {patch.path}
      </div>
      {patch.reason && (
        <div style={{ color: color.textSecondary, marginBottom: 6 }}>{patch.reason}</div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
        <button
          onClick={onCreate}
          disabled={s === 'submitting' || s === 'created' || disabledCreate}
          style={{
            padding: '3px 10px',
            borderRadius: radius.sm,
            border: 'none',
            fontSize: 11,
            fontWeight: 600,
            cursor: (s === 'submitting' || s === 'created' || disabledCreate) ? 'not-allowed' : 'pointer',
            background:
              s === 'created' ? color.success :
              disabledCreate ? color.border :
              color.mzRed,
            color: color.bgSurface,
          }}
          title={disabledCreate ? 'Fallback 모드에서는 사용 불가' : '이 패치로 change request를 만듭니다'}
        >
          {s === 'submitting' ? '생성 중...' :
           s === 'created' ? '✓ Change Request 생성됨' :
           'Change Request로 만들기'}
        </button>
        {s === 'created' && state?.crId && (
          <code style={{ fontSize: 10, color: color.textMuted }}>{state.crId}</code>
        )}
        {s === 'failed' && (
          <span style={{ fontSize: 10, color: color.error }}>
            ✗ {state?.message || '실패'}
          </span>
        )}
      </div>
    </div>
  )
}

function ScoreBadge({ score }: { score: number }) {
  const bg = score >= 80 ? color.success : score >= 50 ? '#f59e0b' : color.error
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: space.sm }}>
      <span style={{
        padding: '6px 12px',
        borderRadius: radius.sm,
        fontSize: 13,
        fontWeight: 700,
        color: color.bgSurface,
        background: bg,
      }}>
        Readiness: {score}%
      </span>
    </div>
  )
}

function IssueGroup({ severity, issues }: { severity: Severity; issues: ReviewIssue[] }) {
  const meta = SEVERITY_META[severity]
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
        <span style={{
          display: 'inline-block',
          padding: '2px 8px',
          borderRadius: 10,
          fontSize: 10,
          fontWeight: 700,
          color: meta.color,
          background: meta.bg,
          border: `1px solid ${meta.border}`,
          textTransform: 'uppercase',
          letterSpacing: 0.5,
        }}>
          {meta.label}
        </span>
        <span style={{ fontSize: 11, color: color.textMuted }}>({issues.length})</span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {issues.map((iss, i) => (
          <div key={i} style={{
            fontSize: 12,
            padding: 8,
            border: `1px solid ${color.border}`,
            borderRadius: radius.sm,
            background: color.bgSurface,
          }}>
            <div style={{ fontWeight: 600, marginBottom: 2 }}>
              {iss.code}
              {iss.section && (
                <span style={{ fontSize: 10, color: color.textMuted, fontWeight: 400, marginLeft: 6 }}>
                  · {iss.section}
                </span>
              )}
            </div>
            <div style={{ color: color.textSecondary, lineHeight: 1.5 }}>{iss.message}</div>
            {iss.question && (
              <div style={{ fontSize: 11, color: color.info, marginTop: 4, fontStyle: 'italic' }}>
                Q. {iss.question}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function buildLocalFallback(completionScore: number, blockingIssues: any[]): ReviewResult {
  const score = Math.round((completionScore || 0) * 100)
  const critical: ReviewIssue[] = (blockingIssues || []).map((b: any, i: number) => ({
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
