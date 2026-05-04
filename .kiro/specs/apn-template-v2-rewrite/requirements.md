# Requirements Document

## Introduction

Refactor the Doc Agent document schema, agent patch paths, funding validation, and DOCX export pipeline to align with the latest APN PoC DOCX template v2 (`apn-poc-template_v2.docx`). This is a breaking change — all legacy fields, compatibility aliases, and v1 template mappings are removed. The goal is speed and full alignment with the v2 template placeholders. No backward compatibility with old saved documents is required.

## Glossary

- **DocumentState**: The Pydantic v2 root model (`agent/lib/schema/document_state.py`) representing the canonical JSON state of an APN PoC Project Plan document stored in DynamoDB.
- **FieldValue**: The 4-property pattern model (`user_input`, `ai_recommended`, `calculated`, `status`) used for every editable field in DocumentState. v2 simplifies status to `empty | draft | confirmed` and removes metadata fields (`reason`, `source_patterns`, `confidence`).
- **Export_Pipeline**: The `export_docx.py` Lambda that downloads the DOCX template from S3, builds a render context from DocumentState, renders via `docxtpl`, uploads the result, and returns a presigned URL.
- **Context_Builder**: The `_build_context()` function inside Export_Pipeline that transforms a DocumentState dict into the flat key-value map consumed by the DOCX template placeholders.
- **Funding_Validator**: The `FundingValidator` class (`agent/app/funding/funding_validator.py`) that performs deterministic GenAIIC PLD funding eligibility checks against DocumentState fields.
- **Discovery_Agent**: The `DiscoveryAgent` class (`agent/app/discovery/discovery_agent.py`) that extracts structured project information from user input and generates JSON Patch operations targeting DocumentState paths.
- **Reviewer_Agent**: The `ReviewerAgent` class (`agent/app/reviewer/reviewer_agent.py`) that validates document completeness, section order, numeric consistency, and runs Funding_Validator.
- **Orchestrator**: The `ParentOrchestrator` class (`agent/app/parent/orchestrator.py`) that coordinates sub-agent delegation and generates JSON Patch operations for DocumentState.
- **Template_S3_Key**: The S3 object key for the DOCX template file. v1: `templates/apn-poc-template.docx`. v2: `templates/apn-poc-template_v2.docx`. The source of truth is `agent/templates/apn-poc-template_v2.docx`.
- **AgentCore_Gateway_Response**: The Lambda response shape `{"outputPayload": json.dumps(payload, ensure_ascii=False)}` required by the AgentCore Gateway integration.

## Requirements

### Requirement 1: DocumentState v2 Schema Redesign

**User Story:** As a developer, I want the DocumentState schema to match the v2 template placeholders exactly, so that every field in the schema maps 1:1 to a template context key without legacy translation.

#### Acceptance Criteria

1. THE DocumentState SHALL define sections matching the v2 structure: `cover`, `executive_summary`, `stakeholders`, `success_criteria`, `assumptions`, `scope_of_work`, `architecture`, `milestones`, `cost_breakdown`, `acceptance`, `resources_cost_estimates`.
2. THE FieldValue SHALL contain only `user_input`, `ai_recommended`, `calculated`, `status`, and `user_edited` properties.
3. THE FieldValue status SHALL accept only the values `empty`, `draft`, and `confirmed`.
4. WHEN FieldValue.resolve() is called, THE FieldValue SHALL return the first non-empty value in priority order: `user_input` > `ai_recommended` > `calculated` > `""`.
5. THE DocumentState SHALL NOT contain a top-level `staffing_plan` field; staffing data SHALL reside within `sections.resources_cost_estimates`.
6. THE DocumentState SHALL NOT contain a `sections.client_signatures` section; client signature fields SHALL reside within `sections.resources_cost_estimates`.
7. THE ExecutiveSummarySection SHALL NOT contain `text` or `summary` fields; it SHALL contain `customer_intro` (FieldValue), `problem_statement` (FieldValue), `proposed_solution` (FieldValue), `phases_overview` (list[FieldValue]), `current_pain_points` (list[FieldValue]), `poc_objectives` (list[FieldValue]), and `custom_blocks` (list[dict]). Business case fields SHALL remain nested under a `business_case: BusinessCase` sub-model with `problem_definition`, `roi_calculation`, `executive_sponsor`, `production_commitment`. Note: `phases_overview`, `current_pain_points`, and `poc_objectives` are list[FieldValue] because the template renders them as bullet lists.
8. THE ArchitectureSection SHALL NOT contain `description` or `tools` fields; it SHALL contain `overview` (FieldValue), `diagram_image_s3_key` (FieldValue — S3 key), `services` (list[ArchitectureService]), and `tools_list` (list[FieldValue]).
9. THE AcceptanceSection SHALL NOT contain a `text` field; it SHALL contain `steps: list[AcceptanceStep]` where each AcceptanceStep has `heading` (FieldValue), `content` (FieldValue), and `bullets` (list[FieldValue]). The export context key remains `acceptance_steps`.
10. THE CostBreakdownSection SHALL contain `calculator_url` (FieldValue), `mrr` (FieldValue), `arr` (FieldValue), `breakdown_table` (list[CostBreakdownRow] where CostBreakdownRow has `category`, `mrr`, `arr`, `note` as FieldValue), `bedrock_extra` (FieldValue), and `funding_calculation` (dict) at the section level; it SHALL NOT contain a nested `aws_service_cost.calculator_share_url` path. The export context maps schema fields to template keys: `calculator_url` → `aws_calculator_url`, `mrr` → `aws_mrr`, `arr` → `aws_arr`, `breakdown_table` → `aws_cost_breakdown_table`, `bedrock_extra` → `aws_bedrock_extra`.
11. THE CategoryGroup SHALL use `category_name: FieldValue` and `bullets: list[FieldValue]`, not `items: list[str]`. The template iterates `group.bullets`.
12. THE ScopeTask fields (`task_category`, `schedule`, `details`, `personnel`) SHALL remain FieldValue-based to support the `user_input / ai_recommended / calculated` pattern.
13. THE ContactEntry SHALL NOT contain a `role_or_description` field but SHALL keep `name`, `title`, `description`, `stakeholder_for`, `role`, and `contact` (all FieldValue). The template requires `executive_sponsors[].description`, `stakeholders[].stakeholder_for`, `project_team[].role`, `escalation_contacts[].role`.
14. THE ResourcesCostEstimatesSection SHALL contain `partner_technical_team: list[TeamMember]` (where TeamMember has `role: FieldValue` and `name: FieldValue`), `rate_solution_architect` (FieldValue), `rate_engineer` (FieldValue), `rate_other` (FieldValue), `phase_hours_table: list[PhaseHours]` (where PhaseHours has `phase: FieldValue`, `sa_hours: int`, `eng_hours: int`, `other_hours: int`, `total: int`), `total_hours: TotalsRow`, `total_cost: TotalsRow` (where TotalsRow has `sa: str`, `eng: str`, `other: str`, `total: str`), `contribution` (Contribution), and client signature fields.
15. THE ScopeOfWorkSection SHALL contain `tasks: list[ScopeTask]`, `out_of_scope: list[FieldValue]`, and `items: list[FieldValue]`. Export mapping: `tasks` → `scope_tasks`, `out_of_scope` → `scope_out_of_scope`, `items` → `scope_items`.
16. WHEN DocumentState() is instantiated with no arguments, THE DocumentState SHALL produce a valid default instance with empty lists as independent objects (no shared mutable defaults).
17. WHEN DocumentState.model_dump() is called, THE DocumentState SHALL produce a JSON-serializable dict without errors.
18. ALL section models SHALL use `extra="forbid"` to prevent typos, EXCEPT `CoverSection` which SHALL use `extra="allow"` because the cover section receives dynamic project metadata fields from agents at runtime.

### Requirement 2: Legacy Field Removal

**User Story:** As a developer, I want all legacy v1 fields removed from the codebase, so that there is no dead code or ambiguity about which schema is active.

#### Acceptance Criteria

1. THE DocumentState SHALL NOT contain the fields: `executive_summary.text`, `executive_summary.summary`, `architecture.description`, `architecture.tools`, `acceptance.text`, `cost_breakdown.aws_service_cost.calculator_share_url` (as a nested path), or a separate `client_signatures` section.
2. THE DocumentState SHALL NOT contain a top-level `staffing_plan` field.
3. THE FieldValue SHALL NOT contain the properties: `reason`, `source_patterns`, or `confidence`.
4. THE FieldStatus enum SHALL NOT contain the values `recommended`, `user_modified`, or `calculated`.
5. THE ContactEntry SHALL NOT contain a `role_or_description` field.
6. THE Export_Pipeline SHALL NOT produce legacy context keys: `executive_summary_text`, `architecture_description`, `acceptance_text`, or `architecture_tools`.
7. THE BusinessCase model SHALL NOT be removed; it SHALL remain as a v2 sub-model under ExecutiveSummarySection.

### Requirement 3: Export Pipeline v2 Context Builder

**User Story:** As a developer, I want the export_docx context builder to produce only v2 template context keys, so that the rendered DOCX matches the v2 template placeholders exactly.

#### Acceptance Criteria

1. THE Context_Builder SHALL produce all v2 cover keys: `customer`, `partner`, `date`.
2. THE Context_Builder SHALL produce all v2 executive summary keys: `customer_intro`, `problem_statement`, `proposed_solution`, `phases_overview`, `current_pain_points`, `poc_objectives`, `business_case_problem` (mapped from `business_case.problem_definition`), `business_case_roi` (mapped from `business_case.roi_calculation`), `business_case_sponsor` (mapped from `business_case.executive_sponsor`), `business_case_commitment` (mapped from `business_case.production_commitment`), `custom_blocks`.
3. THE Context_Builder SHALL produce all v2 stakeholder keys: `executive_sponsors`, `stakeholders`, `project_team`, `escalation_contacts`. Each contact entry SHALL include `description`, `stakeholder_for`, and `role` fields as required by the template.
4. THE Context_Builder SHALL produce all v2 success criteria keys: `success_criteria_groups` (each group with `category_name` and `bullets`), `success_criteria_items`.
5. THE Context_Builder SHALL produce all v2 assumptions keys: `assumptions_groups` (each group with `category_name` and `bullets`), `assumptions_items`.
6. THE Context_Builder SHALL produce all v2 scope keys: `scope_tasks`, `scope_out_of_scope`, `scope_items`.
7. THE Context_Builder SHALL produce all v2 architecture keys: `architecture_overview`, `architecture_diagram_image` (mapped from schema `diagram_image_s3_key`), `architecture_services`, `architecture_tools_list` (mapped from schema `tools_list`).
8. THE Context_Builder SHALL sort architecture services by priority (ascending) in the rendered context.
9. THE Context_Builder SHALL produce all v2 milestone keys: `milestones`.
10. THE Context_Builder SHALL produce all v2 AWS cost keys: `aws_calculator_url` (mapped from schema `calculator_url`), `aws_mrr` (mapped from schema `mrr`), `aws_arr` (mapped from schema `arr`), `aws_cost_breakdown_table` (mapped from schema `breakdown_table`), `aws_bedrock_extra` (mapped from schema `bedrock_extra`).
11. THE Context_Builder SHALL produce all v2 acceptance keys: `acceptance_steps` (mapped from schema `steps`, each with `heading`, `content`, `bullets`).
12. THE Context_Builder SHALL produce all v2 resources keys: `partner_technical_team` (list of `{role, name}`), `rate_solution_architect`, `rate_engineer`, `rate_other`, `phase_hours_table` (list of `{phase, sa_hours, eng_hours, other_hours, total}`), `total_hours` (`{sa, eng, other, total}`), `total_cost` (`{sa, eng, other, total}`), `contribution`, `client_signature_customer_name`, `client_signature_person_name`, `client_signature_designation`, `client_signature_date`.
13. WHEN an empty DocumentState payload is provided, THE Context_Builder SHALL NOT raise an exception.
14. IF the architecture diagram image S3 key is missing or S3 load fails, THEN THE Context_Builder SHALL set `architecture_diagram_image` to an empty string and continue without error.

### Requirement 4: Export Pipeline Response Shape Preservation

**User Story:** As a developer, I want the export_docx Lambda to preserve the AgentCore Gateway response shape, so that the Gateway integration continues to work without changes.

#### Acceptance Criteria

1. THE Export_Pipeline SHALL return responses in the shape `{"outputPayload": json.dumps(payload, ensure_ascii=False)}`.
2. THE Export_Pipeline SHALL NOT return responses in API Gateway `statusCode`/`body` style.
3. WHEN an error occurs during export, THE Export_Pipeline SHALL return the error in the same `{"outputPayload": ...}` shape with `error`, `error_type`, and `stage` fields.

### Requirement 5: Template S3 Key Update

**User Story:** As a developer, I want all template references updated to the v2 template path, so that the system consistently uses the new template file.

#### Acceptance Criteria

1. THE Export_Pipeline TEMPLATE_S3_KEY SHALL be `templates/apn-poc-template_v2.docx`.
2. THE Terraform `export_docx` Lambda environment variable `TEMPLATE_S3_KEY` SHALL be `templates/apn-poc-template_v2.docx`.
3. THE upload_template.py DEFAULT_KEY SHALL be `templates/apn-poc-template_v2.docx`.
4. THE upload_template.py default `--template` argument SHALL be `agent/templates/apn-poc-template_v2.docx`.
5. IF upload_template.sh exists, THEN THE upload_template.sh default template path SHALL reference `apn-poc-template_v2.docx`.

### Requirement 6: Agent Patch Paths v2 Alignment

**User Story:** As a developer, I want all agent-generated JSON Patch operations to target v2 schema paths only, so that patches are valid against the new DocumentState structure.

#### Acceptance Criteria

1. THE Discovery_Agent SHALL generate patches targeting v2 paths only (e.g., `/sections/executive_summary/customer_intro` instead of `/meta/project_goal`).
2. THE Discovery_Agent SHALL NOT generate patches targeting removed paths: `/meta/project_goal`, `/sections/scope_of_work/summary`, or any path containing `role_or_description`.
3. THE Orchestrator `_delegate_architecture` SHALL NOT generate patches targeting `/sections/architecture/description` or `/sections/architecture/tools`.
4. THE Orchestrator `_delegate_architecture` SHALL generate patches targeting `/sections/architecture/overview` and `/sections/architecture/tools_list`.
5. THE Orchestrator `_delegate_staffing` SHALL generate patches targeting `/sections/resources_cost_estimates/...` instead of `/staffing_plan/roles/...`.
6. THE Orchestrator `_delegate_discovery` SHALL NOT generate patches targeting `/staffing_plan/...`.
7. THE Reviewer_Agent SHALL NOT reference `doc_state.staffing_plan.roles`; it SHALL reference staffing data from `doc_state.sections.resources_cost_estimates`.
8. THE Reviewer_Agent SHALL be able to generate patches targeting `/sections/cost_breakdown/funding_calculation`.

### Requirement 7: Funding Validation v2 Field Paths

**User Story:** As a developer, I want the FundingValidator to use v2 schema field paths, so that validation logic works correctly against the new DocumentState structure.

#### Acceptance Criteria

1. THE Funding_Validator `has_calculator_url` SHALL read from `doc_state.sections.cost_breakdown.calculator_url` instead of `doc_state.sections.cost_breakdown.aws_service_cost.calculator_share_url`.
2. THE Funding_Validator `_sow_cost` SHALL read staffing total from `doc_state.sections.resources_cost_estimates` instead of `doc_state.staffing_plan.grand_total_cost`.
3. THE Funding_Validator `_business_case_has` SHALL read business case fields from `doc_state.sections.executive_summary.business_case` (e.g., `business_case.problem_definition`, `business_case.roi_calculation`, `business_case.executive_sponsor`, `business_case.production_commitment`).
4. THE Funding_Validator `has_bedrock` SHALL continue to read from `doc_state.sections.architecture.services`.
5. THE Funding_Validator `calculate_funding` SHALL use the formula `eligible_amount = min(yr1_arr * 0.25, sow_cost, 125000)`.
6. WHEN Bedrock is missing from architecture services, THE Funding_Validator SHALL create a blocking issue with code `BEDROCK_MISSING`.
7. WHEN the executive sponsor field is missing, THE Funding_Validator SHALL create a blocking issue or warning.
8. WHEN ARR is low or missing, THE Funding_Validator SHALL create a warning.
9. WHEN FundingValidationResult.to_dict() is called (or equivalent serialization), THE result SHALL be JSON-serializable.

### Requirement 8: Local Testing Strategy

**User Story:** As a developer, I want all tests to be local, fast, and deterministic with no AWS integration calls, so that the CI pipeline runs quickly and reliably.

#### Acceptance Criteria

1. THE test suite SHALL NOT invoke any AWS Lambda functions, Terraform apply, CDK deploy, S3 upload, or live Bedrock/AgentCore/Gateway calls.
2. THE test suite SHALL use only pytest — no hypothesis or other property-based testing frameworks SHALL be added as dependencies.
3. THE schema smoke test SHALL verify that `DocumentState()` instantiates without error, `model_dump()` produces a valid dict, empty list defaults are independent objects, `FieldValue.resolve()` returns values in the correct priority order, `CategoryGroup` uses `bullets` (not `items`), `AcceptanceSection` uses structured `AcceptanceStep` objects, `ContactEntry` has `description`/`stakeholder_for`/`role` and no `role_or_description`, `partner_technical_team` is `list[TeamMember]`, `total_hours`/`total_cost` are `TotalsRow`, and `phase_hours_table` is `list[PhaseHours]`.
4. THE export context builder test SHALL verify that an empty payload does not raise an exception, a full v2 sample payload maps to all required template context keys, architecture services are sorted by priority, and a missing or failed diagram image does not fail context building.
5. THE funding validator test SHALL verify that missing Bedrock creates a blocking issue, missing sponsor creates a blocking issue or warning, the eligible amount formula `min(yr1_arr * 0.25, sow_cost, 125000)` is correct, low or missing ARR creates warnings, and the result is JSON-serializable.
6. THE agent patch path test SHALL verify that Discovery_Agent output maps to v2 patch paths only, no patches target removed legacy paths, and Reviewer_Agent can patch `/sections/cost_breakdown/funding_calculation`.
7. IF frontend document types are modified, THEN THE frontend typecheck SHALL be run; otherwise frontend tests SHALL be skipped.
8. THE S3 template upload and real DOCX export validation SHALL be defined as manual or optional targeted verification steps, not as automated test suite steps.
