# Implementation Plan: Document Presets & Writing Guides

## Overview

This plan implements preset dropdowns, writing guides, numbered tabs, improved empty states, and fixed defaults across all 11 document tabs. Tasks are ordered: backend prerequisites → frontend defaults → config files → shared components → DocumentPanel → per-section updates → build verification → commit. Validation is `npm run build` only — no test dependencies, no live AWS calls.

## Tasks

- [x] 1. Confirm backend direct array/object replacement support
  - [x] 1.1 Verify `_handle_user_input` in `agent/lambdas/document_api/handler.py` supports direct array/object replacement
    - The v2 migration added a code path: if `isinstance(value, (list, dict))` and path does NOT end with `.user_input`, it walks the doc dict via `_path_parts(path)` and sets the value directly without FieldValue wrapping
    - Confirm this code path exists and correctly handles paths like `sections.stakeholders.executive_sponsors`, `sections.success_criteria.groups`, `sections.assumptions.groups`, `sections.acceptance.steps`, `sections.milestones.phases`, `sections.cost_breakdown.breakdown_table`, `sections.resources_cost_estimates.partner_technical_team`
    - Report the exact function name and line range where this code path exists
    - If the code path is missing or incomplete, implement it before proceeding
    - Arrays such as groups, executive_sponsors, steps, phases, breakdown_table, and partner_technical_team must be persisted as raw arrays, NOT wrapped as FieldValue
    - Do not proceed to frontend array add/delete work until this is confirmed working
    - _Requirements: 23.6_

- [x] 2. Add backend title update support
  - [x] 2.1 Add a `title` path handler in `_handle_user_input` in `agent/lambdas/document_api/handler.py`
    - Currently `_path_parts` validates the path, but the array/object branch requires `parts[0]` to be in `{"meta", "sections", "staffing_plan"}` — `title` is a top-level key and would be rejected
    - Add a new branch before the array/object check: when `path` is `"title"` and value is a string, update `doc_dict["title"]` directly (not wrapped in FieldValue)
    - Generate a `replace` patch operation with path `"/title"`
    - Save via `_conditional_save_document` and publish patch via AppSync
    - This allows the Cover tab to persist project name to `DocumentState.title` using the existing `saveUserInput` API
    - _Requirements: 9.4_

- [x] 3. Add backend shared new-document defaults
  - [x] 3.1 Create shared default helpers in `agent/lambdas/document_api/handler.py`
    - Create `_default_meta()` returning meta dict with: `customer` as empty FieldValue, `partner` as `{"user_input": None, "ai_recommended": None, "calculated": "MegazoneCloud", "status": "confirmed", "user_edited": False}`, `date` as empty FieldValue
    - Create `_default_sections()` returning sections dict with: `stakeholders.executive_sponsors` containing one default ContactEntry (name="James, Kong", title="CAIO", description="Head of AI Business", contact="jameskong@megazone.com" — each as FieldValue with `calculated` set, `status: "confirmed"`, `user_edited: False`; `stakeholder_for` and `role` as empty FieldValue), plus empty arrays for `stakeholders`, `project_team`, `escalation_contacts`
    - _Requirements: 7.1, 7.2, 8.1, 8.2_
  - [x] 3.2 Update `_document_shell` to use shared defaults
    - Replace `"meta": {}` with `"meta": _default_meta()`
    - Replace `"sections": {}` with `"sections": _default_sections()`
    - _Requirements: 7.2, 8.2_
  - [x] 3.3 Update `_handle_create_document` to use shared defaults
    - Replace `"meta": {}` with `"meta": _default_meta()`
    - Replace `"sections": {}` with `"sections": _default_sections()`
    - _Requirements: 7.2, 8.2_

- [x] 4. Update frontend defaults in INITIAL_STATE
  - [x] 4.1 Update `INITIAL_STATE` in `front/src/store/documentStore.ts`
    - Set `meta.partner` to `{user_input: null, ai_recommended: null, calculated: "MegazoneCloud", status: "confirmed", user_edited: false}`
    - Keep `meta.customer` and `meta.date` as `emptyField()`
    - Do NOT add the default executive sponsor row in INITIAL_STATE — it comes from the backend via `getDocument`/`setDocument`
    - Frontend defaults exist only in INITIAL_STATE for immediate UI display before backend data loads
    - After `getDocument`/`setDocument`, backend state is respected as-is — do not re-inject defaults
    - _Requirements: 7.1, 7.4, 7.5, 8.6_

- [x] 5. Create preset configuration file
  - [x] 5.1 Create `front/src/constants/documentPresets.ts`
    - Export all `as const` arrays with exact values from requirements:
    - `INDUSTRY_PRESETS` (12): Healthcare, Finance / Insurance, Retail / Commerce, Manufacturing, Logistics, Gaming, Construction, Automotive, Public Sector, Education, Food / Beverage, Fashion
    - `AWS_SERVICE_PRESETS` (10): Amazon Bedrock, Amazon OpenSearch Service, Amazon S3, Amazon RDS, Amazon ECS, AWS Lambda, Amazon API Gateway, Amazon CloudWatch, AWS IAM, AWS KMS
    - `EXEC_SUMMARY_STARTER_BLOCKS` (9): Who is the customer?, What problems is the customer facing?, What is the proposed solution?, How will the project be carried out?, Current Pain Points, PoC Objectives, Business Objectives, Technical Objectives, Drivers for Moving to AWS Cloud
    - `PAIN_POINT_PRESETS` (8): Manual and repetitive work consumes significant time, Existing search process is slow and inefficient, Current process depends heavily on individual knowledge, Data is scattered across multiple systems or documents, Public AI usage creates data leakage concerns, Current system has accuracy latency or scalability limitations, Existing workflow lacks automation and standardization, Support requests are expected to increase after system launch
    - `POC_OBJECTIVE_PRESETS` (8): Validate Amazon Bedrock-based GenAI capability, Build and verify a RAG-based knowledge search workflow, Validate response accuracy and latency, Validate scalable AWS architecture, Validate secure data processing and access control, Measure business efficiency improvement, Provide technical documentation and knowledge transfer, Define production-readiness criteria
    - `TITLE_PRESETS` (20): "CAIO", "VP, ADC", "VP, ADU", "Director, Business", "Director", "Senior Director", "Unit Leader", "Team Leader", "Delivery Manager", "Project Manager", "Manager", "Sr. Solutions Architect", "Solutions Architect", "AI & Data Engineer", "Data Engineer", "AI Agent Architect", "AI Service Engineer", "Web Designer", "Security SA", "Consultant"
    - `DESCRIPTION_PRESETS` (12), `STAKEHOLDER_FOR_PRESETS` (12), `ROLE_PRESETS` (25) — exact values from Requirement 13
    - `SUCCESS_CRITERIA_PRESET_GROUPS` (8 groups) — exact values from Requirement 15
    - `ASSUMPTIONS_PRESET_GROUPS` (7 groups) — exact values from Requirement 16
    - `TASK_CATEGORY_PRESETS` (14), `PERSONNEL_PRESETS` (12), `DELIVERABLE_PHRASE_PRESETS` (16) — exact values from Requirement 17
    - `SCHEDULE_PATTERN_PRESETS` (11): "-", "1st Week", "1st Week ~ 2nd Week", "2nd Week", "3rd Week ~ 5th Week", "6th Week", "Jun 2, 2025 - Jun 6, 2025", "Jun 9, 2025 - Jun 20, 2025", "Jun 23, 2025 - July 11, 2025", "July 14, 2025 - July 18, 2025", "TBD"
    - `SERVICE_NAME_PRESETS` (22), `SERVICE_DESCRIPTION_PRESETS` (keyed by service name) — exact values from Requirement 18
    - `PROJECT_PHASE_PRESETS` (14), `MILESTONE_DELIVERABLE_PRESETS` (21) — exact values from Requirement 19
    - `COST_CATEGORY_PRESETS` (10), `COST_NOTE_PRESETS` (7) — exact values from Requirement 20
    - `RESOURCE_ROLE_PRESETS` (19), `RATE_PRESETS` (10 numeric values: 65, 80, 81.78, 93, 100, 112.45, 115, 116, 150, 156.25) — exact values from Requirement 21
    - `ACCEPTANCE_STEP_PRESETS` (8 steps with heading + content) — exact values from Requirement 22
    - Export `PresetGroup` and `AcceptanceStepPreset` interfaces
    - Export `presetToFieldValue` and `presetGroupToCategoryGroup` helper functions
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

- [x] 6. Create writing guide configuration file
  - [x] 6.1 Create `front/src/constants/documentGuides.ts`
    - Export `GuideBlock`, `DocumentGuide` type interfaces
    - Export `DOCUMENT_GUIDES` record with all 11 section entries using the `GuideBlock` structure
    - Use the exact Korean content from Requirements 25–35: cover, executive_summary, stakeholders, success_criteria, assumptions, scope_of_work, architecture, milestones, cost_breakdown, resources_cost_estimates, acceptance
    - Each content group becomes a `GuideBlock` with `heading` + `items`
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [x] 7. Create shared components
  - [x] 7.1 Extract shared save helper from `FieldValueEditor` into `front/src/hooks/useFieldSave.ts`
    - Create a `useFieldSave` hook that encapsulates the `useSaveStatus` + `saveUserInput` + optimistic `onLocalUpdate` pattern
    - The hook should accept `docId` and return `{ saveStatus, handleSave }` where `handleSave(dotPath, newValue, field, onLocalUpdate)` performs the optimistic update + API save
    - Refactor `FieldValueEditor` in `front/src/components/editors/FieldValueEditor.tsx` to use `useFieldSave` instead of inline save logic
    - Both `FieldValueEditor` and `EditableComboField` must use this same shared hook — no independent save implementations
    - _Requirements: 5.5, 5.7, 5.9_

  - [x] 7.2 Create `EditableComboField` component at `front/src/components/editors/EditableComboField.tsx`
    - Accept props: `field`, `dotPath`, `docId`, `placeholder`, `multiline`, `presets`, `onLocalUpdate` (same interface as `FieldValueEditor` plus `presets`)
    - `presets` prop type: `readonly (string | number)[]` to support both string presets and numeric rate presets
    - Wrap `EditableField` for text editing behavior
    - Add dropdown trigger button (▾) that opens a preset list
    - Selecting a preset populates the text input; save on blur/Enter via the shared `useFieldSave` hook
    - Custom values always accepted without restriction
    - If `presets` array is empty, hide dropdown trigger and behave like `FieldValueEditor`
    - When saving numeric presets (e.g., rate values), preserve the numeric value — do not persist formatted strings like "$81.78"
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 24.1, 24.3_

  - [x] 7.3 Create `SectionGuideButton` component at `front/src/components/SectionGuideButton.tsx`
    - Accept `sectionKey` prop
    - Render ⓘ icon inline next to section heading
    - On click, toggle a popover displaying `DOCUMENT_GUIDES[sectionKey]` content: title, purpose, blocks (heading + items), useful_prompts, tips
    - Click again or click outside closes the popover
    - If `DOCUMENT_GUIDES[sectionKey]` is undefined, do not render the icon
    - No backend calls, no persistence
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8_

- [x] 8. Update DocumentPanel with numbered tab labels
  - [x] 8.1 Update `TABS` array and `TAB_COMPONENTS` mapping in `front/src/components/DocumentPanel.tsx`
    - Change TABS to: "1. Cover", "2.1 Executive Summary", "2.2 Stakeholders", "2.3 Success Criteria / KPIs", "2.4 Assumptions & Risks", "2.5 Scope of Work", "2.6 Architecture", "2.7 Milestones", "2.8 Cost Breakdown", "2.9 Resources & Cost Estimates", "2.10 Acceptance"
    - Update `TAB_COMPONENTS` record keys to match the new numbered labels
    - Update `TabName` type accordingly
    - _Requirements: 1.1, 1.2, 1.3_

- [x] 9. Update CoverSection
  - [x] 9.1 Update `front/src/components/sections/CoverSection.tsx`
    - Change `<h2>` to "1. Cover" and add `SectionGuideButton` with `sectionKey="cover"`
    - Split fields into two visual groups: "Required for DOCX Cover" (고객사, 파트너, 날짜, 프로젝트명) and "Optional Agent Context" (산업군, 프로젝트 배경, 주요 목표, 예상 AWS 서비스, 기간/예산 메모)
    - 프로젝트명 field saves to `DocumentState.title` via `saveUserInput(docId, "title", value)` (enabled by Task 2)
    - Add `EditableComboField` for `sections.cover.industry` with `INDUSTRY_PRESETS`
    - Add `EditableComboField` for `sections.cover.expected_aws_services` with `AWS_SERVICE_PRESETS` — stored as single FieldValue string (comma-separated if multiple)
    - Other optional fields (`project_background`, `main_objectives`, `timeline_budget_notes`) use plain `FieldValueEditor`
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 10.1, 10.2, 10.3, 10.4, 1.4_

- [x] 10. Update ExecutiveSummarySection
  - [x] 10.1 Update `front/src/components/sections/ExecutiveSummarySection.tsx`
    - Change `<h2>` to "2.1 Executive Summary" and add `SectionGuideButton` with `sectionKey="executive_summary"`
    - Replace legacy empty state text with new direct-edit UX: "Executive Summary가 아직 입력되지 않았습니다. 오른쪽 문서에서 직접 입력하거나, 왼쪽 채팅에서 AI에게 작성을 요청할 수 있습니다."
    - Add direct writing helper hint: "예: 고객사의 현재 과제, PoC 목표, 제안 솔루션을 입력하세요."
    - Add AI prompt example: "AI 요청 예시: Executive Summary 초안 작성해줘"
    - Add starter block presets from `EXEC_SUMMARY_STARTER_BLOCKS` — user selects a block, it maps to the corresponding schema field
    - Add preset items for `current_pain_points[]` using `PAIN_POINT_PRESETS`
    - Add preset items for `poc_objectives[]` using `POC_OBJECTIVE_PRESETS`
    - No auto-insertion of preset blocks
    - Empty state actions: starter block presets, 직접 입력, AI에게 초안 요청
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 6.1, 6.3, 6.4, 6.5, 6.8, 1.4_

- [x] 11. Update StakeholdersSection and ContactTableEditor
  - [x] 11.1 Update `front/src/components/sections/StakeholdersSection.tsx`
    - Change `<h2>` to "2.2 Stakeholders" and add `SectionGuideButton` with `sectionKey="stakeholders"`
    - Use fixed section headings: "Partner Executive Sponsor", "Project Stakeholders", "Partner Project Team", "Project Escalation Contacts"
    - Update column configs to include Email / Contact: Partner Executive Sponsor → [name, title, description, contact]; Project Stakeholders → [name, title, stakeholder_for, contact]; Partner Project Team → [name, title, role, contact]; Project Escalation Contacts → [name, title, role, contact]
    - Update empty state with section-appropriate starter actions
    - _Requirements: 13.1, 14.1, 14.2, 6.1, 6.2, 1.4_

  - [x] 11.2 Update `front/src/components/editors/ContactTableEditor.tsx` to support `EditableComboField`
    - Accept optional `columnPresets` prop mapping column keys to preset arrays
    - Render `EditableComboField` (with presets) instead of `FieldValueEditor` for columns that have presets
    - Presets for: title → `TITLE_PRESETS`, description → `DESCRIPTION_PRESETS`, stakeholder_for → `STAKEHOLDER_FOR_PRESETS`, role → `ROLE_PRESETS`
    - Custom values always accepted
    - _Requirements: 13.2, 13.3, 13.4, 13.5, 13.6_

- [x] 12. Update SuccessCriteriaSection
  - [x] 12.1 Update `front/src/components/sections/SuccessCriteriaSection.tsx`
    - Change `<h2>` to "2.3 Success Criteria / KPIs" and add `SectionGuideButton` with `sectionKey="success_criteria"`
    - Add preset group selector: "프리셋 그룹 추가" button that shows `SUCCESS_CRITERIA_PRESET_GROUPS` for selection
    - On selection, convert preset group to `CategoryGroup` using `presetGroupToCategoryGroup` and add to groups array
    - Persist full groups array via `saveUserInput`
    - Update empty state with starter actions: "프리셋 그룹 추가", "직접 그룹 추가", "AI에게 초안 요청"
    - No auto-insertion on tab open
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 6.1, 6.2, 6.6, 6.7, 6.8, 1.4_

- [x] 13. Update AssumptionsSection
  - [x] 13.1 Update `front/src/components/sections/AssumptionsSection.tsx`
    - Change `<h2>` to "2.4 Assumptions & Risks" and add `SectionGuideButton` with `sectionKey="assumptions"`
    - Add preset group selector: "프리셋 그룹 추가" button that shows `ASSUMPTIONS_PRESET_GROUPS` for selection
    - On selection, convert preset group to `CategoryGroup` and add to groups array
    - Persist full groups array via `saveUserInput`
    - Update empty state with starter actions: "프리셋 그룹 추가", "직접 그룹 추가", "AI에게 초안 요청"
    - No auto-insertion on tab open
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 6.1, 6.2, 6.6, 6.7, 6.8, 1.4_

- [x] 14. Update ScopeOfWorkSection
  - [x] 14.1 Update `front/src/components/sections/ScopeOfWorkSection.tsx`
    - Change `<h2>` to "2.5 Scope of Work" and add `SectionGuideButton` with `sectionKey="scope_of_work"`
    - Replace `FieldValueEditor` with `EditableComboField` for: `task_category` → `TASK_CATEGORY_PRESETS`, `personnel` → `PERSONNEL_PRESETS`, `details` → `DELIVERABLE_PHRASE_PRESETS`, `schedule` → `SCHEDULE_PATTERN_PRESETS`
    - Update empty state with section-appropriate starter actions
    - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 6.1, 6.2, 1.4_

- [x] 15. Update ArchitectureSection
  - [x] 15.1 Update `front/src/components/sections/ArchitectureSection.tsx`
    - Change `<h2>` to "2.6 Architecture" and add `SectionGuideButton` with `sectionKey="architecture"`
    - Replace `FieldValueEditor` for `service_name` with `EditableComboField` using `SERVICE_NAME_PRESETS`
    - Add `EditableComboField` for `description` with `SERVICE_DESCRIPTION_PRESETS` (keyed by service name, fallback to empty)
    - Category `<select>` already uses `SERVICE_CATEGORIES` — no change needed
    - Selecting a service name preset does NOT auto-fill description or category
    - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 1.4_

- [x] 16. Update MilestonesSection
  - [x] 16.1 Update `front/src/components/sections/MilestonesSection.tsx`
    - Change `<h2>` to "2.7 Milestones" and add `SectionGuideButton` with `sectionKey="milestones"`
    - Replace `FieldValueEditor` for `phase` with `EditableComboField` using `PROJECT_PHASE_PRESETS`
    - Replace `FieldValueEditor` for `deliverables` with `EditableComboField` using `MILESTONE_DELIVERABLE_PRESETS`
    - Update empty state with section-appropriate starter actions
    - _Requirements: 19.1, 19.2, 19.3, 19.4, 6.1, 6.2, 1.4_

- [x] 17. Update CostBreakdownSection
  - [x] 17.1 Update `front/src/components/sections/CostBreakdownSection.tsx`
    - Change `<h2>` to "2.8 Cost Breakdown" and add `SectionGuideButton` with `sectionKey="cost_breakdown"`
    - Replace `FieldValueEditor` for `category` with `EditableComboField` using `COST_CATEGORY_PRESETS`
    - Replace `FieldValueEditor` for `note` with `EditableComboField` using `COST_NOTE_PRESETS`
    - Add placeholder `https://calculator.aws/#/estimate?id=...` for `calculator_url` field
    - Keep `mrr` and `arr` as plain `FieldValueEditor`
    - _Requirements: 20.1, 20.2, 20.3, 20.4, 20.5, 1.4_

- [x] 18. Update ResourcesCostEstimatesSection
  - [x] 18.1 Update `front/src/components/sections/ResourcesCostEstimatesSection.tsx`
    - Change `<h2>` to "2.9 Resources & Cost Estimates" and add `SectionGuideButton` with `sectionKey="resources_cost_estimates"`
    - Replace `FieldValueEditor` for team member `role` with `EditableComboField` using `RESOURCE_ROLE_PRESETS`
    - Add `EditableComboField` for rate fields using `RATE_PRESETS` (numeric values — persist as numbers, not formatted strings)
    - Reuse `PROJECT_PHASE_PRESETS` for phase hours table phase field via `EditableComboField`
    - Always display 3 contribution parties: Customer, Partner, AWS (already implemented)
    - _Requirements: 21.1, 21.2, 21.3, 21.4, 21.5, 1.4_

- [x] 19. Update AcceptanceSection
  - [x] 19.1 Update `front/src/components/sections/AcceptanceSection.tsx`
    - Change `<h2>` to "2.10 Acceptance" and add `SectionGuideButton` with `sectionKey="acceptance"`
    - Add "표준 인수 프로세스 적용" button in empty state and as persistent action
    - On click, insert 8 preset acceptance steps from `ACCEPTANCE_STEP_PRESETS`, each with heading and content as `user_input` FieldValues with `status: "draft"` and `user_edited: true`
    - Persist full steps array via `saveUserInput`
    - No auto-insertion on tab open
    - Update empty state with starter actions: "표준 인수 프로세스 적용", "직접 단계 추가", "AI에게 초안 요청"
    - _Requirements: 22.1, 22.2, 22.3, 22.4, 22.5, 22.6, 6.1, 6.2, 6.8, 1.4_

- [x] 20. Build verification
  - Run `npm run build` in `front/` directory and ensure zero errors.
  - Verify all imports resolve correctly (new config files, new components, updated sections).
  - Fix any TypeScript compilation or Vite build errors before proceeding.

- [x] 21. Commit and push
  - Stage all modified and new files
  - Commit with message: `feat: add document presets, writing guides, and numbered tabs`
  - Push to feature branch

## Notes

- Validation is `npm run build` only — no test dependencies, no live AWS calls (Requirement 36).
- All presets work within the existing v2 DocumentState schema — no schema changes needed.
- `expected_aws_services` remains a single FieldValue string (comma-separated), not an array.
- Project name is stored in `DocumentState.title`, not `sections.cover.project_name`.
- Save-on-blur/Enter behavior is preserved everywhere — no section-level Save buttons.
- Array add/delete operations persist the full array to the parent dot-path.
- Presets are suggestions only — custom values are always accepted.
- `EditableComboField` reuses the same save pattern as `FieldValueEditor` via a shared `useFieldSave` hook — no independent save implementation.
- Frontend defaults are for immediate UI display only — backend data from `getDocument`/`setDocument` overwrites them. Do not re-inject defaults after backend data loads.
- `RATE_PRESETS` are numeric values. Display as numbers. Persist numeric values if the schema expects numbers. Do not persist formatted strings like "$81.78".
- Do not stop for minor questions. Make reasonable implementation choices and report them. Stop only for true blockers.
