import { useCallback, useRef, useState } from 'react'
import { ChatPanel } from './ChatPanel'
import { DocumentPanel } from './DocumentPanel'

export function SplitLayout() {
  const [leftWidth, setLeftWidth] = useState(35) // percent
  const dragging = useRef(false)

  const onMouseDown = useCallback(() => { dragging.current = true }, [])

  const onMouseMove = useCallback((e: React.MouseEvent) => {
    if (!dragging.current) return
    const pct = (e.clientX / window.innerWidth) * 100
    setLeftWidth(Math.min(60, Math.max(20, pct)))
  }, [])

  const onMouseUp = useCallback(() => { dragging.current = false }, [])

  return (
    <div
      style={{ display: 'flex', height: '100vh', userSelect: dragging.current ? 'none' : 'auto' }}
      onMouseMove={onMouseMove}
      onMouseUp={onMouseUp}
      onMouseLeave={onMouseUp}
    >
      <div style={{ width: `${leftWidth}%`, overflow: 'auto' }}>
        <ChatPanel />
      </div>
      <div
        onMouseDown={onMouseDown}
        style={{ width: 4, cursor: 'col-resize', background: '#ddd', flexShrink: 0 }}
      />
      <div style={{ flex: 1, overflow: 'auto' }}>
        <DocumentPanel />
      </div>
    </div>
  )
}
