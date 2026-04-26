import { useState } from 'react'
import { useDocumentStore } from '../../store/documentStore'
import { apiFetch } from '../../auth/api'
import { useSessionStore } from '../../store/sessionStore'
import { color } from '../../styles/tokens'

export function ArchitectureSection() {
  const DOC_ID = useSessionStore(s => s.currentDocId) || ''
  const [fileName, setFileName] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Read preview URL from store sections.architecture if available
  const archSection = useDocumentStore(s => s.sections?.architecture) as Record<string, any> | undefined
  const previewUrl = archSection?.preview_url ?? null
  const drawioUrl = archSection?.drawio_url ?? null

  // Text data fields (exclude upload-related keys)
  const uploadKeys = new Set(['preview_url', 'drawio_url'])
  const textEntries = archSection
    ? Object.entries(archSection).filter(([k, v]) => !uploadKeys.has(k) && v)
    : []

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    // Validate file extension
    if (!file.name.endsWith('.drawio') && !file.name.endsWith('.xml')) {
      setError('.drawio 또는 .xml 파일만 업로드 가능합니다.')
      return
    }

    setFileName(file.name)
    setError(null)
    setUploading(true)

    try {
      const formData = new FormData()
      formData.append('file', file)

      const res = await apiFetch(`/documents/${DOC_ID}/architecture/upload`, {
        method: 'POST',
        body: formData,
      })

      if (!res.ok) {
        throw new Error(`Upload failed: ${res.status}`)
      }

      // Response may contain preview_url and drawio_url
      // Actual state update will come via AppSync patch channel
    } catch (err) {
      setError('업로드 중 오류가 발생했습니다. 다시 시도해주세요.')
    } finally {
      setUploading(false)
    }
  }

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>Architecture</h2>

      <div style={{ marginBottom: 16 }}>
        <label
          style={{
            display: 'inline-block', padding: '8px 16px', background: color.bgPrimary,
            borderRadius: 6, cursor: uploading ? 'wait' : 'pointer', border: `1px dashed ${color.border}`,
            opacity: uploading ? 0.6 : 1,
          }}
        >
          <input
            type="file"
            accept=".drawio,.xml"
            onChange={handleUpload}
            disabled={uploading}
            style={{ display: 'none' }}
          />
          {uploading ? '업로드 중...' : '.drawio 파일 업로드'}
        </label>
        {fileName && <span style={{ marginLeft: 12, color: color.textSecondary }}>{fileName}</span>}
        {error && <div style={{ color: color.error, fontSize: 13, marginTop: 4 }}>{error}</div>}
      </div>

      {textEntries.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          {textEntries.map(([key, val]) => (
            <div key={key} style={{ marginBottom: 8, padding: 8, background: color.aiBadgeBg, borderRadius: 4 }}>
              <span style={{ fontWeight: 600 }}>{key}: </span>
              {String(val)}
              <span style={{ padding: '1px 5px', borderRadius: 4, fontSize: 9, fontWeight: 700, color: color.aiBadgeText, background: color.aiBadgeBg, border: `1px solid ${color.aiBadgeBorder}`, marginLeft: 8 }}>AI</span>
            </div>
          ))}
        </div>
      )}

      {previewUrl ? (
        <div>
          <img
            src={previewUrl}
            alt="Architecture diagram preview"
            style={{ maxWidth: '100%', border: `1px solid ${color.border}`, borderRadius: 8 }}
          />
          <div style={{ marginTop: 8, display: 'flex', gap: 12 }}>
            {drawioUrl && (
              <a href={drawioUrl} style={{ color: color.info, fontSize: 13 }} download>
                원본 .drawio 다운로드
              </a>
            )}
            <a href={previewUrl} target="_blank" rel="noopener noreferrer" style={{ color: color.info, fontSize: 13 }}>
              Preview 원본 보기
            </a>
          </div>
        </div>
      ) : (
        <div style={{ padding: 32, background: '#f9fafb', borderRadius: 8, textAlign: 'center', color: color.textMuted }}>
          {uploading
            ? '다이어그램 분석 중...'
            : fileName
              ? '다이어그램 처리 대기 중... (AppSync 패치로 업데이트됩니다)'
              : '아키텍처 다이어그램이 아직 업로드되지 않았습니다.'}
        </div>
      )}
    </div>
  )
}
