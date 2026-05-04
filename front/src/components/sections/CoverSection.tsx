import { useCallback, useState } from 'react'
import { useDocumentStore, type FieldValue } from '../../store/documentStore'
import { useSessionStore } from '../../store/sessionStore'
import { FieldValueEditor } from '../editors/FieldValueEditor'
import { EditableComboField } from '../editors/EditableComboField'
import { EditableField } from '../EditableField'
import { SaveStatusIndicator } from '../SaveStatusIndicator'
import { SectionGuideButton } from '../SectionGuideButton'
import { saveUserInput } from '../../utils/api'
import { useSaveStatus } from '../../hooks/useSaveStatus'
import { emitUserEdit } from '../../utils/userEditEvent'
import { useDocLang } from '../LangContext'
import { INDUSTRY_PRESETS, AWS_SERVICE_PRESETS } from '../../constants/documentPresets'
import { color, font, size, space } from '../../styles/tokens'

export function CoverSection() {
  const lang = useDocLang()
  const meta = useDocumentStore(s => s.meta)
  const koCover = useDocumentStore(s => s.sections?.cover) as Record<string, any> | undefined
  const enCover = useDocumentStore(s => s.sections_en?.cover) as Record<string, any> | undefined
  const cover = lang === 'en' && enCover ? enCover : koCover
  const title = useDocumentStore(s => (s as any).title || '')
  const setDocument = useDocumentStore(s => s.setDocument)
  const docId = useSessionStore(s => s.currentDocId) || ''
  const { saveStatus: titleSaveStatus, doSave: doTitleSave } = useSaveStatus()

  const handleMetaLocalUpdate = useCallback((field: string) => (newField: FieldValue) => {
    setDocument({
      meta: {
        ...meta,
        [field]: newField,
      },
    } as any)
  }, [meta, setDocument])

  const handleCoverFieldLocalUpdate = useCallback((field: string) => (newField: FieldValue) => {
    const sections = useDocumentStore.getState().sections || {}
    const updatedCover = { ...(sections.cover || {}), [field]: newField }
    setDocument({ sections: { ...sections, cover: updatedCover } } as any)
  }, [setDocument])

  const handleTitleSave = useCallback((newValue: string) => {
    setDocument({ title: newValue } as any)
    doTitleSave(() => saveUserInput(docId, 'title', newValue))
    emitUserEdit('Cover', '프로젝트명', String(title), newValue)
  }, [docId, title, setDocument, doTitleSave])

  return (
    <div>
      <h2 style={{ marginBottom: space.lg, fontSize: size.lg, fontWeight: 600, fontFamily: font.heading, display: 'flex', alignItems: 'center', gap: space.xs }}>
        1. Cover
        <SectionGuideButton sectionKey="cover" />
      </h2>

      {/* Required for DOCX Cover */}
      <div style={groupContainer}>
        <h3 style={groupHeading}>Required for DOCX Cover</h3>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <tbody>
            <MetaRow
              label="고객사"
              field={meta?.customer}
              dotPath="meta.customer.user_input"
              docId={docId}
              onLocalUpdate={handleMetaLocalUpdate('customer')}
            />
            <MetaRow
              label="파트너"
              field={meta?.partner}
              dotPath="meta.partner.user_input"
              docId={docId}
              onLocalUpdate={handleMetaLocalUpdate('partner')}
            />
            <MetaRow
              label="날짜"
              field={meta?.date}
              dotPath="meta.date.user_input"
              docId={docId}
              onLocalUpdate={handleMetaLocalUpdate('date')}
              type="date"
            />
            <tr>
              <td style={tdLabel}>프로젝트명</td>
              <td style={tdValue}>
                <div style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                  <EditableField
                    value={title}
                    isAi={false}
                    onSave={handleTitleSave}
                    placeholder="프로젝트명 입력"
                  />
                  <SaveStatusIndicator status={titleSaveStatus} />
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      {/* Optional Agent Context */}
      <div style={{ ...groupContainer, marginTop: space.lg }}>
        <h3 style={groupHeading}>Optional Agent Context</h3>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <tbody>
            <tr>
              <td style={tdLabel}>산업군</td>
              <td style={tdValue}>
                <EditableComboField
                  field={cover?.industry}
                  dotPath="sections.cover.industry.user_input"
                  docId={docId}
                  placeholder="산업군 선택 또는 입력"
                  presets={INDUSTRY_PRESETS}
                  onLocalUpdate={handleCoverFieldLocalUpdate('industry')}
                />
              </td>
            </tr>
            <tr>
              <td style={tdLabel}>프로젝트 배경</td>
              <td style={tdValue}>
                <FieldValueEditor
                  field={cover?.project_background}
                  dotPath="sections.cover.project_background.user_input"
                  docId={docId}
                  placeholder="프로젝트 배경 입력"
                  multiline
                  onLocalUpdate={handleCoverFieldLocalUpdate('project_background')}
                />
              </td>
            </tr>
            <tr>
              <td style={tdLabel}>주요 목표</td>
              <td style={tdValue}>
                <FieldValueEditor
                  field={cover?.main_objectives}
                  dotPath="sections.cover.main_objectives.user_input"
                  docId={docId}
                  placeholder="주요 목표 입력"
                  multiline
                  onLocalUpdate={handleCoverFieldLocalUpdate('main_objectives')}
                />
              </td>
            </tr>
            <tr>
              <td style={tdLabel}>예상 AWS 서비스</td>
              <td style={tdValue}>
                <EditableComboField
                  field={cover?.expected_aws_services}
                  dotPath="sections.cover.expected_aws_services.user_input"
                  docId={docId}
                  placeholder="AWS 서비스 선택 또는 입력"
                  presets={AWS_SERVICE_PRESETS}
                  onLocalUpdate={handleCoverFieldLocalUpdate('expected_aws_services')}
                />
              </td>
            </tr>
            <tr>
              <td style={tdLabel}>기간/예산 메모</td>
              <td style={tdValue}>
                <FieldValueEditor
                  field={cover?.timeline_budget_notes}
                  dotPath="sections.cover.timeline_budget_notes.user_input"
                  docId={docId}
                  placeholder="기간/예산 관련 메모 입력"
                  multiline
                  onLocalUpdate={handleCoverFieldLocalUpdate('timeline_budget_notes')}
                />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  )
}

function MetaRow({ label, field, dotPath, docId, onLocalUpdate, type }: {
  label: string
  field: FieldValue | undefined | null
  dotPath: string
  docId: string
  onLocalUpdate: (newField: FieldValue) => void
  type?: 'text' | 'date'
}) {
  return (
    <tr>
      <td style={tdLabel}>{label}</td>
      <td style={tdValue}>
        <FieldValueEditor
          field={field}
          dotPath={dotPath}
          docId={docId}
          placeholder={`${label} 입력`}
          type={type}
          onLocalUpdate={onLocalUpdate}
        />
      </td>
    </tr>
  )
}

const groupContainer: React.CSSProperties = {
  border: `1px solid ${color.border}`,
  borderRadius: 8,
  padding: space.lg,
  background: color.bgSurface,
}

const groupHeading: React.CSSProperties = {
  fontSize: size.base,
  fontWeight: 600,
  fontFamily: font.heading,
  color: color.textPrimary,
  marginTop: 0,
  marginBottom: space.md,
}

const tdLabel: React.CSSProperties = { padding: '8px 12px', fontWeight: 600, borderBottom: `1px solid ${color.border}`, width: 140 }
const tdValue: React.CSSProperties = { padding: '8px 12px', borderBottom: `1px solid ${color.border}` }
