import { useEffect, useRef, useState } from 'react'
import { color } from '../../styles/tokens'
import { ReviewPanel } from './ReviewPanel'
import { ChangeRequestPanel } from './ChangeRequestPanel'
import { ResourcePlanningPanel } from './ResourcePlanningPanel'
import { SectionSuggestionsPanel } from './SectionSuggestionsPanel'

type DrawerTab = 'review' | 'change_requests' | 'resources' | 'suggestions'

const TABS: Array<{ id: DrawerTab; label: string; short: string }> = [
  { id: 'review', label: 'Submission Readiness', short: 'Readiness' },
  { id: 'change_requests', label: 'Change Requests', short: 'Changes' },
  { id: 'resources', label: 'Resource Planning Assistant', short: 'Planning' },
  { id: 'suggestions', label: 'Section Suggestions', short: 'Presets' },
]

const MIN_WIDTH = 360
const MAX_WIDTH = 1200
const DEFAULT_WIDTH = 480
const LS_WIDTH_KEY = 'mzc.review_drawer.width.v1'

/**
 * ReviewDrawer — right-side drawer that hosts Submission Review, Change
 * Requests, Resource Planning, and Section Suggestions. Supports:
 *  - drag handle on the left edge to resize the drawer (persisted)
 *  - fullscreen toggle for focused review work
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
  const [width, setWidth] = useState<number>(() => {
    try {
      const raw = localStorage.getItem(LS_WIDTH_KEY)
      if (raw) {
        const n = Number(raw)
        if (Number.isFinite(n) && n >= MIN_WIDTH && n <= MAX_WIDTH) return n
      }
    } catch { /* ignore */ }
    return DEFAULT_WIDTH
  })
  const [fullscreen, setFullscreen] = useState(false)
  const dragState = useRef<{ startX: number; startWidth: number } | null>(null)

  // Persist width
  useEffect(() => {
    try { localStorage.setItem(LS_WIDTH_KEY, String(width)) } catch { /* ignore */ }
  }, [width])

  const handleMouseDown = (e: React.MouseEvent) => {
    if (fullscreen) return
    dragState.current = { startX: e.clientX, startWidth: width }
    e.preventDefault()
  }

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!dragState.current) return
      const delta = dragState.current.startX - e.clientX
      const next = Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, dragState.current.startWidth + delta))
      setWidth(next)
    }
    const onUp = () => {
      dragState.current = null
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [])

  const effectiveWidth = fullscreen ? undefined : width

  return (
    <div
      className="review-drawer"
      style={{
        position: 'relative',
        width: fullscreen ? '100%' : effectiveWidth,
        minWidth: fullscreen ? 0 : width,
        flex: fullscreen ? 1 : `0 0 ${width}px`,
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        borderLeft: fullscreen ? 'none' : `1px solid ${color.border}`,
        background: color.bgPrimary,
        flexShrink: 0,
      }}
      data-drawer-width={width}
      data-drawer-fullscreen={fullscreen ? '1' : '0'}
    >
      {/* Drag handle (left edge) */}
      {!fullscreen && (
        <div
          onMouseDown={handleMouseDown}
          role="separator"
          aria-orientation="vertical"
          title="드래그하여 크기 조절"
          className="review-drawer-drag-handle"
        />
      )}

      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8,
        padding: '10px 12px', borderBottom: `1px solid ${color.border}`, background: color.bgSurface,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: color.textPrimary, letterSpacing: '-0.01em' }}>Review & Planning</span>
          <span
            className="mzc-badge"
            title="이 검토는 규칙 기반 결정론적 엔진으로 수행됩니다. LLM 추론은 사용하지 않습니다."
            style={{ fontSize: 9, padding: '1px 6px' }}
          >
            Rule-based · LLM 미사용
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <button
            onClick={() => setFullscreen(v => !v)}
            className="mzc-btn mzc-btn-ghost"
            title={fullscreen ? '원래 크기로' : '전체 화면'}
            style={{ padding: '2px 6px', fontSize: 14, lineHeight: 1 }}
          >
            {fullscreen ? '⤡' : '⤢'}
          </button>
          <button
            onClick={onClose}
            className="mzc-btn mzc-btn-ghost"
            title="닫기"
            style={{ padding: '2px 6px', fontSize: 14, lineHeight: 1 }}
          >
            ✕
          </button>
        </div>
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
