import { useCallback } from 'react'
import { useDocumentStore, type StakeholdersSection as StakeholdersModel, type ContactEntry } from '../../store/documentStore'
import { useSessionStore } from '../../store/sessionStore'
import { ContactTableEditor } from '../editors/ContactTableEditor'
import { useDocLang } from '../LangContext'
import { color } from '../../styles/tokens'

/** Column configuration per contact list (from design.md) */
const EXECUTIVE_SPONSORS_COLUMNS: (keyof ContactEntry)[] = ['name', 'title', 'description']
const STAKEHOLDERS_COLUMNS: (keyof ContactEntry)[] = ['name', 'title', 'stakeholder_for']
const PROJECT_TEAM_COLUMNS: (keyof ContactEntry)[] = ['name', 'title', 'role', 'contact']
const ESCALATION_CONTACTS_COLUMNS: (keyof ContactEntry)[] = ['name', 'title', 'role', 'contact']

type ListKey = 'executive_sponsors' | 'stakeholders' | 'project_team' | 'escalation_contacts'

const LIST_CONFIG: { key: ListKey; label: string; columns: (keyof ContactEntry)[] }[] = [
  { key: 'executive_sponsors', label: 'Executive Sponsors', columns: EXECUTIVE_SPONSORS_COLUMNS },
  { key: 'stakeholders', label: 'Stakeholders', columns: STAKEHOLDERS_COLUMNS },
  { key: 'project_team', label: 'Project Team', columns: PROJECT_TEAM_COLUMNS },
  { key: 'escalation_contacts', label: 'Escalation Contacts', columns: ESCALATION_CONTACTS_COLUMNS },
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
        <h2 style={{ marginBottom: 16 }}>Stakeholders</h2>
        <p style={{ color: color.textMuted }}>
          이해관계자 정보가 아직 입력되지 않았습니다. 채팅에서 "Stakeholders 작성해줘"라고 요청하거나 아래에서 직접 추가하세요.
        </p>
        {LIST_CONFIG.map(({ key, label, columns }) => (
          <div key={key} style={sectionCard}>
            <h3 style={sectionTitle}>{label}</h3>
            <ContactTableEditor
              contacts={[]}
              listDotPath={`sections.stakeholders.${key}`}
              docId={docId}
              onContactsChange={updateList(key)}
              columns={columns}
            />
          </div>
        ))}
      </div>
    )
  }

  const sk = sectionData || ({} as StakeholdersModel)

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>Stakeholders</h2>
      {LIST_CONFIG.map(({ key, label, columns }) => (
        <div key={key} style={sectionCard}>
          <h3 style={sectionTitle}>{label}</h3>
          <ContactTableEditor
            contacts={sk[key] ?? []}
            listDotPath={`sections.stakeholders.${key}`}
            docId={docId}
            onContactsChange={updateList(key)}
            columns={columns}
          />
        </div>
      ))}
    </div>
  )
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
