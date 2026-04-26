import { color, font, size, space, radius, shadow } from './tokens'

export const card: React.CSSProperties = {
  background: color.bgSurface,
  borderRadius: radius.lg,
  boxShadow: shadow.card,
  border: `1px solid ${color.border}`,
}

export const buttonPrimary: React.CSSProperties = {
  padding: `${space.md}px ${space.lg}px`,
  background: color.mzRed,
  color: '#fff',
  border: 'none',
  borderRadius: radius.sm,
  fontSize: size.base,
  fontWeight: 500,
  fontFamily: font.body,
  cursor: 'pointer',
  letterSpacing: '-0.01em',
}

export const buttonPrimaryDisabled: React.CSSProperties = {
  ...buttonPrimary,
  opacity: 0.5,
  cursor: 'not-allowed',
}

export const buttonGhost: React.CSSProperties = {
  padding: `${space.sm}px ${space.lg}px`,
  background: 'transparent',
  color: color.textPrimary,
  border: `1px solid ${color.border}`,
  borderRadius: radius.sm,
  fontSize: size.sm,
  fontWeight: 500,
  fontFamily: font.body,
  cursor: 'pointer',
}

export const input: React.CSSProperties = {
  width: '100%',
  padding: `${space.md}px ${space.lg}px`,
  border: `1px solid ${color.border}`,
  borderRadius: radius.sm,
  fontSize: size.base,
  fontFamily: font.body,
  color: color.textPrimary,
  background: color.bgSurface,
  outline: 'none',
  boxSizing: 'border-box' as const,
  letterSpacing: '-0.01em',
  lineHeight: 1.6,
}

export const badge: React.CSSProperties = {
  display: 'inline-block',
  padding: '1px 5px',
  borderRadius: 4,
  fontSize: 9,
  fontWeight: 700,
  color: color.aiBadgeText,
  background: color.aiBadgeBg,
  border: `1px solid ${color.aiBadgeBorder}`,
  verticalAlign: 'middle',
  lineHeight: '14px',
}

export const sectionTitle: React.CSSProperties = {
  fontSize: size.lg,
  fontWeight: 600,
  fontFamily: font.heading,
  color: color.textPrimary,
  marginBottom: space.lg,
  letterSpacing: '-0.01em',
}
