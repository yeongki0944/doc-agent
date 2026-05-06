import { useMemo, useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { color, font, radius, shadow, space } from '../styles/tokens'
import { buttonGhost, buttonPrimary, input as inputStyle } from '../styles/components'

interface AccountModalProps {
  open: boolean
  onClose: () => void
}

function validatePassword(pw: string) {
  return {
    minLength: pw.length >= 8,
    hasLower: /[a-z]/.test(pw),
    hasNumber: /\d/.test(pw),
  }
}

function changePasswordErrorMessage(error: any) {
  const code = error?.code || error?.name
  if (code === 'NotAuthorizedException') return '현재 비밀번호가 올바르지 않습니다.'
  if (code === 'LimitExceededException') return '요청이 너무 많습니다. 잠시 후 다시 시도해주세요.'
  return error?.message || String(error)
}

function Check({ ok, label }: { ok: boolean; label: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: ok ? color.success : color.textMuted }}>
      <span style={{ fontSize: 14 }}>{ok ? '✓' : '○'}</span>
      <span>{label}</span>
    </div>
  )
}

export function AccountModal({ open, onClose }: AccountModalProps) {
  const { user, changePassword, logout } = useAuth()
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const pwChecks = useMemo(() => validatePassword(newPassword), [newPassword])
  const pwValid = pwChecks.minLength && pwChecks.hasLower && pwChecks.hasNumber
  const pwMatch = newPassword.length > 0 && confirmPassword.length > 0 && newPassword === confirmPassword
  const ready = currentPassword.length > 0 && pwValid && pwMatch

  if (!open) return null

  const clearStatus = () => {
    setError('')
    setMessage('')
  }

  const handleSubmit = async () => {
    clearStatus()
    if (!ready) return
    setLoading(true)
    try {
      await changePassword(currentPassword, newPassword)
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
      setMessage('비밀번호가 변경되었습니다.')
    } catch (e: any) {
      setError(changePasswordErrorMessage(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={s.overlay} role="dialog" aria-modal="true" aria-label="내 계정">
      <div style={s.modal}>
        <div style={s.header}>
          <div>
            <h2 style={s.title}>내 계정</h2>
            <p style={s.subtitle}>Cognito 계정 정보를 관리합니다.</p>
          </div>
          <button type="button" onClick={onClose} style={s.closeBtn} aria-label="닫기">×</button>
        </div>

        <section style={s.section}>
          <h3 style={s.sectionTitle}>계정 정보</h3>
          <div style={s.detailGrid}>
            <span style={s.label}>Email</span>
            <span style={s.value}>{user?.email || '-'}</span>
            <span style={s.label}>Authentication</span>
            <span style={s.value}>Amazon Cognito</span>
            <span style={s.label}>Password</span>
            <span style={s.value}>Managed by Cognito</span>
          </div>
        </section>

        <section style={s.section}>
          <h3 style={s.sectionTitle}>비밀번호 변경</h3>
          <input
            style={s.input}
            type="password"
            placeholder="현재 비밀번호"
            value={currentPassword}
            onChange={e => setCurrentPassword(e.target.value)}
          />
          <input
            style={{
              ...s.input,
              borderColor: newPassword.length > 0 ? (pwValid ? '#22c55e' : '#ef4444') : color.border,
            }}
            type="password"
            placeholder="새 비밀번호"
            value={newPassword}
            onChange={e => setNewPassword(e.target.value)}
          />
          {newPassword.length > 0 && (
            <div style={s.checkGroup}>
              <Check ok={pwChecks.minLength} label="8자 이상" />
              <Check ok={pwChecks.hasLower} label="영문 소문자 포함" />
              <Check ok={pwChecks.hasNumber} label="숫자 포함" />
            </div>
          )}
          <input
            style={{
              ...s.input,
              borderColor: confirmPassword.length > 0 ? (pwMatch ? '#22c55e' : '#ef4444') : color.border,
            }}
            type="password"
            placeholder="새 비밀번호 확인"
            value={confirmPassword}
            onChange={e => setConfirmPassword(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && ready && handleSubmit()}
          />
          {confirmPassword.length > 0 && (
            <div style={s.checkGroup}>
              <Check ok={pwMatch} label="비밀번호 일치" />
            </div>
          )}

          {error && <div style={s.error}>{error}</div>}
          {message && <div style={s.message}>{message}</div>}

          <button
            type="button"
            onClick={handleSubmit}
            disabled={loading || !ready}
            style={{ ...s.primaryBtn, opacity: loading || !ready ? 0.5 : 1, cursor: loading || !ready ? 'not-allowed' : 'pointer' }}
          >
            {loading ? '변경 중...' : '비밀번호 변경'}
          </button>
        </section>

        <div style={s.footer}>
          <button type="button" onClick={logout} style={s.logoutBtn}>로그아웃</button>
        </div>
      </div>
    </div>
  )
}

const s: Record<string, React.CSSProperties> = {
  overlay: {
    position: 'fixed',
    inset: 0,
    zIndex: 1000,
    background: 'rgba(10, 37, 64, 0.32)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: space.lg,
  },
  modal: {
    width: '100%',
    maxWidth: 500,
    background: color.bgSurface,
    border: `1px solid ${color.border}`,
    borderRadius: radius.lg,
    boxShadow: shadow.elevated,
    padding: space.xl,
    fontFamily: font.body,
    color: color.textPrimary,
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    gap: space.md,
    marginBottom: space.lg,
  },
  title: {
    margin: 0,
    fontSize: 20,
    fontWeight: 700,
  },
  subtitle: {
    margin: '4px 0 0',
    color: color.textMuted,
    fontSize: 13,
  },
  closeBtn: {
    background: 'none',
    border: 'none',
    color: color.textSecondary,
    cursor: 'pointer',
    fontSize: 24,
    lineHeight: 1,
    padding: '0 4px',
  },
  section: {
    borderTop: `1px solid ${color.border}`,
    paddingTop: space.lg,
    marginTop: space.lg,
  },
  sectionTitle: {
    margin: `0 0 ${space.md}px`,
    fontSize: 14,
    fontWeight: 700,
  },
  detailGrid: {
    display: 'grid',
    gridTemplateColumns: '128px minmax(0, 1fr)',
    gap: `${space.sm}px ${space.md}px`,
    fontSize: 13,
  },
  label: {
    color: color.textMuted,
  },
  value: {
    color: color.textPrimary,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  input: {
    ...inputStyle,
    marginBottom: space.sm,
  },
  checkGroup: {
    display: 'flex',
    flexDirection: 'column',
    gap: 2,
    padding: `0 ${space.xs}px ${space.sm}px`,
  },
  primaryBtn: {
    ...buttonPrimary,
    width: '100%',
    marginTop: space.sm,
  },
  footer: {
    borderTop: `1px solid ${color.border}`,
    marginTop: space.lg,
    paddingTop: space.lg,
    display: 'flex',
    justifyContent: 'flex-end',
  },
  logoutBtn: {
    ...buttonGhost,
    color: color.textSecondary,
  },
  error: {
    marginTop: space.sm,
    marginBottom: space.sm,
    padding: `${space.sm}px ${space.md}px`,
    background: '#fef2f2',
    color: color.error,
    borderRadius: radius.sm,
    fontSize: 13,
  },
  message: {
    marginTop: space.sm,
    marginBottom: space.sm,
    padding: `${space.sm}px ${space.md}px`,
    background: '#f0fdf4',
    color: color.success,
    borderRadius: radius.sm,
    fontSize: 13,
  },
}
