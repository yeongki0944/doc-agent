import { useCallback, useMemo } from 'react'
import { useDocumentStore, type ScopeOfWorkSection as ScopeOfWorkModel, type ScopeTask, type FieldValue } from '../../store/documentStore'
import { useSessionStore } from '../../store/sessionStore'
import { EditableComboField } from '../editors/EditableComboField'
import { ListEditor } from '../editors/ListEditor'
import { SaveStatusIndicator } from '../SaveStatusIndicator'
import { SectionGuideButton } from '../SectionGuideButton'
import { useSaveStatus } from '../../hooks/useSaveStatus'
import { saveUserInput } from '../../utils/api'
import { useDocLang } from '../LangContext'
import { color, font, size, space } from '../../styles/tokens'
import {
  TASK_CATEGORY_PRESETS,
  PERSONNEL_PRESETS,
  DELIVERABLE_PHRASE_PRESETS,
  SCHEDULE_PATTERN_PRESETS,
} from '../../constants/documentPresets'

const emptyField = (): FieldValue => ({
  user_input: null,
  ai_recommended: null,
  calculated: null,
  status: 'empty',
  user_edited: false,
})

function createEmptyScopeTask(): ScopeTask {
  return {
    task_category: emptyField(),
    schedule: emptyField(),
    details: emptyField(),
    personnel: emptyField(),
  }
}

export function ScopeOfWorkSection() {
  const lang = useDocLang()
  const koData = useDocumentStore(s => s.sections?.scope_of_work) as ScopeOfWorkModel | undefined
  const enData = useDocumentStore(s => s.sections_en?.scope_of_work) as ScopeOfWorkModel | undefined
  const sectionData = lang === 'en' ? enData : koData
  const setDocument = useDocumentStore(s => s.setDocument)
  const docId = useSessionStore(s => s.currentDocId) || ''
  const { saveStatus: arraySaveStatus, doSave: doArraySave } = useSaveStatus()

  const tasks: ScopeTask[] = useMemo(() => sectionData?.tasks ?? [], [sectionData?.tasks])
  const outOfScope: FieldValue[] = useMemo(() => sectionData?.out_of_scope ?? [], [sectionData?.out_of_scope])
  const items: FieldValue[] = useMemo(() => sectionData?.items ?? [], [sectionData?.items])

  const hasContent = Boolean(
    tasks.length > 0 ||
    outOfScope.length > 0 ||
    items.length > 0
  )

  // --- Task field updates (via EditableComboField) ---
  const updateTaskField = useCallback((index: number, field: keyof ScopeTask) => (newField: FieldValue) => {
    const sections = useDocumentStore.getState().sections || {}
    const current = (sections.scope_of_work || {}) as ScopeOfWorkModel
    const currentTasks = [...(current.tasks ?? [])]
    const oldTask = currentTasks[index] || createEmptyScopeTask()
    currentTasks[index] = { ...oldTask, [field]: newField }
    setDocument({ sections: { ...sections, scope_of_work: { ...current, tasks: currentTasks } } } as any)
  }, [setDocument])

  // --- Add/remove tasks (persist full array) ---
  const addTask = useCallback(() => {
    const sections = useDocumentStore.getState().sections || {}
    const current = (sections.scope_of_work || {}) as ScopeOfWorkModel
    const updated = [...(current.tasks ?? []), createEmptyScopeTask()]
    setDocument({ sections: { ...sections, scope_of_work: { ...current, tasks: updated } } } as any)
    doArraySave(() => saveUserInput(docId, 'sections.scope_of_work.tasks', updated))
  }, [setDocument, docId, doArraySave])

  const removeTask = useCallback((index: number) => {
    const sections = useDocumentStore.getState().sections || {}
    const current = (sections.scope_of_work || {}) as ScopeOfWorkModel
    const updated = (current.tasks ?? []).filter((_, i) => i !== index)
    setDocument({ sections: { ...sections, scope_of_work: { ...current, tasks: updated } } } as any)
    doArraySave(() => saveUserInput(docId, 'sections.scope_of_work.tasks', updated))
  }, [setDocument, docId, doArraySave])

  // --- out_of_scope list update ---
  const handleOutOfScopeChange = useCallback((newItems: FieldValue[]) => {
    const sections = useDocumentStore.getState().sections || {}
    const current = (sections.scope_of_work || {}) as ScopeOfWorkModel
    setDocument({ sections: { ...sections, scope_of_work: { ...current, out_of_scope: newItems } } } as any)
  }, [setDocument])

  // --- items list update ---
  const handleItemsChange = useCallback((newItems: FieldValue[]) => {
    const sections = useDocumentStore.getState().sections || {}
    const current = (sections.scope_of_work || {}) as ScopeOfWorkModel
    setDocument({ sections: { ...sections, scope_of_work: { ...current, items: newItems } } } as any)
  }, [setDocument])

  if (!hasContent) {
    return (
      <div>
        <h2 style={headingStyle}>
          2.5 Scope of Work
          <SectionGuideButton sectionKey="scope_of_work" />
        </h2>
        <div style={emptyContainer}>
          <p style={emptyMainText}>
            프로젝트 범위가 아직 정의되지 않았습니다.
            자주 사용하는 형식을 선택하여 시작하거나, 직접 입력할 수 있습니다.
          </p>
          <div style={actionRow}>
            <button style={actionBtn} onClick={addTask}>
              ✏️ 직접 행 추가
            </button>
            <button style={{ ...actionBtn, ...actionBtnMuted }}>
              🤖 AI에게 초안 요청
            </button>
          </div>
          <p style={emptyAiHint}>
            AI 요청 예시: Scope of Work 초안 작성해줘
          </p>
        </div>

        <div style={{ marginTop: 16 }}>
          <h3 style={subHeading}>Items</h3>
          <ListEditor
            items={[]}
            listDotPath="sections.scope_of_work.items"
            docId={docId}
            onItemsChange={handleItemsChange}
            placeholder="항목 입력"
          />
        </div>

        <div style={{ marginTop: 16 }}>
          <h3 style={subHeading}>Tasks</h3>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
            <button type="button" onClick={addTask} style={addButton}>+ Add Task</button>
            <SaveStatusIndicator status={arraySaveStatus} />
          </div>
        </div>

        <div style={{ marginTop: 16 }}>
          <h3 style={subHeading}>Out of Scope</h3>
          <ListEditor
            items={[]}
            listDotPath="sections.scope_of_work.out_of_scope"
            docId={docId}
            onItemsChange={handleOutOfScopeChange}
            placeholder="범위 외 항목 입력"
          />
        </div>
      </div>
    )
  }

  return (
    <div>
      <h2 style={headingStyle}>
        2.5 Scope of Work
        <SectionGuideButton sectionKey="scope_of_work" />
      </h2>

      {/* Items list */}
      {(items.length > 0 || hasContent) && (
        <div style={{ marginBottom: 20 }}>
          <h3 style={subHeading}>Items</h3>
          <ListEditor
            items={items}
            listDotPath="sections.scope_of_work.items"
            docId={docId}
            onItemsChange={handleItemsChange}
            placeholder="항목 입력"
          />
        </div>
      )}

      {/* Tasks table */}
      <div style={{ marginBottom: 20 }}>
        <h3 style={subHeading}>Tasks</h3>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
          <button type="button" onClick={addTask} style={addButton}>+ Add Task</button>
          <SaveStatusIndicator status={arraySaveStatus} />
        </div>
        {tasks.length > 0 && (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
            <thead>
              <tr style={{ background: color.bgPrimary }}>
                {['Task Category', 'Schedule', 'Details', 'Personnel', ''].map(h => (
                  <th key={h} style={th}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tasks.map((task, index) => (
                <tr key={index}>
                  <td style={td}>
                    <EditableComboField
                      field={task.task_category}
                      dotPath={`sections.scope_of_work.tasks.${index}.task_category.user_input`}
                      docId={docId}
                      placeholder="Task Category"
                      presets={TASK_CATEGORY_PRESETS}
                      onLocalUpdate={updateTaskField(index, 'task_category')}
                    />
                  </td>
                  <td style={td}>
                    <EditableComboField
                      field={task.schedule}
                      dotPath={`sections.scope_of_work.tasks.${index}.schedule.user_input`}
                      docId={docId}
                      placeholder="Schedule"
                      presets={SCHEDULE_PATTERN_PRESETS}
                      onLocalUpdate={updateTaskField(index, 'schedule')}
                    />
                  </td>
                  <td style={td}>
                    <EditableComboField
                      field={task.details}
                      dotPath={`sections.scope_of_work.tasks.${index}.details.user_input`}
                      docId={docId}
                      placeholder="Details"
                      multiline
                      presets={DELIVERABLE_PHRASE_PRESETS}
                      onLocalUpdate={updateTaskField(index, 'details')}
                    />
                  </td>
                  <td style={td}>
                    <EditableComboField
                      field={task.personnel}
                      dotPath={`sections.scope_of_work.tasks.${index}.personnel.user_input`}
                      docId={docId}
                      placeholder="Personnel"
                      presets={PERSONNEL_PRESETS}
                      onLocalUpdate={updateTaskField(index, 'personnel')}
                    />
                  </td>
                  <td style={td}>
                    <button type="button" onClick={() => removeTask(index)} style={deleteButton}>Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Out of Scope list */}
      <div style={{ marginBottom: 20 }}>
        <h3 style={subHeading}>Out of Scope</h3>
        <ListEditor
          items={outOfScope}
          listDotPath="sections.scope_of_work.out_of_scope"
          docId={docId}
          onItemsChange={handleOutOfScopeChange}
          placeholder="범위 외 항목 입력"
        />
      </div>
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

const emptyContainer: React.CSSProperties = {
  padding: space.xl,
  border: `1px dashed ${color.border}`,
  borderRadius: 8,
  background: color.bgPrimary,
  textAlign: 'center',
}

const emptyMainText: React.CSSProperties = {
  color: color.textSecondary,
  fontSize: size.base,
  lineHeight: 1.6,
  marginBottom: space.md,
}

const emptyAiHint: React.CSSProperties = {
  color: color.info,
  fontSize: size.sm,
  fontStyle: 'italic',
  marginTop: space.md,
}

const actionRow: React.CSSProperties = {
  display: 'flex',
  gap: space.sm,
  justifyContent: 'center',
  flexWrap: 'wrap',
}

const actionBtn: React.CSSProperties = {
  padding: `${space.sm}px ${space.md}px`,
  border: `1px solid ${color.border}`,
  borderRadius: 6,
  background: color.bgSurface,
  cursor: 'pointer',
  fontSize: size.sm,
  color: color.textPrimary,
}

const actionBtnMuted: React.CSSProperties = {
  color: color.textMuted,
  borderStyle: 'dashed',
}

const subHeading: React.CSSProperties = { fontSize: 14, fontWeight: 700, color: color.textSecondary, marginBottom: 8, marginTop: 0 }
const th: React.CSSProperties = { padding: '8px 6px', borderBottom: `2px solid ${color.border}`, textAlign: 'left' }
const td: React.CSSProperties = { padding: '6px', borderBottom: `1px solid ${color.border}`, verticalAlign: 'top' }
const addButton: React.CSSProperties = {
  background: 'none', border: `1px dashed ${color.border}`,
  borderRadius: 4, padding: '4px 10px', cursor: 'pointer',
  color: color.textSecondary, fontSize: 12,
}
const deleteButton: React.CSSProperties = {
  border: 'none', borderRadius: 6, padding: '6px 10px',
  background: '#fee2e2', color: '#b91c1c', cursor: 'pointer', fontWeight: 600,
}
