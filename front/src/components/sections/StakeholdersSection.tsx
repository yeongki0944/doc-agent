import { useCallback } from 'react'
import { useDocumentStore, type StakeholdersSection as StakeholdersModel, type ContactEntry } from '../../store/documentStore'
import { useSessionStore } from '../../store/sessionStore'
import { ContactTableEditor } from '../editors/ContactTableEditor'
import { SectionGuideButton } from '../SectionGuideButton'
import { useDocLang } from '../LangContext'
import { color, font, size, space } from '../../styles/tokens'
import {
  TITLE_PRESETS,
  DESCRIPTION_PRESETS,
  STAKEHOLDER_FOR_PRESETS,
  ROLE_PRESETS,
} from '../../constants/documentPresets'

/** Column configuration per contact list (from design.md) */
const EXECUTIVE_SPONSORS_COLUMNS: (keyof ContactEntry)[] = ['name', 'title', 'description', 'contact']
const STAKEHOLDERS_COLUMNS: (keyof ContactEntry)[] = ['name', 'title', 'stakeholder_for', 'contact']
const PROJECT_TEAM_COLUMNS: (keyof ContactEntry)[] = ['name', 'title', 'role', 'contact']
const ESCALATION_CONTACTS_COLUMNS: (keyof ContactEntry)[] = ['name', 'title', 'role', 'contact']

type ListKey = 'executive_sponsors' | 'stakeholders' | 'project_team' | 'escalation_contacts'

/** Column presets per contact list */
const EXECUTIVE_SPONSORS_PRESETS: Partial<Record<keyof ContactEntry, readonly (string | number)[]>> = {
  title: TITLE_PRESETS,
  description: DESCRIPTION_PRESETS,
}

const STAKEHOLDERS_PRESETS: Partial<Record<keyof ContactEntry, readonly (string | number)[]>> = {
  title: TITLE_PRESETS,
  stakeholder_for: STAKEHOLDER_FOR_PRESETS,
}

const PROJECT_TEAM_PRESETS: Partial<Record<keyof ContactEntry, readonly (string | number)[]>> = {
  title: TITLE_PRESETS,
  role: ROLE_PRESETS,
}

const ESCALATION_CONTACTS_PRESETS: Partial<Record<keyof ContactEntry, readonly (string | number)[]>> = {
  title: TITLE_PRESETS,
  role: ROLE_PRESETS,
}

const LIST_CONFIG: { key: ListKey; label: string; columns: (keyof ContactEntry)[]; columnPresets: Partial<Record<keyof ContactEntry, readonly (string | number)[]>> }[] = [
  { key: 'executive_sponsors', label: 'Partner Executive Sponsor', columns: EXECUTIVE_SPONSORS_COLUMNS, columnPresets: EXECUTIVE_SPONSORS_PRESETS },
  { key: 'stakeholders', label: 'Project Stakeholders', columns: STAKEHOLDERS_COLUMNS, columnPresets: STAKEHOLDERS_PRESETS },
  { key: 'project_team', label: 'Partner Project Team', columns: PROJECT_TEAM_COLUMNS, columnPresets: PROJECT_TEAM_PRESETS },
  { key: 'escalation_contacts', label: 'Project Escalation Contacts', columns: ESCALATION_CONTACTS_COLUMNS, columnPresets: ESCALATION_CONTACTS_PRESETS },
]

export function StakeholdersSection() {
  const lang = useDocLang()
  const koData = useDocumentStore(s => s.sections?.stakeholders) as StakeholdersModel | undefined
  const enData = useDocumentStore(s => s.sections_en?.stakeholders) as StakeholdersModel | undefined
  const sectionData = lang === 'en' ? enData : koData
  const setDocument = useDocumentStore(s => s.setDocument)
  const docId = useSessionStore(s => s.currentDocId) || ''

  const updateList = useCallback((listKey: ListKey) => (contacts: ContactEntry[]) => {
    const sections = useDocumentStore.getState().sections || {}
    const current = (sections.stakeholders || {}) as StakeholdersModel
    const updated = { ...current, [listKey]: contacts }
    setDocument({ sections: { ...sections, stakeholders: updated } } as any)
  }, [setDocument])

  const hasContent = Boolean(sectionData && (
    (sectionData.executive_sponsors?.length ?? 0) > 0 ||
    (sectionData.stakeholders?.length ?? 0) > 0 ||
    (sectionData.project_team?.length ?? 0) > 0 ||
    (sectionData.escalation_contacts?.length ?? 0) > 0
  ))

  if (!hasContent) {
    return (
      <div>
        <h2 style={headingStyle}>
          2.2 Stakeholders
          <SectionGuideButton sectionKey="stakeholders" />
        </h2>
        <div style={emptyContainer}>
          <p style={emptyMainText}>
            이해관계자 정보가 아직 입력되지 않았습니다.
            자주 사용하는 형식을 선택하여 시작하거나, 직접 입력할 수 있습니다.
          </p>
          <div style={actionRow}>
            <span style={actionHint}>📋 프리셋 행 추가 — 각 테이블의 + 추가 버튼과 드롭다운을 사용하세요</span>
            <span style={actionHint}>✏️ 직접 행 추가 — 아래 테이블에서 + 추가를 클릭하세요</span>
            <span style={actionHintMuted}>🤖 AI에게 초안 요청 — 채팅에서 "Stakeholders 작성해줘"</span>
          </div>
        </div>
        {LIST_CONFIG.map(({ key, label, columns, columnPresets }) => (
          <div key={key} style={sectionCard}>
            <h3 style={sectionTitle}>{label}</h3>
            <ContactTableEditor
              contacts={[]}
              listDotPath={`sections.stakeholders.${key}`}
              docId={docId}
              onContactsChange={updateList(key)}
              columns={columns}
              columnPresets={columnPresets}
            />
          </div>
        ))}
      </div>
    )
  }

  const sk = sectionData || ({} as StakeholdersModel)

  return (
    <div>
      <h2 style={headingStyle}>
        2.2 Stakeholders
        <SectionGuideButton sectionKey="stakeholders" />
      </h2>
      {LIST_CONFIG.map(({ key, label, columns, columnPresets }) => (
        <div key={key} style={sectionCard}>
          <h3 style={sectionTitle}>{label}</h3>
          <ContactTableEditor
            contacts={sk[key] ?? []}
            listDotPath={`sections.stakeholders.${key}`}
            docId={docId}
            onContactsChange={updateList(key)}
            columns={columns}
            columnPresets={columnPresets}
          />
        </div>
      ))}
    </div>
  )
}

const headingStyle: React.CSSProperties = {
  marginBottom: 16,
  fontSize: size.lg,
  fontWeight: 600,
  fontFamily: font.heading,
  display: 'flex',
  alignItems: 'center',
  gap: space.xs,
}

const sectionCard: React.CSSProperties = {
  marginBottom: 20,
  padding: 16,
  border: `1px solid ${color.border}`,
  borderRadius: 8,
  background: color.bgSurface,
}

const sectionTitle: React.CSSProperties = {
  marginTop: 0,
  marginBottom: 12,
  fontSize: 14,
  fontWeight: 700,
  color: color.textPrimary,
}

const emptyContainer: React.CSSProperties = {
  padding: space.xl,
  border: `1px dashed ${color.border}`,
  borderRadius: 8,
  background: color.bgPrimary,
  marginBottom: space.lg,
}

const emptyMainText: React.CSSProperties = {
  color: color.textSecondary,
  fontSize: size.base,
  lineHeight: 1.6,
  marginBottom: space.md,
}

const actionRow: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: space.xs,
}

const actionHint: React.CSSProperties = {
  fontSize: size.sm,
  color: color.textSecondary,
}

const actionHintMuted: React.CSSProperties = {
  fontSize: size.sm,
  color: color.textMuted,
  fontStyle: 'italic',
}
