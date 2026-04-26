import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react'
import {
  type AuthUser,
  getCurrentUser,
  isAuthenticated,
  logout as cognitoLogout,
  login as cognitoLogin,
  signUp as cognitoSignUp,
  confirmSignUp as cognitoConfirm,
  resendConfirmationCode,
} from './cognito'

interface AuthContextType {
  user: AuthUser | null
  authenticated: boolean
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  signUp: (email: string, password: string) => Promise<void>
  confirmSignUp: (email: string, code: string) => Promise<void>
  resendCode: (email: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextType | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    ;(async () => {
      const authed = await isAuthenticated()
      if (authed) {
        const u = await getCurrentUser()
        setUser(u)
      }
      setLoading(false)
    })()
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const u = await cognitoLogin(email, password)
    setUser(u)
  }, [])

  const signUp = useCallback(async (email: string, password: string) => {
    await cognitoSignUp(email, password)
  }, [])

  const confirmCode = useCallback(async (email: string, code: string) => {
    await cognitoConfirm(email, code)
  }, [])

  const resendCode = useCallback(async (email: string) => {
    await resendConfirmationCode(email)
  }, [])

  const logout = useCallback(() => {
    setUser(null)
    cognitoLogout()
  }, [])

  return (
    <AuthContext.Provider value={{
      user,
      authenticated: !!user,
      loading,
      login,
      signUp,
      confirmSignUp: confirmCode,
      resendCode,
      logout,
    }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
