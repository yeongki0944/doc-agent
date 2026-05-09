import { apiFetch } from '../auth/api'
import {
  REVIEW_RULES_SEED,
  type RuleCatalog,
  type RuleDefinition,
} from '../constants/reviewRulesSeed'

/**
 * Review Rules API client. Wraps the (optional) backend `/review_rules`
 * endpoints. When the backend is unavailable the client returns the
 * seed catalog so the Admin page can operate read-only.
 */

export interface ReviewRulesResponse extends RuleCatalog {
  /** True when returned from local seed (fallback) instead of backend. */
  fromFallback?: boolean
}

const LS_CUSTOM_RULES_KEY = 'mzc.review_rules.custom.v1'
const LS_DISABLED_RULES_KEY = 'mzc.review_rules.disabled.v1'

function readLocalCustom(): RuleDefinition[] {
  try {
    const raw = localStorage.getItem(LS_CUSTOM_RULES_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed)) return parsed as RuleDefinition[]
  } catch {
    /* ignore */
  }
  return []
}

function writeLocalCustom(rules: RuleDefinition[]) {
  try {
    localStorage.setItem(LS_CUSTOM_RULES_KEY, JSON.stringify(rules))
  } catch {
    /* ignore */
  }
}

function readLocalDisabled(): Set<string> {
  try {
    const raw = localStorage.getItem(LS_DISABLED_RULES_KEY)
    if (!raw) return new Set()
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed)) return new Set(parsed.filter(x => typeof x === 'string'))
  } catch {
    /* ignore */
  }
  return new Set()
}

function writeLocalDisabled(set: Set<string>) {
  try {
    localStorage.setItem(LS_DISABLED_RULES_KEY, JSON.stringify(Array.from(set)))
  } catch {
    /* ignore */
  }
}

/**
 * Merge backend or seed rules with local custom rules + local enable/disable
 * overrides. The returned catalog is always safe to render.
 */
function mergeLocalOverrides(catalog: RuleCatalog): RuleCatalog {
  const custom = readLocalCustom()
  const disabled = readLocalDisabled()
  const mergedRules = [
    ...catalog.rules.map(r => (disabled.has(r.rule_id) ? { ...r, enabled: false } : r)),
    // Local custom rules (filter out any whose id already exists in catalog)
    ...custom.filter(c => !catalog.rules.some(r => r.rule_id === c.rule_id)),
  ]
  return { ...catalog, rules: mergedRules }
}

export async function listReviewRules(): Promise<ReviewRulesResponse> {
  try {
    const res = await apiFetch('/review_rules')
    if (res.ok) {
      const data = await res.json()
      if (data && Array.isArray(data.rules)) {
        return { ...data, rules: data.rules as RuleDefinition[] }
      }
    }
  } catch {
    /* ignore and fall through */
  }
  const seeded = mergeLocalOverrides(REVIEW_RULES_SEED)
  return { ...seeded, fromFallback: true }
}

/**
 * Toggle a rule enabled/disabled. Tries backend first, then records the
 * choice locally so the admin UI behaves consistently in fallback mode.
 */
export async function setRuleEnabled(
  ruleId: string,
  enabled: boolean,
): Promise<{ ok: boolean; fromFallback: boolean; message?: string }> {
  try {
    const res = await apiFetch(`/review_rules/${encodeURIComponent(ruleId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    })
    if (res.ok) return { ok: true, fromFallback: false }
  } catch {
    /* ignore */
  }
  const disabled = readLocalDisabled()
  if (enabled) disabled.delete(ruleId)
  else disabled.add(ruleId)
  writeLocalDisabled(disabled)
  return {
    ok: true,
    fromFallback: true,
    message: 'Backend unavailable. Stored enable/disable locally.',
  }
}

export async function createCustomRule(rule: RuleDefinition): Promise<{
  ok: boolean
  fromFallback: boolean
  message?: string
  rule: RuleDefinition
}> {
  const payload: RuleDefinition = { ...rule, custom: true, enabled: true }
  try {
    const res = await apiFetch('/review_rules', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (res.ok) {
      const data = await res.json().catch(() => null)
      return { ok: true, fromFallback: false, rule: (data?.rule as RuleDefinition) || payload }
    }
  } catch {
    /* ignore */
  }
  const customs = readLocalCustom().filter(r => r.rule_id !== payload.rule_id)
  customs.push({ ...payload, updated_at: new Date().toISOString() })
  writeLocalCustom(customs)
  return {
    ok: true,
    fromFallback: true,
    message: 'Backend unavailable. Custom rule stored locally.',
    rule: payload,
  }
}

export async function updateCustomRule(
  ruleId: string,
  patch: Partial<RuleDefinition>,
): Promise<{ ok: boolean; fromFallback: boolean; message?: string }> {
  try {
    const res = await apiFetch(`/review_rules/${encodeURIComponent(ruleId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    })
    if (res.ok) return { ok: true, fromFallback: false }
  } catch {
    /* ignore */
  }
  const customs = readLocalCustom()
  const next = customs.map(r => (r.rule_id === ruleId ? { ...r, ...patch, updated_at: new Date().toISOString() } : r))
  writeLocalCustom(next)
  return {
    ok: true,
    fromFallback: true,
    message: 'Backend unavailable. Custom rule updated locally.',
  }
}

export async function deleteCustomRule(ruleId: string): Promise<{
  ok: boolean
  fromFallback: boolean
  message?: string
}> {
  try {
    const res = await apiFetch(`/review_rules/${encodeURIComponent(ruleId)}`, {
      method: 'DELETE',
    })
    if (res.ok) return { ok: true, fromFallback: false }
  } catch {
    /* ignore */
  }
  const customs = readLocalCustom().filter(r => r.rule_id !== ruleId)
  writeLocalCustom(customs)
  return {
    ok: true,
    fromFallback: true,
    message: 'Backend unavailable. Custom rule deleted locally.',
  }
}
