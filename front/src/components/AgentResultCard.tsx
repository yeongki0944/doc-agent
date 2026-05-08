import { color, radius, space } from '../styles/tokens'

export type AgentResultStatus = 'completed' | 'partial_completed' | 'failed' | 'unknown'

export interface AgentResultSummary {
  status: AgentResultStatus
  message?: string
  changed_sections?: string[]
  change_request_id?: string
  error?: string
  error_reason?: string
  actions?: string[]
  warnings?: string[]
  missing_inputs?: string[]
}

const STATUS_META: Record<AgentResultStatus, { label: string; bg: string; fg: string; border: string; icon: string }> = {
  completed: { label: 'Completed', bg: '#f0fdf4', fg: '#166534', border: '#bbf7d0', icon: '✓' },
  partial_completed: { label: 'Partial', bg: '#fff7ed', fg: '#9a3412', border: '#fed7aa', icon: '◐' },
  failed: { label: 'Failed', bg: '#fef2f2', fg: '#991b1b', border: '#fecaca', icon: '✗' },
  unknown: { label: 'Pending', bg: color.bgSubtle, fg: color.textSecondary, border: color.border, icon: '…' },
}

/**
 * AgentResultCard — structured display of an agent run outcome.
 * Shows status, changed sections, change request ID, and error details.
 */
export function AgentResultCard({ result }: { result: AgentResultSummary }) {
  const meta = STATUS_META[result.status] || STATUS_META.unknown
  return (
    <div style={{
      padding: space.sm,
      borderRadius: radius.sm,
      border: `1px solid ${meta.border}`,
      background: meta.bg,
      color: meta.fg,
      fontSize: 12,
      display: 'flex',
      flexDirection: 'column',
      gap: 4,
      maxWidth: '85%',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600 }}>
        <span>{meta.icon}</span>
        <span>{meta.label}</span>
        {result.message && (
          <span style={{ fontWeight: 400, color: meta.fg, marginLeft: 4 }}>— {result.message}</span>
        )}
      </div>

      {Array.isArray(result.changed_sections) && result.changed_sections.length > 0 && (
        <div style={{ fontSize: 11 }}>
          <span style={{ fontWeight: 600 }}>변경된 섹션:</span>{' '}
          {result.changed_sections.join(', ')}
        </div>
      )}

      {result.change_request_id && (
        <div style={{ fontSize: 11 }}>
          <span style={{ fontWeight: 600 }}>Change Request:</span>{' '}
          <code style={{ fontFamily: 'monospace' }}>{result.change_request_id}</code>
        </div>
      )}

      {Array.isArray(result.actions) && result.actions.length > 0 && (
        <div style={{ fontSize: 11 }}>
          <span style={{ fontWeight: 600 }}>Actions:</span>{' '}
          {result.actions.join(', ')}
        </div>
      )}

      {Array.isArray(result.warnings) && result.warnings.length > 0 && (
        <div style={{ fontSize: 11, marginTop: 2 }}>
          <span style={{ fontWeight: 600 }}>Warnings:</span>
          <ul style={{ margin: '2px 0 0', paddingLeft: 18 }}>
            {result.warnings.slice(0, 3).map((w, i) => (
              <li key={i}>{w}</li>
            ))}
            {result.warnings.length > 3 && (
              <li>+ {result.warnings.length - 3} more</li>
            )}
          </ul>
        </div>
      )}

      {Array.isArray(result.missing_inputs) && result.missing_inputs.length > 0 && (
        <div style={{ fontSize: 11 }}>
          <span style={{ fontWeight: 600 }}>Missing inputs:</span>{' '}
          {result.missing_inputs.join(', ')}
        </div>
      )}

      {result.error_reason && (
        <div style={{ fontSize: 11, fontFamily: 'monospace', marginTop: 2 }}>
          <span style={{ fontWeight: 600, fontFamily: 'inherit' }}>Reason:</span>{' '}
          {result.error_reason}
        </div>
      )}

      {result.error && (
        <div style={{ fontSize: 11, fontFamily: 'monospace', marginTop: 2 }}>
          {result.error}
        </div>
      )}
    </div>
  )
}

/** Heuristically derive an AgentResultSummary from a raw agent response object. */
export function parseAgentResult(raw: any): AgentResultSummary | null {
  if (!raw || typeof raw !== 'object') return null
  // Prefer the hardened backend envelope field when present.
  const envelopeStatus = (raw.standard_status || '').toString().toLowerCase()
  const legacyStatus = (raw.status || raw.result_status || '').toString().toLowerCase()
  const status = envelopeStatus || legacyStatus
  const mappedStatus: AgentResultStatus =
    status === 'completed' || status === 'ok' || status === 'success' ? 'completed' :
    status === 'partial' || status === 'partial_completed' ? 'partial_completed' :
    status === 'failed' || status === 'error' ? 'failed' :
    'unknown'

  const changed = Array.isArray(raw.changed_sections) ? raw.changed_sections
    : Array.isArray(raw.sections_changed) ? raw.sections_changed
    : undefined

  const summary: AgentResultSummary = {
    status: mappedStatus,
    message: raw.message || raw.summary || undefined,
    changed_sections: changed,
    change_request_id: raw.change_request_id || raw.change_request?.change_request_id || undefined,
    error: raw.error || undefined,
    error_reason: raw.error_reason || undefined,
    actions: Array.isArray(raw.actions) ? raw.actions : undefined,
    warnings: Array.isArray(raw.warnings) ? raw.warnings : undefined,
    missing_inputs: Array.isArray(raw.missing_inputs) ? raw.missing_inputs : undefined,
  }

  // Only render if at least one meaningful field is present
  const hasContent = !!(
    summary.message ||
    summary.changed_sections?.length ||
    summary.change_request_id ||
    summary.error ||
    summary.error_reason ||
    summary.actions?.length ||
    summary.warnings?.length ||
    summary.missing_inputs?.length
  )
  if (!hasContent && mappedStatus === 'unknown') return null
  return summary
}
