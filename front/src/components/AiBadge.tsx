/**
 * Shared AI recommendation visual indicators.
 * - AiBadge: small "AI" label
 * - AiHighlight: wrapper that adds yellow background + AI badge for ai_recommended values
 */

import type { FieldValue } from '../store/documentStore'
import { color } from '../styles/tokens'

/** Check if a FieldValue is showing an AI-recommended value (no user override) */
export function isAiRecommended(f: FieldValue | undefined | null): boolean {
  return f != null && f.user_input == null && f.ai_recommended != null
}

/** Resolve display value from FieldValue with priority: user_input > ai_recommended > calculated */
export function resolveFieldValue(f: FieldValue | undefined | null): any {
  if (!f) return null
  return f.user_input ?? f.ai_recommended ?? f.calculated ?? null
}

/** Small "AI" badge */
export function AiBadge() {
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '1px 5px',
        borderRadius: 4,
        fontSize: 9,
        fontWeight: 700,
        color: color.aiBadgeText,
        background: color.aiBadgeBg,
        border: `1px solid ${color.aiBadgeBorder}`,
        marginLeft: 4,
        verticalAlign: 'middle',
        lineHeight: '14px',
      }}
    >
      AI
    </span>
  )
}

/** Wrapper that highlights AI-recommended values with yellow background + badge */
export function AiHighlight({
  field,
  children,
}: {
  field: FieldValue | undefined | null
  children: React.ReactNode
}) {
  const isAi = isAiRecommended(field)
  return (
    <span
      style={{
        background: isAi ? color.aiBadgeBg : 'transparent',
        padding: isAi ? '2px 6px' : 0,
        borderRadius: isAi ? 4 : 0,
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
      }}
    >
      {children}
      {isAi && <AiBadge />}
    </span>
  )
}
