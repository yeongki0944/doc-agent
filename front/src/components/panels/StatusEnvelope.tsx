import { color, radius, space } from '../../styles/tokens'

export type StandardStatus = 'completed' | 'partial_completed' | 'failed'

const STATUS_META: Record<StandardStatus, { label: string; bg: string; fg: string; border: string; icon: string }> = {
  completed: { label: 'Completed', bg: '#f0fdf4', fg: '#166534', border: '#bbf7d0', icon: '✓' },
  partial_completed: { label: 'Partial', bg: '#fff7ed', fg: '#9a3412', border: '#fed7aa', icon: '◐' },
  failed: { label: 'Failed', bg: '#fef2f2', fg: '#991b1b', border: '#fecaca', icon: '✗' },
}

export interface EnvelopeFields {
  standard_status?: StandardStatus | string
  message?: string
  warnings?: string[]
  missing_inputs?: string[]
  error_reason?: string
}

/**
 * StatusBadge — small pill that displays a backend standard_status value.
 * Safe to pass any object; renders nothing if no status is present.
 */
export function StatusBadge({ status, message }: { status?: StandardStatus | string; message?: string }) {
  if (!status) return null
  const key = (status as StandardStatus) in STATUS_META ? (status as StandardStatus) : 'completed'
  const meta = STATUS_META[key]
  return (
    <div
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: '2px 10px',
        borderRadius: 12,
        fontSize: 11,
        fontWeight: 600,
        color: meta.fg,
        background: meta.bg,
        border: `1px solid ${meta.border}`,
      }}
      title={message || meta.label}
    >
      <span>{meta.icon}</span>
      <span>{meta.label}</span>
    </div>
  )
}

/**
 * EnvelopeNotices — renders warnings, missing_inputs, and error_reason from the
 * hardened backend response envelope. Safe to call even if none are present
 * (returns null).
 */
export function EnvelopeNotices({
  warnings,
  missing_inputs,
  error_reason,
}: Pick<EnvelopeFields, 'warnings' | 'missing_inputs' | 'error_reason'>) {
  const hasWarnings = Array.isArray(warnings) && warnings.length > 0
  const hasMissing = Array.isArray(missing_inputs) && missing_inputs.length > 0
  if (!hasWarnings && !hasMissing && !error_reason) return null
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {hasWarnings && (
        <div style={{
          fontSize: 11,
          padding: space.sm,
          background: '#fff7ed',
          border: '1px solid #fed7aa',
          color: '#9a3412',
          borderRadius: radius.sm,
          lineHeight: 1.5,
        }}>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>Warnings</div>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {warnings!.map((w, i) => <li key={i}>{w}</li>)}
          </ul>
        </div>
      )}
      {hasMissing && (
        <div style={{
          fontSize: 11,
          padding: space.sm,
          background: '#eff6ff',
          border: '1px solid #bfdbfe',
          color: '#1e3a8a',
          borderRadius: radius.sm,
          lineHeight: 1.5,
        }}>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>Missing inputs</div>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {missing_inputs!.map((m, i) => <li key={i}>{m}</li>)}
          </ul>
        </div>
      )}
      {error_reason && (
        <div style={{
          fontSize: 11,
          padding: space.sm,
          background: '#fef2f2',
          border: '1px solid #fecaca',
          color: '#991b1b',
          borderRadius: radius.sm,
          fontFamily: 'monospace',
        }}>
          <div style={{ fontWeight: 600, marginBottom: 2, fontFamily: 'inherit' }}>Error reason</div>
          {error_reason}
        </div>
      )}
    </div>
  )
}

export const STANDARD_STATUS_META = STATUS_META
