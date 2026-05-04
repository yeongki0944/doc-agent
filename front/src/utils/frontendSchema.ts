import type { ArchitectureService, FieldValue, FieldStatus } from '../store/documentStore'

const makeFieldValue = (aiRecommended: any = null, status: FieldStatus = 'draft'): FieldValue => ({
  user_input: null,
  ai_recommended: aiRecommended,
  calculated: null,
  status,
})

const resolve = (value: any): string => {
  const resolved = unwrapFieldValue(value)
  if (resolved == null) return ''
  if (Array.isArray(resolved)) {
    return resolved.map(item => resolve(item)).filter(Boolean).join('\n')
  }
  if (typeof resolved === 'object') return JSON.stringify(resolved)
  return String(resolved)
}

function unwrapFieldValue(value: any): any {
  if (!value || typeof value !== 'object') return value ?? null
  if ('user_input' in value || 'ai_recommended' in value || 'calculated' in value) {
    return unwrapFieldValue(value.user_input ?? value.ai_recommended ?? value.calculated ?? null)
  }
  return value
}

export function resolveDisplayText(value: any, fallback = ''): string {
  const text = resolve(value)
  return text || fallback
}

export function sortArchitectureServices(services: ArchitectureService[]): ArchitectureService[] {
  return [...services].sort((a, b) => (a.priority ?? 99) - (b.priority ?? 99) || resolve(a.service_name).localeCompare(resolve(b.service_name)))
}

export function isBedrockService(service: ArchitectureService | Record<string, any>): boolean {
  const name = resolve((service as ArchitectureService).service_name ?? service.service_name).toLowerCase()
  const id = String((service as ArchitectureService).service_id ?? service.service_id ?? '').toLowerCase()
  return name.includes('bedrock') || id.includes('bedrock')
}

export function formatMoney(value: any): string {
  const resolved = resolve(value)
  if (resolved === '' || resolved === 'null' || resolved === 'undefined') return '—'
  const num = Number(resolved.replace(/,/g, ''))
  if (Number.isNaN(num)) return resolved
  return num.toLocaleString()
}

export function getFundingEligibility(blockingIssues: any[], funding: any): 'eligible' | 'ineligible' | 'pending' {
  if (blockingIssues.length > 0) return 'ineligible'
  const eligible = resolve(funding?.eligible_amount)
  if (!eligible) return 'pending'
  return Number(eligible.replace(/,/g, '')) > 0 ? 'eligible' : 'ineligible'
}
