import { useEffect, useState } from 'react'
import { useSessionStore } from '../store/sessionStore'
import { useAuth } from '../auth/AuthContext'
import { color, font, space, radius, shadow } from '../styles/tokens'
import { resolveDisplayText } from '../utils/frontendSchema'

export function Sidebar() {
  const { user, logout } = useAuth()
  const documents = useSessionStore(s => s.documents)
  const currentDocId = useSessionStore(s => s.currentDocId)
  const loading = useSessionStore(s => s.loading)
  const fetchDocuments = useSessionStore(s => s.fetchDocuments)
  const createDocument = useSessionStore(s => s.createDocument)
  const deleteDocument = useSessionStore(s => s.deleteDocument)
  const selectDocument = useSessionStore(s => s.selectDocument)
  const [deleting, setDeleting] = useState<string | null>(null)

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

  return (
    <div style={{
      width: 240, minWidth: 240, height: '100vh', display: 'flex', flexDirection: 'column',
      background: color.bgPrimary, borderRight: `1px solid ${color.border}`,
    }}>
      {/* Header */}
      <div style={{ padding: '16px 12px 8px', borderBottom: `1px solid ${color.border}` }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
          <span style={{ fontWeight: 700, fontSize: 15 }}>Doc Agent</span>
        </div>
        <button
          onClick={handleCreate}
          style={{
            width: '100%', padding: '8px 12px', background: color.mzRed, color: color.bgSurface,
            border: 'none', borderRadius: 6, fontSize: 13, fontWeight: 500, cursor: 'pointer',
          }}
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

      {/* Footer — user info + logout */}
      <div style={{
        padding: '12px', borderTop: `1px solid ${color.border}`,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8,
      }}>
        <div style={{ fontSize: 12, color: color.textSecondary, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
          {user?.email || '사용자'}
        </div>
        <button
          onClick={logout}
          style={{
            background: 'none', border: `1px solid ${color.border}`, borderRadius: 4,
            padding: '4px 10px', fontSize: 12, color: color.textSecondary, cursor: 'pointer', flexShrink: 0,
          }}
        >
          로그아웃
        </button>
      </div>
    </div>
  )
}
