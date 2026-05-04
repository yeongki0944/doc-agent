# Implementation Plan: Frontend V2 Direct Edit

## Overview

Migrate the frontend DocumentPanel and all section editors to the backend DocumentState v2 schema. This involves a backend prerequisite (array save support), type model updates, tab restructuring, shared editor components, and section-by-section rewrites. Validation is `npm run build` only — no test frameworks, no AWS deployments.

## Tasks

- [x] 1. Update backend user-input handler for v2 compatibility
  - [x] 1.1 Fix `_field_value_with_user_input` in `agent/lambdas/document_api/handler.py` to use v2 status
    - Change `field["status"] = "user_modified"` to `field["status"] = "draft"`
    - This ensures all scalar user edits produce v2-compliant FieldValues with status `"draft"`
    - _Requirements: 1.2, 1.3_
  - [x] 1.2 Add direct array/object replacement support in `_handle_user_input` in `agent/lambdas/document_api/handler.py`
    - Before the `_set_user_input_field` call, add a condition: if the path does NOT end with `.user_input` and `isinstance(value, (list, dict))`, handle as direct replacement
    - Parse the path using `_path_parts(path)` to get path segments (do NOT pass raw dot-path to `_set_nested`)
    - Walk the nested dict using the parsed parts to find the parent dict
    - Set the value directly at the target key: `parent[parts[-1]] = value`
    - Build a JSON Pointer patch path: `"/" + "/".join(parts)`
    - Generate a single `replace` patch operation for the full path
    - Save the document with `_conditional_save_document` and publish the patch via AppSync
    - Keep the existing FieldValue-wrapping behavior for scalar values and paths ending in `.user_input`
    - _Requirements: 18.1, 18.2, 18.3_

- [x] 2. Update frontend DocumentState types to v2
  - [x] 2.1 Update `FieldStatus` and `FieldValue` in `front/src/store/documentStore.ts`
    - Add `export type FieldStatus = 'empty' | 'draft' | 'confirmed'`
    - Change `FieldValue.status` type from `string` to `FieldStatus`
    - Remove `reason` property from `FieldValue` if present
    - Update `createFieldValue` helper to accept `FieldStatus` parameter
    - Update `emptyField()` factory to include `user_edited: false`
    - _Requirements: 1.1, 1.3, 1.4_
  - [x] 2.2 Add new interfaces to `front/src/store/documentStore.ts`
    - Add `ContactEntry` (6 FieldValue fields: name, title, description, stakeholder_for, role, contact)
    - Add `TeamMember` (role, name)
    - Add `Phase` (phase, completion_date, deliverables)
    - Add `AcceptanceStep` (heading, content, bullets)
    - Add `CostBreakdownRow` (category, mrr, arr, note)
    - Add `ContributionEntry` (amount, pct), `Contribution` (customer, partner, aws)
    - Add `PhaseHours` (phase FieldValue, sa_hours/eng_hours/other_hours/total numbers)
    - Add `TotalsRow` (sa, eng, other, total strings)
    - Add `StakeholdersSection`, `ResourcesCostEstimatesSection`, `AcceptanceSectionData`, `MilestonesSectionData` interfaces
    - _Requirements: 9.1, 14.1, 15.1, 16.1, 17.1, 7.1_
  - [x] 2.3 Update existing interfaces in `front/src/store/documentStore.ts`
    - `CategoryGroup`: rename `items` to `bullets`
    - `ScopeTask`: change `details` from `FieldValue[]` to single `FieldValue`
    - `ExecutiveSummarySection`: add `current_pain_points`, `poc_objectives`, `custom_blocks`; remove `text`, `summary`
    - `ArchitectureSection`: rename `description` → `overview`, `tools` → `tools_list`, `diagram_image_s3_key` as FieldValue; remove index signature
    - `CostBreakdownSection`: replace with v2 fields (calculator_url, mrr, arr, breakdown_table, bedrock_extra, funding_calculation); remove aws_service_cost, staffing_cost, document_local_summary, index signature
    - _Requirements: 4.1, 4.2, 5.1, 6.1, 6.2, 6.3, 7.1, 7.2, 7.3, 21.1, 21.3_
  - [x] 2.4 Remove legacy types and properties from `front/src/store/documentStore.ts`
    - Remove `ClientSignatureSection` interface
    - Remove `DocumentSections.client_signatures` property
    - Remove `DocumentState.staffing_plan` property
    - Remove `StaffingRole` interface and `RoleCategory` type
    - Remove `updateStaffingRole` and `addStaffingRole` store methods
    - Remove `recalculateAll` import from `staffingCalc.ts`
    - _Requirements: 2.1, 3.1, 3.2, 22.3_
  - [x] 2.5 Update `DocumentSections` interface to use new typed section interfaces
    - Replace untyped section entries with: `stakeholders?: StakeholdersSection`, `milestones?: MilestonesSectionData`, `resources_cost_estimates?: ResourcesCostEstimatesSection`, `acceptance?: AcceptanceSectionData`, `cost_breakdown?: CostBreakdownSection`
    - _Requirements: 2.3, 3.1_
  - [x] 2.6 Update `INITIAL_STATE` in `front/src/store/documentStore.ts`
    - Remove `staffing_plan` from initial state
    - Ensure `sections: {}` with no legacy defaults
    - Update `setDocument` method to not merge `staffing_plan`
    - _Requirements: 2.2_

- [x] 3. Update DocumentPanel tab names and order
  - [x] 3.1 Update `front/src/components/DocumentPanel.tsx` with new TABS array and TAB_COMPONENTS mapping
    - Replace TABS with 11 v2 tabs: Cover, Executive Summary, Stakeholders, Success Criteria, Assumptions, Scope of Work, Architecture, Milestones, Cost Breakdown, Resources & Cost Estimates, Acceptance
    - Update TAB_COMPONENTS record to map each tab to its component
    - Remove imports: `OverviewSection`, `ScopeSection`, `TeamSection`, `CostSection`
    - Add imports: `StakeholdersSection`, `CostBreakdownSection`, `ResourcesCostEstimatesSection`
    - Stub new components (`StakeholdersSection`, `CostBreakdownSection`, `ResourcesCostEstimatesSection`) as empty functional components if they don't exist yet, to keep the build passing
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

- [x] 4. Checkpoint — Ensure `npm run build` passes after type and tab changes
  - Run `npm run build` in `front/`. Fix any TypeScript or build errors before proceeding.
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Add shared edit/save helpers
  - [x] 5.1 Create `front/src/hooks/useSaveStatus.ts`
    - Implement `useSaveStatus` hook returning `{ saveStatus, doSave }`
    - `SaveStatus` type: `'idle' | 'saving' | 'saved' | 'failed'`
    - On success: set `'saved'`, auto-reset to `'idle'` after 2 seconds
    - On failure: set `'failed'`, do NOT auto-reset (user must see error)
    - _Requirements: 20.1, 20.2, 20.3, 20.4_
  - [x] 5.2 Create `front/src/components/SaveStatusIndicator.tsx`
    - Render nothing for `'idle'`
    - Show "saving" / "saved" / "failed" states with appropriate colors
    - _Requirements: 20.1, 20.2, 20.3, 20.5_
  - [x] 5.3 Create `front/src/components/editors/FieldValueEditor.tsx`
    - Wrap `EditableField` with optimistic update + `saveUserInput` + `useSaveStatus`
    - Props: `field`, `dotPath`, `docId`, `placeholder`, `multiline`, `type`, `onLocalUpdate`
    - On save: optimistic update must explicitly set `user_input=newValue`, `status='draft'`, `user_edited=true` (do not rely on createFieldValue which may not set user_edited)
    - Display `SaveStatusIndicator` alongside the field
    - _Requirements: 1.2, 19.1, 19.2, 19.3, 19.4, 20.5_
  - [x] 5.4 Create `front/src/components/editors/ListEditor.tsx`
    - Generic editor for `FieldValue[]` lists (tools_list, out_of_scope, items, phases_overview, poc_objectives, current_pain_points)
    - Edit item: dot-path `{listDotPath}.{index}.user_input`
    - Add item: append empty FieldValue (with `user_edited: false`), persist full array to `listDotPath`
    - Remove item: splice, persist full array to `listDotPath`
    - _Requirements: 23.4, 18.1, 18.2_

- [x] 6. Update Cover and Executive Summary sections
  - [x] 6.1 Modify `front/src/components/sections/CoverSection.tsx`
    - Update any `createFieldValue` calls to use v2 status values (`'draft'` instead of `'user_modified'`)
    - Use `FieldValueEditor` for editable fields where applicable
    - _Requirements: 1.2_
  - [x] 6.2 Modify `front/src/components/sections/ExecutiveSummarySection.tsx`
    - Add `current_pain_points[]` and `poc_objectives[]` rendering using `ListEditor` (created in task 5.4)
    - Add `phases_overview[]` rendering using `ListEditor`
    - Render `business_case` nested fields (problem_definition, roi_calculation, executive_sponsor, production_commitment) using `FieldValueEditor`
    - Remove references to legacy `text` and `summary` fields
    - Replace manual `saveUserInput` calls with `FieldValueEditor` for scalar fields
    - Use v2 status values in `createFieldValue` calls
    - _Requirements: 21.1, 21.2, 21.3, 1.2_

- [x] 7. Add Stakeholders editor
  - [x] 7.1 Create `front/src/components/editors/ContactTableEditor.tsx`
    - Render a table of `ContactEntry` rows with configurable visible columns
    - Each cell uses `FieldValueEditor` for inline editing with dot-path `{listDotPath}.{index}.{field}.user_input`
    - Add row: append `createEmptyContactEntry()`, persist full array to `listDotPath` via `saveUserInput`
    - Remove row: splice from array, persist full array to `listDotPath` via `saveUserInput`
    - _Requirements: 9.2, 9.3, 9.4, 18.1, 18.2, 23.2_
  - [x] 7.2 Create `front/src/components/sections/StakeholdersSection.tsx`
    - Read from `sections.stakeholders` in Zustand store
    - Render four `ContactTableEditor` instances: executive_sponsors, stakeholders, project_team, escalation_contacts
    - Each with appropriate column configuration and dot-paths
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

- [x] 8. Replace Success Criteria and Assumptions GenericSection usage
  - [x] 8.1 Create `front/src/components/editors/CategoryGroupEditor.tsx`
    - Render list of `CategoryGroup` entries with editable `category_name` and `bullets[]`
    - Edit category_name: dot-path `{sectionDotPath}.{groupIndex}.category_name.user_input`
    - Edit bullet: dot-path `{sectionDotPath}.{groupIndex}.bullets.{bulletIndex}.user_input`
    - Add bullet to group: append empty FieldValue (with `user_edited: false`), persist full groups array to `sectionDotPath`
    - Add new group: append `createEmptyCategoryGroup()`, persist full groups array
    - Remove group/bullet: splice, persist full groups array
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 18.1, 18.2, 23.1_
  - [x] 8.2 Rewrite `front/src/components/sections/SuccessCriteriaSection.tsx`
    - Replace `GenericSection` usage with `CategoryGroupEditor`
    - Read from `sections.success_criteria.groups`
    - Pass `sectionDotPath = "sections.success_criteria.groups"`
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_
  - [x] 8.3 Rewrite `front/src/components/sections/AssumptionsSection.tsx`
    - Replace `GenericSection` usage with `CategoryGroupEditor`
    - Read from `sections.assumptions.groups`
    - Pass `sectionDotPath = "sections.assumptions.groups"`
    - _Requirements: 11.1, 11.2, 11.3, 11.4_

- [x] 9. Update Scope of Work
  - [x] 9.1 Modify `front/src/components/sections/ScopeOfWorkSection.tsx`
    - Change `ScopeTask.details` handling from `FieldValue[]` to single `FieldValue` — remove `.split('\n')` / `.map()` logic
    - Save details to `sections.scope_of_work.tasks.{index}.details.user_input` as single string
    - Add `out_of_scope` list rendering using `ListEditor` with `listDotPath = "sections.scope_of_work.out_of_scope"`
    - Add `items` list rendering using `ListEditor` with `listDotPath = "sections.scope_of_work.items"`
    - Add/remove ScopeTask rows: persist full tasks array to `sections.scope_of_work.tasks`
    - Use v2 status values in `createFieldValue` / new task creation (`createEmptyScopeTask()`)
    - _Requirements: 5.1, 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 18.1_

- [x] 10. Checkpoint — Ensure `npm run build` passes after editor components and section rewrites
  - Run `npm run build` in `front/`. Fix any TypeScript or build errors.
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Update Architecture editor
  - [x] 11.1 Modify `front/src/components/sections/ArchitectureSection.tsx`
    - Add `FieldValueEditor` for `overview` field (dot-path: `sections.architecture.overview.user_input`)
    - Add inline editing for each service's 6 fields: `service_name`, `description`, `sizing_rationale`, `priority`, `category`, `is_required_for_funding`
    - Add add/remove for services array: persist full array to `sections.architecture.services`
    - Add `ListEditor` for `tools_list` with `listDotPath = "sections.architecture.tools_list"`
    - Keep existing drawio upload/preview functionality
    - Remove fallback rendering of arbitrary key-value pairs
    - _Requirements: 6.1, 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7, 18.1_

- [x] 12. Update Milestones
  - [x] 12.1 Rewrite `front/src/components/sections/MilestonesSection.tsx`
    - Read from `sections.milestones.phases[]` instead of hardcoded PHASES constant
    - Render table of `Phase` entries with `FieldValueEditor` for `phase`, `completion_date`, `deliverables`
    - Dot-paths: `sections.milestones.phases.{index}.{field}.user_input`
    - Add/remove Phase rows: persist full array to `sections.milestones.phases`
    - Remove PHASES constant and any `staffing_plan` references
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6_

- [x] 13. Rewrite Cost Breakdown
  - [x] 13.1 Create `front/src/components/sections/CostBreakdownSection.tsx`
    - Read from `sections.cost_breakdown`
    - Render `FieldValueEditor` for: `calculator_url`, `mrr`, `arr`, `bedrock_extra`
    - Render `breakdown_table` as editable table of `CostBreakdownRow` entries (category, mrr, arr, note)
    - Add/remove `CostBreakdownRow`: persist full array to `sections.cost_breakdown.breakdown_table`
    - Display `funding_calculation` as read-only metrics (no editing, no saveUserInput calls)
    - No references to `staffing_plan`, `aws_service_cost`, `staffing_cost`, `document_local_summary`
    - _Requirements: 7.1, 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 18.1, 25.1, 25.2, 25.3_
  - [x] 13.2 Delete `front/src/components/sections/CostSection.tsx`
    - _Requirements: 22.4_

- [x] 14. Replace Team with Resources & Cost Estimates
  - [x] 14.1 Create `front/src/components/sections/ResourcesCostEstimatesSection.tsx`
    - Read from `sections.resources_cost_estimates`
    - `partner_technical_team`: editable table of `TeamMember` (role, name) with add/remove, persist full array to `sections.resources_cost_estimates.partner_technical_team`
    - Rate fields: `FieldValueEditor` for `rate_solution_architect`, `rate_engineer`, `rate_other`
    - `phase_hours_table`: editable table of `PhaseHours` entries
    - `total_hours` and `total_cost`: read-only `TotalsRow` display (no editing, no saveUserInput)
    - `contribution`: 6 `FieldValueEditor` instances for customer/partner/aws × amount/pct
    - Client signatures: 4 `FieldValueEditor` instances for `client_signature_customer_name`, `client_signature_person_name`, `client_signature_designation`, `client_signature_date`
    - No references to top-level `staffing_plan`
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 16.6, 16.7, 16.8, 18.1, 24.1, 24.2, 24.3_
  - [x] 14.2 Delete `front/src/components/sections/TeamSection.tsx`
    - _Requirements: 22.3_

- [x] 15. Replace Acceptance GenericSection usage
  - [x] 15.1 Create `front/src/components/editors/AcceptanceStepEditor.tsx`
    - Render list of `AcceptanceStep` entries with editable `heading`, `content`, and `bullets[]`
    - Edit heading: dot-path `{sectionDotPath}.{index}.heading.user_input`
    - Edit content: dot-path `{sectionDotPath}.{index}.content.user_input`
    - Edit bullet: dot-path `{sectionDotPath}.{index}.bullets.{bulletIndex}.user_input`
    - Add step: append `createEmptyAcceptanceStep()`, persist full array
    - Add bullet to step: append empty FieldValue, persist full array
    - Remove step/bullet: splice, persist full array
    - _Requirements: 17.1, 17.3, 17.4, 18.1, 18.2, 23.3_
  - [x] 15.2 Rewrite `front/src/components/sections/AcceptanceSection.tsx`
    - Replace `GenericSection` usage with `AcceptanceStepEditor`
    - Read from `sections.acceptance.steps`
    - Pass `sectionDotPath = "sections.acceptance.steps"`
    - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5_

- [x] 16. Remove legacy frontend references
  - [x] 16.1 Delete legacy component files
    - Delete `front/src/components/sections/OverviewSection.tsx`
    - Delete `front/src/components/sections/ScopeSection.tsx`
    - Delete `front/src/components/sections/GenericSection.tsx`
    - _Requirements: 22.1, 22.2, 22.4_
  - [x] 16.2 Delete `front/src/utils/staffingCalc.ts`
    - Remove staffing calculation helpers no longer used in v2
    - _Requirements: 2.1_
  - [x] 16.3 Clean up `front/src/utils/frontendSchema.ts`
    - Remove staffing-related helpers: `createRoleDraft`, `buildStaffingEditPath`, `sortStaffingRoles`, `getRoleOptions`, `ROLE_POOL` (if present)
    - Keep architecture/formatting helpers
    - _Requirements: 22.3_
  - [x] 16.4 Remove any remaining legacy imports across all frontend files
    - Search for and remove imports of: `OverviewSection`, `ScopeSection`, `TeamSection`, `CostSection`, `GenericSection`, `StaffingRole`, `RoleCategory`, `ClientSignatureSection`, `staffing_plan`, `recalculateAll`
    - _Requirements: 22.1, 22.2, 22.3, 22.4_

- [x] 17. Final checkpoint — Run `npm run build` and fix all errors
  - Run `npm run build` in `front/`
  - Fix any TypeScript compilation errors
  - Fix any Vite build errors
  - Verify no references to removed types (`StaffingRole`, `ClientSignatureSection`, `staffing_plan`, `CategoryGroup.items`)
  - Verify no references to removed components (`OverviewSection`, `ScopeSection`, `TeamSection`, `GenericSection`, `CostSection`)
  - Verify no legacy status values (`'user_modified'`, `'recommended'`) in new code
  - _Requirements: 26.1, 26.2, 26.3, 26.4_

- [x] 18. Commit and push
  - Stage all changed files
  - Commit with message: `feat: migrate frontend to DocumentState v2 schema`
  - Push to feature branch

## Notes

- Task 1 (backend handler update) is a **prerequisite** for all frontend array add/remove operations. It must be completed first.
- Tasks marked with `*` are optional and can be skipped.
- Validation is `npm run build` only — no test frameworks, no AWS deployments (Requirement 26).
- Checkpoints (tasks 4, 10, 17) ensure incremental validation.
- All `createFieldValue` calls must use v2 status values: `'empty'`, `'draft'`, `'confirmed'` — never `'user_modified'` or `'recommended'`.
- Array add/remove operations persist the full array to the parent dot-path (Requirement 18).
- `total_hours`, `total_cost`, and `funding_calculation` are read-only — never saved via `saveUserInput` (Requirements 24, 25).
