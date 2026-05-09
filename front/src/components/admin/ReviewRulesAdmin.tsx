import { useEffect, useMemo, useState } from 'react'
import { color, radius, space } from '../../styles/tokens'
import {
  collectCategories,
  type EvaluationType,
  type RuleDefinition,
  type RuleSeverity,
} from '../../constants/reviewRulesSeed'
import {
  createCustomRule,
  deleteCustomRule,
  listReviewRules,
  setRuleEnabled,
  updateCustomRule,
} from '../../utils/reviewRulesApi'
import { useDocLang } from '../LangContext'

type EnabledFilter = 'ALL' | 'ENABLED' | 'DISABLED'
type CustomFilter = 'ALL' | 'CUSTOM' | 'BUILTIN'

const SEVERITIES: RuleSeverity[] = ['Critical', 'High', 'Medium', 'Low', 'Info']
const EVAL_TYPES: EvaluationType[] = ['static', 'llm', 'hybrid']

/**
 * Review Rules Admin — "리뷰 규칙 관리" page. Lists built-in and custom
 * rules, lets operators enable/disable rules, edit custom rules, and add
 * new custom rules. Falls back to a read-only seeded catalog when the
 * backend `/review_rules` endpoint is not deployed.
 */
export function ReviewRulesAdmin({ onClose }: { onClose?: () => void }) {
  const lang = useDocLang()
  const [rules, setRules] = useState<RuleDefinition[]>([])
  const [version, setVersion] = useState<string>('')
  const [sourceDocs, setSourceDocs] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [fromFallback, setFromFallback] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [enabledFilter, setEnabledFilter] = useState<EnabledFilter>('ALL')
  const [severityFilter, setSeverityFilter] = useState<RuleSeverity | 'ALL'>('ALL')
  const [categoryFilter, setCategoryFilter] = useState<string>('ALL')
  const [customFilter, setCustomFilter] = useState<CustomFilter>('ALL')
  const [search, setSearch] = useState('')

  const [selectedRuleId, setSelectedRuleId] = useState<string | null>(null)
  const [addOpen, setAddOpen] = useState(false)
  const [editOpen, setEditOpen] = useState<RuleDefinition | null>(null)

  const reload = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await listReviewRules()
      setRules(data.rules)
      setVersion(data.version || '')
      setSourceDocs(data.source_documents || [])
      setFromFallback(!!data.fromFallback)
    } catch (e: any) {
      setError(e?.message || 'Failed to load rules')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    reload()
  }, [])

  const categories = useMemo(() => collectCategories(rules), [rules])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return rules.filter(r => {
      if (enabledFilter === 'ENABLED' && !r.enabled) return false
      if (enabledFilter === 'DISABLED' && r.enabled) return false
      if (severityFilter !== 'ALL' && r.severity !== severityFilter) return false
      if (categoryFilter !== 'ALL' && r.category_en !== categoryFilter) return false
      if (customFilter === 'CUSTOM' && !r.custom) return false
      if (customFilter === 'BUILTIN' && r.custom) return false
      if (q) {
        const hay = [
          r.rule_id, r.title_kr, r.title_en, r.description_kr, r.description_en,
          r.category_kr, r.category_en, r.source,
        ].join(' ').toLowerCase()
        if (!hay.includes(q)) return false
      }
      return true
    })
  }, [rules, enabledFilter, severityFilter, categoryFilter, customFilter, search])

  const handleToggleEnabled = async (rule: RuleDefinition) => {
    const next = !rule.enabled
    setRules(prev => prev.map(r => r.rule_id === rule.rule_id ? { ...r, enabled: next } : r))
    try {
      await setRuleEnabled(rule.rule_id, next)
    } catch (e: any) {
      setError(e?.message || 'Failed to toggle rule')
      setRules(prev => prev.map(r => r.rule_id === rule.rule_id ? { ...r, enabled: !next } : r))
    }
  }

  const handleDelete = async (rule: RuleDefinition) => {
    if (!rule.custom) return
    if (!confirm(lang === 'ko' ? `커스텀 규칙 "${rule.title_kr}"을(를) 삭제하시겠습니까?` : `Delete custom rule "${rule.title_en}"?`)) return
    try {
      await deleteCustomRule(rule.rule_id)
      await reload()
      if (selectedRuleId === rule.rule_id) setSelectedRuleId(null)
    } catch (e: any) {
      setError(e?.message || 'Failed to delete rule')
    }
  }

  const handleSaveCustom = async (rule: RuleDefinition, isEdit: boolean) => {
    if (isEdit) await updateCustomRule(rule.rule_id, rule)
    else await createCustomRule(rule)
    setAddOpen(false)
    setEditOpen(null)
    await reload()
  }

  const selected = rules.find(r => r.rule_id === selectedRuleId) || null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: color.bgPrimary, overflow: 'hidden' }}>
      {/* Header */}
      <div style={{
        padding: '14px 20px', borderBottom: `1px solid ${color.border}`, background: color.bgSurface,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16,
      }}>
        <div>
          <div style={{ fontSize: 16, fontWeight: 700, color: color.textPrimary, letterSpacing: '-0.01em' }}>
            Review Rules Admin · 리뷰 규칙 관리
          </div>
          <div style={{ fontSize: 12, color: color.textMuted, marginTop: 2 }}>
            {rules.length} rules · {version ? `v${version}` : 'unversioned'}
            {sourceDocs.length > 0 && (
              <span style={{ marginLeft: 8, color: color.textMuted }}>
                · sources: {sourceDocs.join(', ')}
              </span>
            )}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={() => setAddOpen(true)}
            className="mzc-btn mzc-btn-primary"
            style={{ fontSize: 13 }}
          >
            + Add Custom Rule
          </button>
          {onClose && (
            <button
              onClick={onClose}
              className="mzc-btn mzc-btn-secondary"
              style={{ fontSize: 13 }}
            >
              ← Documents
            </button>
          )}
        </div>
      </div>

      {/* Fallback notice */}
      {fromFallback && (
        <div style={{
          padding: '8px 20px', background: '#eff6ff', color: '#1e3a8a',
          borderBottom: `1px solid #bfdbfe`, fontSize: 12,
        }}>
          Rule Admin API is not available yet. Showing local fallback rule catalog. 변경사항은 로컬(브라우저)에만 저장됩니다.
        </div>
      )}
      {error && (
        <div style={{
          padding: '8px 20px', background: '#fef2f2', color: '#991b1b',
          borderBottom: `1px solid #fecaca`, fontSize: 12,
        }}>
          ⚠ {error}
        </div>
      )}

      {/* Filters */}
      <div style={{
        padding: '10px 20px', borderBottom: `1px solid ${color.border}`, background: color.bgSurface,
        display: 'flex', flexWrap: 'wrap', gap: 8,
      }}>
        <select className="mzc-select" value={enabledFilter} onChange={e => setEnabledFilter(e.target.value as EnabledFilter)} style={{ flex: '0 0 auto', width: 140, fontSize: 12 }}>
          <option value="ALL">Enabled: All</option>
          <option value="ENABLED">Enabled only</option>
          <option value="DISABLED">Disabled only</option>
        </select>
        <select className="mzc-select" value={severityFilter} onChange={e => setSeverityFilter(e.target.value as any)} style={{ flex: '0 0 auto', width: 140, fontSize: 12 }}>
          <option value="ALL">Severity: All</option>
          {SEVERITIES.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <select className="mzc-select" value={categoryFilter} onChange={e => setCategoryFilter(e.target.value)} style={{ flex: '0 0 auto', width: 200, fontSize: 12 }}>
          <option value="ALL">Category: All</option>
          {categories.map(c => (
            <option key={c.key} value={c.key}>{lang === 'ko' ? c.kr : c.en}</option>
          ))}
        </select>
        <select className="mzc-select" value={customFilter} onChange={e => setCustomFilter(e.target.value as CustomFilter)} style={{ flex: '0 0 auto', width: 140, fontSize: 12 }}>
          <option value="ALL">Source: All</option>
          <option value="BUILTIN">Built-in</option>
          <option value="CUSTOM">Custom</option>
        </select>
        <input
          className="mzc-input"
          placeholder="Search rules / 규칙 검색..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          style={{ flex: 1, minWidth: 180, fontSize: 12 }}
        />
      </div>

      {/* Body — table + detail */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        <div style={{ flex: 1, overflow: 'auto' }}>
          {loading && rules.length === 0 ? (
            <div style={{ padding: space.xl, color: color.textMuted, fontSize: 13, textAlign: 'center' }}>
              Loading rules...
            </div>
          ) : (
            <table className="mzc-table review-admin-table">
              <thead>
                <tr>
                  <th style={{ width: 70 }}>Enabled</th>
                  <th style={{ width: 80 }}>Severity</th>
                  <th style={{ width: 170 }}>Category</th>
                  <th>Rule</th>
                  <th style={{ width: 90 }}>Type</th>
                  <th style={{ width: 180 }}>Source</th>
                  <th style={{ width: 80 }}>Custom</th>
                  <th style={{ width: 130 }}>Updated</th>
                  <th style={{ width: 120 }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map(r => (
                  <tr
                    key={r.rule_id}
                    className={selectedRuleId === r.rule_id ? 'is-selected' : ''}
                    onClick={() => setSelectedRuleId(r.rule_id)}
                    style={{ cursor: 'pointer', opacity: r.enabled ? 1 : 0.6 }}
                  >
                    <td onClick={e => e.stopPropagation()}>
                      <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                        <input
                          type="checkbox"
                          checked={!!r.enabled}
                          onChange={() => handleToggleEnabled(r)}
                        />
                      </label>
                    </td>
                    <td><span className={`severity-badge ${r.severity.toLowerCase()}`}>{r.severity}</span></td>
                    <td>
                      <div style={{ fontSize: 12, color: color.textPrimary }}>{r.category_kr}</div>
                      <div style={{ fontSize: 10, color: color.textMuted }}>{r.category_en}</div>
                    </td>
                    <td>
                      <div style={{ fontSize: 13, fontWeight: 600 }}>{r.title_kr}</div>
                      <div style={{ fontSize: 11, color: color.textMuted }}>{r.title_en}</div>
                      <code style={{ fontSize: 10, color: color.textMuted }}>{r.rule_id}</code>
                    </td>
                    <td><span className="mzc-badge">{r.evaluation_type}</span></td>
                    <td style={{ fontSize: 11, color: color.textSecondary }}>{r.source}</td>
                    <td>
                      {r.custom
                        ? <span className="mzc-badge mzc-badge-ai">custom</span>
                        : <span className="mzc-badge">built-in</span>}
                    </td>
                    <td style={{ fontSize: 11, color: color.textMuted }}>
                      {r.updated_at ? new Date(r.updated_at).toLocaleString() : '—'}
                    </td>
                    <td onClick={e => e.stopPropagation()}>
                      {r.custom ? (
                        <div style={{ display: 'flex', gap: 4 }}>
                          <button className="mzc-btn mzc-btn-secondary" style={{ fontSize: 11, padding: '3px 8px' }} onClick={() => setEditOpen(r)}>Edit</button>
                          <button className="mzc-btn mzc-btn-danger" style={{ fontSize: 11, padding: '3px 8px' }} onClick={() => handleDelete(r)}>Delete</button>
                        </div>
                      ) : (
                        <span style={{ fontSize: 11, color: color.textMuted }}>read-only</span>
                      )}
                    </td>
                  </tr>
                ))}
                {filtered.length === 0 && !loading && (
                  <tr><td colSpan={9} style={{ padding: space.lg, textAlign: 'center', color: color.textMuted, fontSize: 12 }}>
                    필터에 맞는 규칙이 없습니다.
                  </td></tr>
                )}
              </tbody>
            </table>
          )}
        </div>

        {selected && (
          <RuleDetailDrawer
            rule={selected}
            lang={lang}
            onClose={() => setSelectedRuleId(null)}
            onEdit={selected.custom ? () => setEditOpen(selected) : undefined}
          />
        )}
      </div>

      {/* Add / edit form */}
      {(addOpen || editOpen) && (
        <RuleFormModal
          initial={editOpen || undefined}
          isEdit={!!editOpen}
          onCancel={() => { setAddOpen(false); setEditOpen(null) }}
          onSave={rule => handleSaveCustom(rule, !!editOpen)}
        />
      )}
    </div>
  )
}

/* ---------- Detail drawer ---------- */

function RuleDetailDrawer({
  rule, lang, onClose, onEdit,
}: {
  rule: RuleDefinition
  lang: 'ko' | 'en'
  onClose: () => void
  onEdit?: () => void
}) {
  return (
    <div style={{
      width: 420, minWidth: 420, borderLeft: `1px solid ${color.border}`,
      background: color.bgSurface, overflow: 'auto', display: 'flex', flexDirection: 'column',
    }}>
      <div style={{ padding: '12px 14px', borderBottom: `1px solid ${color.border}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: color.textPrimary, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {lang === 'ko' ? rule.title_kr : rule.title_en}
          </div>
          <code style={{ fontSize: 10, color: color.textMuted }}>{rule.rule_id}</code>
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          {onEdit && (
            <button className="mzc-btn mzc-btn-secondary" style={{ fontSize: 11, padding: '3px 8px' }} onClick={onEdit}>Edit</button>
          )}
          <button onClick={onClose} className="mzc-btn mzc-btn-ghost" style={{ fontSize: 14, padding: '0 6px' }}>✕</button>
        </div>
      </div>
      <div style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 12 }}>
        <KV label="Severity"><span className={`severity-badge ${rule.severity.toLowerCase()}`}>{rule.severity}</span></KV>
        <KV label="Evaluation Type"><span className="mzc-badge">{rule.evaluation_type}</span></KV>
        <KV label="Category">
          <div style={{ fontSize: 12 }}>{rule.category_kr}</div>
          <div style={{ fontSize: 11, color: color.textMuted }}>{rule.category_en}</div>
        </KV>
        <KV label="Related sections">
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {rule.related_sections.map(s => <span key={s} className="mzc-badge">{s}</span>)}
          </div>
        </KV>
        <KV label="제목 / Title">
          <div style={{ fontSize: 12 }}>{rule.title_kr}</div>
          <div style={{ fontSize: 11, color: color.textMuted, marginTop: 2 }}>{rule.title_en}</div>
        </KV>
        <KV label="설명 / Description">
          <div style={{ fontSize: 12 }}>{rule.description_kr}</div>
          <div style={{ fontSize: 11, color: color.textMuted, marginTop: 2 }}>{rule.description_en}</div>
        </KV>
        <KV label="PASS criteria">
          <BilingualList kr={rule.pass_criteria_kr} en={rule.pass_criteria_en} />
        </KV>
        <KV label="WARNING criteria">
          <BilingualList kr={rule.warning_criteria_kr} en={rule.warning_criteria_en} />
        </KV>
        <KV label="FAIL criteria">
          <BilingualList kr={rule.fail_criteria_kr} en={rule.fail_criteria_en} />
        </KV>
        <KV label="Recommendation">
          <div style={{ fontSize: 12 }}>{rule.recommendation_template_kr}</div>
          <div style={{ fontSize: 11, color: color.textMuted, marginTop: 2 }}>{rule.recommendation_template_en}</div>
        </KV>
        <KV label="Source">
          <div style={{ fontSize: 12, color: color.textSecondary }}>{rule.source}</div>
        </KV>
        <KV label="Custom">
          <span className="mzc-badge">{rule.custom ? 'custom' : 'built-in'}</span>
        </KV>
      </div>
    </div>
  )
}

function KV({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.06, color: color.textMuted, marginBottom: 3 }}>
        {label}
      </div>
      <div>{children}</div>
    </div>
  )
}

function BilingualList({ kr, en }: { kr: string[]; en: string[] }) {
  const hasAny = (kr && kr.length > 0) || (en && en.length > 0)
  if (!hasAny) return <span style={{ fontSize: 11, color: color.textMuted }}>—</span>
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      {(kr || []).map((v, i) => (
        <div key={`kr-${i}`} style={{ fontSize: 12 }}>· {v}</div>
      ))}
      {(en || []).map((v, i) => (
        <div key={`en-${i}`} style={{ fontSize: 11, color: color.textMuted, fontStyle: 'italic' }}>· {v}</div>
      ))}
    </div>
  )
}

/* ---------- Add / Edit form ---------- */

function RuleFormModal({
  initial, isEdit, onCancel, onSave,
}: {
  initial?: RuleDefinition
  isEdit: boolean
  onCancel: () => void
  onSave: (rule: RuleDefinition) => void | Promise<void>
}) {
  const [draft, setDraft] = useState<RuleDefinition>(initial || emptyRule())
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const update = (patch: Partial<RuleDefinition>) => setDraft(prev => ({ ...prev, ...patch }))

  const updateList = (key: keyof RuleDefinition, raw: string) => {
    const items = raw.split('\n').map(s => s.trim()).filter(Boolean)
    setDraft(prev => ({ ...prev, [key]: items } as RuleDefinition))
  }

  const updateSections = (raw: string) => {
    const items = raw.split(',').map(s => s.trim()).filter(Boolean)
    setDraft(prev => ({ ...prev, related_sections: items }))
  }

  const handleSubmit = async () => {
    setErr(null)
    if (!draft.rule_id || !/^[a-zA-Z0-9_\-]+$/.test(draft.rule_id)) {
      setErr('rule_id는 영문/숫자/언더스코어/하이픈만 사용하세요.')
      return
    }
    if (!draft.title_kr && !draft.title_en) {
      setErr('제목(한글 또는 영문)을 입력하세요.')
      return
    }
    if (!draft.category_kr || !draft.category_en) {
      setErr('카테고리(KR/EN)를 입력하세요.')
      return
    }
    setSaving(true)
    try {
      await onSave({ ...draft, custom: true, enabled: true })
    } catch (e: any) {
      setErr(e?.message || 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(16, 24, 40, 0.55)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1100,
    }}>
      <div className="mzc-panel" style={{ width: 'min(760px, 92vw)', maxHeight: '90vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <div style={{
          padding: '12px 16px', borderBottom: `1px solid ${color.border}`,
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <div style={{ fontSize: 14, fontWeight: 700 }}>
            {isEdit ? 'Edit Custom Rule' : 'Add Custom Rule'}
          </div>
          <button onClick={onCancel} className="mzc-btn mzc-btn-ghost" style={{ fontSize: 14 }}>✕</button>
        </div>

        <div style={{ flex: 1, overflow: 'auto', padding: 16, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <Field label="rule_id" span={2}>
            <input className="mzc-input" value={draft.rule_id} disabled={isEdit}
              onChange={e => update({ rule_id: e.target.value })}
              placeholder="e.g. custom_latency_target" />
          </Field>

          <Field label="카테고리 (KR)">
            <input className="mzc-input" value={draft.category_kr} onChange={e => update({ category_kr: e.target.value })} />
          </Field>
          <Field label="Category (EN)">
            <input className="mzc-input" value={draft.category_en} onChange={e => update({ category_en: e.target.value })} />
          </Field>

          <Field label="제목 (KR)">
            <input className="mzc-input" value={draft.title_kr} onChange={e => update({ title_kr: e.target.value })} />
          </Field>
          <Field label="Title (EN)">
            <input className="mzc-input" value={draft.title_en} onChange={e => update({ title_en: e.target.value })} />
          </Field>

          <Field label="설명 (KR)" span={2}>
            <textarea className="mzc-textarea" rows={3} value={draft.description_kr} onChange={e => update({ description_kr: e.target.value })} />
          </Field>
          <Field label="Description (EN)" span={2}>
            <textarea className="mzc-textarea" rows={3} value={draft.description_en} onChange={e => update({ description_en: e.target.value })} />
          </Field>

          <Field label="Severity">
            <select className="mzc-select" value={draft.severity} onChange={e => update({ severity: e.target.value as RuleSeverity })}>
              {SEVERITIES.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </Field>
          <Field label="Evaluation Type">
            <select className="mzc-select" value={draft.evaluation_type} onChange={e => update({ evaluation_type: e.target.value as EvaluationType })}>
              {EVAL_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </Field>

          <Field label="Related sections (comma-separated)" span={2}>
            <input className="mzc-input"
              value={draft.related_sections.join(', ')}
              onChange={e => updateSections(e.target.value)}
              placeholder="e.g. cost_breakdown, architecture" />
          </Field>

          <Field label="PASS 기준 (KR, 줄바꿈)">
            <textarea className="mzc-textarea" rows={3} value={draft.pass_criteria_kr.join('\n')} onChange={e => updateList('pass_criteria_kr', e.target.value)} />
          </Field>
          <Field label="PASS criteria (EN, lines)">
            <textarea className="mzc-textarea" rows={3} value={draft.pass_criteria_en.join('\n')} onChange={e => updateList('pass_criteria_en', e.target.value)} />
          </Field>

          <Field label="WARNING 기준 (KR, 줄바꿈)">
            <textarea className="mzc-textarea" rows={3} value={draft.warning_criteria_kr.join('\n')} onChange={e => updateList('warning_criteria_kr', e.target.value)} />
          </Field>
          <Field label="WARNING criteria (EN, lines)">
            <textarea className="mzc-textarea" rows={3} value={draft.warning_criteria_en.join('\n')} onChange={e => updateList('warning_criteria_en', e.target.value)} />
          </Field>

          <Field label="FAIL 기준 (KR, 줄바꿈)">
            <textarea className="mzc-textarea" rows={3} value={draft.fail_criteria_kr.join('\n')} onChange={e => updateList('fail_criteria_kr', e.target.value)} />
          </Field>
          <Field label="FAIL criteria (EN, lines)">
            <textarea className="mzc-textarea" rows={3} value={draft.fail_criteria_en.join('\n')} onChange={e => updateList('fail_criteria_en', e.target.value)} />
          </Field>

          <Field label="권장사항 템플릿 (KR)">
            <textarea className="mzc-textarea" rows={2} value={draft.recommendation_template_kr} onChange={e => update({ recommendation_template_kr: e.target.value })} />
          </Field>
          <Field label="Recommendation (EN)">
            <textarea className="mzc-textarea" rows={2} value={draft.recommendation_template_en} onChange={e => update({ recommendation_template_en: e.target.value })} />
          </Field>

          <Field label="Source" span={2}>
            <input className="mzc-input" value={draft.source} onChange={e => update({ source: e.target.value })}
              placeholder="e.g. Custom / Team X" />
          </Field>
        </div>

        {err && (
          <div style={{ padding: '8px 16px', fontSize: 12, color: color.error, background: '#fef2f2', borderTop: '1px solid #fecaca' }}>
            ⚠ {err}
          </div>
        )}

        <div style={{
          padding: '12px 16px', borderTop: `1px solid ${color.border}`,
          display: 'flex', justifyContent: 'flex-end', gap: 8,
        }}>
          <button className="mzc-btn mzc-btn-secondary" onClick={onCancel} disabled={saving}>Cancel</button>
          <button className="mzc-btn mzc-btn-primary" onClick={handleSubmit} disabled={saving}>
            {saving ? 'Saving...' : (isEdit ? 'Save changes' : 'Add rule')}
          </button>
        </div>
      </div>
    </div>
  )
}

function Field({ label, span, children }: { label: string; span?: number; children: React.ReactNode }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 4, gridColumn: span === 2 ? '1 / span 2' : undefined }}>
      <span style={{ fontSize: 11, fontWeight: 600, color: color.textSecondary }}>{label}</span>
      {children}
    </label>
  )
}

function emptyRule(): RuleDefinition {
  return {
    rule_id: '',
    enabled: true,
    custom: true,
    category_en: '',
    category_kr: '',
    title_en: '',
    title_kr: '',
    description_en: '',
    description_kr: '',
    severity: 'Medium',
    evaluation_type: 'llm',
    related_sections: [],
    pass_criteria_en: [],
    pass_criteria_kr: [],
    warning_criteria_en: [],
    warning_criteria_kr: [],
    fail_criteria_en: [],
    fail_criteria_kr: [],
    recommendation_template_en: '',
    recommendation_template_kr: '',
    source: 'Custom',
  }
}
