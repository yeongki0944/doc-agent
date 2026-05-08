import { useEffect, useMemo, useState } from 'react'
import { color, radius, space } from '../../styles/tokens'
import { useDocumentStore } from '../../store/documentStore'
import {
  approveChangeRequest,
  rejectChangeRequest,
  getDocument,
  type ChangeRequest,
  type ChangeRequestChange,
} from '../../utils/api'

/**
 * Change Request Panel — shows pending change requests with AS-IS / TO-BE,
 * reason, requester, status, approve/reject actions. Similar to a lightweight
 * GitHub PR review UI.
 */
export function ChangeRequestPanel({ docId }: { docId: string }) {
  const setDocument = useDocumentStore(s => s.setDocument)
  const [requests, setRequests] = useState<ChangeRequest[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [actionId, setActionId] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const doc = await getDocument(docId)
      const cr = Array.isArray(doc?.change_requests) ? doc.change_requests : []
      setRequests(cr)
      if (doc) setDocument(doc)
    } catch (e: any) {
      setError(e?.message || 'Change Request 불러오기 실패')
      setRequests([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docId])

  const pending = useMemo(() => requests.filter(r => r.status === 'pending'), [requests])
  const processed = useMemo(() => requests.filter(r => r.status !== 'pending'), [requests])

  const handleApprove = async (id: string) => {
    setActionId(id)
    try {
      await approveChangeRequest(docId, id)
      await load()
    } catch (e: any) {
      setError(e?.message || 'Approve 실패')
    } finally {
      setActionId(null)
    }
  }

  const handleReject = async (id: string) => {
    setActionId(id)
    try {
      await rejectChangeRequest(docId, id)
      await load()
    } catch (e: any) {
      setError(e?.message || 'Reject 실패')
    } finally {
      setActionId(null)
    }
  }

  return (
    <div style={{ padding: space.md, display: 'flex', flexDirection: 'column', gap: space.md }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <h3 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>Change Requests</h3>
        <button
          onClick={load}
          disabled={loading}
          style={{
            padding: '4px 10px',
            borderRadius: radius.sm,
            border: `1px solid ${color.border}`,
            fontSize: 11,
            cursor: loading ? 'wait' : 'pointer',
            background: color.bgSurface,
            color: color.textSecondary,
          }}
        >
          {loading ? '...' : '새로고침'}
        </button>
      </div>

      {error && (
        <div style={{
          fontSize: 12, color: color.error, padding: space.sm,
          background: '#fef2f2', borderRadius: radius.sm, border: '1px solid #fecaca',
        }}>
          ⚠ {error}
        </div>
      )}

      {!loading && pending.length === 0 && processed.length === 0 && !error && (
        <div style={{
          fontSize: 12, color: color.textMuted, padding: space.sm,
          background: color.bgSubtle, borderRadius: radius.sm,
        }}>
          대기 중인 Change Request가 없습니다.
        </div>
      )}

      {pending.length > 0 && (
        <Section title={`Pending (${pending.length})`}>
          {pending.map(cr => (
            <ChangeRequestCard
              key={cr.change_request_id}
              cr={cr}
              actionInFlight={actionId === cr.change_request_id}
              onApprove={() => handleApprove(cr.change_request_id)}
              onReject={() => handleReject(cr.change_request_id)}
            />
          ))}
        </Section>
      )}

      {processed.length > 0 && (
        <Section title={`Processed (${processed.length})`}>
          {processed.map(cr => (
            <ChangeRequestCard key={cr.change_request_id} cr={cr} />
          ))}
        </Section>
      )}
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{ fontSize: 11, fontWeight: 600, color: color.textMuted, marginBottom: 6, textTransform: 'uppercase', letterSpacing: 0.5 }}>
        {title}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {children}
      </div>
    </div>
  )
}

function ChangeRequestCard({
  cr,
  actionInFlight = false,
  onApprove,
  onReject,
}: {
  cr: ChangeRequest
  actionInFlight?: boolean
  onApprove?: () => void
  onReject?: () => void
}) {
  const statusColor =
    cr.status === 'approved' ? color.success :
    cr.status === 'rejected' ? color.error :
    '#f59e0b'

  return (
    <div style={{
      border: `1px solid ${color.border}`,
      borderRadius: radius.sm,
      background: color.bgSurface,
      padding: space.sm,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
        <span style={{ fontSize: 11, fontFamily: 'monospace', color: color.textMuted }}>
          {cr.change_request_id}
        </span>
        <span style={{
          fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 10,
          color: color.bgSurface, background: statusColor, textTransform: 'uppercase',
        }}>
          {cr.status}
        </span>
      </div>

      {cr.summary && (
        <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>{cr.summary}</div>
      )}

      <div style={{ fontSize: 11, color: color.textMuted, marginBottom: 6 }}>
        {cr.requester && <>요청자: {cr.requester}</>}
        {cr.created_at && <> · {formatTs(cr.created_at)}</>}
      </div>

      {Array.isArray(cr.changes) && cr.changes.map((ch, i) => (
        <ChangeEntry key={i} change={ch} />
      ))}

      {onApprove && onReject && cr.status === 'pending' && (
        <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
          <button
            onClick={onApprove}
            disabled={actionInFlight}
            style={{
              padding: '4px 12px',
              borderRadius: radius.sm,
              border: 'none',
              fontSize: 11,
              fontWeight: 600,
              background: color.success,
              color: color.bgSurface,
              cursor: actionInFlight ? 'wait' : 'pointer',
            }}
          >
            ✓ Approve
          </button>
          <button
            onClick={onReject}
            disabled={actionInFlight}
            style={{
              padding: '4px 12px',
              borderRadius: radius.sm,
              border: `1px solid ${color.error}`,
              fontSize: 11,
              fontWeight: 600,
              background: color.bgSurface,
              color: color.error,
              cursor: actionInFlight ? 'wait' : 'pointer',
            }}
          >
            ✗ Reject
          </button>
        </div>
      )}
    </div>
  )
}

function ChangeEntry({ change }: { change: ChangeRequestChange }) {
  return (
    <div style={{ marginTop: 6, padding: 8, background: color.bgSubtle, borderRadius: radius.sm, fontSize: 11 }}>
      {change.section && (
        <div style={{ fontWeight: 600, marginBottom: 4 }}>{change.section}</div>
      )}
      <div style={{ display: 'grid', gridTemplateColumns: '50px 1fr', rowGap: 2, columnGap: 6 }}>
        <span style={{ color: color.error, fontWeight: 600 }}>AS-IS</span>
        <code style={{ fontSize: 10, whiteSpace: 'pre-wrap', wordBreak: 'break-word', color: color.textSecondary }}>
          {truncate(stringify(change.as_is))}
        </code>
        <span style={{ color: color.success, fontWeight: 600 }}>TO-BE</span>
        <code style={{ fontSize: 10, whiteSpace: 'pre-wrap', wordBreak: 'break-word', color: color.textSecondary }}>
          {truncate(stringify(change.to_be))}
        </code>
      </div>
      {change.reason && (
        <div style={{ marginTop: 4, color: color.textSecondary, fontStyle: 'italic' }}>
          이유: {change.reason}
        </div>
      )}
    </div>
  )
}

function stringify(v: any): string {
  if (v == null) return '—'
  if (typeof v === 'string') return v
  try { return JSON.stringify(v) } catch { return String(v) }
}

function truncate(s: string, max = 120): string {
  if (!s) return ''
  return s.length > max ? s.slice(0, max) + '…' : s
}

function formatTs(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleString()
  } catch { return iso }
}
