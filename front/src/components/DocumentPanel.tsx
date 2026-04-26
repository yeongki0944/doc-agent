import { useState } from 'react'
import { useDocumentStore } from '../store/documentStore'
import { requestReview, requestExport } from '../utils/api'
import { CoverSection } from './sections/CoverSection'
import { OverviewSection } from './sections/OverviewSection'
import { TeamSection } from './sections/TeamSection'
import { SuccessCriteriaSection } from './sections/SuccessCriteriaSection'
import { AssumptionsSection } from './sections/AssumptionsSection'
import { ScopeSection } from './sections/ScopeSection'
import { ArchitectureSection } from './sections/ArchitectureSection'
import { MilestonesSection } from './sections/MilestonesSection'
import { CostSection } from './sections/CostSection'
import { AcceptanceSection } from './sections/AcceptanceSection'

const TABS = [
  'Cover', 'Overview', 'Team', 'Success Criteria', 'Assumptions',
  'Scope', 'Architecture', 'Milestones', 'Cost', 'Acceptance',
] as const

type TabName = typeof TABS[number]

const TAB_COMPONENTS: Record<TabName, React.FC> = {
  Cover: CoverSection,
  Overview: OverviewSection,
  Team: TeamSection,
  'Success Criteria': SuccessCriteriaSection,
  Assumptions: AssumptionsSection,
  Scope: ScopeSection,
  Architecture: ArchitectureSection,
  Milestones: MilestonesSection,
  Cost: CostSection,
  Acceptance: AcceptanceSection,
}

export function DocumentPanel() {
  const [activeTab, setActiveTab] = useState<TabName>('Cover')
  const completionScore = useDocumentStore(s => s.completion_score ?? 0)
  const blockingIssues = useDocumentStore(s => s.blocking_issues ?? [])
  const docId = useDocumentStore(s => s.document_id)
  const ActiveComponent = TAB_COMPONENTS[activeTab]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <Header completionScore={completionScore} blockingIssues={blockingIssues} docId={docId} />
      <TabBar tabs={TABS} active={activeTab} onSelect={setActiveTab} />
      <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
        <ActiveComponent />
      </div>
    </div>
  )
}

function Header({ completionScore, blockingIssues, docId }: { completionScore: number; blockingIssues: any[]; docId: string }) {
  const exportEnabled = blockingIssues.length === 0

  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 16px', borderBottom: '1px solid #eee' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontWeight: 600, fontSize: 15 }}>APN PoC Project Plan</span>
        <CompletionBadge score={completionScore} />
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <ReviewButton docId={docId} />
        <ExportButton disabled={!exportEnabled} docId={docId} />
      </div>
    </div>
  )
}

/** Completion score badge: 0.0~1.0 displayed as percentage with color coding */
export function CompletionBadge({ score }: { score: number }) {
  const pct = Math.round(score * 100)
  const bg = pct >= 100 ? '#22c55e' : pct >= 50 ? '#f59e0b' : '#ef4444'
  return (
    <span
      style={{ padding: '2px 8px', borderRadius: 10, fontSize: 12, fontWeight: 600, color: '#fff', background: bg }}
      role="status"
      aria-label={`Completion: ${pct}%`}
    >
      {pct}%
    </span>
  )
}

/** Export button: enabled only when blocking_issues is empty */
function ExportButton({ disabled, docId }: { disabled: boolean; docId: string }) {
  const handleExport = async () => {
    if (disabled) return
    try {
      const result = await requestExport(docId)
      if (result?.download_url) {
        window.open(result.download_url, '_blank')
      }
    } catch {
      // Error handled by status channel
    }
  }

  return (
    <button
      disabled={disabled}
      onClick={handleExport}
      title={disabled ? 'Blocking issues가 해결되어야 export 가능합니다' : 'DOCX 파일로 내보내기'}
      style={{
        padding: '6px 14px', borderRadius: 6, border: 'none', fontSize: 13,
        cursor: disabled ? 'not-allowed' : 'pointer',
        background: disabled ? '#d1d5db' : '#3b82f6', color: '#fff',
      }}
    >
      DOCX Export
    </button>
  )
}

function ReviewButton({ docId }: { docId: string }) {
  const [loading, setLoading] = useState(false)

  const handleReview = async () => {
    setLoading(true)
    try {
      await requestReview(docId)
    } catch {
      // Error handled by status channel
    } finally {
      setLoading(false)
    }
  }

  return (
    <button
      onClick={handleReview}
      disabled={loading}
      style={{ padding: '6px 14px', borderRadius: 6, border: '1px solid #d1d5db', fontSize: 13, cursor: loading ? 'wait' : 'pointer', background: '#fff', color: '#374151' }}
    >
      {loading ? '리뷰 중...' : '리뷰 요청'}
    </button>
  )
}

function TabBar({ tabs, active, onSelect }: { tabs: readonly string[]; active: string; onSelect: (t: any) => void }) {
  return (
    <div style={{ display: 'flex', overflowX: 'auto', borderBottom: '1px solid #eee', padding: '0 8px' }}>
      {tabs.map(t => (
        <button
          key={t}
          onClick={() => onSelect(t)}
          style={{
            padding: '8px 14px', border: 'none', background: 'none', cursor: 'pointer',
            fontSize: 13, fontWeight: active === t ? 600 : 400, whiteSpace: 'nowrap',
            borderBottom: active === t ? '2px solid #3b82f6' : '2px solid transparent',
            color: active === t ? '#3b82f6' : '#666',
          }}
        >
          {t}
        </button>
      ))}
    </div>
  )
}
