import { useState } from 'react'
import { color, radius, space } from '../../styles/tokens'
import { requestReview, type ReviewResult, type ReviewIssue } from '../../utils/api'
import { useDocumentStore } from '../../store/documentStore'

type Severity = 'critical' | 'high' | 'medium' | 'low'

const SEVERITY_META: Record<Severity, { label: string; color: string; bg: string; border: string }> = {
  critical: { label: 'Critical', color: '#ffffff', bg: '#DC2626', border: '#B91C1C' },
  high: { label: 'High', color: '#ffffff', bg: '#EA580C', border: '#C2410C' },
  medium: { label: 'Medium', color: '#78350F', bg: '#FEF3C7', border: '#FDE68A' },
  low: { label: 'Low', color: '#1E3A8A', bg: '#DBEAFE', border: '#BFDBFE' },
}

/**
 * Submission Review Panel — runs run_submission_lint and displays
 * readiness_score, grouped issues, missing_questions, and suggested_patches.
 */
export function ReviewPanel({ docId }: { docId: string }) {
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<ReviewResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const completionScore = useDocumentStore(s => s.completion_score ?? 0)
  const blockingIssues = useDocumentStore(s => s.blocking_issues ?? [])

  const handleRun = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await requestReview(docId)
      setResult(data)
    } catch (e: any) {
      setError(e?.message || 'Review 요청에 실패했습니다.')
      // Fallback: minimal local computation so the UI stays useful
      const localFallback = buildLocalFallback(completionScore, blockingIssues)
      setResult(localFallback)
    } finally {
      setLoading(false)
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

      {result && <ReviewResultView result={result} />}
    </div>
  )
}

function ReviewResultView({ result }: { result: ReviewResult }) {
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
              <div
                key={i}
                style={{
                  fontSize: 11,
                  padding: 8,
                  border: `1px solid ${color.border}`,
                  borderRadius: radius.sm,
                  background: color.bgSurface,
                }}
              >
                <div style={{ fontFamily: 'monospace', color: color.info, marginBottom: 2 }}>
                  {p.op} {p.path}
                </div>
                {p.reason && (
                  <div style={{ color: color.textSecondary }}>{p.reason}</div>
                )}
              </div>
            ))}
          </div>
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
