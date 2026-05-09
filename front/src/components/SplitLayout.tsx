import { useState } from 'react'
import { color, shadow } from '../styles/tokens'
import { ChatPanel } from './ChatPanel'
import { DocumentPanel } from './DocumentPanel'
import { Sidebar } from './Sidebar'
import { useSessionStore } from '../store/sessionStore'
import { ReviewRulesAdmin } from './admin/ReviewRulesAdmin'

type ViewMode = 'documents' | 'rules_admin'

export function SplitLayout() {
  const currentDocId = useSessionStore(s => s.currentDocId)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [chatOpen, setChatOpen] = useState(false)
  const [view, setView] = useState<ViewMode>('documents')

  if (view === 'rules_admin') {
    return (
      <div style={{ display: 'flex', height: '100vh', overflowX: 'hidden' }}>
        <Sidebar
          collapsed={sidebarCollapsed}
          onToggle={() => setSidebarCollapsed(prev => !prev)}
          activeView={view}
          onNavigate={setView}
        />
        <div style={{ flex: 1, minWidth: 0, display: 'flex' }}>
          <ReviewRulesAdmin onClose={() => setView('documents')} />
        </div>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', height: '100vh', overflowX: 'hidden' }}>
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed(prev => !prev)}
        activeView={view}
        onNavigate={setView}
      />
      {currentDocId ? (
        <div style={{ flex: 1, display: 'flex', minWidth: 0, width: '100%' }}>
          <div style={{ flex: 1, overflow: 'auto', minWidth: 0, width: '100%' }}>
            <DocumentPanel docId={currentDocId} />
          </div>
        </div>
      ) : (
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: color.textMuted, background: 'var(--mzc-bg)' }}>
          <div style={{ textAlign: 'center', maxWidth: 420 }}>
            <div style={{
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              width: 72, height: 72, borderRadius: 20,
              background: 'var(--mzc-primary-soft)', color: 'var(--mzc-primary)',
              marginBottom: 20, fontSize: 36,
            }}>
              📄
            </div>
            <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--mzc-text)', letterSpacing: '-0.01em', marginBottom: 8 }}>
              MZC PoC Funding Platform
            </div>
            <div style={{ fontSize: 14, lineHeight: 1.55 }}>
              문서를 선택하거나 새 문서를 만들어 제안서 작업을 시작하세요.
            </div>
          </div>
        </div>
      )}

      {/* Floating chat toggle button */}
      {currentDocId && (
        <button
          onClick={() => setChatOpen(prev => !prev)}
          style={{
            position: 'fixed',
            bottom: 24,
            right: 24,
            zIndex: 1000,
            width: 52,
            height: 52,
            borderRadius: '50%',
            border: 'none',
            background: color.primary,
            color: color.bgSurface,
            fontSize: 22,
            cursor: 'pointer',
            boxShadow: shadow.elevated,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            lineHeight: 1,
          }}
          title={chatOpen ? 'Ask Agent 닫기' : 'Ask Agent'}
        >
          {chatOpen ? '✕' : '💬'}
        </button>
      )}

      {/* Floating chat popup */}
      {currentDocId && chatOpen && (
        <div
          className="mzc-panel"
          style={{
            position: 'fixed',
            bottom: 90,
            right: 24,
            width: 440,
            maxHeight: '72vh',
            zIndex: 1001,
            borderRadius: 16,
            boxShadow: '0 16px 40px rgba(16, 24, 40, 0.16)',
            overflow: 'hidden',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          {/* Popup header with close button */}
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '12px 16px',
            borderBottom: `1px solid ${color.border}`,
            background: color.bgSurface,
            flexShrink: 0,
          }}>
            <span style={{ fontWeight: 700, fontSize: 14, color: color.textPrimary, display: 'flex', alignItems: 'center', gap: 8 }}>
              <span className="mzc-badge mzc-badge-ai" style={{ fontSize: 10 }}>AI</span>
              Ask Agent
            </span>
            <button
              onClick={() => setChatOpen(false)}
              style={{
                background: 'none', border: 'none', cursor: 'pointer',
                fontSize: 16, color: color.textMuted, padding: '2px 4px',
                lineHeight: 1,
              }}
              title="닫기"
            >
              ✕
            </button>
          </div>
          <div style={{
            flex: 1,
            minHeight: 0,
            overflow: 'hidden',
            display: 'flex',
            flexDirection: 'column',
          }}>
            <ChatPanel docId={currentDocId} />
          </div>
        </div>
      )}
    </div>
  )
}
