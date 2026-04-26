import { SplitLayout } from './components/SplitLayout'
import { useAuth } from './auth/AuthContext'
import LoginPage from './components/LoginPage'

export default function App() {
  const { authenticated, loading } = useAuth()

  if (loading) return <div style={{ padding: 40 }}>로딩 중...</div>
  if (!authenticated) return <LoginPage />

  return <SplitLayout />
}
