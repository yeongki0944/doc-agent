import { useMemo, useState } from 'react'
import { useDocumentStore, type ArchitectureService } from '../../store/documentStore'
import { apiFetch } from '../../auth/api'
import { useSessionStore } from '../../store/sessionStore'
import { color } from '../../styles/tokens'
import { resolveFieldValue } from '../AiBadge'
import { isBedrockService, sortArchitectureServices } from '../../utils/frontendSchema'

export function ArchitectureSection() {
  const DOC_ID = useSessionStore(s => s.currentDocId) || ''
  const [fileName, setFileName] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const archSection = useDocumentStore(s => s.sections?.architecture) as Record<string, any> | undefined
  const previewUrl = archSection?.preview_url ?? null
  const drawioUrl = archSection?.drawio_url ?? null
  const services = useMemo(() => sortArchitectureServices((archSection?.services ?? []) as ArchitectureService[]), [archSection?.services])

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

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
    } catch {
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

      {archSection?.overview && (
        <div style={{ marginBottom: 16, padding: 12, borderRadius: 8, background: color.bgPrimary, border: `1px solid ${color.border}` }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: color.textMuted, marginBottom: 4 }}>Overview</div>
          <div>{String(resolveFieldValue(archSection.overview))}</div>
        </div>
      )}

      {services.length > 0 ? (
        <div style={{ display: 'grid', gap: 12, marginBottom: 16 }}>
          {services.map(service => (
            <div key={`${service.service_id ?? resolveFieldValue(service.service_name)}`} style={serviceCard}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'flex-start' }}>
                <div>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                    <strong>{String(resolveFieldValue(service.service_name))}</strong>
                    <span style={chipStyle}>#{service.priority}</span>
                    <span style={chipStyle}>{service.category}</span>
                    {isBedrockService(service) && (
                      <span style={{ ...chipStyle, background: '#fef3c7', color: '#92400e', borderColor: '#fcd34d' }}>Funding required</span>
                    )}
                  </div>
                  <div style={{ fontSize: 12, color: color.textMuted, marginTop: 4 }}>
                    {service.service_id || ''}
                  </div>
                </div>
              </div>
              <div style={{ marginTop: 10 }}>
                <div style={label}>Description</div>
                <div>{String(resolveFieldValue(service.description) || '—')}</div>
              </div>
              <div style={{ marginTop: 8 }}>
                <div style={label}>Sizing rationale</div>
                <div>{String(resolveFieldValue(service.sizing_rationale) || '—')}</div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div style={{ marginBottom: 16, padding: 16, background: '#f9fafb', borderRadius: 8, textAlign: 'center', color: color.textMuted }}>
          {uploading
            ? '다이어그램 분석 중...'
            : fileName
              ? '다이어그램 처리 대기 중... (AppSync 패치로 업데이트됩니다)'
              : '아키텍처 다이어그램이 아직 업로드되지 않았습니다.'}
        </div>
      )}

      {!services.length && archSection && Object.keys(archSection).length > 0 && (
        <div style={{ marginBottom: 16 }}>
          {Object.entries(archSection).filter(([k, v]) => !['preview_url', 'drawio_url', 'services', 'overview'].includes(k) && v).map(([key, val]) => (
            <div key={key} style={{ marginBottom: 8, padding: 8, background: color.aiBadgeBg, borderRadius: 4 }}>
              <span style={{ fontWeight: 600 }}>{key}: </span>
              {String(val)}
              <span style={badgeStyle}>AI</span>
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
      ) : null}
    </div>
  )
}

const serviceCard: React.CSSProperties = {
  padding: 12,
  border: `1px solid ${color.border}`,
  borderRadius: 8,
  background: color.bgSurface,
}

const chipStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  padding: '2px 8px',
  borderRadius: 999,
  border: `1px solid ${color.border}`,
  background: color.bgPrimary,
  fontSize: 11,
  color: color.textSecondary,
}

const badgeStyle: React.CSSProperties = {
  padding: '1px 5px',
  borderRadius: 4,
  fontSize: 9,
  fontWeight: 700,
  color: color.aiBadgeText,
  background: color.aiBadgeBg,
  border: `1px solid ${color.aiBadgeBorder}`,
  marginLeft: 8,
}

const label: React.CSSProperties = { fontSize: 11, fontWeight: 700, color: color.textMuted, marginBottom: 2 }
