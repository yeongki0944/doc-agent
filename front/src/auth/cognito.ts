import {
  CognitoUserPool,
  CognitoUser,
  AuthenticationDetails,
  CognitoUserAttribute,
  CognitoUserSession,
} from 'amazon-cognito-identity-js'

const USER_POOL_ID = import.meta.env.VITE_COGNITO_USER_POOL_ID as string
const CLIENT_ID = import.meta.env.VITE_COGNITO_CLIENT_ID as string

const userPool = new CognitoUserPool({
  UserPoolId: USER_POOL_ID,
  ClientId: CLIENT_ID,
})

export interface AuthUser {
  sub: string
  email: string
}

// ── helpers ──

function getSession(): Promise<CognitoUserSession | null> {
  const user = userPool.getCurrentUser()
  if (!user) return Promise.resolve(null)
  return new Promise((resolve) => {
    user.getSession((err: Error | null, session: CognitoUserSession | null) => {
      if (err || !session || !session.isValid()) resolve(null)
      else resolve(session)
    })
  })
}

function parseUser(session: CognitoUserSession): AuthUser {
  const payload = session.getIdToken().decodePayload()
  return { sub: payload.sub, email: payload.email }
}

// ── public API ──

export async function login(email: string, password: string): Promise<AuthUser> {
  const user = new CognitoUser({ Username: email, Pool: userPool })
  const authDetails = new AuthenticationDetails({ Username: email, Password: password })

  return new Promise((resolve, reject) => {
    user.authenticateUser(authDetails, {
      onSuccess: (session) => resolve(parseUser(session)),
      onFailure: (err) => reject(err),
      newPasswordRequired: () => reject(new Error('NEW_PASSWORD_REQUIRED')),
    })
  })
}

export async function signUp(email: string, password: string): Promise<string> {
  const attrs = [new CognitoUserAttribute({ Name: 'email', Value: email })]

  return new Promise((resolve, reject) => {
    userPool.signUp(email, password, attrs, [], (err, result) => {
      if (err) return reject(err)
      resolve(result?.userSub || '')
    })
  })
}

export async function confirmSignUp(email: string, code: string): Promise<void> {
  const user = new CognitoUser({ Username: email, Pool: userPool })
  return new Promise((resolve, reject) => {
    user.confirmRegistration(code, true, (err) => {
      if (err) reject(err)
      else resolve()
    })
  })
}

export async function resendConfirmationCode(email: string): Promise<void> {
  const user = new CognitoUser({ Username: email, Pool: userPool })
  return new Promise((resolve, reject) => {
    user.resendConfirmationCode((err) => {
      if (err) reject(err)
      else resolve()
    })
  })
}

export async function forgotPassword(email: string): Promise<void> {
  const user = new CognitoUser({ Username: email, Pool: userPool })
  return new Promise((resolve, reject) => {
    let settled = false
    user.forgotPassword({
      onSuccess: () => {
        if (!settled) {
          settled = true
          resolve()
        }
      },
      onFailure: (err) => {
        if (!settled) {
          settled = true
          reject(err)
        }
      },
      inputVerificationCode: () => {
        if (!settled) {
          settled = true
          resolve()
        }
      },
    })
  })
}

export async function confirmForgotPassword(email: string, code: string, newPassword: string): Promise<void> {
  const user = new CognitoUser({ Username: email, Pool: userPool })
  return new Promise((resolve, reject) => {
    user.confirmPassword(code, newPassword, {
      onSuccess: () => resolve(),
      onFailure: (err) => reject(err),
    })
  })
}

export async function changePassword(oldPassword: string, newPassword: string): Promise<void> {
  const user = userPool.getCurrentUser()
  if (!user) throw new Error('로그인 세션을 찾을 수 없습니다. 다시 로그인해주세요.')

  const session = await getSession()
  if (!session || !session.isValid()) {
    throw new Error('로그인 세션이 만료되었습니다. 다시 로그인해주세요.')
  }

  return new Promise((resolve, reject) => {
    user.changePassword(oldPassword, newPassword, (err) => {
      if (err) reject(err)
      else resolve()
    })
  })
}

export async function getCurrentUser(): Promise<AuthUser | null> {
  const session = await getSession()
  if (!session) return null
  return parseUser(session)
}

export async function getIdToken(): Promise<string | null> {
  const session = await getSession()
  if (!session) return null
  return session.getIdToken().getJwtToken()
}

export async function refreshTokens(): Promise<boolean> {
  const user = userPool.getCurrentUser()
  if (!user) return false
  const session = await getSession()
  if (!session) return false

  const refreshToken = session.getRefreshToken()
  return new Promise((resolve) => {
    user.refreshSession(refreshToken, (err: Error | null) => {
      resolve(!err)
    })
  })
}

export function logout(): void {
  const user = userPool.getCurrentUser()
  if (user) user.signOut()
  window.location.href = '/'
}

export async function isAuthenticated(): Promise<boolean> {
  const session = await getSession()
  return session !== null && session.isValid()
}
