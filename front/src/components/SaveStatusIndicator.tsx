import { color } from '../styles/tokens'
import type { SaveStatus } from '../hooks/useSaveStatus'

/**
 * Minimal save-status indicator. Renders nothing for 'idle'.
 * Shows "저장 중..." / "✓ 저장됨" / "✗ 저장 실패" with appropriate colors.
 */
export function SaveStatusIndicator({ status }: { status: SaveStatus }) {
  if (status === 'idle') return null

  const statusColor =
    status === 'saving' ? color.textMuted
    : status === 'saved' ? color.success
    : color.error

  const label =
    status === 'saving' ? '저장 중...'
    : status === 'saved' ? '✓ 저장됨'
    : '✗ 저장 실패'

  return (
    <span style={{ fontSize: 11, color: statusColor, marginLeft: 4 }}>
      {label}
    </span>
  )
}
