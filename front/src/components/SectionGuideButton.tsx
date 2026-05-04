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

  if (!guide) return null

  return (
    <div ref={containerRef} style={{ display: 'inline-block', position: 'relative', verticalAlign: 'middle' }}>
      <button
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
            position: 'absolute',
            top: '100%',
            left: 0,
            zIndex: 1000,
            background: color.bgSurface,
            border: `1px solid ${color.border}`,
            borderRadius: radius.md,
            boxShadow: shadow.elevated,
            maxWidth: 400,
            maxHeight: 420,
            overflowY: 'auto',
            padding: space.lg,
            marginTop: 4,
          }}
        >
          {/* Title */}
          <div style={{
            fontWeight: 700,
            fontSize: size.md,
            color: color.textPrimary,
            fontFamily: font.heading,
            marginBottom: space.sm,
          }}>
            {guide.title}
          </div>

          {/* Purpose */}
          <div style={{
            fontSize: size.sm,
            color: color.textSecondary,
            marginBottom: space.md,
            lineHeight: 1.5,
          }}>
            {guide.purpose}
          </div>

          {/* Blocks */}
          {guide.blocks.map((block, bi) => (
            <div key={bi} style={{ marginBottom: space.md }}>
              <div style={{
                fontWeight: 600,
                fontSize: size.sm,
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
                    fontSize: size.xs,
                    color: color.textSecondary,
                    lineHeight: 1.6,
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
            <div style={{ marginBottom: space.md }}>
              <div style={{
                fontWeight: 600,
                fontSize: size.sm,
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
                    fontSize: size.xs,
                    color: color.info,
                    lineHeight: 1.6,
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
                fontSize: size.sm,
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
                    fontSize: size.xs,
                    color: color.textSecondary,
                    lineHeight: 1.6,
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
