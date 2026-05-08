import { useState } from 'react'
import { color, shadow, radius } from '../styles/tokens'
import { ChatPanel } from './ChatPanel'
import { DocumentPanel } from './DocumentPanel'
import { Sidebar } from './Sidebar'
import { useSessionStore } from '../store/sessionStore'

export function SplitLayout() {
  const currentDocId = useSessionStore(s => s.currentDocId)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [chatOpen, setChatOpen] = useState(false)

  return (
    <div style={{ display: 'flex', height: '100vh', overflowX: 'hidden' }}>
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed(prev => !prev)}
      />
      {currentDocId ? (
        <div style={{ flex: 1, display: 'flex', minWidth: 0, width: '100%' }}>
          <div style={{ flex: 1, overflow: 'auto', minWidth: 0, width: '100%' }}>
            <DocumentPanel docId={currentDocId} />
          </div>
        </div>
      ) : (
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: color.textMuted }}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 48, marginBottom: 16 }}>📄</div>
            <div style={{ fontSize: 16 }}>문서를 선택하거나 새 문서를 만들어주세요</div>
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
            background: color.mzRed,
            color: color.bgSurface,
            fontSize: 24,
            cursor: 'pointer',
            boxShadow: shadow.elevated,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            lineHeight: 1,
          }}
          title={chatOpen ? '채팅 닫기' : '채팅 열기'}
        >
          {chatOpen ? '✕' : '💬'}
        </button>
      )}

      {/* Floating chat popup */}
      {currentDocId && chatOpen && (
        <div
          style={{
            position: 'fixed',
            bottom: 80,
            right: 24,
            width: 420,
            maxHeight: '70vh',
            zIndex: 1001,
            borderRadius: 12,
            boxShadow: '0 8px 32px rgba(10,37,64,0.18)',
            background: color.bgSurface,
            overflow: 'hidden',
            display: 'flex',
            flexDirection: 'column',
            border: `1px solid ${color.border}`,
          }}
        >
          {/* Popup header with close button */}
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '10px 14px',
            borderBottom: `1px solid ${color.border}`,
            background: color.bgPrimary,
            flexShrink: 0,
          }}>
            <span style={{ fontWeight: 600, fontSize: 14 }}>💬 Chat</span>
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
