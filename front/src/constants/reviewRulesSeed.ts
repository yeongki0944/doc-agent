/**
 * Review Rules Seed Catalog
 *
 * Bilingual (KR/EN) review rule catalog used as fallback when the backend
 * `/review_rules` endpoint is not yet available. Sourced from the
 * `review_rules_seed.json` bundle (version 2026-05-09.v1) derived from:
 *  - AWS Fund Program
 *  - GenAIIC PLD Funding Guide 2025
 *  - SOW Pre-Submission Checklist for MegazoneCloud
 *
 * The Review Panel and Review Rules Admin page both consume rules in this
 * shape. When backend support lands, responses with the same field shape
 * take precedence.
 */

export type RuleSeverity = 'Critical' | 'High' | 'Medium' | 'Low' | 'Info'
export type EvaluationType = 'static' | 'llm' | 'hybrid'
export type RuleStatus = 'PASS' | 'WARNING' | 'FAIL' | 'NOT_CHECKED'

export interface RuleDefinition {
  rule_id: string
  enabled: boolean
  custom: boolean
  category_en: string
  category_kr: string
  title_en: string
  title_kr: string
  description_en: string
  description_kr: string
  severity: RuleSeverity
  evaluation_type: EvaluationType
  related_sections: string[]
  pass_criteria_en: string[]
  pass_criteria_kr: string[]
  warning_criteria_en: string[]
  warning_criteria_kr: string[]
  fail_criteria_en: string[]
  fail_criteria_kr: string[]
  recommendation_template_en: string
  recommendation_template_kr: string
  source: string
  updated_at?: string
}

export interface RuleCatalog {
  version: string
  source_documents: string[]
  rules: RuleDefinition[]
}

export const REVIEW_RULES_SEED: RuleCatalog = {
  version: '2026-05-09.v1',
  source_documents: [
    'AWS펀드 프로그램.txt',
    'GenAIIC PLD 펀딩 가이드 2025.txt',
    'SOW Pre-Submission Checklist for MegazoneCloud (한글본).docx.txt',
  ],
  rules: [
    {
      rule_id: 'bedrock_included',
      enabled: true,
      custom: false,
      category_en: 'GenAI IC Eligibility',
      category_kr: 'GenAI IC 자격',
      title_en: 'Amazon Bedrock is included as a core service',
      title_kr: 'Amazon Bedrock이 핵심 서비스로 포함되어 있는가',
      description_en: 'The project must clearly include Amazon Bedrock as a core GenAI service.',
      description_kr: '프로젝트에는 Amazon Bedrock이 핵심 GenAI 서비스로 명확히 포함되어야 합니다.',
      severity: 'Critical',
      evaluation_type: 'hybrid',
      related_sections: ['architecture', 'scope_of_work', 'cost_breakdown'],
      pass_criteria_en: [
        'Amazon Bedrock is explicitly listed as a core service.',
        'Bedrock usage is tied to the use case.',
      ],
      pass_criteria_kr: [
        'Amazon Bedrock이 핵심 서비스로 명시되어 있습니다.',
        'Bedrock 사용 목적이 Use Case와 연결되어 있습니다.',
      ],
      warning_criteria_en: ['Bedrock is mentioned but its role is unclear.'],
      warning_criteria_kr: ['Bedrock은 언급되었지만 역할이 불명확합니다.'],
      fail_criteria_en: ['Amazon Bedrock is not mentioned.'],
      fail_criteria_kr: ['Amazon Bedrock이 언급되지 않았습니다.'],
      recommendation_template_en:
        'Add Amazon Bedrock as a core service and explain how it powers the GenAI use case.',
      recommendation_template_kr:
        'Amazon Bedrock을 핵심 서비스로 추가하고 GenAI Use Case에서 어떤 역할을 하는지 설명하십시오.',
      source: 'AWS Fund Program / GenAIIC PLD Funding Guide',
    },
    {
      rule_id: 'funding_amount_rule',
      enabled: true,
      custom: false,
      category_en: 'Funding',
      category_kr: '펀딩',
      title_en: 'Funding amount follows min(25% ARR, SOW Cost, $125K)',
      title_kr: '펀딩 금액이 25% ARR, SOW Cost, $125K 중 작은 값 기준을 따르는가',
      description_en:
        'The requested funding amount should be justified against ARR, SOW Cost, and the $125K cap.',
      description_kr: '요청 펀딩 금액은 ARR, SOW Cost, $125K 한도 기준으로 검증되어야 합니다.',
      severity: 'Critical',
      evaluation_type: 'static',
      related_sections: ['cost_breakdown', 'resources_cost_estimates'],
      pass_criteria_en: [
        'ARR, SOW Cost, and requested funding amount are present.',
        'The calculated eligible funding amount is clear.',
      ],
      pass_criteria_kr: [
        'ARR, SOW Cost, 요청 펀딩 금액이 모두 존재합니다.',
        '지원 가능 금액 계산 결과가 명확합니다.',
      ],
      warning_criteria_en: ['Some funding inputs exist but calculation is incomplete.'],
      warning_criteria_kr: ['일부 펀딩 입력값은 있으나 계산이 불완전합니다.'],
      fail_criteria_en: ['Funding amount is requested without ARR or SOW Cost basis.'],
      fail_criteria_kr: ['ARR 또는 SOW Cost 근거 없이 펀딩 금액이 요청되었습니다.'],
      recommendation_template_en:
        'Add ARR, SOW Cost, requested funding amount, and calculate min(ARR × 25%, SOW Cost, $125K).',
      recommendation_template_kr:
        'ARR, SOW Cost, 요청 펀딩 금액을 추가하고 min(ARR × 25%, SOW Cost, $125K)를 계산하십시오.',
      source: 'AWS Fund Program',
    },
    {
      rule_id: 'calculator_link_exists',
      enabled: true,
      custom: false,
      category_en: 'AWS ARR',
      category_kr: 'AWS ARR',
      title_en: 'AWS Calculator link is provided',
      title_kr: 'AWS Calculator 링크가 제공되었는가',
      description_en:
        'The Project Plan/SOW should include an AWS Online Calculator link for possible AWS services.',
      description_kr:
        'Project Plan/SOW에는 가능한 AWS 서비스에 대한 AWS Online Calculator 링크가 포함되어야 합니다.',
      severity: 'Critical',
      evaluation_type: 'static',
      related_sections: ['cost_breakdown'],
      pass_criteria_en: ['A valid AWS Calculator URL is present.'],
      pass_criteria_kr: ['유효한 AWS Calculator URL이 존재합니다.'],
      warning_criteria_en: ['A calculator reference exists but URL is missing or invalid.'],
      warning_criteria_kr: ['Calculator 언급은 있으나 URL이 없거나 유효하지 않습니다.'],
      fail_criteria_en: ['No AWS Calculator link is provided.'],
      fail_criteria_kr: ['AWS Calculator 링크가 제공되지 않았습니다.'],
      recommendation_template_en:
        'Add an AWS Calculator share URL for all supported AWS services.',
      recommendation_template_kr: '지원 가능한 AWS 서비스에 대한 AWS Calculator 공유 URL을 추가하십시오.',
      source: 'GenAIIC PLD Funding Guide',
    },
    {
      rule_id: 'bedrock_cost_estimate_exists',
      enabled: true,
      custom: false,
      category_en: 'AWS ARR',
      category_kr: 'AWS ARR',
      title_en: 'Bedrock cost is estimated separately when not available in Calculator',
      title_kr: 'Calculator에 없는 Bedrock 비용이 별도 산정되었는가',
      description_en:
        'If Bedrock is not available in the Calculator estimate, a separate spreadsheet-style estimate should be included.',
      description_kr: 'Bedrock 비용이 Calculator에 포함되지 않는 경우 별도 산정 근거가 포함되어야 합니다.',
      severity: 'Critical',
      evaluation_type: 'hybrid',
      related_sections: ['cost_breakdown', 'assumptions'],
      pass_criteria_en: [
        'Bedrock token usage assumptions are documented.',
        'Bedrock monthly or annual cost estimate is present.',
      ],
      pass_criteria_kr: [
        'Bedrock Token 사용 가정이 문서화되어 있습니다.',
        'Bedrock 월간 또는 연간 비용 산정이 존재합니다.',
      ],
      warning_criteria_en: ['Bedrock cost exists but token assumptions are weak.'],
      warning_criteria_kr: ['Bedrock 비용은 있으나 Token 가정이 약합니다.'],
      fail_criteria_en: ['No Bedrock cost or token estimate is provided.'],
      fail_criteria_kr: ['Bedrock 비용 또는 Token 산정이 제공되지 않았습니다.'],
      recommendation_template_en:
        'Add Bedrock input/output token assumptions and estimated monthly/annual cost.',
      recommendation_template_kr: 'Bedrock input/output token 가정과 월/연 비용 산정을 추가하십시오.',
      source: 'GenAIIC PLD Funding Guide / SOW Checklist',
    },
    {
      rule_id: 'total_arr_documented',
      enabled: true,
      custom: false,
      category_en: 'AWS ARR',
      category_kr: 'AWS ARR',
      title_en: 'Total AWS ARR is documented',
      title_kr: '전체 AWS ARR이 문서화되었는가',
      description_en:
        'The document should state total AWS ARR, combining Calculator-based and separate estimates if needed.',
      description_kr:
        '문서에는 Calculator 기반 비용과 별도 산정을 합산한 전체 AWS ARR이 명시되어야 합니다.',
      severity: 'Critical',
      evaluation_type: 'static',
      related_sections: ['cost_breakdown'],
      pass_criteria_en: ['Total AWS ARR is explicitly stated.'],
      pass_criteria_kr: ['전체 AWS ARR이 명확히 기재되어 있습니다.'],
      warning_criteria_en: ['MRR exists but ARR is not clearly calculated.'],
      warning_criteria_kr: ['MRR은 있으나 ARR 계산이 명확하지 않습니다.'],
      fail_criteria_en: ['No AWS ARR or MRR basis is provided.'],
      fail_criteria_kr: ['AWS ARR 또는 MRR 근거가 제공되지 않았습니다.'],
      recommendation_template_en: 'Add total AWS MRR/ARR and show how it was calculated.',
      recommendation_template_kr: '전체 AWS MRR/ARR과 계산 방식을 추가하십시오.',
      source: 'GenAIIC PLD Funding Guide',
    },
    {
      rule_id: 'genai_arr_percentage',
      enabled: true,
      custom: false,
      category_en: 'AWS ARR',
      category_kr: 'AWS ARR',
      title_en: 'Core GenAI service percentage in ARR is documented',
      title_kr: '전체 ARR 중 핵심 GenAI 서비스 비중이 문서화되었는가',
      description_en:
        'The document should mention the percentage of core AWS GenAI services in total AWS ARR.',
      description_kr: '문서에는 전체 AWS ARR 중 핵심 GenAI 서비스 비중이 명시되어야 합니다.',
      severity: 'High',
      evaluation_type: 'llm',
      related_sections: ['cost_breakdown'],
      pass_criteria_en: ['Core GenAI service percentage is stated.'],
      pass_criteria_kr: ['핵심 GenAI 서비스 비중이 명시되어 있습니다.'],
      warning_criteria_en: ['GenAI service costs are present but percentage is not calculated.'],
      warning_criteria_kr: ['GenAI 서비스 비용은 있으나 비중 계산이 없습니다.'],
      fail_criteria_en: ['No GenAI ARR percentage or comparable explanation is provided.'],
      fail_criteria_kr: ['GenAI ARR 비중 또는 유사 설명이 없습니다.'],
      recommendation_template_en:
        'Add the percentage of core AWS GenAI services within total AWS ARR.',
      recommendation_template_kr: '전체 AWS ARR 중 핵심 AWS GenAI 서비스 비중을 추가하십시오.',
      source: 'GenAIIC PLD Funding Guide',
    },
    {
      rule_id: 'sow_cost_breakdown_exists',
      enabled: true,
      custom: false,
      category_en: 'SOW Cost',
      category_kr: 'SOW 비용',
      title_en: 'SOW cost breakdown is documented',
      title_kr: 'SOW Cost Breakdown이 문서화되었는가',
      description_en:
        'The document should break down SOW cost by activity, role, phase, or partner/customer contribution.',
      description_kr:
        '문서에는 활동, 역할, 단계 또는 Partner/Customer 분담 기준으로 SOW 비용이 분해되어야 합니다.',
      severity: 'Critical',
      evaluation_type: 'hybrid',
      related_sections: ['resources_cost_estimates'],
      pass_criteria_en: [
        'SOW cost breakdown exists.',
        'Role/rate/hour or contribution basis is clear.',
      ],
      pass_criteria_kr: [
        'SOW 비용 분해가 존재합니다.',
        'Role/rate/hour 또는 비용 분담 기준이 명확합니다.',
      ],
      warning_criteria_en: ['Total SOW cost exists but detailed breakdown is weak.'],
      warning_criteria_kr: ['총 SOW 비용은 있으나 상세 분해가 약합니다.'],
      fail_criteria_en: ['No SOW cost breakdown is provided.'],
      fail_criteria_kr: ['SOW 비용 분해가 제공되지 않았습니다.'],
      recommendation_template_en:
        'Add a SOW cost breakdown by role, rate, hours, phase, and contribution owner.',
      recommendation_template_kr:
        '역할, 단가, 시간, 단계, 비용 분담 주체 기준으로 SOW 비용 분해를 추가하십시오.',
      source: 'GenAIIC PLD Funding Guide / SOW Checklist',
    },
    {
      rule_id: 'partner_customer_cost_split',
      enabled: true,
      custom: false,
      category_en: 'SOW Cost',
      category_kr: 'SOW 비용',
      title_en: 'Partner and customer cost split is clear',
      title_kr: 'Partner / Customer 비용 분담이 명확한가',
      description_en:
        'The cost split between AWS partner and customer should be clear where applicable.',
      description_kr: '해당되는 경우 AWS Partner와 Customer 간 비용 분담이 명확해야 합니다.',
      severity: 'High',
      evaluation_type: 'llm',
      related_sections: ['resources_cost_estimates', 'cost_breakdown'],
      pass_criteria_en: ['Partner/customer contribution split is documented.'],
      pass_criteria_kr: ['Partner/Customer 비용 분담이 문서화되어 있습니다.'],
      warning_criteria_en: ['Contribution is implied but not clearly stated.'],
      warning_criteria_kr: ['비용 분담이 암시되어 있으나 명확하지 않습니다.'],
      fail_criteria_en: ['No cost split or contribution ownership is provided.'],
      fail_criteria_kr: ['비용 분담 또는 부담 주체가 제공되지 않았습니다.'],
      recommendation_template_en: 'Add partner/customer contribution details for SOW cost.',
      recommendation_template_kr: 'SOW 비용에 대한 Partner/Customer 분담 내용을 추가하십시오.',
      source: 'GenAIIC PLD Funding Guide',
    },
    {
      rule_id: 'use_case_defined',
      enabled: true,
      custom: false,
      category_en: 'Use Case',
      category_kr: '유스케이스',
      title_en: 'Customer use case is clearly described',
      title_kr: '고객 Use Case가 명확히 설명되었는가',
      description_en:
        'The document should clearly describe the customer use case and target business workflow.',
      description_kr: '문서에는 고객 Use Case와 대상 업무 흐름이 명확히 설명되어야 합니다.',
      severity: 'Critical',
      evaluation_type: 'llm',
      related_sections: ['executive_summary', 'scope_of_work', 'architecture'],
      pass_criteria_en: ['Use case is specific and tied to customer business workflow.'],
      pass_criteria_kr: ['Use Case가 구체적이며 고객 업무 흐름과 연결되어 있습니다.'],
      warning_criteria_en: ['Use case is present but generic.'],
      warning_criteria_kr: ['Use Case는 있으나 일반적입니다.'],
      fail_criteria_en: ['Use case is missing or unclear.'],
      fail_criteria_kr: ['Use Case가 없거나 불명확합니다.'],
      recommendation_template_en: 'Add a concise customer-specific GenAI use case description.',
      recommendation_template_kr: '고객별 GenAI Use Case 설명을 구체적으로 추가하십시오.',
      source: 'GenAIIC PLD Funding Guide / SOW Checklist',
    },
    {
      rule_id: 'business_problem_defined',
      enabled: true,
      custom: false,
      category_en: 'Business Case & Commitment',
      category_kr: '비즈니스 케이스 및 커밋먼트',
      title_en: 'Customer problem and pain point are specific',
      title_kr: '고객 문제와 Pain Point가 구체적인가',
      description_en:
        'The document should describe why the customer is investing and what problem is being solved.',
      description_kr: '문서에는 고객이 왜 투자하는지와 어떤 문제를 해결하려는지 설명되어야 합니다.',
      severity: 'High',
      evaluation_type: 'llm',
      related_sections: ['executive_summary'],
      pass_criteria_en: [
        'Specific pain points, current workload, time, cost, or error rate are described.',
      ],
      pass_criteria_kr: [
        '구체적인 Pain Point, 현재 업무량, 시간, 비용, 오류율 등이 설명되어 있습니다.',
      ],
      warning_criteria_en: ['Pain point exists but lacks measurable detail.'],
      warning_criteria_kr: ['Pain Point는 있으나 정량적 세부정보가 부족합니다.'],
      fail_criteria_en: ['No specific customer problem is described.'],
      fail_criteria_kr: ['구체적인 고객 문제가 설명되지 않았습니다.'],
      recommendation_template_en:
        'Add specific customer pain points such as manual workload, search time, error rate, or cost.',
      recommendation_template_kr:
        '수작업량, 검색 시간, 오류율, 비용 등 구체적인 고객 Pain Point를 추가하십시오.',
      source: 'SOW Pre-Submission Checklist',
    },
    {
      rule_id: 'business_value_quantified',
      enabled: true,
      custom: false,
      category_en: 'Business Case & Commitment',
      category_kr: '비즈니스 케이스 및 커밋먼트',
      title_en: 'Business value is quantified',
      title_kr: '비즈니스 가치가 수치화되었는가',
      description_en:
        'The document should quantify expected business value such as time savings, cost reduction, or productivity improvement.',
      description_kr:
        '문서에는 시간 절감, 비용 절감, 생산성 개선 등 기대 비즈니스 가치가 수치화되어야 합니다.',
      severity: 'High',
      evaluation_type: 'llm',
      related_sections: ['executive_summary', 'success_criteria'],
      pass_criteria_en: ['Business value is expressed with numbers or measurable outcomes.'],
      pass_criteria_kr: ['비즈니스 가치가 수치 또는 측정 가능한 결과로 표현되어 있습니다.'],
      warning_criteria_en: ['Business value is described qualitatively only.'],
      warning_criteria_kr: ['비즈니스 가치가 정성적으로만 설명되어 있습니다.'],
      fail_criteria_en: ['No business value is stated.'],
      fail_criteria_kr: ['비즈니스 가치가 명시되지 않았습니다.'],
      recommendation_template_en:
        'Add quantified value such as time saved, cost saved, automation rate, or accuracy improvement.',
      recommendation_template_kr:
        '절감 시간, 절감 비용, 자동화율, 정확도 개선 등 수치화된 가치를 추가하십시오.',
      source: 'SOW Pre-Submission Checklist',
    },
    {
      rule_id: 'roi_basis_exists',
      enabled: true,
      custom: false,
      category_en: 'Business Case & Commitment',
      category_kr: '비즈니스 케이스 및 커밋먼트',
      title_en: 'ROI basis is documented',
      title_kr: 'ROI 계산 근거가 있는가',
      description_en:
        'The document should include ROI logic such as before/after effort, cost savings, or TCO comparison.',
      description_kr:
        '문서에는 전후 업무량, 비용 절감, TCO 비교 등 ROI 계산 논리가 포함되어야 합니다.',
      severity: 'High',
      evaluation_type: 'llm',
      related_sections: ['executive_summary', 'success_criteria', 'cost_breakdown'],
      pass_criteria_en: ['ROI calculation or value formula is present.'],
      pass_criteria_kr: ['ROI 계산 또는 가치 산식이 존재합니다.'],
      warning_criteria_en: ['ROI is implied but not calculated.'],
      warning_criteria_kr: ['ROI가 암시되어 있으나 계산되지 않았습니다.'],
      fail_criteria_en: ['No ROI basis is provided.'],
      fail_criteria_kr: ['ROI 근거가 제공되지 않았습니다.'],
      recommendation_template_en:
        'Add a simple ROI calculation using time saved, hourly cost, annual volume, or TCO.',
      recommendation_template_kr:
        '절감 시간, 시간당 비용, 연간 처리량 또는 TCO 기반의 간단한 ROI 계산을 추가하십시오.',
      source: 'SOW Pre-Submission Checklist',
    },
    {
      rule_id: 'executive_sponsor_exists',
      enabled: true,
      custom: false,
      category_en: 'Business Case & Commitment',
      category_kr: '비즈니스 케이스 및 커밋먼트',
      title_en: 'Executive sponsor is identified',
      title_kr: 'Executive Sponsor가 명시되었는가',
      description_en:
        'The document should identify the executive sponsor or decision owner where available.',
      description_kr: '문서에는 가능하면 Executive Sponsor 또는 의사결정 책임자가 명시되어야 합니다.',
      severity: 'Medium',
      evaluation_type: 'llm',
      related_sections: ['stakeholders', 'executive_summary'],
      pass_criteria_en: ['Executive sponsor or decision owner is identified.'],
      pass_criteria_kr: ['Executive Sponsor 또는 의사결정 책임자가 식별되어 있습니다.'],
      warning_criteria_en: ['Stakeholders exist but sponsor is unclear.'],
      warning_criteria_kr: ['이해관계자는 있으나 Sponsor가 불명확합니다.'],
      fail_criteria_en: ['No sponsor or decision owner is identified.'],
      fail_criteria_kr: ['Sponsor 또는 의사결정자가 식별되지 않았습니다.'],
      recommendation_template_en:
        'Add executive sponsor or decision owner information if available.',
      recommendation_template_kr: '가능한 경우 Executive Sponsor 또는 의사결정자 정보를 추가하십시오.',
      source: 'SOW Pre-Submission Checklist',
    },
    {
      rule_id: 'production_commitment_exists',
      enabled: true,
      custom: false,
      category_en: 'Business Case & Commitment',
      category_kr: '비즈니스 케이스 및 커밋먼트',
      title_en: 'Production commitment or production path is documented',
      title_kr: 'Production 전환 계획 또는 커밋먼트가 문서화되었는가',
      description_en:
        'The document should describe the plan or condition for moving from PoC to production.',
      description_kr: '문서에는 PoC 이후 Production 전환 계획 또는 조건이 설명되어야 합니다.',
      severity: 'Critical',
      evaluation_type: 'llm',
      related_sections: ['executive_summary', 'milestones', 'acceptance'],
      pass_criteria_en: ['Production timeline, condition, or commitment is documented.'],
      pass_criteria_kr: ['Production 일정, 조건 또는 커밋먼트가 문서화되어 있습니다.'],
      warning_criteria_en: ['Production is mentioned but timeline or condition is weak.'],
      warning_criteria_kr: ['Production은 언급되었으나 일정 또는 조건이 약합니다.'],
      fail_criteria_en: ['No production path or commitment is documented.'],
      fail_criteria_kr: ['Production 전환 경로 또는 커밋먼트가 문서화되지 않았습니다.'],
      recommendation_template_en: 'Add a production transition plan or condition after successful PoC.',
      recommendation_template_kr: 'PoC 성공 후 Production 전환 계획 또는 조건을 추가하십시오.',
      source: 'SOW Pre-Submission Checklist / GenAIIC PLD Funding Guide',
    },
    {
      rule_id: 'success_criteria_measurable',
      enabled: true,
      custom: false,
      category_en: 'Success Criteria',
      category_kr: '성공 기준',
      title_en: 'Success criteria are measurable',
      title_kr: '성공 기준이 정량적으로 측정 가능한가',
      description_en:
        'Success criteria should include measurable KPIs such as accuracy, latency, automation rate, or satisfaction.',
      description_kr:
        '성공 기준에는 정확도, 응답시간, 자동화율, 만족도 등 측정 가능한 KPI가 포함되어야 합니다.',
      severity: 'High',
      evaluation_type: 'llm',
      related_sections: ['success_criteria'],
      pass_criteria_en: ['Success criteria include clear numeric targets.'],
      pass_criteria_kr: ['성공 기준에 명확한 정량 목표가 포함되어 있습니다.'],
      warning_criteria_en: ['Success criteria exist but are mostly qualitative.'],
      warning_criteria_kr: ['성공 기준은 있으나 대부분 정성적입니다.'],
      fail_criteria_en: ['No measurable success criteria are provided.'],
      fail_criteria_kr: ['측정 가능한 성공 기준이 제공되지 않았습니다.'],
      recommendation_template_en:
        'Add measurable targets such as accuracy, response time, automation rate, or user satisfaction.',
      recommendation_template_kr:
        '정확도, 응답시간, 자동화율, 사용자 만족도 등 측정 가능한 목표를 추가하십시오.',
      source: 'SOW Pre-Submission Checklist',
    },
    {
      rule_id: 'usage_volume_exists',
      enabled: true,
      custom: false,
      category_en: 'Production Usage & Cost Assumptions',
      category_kr: '프로덕션 사용량 및 비용 가정',
      title_en: 'Production request volume is documented',
      title_kr: '프로덕션 요청량이 문서화되었는가',
      description_en:
        'The document should include expected users, request volume, peak usage, or usage period.',
      description_kr:
        '문서에는 예상 사용자 수, 요청량, 피크 사용량 또는 사용 시간대가 포함되어야 합니다.',
      severity: 'Critical',
      evaluation_type: 'llm',
      related_sections: ['assumptions', 'cost_breakdown'],
      pass_criteria_en: ['Expected user count and daily/monthly request volume are provided.'],
      pass_criteria_kr: ['예상 사용자 수와 일/월 요청량이 제공되어 있습니다.'],
      warning_criteria_en: ['Usage is described qualitatively but lacks concrete numbers.'],
      warning_criteria_kr: ['사용량이 정성적으로만 설명되고 구체적인 수치가 부족합니다.'],
      fail_criteria_en: ['No production usage volume is provided.'],
      fail_criteria_kr: ['프로덕션 사용량 가정이 제공되지 않았습니다.'],
      recommendation_template_en:
        'Add expected users, daily requests, peak concurrency, and usage period.',
      recommendation_template_kr:
        '예상 사용자 수, 일 요청량, 피크 동시성, 사용 시간대를 추가하십시오.',
      source: 'SOW Pre-Submission Checklist',
    },
    {
      rule_id: 'token_assumption_exists',
      enabled: true,
      custom: false,
      category_en: 'Production Usage & Cost Assumptions',
      category_kr: '프로덕션 사용량 및 비용 가정',
      title_en: 'Bedrock token assumptions are documented',
      title_kr: 'Bedrock Token 사용 가정이 문서화되었는가',
      description_en:
        'The document should include input/output token assumptions for Bedrock usage.',
      description_kr: '문서에는 Bedrock 사용에 대한 input/output token 가정이 포함되어야 합니다.',
      severity: 'Critical',
      evaluation_type: 'llm',
      related_sections: ['assumptions', 'cost_breakdown'],
      pass_criteria_en: [
        'Input/output token assumptions and monthly token volume are provided.',
      ],
      pass_criteria_kr: ['Input/output token 가정과 월간 token 사용량이 제공되어 있습니다.'],
      warning_criteria_en: ['Token usage exists but calculation is incomplete.'],
      warning_criteria_kr: ['Token 사용량은 있으나 계산이 불완전합니다.'],
      fail_criteria_en: ['No Bedrock token assumption is provided.'],
      fail_criteria_kr: ['Bedrock Token 가정이 제공되지 않았습니다.'],
      recommendation_template_en:
        'Add average input/output tokens, requests per user, users, and monthly token calculation.',
      recommendation_template_kr:
        '평균 input/output token, 사용자별 요청 수, 사용자 수, 월간 token 계산을 추가하십시오.',
      source: 'SOW Pre-Submission Checklist',
    },
    {
      rule_id: 'data_volume_exists',
      enabled: true,
      custom: false,
      category_en: 'Production Usage & Cost Assumptions',
      category_kr: '프로덕션 사용량 및 비용 가정',
      title_en: 'Data volume and retention assumptions are documented',
      title_kr: '데이터 규모와 보관 가정이 문서화되었는가',
      description_en:
        'The document should include data size, document count, storage, vector index, or retention assumptions.',
      description_kr:
        '문서에는 데이터 크기, 문서 수, 스토리지, 벡터 인덱스, 보관 기간 가정이 포함되어야 합니다.',
      severity: 'High',
      evaluation_type: 'llm',
      related_sections: ['assumptions', 'architecture', 'cost_breakdown'],
      pass_criteria_en: ['Data volume and retention assumptions are documented.'],
      pass_criteria_kr: ['데이터 규모와 보관 가정이 문서화되어 있습니다.'],
      warning_criteria_en: ['Data source is described but volume or retention is missing.'],
      warning_criteria_kr: ['데이터 소스는 설명되었으나 규모 또는 보관 기간이 없습니다.'],
      fail_criteria_en: ['No data volume or retention assumption is provided.'],
      fail_criteria_kr: ['데이터 규모 또는 보관 가정이 제공되지 않았습니다.'],
      recommendation_template_en:
        'Add document count, data size, vector index size, and retention period.',
      recommendation_template_kr: '문서 수, 데이터 크기, 벡터 인덱스 크기, 보관 기간을 추가하십시오.',
      source: 'SOW Pre-Submission Checklist',
    },
    {
      rule_id: 'growth_assumption_exists',
      enabled: true,
      custom: false,
      category_en: 'Production Usage & Cost Assumptions',
      category_kr: '프로덕션 사용량 및 비용 가정',
      title_en: 'Growth assumption is documented',
      title_kr: '성장률 또는 확장 가정이 문서화되었는가',
      description_en: 'The document should describe expected usage growth or rollout-driven growth.',
      description_kr: '문서에는 예상 사용량 증가율 또는 Rollout 기반 확장 가정이 포함되어야 합니다.',
      severity: 'Medium',
      evaluation_type: 'llm',
      related_sections: ['assumptions', 'deployment', 'cost_breakdown'],
      pass_criteria_en: ['Growth rate or rollout growth assumption is provided.'],
      pass_criteria_kr: ['성장률 또는 Rollout 기반 증가 가정이 제공되어 있습니다.'],
      warning_criteria_en: ['Growth is implied but not quantified.'],
      warning_criteria_kr: ['성장은 암시되어 있으나 정량화되지 않았습니다.'],
      fail_criteria_en: ['No growth assumption is provided.'],
      fail_criteria_kr: ['성장률 또는 확장 가정이 제공되지 않았습니다.'],
      recommendation_template_en:
        'Add monthly growth rate or phased rollout growth assumptions.',
      recommendation_template_kr: '월간 성장률 또는 단계별 Rollout 증가 가정을 추가하십시오.',
      source: 'SOW Pre-Submission Checklist',
    },
    {
      rule_id: 'cost_assumption_detailed',
      enabled: true,
      custom: false,
      category_en: 'Production Usage & Cost Assumptions',
      category_kr: '프로덕션 사용량 및 비용 가정',
      title_en: 'Cost assumptions are detailed by service and usage',
      title_kr: '서비스/사용량별 비용 가정이 구체적인가',
      description_en:
        'Cost estimates should be tied to usage assumptions and service-level details.',
      description_kr: '비용 산정은 사용량 가정 및 서비스별 상세 내역과 연결되어야 합니다.',
      severity: 'High',
      evaluation_type: 'hybrid',
      related_sections: ['cost_breakdown'],
      pass_criteria_en: ['Cost is documented by service and usage basis.'],
      pass_criteria_kr: ['서비스별 및 사용량 기준으로 비용이 문서화되어 있습니다.'],
      warning_criteria_en: ['Cost is listed but assumptions are weak.'],
      warning_criteria_kr: ['비용은 나열되어 있으나 가정이 약합니다.'],
      fail_criteria_en: ['No detailed cost assumptions are provided.'],
      fail_criteria_kr: ['상세 비용 가정이 제공되지 않았습니다.'],
      recommendation_template_en:
        'Add service-level cost assumptions including volume, unit, and calculation basis.',
      recommendation_template_kr:
        '서비스별 사용량, 단위, 계산 기준을 포함한 비용 가정을 추가하십시오.',
      source: 'SOW Pre-Submission Checklist',
    },
    {
      rule_id: 'architecture_diagram_exists',
      enabled: true,
      custom: false,
      category_en: 'Architecture & Service Sizing',
      category_kr: '아키텍처 및 서비스 사이징',
      title_en: 'Architecture diagram is included',
      title_kr: '아키텍처 다이어그램이 포함되어 있는가',
      description_en:
        'The Project Plan/SOW should include an architecture diagram for the use case.',
      description_kr: 'Project Plan/SOW에는 Use Case에 대한 아키텍처 다이어그램이 포함되어야 합니다.',
      severity: 'Critical',
      evaluation_type: 'static',
      related_sections: ['architecture'],
      pass_criteria_en: ['Architecture diagram or diagram artifact exists.'],
      pass_criteria_kr: ['아키텍처 다이어그램 또는 다이어그램 아티팩트가 존재합니다.'],
      warning_criteria_en: ['Architecture is described in text but diagram is missing.'],
      warning_criteria_kr: ['아키텍처가 텍스트로 설명되었으나 다이어그램이 없습니다.'],
      fail_criteria_en: ['No architecture diagram or equivalent artifact is provided.'],
      fail_criteria_kr: ['아키텍처 다이어그램 또는 동등한 아티팩트가 제공되지 않았습니다.'],
      recommendation_template_en:
        'Add an architecture diagram showing AWS services, data flow, and integration points.',
      recommendation_template_kr:
        'AWS 서비스, 데이터 흐름, 연동 지점을 보여주는 아키텍처 다이어그램을 추가하십시오.',
      source: 'GenAIIC PLD Funding Guide / SOW Checklist',
    },
    {
      rule_id: 'architecture_services_defined',
      enabled: true,
      custom: false,
      category_en: 'Architecture & Service Sizing',
      category_kr: '아키텍처 및 서비스 사이징',
      title_en: 'AWS services and their roles are clearly described',
      title_kr: 'AWS 서비스와 역할이 명확히 설명되었는가',
      description_en:
        'The document should describe each key AWS service and why it is used.',
      description_kr: '문서에는 주요 AWS 서비스와 사용 이유가 설명되어야 합니다.',
      severity: 'High',
      evaluation_type: 'llm',
      related_sections: ['architecture'],
      pass_criteria_en: ['Key AWS services and purposes are clearly described.'],
      pass_criteria_kr: ['주요 AWS 서비스와 목적이 명확히 설명되어 있습니다.'],
      warning_criteria_en: ['Services are listed but roles are unclear.'],
      warning_criteria_kr: ['서비스는 나열되었으나 역할이 불명확합니다.'],
      fail_criteria_en: ['No clear AWS service description is provided.'],
      fail_criteria_kr: ['명확한 AWS 서비스 설명이 제공되지 않았습니다.'],
      recommendation_template_en: 'Add service-by-service purpose and role descriptions.',
      recommendation_template_kr: '서비스별 목적과 역할 설명을 추가하십시오.',
      source: 'SOW Pre-Submission Checklist',
    },
    {
      rule_id: 'architecture_cost_alignment',
      enabled: true,
      custom: false,
      category_en: 'Architecture & Service Sizing',
      category_kr: '아키텍처 및 서비스 사이징',
      title_en: 'Architecture services match cost estimate services',
      title_kr: '아키텍처 서비스와 비용 산정 서비스가 일치하는가',
      description_en:
        'All services in the architecture should be reflected in cost estimates, and cost items should appear in architecture.',
      description_kr:
        '아키텍처에 있는 모든 서비스는 비용 산정에 반영되어야 하며, 비용 항목도 아키텍처에 나타나야 합니다.',
      severity: 'Critical',
      evaluation_type: 'hybrid',
      related_sections: ['architecture', 'cost_breakdown'],
      pass_criteria_en: ['Architecture services and cost services are aligned.'],
      pass_criteria_kr: ['아키텍처 서비스와 비용 산정 서비스가 일치합니다.'],
      warning_criteria_en: ['Minor services are missing from one side.'],
      warning_criteria_kr: ['일부 부가 서비스가 한쪽에서 누락되었습니다.'],
      fail_criteria_en: ['Major service mismatch exists between architecture and cost estimate.'],
      fail_criteria_kr: ['아키텍처와 비용 산정 사이에 주요 서비스 불일치가 있습니다.'],
      recommendation_template_en:
        'Align architecture services and cost estimate line items, especially Bedrock, OpenSearch, Redshift, Redis, Kafka/MSK, NAT Gateway, and storage.',
      recommendation_template_kr:
        'Bedrock, OpenSearch, Redshift, Redis, Kafka/MSK, NAT Gateway, Storage 등 주요 서비스를 기준으로 아키텍처와 비용 항목을 정합화하십시오.',
      source: 'SOW Pre-Submission Checklist',
    },
    {
      rule_id: 'service_sizing_rationale',
      enabled: true,
      custom: false,
      category_en: 'Architecture & Service Sizing',
      category_kr: '아키텍처 및 서비스 사이징',
      title_en: 'Key service sizing rationale is documented',
      title_kr: '주요 서비스의 사이징 근거가 문서화되었는가',
      description_en:
        'The document should justify service sizing decisions using workload, data volume, latency, accuracy, or scale needs.',
      description_kr:
        '문서에는 워크로드, 데이터 규모, 지연시간, 정확도, 확장 요구사항을 기반으로 서비스 사이징 근거가 포함되어야 합니다.',
      severity: 'High',
      evaluation_type: 'llm',
      related_sections: ['architecture', 'cost_breakdown'],
      pass_criteria_en: ['Sizing rationale is provided for major services.'],
      pass_criteria_kr: ['주요 서비스에 대한 사이징 근거가 제공되어 있습니다.'],
      warning_criteria_en: ['Sizing is present but rationale is weak.'],
      warning_criteria_kr: ['사이징은 있으나 근거가 약합니다.'],
      fail_criteria_en: ['No sizing rationale is provided.'],
      fail_criteria_kr: ['사이징 근거가 제공되지 않았습니다.'],
      recommendation_template_en:
        'Add sizing rationale for major services using workload, data, latency, accuracy, and scale assumptions.',
      recommendation_template_kr:
        '워크로드, 데이터, 지연시간, 정확도, 확장 가정을 활용해 주요 서비스 사이징 근거를 추가하십시오.',
      source: 'SOW Pre-Submission Checklist',
    },
    {
      rule_id: 'capacity_mode_explained',
      enabled: true,
      custom: false,
      category_en: 'Architecture & Service Sizing',
      category_kr: '아키텍처 및 서비스 사이징',
      title_en: 'Capacity mode choices are explained',
      title_kr: '용량 모드 선택 이유가 설명되었는가',
      description_en:
        'Capacity mode choices such as on-demand, provisioned, or autoscaling should be explained where relevant.',
      description_kr:
        '온디맨드, 프로비저닝, 오토스케일링 등 용량 모드 선택 이유가 관련 서비스에 대해 설명되어야 합니다.',
      severity: 'Medium',
      evaluation_type: 'llm',
      related_sections: ['architecture', 'cost_breakdown'],
      pass_criteria_en: ['Capacity mode decisions are explained for relevant services.'],
      pass_criteria_kr: ['관련 서비스에 대한 용량 모드 선택 이유가 설명되어 있습니다.'],
      warning_criteria_en: ['Capacity mode is implied but not explained.'],
      warning_criteria_kr: ['용량 모드가 암시되어 있으나 설명이 부족합니다.'],
      fail_criteria_en: ['No capacity mode rationale is provided.'],
      fail_criteria_kr: ['용량 모드 선택 근거가 제공되지 않았습니다.'],
      recommendation_template_en:
        'Explain why each major service uses on-demand, provisioned, or autoscaling capacity.',
      recommendation_template_kr:
        '각 주요 서비스가 온디맨드, 프로비저닝, 오토스케일링 중 어떤 용량 모드를 사용하는지와 이유를 설명하십시오.',
      source: 'SOW Pre-Submission Checklist',
    },
    {
      rule_id: 'scope_phase_deliverables',
      enabled: true,
      custom: false,
      category_en: 'Scope of Work',
      category_kr: '작업 범위',
      title_en: 'SOW phases and deliverables are documented',
      title_kr: 'SOW 단계와 산출물이 문서화되었는가',
      description_en: 'The document should include clear phases, tasks, and deliverables.',
      description_kr: '문서에는 명확한 단계, 작업, 산출물이 포함되어야 합니다.',
      severity: 'High',
      evaluation_type: 'llm',
      related_sections: ['scope_of_work', 'milestones'],
      pass_criteria_en: ['Phases, tasks, and deliverables are clearly documented.'],
      pass_criteria_kr: ['단계, 작업, 산출물이 명확히 문서화되어 있습니다.'],
      warning_criteria_en: ['Phases exist but deliverables are weak.'],
      warning_criteria_kr: ['단계는 있으나 산출물이 약합니다.'],
      fail_criteria_en: ['No clear SOW phases or deliverables are provided.'],
      fail_criteria_kr: ['명확한 SOW 단계 또는 산출물이 제공되지 않았습니다.'],
      recommendation_template_en:
        'Add phase-level tasks and deliverables such as Analysis/Design, Development, Deployment, and Stabilization.',
      recommendation_template_kr:
        'Analysis/Design, Development, Deployment, Stabilization 등 단계별 작업과 산출물을 추가하십시오.',
      source: 'SOW Pre-Submission Checklist',
    },
    {
      rule_id: 'deployment_rollout_plan',
      enabled: true,
      custom: false,
      category_en: 'Deployment & Scaling Plan',
      category_kr: '배포 및 확장 계획',
      title_en: 'Phased rollout plan is documented',
      title_kr: '단계별 Rollout 계획이 문서화되었는가',
      description_en: 'The document should describe pilot-to-production rollout stages.',
      description_kr: '문서에는 파일럿에서 프로덕션까지의 단계별 Rollout 계획이 설명되어야 합니다.',
      severity: 'Medium',
      evaluation_type: 'llm',
      related_sections: ['milestones', 'acceptance', 'assumptions'],
      pass_criteria_en: ['Rollout phases and timeline are documented.'],
      pass_criteria_kr: ['Rollout 단계와 일정이 문서화되어 있습니다.'],
      warning_criteria_en: ['Deployment is mentioned but rollout is vague.'],
      warning_criteria_kr: ['배포는 언급되었으나 Rollout이 모호합니다.'],
      fail_criteria_en: ['No rollout plan is provided.'],
      fail_criteria_kr: ['Rollout 계획이 제공되지 않았습니다.'],
      recommendation_template_en:
        'Add staged rollout from pilot users to production users with dates or months.',
      recommendation_template_kr:
        '파일럿 사용자에서 프로덕션 사용자로 확대되는 단계별 Rollout 일정 또는 기간을 추가하십시오.',
      source: 'SOW Pre-Submission Checklist',
    },
    {
      rule_id: 'scaling_strategy_exists',
      enabled: true,
      custom: false,
      category_en: 'Deployment & Scaling Plan',
      category_kr: '배포 및 확장 계획',
      title_en: 'Scaling strategy is documented',
      title_kr: '확장 전략이 문서화되었는가',
      description_en: 'The document should describe how the system scales with traffic, users, or workload.',
      description_kr: '문서에는 트래픽, 사용자, 워크로드 증가에 따른 확장 전략이 설명되어야 합니다.',
      severity: 'Medium',
      evaluation_type: 'llm',
      related_sections: ['architecture', 'assumptions'],
      pass_criteria_en: ['Autoscaling or capacity expansion strategy is documented.'],
      pass_criteria_kr: ['오토스케일링 또는 용량 확장 전략이 문서화되어 있습니다.'],
      warning_criteria_en: ['Scaling is mentioned without clear threshold or method.'],
      warning_criteria_kr: ['확장이 언급되었으나 임계치 또는 방법이 명확하지 않습니다.'],
      fail_criteria_en: ['No scaling strategy is provided.'],
      fail_criteria_kr: ['확장 전략이 제공되지 않았습니다.'],
      recommendation_template_en:
        'Add scaling strategy such as autoscaling thresholds, capacity ranges, or growth-driven scaling.',
      recommendation_template_kr: '오토스케일링 임계치, 용량 범위, 성장 기반 확장 전략을 추가하십시오.',
      source: 'SOW Pre-Submission Checklist',
    },
    {
      rule_id: 'budget_by_phase_exists',
      enabled: true,
      custom: false,
      category_en: 'Deployment & Scaling Plan',
      category_kr: '배포 및 확장 계획',
      title_en: 'Budget or cost by rollout phase is documented',
      title_kr: '단계별 예산 또는 비용 전망이 문서화되었는가',
      description_en:
        'The document should show how cost changes across rollout phases when applicable.',
      description_kr: '해당되는 경우 Rollout 단계별 비용 변화가 문서화되어야 합니다.',
      severity: 'Medium',
      evaluation_type: 'llm',
      related_sections: ['cost_breakdown', 'milestones'],
      pass_criteria_en: ['Budget or cost by rollout phase is documented.'],
      pass_criteria_kr: ['단계별 예산 또는 비용 전망이 문서화되어 있습니다.'],
      warning_criteria_en: ['Total cost exists but phase-level budget is missing.'],
      warning_criteria_kr: ['총 비용은 있으나 단계별 예산이 없습니다.'],
      fail_criteria_en: ['No phase-level budget or cost outlook is provided.'],
      fail_criteria_kr: ['단계별 예산 또는 비용 전망이 제공되지 않았습니다.'],
      recommendation_template_en:
        'Add cost outlook by rollout phase if production scale is part of the proposal.',
      recommendation_template_kr:
        'Production 확장이 포함된 경우 Rollout 단계별 비용 전망을 추가하십시오.',
      source: 'SOW Pre-Submission Checklist',
    },
    {
      rule_id: 'risk_assessment_required',
      enabled: true,
      custom: false,
      category_en: 'Risk Assessment & Governance',
      category_kr: '리스크 평가 및 거버넌스',
      title_en: 'Risk assessment is completed for regulated or high-risk use cases',
      title_kr: '규제/고위험 Use Case에 대한 리스크 평가가 완료되었는가',
      description_en: 'Regulated or high-risk use cases should include risk and governance assessment.',
      description_kr: '규제 산업 또는 고위험 Use Case에는 리스크 및 거버넌스 평가가 포함되어야 합니다.',
      severity: 'High',
      evaluation_type: 'llm',
      related_sections: ['assumptions', 'architecture', 'acceptance'],
      pass_criteria_en: ['Risk assessment is documented or explicitly not applicable.'],
      pass_criteria_kr: ['리스크 평가가 문서화되었거나 명확히 해당 없음으로 설명되어 있습니다.'],
      warning_criteria_en: ['Risk is mentioned but controls are weak.'],
      warning_criteria_kr: ['리스크는 언급되었으나 통제가 약합니다.'],
      fail_criteria_en: ['High-risk use case has no risk assessment.'],
      fail_criteria_kr: ['고위험 Use Case임에도 리스크 평가가 없습니다.'],
      recommendation_template_en:
        'Add risk assessment for regulated/high-risk AI use cases, or state why it is not applicable.',
      recommendation_template_kr:
        '규제/고위험 AI Use Case에 대한 리스크 평가를 추가하거나 해당 없음 사유를 명시하십시오.',
      source: 'SOW Pre-Submission Checklist',
    },
    {
      rule_id: 'human_in_loop_defined',
      enabled: true,
      custom: false,
      category_en: 'Risk Assessment & Governance',
      category_kr: '리스크 평가 및 거버넌스',
      title_en: 'Human-in-the-loop control is documented when needed',
      title_kr: '필요 시 Human-in-the-loop 통제가 문서화되었는가',
      description_en:
        'High-impact recommendations or decisions should include human review controls where needed.',
      description_kr:
        '중요한 추천 또는 의사결정에는 필요한 경우 사람의 검토 통제가 포함되어야 합니다.',
      severity: 'High',
      evaluation_type: 'llm',
      related_sections: ['architecture', 'acceptance', 'assumptions'],
      pass_criteria_en: ['Human review process is documented where applicable.'],
      pass_criteria_kr: ['해당되는 경우 사람의 검토 프로세스가 문서화되어 있습니다.'],
      warning_criteria_en: ['Human review is implied but not operationalized.'],
      warning_criteria_kr: ['사람의 검토가 암시되어 있으나 운영 방식이 없습니다.'],
      fail_criteria_en: ['High-risk AI decision flow has no human review control.'],
      fail_criteria_kr: ['고위험 AI 의사결정 흐름에 사람의 검토 통제가 없습니다.'],
      recommendation_template_en:
        'Add human-in-the-loop review process for high-risk recommendations or decisions.',
      recommendation_template_kr:
        '고위험 추천 또는 의사결정에 대한 Human-in-the-loop 검토 프로세스를 추가하십시오.',
      source: 'SOW Pre-Submission Checklist',
    },
    {
      rule_id: 'audit_logging_defined',
      enabled: true,
      custom: false,
      category_en: 'Risk Assessment & Governance',
      category_kr: '리스크 평가 및 거버넌스',
      title_en: 'Audit logging requirement is documented',
      title_kr: '감사 로그 요건이 문서화되었는가',
      description_en:
        'The document should describe audit logging requirements for AI decisions or critical workflows when relevant.',
      description_kr:
        '관련되는 경우 AI 판단 또는 중요 업무 흐름에 대한 감사 로그 요건이 설명되어야 합니다.',
      severity: 'Medium',
      evaluation_type: 'llm',
      related_sections: ['architecture', 'assumptions'],
      pass_criteria_en: ['Audit logging requirement is documented or explicitly not applicable.'],
      pass_criteria_kr: ['감사 로그 요건이 문서화되었거나 명확히 해당 없음으로 설명되어 있습니다.'],
      warning_criteria_en: ['Logging is mentioned but audit retention or scope is unclear.'],
      warning_criteria_kr: ['로그는 언급되었으나 감사 보관 또는 범위가 불명확합니다.'],
      fail_criteria_en: ['No audit logging requirement is provided for relevant use cases.'],
      fail_criteria_kr: ['관련 Use Case에 대한 감사 로그 요건이 제공되지 않았습니다.'],
      recommendation_template_en:
        'Add audit logging scope, retention, and review requirement where applicable.',
      recommendation_template_kr:
        '해당되는 경우 감사 로그 범위, 보관 기간, 검토 요건을 추가하십시오.',
      source: 'SOW Pre-Submission Checklist',
    },
    {
      rule_id: 'compliance_requirements_defined',
      enabled: true,
      custom: false,
      category_en: 'Risk Assessment & Governance',
      category_kr: '리스크 평가 및 거버넌스',
      title_en: 'Compliance requirements are documented',
      title_kr: '컴플라이언스 요건이 문서화되었는가',
      description_en:
        'The document should describe compliance requirements such as PIPA, GDPR, HIPAA, PCI-DSS where applicable.',
      description_kr:
        '해당되는 경우 PIPA, GDPR, HIPAA, PCI-DSS 등 컴플라이언스 요건이 설명되어야 합니다.',
      severity: 'High',
      evaluation_type: 'llm',
      related_sections: ['assumptions', 'architecture'],
      pass_criteria_en: [
        'Relevant compliance requirements are documented or explicitly not applicable.',
      ],
      pass_criteria_kr: [
        '관련 컴플라이언스 요건이 문서화되었거나 명확히 해당 없음으로 설명되어 있습니다.',
      ],
      warning_criteria_en: ['Compliance is mentioned but requirements are incomplete.'],
      warning_criteria_kr: ['컴플라이언스가 언급되었으나 요건이 불완전합니다.'],
      fail_criteria_en: ['Regulated use case has no compliance consideration.'],
      fail_criteria_kr: ['규제 대상 Use Case임에도 컴플라이언스 고려사항이 없습니다.'],
      recommendation_template_en: 'Add applicable compliance requirements and data protection controls.',
      recommendation_template_kr: '적용 가능한 컴플라이언스 요건과 데이터 보호 통제를 추가하십시오.',
      source: 'SOW Pre-Submission Checklist',
    },
    {
      rule_id: 'model_validation_plan_exists',
      enabled: true,
      custom: false,
      category_en: 'Risk Assessment & Governance',
      category_kr: '리스크 평가 및 거버넌스',
      title_en: 'Model accuracy/testing plan is documented',
      title_kr: '모델 정확도/검증 계획이 문서화되었는가',
      description_en:
        'The document should include testing or validation plan for model accuracy, safety, or fairness where applicable.',
      description_kr:
        '문서에는 해당되는 경우 모델 정확도, 안전성, 공정성 검증 계획이 포함되어야 합니다.',
      severity: 'Medium',
      evaluation_type: 'llm',
      related_sections: ['success_criteria', 'acceptance'],
      pass_criteria_en: ['Model validation plan and target metrics are documented.'],
      pass_criteria_kr: ['모델 검증 계획과 목표 지표가 문서화되어 있습니다.'],
      warning_criteria_en: ['Validation is mentioned but test set, metric, or process is weak.'],
      warning_criteria_kr: ['검증은 언급되었으나 테스트셋, 지표, 절차가 약합니다.'],
      fail_criteria_en: ['No model validation or testing plan is provided.'],
      fail_criteria_kr: ['모델 검증 또는 테스트 계획이 제공되지 않았습니다.'],
      recommendation_template_en:
        'Add validation dataset, metric, target threshold, and review process.',
      recommendation_template_kr:
        '검증 데이터셋, 지표, 목표 임계치, 검토 절차를 추가하십시오.',
      source: 'SOW Pre-Submission Checklist',
    },
    {
      rule_id: 'cross_document_consistency',
      enabled: true,
      custom: false,
      category_en: 'Final Check',
      category_kr: '최종 점검',
      title_en: 'Cross-document consistency is verified',
      title_kr: '문서 간 모순이 없는지 교차 검증되었는가',
      description_en:
        'The document should not contain contradictions across use case, architecture, cost, scope, and timeline.',
      description_kr: 'Use Case, 아키텍처, 비용, 범위, 일정 사이에 모순이 없어야 합니다.',
      severity: 'High',
      evaluation_type: 'llm',
      related_sections: [
        'executive_summary',
        'scope_of_work',
        'architecture',
        'cost_breakdown',
        'milestones',
      ],
      pass_criteria_en: ['No major contradiction is found across sections.'],
      pass_criteria_kr: ['섹션 간 주요 모순이 발견되지 않습니다.'],
      warning_criteria_en: ['Minor inconsistency exists but does not block submission.'],
      warning_criteria_kr: ['작은 불일치가 있으나 제출을 막을 수준은 아닙니다.'],
      fail_criteria_en: ['Major contradiction exists across sections.'],
      fail_criteria_kr: ['섹션 간 주요 모순이 존재합니다.'],
      recommendation_template_en:
        'Align use case, architecture, cost, scope, resource plan, and timeline.',
      recommendation_template_kr:
        'Use Case, 아키텍처, 비용, 범위, 리소스 계획, 일정을 정합화하십시오.',
      source: 'SOW Pre-Submission Checklist',
    },
    {
      rule_id: 'apfp_submission_info_exists',
      enabled: true,
      custom: false,
      category_en: 'APFP',
      category_kr: 'APFP',
      title_en: 'APFP submission information is prepared',
      title_kr: 'APFP 제출 정보가 준비되었는가',
      description_en:
        'The document should support APFP submission fields such as project name, business description, dates, currency, total cost, and requested funding amount.',
      description_kr:
        '문서는 프로젝트명, 비즈니스 설명, 일정, 통화, 총 비용, 요청 펀딩 금액 등 APFP 제출 정보를 뒷받침해야 합니다.',
      severity: 'Medium',
      evaluation_type: 'llm',
      related_sections: ['cover', 'executive_summary', 'milestones', 'cost_breakdown'],
      pass_criteria_en: ['Key APFP submission information is present.'],
      pass_criteria_kr: ['주요 APFP 제출 정보가 존재합니다.'],
      warning_criteria_en: ['Some APFP fields are present but incomplete.'],
      warning_criteria_kr: ['일부 APFP 필드는 있으나 불완전합니다.'],
      fail_criteria_en: ['APFP submission information is mostly missing.'],
      fail_criteria_kr: ['APFP 제출 정보가 대부분 누락되었습니다.'],
      recommendation_template_en:
        'Add APFP-ready project name, business description, start/end dates, total cost, and requested funding amount.',
      recommendation_template_kr:
        'APFP 제출용 프로젝트명, 비즈니스 설명, 시작/종료일, 총 비용, 요청 펀딩 금액을 추가하십시오.',
      source: 'GenAIIC PLD Funding Guide',
    },
    {
      rule_id: 'claim_timeline_awareness',
      enabled: true,
      custom: false,
      category_en: 'APFP',
      category_kr: 'APFP',
      title_en: 'Claim timeline and completion evidence requirements are understood',
      title_kr: 'Claim 기한과 완료 증빙 요건이 반영되었는가',
      description_en:
        'The project should consider claim submission timing and completion sign-off requirements after project completion.',
      description_kr:
        '프로젝트 완료 후 Claim 제출 기한과 완료 증빙/Sign-off 요건을 고려해야 합니다.',
      severity: 'Low',
      evaluation_type: 'llm',
      related_sections: ['milestones', 'acceptance'],
      pass_criteria_en: ['Claim or completion evidence requirements are mentioned where relevant.'],
      pass_criteria_kr: ['관련되는 경우 Claim 또는 완료 증빙 요건이 언급되어 있습니다.'],
      warning_criteria_en: ['Completion is mentioned but claim timing is not considered.'],
      warning_criteria_kr: ['완료는 언급되었으나 Claim 기한은 고려되지 않았습니다.'],
      fail_criteria_en: ['No claim or completion evidence awareness is shown.'],
      fail_criteria_kr: ['Claim 또는 완료 증빙 요건에 대한 고려가 없습니다.'],
      recommendation_template_en:
        'Add completion sign-off and claim timing awareness if needed for APFP process.',
      recommendation_template_kr:
        'APFP 절차상 필요한 경우 완료 Sign-off와 Claim 기한 고려사항을 추가하십시오.',
      source: 'GenAIIC PLD Funding Guide',
    },
  ],
}

/**
 * Mapping from legacy backend issue codes (in run_submission_lint) to
 * new rule_ids. Used by the adapter to build a rule matrix from older
 * issue-based responses until the backend emits rule_evaluations[].
 */
export const LEGACY_ISSUE_TO_RULE_ID: Record<string, string> = {
  BEDROCK_EVIDENCE_MISSING: 'bedrock_included',
  ARR_MISSING: 'total_arr_documented',
  SOW_COST_MISSING: 'sow_cost_breakdown_exists',
  CALCULATOR_URL_MISSING: 'calculator_link_exists',
  ARCHITECTURE_INCOMPLETE: 'architecture_services_defined',
  ARCHITECTURE_OVERVIEW_MISSING: 'service_sizing_rationale',
  BUSINESS_CASE_MISSING: 'business_problem_defined',
  RISK_GOVERNANCE_MISSING: 'risk_assessment_required',
  CUSTOMER_MISSING: 'apfp_submission_info_exists',
  EXECUTIVE_SUMMARY_INCOMPLETE: 'business_problem_defined',
  STAKEHOLDERS_INCOMPLETE: 'executive_sponsor_exists',
  SUCCESS_CRITERIA_INCOMPLETE: 'success_criteria_measurable',
  ASSUMPTIONS_INCOMPLETE: 'cost_assumption_detailed',
  SCOPE_OF_WORK_INCOMPLETE: 'scope_phase_deliverables',
  MILESTONES_INCOMPLETE: 'deployment_rollout_plan',
  COST_BREAKDOWN_INCOMPLETE: 'architecture_cost_alignment',
  ACCEPTANCE_INCOMPLETE: 'model_validation_plan_exists',
  RESOURCES_COST_ESTIMATES_INCOMPLETE: 'sow_cost_breakdown_exists',
  COVER_INCOMPLETE: 'apfp_submission_info_exists',
}

export const SECTION_LABELS: Record<string, { kr: string; en: string }> = {
  cover: { kr: '표지', en: 'Cover' },
  executive_summary: { kr: 'Executive Summary', en: 'Executive Summary' },
  stakeholders: { kr: '이해관계자', en: 'Stakeholders' },
  success_criteria: { kr: '성공 기준', en: 'Success Criteria' },
  assumptions: { kr: '가정사항', en: 'Assumptions' },
  scope_of_work: { kr: '작업 범위', en: 'Scope of Work' },
  architecture: { kr: '아키텍처', en: 'Architecture' },
  milestones: { kr: '마일스톤', en: 'Milestones' },
  cost_breakdown: { kr: '비용 분석', en: 'Cost Breakdown' },
  acceptance: { kr: '인수 기준', en: 'Acceptance' },
  resources_cost_estimates: { kr: '리소스 비용', en: 'Resources & Cost Estimates' },
  deployment: { kr: '배포', en: 'Deployment' },
  meta: { kr: '메타', en: 'Meta' },
}

export function sectionLabel(key: string, lang: 'ko' | 'en'): string {
  const entry = SECTION_LABELS[key]
  if (!entry) return key
  return lang === 'ko' ? entry.kr : entry.en
}

export function collectCategories(rules: RuleDefinition[]): Array<{ key: string; kr: string; en: string }> {
  const seen = new Map<string, { kr: string; en: string }>()
  for (const r of rules) {
    if (!seen.has(r.category_en)) {
      seen.set(r.category_en, { kr: r.category_kr, en: r.category_en })
    }
  }
  return Array.from(seen.entries()).map(([key, v]) => ({ key, ...v }))
}
