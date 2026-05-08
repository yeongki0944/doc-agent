import { useState } from 'react'
import { color, space } from '../../styles/tokens'
import { ReviewPanel } from './ReviewPanel'
import { ChangeRequestPanel } from './ChangeRequestPanel'
import { ResourcePlanningPanel } from './ResourcePlanningPanel'
import { SectionSuggestionsPanel } from './SectionSuggestionsPanel'

type DrawerTab = 'review' | 'change_requests' | 'resources' | 'suggestions'

const TABS: Array<{ id: DrawerTab; label: string; short: string }> = [
  { id: 'review', label: 'Review', short: 'Review' },
  { id: 'change_requests', label: 'Change Requests', short: 'CR' },
  { id: 'resources', label: 'Resources', short: 'Res' },
  { id: 'suggestions', label: 'Suggestions', short: 'Sug' },
]

/**
 * ReviewDrawer — right-side drawer that hosts:
 *  - Submission Review Panel
 *  - Change Request Panel
 *  - Resource Planning Assistant
 *  - Section Suggestions
 * Opened via the "Review" button in the DocumentPanel header.
 */
export function ReviewDrawer({
  docId,
  activeTab,
  onClose,
  onSendPrompt,
  initialTab = 'review',
}: {
  docId: string
  activeTab: string
  onClose: () => void
  onSendPrompt?: (prompt: string) => void
  initialTab?: DrawerTab
}) {
  const [tab, setTab] = useState<DrawerTab>(initialTab)

  return (
    <div style={{
      width: 380,
      minWidth: 380,
      maxWidth: 380,
      height: '100%',
      display: 'flex',
      flexDirection: 'column',
      borderLeft: `1px solid ${color.border}`,
      background: color.bgPrimary,
      flexShrink: 0,
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '10px 12px', borderBottom: `1px solid ${color.border}`, background: color.bgSurface,
      }}>
        <span style={{ fontSize: 13, fontWeight: 700 }}>Review & Planning</span>
        <button
          onClick={onClose}
          style={{
            background: 'none', border: 'none', cursor: 'pointer',
            fontSize: 16, color: color.textMuted, padding: '2px 4px', lineHeight: 1,
          }}
          title="닫기"
        >
          ✕
        </button>
      </div>

      <div style={{ display: 'flex', borderBottom: `1px solid ${color.border}`, background: color.bgSurface }}>
        {TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            style={{
              flex: 1,
              padding: '8px 6px',
              border: 'none',
              background: 'none',
              cursor: 'pointer',
              fontSize: 12,
              fontWeight: tab === t.id ? 600 : 400,
              borderBottom: tab === t.id ? `2px solid ${color.mzRed}` : '2px solid transparent',
              color: tab === t.id ? color.mzRed : color.textSecondary,
              whiteSpace: 'nowrap',
            }}
          >
            {t.short}
          </button>
        ))}
      </div>

      <div style={{ flex: 1, overflow: 'auto' }}>
        {tab === 'review' && <ReviewPanel docId={docId} />}
        {tab === 'change_requests' && <ChangeRequestPanel docId={docId} />}
        {tab === 'resources' && <ResourcePlanningPanel docId={docId} />}
        {tab === 'suggestions' && (
          <SectionSuggestionsPanel docId={docId} activeTab={activeTab} onSendPrompt={onSendPrompt} />
        )}
      </div>
    </div>
  )
}
