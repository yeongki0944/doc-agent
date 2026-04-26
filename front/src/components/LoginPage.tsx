import { useState, useMemo } from 'react'
import { useAuth } from '../auth/AuthContext'

import { color, font, space, radius, shadow } from '../styles/tokens'
import { input as inputStyle, buttonPrimary } from '../styles/components'

type Mode = 'login' | 'signup' | 'confirm'

const ALLOWED_DOMAINS = ['mz.co.kr', 'megazone.com']

function validateEmail(email: string) {
  const checks = {
    format: /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email),
    domain: false,
  }
  if (checks.format) {
    const domain = email.split('@')[1]?.toLowerCase() || ''
    checks.domain = ALLOWED_DOMAINS.includes(domain)
  }
  return checks
}

function validatePassword(pw: string) {
  return {
    minLength: pw.length >= 8,
    hasLower: /[a-z]/.test(pw),
    hasNumber: /\d/.test(pw),
  }
}

function Check({ ok, label }: { ok: boolean; label: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: ok ? color.success : color.textMuted }}>
      <span style={{ fontSize: 14 }}>{ok ? '✓' : '○'}</span>
      <span>{label}</span>
    </div>
  )
}

export default function LoginPage() {
  const { login, signUp, confirmSignUp, resendCode } = useAuth()
  const [mode, setMode] = useState<Mode>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')

  const emailChecks = useMemo(() => validateEmail(email), [email])
  const pwChecks = useMemo(() => validatePassword(password), [password])
  const pwMatch = password.length > 0 && confirmPassword.length > 0 && password === confirmPassword
  const emailValid = emailChecks.format && emailChecks.domain
  const pwValid = pwChecks.minLength && pwChecks.hasLower && pwChecks.hasNumber
  const signUpReady = emailValid && pwValid && pwMatch

  const clearState = () => { setError(''); setMessage('') }

  const handleLogin = async () => {
    clearState()
    setLoading(true)
    try {
      await login(email, password)
    } catch (e: any) {
      const msg = e?.message || String(e)
      if (msg === 'User is not confirmed.') {
        setMode('confirm')
        setMessage('이메일 인증이 필요합니다. 인증 코드를 입력해주세요.')
      } else if (msg.includes('Incorrect username or password')) {
        setError('이메일 또는 비밀번호가 올바르지 않습니다.')
      } else {
        setError(msg)
      }
    } finally {
      setLoading(false)
    }
  }

  const handleSignUp = async () => {
    clearState()
    if (!signUpReady) return
    setLoading(true)
    try {
      await signUp(email, password)
      setMode('confirm')
      setMessage('인증 코드가 이메일로 발송되었습니다.')
    } catch (e: any) {
      const msg = e?.message || String(e)
      if (msg.includes('PreSignUp')) {
        setError('@mz.co.kr 또는 @megazone.com 이메일만 가입 가능합니다.')
      } else if (msg.includes('already exists')) {
        setError('이미 가입된 이메일입니다.')
      } else {
        setError(msg)
      }
    } finally {
      setLoading(false)
    }
  }

  const handleConfirm = async () => {
    clearState()
    setLoading(true)
    try {
      await confirmSignUp(email, code)
      setMessage('인증 완료! 로그인합니다...')
      await login(email, password)
    } catch (e: any) {
      setError(e?.message || '인증 코드가 올바르지 않습니다.')
    } finally {
      setLoading(false)
    }
  }

  const handleResend = async () => {
    clearState()
    try {
      await resendCode(email)
      setMessage('인증 코드가 재발송되었습니다.')
    } catch (e: any) {
      setError(e?.message || '재발송 실패')
    }
  }

  return (
    <div style={s.container}>
      <div style={s.card}>
        <h1 style={{ marginBottom: 4, fontSize: 22 }}>Doc Agent</h1>
        <p style={{ color: '#666', marginBottom: 24, fontSize: 13 }}>
          APN PoC Project Plan 자동 생성
        </p>

        {mode === 'confirm' ? (
          <>
            <p style={{ fontSize: 13, color: '#374151', marginBottom: 16 }}>
              <strong>{email}</strong>로 발송된 인증 코드를 입력해주세요.
            </p>
            <input
              style={s.input}
              placeholder="인증 코드 6자리"
              value={code}
              onChange={e => setCode(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleConfirm()}
              maxLength={6}
              autoFocus
            />
            <button onClick={handleConfirm} disabled={loading || code.length < 6} style={{
              ...s.btn, opacity: loading || code.length < 6 ? 0.6 : 1,
            }}>
              {loading ? '확인 중...' : '인증 확인'}
            </button>
            <button onClick={handleResend} style={s.linkBtn}>인증 코드 재발송</button>
            <button onClick={() => { setMode('login'); clearState() }} style={s.linkBtn}>
              ← 로그인으로 돌아가기
            </button>
          </>
        ) : (
          <>
            {/* Email */}
            <div style={{ position: 'relative', marginBottom: mode === 'signup' && email.length > 0 ? 4 : 10 }}>
              <input
                style={{
                  ...s.input, marginBottom: 0,
                  borderColor: mode === 'signup' && email.length > 0
                    ? (emailValid ? '#22c55e' : '#ef4444') : '#d1d5db',
                }}
                type="email"
                placeholder="이메일"
                value={email}
                onChange={e => setEmail(e.target.value)}
                autoFocus
              />
            </div>
            {mode === 'signup' && email.length > 0 && (
              <div style={s.checkGroup}>
                <Check ok={emailChecks.format} label="올바른 이메일 형식" />
                <Check ok={emailChecks.domain} label="허용 도메인 (@mz.co.kr / @megazone.com)" />
              </div>
            )}

            {/* Password */}
            <div style={{ marginBottom: mode === 'signup' && password.length > 0 ? 4 : 10 }}>
              <input
                style={{
                  ...s.input, marginBottom: 0,
                  borderColor: mode === 'signup' && password.length > 0
                    ? (pwValid ? '#22c55e' : '#ef4444') : '#d1d5db',
                }}
                type="password"
                placeholder="비밀번호"
                value={password}
                onChange={e => setPassword(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && mode === 'login' && handleLogin()}
              />
            </div>
            {mode === 'signup' && password.length > 0 && (
              <div style={s.checkGroup}>
                <Check ok={pwChecks.minLength} label="8자 이상" />
                <Check ok={pwChecks.hasLower} label="영문 소문자 포함" />
                <Check ok={pwChecks.hasNumber} label="숫자 포함" />
              </div>
            )}

            {/* Confirm Password */}
            {mode === 'signup' && (
              <>
                <div style={{ marginBottom: confirmPassword.length > 0 ? 4 : 10 }}>
                  <input
                    style={{
                      ...s.input, marginBottom: 0,
                      borderColor: confirmPassword.length > 0
                        ? (pwMatch ? '#22c55e' : '#ef4444') : '#d1d5db',
                    }}
                    type="password"
                    placeholder="비밀번호 확인"
                    value={confirmPassword}
                    onChange={e => setConfirmPassword(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && signUpReady && handleSignUp()}
                  />
                </div>
                {confirmPassword.length > 0 && (
                  <div style={s.checkGroup}>
                    <Check ok={pwMatch} label="비밀번호 일치" />
                  </div>
                )}
              </>
            )}

            {/* Buttons */}
            {mode === 'login' ? (
              <>
                <button onClick={handleLogin} disabled={loading} style={s.btn}>
                  {loading ? '로그인 중...' : '로그인'}
                </button>
                <button onClick={() => { setMode('signup'); clearState() }} style={s.linkBtn}>
                  계정이 없으신가요? 회원가입
                </button>
              </>
            ) : (
              <>
                <button
                  onClick={handleSignUp}
                  disabled={loading || !signUpReady}
                  style={{ ...s.btn, opacity: loading || !signUpReady ? 0.5 : 1, cursor: loading || !signUpReady ? 'not-allowed' : 'pointer' }}
                >
                  {loading ? '가입 중...' : '회원가입'}
                </button>
                <button onClick={() => { setMode('login'); clearState() }} style={s.linkBtn}>
                  이미 계정이 있으신가요? 로그인
                </button>
              </>
            )}
          </>
        )}

        {error && <div style={s.error}>{error}</div>}
        {message && <div style={s.message}>{message}</div>}

        <p style={{ fontSize: 11, color: '#aaa', marginTop: 20 }}>
          @mz.co.kr, @megazone.com 이메일만 가입 가능
        </p>
      </div>
    </div>
  )
}

const s: Record<string, React.CSSProperties> = {
  container: {
    minHeight: '100vh', display: 'flex', alignItems: 'center',
    justifyContent: 'center', background: color.bgPrimary,
  },
  card: {
    background: color.bgSurface, padding: space.xxxl, borderRadius: radius.lg,
    boxShadow: shadow.elevated, width: 380, textAlign: 'center',
    border: `1px solid ${color.border}`,
  },
  input: {
    ...inputStyle, marginBottom: space.md,
    transition: 'border-color 0.15s',
  },
  btn: {
    ...buttonPrimary, width: '100%', marginTop: space.sm,
  },
  linkBtn: {
    background: 'none', border: 'none', color: color.mzRed, fontSize: 13,
    cursor: 'pointer', marginTop: space.md, display: 'block', width: '100%',
    fontFamily: font.body,
  },
  checkGroup: {
    display: 'flex', flexDirection: 'column' as const, gap: 2,
    padding: `${space.xs}px ${space.xs}px ${space.sm}px`, textAlign: 'left' as const,
  },
  error: {
    marginTop: space.md, padding: `${space.sm}px ${space.md}px`, background: '#fef2f2',
    color: color.error, borderRadius: radius.sm, fontSize: 13, textAlign: 'left' as const,
  },
  message: {
    marginTop: space.md, padding: `${space.sm}px ${space.md}px`, background: '#f0fdf4',
    color: color.success, borderRadius: radius.sm, fontSize: 13, textAlign: 'left' as const,
  },
}
