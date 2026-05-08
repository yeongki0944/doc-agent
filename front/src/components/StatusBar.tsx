/**
 * StatusBar: displays agent processing status and active agent name.
 */

import { useDocumentStore, type AgentStatus } from '../store/documentStore'
import { color } from '../styles/tokens'
import { reconnectAppSync } from '../utils/appsync'

const STATUS_CONFIG: Record<AgentStatus, { color: string; label: string; pulse?: boolean }> = {
  processing: { color: '#f59e0b', label: 'Running', pulse: true },
  idle: { color: color.success, label: 'Idle' },
  error: { color: color.error, label: 'Error' },
  degraded: { color: '#f97316', label: 'Degraded', pulse: true },
}

const AGENT_DISPLAY_NAMES: Record<string, string> = {
  task_planner: '🔍 메시지 분석',
  runtime: '🧠 Runtime',
  discovery_agent: '📋 정보 수집',
  section_writer_agent: '✏️ 섹션 작성',
  staffing_agent: '👥 팀 구성',
  cost_agent: '💰 비용 산정',
  architecture_agent: '🏗️ 아키텍처',
  reviewer_agent: '🔎 문서 리뷰',
  formatter_agent: '📄 DOCX 생성',
  conversation_agent: '💬 대화',
}

export function StatusBar() {
  const agentStatus = useDocumentStore(s => s.agentStatus)
  const appsyncConnected = useDocumentStore(s => s.appsyncConnected)
  const agentActive = useDocumentStore(s => (s as any).agent_active || '')
  const agentMessage = useDocumentStore(s => (s as any).agent_message || '')
  const config = STATUS_CONFIG[agentStatus] || STATUS_CONFIG.idle

  const activeLabel = AGENT_DISPLAY_NAMES[agentActive] || agentActive

  return (
    <div style={{ padding: '6px 12px', borderBottom: `1px solid ${color.border}`, fontSize: 13, color: color.textSecondary }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
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
        <span style={{ fontWeight: 500 }}>
          Agent: {config.label}
          {agentStatus === 'processing' && activeLabel && (
            <span style={{ fontWeight: 400, marginLeft: 4, color: color.textMuted }}>
              ({activeLabel})
            </span>
          )}
        </span>
        {agentStatus === 'processing' && agentMessage && (
          <span style={{ fontSize: 12, color: color.textMuted }}>{agentMessage}</span>
        )}
        {!appsyncConnected && (
          <>
            <span style={{ fontSize: 11, color: '#f59e0b', marginLeft: 'auto' }}>
              ⚠ 실시간 연결 대기 중
            </span>
            <button
              onClick={() => reconnectAppSync()}
              style={{
                fontSize: 10,
                padding: '2px 8px',
                border: `1px solid ${color.border}`,
                borderRadius: 4,
                background: color.bgSurface,
                color: color.textSecondary,
                cursor: 'pointer',
              }}
              title="AppSync WebSocket 즉시 재연결"
            >
              재연결
            </button>
          </>
        )}
      </div>

      {agentStatus === 'degraded' && (
        <div style={{
          marginTop: 4, padding: '4px 8px', background: '#fff7ed', borderRadius: 4,
          fontSize: 12, color: '#c2410c', border: '1px solid #fed7aa',
        }}>
          ⚠ Degraded mode — Memory API 또는 inference profile 일시 불가.
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
