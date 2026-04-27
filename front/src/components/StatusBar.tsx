/**
 * StatusBar: displays agent processing status, funding health, and issue summaries.
 */

import { useMemo } from 'react'
import { useDocumentStore, type AgentStatus } from '../store/documentStore'
import { color } from '../styles/tokens'
import { getFundingEligibility, isBedrockService } from '../utils/frontendSchema'

const STATUS_CONFIG: Record<AgentStatus, { color: string; label: string; pulse?: boolean }> = {
  processing: { color: '#f59e0b', label: 'processing', pulse: true },
  idle: { color: color.success, label: 'idle' },
  error: { color: color.error, label: 'error' },
  degraded: { color: '#f97316', label: 'degraded', pulse: true },
}

export function StatusBar() {
  const agentStatus = useDocumentStore(s => s.agentStatus)
  const appsyncConnected = useDocumentStore(s => s.appsyncConnected)
  const blockingIssues = useDocumentStore(s => s.blocking_issues ?? [])
  const warnings = useDocumentStore(s => s.warnings ?? [])
  const funding = useDocumentStore(s => s.sections?.cost_breakdown?.funding_calculation)
  const architecture = useDocumentStore(s => s.sections?.architecture)
  const config = STATUS_CONFIG[agentStatus] || STATUS_CONFIG.idle

  const fundingStatus = useMemo(
    () => getFundingEligibility(blockingIssues, funding),
    [blockingIssues, funding],
  )
  const bedrockIncluded = Boolean(architecture?.services?.some(service => isBedrockService(service as any)))

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
        <span>Agent: {config.label}</span>
        <span style={badgeStyle(fundingStatus === 'eligible' ? '#dcfce7' : fundingStatus === 'ineligible' ? '#fee2e2' : '#fef3c7', fundingStatus === 'eligible' ? '#166534' : fundingStatus === 'ineligible' ? '#991b1b' : '#92400e')}>
          Funding: {fundingStatus}
        </span>
        <span style={badgeStyle(bedrockIncluded ? '#dcfce7' : '#fee2e2', bedrockIncluded ? '#166534' : '#991b1b')}>
          Bedrock {bedrockIncluded ? 'included' : 'missing'}
        </span>
        {blockingIssues.length > 0 && <span style={issueBadge('#fee2e2', '#991b1b')}>Blocking issues: {blockingIssues.length}</span>}
        {warnings.length > 0 && <span style={issueBadge('#fef3c7', '#92400e')}>Warnings: {warnings.length}</span>}
        {!appsyncConnected && (
          <span style={{ fontSize: 11, color: '#f59e0b', marginLeft: 'auto' }}>
            ⚠ 실시간 연결 대기 중
          </span>
        )}
      </div>

      {blockingIssues.length > 0 && (
        <div style={{
          marginTop: 4, padding: '4px 8px', background: '#fef2f2', borderRadius: 4,
          fontSize: 12, color: '#b91c1c', border: '1px solid #fecaca',
        }}>
          {blockingIssues.slice(0, 2).map(issue => issue.message || issue.code).join(' · ')}
        </div>
      )}

      {warnings.length > 0 && (
        <div style={{
          marginTop: 4, padding: '4px 8px', background: '#fffbeb', borderRadius: 4,
          fontSize: 12, color: '#b45309', border: '1px solid #fde68a',
        }}>
          {warnings.slice(0, 2).map(warning => warning.message || warning.code).join(' · ')}
        </div>
      )}

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

function badgeStyle(background: string, colorValue: string): React.CSSProperties {
  return {
    display: 'inline-flex',
    alignItems: 'center',
    padding: '2px 8px',
    borderRadius: 999,
    background,
    color: colorValue,
    fontSize: 11,
    fontWeight: 700,
  }
}

function issueBadge(background: string, colorValue: string): React.CSSProperties {
  return badgeStyle(background, colorValue)
}
