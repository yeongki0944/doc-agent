/**
 * StatusBar: displays agent processing status and degraded mode warnings.
 * Subscribes to AppSync docs/{docId}/status channel via Zustand store.
 */

import { useDocumentStore, type AgentStatus } from '../store/documentStore'
import { color } from '../styles/tokens'

const STATUS_CONFIG: Record<AgentStatus, { color: string; label: string; pulse?: boolean }> = {
  processing: { color: '#f59e0b', label: 'processing', pulse: true },
  idle: { color: color.success, label: 'idle' },
  error: { color: color.error, label: 'error' },
  degraded: { color: '#f97316', label: 'degraded', pulse: true },
}

export function StatusBar() {
  const agentStatus = useDocumentStore(s => s.agentStatus)
  const appsyncConnected = useDocumentStore(s => s.appsyncConnected)
  const config = STATUS_CONFIG[agentStatus] || STATUS_CONFIG.idle

  return (
    <div style={{ padding: '6px 12px', borderBottom: `1px solid ${color.border}`, fontSize: 13, color: color.textSecondary }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span
          style={{
            display: 'inline-block',
            width: 8,
            height: 8,
            borderRadius: '50%',
            background: config.color,
            animation: config.pulse ? 'pulse 1.5s ease-in-out infinite' : 'none',
          }}
        />
        <span>Agent: {config.label}</span>
        {!appsyncConnected && (
          <span style={{ fontSize: 11, color: '#f59e0b', marginLeft: 'auto' }}>
            ⚠ 실시간 연결 대기 중
          </span>
        )}
      </div>

      {agentStatus === 'degraded' && (
        <div style={{
          marginTop: 4, padding: '4px 8px', background: '#fff7ed', borderRadius: 4,
          fontSize: 12, color: '#c2410c', border: '1px solid #fed7aa',
        }}>
          ⚠ Degraded mode — Memory API 또는 inference profile 일시 불가. 기본 기능은 정상 동작합니다.
        </div>
      )}

      {agentStatus === 'error' && (
        <div style={{
          marginTop: 4, padding: '4px 8px', background: '#fef2f2', borderRadius: 4,
          fontSize: 12, color: '#dc2626', border: '1px solid #fecaca',
        }}>
          ⚠ 에이전트 처리 중 오류가 발생했습니다.
        </div>
      )}
    </div>
  )
}
