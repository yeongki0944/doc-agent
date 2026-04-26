import { useDocumentStore, type FieldValue } from '../../store/documentStore'
import { AiHighlight, resolveFieldValue } from '../AiBadge'

export function CoverSection() {
  const meta = useDocumentStore(s => s.meta)
  const cover = useDocumentStore(s => s.sections?.cover) as Record<string, any> | undefined

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>Cover Page</h2>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <tbody>
          <FieldRow label="고객사" field={meta?.customer} />
          <FieldRow label="파트너" field={meta?.partner} />
          <FieldRow label="날짜" field={meta?.date} />
          {cover?.title && <SimpleRow label="프로젝트명" value={cover.title} />}
          {cover?.goal && <SimpleRow label="목표" value={cover.goal} />}
          {cover?.period && <SimpleRow label="기간" value={cover.period} />}
          {cover?.budget && <SimpleRow label="예산" value={cover.budget} />}
          {cover?.aws_services && <SimpleRow label="AWS 서비스" value={cover.aws_services} />}
          {cover?.version && <SimpleRow label="버전" value={cover.version} />}
        </tbody>
      </table>
    </div>
  )
}

function FieldRow({ label, field }: { label: string; field: FieldValue | undefined | null }) {
  const value = resolveFieldValue(field)
  return (
    <tr>
      <td style={{ padding: '8px 12px', fontWeight: 600, borderBottom: '1px solid #eee', width: 120 }}>{label}</td>
      <td style={{ padding: '8px 12px', borderBottom: '1px solid #eee' }}>
        <AiHighlight field={field}>
          {value ?? '-'}
        </AiHighlight>
      </td>
    </tr>
  )
}

function SimpleRow({ label, value }: { label: string; value: string }) {
  return (
    <tr>
      <td style={{ padding: '8px 12px', fontWeight: 600, borderBottom: '1px solid #eee', width: 120 }}>{label}</td>
      <td style={{ padding: '8px 12px', borderBottom: '1px solid #eee', background: '#fef9c3' }}>
        {value} <span style={{ padding: '1px 5px', borderRadius: 4, fontSize: 9, fontWeight: 700, color: '#d97706', background: '#fef3c7', border: '1px solid #fde68a', marginLeft: 4 }}>AI</span>
      </td>
    </tr>
  )
}
