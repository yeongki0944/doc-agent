import assert from 'node:assert/strict'
import { mkdtemp, rm, readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { build } from 'esbuild'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const srcRoot = path.resolve(__dirname, '..')
const tempDir = await mkdtemp(path.join(srcRoot, '.tmp-front-schema-'))
const bundlePath = path.join(tempDir, 'bundle.mjs')

const result = await build({
  entryPoints: [path.join(srcRoot, 'utils/frontendSchema.ts')],
  bundle: true,
  format: 'esm',
  platform: 'node',
  write: false,
  loader: { '.json': 'json' },
})

await writeFile(bundlePath, result.outputFiles[0].text)
const schema = await import(pathToFileURL(bundlePath))

const {
  createRoleDraft,
  buildStaffingEditPath,
  getRoleOptions,
  resolveDisplayText,
  sortStaffingRoles,
  sortArchitectureServices,
  isBedrockService,
  formatMoney,
  getFundingEligibility,
} = schema

assert.equal(getRoleOptions('engineer').length > 0, true)

const draft = createRoleDraft('engineer', 'backend_engineer')
assert.equal(draft.category, 'engineer')
assert.equal(draft.role_type.ai_recommended, 'backend_engineer')
assert.equal(draft.display_name, 'Backend Engineer')
assert.equal(draft.rate_default.ai_recommended, 75)
assert.equal(buildStaffingEditPath('role-1', 'rate_per_hour'), 'staffing_plan.roles.role-1.rate_per_hour.user_input')

const sortedRoles = sortStaffingRoles({
  b: { role_id: 'b', display_name: 'Beta', category: 'engineer', role_type: draft.role_type, rate_default: draft.rate_default, count: draft.count, allocation_pct: draft.allocation_pct, rate_per_hour: draft.rate_per_hour, phase_hours: draft.phase_hours, total_hours: draft.total_hours, total_cost: draft.total_cost },
  a: { ...draft, role_id: 'a', display_name: 'Alpha' },
})
assert.deepEqual(sortedRoles.map(role => role.display_name), ['Alpha', 'Beta'])
assert.equal(resolveDisplayText({ user_input: null, ai_recommended: 'Field Role', calculated: null, status: 'recommended' }), 'Field Role')
assert.equal(resolveDisplayText({ user_input: { user_input: null, ai_recommended: 'Nested Role', calculated: null, status: 'recommended' }, ai_recommended: null, calculated: null, status: 'user_modified' }), 'Nested Role')

const services = sortArchitectureServices([
  {
    service_name: { ai_recommended: 'Amazon S3' },
    service_id: 'amazon_s3',
    priority: 11,
    category: 'data',
    description: { ai_recommended: '' },
    sizing_rationale: { ai_recommended: '' },
    is_required_for_funding: false,
  },
  {
    service_name: { ai_recommended: 'Amazon Bedrock' },
    service_id: 'amazon_bedrock',
    priority: 1,
    category: 'genai_core',
    description: { ai_recommended: '' },
    sizing_rationale: { ai_recommended: '' },
    is_required_for_funding: true,
  },
])
assert.deepEqual(services.map(service => service.service_id), ['amazon_bedrock', 'amazon_s3'])
assert.equal(isBedrockService(services[0]), true)

assert.equal(formatMoney({ calculated: 125000 }), '125,000')
assert.equal(getFundingEligibility([], { eligible_amount: { calculated: 1000 } }), 'eligible')
assert.equal(getFundingEligibility([{ code: 'ERR' }], { eligible_amount: { calculated: 1000 } }), 'ineligible')

const rolePoolRaw = await readFile(path.join(srcRoot, 'data/role_pool.json'), 'utf8')
const rolePool = JSON.parse(rolePoolRaw)
assert.deepEqual(Object.keys(rolePool).sort(), ['engineer', 'other', 'solution_architect'])
assert.ok(rolePool.solution_architect.some((role) => role.role_id === 'ai_agent_architect'))
assert.ok(rolePool.engineer.some((role) => role.role_id === 'frontend_engineer'))
assert.ok(rolePool.other.some((role) => role.role_id === 'project_manager'))

const documentPanelSource = await readFile(path.join(srcRoot, 'components/DocumentPanel.tsx'), 'utf8')
assert.ok(documentPanelSource.includes('const exportEnabled = blockingIssues.length === 0'))
assert.ok(documentPanelSource.includes('disabled={!exportEnabled}'))

await rm(tempDir, { recursive: true, force: true })
