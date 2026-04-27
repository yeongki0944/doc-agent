import { useMemo, useState } from 'react'
import { useDocumentStore, createFieldValue, type ScopeTask } from '../../store/documentStore'
import { useSessionStore } from '../../store/sessionStore'
import { saveUserInput } from '../../utils/api'
import { emitUserEdit } from '../../utils/userEditEvent'
import { EditableField } from '../EditableField'
import { color } from '../../styles/tokens'
import { resolveFieldValue, isAiRecommended } from '../AiBadge'

function toText(value: any): string {
  if (Array.isArray(value)) {
    return value.map(v => String(resolveFieldValue(v) ?? '')).filter(Boolean).join('\n')
  }
  return String(resolveFieldValue(value) ?? '')
}

function createTask(): ScopeTask {
  return {
    task_category: createFieldValue('', null, null, 'empty'),
    schedule: createFieldValue('', null, null, 'empty'),
    details: [createFieldValue('', null, null, 'empty')],
    personnel: createFieldValue('', null, null, 'empty'),
  }
}

export function ScopeOfWorkSection() {
  const sectionData = useDocumentStore(s => s.sections?.scope_of_work) as Record<string, any> | undefined
  const setDocument = useDocumentStore(s => s.setDocument)
  const docId = useSessionStore(s => s.currentDocId) || ''
  const tasks: ScopeTask[] = useMemo(() => (sectionData?.tasks as ScopeTask[]) || [], [sectionData?.tasks])
  const [draftTask, setDraftTask] = useState<ScopeTask | null>(null)

  const hasContent = Boolean(tasks.length || (sectionData && Object.keys(sectionData).some(k => sectionData[k])))

  const updateTaskField = (index: number, field: keyof ScopeTask, newValue: string) => {
    const sections = useDocumentStore.getState().sections || {}
    const current = ((sections.scope_of_work || {}) as any)
    const currentTasks: ScopeTask[] = Array.isArray(current.tasks) ? [...current.tasks] : []
    const oldTask = currentTasks[index] || createTask()

    const nextTask = { ...oldTask }
    if (field === 'details') {
      nextTask.details = newValue.split('\n').map(line => createFieldValue(line, null, null, 'user_modified')).filter(item => String(resolveFieldValue(item) ?? '').trim())
    } else {
      ;(nextTask as any)[field] = createFieldValue(newValue, null, null, 'user_modified')
    }
    currentTasks[index] = nextTask
    setDocument({ sections: { ...sections, scope_of_work: { ...current, tasks: currentTasks } } } as any)
    saveUserInput(docId, `sections.scope_of_work.tasks.${index}.${field}.user_input`, newValue).catch(() => {})
    emitUserEdit('Scope of Work', String(field), toText((oldTask as any)[field]), newValue)
  }

  const addTask = () => {
    const sections = useDocumentStore.getState().sections || {}
    const current = ((sections.scope_of_work || {}) as any)
    const currentTasks: ScopeTask[] = Array.isArray(current.tasks) ? [...current.tasks] : []
    const nextDraft = draftTask || createTask()
    currentTasks.push(nextDraft)
    setDocument({ sections: { ...sections, scope_of_work: { ...current, tasks: currentTasks } } } as any)
    saveUserInput(docId, `sections.scope_of_work.tasks`, currentTasks.map(task => ({
      task_category: toText(task.task_category),
      schedule: toText(task.schedule),
      details: toText(task.details).split('\n').filter(Boolean),
      personnel: toText(task.personnel),
    }))).catch(() => {})
    setDraftTask(null)
  }

  const removeTask = (index: number) => {
    const sections = useDocumentStore.getState().sections || {}
    const current = ((sections.scope_of_work || {}) as any)
    const currentTasks: ScopeTask[] = Array.isArray(current.tasks) ? [...current.tasks] : []
    currentTasks.splice(index, 1)
    setDocument({ sections: { ...sections, scope_of_work: { ...current, tasks: currentTasks } } } as any)
    saveUserInput(docId, `sections.scope_of_work.tasks`, currentTasks.map(task => ({
      task_category: toText(task.task_category),
      schedule: toText(task.schedule),
      details: toText(task.details).split('\n').filter(Boolean),
      personnel: toText(task.personnel),
    }))).catch(() => {})
  }

  if (!hasContent) {
    return (
      <div>
        <h2 style={{ marginBottom: 16 }}>Scope of Work</h2>
        <p style={{ color: color.textMuted }}>프로젝트 범위가 아직 정의되지 않았습니다. 채팅에서 "Scope 작성해줘"라고 요청하세요.</p>
      </div>
    )
  }

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>Scope of Work</h2>
      <div style={toolbar}>
        <button type="button" onClick={() => setDraftTask(createTask())} style={secondaryButton}>Add Task</button>
        {draftTask && <button type="button" onClick={addTask} style={primaryButton}>Save Task</button>}
      </div>
      {draftTask && <TaskEditor task={draftTask} onChange={setDraftTask} onSave={addTask} onCancel={() => setDraftTask(null)} />}
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
        <thead>
          <tr style={{ background: color.bgPrimary }}>
            {['Task Category', 'Schedule', 'Details', 'Personnel', ''].map(h => (
              <th key={h} style={{ padding: '8px 6px', borderBottom: `2px solid ${color.border}`, textAlign: 'left' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {tasks.map((task, index) => (
            <tr key={index}>
              <td style={td}>
                <EditableField
                  value={toText(task.task_category)}
                  isAi={isAiRecommended(task.task_category)}
                  onSave={v => updateTaskField(index, 'task_category', v)}
                />
              </td>
              <td style={td}>
                <EditableField
                  value={toText(task.schedule)}
                  isAi={isAiRecommended(task.schedule)}
                  onSave={v => updateTaskField(index, 'schedule', v)}
                />
              </td>
              <td style={td}>
                <EditableField
                  value={toText(task.details)}
                  isAi={task.details.some(isAiRecommended)}
                  onSave={v => updateTaskField(index, 'details', v)}
                  multiline
                />
              </td>
              <td style={td}>
                <EditableField
                  value={toText(task.personnel)}
                  isAi={isAiRecommended(task.personnel)}
                  onSave={v => updateTaskField(index, 'personnel', v)}
                />
              </td>
              <td style={td}>
                <button type="button" onClick={() => removeTask(index)} style={deleteButton}>Delete</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function TaskEditor({
  task,
  onChange,
  onSave,
  onCancel,
}: {
  task: ScopeTask
  onChange: (task: ScopeTask) => void
  onSave: () => void
  onCancel: () => void
}) {
  return (
    <div style={{ marginBottom: 16, padding: 12, borderRadius: 8, border: `1px solid ${color.border}`, background: color.bgPrimary }}>
      <div style={editorGrid}>
        <label style={fieldLabel}>
          <span style={labelText}>Task Category</span>
          <input value={toText(task.task_category)} onChange={e => onChange({ ...task, task_category: createFieldValue(e.target.value, null, null, 'user_modified') })} style={inputStyle} />
        </label>
        <label style={fieldLabel}>
          <span style={labelText}>Schedule</span>
          <input value={toText(task.schedule)} onChange={e => onChange({ ...task, schedule: createFieldValue(e.target.value, null, null, 'user_modified') })} style={inputStyle} />
        </label>
        <label style={fieldLabel}>
          <span style={labelText}>Personnel</span>
          <input value={toText(task.personnel)} onChange={e => onChange({ ...task, personnel: createFieldValue(e.target.value, null, null, 'user_modified') })} style={inputStyle} />
        </label>
      </div>
      <label style={{ ...fieldLabel, marginTop: 8 }}>
        <span style={labelText}>Details</span>
        <textarea
          value={toText(task.details)}
          onChange={e => onChange({ ...task, details: e.target.value.split('\n').map(line => createFieldValue(line, null, null, 'user_modified')) })}
          rows={3}
          style={{ ...inputStyle, resize: 'vertical' }}
        />
      </label>
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 8 }}>
        <button type="button" onClick={onCancel} style={secondaryButton}>Cancel</button>
        <button type="button" onClick={onSave} style={primaryButton}>Add</button>
      </div>
    </div>
  )
}

const td: React.CSSProperties = { padding: '6px', borderBottom: `1px solid ${color.border}` }
const toolbar: React.CSSProperties = { display: 'flex', gap: 8, marginBottom: 12 }
const fieldLabel: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: 4 }
const labelText: React.CSSProperties = { fontSize: 11, color: color.textMuted, fontWeight: 600 }
const editorGrid: React.CSSProperties = { display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 8 }
const inputStyle: React.CSSProperties = { border: `1px solid ${color.border}`, borderRadius: 6, padding: '7px 8px', fontSize: 13, background: color.bgSurface }
const primaryButton: React.CSSProperties = { border: 'none', borderRadius: 6, padding: '8px 12px', background: color.mzRed, color: color.bgSurface, cursor: 'pointer', fontWeight: 600 }
const secondaryButton: React.CSSProperties = { border: `1px solid ${color.border}`, borderRadius: 6, padding: '8px 12px', background: color.bgSurface, color: color.textPrimary, cursor: 'pointer', fontWeight: 600 }
const deleteButton: React.CSSProperties = { border: 'none', borderRadius: 6, padding: '6px 10px', background: '#fee2e2', color: '#b91c1c', cursor: 'pointer', fontWeight: 600 }
