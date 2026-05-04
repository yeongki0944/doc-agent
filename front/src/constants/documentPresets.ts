import type { FieldValue, FieldStatus, CategoryGroup } from '../store/documentStore'

// --- Interfaces ---

export interface PresetGroup {
  readonly category_name: string
  readonly bullets: readonly string[]
}

export interface AcceptanceStepPreset {
  readonly heading: string
  readonly content: string
  readonly bullets: readonly string[]
}

// --- Helper Functions ---

export function presetToFieldValue(value: string): FieldValue {
  return {
    user_input: value,
    ai_recommended: null,
    calculated: null,
    status: 'draft' as FieldStatus,
    user_edited: true,
  }
}

export function presetGroupToCategoryGroup(preset: PresetGroup): CategoryGroup {
  return {
    category_name: presetToFieldValue(preset.category_name),
    bullets: preset.bullets.map(presetToFieldValue),
  }
}

// --- Cover Presets ---

export const INDUSTRY_PRESETS = [
  'Healthcare',
  'Finance / Insurance',
  'Retail / Commerce',
  'Manufacturing',
  'Logistics',
  'Gaming',
  'Construction',
  'Automotive',
  'Public Sector',
  'Education',
  'Food / Beverage',
  'Fashion',
] as const

export const AWS_SERVICE_PRESETS = [
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
] as const

// --- Executive Summary Presets ---

export const EXEC_SUMMARY_STARTER_BLOCKS = [
  'Who is the customer?',
  'What problems is the customer facing?',
  'What is the proposed solution?',
  'How will the project be carried out?',
  'Current Pain Points',
  'PoC Objectives',
  'Business Objectives',
  'Technical Objectives',
  'Drivers for Moving to AWS Cloud',
] as const

export const PAIN_POINT_PRESETS = [
  'Manual and repetitive work consumes significant time',
  'Existing search process is slow and inefficient',
  'Current process depends heavily on individual knowledge',
  'Data is scattered across multiple systems or documents',
  'Public AI usage creates data leakage concerns',
  'Current system has accuracy, latency, or scalability limitations',
  'Existing workflow lacks automation and standardization',
  'Support requests are expected to increase after system launch',
] as const

export const POC_OBJECTIVE_PRESETS = [
  'Validate Amazon Bedrock-based GenAI capability',
  'Build and verify a RAG-based knowledge search workflow',
  'Validate response accuracy and latency',
  'Validate scalable AWS architecture',
  'Validate secure data processing and access control',
  'Measure business efficiency improvement',
  'Provide technical documentation and knowledge transfer',
  'Define production-readiness criteria',
] as const

// --- Stakeholders Presets ---

export const TITLE_PRESETS = [
  'CAIO',
  'VP, ADC',
  'VP, ADU',
  'Director, Business',
  'Director',
  'Senior Director',
  'Unit Leader',
  'Team Leader',
  'Delivery Manager',
  'Project Manager',
  'Manager',
  'Sr. Solutions Architect',
  'Solutions Architect',
  'AI & Data Engineer',
  'Data Engineer',
  'AI Agent Architect',
  'AI Service Engineer',
  'Web Designer',
  'Security SA',
  'Consultant',
] as const

export const DESCRIPTION_PRESETS = [
  'Head of AI Business',
  'Head of AI & Data Business',
  'Head of Business Service',
  'Project Sponsor',
  'Engagement Partner',
  'Head of IT Departments',
  'Head of Digital Planning Team',
  'Business Requirements',
  'PMO',
  'QA',
  'Security',
  'Architecture Review',
] as const

export const STAKEHOLDER_FOR_PRESETS = [
  'Project Sponsor',
  'Head of Business Service',
  'Head of IT Departments',
  'Business Requirements',
  'PMO',
  'IT – QA & Testing',
  'Biz Requirements',
  'QA',
  'Security',
  'Infrastructure',
  'Architecture Review',
  'Customer Contact',
] as const

export const ROLE_PRESETS = [
  'Project Manager',
  'PM',
  'PMO',
  'Project QA',
  'QA',
  'Engagement Partner',
  'Architect',
  'Technical Lead',
  'Solutions Architect',
  'SA',
  'AI Engineer',
  'GenAI Engineer',
  'AI & Data Engineering',
  'AI Agent Architect',
  'Agent Development',
  'AI Service Engineer',
  'Data Pipeline Architect',
  'RAG Development',
  'UI Engineer',
  'UI Developer',
  'Web Designer',
  'Security Design & Build',
  'Security',
  'Advisor',
  'Customer Contact',
] as const

// --- Success Criteria Preset Groups ---

export const SUCCESS_CRITERIA_PRESET_GROUPS: readonly PresetGroup[] = [
  {
    category_name: 'Strategy Development & Planning',
    bullets: [
      'Define clear project objectives aligned with business goals',
      'Establish measurable KPIs for PoC evaluation',
      'Develop a comprehensive project execution plan',
    ],
  },
  {
    category_name: 'Technical Framework Design',
    bullets: [
      'Design scalable AWS architecture meeting performance requirements',
      'Define data pipeline and integration architecture',
      'Establish technical standards and best practices',
    ],
  },
  {
    category_name: 'Implementation Roadmap',
    bullets: [
      'Complete all planned development milestones on schedule',
      'Deliver working prototype demonstrating core functionality',
      'Achieve successful integration with existing systems',
    ],
  },
  {
    category_name: 'Knowledge Transfer',
    bullets: [
      'Deliver comprehensive technical documentation',
      'Conduct hands-on training sessions for customer team',
      'Provide operational runbooks and best practices guide',
    ],
  },
  {
    category_name: 'Project Objective',
    bullets: [
      'Validate GenAI capability using Amazon Bedrock',
      'Demonstrate measurable business efficiency improvement',
      'Confirm production-readiness of the proposed solution',
    ],
  },
  {
    category_name: 'Security and Data Protection Perspective',
    bullets: [
      'Implement data encryption at rest and in transit',
      'Validate access control and authentication mechanisms',
      'Ensure compliance with customer security policies',
    ],
  },
  {
    category_name: 'RAG Environment and Response Quality Perspective',
    bullets: [
      'Achieve response accuracy of 90% or higher',
      'Maintain average response latency under 3 seconds',
      'Validate RAG pipeline with customer-provided documents',
    ],
  },
  {
    category_name: 'Cost Effectiveness Perspective',
    bullets: [
      'Operate within estimated monthly AWS cost budget',
      'Demonstrate cost savings compared to current process',
      'Provide detailed cost breakdown and optimization recommendations',
    ],
  },
] as const

// --- Assumptions Preset Groups ---

export const ASSUMPTIONS_PRESET_GROUPS: readonly PresetGroup[] = [
  {
    category_name: 'Business Context',
    bullets: [
      'Customer will provide necessary business requirements and system documentation',
      'Key stakeholders will participate in regular meetings and reviews',
      'Project scope and objectives are agreed upon before execution begins',
    ],
  },
  {
    category_name: 'Technical Environment',
    bullets: [
      'Amazon Bedrock is available in the target AWS region',
      'Customer will provide access to required data sources and systems',
      'Existing infrastructure supports integration with AWS services',
    ],
  },
  {
    category_name: 'Project Execution',
    bullets: [
      'Project timeline follows the agreed schedule with defined milestones',
      'Customer will provide timely feedback during review periods',
      'Change requests will follow the agreed change management process',
    ],
  },
  {
    category_name: 'Scope Boundaries',
    bullets: [
      'Production deployment is out of scope for this PoC phase',
      'Performance testing is limited to defined test scenarios',
      'Third-party system integration is limited to agreed interfaces',
    ],
  },
  {
    category_name: 'Future Considerations',
    bullets: [
      'Production migration plan will be developed as a separate phase',
      'Scaling requirements will be assessed based on PoC results',
      'Long-term operational model will be defined post-PoC',
    ],
  },
  {
    category_name: 'Security & Compliance',
    bullets: [
      'Data is encrypted at rest and in transit',
      'Access control follows the principle of least privilege',
      'Customer security and compliance policies are provided in advance',
    ],
  },
  {
    category_name: 'AWS Service Usage Assumptions',
    bullets: [
      'OpenSearch sizing is validated based on data volume and search requirements',
      'Bedrock model selection is based on accuracy and latency requirements',
      'AWS service limits are sufficient for PoC workload',
    ],
  },
] as const

// --- Scope of Work Presets ---

export const TASK_CATEGORY_PRESETS = [
  'Assessment and Analysis',
  'Analysis/Design',
  'AI Solution Design',
  'Integration Planning',
  'Development',
  'Verification and Enhancement',
  'PoC Results and Cost Analysis',
  'Strategy Development',
  'Documentation & Knowledge Transfer',
  'Deployment',
  'Operation / Stabilization',
  'Implementation',
  'Testing',
  'Open',
] as const

export const PERSONNEL_PRESETS = [
  'Senior Technician (Partner)',
  'Junior Technician (Partner)',
  'Customer Contact',
  'Partner and Customer Contact',
  'Project Manager',
  'Solution Architect',
  'AI Engineer',
  'GenAI Engineer',
  'AI Service Engineer',
  'Data Engineer',
  'Security Specialist',
  'QA',
] as const

export const DELIVERABLE_PHRASE_PRESETS = [
  'Project scope and architecture design',
  'Analyze customer requirements and design the technical architecture and solution',
  'Select the optimal GenAI model using Amazon Bedrock',
  'AWS infrastructure setup',
  'Data preprocessing and indexing',
  'RAG pipeline development',
  'Prompt development',
  'GenAI backend API development',
  'Frontend development for GenAI chat',
  'Internal verification based on scenarios',
  'Customer verification based on scenarios',
  'Enhancement based on customer feedback',
  'Confirmation of project success based on established success criteria',
  'User training',
  'Knowledge transfer',
  'Documentation and handover',
] as const

export const SCHEDULE_PATTERN_PRESETS = [
  '-',
  '1st Week',
  '1st Week ~ 2nd Week',
  '2nd Week',
  '3rd Week ~ 5th Week',
  '6th Week',
  'Jun 2, 2025 - Jun 6, 2025',
  'Jun 9, 2025 - Jun 20, 2025',
  'Jun 23, 2025 - July 11, 2025',
  'July 14, 2025 - July 18, 2025',
  'TBD',
] as const

// --- Architecture Presets ---

export const SERVICE_NAME_PRESETS = [
  'Amazon Bedrock',
  'Amazon OpenSearch Service',
  'Amazon S3',
  'Amazon EC2',
  'Amazon EBS',
  'Amazon RDS',
  'Amazon API Gateway',
  'AWS Lambda',
  'Amazon ECS',
  'Elastic Load Balancing',
  'Amazon CloudWatch',
  'AWS IAM',
  'AWS WAF',
  'AWS Shield',
  'AWS KMS',
  'AWS Glue Data Catalog',
  'Amazon Athena',
  'Amazon SageMaker',
  'Amazon EventBridge',
  'AWS Config',
  'VPC',
  'NAT Gateway',
] as const

export const SERVICE_DESCRIPTION_PRESETS: Readonly<Record<string, string>> = {
  'Amazon Bedrock': 'Used for LLM-based response generation, classification, summarization, and reasoning.',
  'Amazon OpenSearch Service': 'Used for vector search and retrieval-augmented generation.',
  'Amazon S3': 'Used for storing raw, processed, and result data.',
  'Amazon RDS': 'Used for metadata, prompt history, user activity, or application data.',
  'Amazon ECS': 'Used for containerized application runtime.',
  'AWS Lambda': 'Used for serverless processing and event-based integration.',
  'Amazon CloudWatch': 'Used for logs, metrics, alarms, and operational monitoring.',
} as const

// --- Milestones Presets ---

export const PROJECT_PHASE_PRESETS = [
  'Assessment and Analysis',
  'Analysis/Design',
  'AI Solution Design',
  'Integration Planning',
  'Development',
  'Verification and Enhancement',
  'PoC Results and Cost Analysis',
  'Strategy Development',
  'Documentation & Knowledge Transfer',
  'Deployment',
  'Operation / Stabilization',
  'Implementation',
  'Testing',
  'Open',
] as const

export const MILESTONE_DELIVERABLE_PRESETS = [
  'Execution Plan',
  'WBS',
  'Requirements Definition Document',
  'Current State Analysis Report',
  'High-Level Architecture',
  'Infra and Data Architecture Definition Document',
  'Architecture Design Document',
  'API Specification',
  'Table Definition Document',
  'Prompt Design Document',
  'RAG Pipeline Code',
  'Development Code',
  'Web Interface',
  'Test Scenarios and Results Document',
  'Performance Analysis',
  'Completion Report',
  'Final Report',
  'Operating Manual',
  'User Manual',
  'Knowledge Transfer Materials',
  'Best Practices Guide',
] as const

// --- Cost Breakdown Presets ---

export const COST_CATEGORY_PRESETS = [
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
] as const

export const COST_NOTE_PRESETS = [
  'AWS Calculator link',
  'Excel file',
  'Bedrock extra estimate',
  'Included in AWS Calculator',
  'Estimated based on token usage',
  'Estimated based on active users and daily queries',
  'Estimated based on data volume and retention period',
] as const

// --- Resources & Cost Estimates Presets ---

export const RESOURCE_ROLE_PRESETS = [
  'PM',
  'Project Manager',
  'Project QA',
  'PMO',
  'Solution Architect',
  'Solutions Architect',
  'Sr. Solutions Architect',
  'AI Agent Architect',
  'AI Service Engineer',
  'AI & Data Engineer',
  'GenAI Engineer',
  'Data Engineer',
  'RAG Developer',
  'UI Engineer',
  'Web Designer',
  'Security SA',
  'Consultant',
  'Advisor',
  'Customer Contact',
] as const

export const RATE_PRESETS = [65, 80, 81.78, 93, 100, 112.45, 115, 116, 150, 156.25] as const

// --- Acceptance Presets ---

export const ACCEPTANCE_STEP_PRESETS: readonly AcceptanceStepPreset[] = [
  {
    heading: 'Deliverable Submission and Review',
    content: 'Upon completion of each project phase, the provider will submit the associated deliverables to the customer for review.',
    bullets: [],
  },
  {
    heading: 'Review Period',
    content: 'The customer will review, evaluate, and assess each deliverable within the agreed acceptance period.',
    bullets: [],
  },
  {
    heading: 'Acceptance Confirmation',
    content: 'If a deliverable meets the acceptance criteria, the customer will provide written acceptance confirmation.',
    bullets: [],
  },
  {
    heading: 'Rejection Process',
    content: 'If a deliverable does not meet the acceptance criteria, the customer will provide a rejection notice with reasons.',
    bullets: [],
  },
  {
    heading: 'Correction and Resubmission',
    content: 'The provider will correct identified deficiencies and resubmit the deliverable for review.',
    bullets: [],
  },
  {
    heading: 'Secondary Review',
    content: 'For resubmitted deliverables, the customer review will focus on whether the identified issues have been resolved.',
    bullets: [],
  },
  {
    heading: 'Automatic Acceptance',
    content: 'If the customer does not provide a rejection notice within the acceptance period, the deliverable will be deemed accepted.',
    bullets: [],
  },
  {
    heading: 'Final Project Acceptance',
    content: 'Final project acceptance will be granted upon completion and acceptance of all required deliverables.',
    bullets: [],
  },
] as const
