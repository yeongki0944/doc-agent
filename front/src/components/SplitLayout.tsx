import { useCallback, useRef, useState } from 'react'
import { ChatPanel } from './ChatPanel'
import { DocumentPanel } from './DocumentPanel'
import { Sidebar } from './Sidebar'
import { useSessionStore } from '../store/sessionStore'

export function SplitLayout() {
  const [leftWidth, setLeftWidth] = useState(35) // percent of main area
  const dragging = useRef(false)
  const currentDocId = useSessionStore(s => s.currentDocId)

  const onMouseDown = useCallback(() => { dragging.current = true }, [])

  const onMouseMove = useCallback((e: React.MouseEvent) => {
    if (!dragging.current) return
    // Calculate percentage relative to the main area (excluding sidebar 240px)
    const mainLeft = 240
    const mainWidth = window.innerWidth - mainLeft
    const pct = ((e.clientX - mainLeft) / mainWidth) * 100
    setLeftWidth(Math.min(60, Math.max(20, pct)))
  }, [])

  const onMouseUp = useCallback(() => { dragging.current = false }, [])

  return (
    <div style={{ display: 'flex', height: '100vh' }}>
      <Sidebar />
      {currentDocId ? (
        <div
          style={{ flex: 1, display: 'flex', userSelect: dragging.current ? 'none' : 'auto' }}
          onMouseMove={onMouseMove}
          onMouseUp={onMouseUp}
          onMouseLeave={onMouseUp}
        >
          <div style={{ width: `${leftWidth}%`, overflow: 'auto' }}>
            <ChatPanel docId={currentDocId} />
          </div>
          <div
            onMouseDown={onMouseDown}
            style={{ width: 4, cursor: 'col-resize', background: '#ddd', flexShrink: 0 }}
          />
          <div style={{ flex: 1, overflow: 'auto' }}>
            <DocumentPanel docId={currentDocId} />
          </div>
        </div>
      ) : (
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#999' }}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 48, marginBottom: 16 }}>📄</div>
            <div style={{ fontSize: 16 }}>문서를 선택하거나 새 문서를 만들어주세요</div>
          </div>
        </div>
      )}
    </div>
  )
}
