# Requirements Document: Document Presets & Writing Guides

## Introduction

The Document Presets feature improves all Live Document tabs so users do not start from a blank page. The frontend provides preset dropdowns, starter templates, Korean writing guides, and improved empty states so users can quickly fill in content. Presets are suggestions, not restrictions. Users must always be able to type custom values. Preset values are persisted only when the user explicitly clicks Add / Apply / Select — never automatically on tab open.

This feature also adds numbered tab labels that map to the DOCX document structure, separates required vs optional fields on the Cover tab, improves empty-state UX across all tabs, and provides a per-tab Korean writing guide accessible via a header icon.

## Glossary

- **Document_Panel**: The main React component (`DocumentPanel.tsx`) that renders all document tabs and manages tab navigation.
- **FieldValue**: The standard data shape `{user_input, ai_recommended, calculated, status, user_edited}` used for all editable fields in the document store.
- **Preset**: A predefined value or group of values offered as a suggestion to the user. Presets do not restrict input.
- **Preset_Config**: The centralized TypeScript constants file (`front/src/constants/documentPresets.ts`) containing all preset values for all sections.
- **Guide_Config**: The centralized TypeScript constants file (`front/src/constants/documentGuides.ts`) containing Korean writing guide content for all tabs.
- **EditableComboField**: A reusable combo-box style React component that shows the current value, allows selecting from presets, and allows custom typing.
- **SectionGuideButton**: A reusable React component that renders a guide icon (ⓘ) next to a section title and opens a popup/popover/collapsible panel with Korean writing guidance.
- **Section_Component**: Any React component under `front/src/components/sections/` that renders a document tab (e.g., `CoverSection`, `StakeholdersSection`).
- **Editor_Component**: Any React component under `front/src/components/editors/` that provides inline editing (e.g., `FieldValueEditor`, `ContactTableEditor`).
- **Empty_State**: The UI shown when a section has no content. Must provide starter actions, not just a blank message.
- **Fixed_Default**: A value that is automatically applied to new documents without user action. Only explicitly approved fixed defaults are allowed.
- **User_Applied_Preset**: A preset value that the user explicitly selects via a button or dropdown. Persisted as `user_input` with `status="draft"` and `user_edited=true`.
- **Document_Store**: The Zustand store (`documentStore.ts`) that holds the client-side document state.
- **Save_API**: The `saveUserInput` function that persists field values to the backend via REST API.
- **Writing_Guide**: A Korean-language help panel that explains how to write a specific section, including purpose, recommended structure, examples, useful AI prompts, and tips.

## Requirements

### Requirement 1: Numbered Tab Labels for DOCX Mapping

**User Story:** As a user, I want the tab labels to include document section numbers, so that I can easily understand how the web UI maps to the actual DOCX document structure.

#### Acceptance Criteria

1. THE Document_Panel SHALL render tab labels with the following numbering: "1. Cover", "2.1 Executive Summary", "2.2 Stakeholders", "2.3 Success Criteria / KPIs", "2.4 Assumptions & Risks", "2.5 Scope of Work", "2.6 Architecture", "2.7 Milestones", "2.8 Cost Breakdown", "2.9 Resources & Cost Estimates", "2.10 Acceptance".
2. THE numbered tab labels SHALL be visible UI labeling only.
3. THE numbered tab labels SHALL NOT change any schema keys, save paths, or export context keys.
4. THE section `<h2>` headings inside each tab SHALL also reflect the numbered label (e.g., "2.1 Executive Summary").

### Requirement 2: Centralized Preset Configuration File

**User Story:** As a developer, I want all preset values defined in a single constants file, so that presets are easy to maintain and consistent across all tabs.

#### Acceptance Criteria

1. THE Preset_Config SHALL export typed constant arrays for every section listed in Requirements 8 through 18.
2. THE Preset_Config SHALL be located at `front/src/constants/documentPresets.ts`.
3. THE Preset_Config SHALL use TypeScript `as const` assertions or readonly arrays so that preset values are immutable at compile time.
4. WHEN a developer adds or removes a preset value, THE Preset_Config SHALL be the only file that requires modification for the preset data itself.

### Requirement 3: Centralized Writing Guide Configuration File

**User Story:** As a developer, I want all Korean writing guide content defined in a single constants file, so that guide content is easy to maintain and consistent across all tabs.

#### Acceptance Criteria

1. THE Guide_Config SHALL be located at `front/src/constants/documentGuides.ts`.
2. THE Guide_Config SHALL export a typed object keyed by section name (e.g., `cover`, `executive_summary`, `stakeholders`, etc.).
3. THE Guide_Config SHALL use a common flexible block structure to avoid TypeScript/UI complexity from varying key names. The recommended types are: `type GuideBlock = { heading: string; items: string[] }` and `type DocumentGuide = { title: string; purpose: string; blocks: GuideBlock[]; useful_prompts?: string[]; tips: string[] }`. The Korean content specified in Requirements 25 through 35 SHALL be represented using this `blocks` structure (e.g., required fields, optional fields, recommended structure, examples, etc. each become a `GuideBlock`). **Note**: Labels such as `required_fields`, `optional_fields`, `recommended_structure`, `examples`, `recommended_categories`, `common_details`, `recommended_services`, `common_deliverables`, `required_information`, `contribution_parties`, and `recommended_steps` used in Requirements 25–35 are content group names only. In implementation, each of these SHALL become a `GuideBlock` entry inside `DocumentGuide.blocks` (with the label as `heading` and the items as `items`), NOT separate top-level keys on the guide object.
4. THE Guide_Config SHALL contain the Korean writing guide content specified in Requirements 25 through 35.

### Requirement 4: Reusable Section Guide Button Component

**User Story:** As a user, I want a guide icon next to each section title that opens a Korean writing guide, so that I can learn how to write each section without leaving the editor.

#### Acceptance Criteria

1. THE SectionGuideButton SHALL render a small icon (e.g., ⓘ) next to the section `<h2>` title.
2. WHEN the user clicks the icon, THE SectionGuideButton SHALL open a popup, popover, or collapsible panel displaying the Korean writing guide for that section.
3. THE SectionGuideButton SHALL allow the user to close the guide panel.
4. THE guide panel SHALL NOT block editing permanently; the user must be able to dismiss it and continue editing.
5. THE SectionGuideButton SHALL accept a `sectionKey` prop and read guide content from Guide_Config.
6. THE SectionGuideButton SHALL NOT require a backend call to display guide content.
7. THE SectionGuideButton SHALL NOT persist anything to the database.
8. EVERY Section_Component SHALL render a SectionGuideButton in its header area.

### Requirement 5: Reusable Editable Combo-Box Component

**User Story:** As a developer, I want a reusable combo-box component that combines a text input with a preset dropdown, so that I can add preset support to any field without duplicating logic.

#### Acceptance Criteria

1. THE EditableComboField SHALL display the current field value as editable text.
2. THE EditableComboField SHALL render a dropdown trigger that opens a list of preset options.
3. WHEN the user selects a preset option, THE EditableComboField SHALL populate the text input with the selected preset value.
4. WHEN the user types a custom value that does not match any preset, THE EditableComboField SHALL accept and save the custom value.
5. THE EditableComboField SHALL save the selected or custom value to the `FieldValue.user_input` path using the same save mechanism as FieldValueEditor (blur/Enter triggers save).
6. THE EditableComboField SHALL accept a `presets` prop containing the list of preset strings to display.
7. THE EditableComboField SHALL accept the same `dotPath`, `docId`, `field`, and `onLocalUpdate` props as FieldValueEditor so it can be used as a drop-in replacement.
8. THE EditableComboField SHALL NOT restrict input to preset values only.
9. THE EditableComboField SHALL NOT own the `saveUserInput` call directly if the architecture keeps save logic in the section or helper layer; instead it SHALL delegate saving through the `onLocalUpdate` and existing save pattern.

### Requirement 6: Empty Section Starter Actions

**User Story:** As a user, I want to see helpful starter actions when a section is empty, so that I know how to begin filling in content without relying solely on the chat.

#### Acceptance Criteria

1. WHEN a Section_Component has no content, THE Section_Component SHALL display starter action buttons instead of only a blank message.
2. THE Empty_State actions SHALL be section-appropriate, not identical across all tabs. Examples: CategoryGroup sections (Success Criteria, Assumptions) SHALL offer "프리셋 그룹 추가" and "직접 그룹 추가"; table sections (Stakeholders, Scope of Work, Milestones, Cost Breakdown, Resources) SHALL offer "프리셋 행 추가" and "직접 행 추가"; Acceptance SHALL offer "표준 인수 프로세스 적용" and "직접 단계 추가"; Cover SHALL show required/optional field guidance rather than preset group actions.
3. THE Empty_State SHALL display guidance text such as "자주 사용하는 형식을 선택하여 시작하거나, 직접 입력할 수 있습니다."
4. THE Empty_State SHALL NOT state that chat is the only way to create the section.
5. THE Empty_State SHALL NOT use the legacy word "Overview" when referring to Executive Summary.
6. WHEN the user clicks a preset action, THE Section_Component SHALL present the relevant preset groups or items from Preset_Config for user selection.
7. WHEN the user clicks a custom add action, THE Section_Component SHALL add an empty editable row, group, or step as appropriate.
8. WHEN the user clicks "AI에게 초안 요청", THE Section_Component SHALL provide example AI prompt text that the user can copy or use as guidance (e.g., "Executive Summary 초안 작성해줘").

### Requirement 7: Fixed Default — Partner Value

**User Story:** As a user, I want the partner field to default to "MegazoneCloud" for new documents, so that I do not have to type it every time.

#### Acceptance Criteria

1. WHEN a new document is created, THE Document_Store SHALL initialize `meta.partner` with `{user_input: null, ai_recommended: null, calculated: "MegazoneCloud", status: "confirmed", user_edited: false}`.
2. THE backend document creation endpoint SHALL also set `meta.partner` to the same FieldValue shape with `calculated: "MegazoneCloud"` and `status: "confirmed"`.
3. WHEN the user edits the partner field, THE Document_Store SHALL save the new value as `user_input` with `status: "draft"` and `user_edited: true`.
4. THE CoverSection SHALL display "MegazoneCloud" as the resolved value for the partner field on new documents.
5. OTHER required Cover fields (고객사, 날짜, 프로젝트명) SHALL start empty on new documents.

### Requirement 8: Fixed Default — Partner Executive Sponsor

**User Story:** As a user, I want one default Partner Executive Sponsor row pre-filled for new documents, so that the standard sponsor information is readily available.

#### Acceptance Criteria

1. WHEN a new document is created, THE Document_Store SHALL initialize `sections.stakeholders.executive_sponsors` with exactly one ContactEntry containing: name `"James, Kong"`, title `"CAIO"`, description `"Head of AI Business"`, contact `"jameskong@megazone.com"`, each as a FieldValue with `calculated` set to the value, `status: "confirmed"`, and `user_edited: false`.
2. THE backend document creation endpoint SHALL persist the same default executive sponsor row.
3. WHEN the user edits any field in the default executive sponsor row, THE Document_Store SHALL save the new value as `user_input` with `status: "draft"` and `user_edited: true`.
4. WHEN the user deletes the default executive sponsor row, THE Document_Store SHALL remove the row and persist the change.
5. THE Document_Store SHALL NOT auto-insert any other named people beyond this single default row.
6. THE frontend default insertion SHALL be idempotent: THE Document_Store SHALL NOT add the default Partner Executive Sponsor row when the loaded document already contains `executive_sponsors` data. Frontend defaults SHALL only be applied during new document bootstrap before backend data is loaded. THE backend document creation endpoint SHALL remain the source of truth after creation.

### Requirement 9: Cover Tab — Required vs Optional Separation

**User Story:** As a user, I want the Cover tab to clearly separate required DOCX cover fields from optional agent context fields, so that I know which fields are essential for the exported document.

#### Acceptance Criteria

1. THE CoverSection SHALL visually separate fields into two groups: "Required for DOCX Cover" and "Optional Agent Context".
2. THE "Required for DOCX Cover" group SHALL contain: 고객사 (`meta.customer`), 파트너 (`meta.partner`), 날짜 (`meta.date`), 프로젝트명 (`DocumentState.title`).
3. THE "Optional Agent Context" group SHALL contain: 산업군 (`sections.cover.industry`), 프로젝트 배경 (`sections.cover.project_background`), 주요 목표 (`sections.cover.main_objectives`), 예상 AWS 서비스 (`sections.cover.expected_aws_services`), 기간/예산 메모 (`sections.cover.timeline_budget_notes`).
4. THE 프로젝트명 field SHALL be stored in the top-level `DocumentState.title` property. IF `saveUserInput` only supports FieldValue paths, THE implementation SHALL use or reuse the appropriate title update mechanism (e.g., a dedicated API call or store method). THE implementation SHALL NOT store project name only under `sections.cover.project_name`.
5. THE optional agent context fields SHALL help downstream agents generate better Executive Summary, Scope, Architecture, Cost, and Reviewer output.
6. THE optional agent context fields SHALL NOT be required for DOCX cover rendering.
7. THE optional agent context fields SHALL default to empty on new documents.

### Requirement 10: Cover Tab Presets

**User Story:** As a user, I want preset dropdowns for industry and expected AWS services on the Cover tab, so that I can quickly select common values.

#### Acceptance Criteria

1. THE CoverSection SHALL render an EditableComboField for the `sections.cover.industry` field with presets: Healthcare, Finance / Insurance, Retail / Commerce, Manufacturing, Logistics, Gaming, Construction, Automotive, Public Sector, Education, Food / Beverage, Fashion.
2. THE CoverSection SHALL render an EditableComboField for the `sections.cover.expected_aws_services` field with presets: Amazon Bedrock, Amazon OpenSearch Service, Amazon S3, Amazon RDS, Amazon ECS, AWS Lambda, Amazon API Gateway, Amazon CloudWatch, AWS IAM, AWS KMS.
3. WHEN the user selects a preset for industry or expected AWS services, THE CoverSection SHALL persist the value only after the user confirms via the standard save-on-blur/Enter mechanism.
4. THE `sections.cover.expected_aws_services` field SHALL be stored as a single FieldValue string. IF multiple services are selected, they SHALL be joined as comma-separated text within the single FieldValue. THE implementation SHALL NOT introduce a new array schema for this field.

### Requirement 11: Executive Summary — Direct Edit UX Improvement

**User Story:** As a user, I want the Executive Summary empty state to support direct editing and not imply that chat is the only way to create content.

#### Acceptance Criteria

1. THE ExecutiveSummarySection empty state SHALL NOT display the legacy text "프로젝트 개요가 아직 입력되지 않았습니다. 채팅에서 \"Overview 작성해줘\"라고 요청하세요."
2. THE ExecutiveSummarySection empty state SHALL display text such as: "Executive Summary가 아직 입력되지 않았습니다. 오른쪽 문서에서 직접 입력하거나, 왼쪽 채팅에서 AI에게 작성을 요청할 수 있습니다."
3. THE ExecutiveSummarySection empty state SHALL provide a direct writing helper hint such as: "예: 고객사의 현재 과제, PoC 목표, 제안 솔루션을 입력하세요."
4. THE ExecutiveSummarySection empty state SHALL provide an AI prompt example such as: "AI 요청 예시: Executive Summary 초안 작성해줘"
5. THE ExecutiveSummarySection empty state SHALL NOT use the legacy word "Overview" when referring to Executive Summary.
6. THE ExecutiveSummarySection SHALL provide starter actions per Requirement 6.

### Requirement 12: Executive Summary Presets

**User Story:** As a user, I want preset writing blocks and list item presets for the Executive Summary tab, so that I can quickly add common sections.

#### Acceptance Criteria

1. THE ExecutiveSummarySection SHALL offer starter block presets: "Who is the customer?", "What problems is the customer facing?", "What is the proposed solution?", "How will the project be carried out?", "Current Pain Points", "PoC Objectives", "Business Objectives", "Technical Objectives", "Drivers for Moving to AWS Cloud".
2. WHEN the user selects a starter block, THE ExecutiveSummarySection SHALL map the block to the corresponding schema field (e.g., "Who is the customer?" maps to `customer_intro`, "Current Pain Points" maps to `current_pain_points[]`).
3. THE ExecutiveSummarySection SHALL provide preset items for `current_pain_points[]` containing 8 common pain point phrases from Preset_Config.
4. THE ExecutiveSummarySection SHALL provide preset items for `poc_objectives[]` containing 8 common objective phrases from Preset_Config.
5. WHEN the user applies a preset pain point or objective, THE ExecutiveSummarySection SHALL persist the value as `user_input` with `status: "draft"` and `user_edited: true`.
6. THE ExecutiveSummarySection SHALL NOT auto-insert any preset blocks; the user must explicitly select them.

### Requirement 13: Stakeholders — Blank State and Input Improvement

**User Story:** As a user, I want the Stakeholders tab to be easy to fill from a blank page with fixed table sections, dropdown presets, and add-row actions.

#### Acceptance Criteria

1. THE StakeholdersSection SHALL use fixed section headings: "Partner Executive Sponsor", "Project Stakeholders", "Partner Project Team", "Project Escalation Contacts". These headings SHALL NOT be stored as user input.
2. THE ContactTableEditor SHALL render an EditableComboField for the `title` column with 20 preset values from Preset_Config:
   - "CAIO"
   - "VP, ADC"
   - "VP, ADU"
   - "Director, Business"
   - "Director"
   - "Senior Director"
   - "Unit Leader"
   - "Team Leader"
   - "Delivery Manager"
   - "Project Manager"
   - "Manager"
   - "Sr. Solutions Architect"
   - "Solutions Architect"
   - "AI & Data Engineer"
   - "Data Engineer"
   - "AI Agent Architect"
   - "AI Service Engineer"
   - "Web Designer"
   - "Security SA"
   - "Consultant"
3. THE ContactTableEditor SHALL render an EditableComboField for the `description` column with 12 preset values from Preset_Config: Head of AI Business, Head of AI & Data Business, Head of Business Service, Project Sponsor, Engagement Partner, Head of IT Departments, Head of Digital Planning Team, Business Requirements, PMO, QA, Security, Architecture Review.
4. THE ContactTableEditor SHALL render an EditableComboField for the `stakeholder_for` column with 12 preset values from Preset_Config: Project Sponsor, Head of Business Service, Head of IT Departments, Business Requirements, PMO, IT – QA & Testing, Biz Requirements, QA, Security, Infrastructure, Architecture Review, Customer Contact.
5. THE ContactTableEditor SHALL render an EditableComboField for the `role` column with 25 preset values from Preset_Config: Project Manager, PM, PMO, Project QA, QA, Engagement Partner, Architect, Technical Lead, Solutions Architect, SA, AI Engineer, GenAI Engineer, AI & Data Engineering, AI Agent Architect, Agent Development, AI Service Engineer, Data Pipeline Architect, RAG Development, UI Engineer, UI Developer, Web Designer, Security Design & Build, Security, Advisor, Customer Contact.
6. WHEN the user types a custom value in any preset-enabled column, THE ContactTableEditor SHALL accept the custom value without restriction.

### Requirement 14: Stakeholders — Email / Contact Column

**User Story:** As a user, I want all stakeholder tables to include an Email / Contact column, so that contact information is always captured.

#### Acceptance Criteria

1. ALL stakeholder sub-tables SHALL include the Email / Contact column using `ContactEntry.contact`.
2. THE column configuration for each table SHALL be: Partner Executive Sponsor (Name, Title, Description, Email / Contact), Project Stakeholders (Name, Title, Stakeholder For, Email / Contact), Partner Project Team (Name, Title, Role, Email / Contact), Project Escalation Contacts (Name, Title, Role, Email / Contact).

### Requirement 15: Success Criteria / KPIs Presets

**User Story:** As a user, I want preset groups for Success Criteria / KPIs, so that I can quickly apply common criteria categories without typing from scratch.

#### Acceptance Criteria

1. THE SuccessCriteriaSection SHALL offer 8 preset groups from Preset_Config, each with a category name and bullet items.
2. WHEN the user clicks "Apply" or "Select" on a preset group, THE SuccessCriteriaSection SHALL add the group to the section as a CategoryGroup with `user_input` values, `status: "draft"`, and `user_edited: true`.
3. THE SuccessCriteriaSection SHALL NOT auto-insert any preset groups when the tab is opened.
4. WHEN the user edits a bullet or category name after applying a preset, THE SuccessCriteriaSection SHALL save the edited value normally.
5. WHEN the section is empty, THE SuccessCriteriaSection SHALL display starter actions per Requirement 6.

### Requirement 16: Assumptions & Risks Presets

**User Story:** As a user, I want preset groups for Assumptions & Risks, so that I can quickly apply common assumption and risk categories.

#### Acceptance Criteria

1. THE AssumptionsSection SHALL offer 7 preset groups from Preset_Config, each with a category name and bullet items.
2. WHEN the user clicks "Apply" or "Select" on a preset group, THE AssumptionsSection SHALL add the group to the section as a CategoryGroup with `user_input` values, `status: "draft"`, and `user_edited: true`.
3. THE AssumptionsSection SHALL NOT auto-insert any preset groups when the tab is opened.
4. WHEN the user edits a bullet or category name after applying a preset, THE AssumptionsSection SHALL save the edited value normally.
5. WHEN the section is empty, THE AssumptionsSection SHALL display starter actions per Requirement 6.

### Requirement 17: Scope of Work Presets

**User Story:** As a user, I want preset dropdowns for task category, personnel, and deliverable phrases in the Scope of Work tab, so that I can fill in tasks faster.

#### Acceptance Criteria

1. THE ScopeOfWorkSection SHALL render an EditableComboField for the `task_category` field with 14 preset values from Preset_Config: Assessment and Analysis, Analysis/Design, AI Solution Design, Integration Planning, Development, Verification and Enhancement, PoC Results and Cost Analysis, Strategy Development, Documentation & Knowledge Transfer, Deployment, Operation / Stabilization, Implementation, Testing, Open.
2. THE ScopeOfWorkSection SHALL render an EditableComboField for the `personnel` field with 12 preset values from Preset_Config: Senior Technician (Partner), Junior Technician (Partner), Customer Contact, Partner and Customer Contact, Project Manager, Solution Architect, AI Engineer, GenAI Engineer, AI Service Engineer, Data Engineer, Security Specialist, QA.
3. THE ScopeOfWorkSection SHALL provide 16 common deliverable phrase presets from Preset_Config for the `details` field.
4. THE ScopeOfWorkSection SHALL provide schedule pattern presets from Preset_Config for the `schedule` field.
5. WHEN the user types a custom value in any preset-enabled field, THE ScopeOfWorkSection SHALL accept the custom value without restriction.

### Requirement 18: Architecture Presets

**User Story:** As a user, I want preset dropdowns for service names, categories, and descriptions in the Architecture tab, so that I can add AWS services quickly.

#### Acceptance Criteria

1. THE ArchitectureSection SHALL render an EditableComboField for the `service_name` field with 22 service name presets from Preset_Config: Amazon Bedrock, Amazon OpenSearch Service, Amazon S3, Amazon EC2, Amazon EBS, Amazon RDS, Amazon API Gateway, AWS Lambda, Amazon ECS, Elastic Load Balancing, Amazon CloudWatch, AWS IAM, AWS WAF, AWS Shield, AWS KMS, AWS Glue Data Catalog, Amazon Athena, Amazon SageMaker, Amazon EventBridge, AWS Config, VPC, NAT Gateway.
2. THE ArchitectureSection SHALL provide 6 service category presets from Preset_Config for the `category` select field (genai_core, data, compute, network, security, monitoring).
3. THE ArchitectureSection SHALL provide common service description presets from Preset_Config for key services (e.g., Amazon Bedrock, Amazon OpenSearch Service, Amazon S3, Amazon RDS, Amazon ECS, AWS Lambda, Amazon CloudWatch).
4. WHEN the user selects a service name preset, THE ArchitectureSection SHALL NOT auto-fill the description or category; each field is independently editable.
5. WHEN the user types a custom service name, THE ArchitectureSection SHALL accept the custom value without restriction.

### Requirement 19: Milestones Presets

**User Story:** As a user, I want preset dropdowns for phase names and deliverables in the Milestones tab, so that I can set up project phases quickly.

#### Acceptance Criteria

1. THE MilestonesSection SHALL render an EditableComboField for the `phase` field with 14 phase presets from Preset_Config.
2. THE MilestonesSection SHALL render an EditableComboField for the `deliverables` field with 21 deliverable presets from Preset_Config: Execution Plan, WBS, Requirements Definition Document, Current State Analysis Report, High-Level Architecture, Infra and Data Architecture Definition Document, Architecture Design Document, API Specification, Table Definition Document, Prompt Design Document, RAG Pipeline Code, Development Code, Web Interface, Test Scenarios and Results Document, Performance Analysis, Completion Report, Final Report, Operating Manual, User Manual, Knowledge Transfer Materials, Best Practices Guide.
3. WHEN the user types a custom phase name or deliverable, THE MilestonesSection SHALL accept the custom value without restriction.
4. WHEN the section is empty, THE MilestonesSection SHALL display starter actions per Requirement 6.

### Requirement 20: Cost Breakdown Presets

**User Story:** As a user, I want preset dropdowns for cost categories and notes in the Cost Breakdown tab, so that I can build the cost table faster.

#### Acceptance Criteria

1. THE CostBreakdownSection SHALL render an EditableComboField for the `category` field with 10 cost category presets from Preset_Config: Bedrock, Infra, OpenSearch, Compute, Storage, Database, Network, Monitoring, Security, Total.
2. THE CostBreakdownSection SHALL render an EditableComboField for the `note` field with 7 common cost note presets from Preset_Config: AWS Calculator link, Excel file, Bedrock extra estimate, Included in AWS Calculator, Estimated based on token usage, Estimated based on active users and daily queries, Estimated based on data volume and retention period.
3. THE CostBreakdownSection SHALL show a placeholder for the `calculator_url` field: `https://calculator.aws/#/estimate?id=...`
4. THE CostBreakdownSection SHALL keep the `mrr` and `arr` fields editable as they currently are.
5. WHEN the user types a custom category or note, THE CostBreakdownSection SHALL accept the custom value without restriction.

### Requirement 21: Resources & Cost Estimates Presets

**User Story:** As a user, I want preset dropdowns for roles and rates in the Resources & Cost Estimates tab, so that I can build the staffing table faster.

#### Acceptance Criteria

1. THE ResourcesCostEstimatesSection SHALL render an EditableComboField for the `role` field in the partner technical team table with 19 role presets from Preset_Config: PM, Project Manager, Project QA, PMO, Solution Architect, Solutions Architect, Sr. Solutions Architect, AI Agent Architect, AI Service Engineer, AI & Data Engineer, GenAI Engineer, Data Engineer, RAG Developer, UI Engineer, Web Designer, Security SA, Consultant, Advisor, Customer Contact.
2. THE ResourcesCostEstimatesSection SHALL provide 10 rate presets from Preset_Config for the rate fields: 65, 80, 81.78, 93, 100, 112.45, 115, 116, 150, 156.25. Rate presets SHALL be displayed as numbers. THE implementation SHALL persist numeric values if the schema expects numeric values. THE implementation SHALL NOT persist formatted strings like "$81.78" unless the existing schema expects strings.
3. THE ResourcesCostEstimatesSection SHALL reuse phase presets (PROJECT_PHASE_PRESETS) from Preset_Config for the phase hours table.
4. THE ResourcesCostEstimatesSection SHALL always display the three contribution parties: Customer, Partner, AWS.
5. WHEN the user types a custom role or rate, THE ResourcesCostEstimatesSection SHALL accept the custom value without restriction.

### Requirement 22: Acceptance Tab Presets

**User Story:** As a user, I want a one-click "Apply standard acceptance process" button that fills in common acceptance steps, so that I do not have to type them from scratch.

#### Acceptance Criteria

1. THE AcceptanceSection SHALL provide an "표준 인수 프로세스 적용" (Apply standard acceptance process) button when the section is empty or as a persistent action.
2. WHEN the user clicks the button, THE AcceptanceSection SHALL insert 8 preset acceptance steps from Preset_Config, each with a heading and content: Deliverable Submission and Review, Review Period, Acceptance Confirmation, Rejection Process, Correction and Resubmission, Secondary Review, Automatic Acceptance, Final Project Acceptance.
3. THE AcceptanceSection SHALL persist the applied steps as `user_input` values with `status: "draft"` and `user_edited: true`.
4. THE AcceptanceSection SHALL NOT auto-insert any acceptance steps when the tab is opened.
5. WHEN the user edits a heading, content, or bullet after applying the preset, THE AcceptanceSection SHALL save the edited value normally.
6. WHEN the section is empty, THE AcceptanceSection SHALL display starter actions per Requirement 6.

### Requirement 23: Preset Persistence Policy

**User Story:** As a developer, I want a clear persistence policy for presets, so that fixed defaults, user-applied presets, and placeholders are handled consistently.

#### Acceptance Criteria

1. THE Document_Store SHALL persist fixed defaults using the FieldValue shape: `{calculated: <value>, status: "confirmed", user_edited: false}`.
2. THE Document_Store SHALL persist user-applied presets using the FieldValue shape: `{user_input: <value>, status: "draft", user_edited: true}`.
3. THE Document_Store SHALL NOT persist placeholder text or hint text to the backend.
4. WHEN a user opens a tab, THE Document_Store SHALL NOT automatically persist any preset values solely because the tab was opened.
5. THE Document_Store SHALL persist preset values only when the user explicitly triggers an Add, Apply, or Select action.
6. FOR add and delete operations on arrays (e.g., adding or removing a stakeholder row, a CategoryGroup, or an AcceptanceStep), THE implementation SHALL persist the full updated array to the parent dot-path (e.g., `sections.stakeholders.executive_sponsors`, `sections.success_criteria.groups`, `sections.acceptance.steps`).

### Requirement 24: Immediate Save Behavior Preservation

**User Story:** As a user, I want the existing save-on-blur/Enter behavior preserved, so that my edits are saved immediately without needing section-level Save buttons.

#### Acceptance Criteria

1. THE EditableComboField SHALL trigger a save on blur and on Enter keypress, consistent with the existing EditableField behavior.
2. THE Section_Components SHALL NOT add section-level Save buttons.
3. WHEN the user selects a preset from a dropdown and the field loses focus, THE EditableComboField SHALL save the selected value immediately.

### Requirement 25: Writing Guide — Cover

**User Story:** As a user, I want a Korean writing guide for the Cover tab, so that I understand which fields are required for the DOCX and which optional fields help AI generate better content.

#### Acceptance Criteria

1. THE Guide_Config SHALL contain a `cover` entry with the following Korean content:
   - **title**: "Cover 작성 가이드"
   - **purpose**: "표지에는 DOCX 문서에 직접 표시되는 핵심 식별 정보를 입력합니다. 고객사, 파트너, 날짜, 프로젝트명은 문서 표지와 Export 결과에 직접 반영됩니다."
   - **required_fields**: ["고객사: 문서 대상 고객사명입니다. 예: 광동제약, Hanjin, E-mart", "파트너: 기본값은 MegazoneCloud입니다.", "날짜: 문서 기준일 또는 제출일입니다. 예: 2026-04-26", "프로젝트명: 문서 제목이자 프로젝트명입니다."]
   - **optional_fields**: ["산업군: AI가 산업 특화 표현을 생성하는 데 사용합니다.", "프로젝트 배경: Executive Summary 작성 품질을 높입니다.", "주요 목표: Success Criteria와 Scope 작성에 활용됩니다.", "예상 AWS 서비스: Architecture와 Cost Breakdown 작성에 활용됩니다.", "기간/예산 메모: Milestones와 Cost 작성에 활용됩니다."]
   - **tips**: ["필수값은 DOCX 표지에 직접 표시됩니다.", "옵션값은 표지에는 직접 표시되지 않을 수 있지만, AI가 다른 섹션을 더 정확하게 작성하는 데 사용됩니다.", "샘플값은 placeholder로만 보여주고 실제 값으로 저장하지 않습니다."]

### Requirement 26: Writing Guide — Executive Summary

**User Story:** As a user, I want a Korean writing guide for the Executive Summary tab, so that I know how to write a compelling summary for AWS funding reviewers.

#### Acceptance Criteria

1. THE Guide_Config SHALL contain an `executive_summary` entry with the following Korean content:
   - **title**: "Executive Summary 작성 가이드"
   - **purpose**: "고객이 누구인지, 어떤 문제를 가지고 있는지, 이 PoC가 어떤 방식으로 해결할지 요약합니다. AWS 펀딩 검토자는 이 섹션을 통해 비즈니스 가치와 프로젝트 필요성을 빠르게 판단합니다."
   - **recommended_structure**: ["고객 소개: 고객사의 산업, 규모, 주요 사업을 간단히 설명합니다.", "현재 문제점: 수작업, 검색 지연, 데이터 분산, 비용 증가, 보안 우려 등 현재 pain point를 적습니다.", "제안 솔루션: Amazon Bedrock, RAG, OpenSearch, S3 등으로 어떤 해결책을 제안하는지 설명합니다.", "PoC 목표: PoC에서 검증할 기능, 성능, 비용, 보안 목표를 적습니다.", "진행 방식: 몇 개 phase로 진행되는지 간단히 설명합니다.", "비즈니스 효과: 업무 시간 절감, 정확도 향상, 비용 절감, 사용자 만족도 향상 등을 적습니다."]
   - **useful_prompts**: ["이 고객의 현재 문제점과 PoC 목표를 기반으로 Executive Summary 초안을 작성해줘.", "비즈니스 가치와 AWS 사용 이유가 잘 드러나도록 Executive Summary를 보강해줘.", "현재 문장을 APN Project Plan 스타일의 영어 문서로 다듬어줘."]
   - **tips**: ["단순 기술 설명만 쓰지 말고 비즈니스 가치와 고객 pain point를 함께 적습니다.", "정량 목표가 있으면 포함합니다. 예: 검색 시간 30분 → 2분, 정확도 90%, 응답 시간 3초 이하", "AWS 사용 이유와 GenAI 도입 이유가 드러나야 합니다."]

### Requirement 27: Writing Guide — Stakeholders

**User Story:** As a user, I want a Korean writing guide for the Stakeholders tab, so that I know which roles and contacts to include.

#### Acceptance Criteria

1. THE Guide_Config SHALL contain a `stakeholders` entry with the following Korean content:
   - **title**: "Stakeholders 작성 가이드"
   - **purpose**: "프로젝트 의사결정자, 고객 담당자, 파트너 수행팀, 에스컬레이션 담당자를 정리합니다. AWS 제출 문서에서는 누가 후원하고, 누가 수행하고, 누가 승인하는지 명확해야 합니다."
   - **recommended_sections**: ["Partner Executive Sponsor: 파트너 측 임원 후원자입니다. 기본값으로 James, Kong / CAIO / Head of AI Business / jameskong@megazone.com 을 제공합니다.", "Project Stakeholders: 고객 또는 관련 조직의 주요 이해관계자입니다.", "Partner Project Team: 실제 프로젝트를 수행하는 파트너 팀입니다.", "Project Escalation Contacts: 이슈 발생 시 에스컬레이션할 담당자입니다."]
   - **tips**: ["이메일 또는 연락처는 가능한 한 입력합니다.", "Title, Role, Stakeholder For는 드롭다운에서 선택 후 수정할 수 있어야 합니다.", "사람 이름은 프로젝트마다 다르므로 기본 자동 입력은 Partner Executive Sponsor 1명만 사용합니다.", "나머지 인원은 드롭다운 또는 직접 입력으로 추가합니다."]

### Requirement 28: Writing Guide — Success Criteria / KPIs

**User Story:** As a user, I want a Korean writing guide for the Success Criteria tab, so that I know how to define measurable success criteria.

#### Acceptance Criteria

1. THE Guide_Config SHALL contain a `success_criteria` entry with the following Korean content:
   - **title**: "Success Criteria / KPIs 작성 가이드"
   - **purpose**: "PoC가 성공했다고 판단할 수 있는 기준을 정의합니다. 가능하면 정량 목표와 검증 방법을 포함해야 합니다."
   - **recommended_categories**: ["Strategy Development & Planning", "Technical Framework Design", "Implementation Roadmap", "Knowledge Transfer", "Project Objective", "Security and Data Protection Perspective", "RAG Environment and Response Quality Perspective", "Cost Effectiveness Perspective"]
   - **examples**: ["응답 정확도 90% 이상 달성", "평균 응답 시간 3초 이하", "수작업 처리 시간 30% 이상 감소", "RAG 기반 문서 검색 정확도 90% 이상", "핵심 시나리오 테스트 통과율 100%", "월 예상 AWS 비용 범위 내 운영 가능성 검증"]
   - **tips**: ["\"좋아진다\"처럼 추상적인 표현보다 측정 가능한 기준을 사용합니다.", "accuracy, latency, cost, automation rate, user satisfaction 같은 KPI를 포함합니다.", "AWS 펀딩 검토 관점에서는 비즈니스 가치와 프로덕션 전환 가능성이 중요합니다."]

### Requirement 29: Writing Guide — Assumptions & Risks

**User Story:** As a user, I want a Korean writing guide for the Assumptions & Risks tab, so that I know what assumptions and risks to document.

#### Acceptance Criteria

1. THE Guide_Config SHALL contain an `assumptions` entry with the following Korean content:
   - **title**: "Assumptions & Risks 작성 가이드"
   - **purpose**: "프로젝트 수행을 위해 전제한 조건, 고객 제공 필요사항, 기술적 제약, 보안/컴플라이언스 리스크를 정리합니다."
   - **recommended_categories**: ["Business Context", "Technical Environment", "Project Execution", "Scope Boundaries", "Future Considerations", "Security & Compliance", "AWS Service Usage Assumptions"]
   - **examples**: ["고객은 필요한 업무 요구사항과 시스템 문서를 제공합니다.", "주요 이해관계자는 정기 회의와 검토에 참여합니다.", "Amazon Bedrock은 대상 리전에서 사용 가능하다고 가정합니다.", "데이터는 저장 및 전송 시 암호화됩니다.", "실제 운영 배포는 본 PoC 범위에서 제외될 수 있습니다.", "OpenSearch 사이징은 데이터량과 검색 요구사항을 기반으로 검증합니다."]
   - **tips**: ["고객이 제공해야 하는 데이터, 문서, 담당자, 일정 조건을 명확히 적습니다.", "금융, 헬스케어, 공공, 보험 등 규제 산업은 보안과 거버넌스 가정을 반드시 포함합니다.", "AWS 서비스 사용 가정은 비용 산정과 연결되어야 합니다."]

### Requirement 30: Writing Guide — Scope of Work

**User Story:** As a user, I want a Korean writing guide for the Scope of Work tab, so that I know how to define in-scope and out-of-scope work.

#### Acceptance Criteria

1. THE Guide_Config SHALL contain a `scope_of_work` entry with the following Korean content:
   - **title**: "Scope of Work 작성 가이드"
   - **purpose**: "프로젝트에서 수행할 작업과 제외할 작업을 명확히 정의합니다. 일정, 세부 작업, 담당 인력, 산출물을 함께 작성하면 좋습니다."
   - **recommended_categories**: ["Assessment and Analysis", "Analysis/Design", "AI Solution Design", "Integration Planning", "Development", "Verification and Enhancement", "PoC Results and Cost Analysis", "Documentation & Knowledge Transfer", "Deployment", "Operation / Stabilization"]
   - **common_details**: ["고객 요구사항 분석", "아키텍처 설계", "AWS 인프라 구성", "데이터 전처리 및 인덱싱", "RAG 파이프라인 개발", "Prompt 개발", "GenAI Backend API 개발", "Frontend 개발", "시나리오 기반 검증", "고객 피드백 반영", "사용자 교육 및 지식 이전"]
   - **tips**: ["In-Scope와 Out-of-Scope를 구분합니다.", "실제 구현이 제외되는 컨설팅/설계형 PoC라면 명확히 적습니다.", "각 작업은 Milestones와 Deliverables 섹션과 일관되어야 합니다."]

### Requirement 31: Writing Guide — Architecture

**User Story:** As a user, I want a Korean writing guide for the Architecture tab, so that I know how to document AWS services and ensure consistency with cost breakdown.

#### Acceptance Criteria

1. THE Guide_Config SHALL contain an `architecture` entry with the following Korean content:
   - **title**: "Architecture 작성 가이드"
   - **purpose**: "PoC에서 사용할 AWS 서비스와 각 서비스의 역할을 설명합니다. 아키텍처 다이어그램과 비용 산정이 서로 일치해야 합니다."
   - **recommended_services**: ["Amazon Bedrock", "Amazon OpenSearch Service", "Amazon S3", "Amazon RDS", "Amazon ECS", "AWS Lambda", "Amazon API Gateway", "Amazon CloudWatch", "AWS IAM", "AWS KMS", "VPC", "Elastic Load Balancing", "AWS WAF", "AWS Glue Data Catalog", "Amazon Athena", "Amazon SageMaker"]
   - **tips**: ["다이어그램에 있는 서비스는 Cost Breakdown에도 반영되어야 합니다.", "Cost Breakdown에 있는 서비스는 Architecture에도 설명되어야 합니다.", "Bedrock 사용 목적, OpenSearch 사용 목적, S3 데이터 저장 목적은 명확히 적습니다.", "월 $5,000 이상 주요 서비스는 사이징 근거를 적는 것이 좋습니다."]

### Requirement 32: Writing Guide — Milestones

**User Story:** As a user, I want a Korean writing guide for the Milestones tab, so that I know how to define project phases and deliverables.

#### Acceptance Criteria

1. THE Guide_Config SHALL contain a `milestones` entry with the following Korean content:
   - **title**: "Milestones 작성 가이드"
   - **purpose**: "프로젝트 phase, 예상 완료일, 산출물을 정리합니다. Scope of Work와 일정 및 산출물이 일치해야 합니다."
   - **recommended_phases**: ["Assessment and Analysis", "Analysis/Design", "AI Solution Design", "Integration Planning", "Development", "Verification and Enhancement", "Documentation & Knowledge Transfer", "Deployment", "Operation / Stabilization", "Implementation", "Testing", "Open"]
   - **common_deliverables**: ["Execution Plan", "WBS", "Requirements Definition Document", "Architecture Design Document", "API Specification", "Prompt Design Document", "RAG Pipeline Code", "Test Scenarios and Results Document", "Performance Analysis", "Completion Report", "Operating Manual", "User Manual", "Knowledge Transfer Materials"]
   - **tips**: ["날짜가 확정되지 않았다면 주차 또는 phase 기반으로 작성할 수 있습니다.", "각 phase의 deliverable은 Acceptance와 연결됩니다.", "너무 많은 산출물을 넣기보다 AWS 제출에 필요한 핵심 산출물을 명확히 적습니다."]

### Requirement 33: Writing Guide — Cost Breakdown

**User Story:** As a user, I want a Korean writing guide for the Cost Breakdown tab, so that I know how to document AWS costs for funding review.

#### Acceptance Criteria

1. THE Guide_Config SHALL contain a `cost_breakdown` entry with the following Korean content:
   - **title**: "Cost Breakdown 작성 가이드"
   - **purpose**: "예상 AWS 비용과 비용 산정 근거를 정리합니다. AWS 펀딩 검토에서는 AWS Calculator 링크, Bedrock 별도 산정, ARR/MRR, 서비스별 비용 근거가 중요합니다."
   - **required_information**: ["AWS Pricing Calculator URL", "MRR", "ARR", "서비스별 비용 표", "Bedrock token cost 또는 별도 Excel 산정", "비용 산정 가정"]
   - **common_categories**: ["Bedrock", "Infra", "OpenSearch", "Compute", "Storage", "Database", "Network", "Monitoring", "Security", "Total"]
   - **tips**: ["Bedrock이 AWS Calculator에 없거나 별도 산정이 필요한 경우 별도 note로 작성합니다.", "아키텍처에 있는 서비스와 비용표의 서비스가 일치해야 합니다.", "사용량 가정이 있으면 함께 적습니다. 예: 사용자 수, 일 요청 수, 입력/출력 토큰 수, 문서 수", "GenAI IC 펀딩은 ARR, SOW Cost, 최대 한도 기준과 연결되므로 수치가 명확해야 합니다."]

### Requirement 34: Writing Guide — Resources & Cost Estimates

**User Story:** As a user, I want a Korean writing guide for the Resources & Cost Estimates tab, so that I know how to document staffing, rates, and cost sharing.

#### Acceptance Criteria

1. THE Guide_Config SHALL contain a `resources_cost_estimates` entry with the following Korean content:
   - **title**: "Resources & Cost Estimates 작성 가이드"
   - **purpose**: "파트너 수행 인력, 역할별 rate, phase별 투입 시간, 총 비용, 비용 분담 구조를 정리합니다."
   - **recommended_roles**: ["PM", "Project Manager", "Project QA", "PMO", "Solution Architect", "Sr. Solutions Architect", "AI Agent Architect", "AI Service Engineer", "AI & Data Engineer", "GenAI Engineer", "Data Engineer", "UI Engineer", "Web Designer", "Security SA", "Consultant", "Advisor"]
   - **contribution_parties**: ["Customer", "Partner", "AWS"]
   - **tips**: ["역할과 phase는 Scope/Milestones와 일치해야 합니다.", "rate와 total hours를 기반으로 total cost가 계산되어야 합니다.", "Customer, Partner, AWS 비용 분담을 명확히 적습니다.", "Client signature 정보는 문서 제출 전 확인이 필요합니다."]

### Requirement 35: Writing Guide — Acceptance

**User Story:** As a user, I want a Korean writing guide for the Acceptance tab, so that I know how to define the acceptance process.

#### Acceptance Criteria

1. THE Guide_Config SHALL contain an `acceptance` entry with the following Korean content:
   - **title**: "Acceptance 작성 가이드"
   - **purpose**: "산출물 제출, 고객 검토, 승인, 반려, 수정 및 재제출, 자동 승인 조건을 정의합니다."
   - **recommended_steps**: ["Deliverable Submission and Review", "Review Period", "Acceptance Confirmation", "Rejection Process", "Correction and Resubmission", "Secondary Review", "Automatic Acceptance", "Final Project Acceptance"]
   - **tips**: ["검토 기간은 보통 8 business days 또는 고객과 합의한 기간을 사용합니다.", "각 phase 산출물이 acceptance 대상이 됩니다.", "반려 시 고객은 사유를 제공하고, 파트너는 수정 후 재제출합니다.", "기간 내 반려가 없으면 자동 승인되는 조항을 포함할 수 있습니다."]

### Requirement 36: Validation Constraints

**User Story:** As a developer, I want validation limited to `npm run build`, so that no live AWS services are invoked during development testing.

#### Acceptance Criteria

1. THE build process SHALL pass `npm run build` without errors after all changes are applied.
2. THE implementation SHALL NOT invoke Terraform, CDK, Lambda, S3 upload, Bedrock, AgentCore, Gateway, or AppSync live calls during validation.
3. THE implementation SHALL NOT run AWS live tests.
