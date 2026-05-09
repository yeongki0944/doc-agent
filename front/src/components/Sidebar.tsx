import { useEffect, useState } from 'react'
import { useSessionStore } from '../store/sessionStore'
import { useAuth } from '../auth/AuthContext'
import { color, font, space, radius, shadow } from '../styles/tokens'
import { resolveDisplayText } from '../utils/frontendSchema'
import { AccountModal } from './AccountModal'

export interface SidebarProps {
  collapsed?: boolean
  onToggle?: () => void
  activeView?: 'documents' | 'rules_admin'
  onNavigate?: (view: 'documents' | 'rules_admin') => void
}

export function Sidebar({ collapsed = false, onToggle, activeView = 'documents', onNavigate }: SidebarProps) {
  const { user, logout } = useAuth()
  const documents = useSessionStore(s => s.documents)
  const currentDocId = useSessionStore(s => s.currentDocId)
  const loading = useSessionStore(s => s.loading)
  const fetchDocuments = useSessionStore(s => s.fetchDocuments)
  const createDocument = useSessionStore(s => s.createDocument)
  const deleteDocument = useSessionStore(s => s.deleteDocument)
  const selectDocument = useSessionStore(s => s.selectDocument)
  const [deleting, setDeleting] = useState<string | null>(null)
  const [accountOpen, setAccountOpen] = useState(false)

  useEffect(() => {
    fetchDocuments()
  }, [fetchDocuments])

  const handleCreate = async () => {
    await createDocument()
  }

  const handleDelete = async (e: React.MouseEvent, docId: string) => {
    e.stopPropagation()
    if (!confirm('이 문서를 삭제하시겠습니까?')) return
    setDeleting(docId)
    try {
      await deleteDocument(docId)
    } finally {
      setDeleting(null)
    }
  }

  // Collapsed rail view
  if (collapsed) {
    return (
      <div style={{
        width: 48, minWidth: 48, height: '100vh', display: 'flex', flexDirection: 'column',
        background: color.bgPrimary, borderRight: `1px solid ${color.border}`,
        alignItems: 'center', paddingTop: 12,
      }}>
        <span style={{ fontSize: 18, marginBottom: 8 }} title="MZC PoC Funding Platform">📄</span>
        <button
          onClick={onToggle}
          style={{
            background: 'none', border: 'none', cursor: 'pointer',
            fontSize: 14, color: color.textSecondary, padding: '4px',
            borderRadius: 4, lineHeight: 1,
          }}
          title="사이드바 펼치기"
        >
          ▶
        </button>
      </div>
    )
  }

  return (
    <div style={{
      width: 240, minWidth: 240, height: '100vh', display: 'flex', flexDirection: 'column',
      background: color.bgPrimary, borderRight: `1px solid ${color.border}`,
    }}>
      {/* Header */}
      <div style={{ padding: '16px 12px 8px', borderBottom: `1px solid ${color.border}` }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
          <span style={{ fontWeight: 800, fontSize: 14, letterSpacing: '-0.01em', color: color.textPrimary }}>MZC PoC Funding Platform</span>
          {onToggle && (
            <button
              onClick={onToggle}
              style={{
                background: 'none', border: 'none', cursor: 'pointer',
                fontSize: 13, color: color.textSecondary, padding: '2px 4px',
                borderRadius: 4, lineHeight: 1,
              }}
              title="사이드바 접기"
            >
              ◀
            </button>
          )}
        </div>
        <button
          onClick={handleCreate}
          className="mzc-btn mzc-btn-primary"
          style={{ width: '100%', fontSize: 13 }}
        >
          + 새 문서
        </button>
      </div>

      {/* Document list */}
      <div style={{ flex: 1, overflow: 'auto', padding: '8px 0' }}>
        {loading && documents.length === 0 && (
          <div style={{ padding: 12, color: color.textMuted, fontSize: 13, textAlign: 'center' }}>불러오는 중...</div>
        )}
        {!loading && documents.length === 0 && (
          <div style={{ padding: 12, color: color.textMuted, fontSize: 13, textAlign: 'center' }}>
            문서가 없습니다.<br />새 문서를 만들어보세요.
          </div>
        )}
        {documents.map(doc => (
          <div
            key={doc.document_id}
            onClick={() => selectDocument(doc.document_id)}
            style={{
              padding: '10px 12px', margin: '0 8px', borderRadius: 6, cursor: 'pointer',
              background: currentDocId === doc.document_id ? color.bgSubtle : 'transparent',
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              gap: 4,
            }}
          >
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{
                fontSize: 13, fontWeight: currentDocId === doc.document_id ? 600 : 400,
                whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
              }}>
                {resolveDisplayText(doc.title, '제목 없음')}
              </div>
              {doc.updated_at && (
                <div style={{ fontSize: 11, color: color.textMuted, marginTop: 2 }}>
                  {new Date(doc.updated_at).toLocaleDateString('ko-KR')}
                </div>
              )}
            </div>
            <button
              onClick={(e) => handleDelete(e, doc.document_id)}
              disabled={deleting === doc.document_id}
              title="삭제"
              style={{
                background: 'none', border: 'none', cursor: 'pointer', padding: '2px 6px',
                fontSize: 14, color: color.textMuted, borderRadius: 4, flexShrink: 0,
              }}
            >
              {deleting === doc.document_id ? '...' : '✕'}
            </button>
          </div>
        ))}
      </div>

      {/* Footer — user info + account actions */}
      <div style={{
        padding: '12px', borderTop: `1px solid ${color.border}`,
        display: 'flex', flexDirection: 'column', gap: 8,
      }}>
        {onNavigate && (
          <div style={{ display: 'flex', gap: 6 }}>
            <button
              onClick={() => onNavigate('documents')}
              style={{
                flex: 1, background: activeView === 'documents' ? color.bgSubtle : 'transparent',
                border: `1px solid ${activeView === 'documents' ? color.borderStrong : color.border}`,
                borderRadius: 4, padding: '5px 8px', fontSize: 12,
                color: activeView === 'documents' ? color.textPrimary : color.textSecondary,
                cursor: 'pointer', fontWeight: activeView === 'documents' ? 600 : 400,
              }}
              title="문서 목록"
            >
              📄 Documents
            </button>
            <button
              onClick={() => onNavigate('rules_admin')}
              style={{
                flex: 1, background: activeView === 'rules_admin' ? color.bgSubtle : 'transparent',
                border: `1px solid ${activeView === 'rules_admin' ? color.borderStrong : color.border}`,
                borderRadius: 4, padding: '5px 8px', fontSize: 12,
                color: activeView === 'rules_admin' ? color.textPrimary : color.textSecondary,
                cursor: 'pointer', fontWeight: activeView === 'rules_admin' ? 600 : 400,
              }}
              title="리뷰 규칙 관리"
            >
              ⚙ Rules
            </button>
          </div>
        )}
        <div style={{ fontSize: 12, color: color.textSecondary, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={user?.email || '사용자'}>
          {user?.email || '사용자'}
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <button
            onClick={() => setAccountOpen(true)}
            style={{
              flex: 1, background: color.bgSurface, border: `1px solid ${color.border}`, borderRadius: 4,
              padding: '5px 8px', fontSize: 12, color: color.textPrimary, cursor: 'pointer',
            }}
          >
            내 계정
          </button>
          <button
            onClick={logout}
            style={{
              flex: 1, background: 'none', border: `1px solid ${color.border}`, borderRadius: 4,
              padding: '5px 8px', fontSize: 12, color: color.textSecondary, cursor: 'pointer',
            }}
          >
            로그아웃
          </button>
        </div>
      </div>
      <AccountModal open={accountOpen} onClose={() => setAccountOpen(false)} />
    </div>
  )
}
