import { useState, useRef, useEffect } from 'react'
import { DOCUMENT_GUIDES } from '../constants/documentGuides'
import { color, radius, shadow, size, space, font } from '../styles/tokens'

export interface SectionGuideButtonProps {
  sectionKey: string
}

/**
 * Renders ⓘ icon inline next to a section heading.
 * On click, toggles a popover displaying the Korean writing guide for that section.
 * If DOCUMENT_GUIDES[sectionKey] is undefined, renders nothing.
 */
export function SectionGuideButton({ sectionKey }: SectionGuideButtonProps) {
  const guide = DOCUMENT_GUIDES[sectionKey]
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const btnRef = useRef<HTMLButtonElement>(null)
  const [popoverPos, setPopoverPos] = useState<{ top: number; left: number }>({ top: 0, left: 0 })

  // Close on click outside
  useEffect(() => {
    if (!open) return
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [open])

  // Calculate popover position when opening
  useEffect(() => {
    if (!open || !btnRef.current) return
    const rect = btnRef.current.getBoundingClientRect()
    const spaceBelow = window.innerHeight - rect.bottom
    // If not enough space below (less than 300px), align near top of viewport
    const top = spaceBelow < 300 ? 24 : rect.bottom + 4
    // Keep left within viewport
    const left = Math.min(rect.left, window.innerWidth - 580)
    setPopoverPos({ top: Math.max(top, 8), left: Math.max(left, 8) })
  }, [open])

  if (!guide) return null

  return (
    <div ref={containerRef} style={{ display: 'inline-block', verticalAlign: 'middle' }}>
      <button
        ref={btnRef}
        type="button"
        onClick={() => setOpen(prev => !prev)}
        style={{
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          fontSize: size.md,
          color: color.info,
          padding: '0 4px',
          lineHeight: 1,
          verticalAlign: 'middle',
        }}
        title="작성 가이드 보기"
        aria-label="작성 가이드 보기"
      >
        ⓘ
      </button>
      {open && (
        <div
          style={{
            position: 'fixed',
            top: popoverPos.top,
            left: popoverPos.left,
            zIndex: 9999,
            background: color.bgSurface,
            border: `1px solid ${color.border}`,
            borderRadius: radius.md,
            boxShadow: shadow.elevated,
            maxWidth: 640,
            width: 'min(560px, calc(100vw - 48px))',
            maxHeight: '70vh',
            overflowY: 'auto',
            padding: space.lg,
          }}
        >
          {/* Title */}
          <div style={{
            fontWeight: 700,
            fontSize: 15,
            color: color.textPrimary,
            fontFamily: font.heading,
            marginBottom: space.sm,
          }}>
            {guide.title}
          </div>

          {/* Purpose */}
          <div style={{
            fontSize: 13,
            color: color.textSecondary,
            marginBottom: space.md,
            lineHeight: 1.6,
          }}>
            {guide.purpose}
          </div>

          {/* Blocks */}
          {guide.blocks.map((block, bi) => (
            <div key={bi} style={{ marginBottom: 16 }}>
              <div style={{
                fontWeight: 600,
                fontSize: 13,
                color: color.textPrimary,
                marginBottom: space.xs,
              }}>
                {block.heading}
              </div>
              <ul style={{
                margin: 0,
                paddingLeft: space.lg,
                listStyleType: 'disc',
              }}>
                {block.items.map((item, ii) => (
                  <li key={ii} style={{
                    fontSize: 12,
                    color: color.textSecondary,
                    lineHeight: 1.7,
                    marginBottom: 2,
                  }}>
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          ))}

          {/* Useful Prompts */}
          {guide.useful_prompts && guide.useful_prompts.length > 0 && (
            <div style={{ marginBottom: 16 }}>
              <div style={{
                fontWeight: 600,
                fontSize: 13,
                color: color.textPrimary,
                marginBottom: space.xs,
              }}>
                유용한 AI 프롬프트
              </div>
              <ul style={{
                margin: 0,
                paddingLeft: space.lg,
                listStyleType: '"💡 "',
              }}>
                {guide.useful_prompts.map((prompt, pi) => (
                  <li key={pi} style={{
                    fontSize: 12,
                    color: color.info,
                    lineHeight: 1.7,
                    marginBottom: 2,
                  }}>
                    {prompt}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Tips */}
          {guide.tips.length > 0 && (
            <div>
              <div style={{
                fontWeight: 600,
                fontSize: 13,
                color: color.textPrimary,
                marginBottom: space.xs,
              }}>
                💡 Tips
              </div>
              <ul style={{
                margin: 0,
                paddingLeft: space.lg,
                listStyleType: '"• "',
              }}>
                {guide.tips.map((tip, ti) => (
                  <li key={ti} style={{
                    fontSize: 12,
                    color: color.textSecondary,
                    lineHeight: 1.7,
                    marginBottom: 2,
                  }}>
                    {tip}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
