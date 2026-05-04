# Implementation Plan: APN Template v2 Rewrite

## Overview

Breaking rewrite of the Doc Agent data layer to align with the APN PoC DOCX template v2. The implementation follows a dependency-driven order: schema first (foundation), then consumers (export, funding, agents), then infra config, then tests. All legacy v1 fields, aliases, and compatibility paths are removed. No backward compatibility. No new dev dependencies (no hypothesis).

## Tasks

- [x] 1. Rewrite DocumentState v2 schema
  - [x] 1.1 Rewrite FieldValue, FieldStatus, and remove legacy types
    - Remove `reason`, `source_patterns`, `confidence` from FieldValue
    - Remove `CalculatedOnly` class entirely
    - Reduce FieldStatus enum to `empty`, `draft`, `confirmed` (remove `recommended`, `user_modified`, `calculated`)
    - Add `resolve()` method to FieldValue: returns first non-empty value in priority `user_input > ai_recommended > calculated > ""`
    - _Requirements: 1.2, 1.3, 1.4, 2.3, 2.4_

  - [x] 1.2 Rewrite section models to v2 structure
    - **ExecutiveSummarySection** (`extra="forbid"`): remove `text`, `summary`; KEEP `business_case: BusinessCase` nested; add `customer_intro` (FieldValue), `problem_statement` (FieldValue), `proposed_solution` (FieldValue), `phases_overview` (list[FieldValue]), `current_pain_points` (list[FieldValue]), `poc_objectives` (list[FieldValue]), `custom_blocks` (list[dict]). Note: `phases_overview`, `current_pain_points`, `poc_objectives` are list[FieldValue] because the template renders them as bullet lists.
    - **BusinessCase**: KEEP as v2 sub-model with `problem_definition`, `roi_calculation`, `executive_sponsor`, `production_commitment` (all FieldValue). Do NOT remove or flatten.
    - **ArchitectureSection** (`extra="forbid"`): remove `description`, `tools`; keep `overview` (FieldValue), `services`; add `diagram_image_s3_key` (FieldValue), `tools_list` (list[FieldValue])
    - **AcceptanceSection** (`extra="forbid"`): remove `text`; add `steps: list[AcceptanceStep]` where AcceptanceStep has `heading` (FieldValue), `content` (FieldValue), `bullets` (list[FieldValue])
    - **CostBreakdownSection** (`extra="forbid"`): remove nested `staffing_cost`, `aws_service_cost`, `document_local_summary`; add `calculator_url` (FieldValue), `mrr` (FieldValue), `arr` (FieldValue), `breakdown_table` (list[CostBreakdownRow] where CostBreakdownRow has `category`, `mrr`, `arr`, `note` as FieldValue), `bedrock_extra` (FieldValue), `funding_calculation` (dict)
    - **CategoryGroup**: change `items: list[FieldValue]` → `bullets: list[FieldValue]`; keep `category_name: FieldValue`
    - **ScopeTask**: change `details` from `list[FieldValue]` to single `FieldValue`; keep `task_category`, `schedule`, `personnel` as FieldValue (do NOT convert to str)
    - **ContactEntry**: remove `role_or_description` only; KEEP `name`, `title`, `description`, `stakeholder_for`, `role`, `contact` (all FieldValue)
    - **SuccessCriteriaSection** / **AssumptionsSection** (`extra="forbid"`): keep `groups: list[CategoryGroup]` and `items: list[FieldValue]` (ungrouped fallback)
    - **ScopeOfWorkSection** (`extra="forbid"`): keep `tasks: list[ScopeTask]`, `out_of_scope: list[FieldValue]`, `items: list[FieldValue]`. Export mapping: `tasks` → `scope_tasks`, `out_of_scope` → `scope_out_of_scope`, `items` → `scope_items`
    - **CoverSection**: keep `extra="allow"` (agents write dynamic metadata)
    - All other sections: use `extra="forbid"`
    - _Requirements: 1.1, 1.7, 1.8, 1.9, 1.10, 1.11, 1.12, 1.13, 1.17, 2.1, 2.5, 2.7_

  - [x] 1.3 Rewrite ResourcesCostEstimatesSection and remove top-level staffing_plan
    - Add new typed models: `TeamMember` (role, name as FieldValue), `PhaseHours` (phase as FieldValue, sa_hours/eng_hours/other_hours/total as int), `TotalsRow` (sa/eng/other/total as str), `CostBreakdownRow` (category, mrr, arr, note as FieldValue), `AcceptanceStep` (heading, content as FieldValue, bullets as list[FieldValue])
    - Add to ResourcesCostEstimatesSection (`extra="forbid"`): `partner_technical_team: list[TeamMember]`, `rate_solution_architect` (FieldValue), `rate_engineer` (FieldValue), `rate_other` (FieldValue), `phase_hours_table: list[PhaseHours]`, `total_hours: TotalsRow`, `total_cost: TotalsRow`, `contribution` (Contribution), client signature fields (FieldValue)
    - Remove `ClientSignatureSection` from Sections
    - Remove `StaffingPlan`, `StaffingRole`, old `PhaseHours` classes and `staffing_plan` from DocumentState root
    - Remove legacy sub-models: `RoleCostSummary`, `StaffingCost`, `ServiceBreakdownItem`, `AWSServiceCost`, `DocumentLocalSummary`, `FundingCalculation` (replaced by dict)
    - Ensure `DocumentState()` instantiates with valid defaults and independent mutable lists
    - _Requirements: 1.5, 1.6, 1.14, 1.15, 1.16, 2.2_

- [x] 2. Checkpoint — Verify schema compiles and instantiates
  - Run `python -c "from agent.lib.schema.document_state import DocumentState; d = DocumentState(); print(d.model_dump())"` to confirm no import errors and valid defaults
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Rewrite export_docx context builder
  - [x] 3.1 Rewrite `_build_context()` for v2 schema paths
    - Read from v2 schema paths only (no legacy fallbacks)
    - Map nested `business_case.problem_definition` → `business_case_problem`, `business_case.roi_calculation` → `business_case_roi`, `business_case.executive_sponsor` → `business_case_sponsor`, `business_case.production_commitment` → `business_case_commitment`
    - Map `diagram_image_s3_key` → `architecture_diagram_image`, `tools_list` → `architecture_tools_list`
    - Map `calculator_url` → `aws_calculator_url`, `mrr` → `aws_mrr`, `arr` → `aws_arr`, `breakdown_table` → `aws_cost_breakdown_table`, `bedrock_extra` → `aws_bedrock_extra`
    - Map `acceptance.steps` → `acceptance_steps` (each with heading, content, bullets)
    - Map `scope_of_work.tasks` → `scope_tasks`, `scope_of_work.out_of_scope` → `scope_out_of_scope`, `scope_of_work.items` → `scope_items`
    - Render `phases_overview`, `current_pain_points`, `poc_objectives` as lists (they are list[FieldValue] in schema)
    - Render `success_criteria_groups` / `assumptions_groups` with `category_name` and `bullets` (not `items`)
    - Render `partner_technical_team` as list of `{role, name}`
    - Render `phase_hours_table` as list of `{phase, sa_hours, eng_hours, other_hours, total}`
    - Render `total_hours` / `total_cost` as `{sa, eng, other, total}`
    - Read client signatures from `resources_cost_estimates`
    - Sort architecture services by priority ascending
    - Remove all legacy context keys: `executive_summary_text`, `architecture_description`, `acceptance_text`, `architecture_tools`
    - Remove legacy helper functions: `_build_staffing_context`, `_build_staffing_totals`, `_build_phase_hours_table`, `_signature_context`
    - _Requirements: 3.1–3.14, 2.6_

  - [x] 3.2 Update TEMPLATE_S3_KEY constant and error handling
    - Change `TEMPLATE_S3_KEY` default to `templates/apn-poc-template_v2.docx`
    - Preserve `{"outputPayload": json.dumps(payload, ensure_ascii=False)}` response shape
    - Handle empty payload without exception
    - Handle missing/failed diagram image gracefully (set to empty string)
    - _Requirements: 4.1, 4.2, 4.3, 5.1_

- [x] 4. Update FundingValidator field paths
  - [x] 4.1 Update FundingValidator to v2 schema paths
    - `has_calculator_url`: read from `cost_breakdown.calculator_url` instead of `cost_breakdown.aws_service_cost.calculator_share_url`
    - `_sow_cost`: read from `resources_cost_estimates.total_cost` instead of `staffing_plan.grand_total_cost`
    - `_business_case_has`: read from `executive_summary.business_case.problem_definition` (BusinessCase stays nested — path unchanged)
    - `_aws_annual_cost`: read from `cost_breakdown.arr` instead of `cost_breakdown.aws_service_cost.monthly_cost_summary`
    - Remove references to `StaffingCost`, `AWSServiceCost` sub-models
    - Keep `has_bedrock` reading from `architecture.services` (unchanged)
    - Keep `calculate_funding` formula: `eligible_amount = min(yr1_arr * 0.25, sow_cost, 125000)`
    - _Requirements: 7.1–7.9_

- [x] 5. Update agent patch paths
  - [x] 5.1 Update DiscoveryAgent and Orchestrator._delegate_discovery patch paths
    - Remove patches targeting `/meta/project_goal`, `/sections/scope_of_work/summary`
    - Update discovery patches to target v2 paths: `/sections/executive_summary/customer_intro`, `/sections/executive_summary/problem_statement`, etc.
    - Update `_discovery_schema_patches` helper for v2 field structure (nested business_case, bullets not items, FieldValue-based ScopeTask)
    - Remove any patches targeting `role_or_description`
    - _Requirements: 6.1, 6.2_

  - [x] 5.2 Update Orchestrator._delegate_architecture patch paths
    - Remove patches targeting `/sections/architecture/description` and `/sections/architecture/tools`
    - Add/update patches targeting `/sections/architecture/overview` and `/sections/architecture/tools_list`
    - _Requirements: 6.3, 6.4_

  - [x] 5.3 Update Orchestrator._delegate_staffing patch paths
    - Change patches from `/staffing_plan/roles/...` to `/sections/resources_cost_estimates/...`
    - Remove any patches targeting `/staffing_plan/...`
    - _Requirements: 6.5, 6.6_

  - [x] 5.4 Update ReviewerAgent for v2 schema
    - Remove `doc_state.staffing_plan.roles` references; read from `doc_state.sections.resources_cost_estimates`
    - Update `calculate_completion_score` to not reference `staffing_plan`
    - Ensure reviewer can generate patches targeting `/sections/cost_breakdown/funding_calculation`
    - _Requirements: 6.7, 6.8_

- [x] 6. Checkpoint — Verify all modules compile
  - Run `python -c "from agent.lib.schema.document_state import DocumentState; from agent.lambdas.gateway_tools.export_docx import _build_context; from agent.app.funding.funding_validator import FundingValidator"` to confirm no import errors
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Update template deployment config
  - [x] 7.1 Update Terraform and upload scripts
    - In `infra/terraform/main.tf`: change `TEMPLATE_S3_KEY` env var from `templates/apn-poc-template.docx` to `templates/apn-poc-template_v2.docx`
    - In `infra/scripts/upload_template.py`: change `DEFAULT_KEY` to `templates/apn-poc-template_v2.docx` and `--template` default to `agent/templates/apn-poc-template_v2.docx`
    - In `infra/scripts/upload_template.sh`: change `TEMPLATE_PATH` default to `agent/templates/apn-poc-template_v2.docx`
    - _Requirements: 5.1–5.5_

- [x] 8. Write schema v2 tests
  - [x] 8.1 Write schema smoke tests in `agent/lib/schema/test_schema_v2.py`
    - Test `DocumentState()` instantiates without error
    - Test `model_dump()` produces a valid JSON-serializable dict
    - Test FieldStatus enum has only `empty`, `draft`, `confirmed`
    - Test FieldValue has no `reason`, `source_patterns`, `confidence` attributes
    - Test FieldValue.resolve() priority: user_input > ai_recommended > calculated > ""
    - Test DocumentState has no `staffing_plan` attribute
    - Test ExecutiveSummarySection has no `text`, `summary` attributes but HAS `business_case: BusinessCase`
    - Test ArchitectureSection has no `description`, `tools` attributes; has `diagram_image_s3_key`, `tools_list`
    - Test AcceptanceSection has no `text` attribute; has `steps: list[AcceptanceStep]` with heading/content/bullets
    - Test ContactEntry has `description`, `stakeholder_for`, `role` and does NOT have `role_or_description`
    - Test CategoryGroup has `bullets: list[FieldValue]` (not `items`)
    - Test ScopeTask fields (`task_category`, `schedule`, `details`, `personnel`) are FieldValue
    - Test `partner_technical_team` is `list[TeamMember]` with role/name
    - Test `total_hours` and `total_cost` are `TotalsRow` with sa/eng/other/total
    - Test `phase_hours_table` is `list[PhaseHours]` with phase/sa_hours/eng_hours/other_hours/total
    - Test CostBreakdownSection has `calculator_url`, `mrr`, `arr`, `breakdown_table`, `bedrock_extra` (not aws_ prefixed)
    - Test CostBreakdownRow has `category`, `mrr`, `arr`, `note` (all FieldValue)
    - Test ScopeOfWorkSection has `tasks`, `out_of_scope`, `items`
    - Test `phases_overview`, `current_pain_points`, `poc_objectives` are list[FieldValue]
    - Test two DocumentState() instances have independent mutable lists
    - Test CoverSection allows extra fields; other sections forbid extra fields
    - _Requirements: 1.1–1.17, 2.1–2.7, 8.2, 8.3_

- [x] 9. Write export context builder v2 tests
  - [x] 9.1 Write export unit tests in `agent/lambdas/gateway_tools/test_export_v2.py`
    - Test empty payload does not raise exception
    - Test full v2 sample payload maps to all required template context keys
    - Test schema→template field mapping: `business_case.problem_definition` → `business_case_problem`, `diagram_image_s3_key` → `architecture_diagram_image`, `tools_list` → `architecture_tools_list`, `calculator_url` → `aws_calculator_url`, `mrr` → `aws_mrr`, `arr` → `aws_arr`, `breakdown_table` → `aws_cost_breakdown_table`, `bedrock_extra` → `aws_bedrock_extra`, `steps` → `acceptance_steps`, `scope_of_work.tasks` → `scope_tasks`, `scope_of_work.out_of_scope` → `scope_out_of_scope`, `scope_of_work.items` → `scope_items`
    - Test success_criteria_groups render with `category_name` and `bullets`
    - Test partner_technical_team renders as list of `{role, name}`
    - Test total_hours/total_cost render as `{sa, eng, other, total}`
    - Test architecture services are sorted by priority ascending
    - Test missing/failed diagram image does not fail context building
    - Test TEMPLATE_S3_KEY constant equals `templates/apn-poc-template_v2.docx`
    - Test no legacy keys present in output (`executive_summary_text`, `architecture_description`, `acceptance_text`, `architecture_tools`)
    - _Requirements: 3.1–3.14, 2.6, 8.4_

- [x] 10. Write funding validator v2 tests
  - [x] 10.1 Write funding unit tests in `agent/app/funding/test_funding_v2.py`
    - Test missing Bedrock creates blocking issue with code `BEDROCK_MISSING`
    - Test missing sponsor creates blocking issue or warning
    - Test eligible amount formula: `min(yr1_arr * 0.25, sow_cost, 125000)` with sample values
    - Test eligible amount is 0.0 when yr1_arr or sow_cost is zero
    - Test low/missing ARR creates warnings
    - Test FundingValidationResult is JSON-serializable
    - Test `has_calculator_url` reads from `cost_breakdown.calculator_url`
    - Test `_sow_cost` reads from `resources_cost_estimates.total_cost`
    - Test `_business_case_has` reads from `executive_summary.business_case.problem_definition` (nested)
    - _Requirements: 7.1–7.9, 8.5_

- [x] 11. Write agent patch path tests
  - [x] 11.1 Write agent patch path tests in `agent/app/test_agent_patch_paths_v2.py`
    - Test Discovery patches target v2 paths only (no `/meta/project_goal`, no `/sections/scope_of_work/summary`, no `role_or_description`)
    - Test Orchestrator architecture patches target `/sections/architecture/overview` and `/sections/architecture/tools_list` (not `/sections/architecture/description` or `/sections/architecture/tools`)
    - Test Orchestrator staffing patches target `/sections/resources_cost_estimates/...` (not `/staffing_plan/...`)
    - Test ReviewerAgent does not reference `staffing_plan.roles`
    - Test ReviewerAgent can patch `/sections/cost_breakdown/funding_calculation`
    - _Requirements: 6.1–6.8, 8.6_

- [x] 12. Checkpoint — Run full test suite
  - Run `pytest agent/lib/schema/test_schema_v2.py agent/lambdas/gateway_tools/test_export_v2.py agent/app/funding/test_funding_v2.py agent/app/test_agent_patch_paths_v2.py -v`
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Commit and push
  - [x] 13.1 Commit all changes and push to feature branch
    - Stage all modified and new files
    - Commit with message: `feat: rewrite DocumentState schema, export pipeline, funding validator, and agent patch paths for APN template v2`
    - Push to branch `feat/apn-template-v2-rewrite`
    - _Requirements: all_

## Notes

- No hypothesis or property-based testing — pytest unit tests only
- No new dev dependencies added
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation after each major phase
- No AWS integration tests — all tests are local, fast, and deterministic
- Section models use `extra="forbid"` except CoverSection (`extra="allow"` for dynamic agent metadata)
- BusinessCase remains nested under ExecutiveSummarySection — export context flattens it
- Schema field names are clean (no `aws_` prefix); export context maps to template keys with `aws_` prefix
