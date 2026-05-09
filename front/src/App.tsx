import { SplitLayout } from './components/SplitLayout'
import { useAuth } from './auth/AuthContext'
import LoginPage from './components/LoginPage'
import { ReviewRulesAdmin } from './components/admin/ReviewRulesAdmin'
import { LangProvider } from './components/LangContext'
import { useHashRoute, navigate } from './utils/hashRoute'

export default function App() {
  const { authenticated, loading } = useAuth()
  const route = useHashRoute()

  if (loading) return (
    <div style={{
      height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'var(--mzc-bg)', color: 'var(--mzc-text-muted)', fontSize: 14,
    }}>
      <div style={{ textAlign: 'center' }}>
        <div style={{
          display: 'inline-block', width: 36, height: 36, borderRadius: '50%',
          border: '3px solid var(--mzc-border)', borderTopColor: 'var(--mzc-primary)',
          animation: 'mzc-spin 0.9s linear infinite', marginBottom: 12,
        }} />
        <div>MZC PoC Funding Platform 로딩 중…</div>
        <style>{`@keyframes mzc-spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    </div>
  )
  if (!authenticated) return <LoginPage />

  // Admin routes — separate full-screen pages, no sidebar.
  if (route.startsWith('#/admin/rules')) {
    return (
      <LangProvider value="ko">
        <ReviewRulesAdmin onClose={() => navigate('#/')} />
      </LangProvider>
    )
  }

  return <SplitLayout />
}
