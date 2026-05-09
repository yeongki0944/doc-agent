/**
 * Review Rule Catalog
 *
 * Defines the full submission review rule catalog used by the Review Panel.
 * The backend (`run_submission_lint`) currently returns grouped issues[] and
 * suggested_patches[] only; this catalog lets the UI render a complete
 * rule evaluation matrix (PASS / WARNING / FAIL / NOT_CHECKED) for every
 * rule, not just the ones that tripped.
 *
 * If/when the backend starts returning `rule_evaluations[]` directly,
 * `reviewAdapter.ts` will prefer that payload and use this catalog only for
 * display metadata enrichment.
 */

export type RuleStatus = 'PASS' | 'WARNING' | 'FAIL' | 'NOT_CHECKED'
export type RuleSeverity = 'Critical' | 'High' | 'Medium' | 'Low' | 'Info'

export type CategoryKey =
  | 'business_case'
  | 'production_cost'
  | 'architecture_sizing'
  | 'deployment_scaling'
  | 'risk_governance'
  | 'funding_arr_sow'
  | 'apn_template'
  | 'arch_cost_alignment'

export interface CategoryMeta {
  key: CategoryKey
  label: string
  description: string
}

export const CATEGORIES: CategoryMeta[] = [
  {
    key: 'business_case',
    label: 'Business Case & Commitment',
    description: '비즈니스 케이스, 스폰서, 프로덕션 커밋먼트',
  },
  {
    key: 'production_cost',
    label: 'Production Usage & Cost Assumptions',
    description: '프로덕션 사용량과 비용 가정',
  },
  {
    key: 'architecture_sizing',
    label: 'Architecture & Service Sizing',
    description: '아키텍처 구성과 서비스 사이징',
  },
  {
    key: 'deployment_scaling',
    label: 'Deployment & Scaling Plan',
    description: '배포/확장 계획과 마일스톤',
  },
  {
    key: 'risk_governance',
    label: 'Risk Assessment & Governance',
    description: '리스크, 가정, 거버넌스',
  },
  {
    key: 'funding_arr_sow',
    label: 'Funding / ARR / SOW Cost',
    description: 'ARR, SOW, AWS Calculator 근거',
  },
  {
    key: 'apn_template',
    label: 'APN Template Completeness',
    description: 'APN 템플릿 필수 섹션 완성도',
  },
  {
    key: 'arch_cost_alignment',
    label: 'Architecture-Cost Alignment',
    description: '아키텍처 서비스와 비용 산정의 일관성',
  },
]

export interface RuleDefinition {
  id: string
  /** Stable rule title. */
  title: string
  /** What this rule checks. */
  definition: string
  category: CategoryKey
  severity: RuleSeverity
  /** Backend issue codes that indicate this rule failed. */
  issueCodes: string[]
  /** Document section(s) this rule evaluates. */
  sectionRefs: string[]
  /** Human-readable pass / warning / fail criteria. */
  passCriteria: string
  warningCriteria: string
  failCriteria: string
  /** Short recommendation when the rule does not pass. */
  recommendation: string
}

/**
 * The canonical rule catalog. IDs map 1:1 to backend issue codes where
 * possible; derived or cross-cutting rules use RULE_* prefixes.
 */
export const REVIEW_RULES: RuleDefinition[] = [
  // --- Business Case & Commitment ---
  {
    id: 'BUSINESS_CASE_MISSING',
    title: 'Business case is documented',
    definition: 'Executive Summary에 비즈니스 케이스, 스폰서, 프로덕션 커밋먼트가 서술되어야 합니다.',
    category: 'business_case',
    severity: 'Medium',
    issueCodes: ['BUSINESS_CASE_MISSING'],
    sectionRefs: ['executive_summary'],
    passCriteria: 'Executive Summary에 비즈니스 문제, ROI 근거, 스폰서, 프로덕션 커밋먼트가 명시됨',
    warningCriteria: '일부 항목만 기재되어 있고 ROI/스폰서 근거가 약함',
    failCriteria: 'Executive Summary가 비어 있거나 비즈니스 케이스가 서술되지 않음',
    recommendation: '비즈니스 문제, 기대 ROI, 스폰서, 프로덕션 커밋먼트를 Executive Summary에 추가하세요.',
  },
  {
    id: 'EXECUTIVE_SUMMARY_INCOMPLETE',
    title: 'Executive Summary is complete',
    definition: 'Executive Summary 섹션 자체가 템플릿에 맞게 채워져 있어야 합니다.',
    category: 'business_case',
    severity: 'High',
    issueCodes: ['EXECUTIVE_SUMMARY_INCOMPLETE'],
    sectionRefs: ['executive_summary'],
    passCriteria: 'Executive Summary에 groups 또는 본문이 존재',
    warningCriteria: 'Executive Summary가 단편적으로만 작성됨',
    failCriteria: 'Executive Summary 섹션이 비어 있음',
    recommendation: 'Executive Summary 섹션을 채우세요. AI 추천 프롬프트를 활용하면 빠릅니다.',
  },

  // --- Production Usage & Cost Assumptions ---
  {
    id: 'COST_BREAKDOWN_INCOMPLETE',
    title: 'Cost breakdown is populated',
    definition: 'Cost Breakdown 섹션은 프로덕션 사용량 가정과 함께 채워져야 합니다.',
    category: 'production_cost',
    severity: 'High',
    issueCodes: ['COST_BREAKDOWN_INCOMPLETE'],
    sectionRefs: ['cost_breakdown'],
    passCriteria: 'Cost Breakdown에 staffing_cost 또는 aws_service_cost가 기재됨',
    warningCriteria: '일부 카테고리만 채워짐',
    failCriteria: 'Cost Breakdown 섹션이 비어 있음',
    recommendation: 'Staffing cost, AWS service cost, document summary를 Cost Breakdown에 채우세요.',
  },
  {
    id: 'ASSUMPTIONS_INCOMPLETE',
    title: 'Cost & usage assumptions are documented',
    definition: 'Assumptions 섹션에 프로덕션 사용량/비용 가정이 포함되어야 합니다.',
    category: 'production_cost',
    severity: 'Medium',
    issueCodes: ['ASSUMPTIONS_INCOMPLETE'],
    sectionRefs: ['assumptions'],
    passCriteria: 'Assumptions에 사용량/비용/운영 가정이 명시됨',
    warningCriteria: '가정이 일부만 기재됨',
    failCriteria: 'Assumptions 섹션이 비어 있음',
    recommendation: 'MAU, MRR/ARR, 피크 부하 등 가정을 Assumptions 섹션에 추가하세요.',
  },

  // --- Architecture & Service Sizing ---
  {
    id: 'ARCHITECTURE_INCOMPLETE',
    title: 'Architecture section is populated',
    definition: 'Architecture 섹션에 AWS 서비스 목록과 설명이 포함되어야 합니다.',
    category: 'architecture_sizing',
    severity: 'High',
    issueCodes: ['ARCHITECTURE_INCOMPLETE'],
    sectionRefs: ['architecture'],
    passCriteria: 'Architecture 섹션에 services 또는 overview가 존재',
    warningCriteria: 'services 목록만 있고 설명은 없음',
    failCriteria: 'Architecture 섹션이 비어 있음',
    recommendation: 'Architecture 섹션에 AWS 서비스 목록과 구성 설명을 추가하세요.',
  },
  {
    id: 'ARCHITECTURE_OVERVIEW_MISSING',
    title: 'Architecture overview is present',
    definition: '서비스가 나열되어 있다면 Architecture overview도 서술되어야 합니다.',
    category: 'architecture_sizing',
    severity: 'Medium',
    issueCodes: ['ARCHITECTURE_OVERVIEW_MISSING'],
    sectionRefs: ['architecture'],
    passCriteria: 'Architecture overview에 서비스 선정 배경과 사이징 근거가 서술됨',
    warningCriteria: 'overview가 존재하나 사이징/근거가 약함',
    failCriteria: '서비스는 나열되어 있는데 overview가 비어 있음',
    recommendation: '각 AWS 서비스가 워크로드 사이징을 어떻게 뒷받침하는지 overview에 기술하세요.',
  },
  {
    id: 'BEDROCK_EVIDENCE_MISSING',
    title: 'Amazon Bedrock evidence is provided',
    definition: 'GenAI 펀딩 자격을 위해 Amazon Bedrock 관련 모델/가드레일/사용 가정이 명시되어야 합니다.',
    category: 'architecture_sizing',
    severity: 'Critical',
    issueCodes: ['BEDROCK_EVIDENCE_MISSING'],
    sectionRefs: ['architecture'],
    passCriteria: 'Architecture services에 Bedrock 모델/가드레일/사용 가정이 명시됨',
    warningCriteria: 'Bedrock을 언급하지만 모델/사용 방식이 모호함',
    failCriteria: 'Architecture에 Bedrock 관련 근거가 없음',
    recommendation: 'Bedrock 모델 ID, 사용 방식(RAG/Agent 등), guardrail 구성을 Architecture에 추가하세요.',
  },

  // --- Deployment & Scaling Plan ---
  {
    id: 'MILESTONES_INCOMPLETE',
    title: 'Milestones are defined',
    definition: '배포/확장 흐름은 Milestones 섹션에 단계별로 정의되어야 합니다.',
    category: 'deployment_scaling',
    severity: 'High',
    issueCodes: ['MILESTONES_INCOMPLETE'],
    sectionRefs: ['milestones'],
    passCriteria: 'Milestones에 단계, 일정, 산출물이 정의됨',
    warningCriteria: 'Milestones가 일부만 정의됨',
    failCriteria: 'Milestones 섹션이 비어 있음',
    recommendation: 'Discovery / Build / Handover 단계와 주요 산출물을 Milestones에 추가하세요.',
  },
  {
    id: 'SCOPE_OF_WORK_INCOMPLETE',
    title: 'Scope of Work is documented',
    definition: '배포 범위와 경계가 Scope of Work에 명시되어야 합니다.',
    category: 'deployment_scaling',
    severity: 'High',
    issueCodes: ['SCOPE_OF_WORK_INCOMPLETE'],
    sectionRefs: ['scope_of_work'],
    passCriteria: 'In-scope / Out-of-scope가 모두 기재됨',
    warningCriteria: 'In-scope만 있고 Out-of-scope가 누락됨',
    failCriteria: 'Scope of Work가 비어 있음',
    recommendation: 'Scope of Work에 In-scope / Out-of-scope 항목을 모두 기재하세요.',
  },

  // --- Risk Assessment & Governance ---
  {
    id: 'RISK_GOVERNANCE_MISSING',
    title: 'Risk and governance assumptions are documented',
    definition: 'Assumptions 섹션에 리스크와 거버넌스 항목이 포함되어야 합니다.',
    category: 'risk_governance',
    severity: 'Medium',
    issueCodes: ['RISK_GOVERNANCE_MISSING'],
    sectionRefs: ['assumptions'],
    passCriteria: '리스크, 거버넌스 통제, 고객 측 가정이 기재됨',
    warningCriteria: '리스크만 있고 거버넌스는 누락됨',
    failCriteria: 'Assumptions에 리스크/거버넌스 항목이 없음',
    recommendation: '리스크 레지스터, 보안/거버넌스 통제, 고객 측 책임을 Assumptions에 추가하세요.',
  },
  {
    id: 'STAKEHOLDERS_INCOMPLETE',
    title: 'Stakeholders are listed',
    definition: 'Stakeholders 섹션에 스폰서, 팀, 에스컬레이션 경로가 정의되어야 합니다.',
    category: 'risk_governance',
    severity: 'Medium',
    issueCodes: ['STAKEHOLDERS_INCOMPLETE'],
    sectionRefs: ['stakeholders'],
    passCriteria: 'Sponsors / team / escalation이 모두 정의됨',
    warningCriteria: '일부만 정의됨',
    failCriteria: 'Stakeholders 섹션이 비어 있음',
    recommendation: '스폰서, 실행 팀, 에스컬레이션 담당자를 Stakeholders에 추가하세요.',
  },
  {
    id: 'ACCEPTANCE_INCOMPLETE',
    title: 'Acceptance criteria are defined',
    definition: 'Acceptance 섹션에 인수 기준이 명시되어야 합니다.',
    category: 'risk_governance',
    severity: 'Medium',
    issueCodes: ['ACCEPTANCE_INCOMPLETE'],
    sectionRefs: ['acceptance'],
    passCriteria: '인수 기준이 단계별로 정의됨',
    warningCriteria: '인수 기준이 일부만 정의됨',
    failCriteria: 'Acceptance 섹션이 비어 있음',
    recommendation: '단계별 인수 기준과 검증 방법을 Acceptance에 추가하세요.',
  },

  // --- Funding / ARR / SOW Cost ---
  {
    id: 'ARR_MISSING',
    title: 'Year 1 ARR basis is provided',
    definition: '펀딩 자격 판정에 필요한 Year 1 ARR 근거가 필요합니다.',
    category: 'funding_arr_sow',
    severity: 'High',
    issueCodes: ['ARR_MISSING'],
    sectionRefs: ['cost_breakdown'],
    passCriteria: 'ARR 값이 명시되고 근거(MRR×12 등)가 기재됨',
    warningCriteria: 'MRR만 있고 ARR 근거가 명시적이지 않음',
    failCriteria: 'ARR 값이 없음',
    recommendation: 'Cost Breakdown에 Year 1 ARR 값과 산출 근거를 추가하세요.',
  },
  {
    id: 'SOW_COST_MISSING',
    title: 'SOW cost basis is provided',
    definition: '펀딩 공식은 min(ARR × 25%, SOW Cost, 125K)입니다. SOW Cost가 필요합니다.',
    category: 'funding_arr_sow',
    severity: 'High',
    issueCodes: ['SOW_COST_MISSING'],
    sectionRefs: ['resources_cost_estimates', 'cost_breakdown'],
    passCriteria: 'SOW cost 값이 명시됨 (resources_cost_estimates 또는 funding_calculation)',
    warningCriteria: '값이 있으나 산출 근거가 약함',
    failCriteria: 'SOW cost가 없음',
    recommendation: 'Resources & Cost Estimates에서 SOW 총 비용을 확정하세요.',
  },
  {
    id: 'CALCULATOR_URL_MISSING',
    title: 'AWS Calculator URL is attached',
    definition: 'AWS Pricing Calculator 링크가 Cost Breakdown에 첨부되어야 합니다.',
    category: 'funding_arr_sow',
    severity: 'High',
    issueCodes: ['CALCULATOR_URL_MISSING'],
    sectionRefs: ['cost_breakdown'],
    passCriteria: 'calculator_url이 resolved 상태로 존재',
    warningCriteria: 'URL은 있으나 플레이스홀더로 보임',
    failCriteria: 'calculator_url이 비어 있음',
    recommendation: 'AWS Pricing Calculator 공유 링크를 Cost Breakdown에 첨부하세요.',
  },

  // --- APN Template Completeness ---
  {
    id: 'COVER_INCOMPLETE',
    title: 'Cover page is complete',
    definition: '표지 필수 항목(고객사, 파트너, 날짜, 프로젝트명)이 모두 채워져야 합니다.',
    category: 'apn_template',
    severity: 'High',
    issueCodes: ['COVER_INCOMPLETE'],
    sectionRefs: ['cover'],
    passCriteria: 'Cover 필수 항목이 모두 채워짐',
    warningCriteria: '일부 필수 항목이 비어 있음',
    failCriteria: 'Cover 섹션이 비어 있음',
    recommendation: 'Cover 섹션의 필수 항목을 모두 채우세요.',
  },
  {
    id: 'SUCCESS_CRITERIA_INCOMPLETE',
    title: 'Success criteria are defined',
    definition: 'Success Criteria 섹션에 측정 가능한 KPI/기준이 정의되어야 합니다.',
    category: 'apn_template',
    severity: 'High',
    issueCodes: ['SUCCESS_CRITERIA_INCOMPLETE'],
    sectionRefs: ['success_criteria'],
    passCriteria: '측정 가능한 KPI 또는 정량 기준이 기재됨',
    warningCriteria: '정성적 기준만 기재됨',
    failCriteria: 'Success Criteria 섹션이 비어 있음',
    recommendation: '측정 가능한 KPI와 목표치를 Success Criteria에 추가하세요.',
  },
  {
    id: 'CUSTOMER_MISSING',
    title: 'Customer name is confirmed',
    definition: 'meta.customer가 확정 상태여야 합니다.',
    category: 'apn_template',
    severity: 'Low',
    issueCodes: ['CUSTOMER_MISSING'],
    sectionRefs: ['cover'],
    passCriteria: 'meta.customer가 resolved 상태',
    warningCriteria: 'customer가 플레이스홀더로 남아 있음',
    failCriteria: 'customer 값이 없음',
    recommendation: 'Cover에서 고객사명을 확정하세요.',
  },
  {
    id: 'RESOURCES_COST_ESTIMATES_INCOMPLETE',
    title: 'Resources & Cost Estimates are filled',
    definition: 'APN 템플릿의 Resources & Cost Estimates 섹션이 채워져야 합니다.',
    category: 'apn_template',
    severity: 'High',
    issueCodes: ['RESOURCES_COST_ESTIMATES_INCOMPLETE'],
    sectionRefs: ['resources_cost_estimates'],
    passCriteria: 'Role rates, phase hours, contribution이 모두 기재됨',
    warningCriteria: '일부 테이블이 채워지지 않음',
    failCriteria: '섹션이 비어 있음',
    recommendation: 'Role rate, phase hours, contribution 테이블을 Resources & Cost Estimates에 채우세요.',
  },

  // --- Architecture-Cost Alignment (cross-cutting) ---
  {
    id: 'RULE_ARCH_COST_ALIGNMENT',
    title: 'Architecture services are reflected in cost breakdown',
    definition: 'Architecture에 나열된 AWS 서비스가 Cost Breakdown의 aws_service_cost에도 반영되어야 합니다.',
    category: 'arch_cost_alignment',
    severity: 'Medium',
    // No direct backend code; derived from ARCHITECTURE_INCOMPLETE +
    // COST_BREAKDOWN_INCOMPLETE combination in the adapter.
    issueCodes: [],
    sectionRefs: ['architecture', 'cost_breakdown'],
    passCriteria: 'Architecture 서비스와 Cost Breakdown aws_service_cost가 모두 채워짐',
    warningCriteria: '서비스는 있는데 비용 항목이 비어 있음',
    failCriteria: '둘 다 비어 있음',
    recommendation: 'Architecture의 각 AWS 서비스에 대해 Cost Breakdown에 비용 항목을 매핑하세요.',
  },
]

export const RULES_BY_CATEGORY: Record<CategoryKey, RuleDefinition[]> = CATEGORIES.reduce(
  (acc, cat) => {
    acc[cat.key] = REVIEW_RULES.filter(r => r.category === cat.key)
    return acc
  },
  {} as Record<CategoryKey, RuleDefinition[]>,
)

export const RULES_BY_ID: Record<string, RuleDefinition> = REVIEW_RULES.reduce(
  (acc, r) => {
    acc[r.id] = r
    return acc
  },
  {} as Record<string, RuleDefinition>,
)

export const RULE_BY_ISSUE_CODE: Record<string, RuleDefinition> = REVIEW_RULES.reduce(
  (acc, r) => {
    for (const code of r.issueCodes) acc[code] = r
    return acc
  },
  {} as Record<string, RuleDefinition>,
)

export const SECTION_LABELS: Record<string, string> = {
  cover: 'Cover',
  executive_summary: 'Executive Summary',
  stakeholders: 'Stakeholders',
  success_criteria: 'Success Criteria',
  assumptions: 'Assumptions',
  scope_of_work: 'Scope of Work',
  architecture: 'Architecture',
  milestones: 'Milestones',
  cost_breakdown: 'Cost Breakdown',
  acceptance: 'Acceptance',
  resources_cost_estimates: 'Resources & Cost Estimates',
  meta: 'Meta',
}
