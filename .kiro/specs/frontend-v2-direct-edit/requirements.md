# Requirements Document

## Introduction

Align the frontend right-side Live Document editor (DocumentPanel) with the backend DocumentState v2 schema. The backend has been rewritten on branch `feat/apn-template-v2-rewrite` with a simplified schema: 3-status FieldValue (`empty|draft|confirmed`), no top-level `staffing_plan`, no `client_signatures` section, `CategoryGroup.bullets` instead of `items`, single `ScopeTask.details` FieldValue, and new sections like `StakeholdersSection` and `ResourcesCostEstimatesSection`. The frontend must adopt these types, rename/reorder tabs to match v2 document chapters, replace legacy GenericSection usage with structured editors, and enable direct inline editing with immediate save via the existing `saveUserInput` API.

## Glossary

- **DocumentPanel**: The right-side panel component (`DocumentPanel.tsx`) that renders tabbed section editors for the APN PoC Project Plan document.
- **DocumentState**: The Zustand store type (`documentStore.ts`) representing the full document JSON state, mirroring the backend DynamoDB schema.
- **FieldValue**: The 4-property pattern object `{ user_input, ai_recommended, calculated, status }` used for every editable field.
- **FieldStatus**: The status lifecycle enum for FieldValue. V2 values: `empty | draft | confirmed`.
- **EditableField**: The inline-editable UI primitive (`EditableField.tsx`) that supports double-click-to-edit, blur/Enter to save, Esc to cancel.
- **saveUserInput**: The API function (`api.ts`) that persists a single field edit to the backend via `POST /documents/{docId}/user-input`.
- **CategoryGroup**: A grouped list structure with `category_name: FieldValue` and `bullets: FieldValue[]`, used by Success Criteria and Assumptions sections.
- **AcceptanceStep**: A structured acceptance criteria entry with `heading: FieldValue`, `content: FieldValue`, and `bullets: FieldValue[]`.
- **ScopeTask**: A scope of work task row with `task_category`, `schedule`, `details` (single FieldValue in v2), and `personnel`.
- **ContactEntry**: A stakeholder/team member row with `name`, `title`, `description`, `stakeholder_for`, `role`, `contact` — all FieldValue.
- **TeamMember**: A partner technical team member with `role: FieldValue` and `name: FieldValue`, used in Resources & Cost Estimates.
- **GenericSection**: The legacy generic key-value editor component that renders arbitrary section data as flat key-value pairs. To be replaced by structured editors.
- **Save_Status_Indicator**: A minimal UI element showing the current save state of a field: `saving`, `saved`, or `failed`.
- **Phase**: A milestones table row with `phase: FieldValue`, `completion_date: FieldValue`, `deliverables: FieldValue`.
- **CostBreakdownRow**: A cost breakdown table row with `category`, `mrr`, `arr`, `note` — all FieldValue.
- **ResourcesCostEstimatesSection**: The v2 section replacing top-level `staffing_plan` and `client_signatures`, containing `partner_technical_team`, rates, `phase_hours_table`, totals, `contribution`, and client signature fields.

## Requirements

### Requirement 1: V2 FieldValue Status Alignment

**User Story:** As a developer, I want the frontend FieldValue type to use the v2 status enum (`empty | draft | confirmed`), so that frontend state is consistent with the backend schema.

#### Acceptance Criteria

1. THE DocumentState FieldValue type SHALL define status as a union type of `'empty' | 'draft' | 'confirmed'`.
2. WHEN a user edits a field, THE optimistic frontend state update SHALL set `user_input` to the new value, `status` to `'draft'`, and `user_edited` to `true`.
3. THE DocumentState store SHALL NOT use legacy status values such as `'user_modified'`, `'recommended'`, or `'calculated'`.
4. THE `createFieldValue` helper SHALL accept only `'empty' | 'draft' | 'confirmed'` as the status parameter.

### Requirement 2: Remove Top-Level staffing_plan

**User Story:** As a developer, I want the frontend DocumentState to remove the top-level `staffing_plan` property, so that staffing data is read from `sections.resources_cost_estimates` as defined in v2.

#### Acceptance Criteria

1. THE DocumentState interface SHALL NOT include a top-level `staffing_plan` property.
2. THE DocumentState INITIAL_STATE SHALL NOT include a `staffing_plan` object.
3. WHEN the DocumentPanel loads a document, THE DocumentState store SHALL read staffing data from `sections.resources_cost_estimates` instead of `staffing_plan`.

### Requirement 3: Remove client_signatures Section

**User Story:** As a developer, I want the frontend to remove the `client_signatures` section type, so that client signature fields are accessed from `sections.resources_cost_estimates` as defined in v2.

#### Acceptance Criteria

1. THE DocumentSections interface SHALL NOT include a `client_signatures` property.
2. THE ClientSignatureSection interface SHALL be removed from the documentStore module.

### Requirement 4: CategoryGroup Uses bullets Instead of items

**User Story:** As a developer, I want the frontend CategoryGroup type to use `bullets: FieldValue[]` instead of `items: FieldValue[]`, so that it matches the backend v2 schema.

#### Acceptance Criteria

1. THE CategoryGroup interface SHALL define a `bullets` property of type `FieldValue[]`.
2. THE CategoryGroup interface SHALL NOT define an `items` property.
3. WHEN a CategoryGroup editor renders bullet entries, THE editor SHALL read from `group.bullets`.

### Requirement 5: ScopeTask.details Is a Single FieldValue

**User Story:** As a developer, I want the frontend ScopeTask type to define `details` as a single `FieldValue` instead of `FieldValue[]`, so that it matches the backend v2 schema.

#### Acceptance Criteria

1. THE ScopeTask interface SHALL define `details` as type `FieldValue` (not `FieldValue[]`).
2. WHEN a user edits a scope task's details, THE Scope_of_Work editor SHALL save the value to `sections.scope_of_work.tasks.{index}.details.user_input` as a single string.

### Requirement 6: Architecture Section V2 Fields

**User Story:** As a developer, I want the frontend ArchitectureSection type to use v2 field names (`overview`, `diagram_image_s3_key`, `tools_list`), so that legacy fields (`description`, `tools`) are removed.

#### Acceptance Criteria

1. THE ArchitectureSection interface SHALL include `overview: FieldValue`, `diagram_image_s3_key: FieldValue`, `services: ArchitectureService[]`, and `tools_list: FieldValue[]`.
2. THE ArchitectureSection interface SHALL NOT include `description` or `tools` properties.
3. THE ArchitectureSection interface SHALL NOT use an index signature (`[key: string]: any`).

### Requirement 7: CostBreakdownSection V2 Fields

**User Story:** As a developer, I want the frontend CostBreakdownSection type to use v2 fields (`calculator_url`, `mrr`, `arr`, `breakdown_table`, `bedrock_extra`, `funding_calculation`), so that legacy fields (`aws_service_cost`, `staffing_cost`, `document_local_summary`) are removed.

#### Acceptance Criteria

1. THE CostBreakdownSection interface SHALL include `calculator_url: FieldValue`, `mrr: FieldValue`, `arr: FieldValue`, `breakdown_table: CostBreakdownRow[]`, `bedrock_extra: FieldValue`, and `funding_calculation: Record<string, any>`.
2. THE CostBreakdownSection interface SHALL NOT include `aws_service_cost`, `staffing_cost`, or `document_local_summary` properties.
3. THE CostBreakdownSection interface SHALL NOT use an index signature (`[key: string]: any`).

### Requirement 8: V2 Tab Order and Naming

**User Story:** As a user, I want the DocumentPanel tabs to match the v2 document chapter order and names, so that the editor reflects the actual document structure.

#### Acceptance Criteria

1. THE DocumentPanel SHALL render tabs in the following order: Cover, Executive Summary, Stakeholders, Success Criteria, Assumptions, Scope of Work, Architecture, Milestones, Cost Breakdown, Resources & Cost Estimates, Acceptance.
2. THE DocumentPanel SHALL rename the "Overview" tab to "Executive Summary".
3. THE DocumentPanel SHALL rename the "Team" tab to "Resources & Cost Estimates".
4. THE DocumentPanel SHALL rename the "Scope" tab to "Scope of Work".
5. THE DocumentPanel SHALL rename the "Cost" tab to "Cost Breakdown".
6. THE DocumentPanel SHALL add a "Stakeholders" tab between "Executive Summary" and "Success Criteria".

### Requirement 9: Stakeholders Section Editor

**User Story:** As a user, I want a Stakeholders tab that lets me edit executive sponsors, stakeholders, project team members, and escalation contacts, so that I can manage all stakeholder information directly.

#### Acceptance Criteria

1. THE Stakeholders editor SHALL display four contact lists: executive_sponsors, stakeholders, project_team, and escalation_contacts.
2. WHEN a user edits a contact field (name, title, description, stakeholder_for, role, contact), THE Stakeholders editor SHALL save the value via saveUserInput with path `sections.stakeholders.{list_name}.{index}.{field}.user_input`.
3. THE Stakeholders editor SHALL allow adding new ContactEntry rows to each list.
4. THE Stakeholders editor SHALL allow removing ContactEntry rows from each list.

### Requirement 10: CategoryGroup Editor for Success Criteria

**User Story:** As a user, I want the Success Criteria tab to use a structured CategoryGroup editor instead of GenericSection, so that I can edit grouped criteria with category names and bullet items.

#### Acceptance Criteria

1. THE Success_Criteria editor SHALL render each CategoryGroup with an editable `category_name` field and a list of editable `bullets`.
2. WHEN a user edits a bullet, THE Success_Criteria editor SHALL save the value via saveUserInput with path `sections.success_criteria.groups.{groupIndex}.bullets.{bulletIndex}.user_input`.
3. WHEN a user edits a category name, THE Success_Criteria editor SHALL save the value via saveUserInput with path `sections.success_criteria.groups.{groupIndex}.category_name.user_input`.
4. THE Success_Criteria editor SHALL allow adding new bullets to a group.
5. THE Success_Criteria editor SHALL allow adding new CategoryGroup entries.
6. THE Success_Criteria editor SHALL NOT use GenericSection.

### Requirement 11: CategoryGroup Editor for Assumptions

**User Story:** As a user, I want the Assumptions tab to use the same CategoryGroup editor as Success Criteria, so that I can edit grouped assumptions with category names and bullet items.

#### Acceptance Criteria

1. THE Assumptions editor SHALL render each CategoryGroup with an editable `category_name` field and a list of editable `bullets`.
2. WHEN a user edits a bullet, THE Assumptions editor SHALL save the value via saveUserInput with path `sections.assumptions.groups.{groupIndex}.bullets.{bulletIndex}.user_input`.
3. THE Assumptions editor SHALL allow adding new bullets and new CategoryGroup entries.
4. THE Assumptions editor SHALL NOT use GenericSection.

### Requirement 12: Scope of Work V2 Editor

**User Story:** As a user, I want the Scope of Work tab to support the v2 schema with single-FieldValue details, out_of_scope list, and items list, so that I can edit all scope data directly.

#### Acceptance Criteria

1. THE Scope_of_Work editor SHALL render each ScopeTask with editable `task_category`, `schedule`, `details` (single FieldValue), and `personnel` fields.
2. WHEN a user edits a task's details, THE Scope_of_Work editor SHALL save a single string value to `sections.scope_of_work.tasks.{index}.details.user_input`.
3. THE Scope_of_Work editor SHALL render and allow editing of `out_of_scope` items as a list of FieldValue entries.
4. THE Scope_of_Work editor SHALL allow adding and removing `out_of_scope` entries.
5. THE Scope_of_Work editor SHALL render, add, edit, and remove `items[]` entries if present.
6. THE Scope_of_Work editor SHALL allow adding and removing ScopeTask rows.

### Requirement 13: Architecture Direct Editing

**User Story:** As a user, I want to directly edit the architecture overview, services, and tools list from the Architecture tab, so that I can modify architecture details without relying solely on AI or chat.

#### Acceptance Criteria

1. THE Architecture editor SHALL render the `overview` field as an editable FieldValue using EditableField.
2. WHEN a user edits the overview, THE Architecture editor SHALL save the value via saveUserInput with path `sections.architecture.overview.user_input`.
3. THE Architecture editor SHALL render each service's `service_name`, `description`, `sizing_rationale`, `priority`, `category`, and `is_required_for_funding` as editable fields.
4. THE Architecture editor SHALL allow adding new ArchitectureService rows.
5. THE Architecture editor SHALL allow removing ArchitectureService rows.
6. THE Architecture editor SHALL render `tools_list` as an editable list of FieldValue entries.
7. THE Architecture editor SHALL keep the existing drawio upload/preview functionality.

### Requirement 14: Milestones V2 Editor

**User Story:** As a user, I want the Milestones tab to render phases from `sections.milestones.phases[]` with editable phase, completion_date, and deliverables fields, so that milestones reflect the v2 schema.

#### Acceptance Criteria

1. THE Milestones editor SHALL render milestone data from `sections.milestones.phases[]` as a table of Phase entries.
2. WHEN a user edits a phase field, THE Milestones editor SHALL save the value via saveUserInput with path `sections.milestones.phases.{index}.{field}.user_input`.
3. THE Milestones editor SHALL allow adding new Phase rows.
4. THE Milestones editor SHALL allow removing Phase rows.
5. THE Milestones editor SHALL NOT use hardcoded PHASES constants for milestone data.
6. THE Milestones editor SHALL NOT read from `staffing_plan.roles` for milestone display.

### Requirement 15: Cost Breakdown V2 Editor

**User Story:** As a user, I want the Cost Breakdown tab to display and edit v2 cost fields (calculator_url, mrr, arr, breakdown_table, bedrock_extra, funding_calculation), so that the cost view matches the backend schema.

#### Acceptance Criteria

1. THE Cost_Breakdown editor SHALL render editable fields for `calculator_url`, `mrr`, `arr`, and `bedrock_extra`.
2. THE Cost_Breakdown editor SHALL render `breakdown_table` as an editable table of CostBreakdownRow entries (category, mrr, arr, note).
3. THE Cost_Breakdown editor SHALL allow adding new CostBreakdownRow entries to `breakdown_table`.
4. THE Cost_Breakdown editor SHALL allow removing CostBreakdownRow entries from `breakdown_table`.
5. THE Cost_Breakdown editor SHALL display `funding_calculation` data as read-only metrics.
6. THE Cost_Breakdown editor SHALL NOT read from `staffing_plan` or `aws_service_cost` or `staffing_cost` or `document_local_summary`.

### Requirement 16: Resources & Cost Estimates Editor

**User Story:** As a user, I want a Resources & Cost Estimates tab that replaces the old Team tab, so that I can edit partner team members, rates, phase hours, totals, contribution, and client signatures from a single section.

#### Acceptance Criteria

1. THE Resources_Cost_Estimates editor SHALL render `partner_technical_team` as an editable table of TeamMember entries (role, name).
2. THE Resources_Cost_Estimates editor SHALL render editable rate fields: `rate_solution_architect`, `rate_engineer`, `rate_other`.
3. THE Resources_Cost_Estimates editor SHALL render `phase_hours_table` as an editable table of PhaseHours entries.
4. THE Resources_Cost_Estimates editor SHALL display `total_hours` and `total_cost` as read-only TotalsRow data.
5. THE Resources_Cost_Estimates editor SHALL render `contribution` as editable entries: `contribution.customer.amount`, `contribution.customer.pct`, `contribution.partner.amount`, `contribution.partner.pct`, `contribution.aws.amount`, `contribution.aws.pct`.
6. THE Resources_Cost_Estimates editor SHALL render client signature fields: `client_signature_customer_name`, `client_signature_person_name`, `client_signature_designation`, `client_signature_date`.
7. WHEN a user edits a field, THE Resources_Cost_Estimates editor SHALL save the value via saveUserInput with the appropriate `sections.resources_cost_estimates.{path}` dot-path.
8. THE Resources_Cost_Estimates editor SHALL NOT read from the top-level `staffing_plan`.

### Requirement 17: Acceptance Section V2 Editor

**User Story:** As a user, I want the Acceptance tab to use a structured AcceptanceStep editor instead of GenericSection, so that I can edit acceptance steps with headings, content, and bullet lists.

#### Acceptance Criteria

1. THE Acceptance editor SHALL render each AcceptanceStep with editable `heading`, `content`, and `bullets[]` fields.
2. WHEN a user edits an acceptance step field, THE Acceptance editor SHALL save the value via saveUserInput with path `sections.acceptance.steps.{index}.{field}.user_input`.
3. THE Acceptance editor SHALL allow adding new AcceptanceStep entries.
4. THE Acceptance editor SHALL allow adding new bullets to an AcceptanceStep.
5. THE Acceptance editor SHALL NOT use GenericSection.

### Requirement 18: Array Add/Remove Persistence

**User Story:** As a developer, I want add/remove operations on array fields to persist the full updated array to the parent path, so that the backend receives a consistent array state.

#### Acceptance Criteria

1. WHEN a user adds or removes a row in an array field, THE editor SHALL update the local array in the Zustand store and persist the full array via `saveUserInput` to the parent path (e.g. `sections.stakeholders.executive_sponsors`, `sections.success_criteria.groups`, `sections.scope_of_work.tasks`, `sections.architecture.services`, `sections.cost_breakdown.breakdown_table`, `sections.acceptance.steps`, `sections.milestones.phases`, `sections.resources_cost_estimates.partner_technical_team`).
2. WHEN adding a new row, THE editor SHALL create a complete v2-shaped object with empty FieldValue defaults for all required fields. THE editor SHALL NOT add partial objects or plain strings where FieldValue is expected.
3. THE serialized array sent to `saveUserInput` SHALL match the backend v2 schema shape for that array.

### Requirement 19: Immediate Save on Blur or Enter

**User Story:** As a user, I want each field to save immediately when I press Enter or move focus away (blur), so that my edits are persisted without needing a separate Save button.

#### Acceptance Criteria

1. THE EditableField component SHALL remain a UI-only primitive: it calls its `onSave` callback on blur or Enter, but SHALL NOT call `saveUserInput` directly.
2. WHEN a user finishes editing a field (blur or Enter), THE section editor or shared save helper SHALL call `saveUserInput` with the field's dot-path and new value inside the `onSave` callback.
3. THE section editors SHALL NOT render section-level Save buttons.
4. THE EditableField component SHALL continue to support Esc to cancel without saving.

### Requirement 20: Save Status Indicator

**User Story:** As a user, I want to see a minimal save status indicator (saving/saved/failed) after editing a field, so that I know whether my edit was persisted.

#### Acceptance Criteria

1. WHEN a save operation is in progress, THE Save_Status_Indicator SHALL display a "saving" state.
2. WHEN a save operation completes successfully, THE Save_Status_Indicator SHALL display a "saved" state.
3. IF a save operation fails, THEN THE Save_Status_Indicator SHALL display a "failed" state with a visual error indication.
4. THE Save_Status_Indicator SHALL NOT silently ignore save errors.
5. FOR MVP, save status MAY be tracked per field or per section. THE UI SHALL at minimum show the latest save state (saving, saved, or failed) for the most recent edit operation.

### Requirement 21: Executive Summary V2 Fields

**User Story:** As a user, I want the Executive Summary tab to support v2 fields including `current_pain_points`, `poc_objectives`, and `custom_blocks`, so that all executive summary data is editable.

#### Acceptance Criteria

1. THE Executive_Summary editor SHALL render editable fields for `customer_intro`, `problem_statement`, `proposed_solution`, `phases_overview[]`, `current_pain_points[]`, and `poc_objectives[]`.
2. THE Executive_Summary editor SHALL render the nested `business_case` fields: `problem_definition`, `roi_calculation`, `executive_sponsor`, `production_commitment`.
3. THE Executive_Summary editor SHALL NOT reference legacy fields `text` or `summary`.

### Requirement 22: Remove Legacy Components and References

**User Story:** As a developer, I want all legacy component wrappers (OverviewSection re-export, ScopeSection re-export, TeamSection) and GenericSection usage to be removed or replaced, so that the codebase has no dead code referencing the old schema.

#### Acceptance Criteria

1. THE codebase SHALL NOT import or use `OverviewSection` as a re-export wrapper for `ExecutiveSummarySection`.
2. THE codebase SHALL NOT import or use `ScopeSection` as a re-export wrapper for `ScopeOfWorkSection`.
3. THE codebase SHALL NOT import or use `TeamSection` for staffing plan editing.
4. WHEN all section editors are migrated, THE GenericSection component SHALL be removed if no remaining consumers exist.

### Requirement 23: Reusable Editor Components

**User Story:** As a developer, I want shared reusable editor components (CategoryGroup editor, contact table editor, AcceptanceStep editor, resource cost table editor, list editor), so that section editors share consistent editing patterns.

#### Acceptance Criteria

1. THE codebase SHALL provide a reusable CategoryGroup editor component that renders `category_name` and `bullets[]` with add/remove capabilities.
2. THE codebase SHALL provide a reusable contact table editor component for rendering and editing lists of ContactEntry objects.
3. THE codebase SHALL provide a reusable AcceptanceStep editor component that renders `heading`, `content`, and `bullets[]`.
4. THE codebase SHALL provide a reusable list editor helper for rendering and editing ordered lists of FieldValue entries with add/remove capabilities.

### Requirement 24: Totals Display Behavior

**User Story:** As a user, I want total_hours and total_cost to be displayed as read-only values, so that I can see aggregated data without accidentally editing computed fields.

#### Acceptance Criteria

1. FOR MVP, THE Resources_Cost_Estimates editor SHALL display `total_hours` and `total_cost` as read-only values from DocumentState.
2. THE frontend MAY recalculate totals locally for preview purposes, but THE source-of-truth for persisted totals SHALL remain the DocumentState fields received from the backend.
3. THE frontend SHALL NOT persist locally-recalculated totals via `saveUserInput`.

### Requirement 25: Funding Calculation Read-Only

**User Story:** As a user, I want funding_calculation to be displayed as read-only metrics, so that funding data is only updated by the reviewer/backend logic and not accidentally edited.

#### Acceptance Criteria

1. THE Cost_Breakdown editor SHALL display `funding_calculation` fields as read-only metrics.
2. THE Cost_Breakdown editor SHALL NOT allow direct editing of `funding_calculation` fields.
3. THE Cost_Breakdown editor SHALL NOT call `saveUserInput` for any `funding_calculation` path.

### Requirement 26: Local Testing Only

**User Story:** As a developer, I want all validation to be limited to local frontend checks (TypeScript typecheck, existing unit tests), so that no AWS resources are invoked during development.

#### Acceptance Criteria

1. THE development workflow SHALL run `npm run build` (TypeScript compilation + Vite build) to validate changes.
2. THE development workflow MAY optionally run `npx tsc -b --noEmit` for type-check-only passes during development.
3. THE development workflow SHALL NOT invoke any AWS services (Terraform apply, CDK deploy, Lambda invoke, S3 upload, Bedrock calls, AppSync calls, or broad E2E tests).
4. THE development workflow SHALL NOT add new test framework dependencies (vitest, jest, fast-check, testing-library, etc.) for this MVP.
