// --- Writing Guide Types ---

export interface GuideBlock {
  heading: string
  items: string[]
}

export interface DocumentGuide {
  title: string
  purpose: string
  blocks: GuideBlock[]
  useful_prompts?: string[]
  tips: string[]
}

// --- All 11 Section Writing Guides (Korean) ---

export const DOCUMENT_GUIDES: Record<string, DocumentGuide> = {
  // Requirement 25: Cover
  cover: {
    title: 'Cover 작성 가이드',
    purpose:
      '표지에는 DOCX 문서에 직접 표시되는 핵심 식별 정보를 입력합니다. 고객사, 파트너, 날짜, 프로젝트명은 문서 표지와 Export 결과에 직접 반영됩니다.',
    blocks: [
      {
        heading: '필수 항목 (Required Fields)',
        items: [
          '고객사: 문서 대상 고객사명입니다. 예: 광동제약, Hanjin, E-mart',
          '파트너: 기본값은 MegazoneCloud입니다.',
          '날짜: 문서 기준일 또는 제출일입니다. 예: 2026-04-26',
          '프로젝트명: 문서 제목이자 프로젝트명입니다.',
        ],
      },
      {
        heading: '선택 항목 (Optional Fields)',
        items: [
          '산업군: AI가 산업 특화 표현을 생성하는 데 사용합니다.',
          '프로젝트 배경: Executive Summary 작성 품질을 높입니다.',
          '주요 목표: Success Criteria와 Scope 작성에 활용됩니다.',
          '예상 AWS 서비스: Architecture와 Cost Breakdown 작성에 활용됩니다.',
          '기간/예산 메모: Milestones와 Cost 작성에 활용됩니다.',
        ],
      },
    ],
    tips: [
      '필수값은 DOCX 표지에 직접 표시됩니다.',
      '옵션값은 표지에는 직접 표시되지 않을 수 있지만, AI가 다른 섹션을 더 정확하게 작성하는 데 사용됩니다.',
      '샘플값은 placeholder로만 보여주고 실제 값으로 저장하지 않습니다.',
    ],
  },

  // Requirement 26: Executive Summary
  executive_summary: {
    title: 'Executive Summary 작성 가이드',
    purpose:
      '고객이 누구인지, 어떤 문제를 가지고 있는지, 이 PoC가 어떤 방식으로 해결할지 요약합니다. AWS 펀딩 검토자는 이 섹션을 통해 비즈니스 가치와 프로젝트 필요성을 빠르게 판단합니다.',
    blocks: [
      {
        heading: '권장 구조 (Recommended Structure)',
        items: [
          '고객 소개: 고객사의 산업, 규모, 주요 사업을 간단히 설명합니다.',
          '현재 문제점: 수작업, 검색 지연, 데이터 분산, 비용 증가, 보안 우려 등 현재 pain point를 적습니다.',
          '제안 솔루션: Amazon Bedrock, RAG, OpenSearch, S3 등으로 어떤 해결책을 제안하는지 설명합니다.',
          'PoC 목표: PoC에서 검증할 기능, 성능, 비용, 보안 목표를 적습니다.',
          '진행 방식: 몇 개 phase로 진행되는지 간단히 설명합니다.',
          '비즈니스 효과: 업무 시간 절감, 정확도 향상, 비용 절감, 사용자 만족도 향상 등을 적습니다.',
        ],
      },
    ],
    useful_prompts: [
      '이 고객의 현재 문제점과 PoC 목표를 기반으로 Executive Summary 초안을 작성해줘.',
      '비즈니스 가치와 AWS 사용 이유가 잘 드러나도록 Executive Summary를 보강해줘.',
      '현재 문장을 APN Project Plan 스타일의 영어 문서로 다듬어줘.',
    ],
    tips: [
      '단순 기술 설명만 쓰지 말고 비즈니스 가치와 고객 pain point를 함께 적습니다.',
      '정량 목표가 있으면 포함합니다. 예: 검색 시간 30분 → 2분, 정확도 90%, 응답 시간 3초 이하',
      'AWS 사용 이유와 GenAI 도입 이유가 드러나야 합니다.',
    ],
  },

  // Requirement 27: Stakeholders
  stakeholders: {
    title: 'Stakeholders 작성 가이드',
    purpose:
      '프로젝트 의사결정자, 고객 담당자, 파트너 수행팀, 에스컬레이션 담당자를 정리합니다. AWS 제출 문서에서는 누가 후원하고, 누가 수행하고, 누가 승인하는지 명확해야 합니다.',
    blocks: [
      {
        heading: '권장 섹션 (Recommended Sections)',
        items: [
          'Partner Executive Sponsor: 파트너 측 임원 후원자입니다. 기본값으로 James, Kong / CAIO / Head of AI Business / jameskong@megazone.com 을 제공합니다.',
          'Project Stakeholders: 고객 또는 관련 조직의 주요 이해관계자입니다.',
          'Partner Project Team: 실제 프로젝트를 수행하는 파트너 팀입니다.',
          'Project Escalation Contacts: 이슈 발생 시 에스컬레이션할 담당자입니다.',
        ],
      },
    ],
    tips: [
      '이메일 또는 연락처는 가능한 한 입력합니다.',
      'Title, Role, Stakeholder For는 드롭다운에서 선택 후 수정할 수 있어야 합니다.',
      '사람 이름은 프로젝트마다 다르므로 기본 자동 입력은 Partner Executive Sponsor 1명만 사용합니다.',
      '나머지 인원은 드롭다운 또는 직접 입력으로 추가합니다.',
    ],
  },

  // Requirement 28: Success Criteria / KPIs
  success_criteria: {
    title: 'Success Criteria / KPIs 작성 가이드',
    purpose:
      'PoC가 성공했다고 판단할 수 있는 기준을 정의합니다. 가능하면 정량 목표와 검증 방법을 포함해야 합니다.',
    blocks: [
      {
        heading: '권장 카테고리 (Recommended Categories)',
        items: [
          'Strategy Development & Planning',
          'Technical Framework Design',
          'Implementation Roadmap',
          'Knowledge Transfer',
          'Project Objective',
          'Security and Data Protection Perspective',
          'RAG Environment and Response Quality Perspective',
          'Cost Effectiveness Perspective',
        ],
      },
      {
        heading: '예시 (Examples)',
        items: [
          '응답 정확도 90% 이상 달성',
          '평균 응답 시간 3초 이하',
          '수작업 처리 시간 30% 이상 감소',
          'RAG 기반 문서 검색 정확도 90% 이상',
          '핵심 시나리오 테스트 통과율 100%',
          '월 예상 AWS 비용 범위 내 운영 가능성 검증',
        ],
      },
    ],
    tips: [
      '"좋아진다"처럼 추상적인 표현보다 측정 가능한 기준을 사용합니다.',
      'accuracy, latency, cost, automation rate, user satisfaction 같은 KPI를 포함합니다.',
      'AWS 펀딩 검토 관점에서는 비즈니스 가치와 프로덕션 전환 가능성이 중요합니다.',
    ],
  },

  // Requirement 29: Assumptions & Risks
  assumptions: {
    title: 'Assumptions & Risks 작성 가이드',
    purpose:
      '프로젝트 수행을 위해 전제한 조건, 고객 제공 필요사항, 기술적 제약, 보안/컴플라이언스 리스크를 정리합니다.',
    blocks: [
      {
        heading: '권장 카테고리 (Recommended Categories)',
        items: [
          'Business Context',
          'Technical Environment',
          'Project Execution',
          'Scope Boundaries',
          'Future Considerations',
          'Security & Compliance',
          'AWS Service Usage Assumptions',
        ],
      },
      {
        heading: '예시 (Examples)',
        items: [
          '고객은 필요한 업무 요구사항과 시스템 문서를 제공합니다.',
          '주요 이해관계자는 정기 회의와 검토에 참여합니다.',
          'Amazon Bedrock은 대상 리전에서 사용 가능하다고 가정합니다.',
          '데이터는 저장 및 전송 시 암호화됩니다.',
          '실제 운영 배포는 본 PoC 범위에서 제외될 수 있습니다.',
          'OpenSearch 사이징은 데이터량과 검색 요구사항을 기반으로 검증합니다.',
        ],
      },
    ],
    tips: [
      '고객이 제공해야 하는 데이터, 문서, 담당자, 일정 조건을 명확히 적습니다.',
      '금융, 헬스케어, 공공, 보험 등 규제 산업은 보안과 거버넌스 가정을 반드시 포함합니다.',
      'AWS 서비스 사용 가정은 비용 산정과 연결되어야 합니다.',
    ],
  },

  // Requirement 30: Scope of Work
  scope_of_work: {
    title: 'Scope of Work 작성 가이드',
    purpose:
      '프로젝트에서 수행할 작업과 제외할 작업을 명확히 정의합니다. 일정, 세부 작업, 담당 인력, 산출물을 함께 작성하면 좋습니다.',
    blocks: [
      {
        heading: '권장 카테고리 (Recommended Categories)',
        items: [
          'Assessment and Analysis',
          'Analysis/Design',
          'AI Solution Design',
          'Integration Planning',
          'Development',
          'Verification and Enhancement',
          'PoC Results and Cost Analysis',
          'Documentation & Knowledge Transfer',
          'Deployment',
          'Operation / Stabilization',
        ],
      },
      {
        heading: '일반적인 세부 작업 (Common Details)',
        items: [
          '고객 요구사항 분석',
          '아키텍처 설계',
          'AWS 인프라 구성',
          '데이터 전처리 및 인덱싱',
          'RAG 파이프라인 개발',
          'Prompt 개발',
          'GenAI Backend API 개발',
          'Frontend 개발',
          '시나리오 기반 검증',
          '고객 피드백 반영',
          '사용자 교육 및 지식 이전',
        ],
      },
    ],
    tips: [
      'In-Scope와 Out-of-Scope를 구분합니다.',
      '실제 구현이 제외되는 컨설팅/설계형 PoC라면 명확히 적습니다.',
      '각 작업은 Milestones와 Deliverables 섹션과 일관되어야 합니다.',
    ],
  },

  // Requirement 31: Architecture
  architecture: {
    title: 'Architecture 작성 가이드',
    purpose:
      'PoC에서 사용할 AWS 서비스와 각 서비스의 역할을 설명합니다. 아키텍처 다이어그램과 비용 산정이 서로 일치해야 합니다.',
    blocks: [
      {
        heading: '권장 서비스 (Recommended Services)',
        items: [
          'Amazon Bedrock',
          'Amazon OpenSearch Service',
          'Amazon S3',
          'Amazon RDS',
          'Amazon ECS',
          'AWS Lambda',
          'Amazon API Gateway',
          'Amazon CloudWatch',
          'AWS IAM',
          'AWS KMS',
          'VPC',
          'Elastic Load Balancing',
          'AWS WAF',
          'AWS Glue Data Catalog',
          'Amazon Athena',
          'Amazon SageMaker',
        ],
      },
    ],
    tips: [
      '다이어그램에 있는 서비스는 Cost Breakdown에도 반영되어야 합니다.',
      'Cost Breakdown에 있는 서비스는 Architecture에도 설명되어야 합니다.',
      'Bedrock 사용 목적, OpenSearch 사용 목적, S3 데이터 저장 목적은 명확히 적습니다.',
      '월 $5,000 이상 주요 서비스는 사이징 근거를 적는 것이 좋습니다.',
    ],
  },

  // Requirement 32: Milestones
  milestones: {
    title: 'Milestones 작성 가이드',
    purpose:
      '프로젝트 phase, 예상 완료일, 산출물을 정리합니다. Scope of Work와 일정 및 산출물이 일치해야 합니다.',
    blocks: [
      {
        heading: '권장 Phase (Recommended Phases)',
        items: [
          'Assessment and Analysis',
          'Analysis/Design',
          'AI Solution Design',
          'Integration Planning',
          'Development',
          'Verification and Enhancement',
          'Documentation & Knowledge Transfer',
          'Deployment',
          'Operation / Stabilization',
          'Implementation',
          'Testing',
          'Open',
        ],
      },
      {
        heading: '일반적인 산출물 (Common Deliverables)',
        items: [
          'Execution Plan',
          'WBS',
          'Requirements Definition Document',
          'Architecture Design Document',
          'API Specification',
          'Prompt Design Document',
          'RAG Pipeline Code',
          'Test Scenarios and Results Document',
          'Performance Analysis',
          'Completion Report',
          'Operating Manual',
          'User Manual',
          'Knowledge Transfer Materials',
        ],
      },
    ],
    tips: [
      '날짜가 확정되지 않았다면 주차 또는 phase 기반으로 작성할 수 있습니다.',
      '각 phase의 deliverable은 Acceptance와 연결됩니다.',
      '너무 많은 산출물을 넣기보다 AWS 제출에 필요한 핵심 산출물을 명확히 적습니다.',
    ],
  },

  // Requirement 33: Cost Breakdown
  cost_breakdown: {
    title: 'Cost Breakdown 작성 가이드',
    purpose:
      '예상 AWS 비용과 비용 산정 근거를 정리합니다. AWS 펀딩 검토에서는 AWS Calculator 링크, Bedrock 별도 산정, ARR/MRR, 서비스별 비용 근거가 중요합니다.',
    blocks: [
      {
        heading: '필수 정보 (Required Information)',
        items: [
          'AWS Pricing Calculator URL',
          'MRR',
          'ARR',
          '서비스별 비용 표',
          'Bedrock token cost 또는 별도 Excel 산정',
          '비용 산정 가정',
        ],
      },
      {
        heading: '일반적인 비용 카테고리 (Common Categories)',
        items: [
          'Bedrock',
          'Infra',
          'OpenSearch',
          'Compute',
          'Storage',
          'Database',
          'Network',
          'Monitoring',
          'Security',
          'Total',
        ],
      },
    ],
    tips: [
      'Bedrock이 AWS Calculator에 없거나 별도 산정이 필요한 경우 별도 note로 작성합니다.',
      '아키텍처에 있는 서비스와 비용표의 서비스가 일치해야 합니다.',
      '사용량 가정이 있으면 함께 적습니다. 예: 사용자 수, 일 요청 수, 입력/출력 토큰 수, 문서 수',
      'GenAI IC 펀딩은 ARR, SOW Cost, 최대 한도 기준과 연결되므로 수치가 명확해야 합니다.',
    ],
  },

  // Requirement 34: Resources & Cost Estimates
  resources_cost_estimates: {
    title: 'Resources & Cost Estimates 작성 가이드',
    purpose:
      '파트너 수행 인력, 역할별 rate, phase별 투입 시간, 총 비용, 비용 분담 구조를 정리합니다.',
    blocks: [
      {
        heading: '권장 역할 (Recommended Roles)',
        items: [
          'PM',
          'Project Manager',
          'Project QA',
          'PMO',
          'Solution Architect',
          'Sr. Solutions Architect',
          'AI Agent Architect',
          'AI Service Engineer',
          'AI & Data Engineer',
          'GenAI Engineer',
          'Data Engineer',
          'UI Engineer',
          'Web Designer',
          'Security SA',
          'Consultant',
          'Advisor',
        ],
      },
      {
        heading: '비용 분담 당사자 (Contribution Parties)',
        items: ['Customer', 'Partner', 'AWS'],
      },
    ],
    tips: [
      '역할과 phase는 Scope/Milestones와 일치해야 합니다.',
      'rate와 total hours를 기반으로 total cost가 계산되어야 합니다.',
      'Customer, Partner, AWS 비용 분담을 명확히 적습니다.',
      'Client signature 정보는 문서 제출 전 확인이 필요합니다.',
    ],
  },

  // Requirement 35: Acceptance
  acceptance: {
    title: 'Acceptance 작성 가이드',
    purpose:
      '산출물 제출, 고객 검토, 승인, 반려, 수정 및 재제출, 자동 승인 조건을 정의합니다.',
    blocks: [
      {
        heading: '권장 단계 (Recommended Steps)',
        items: [
          'Deliverable Submission and Review',
          'Review Period',
          'Acceptance Confirmation',
          'Rejection Process',
          'Correction and Resubmission',
          'Secondary Review',
          'Automatic Acceptance',
          'Final Project Acceptance',
        ],
      },
    ],
    tips: [
      '검토 기간은 보통 8 business days 또는 고객과 합의한 기간을 사용합니다.',
      '각 phase 산출물이 acceptance 대상이 됩니다.',
      '반려 시 고객은 사유를 제공하고, 파트너는 수정 후 재제출합니다.',
      '기간 내 반려가 없으면 자동 승인되는 조항을 포함할 수 있습니다.',
    ],
  },
}
