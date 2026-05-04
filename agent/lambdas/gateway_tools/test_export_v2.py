"""Focused v2 export context builder tests.

Covers the specific requirements from task 9.1:
1. Empty payload does not raise exception
2. Full v2 sample payload maps to all required template context keys
3. Schema→template field mapping verification
4. success_criteria_groups render with category_name and bullets
5. partner_technical_team renders as list of {role, name}
6. total_hours/total_cost render as {sa, eng, other, total}
7. Architecture services sorted by priority ascending
8. Missing/failed diagram image does not fail context building
9. TEMPLATE_S3_KEY constant equals templates/apn-poc-template_v2.docx
10. No legacy keys present in output

Requirements: 3.1–3.14, 2.6, 8.4
"""

from __future__ import annotations

import pytest

from agent.lambdas.gateway_tools.export_docx import (
    TEMPLATE_S3_KEY,
    _build_context,
)


# ---------------------------------------------------------------------------
# Shared fixture: full v2 sample payload
# ---------------------------------------------------------------------------

def _full_v2_payload() -> dict:
    """Return a complete v2 DocumentState-like dict for testing."""
    return {
        "doc_id": "doc-v2-test",
        "version": 5,
        "meta": {
            "customer": {"user_input": "TestCorp"},
            "partner": {"user_input": "PartnerCo"},
            "date": {"user_input": "2026-06-01"},
        },
        "sections": {
            "cover": {"title": "PoC Plan v2"},
            "executive_summary": {
                "customer_intro": {"ai_recommended": "Intro text"},
                "problem_statement": {"ai_recommended": "Problem text"},
                "proposed_solution": {"ai_recommended": "Solution text"},
                "phases_overview": [{"ai_recommended": "Phase A"}, {"ai_recommended": "Phase B"}],
                "current_pain_points": [{"user_input": "Pain A"}],
                "poc_objectives": [{"ai_recommended": "Obj 1"}],
                "business_case": {
                    "problem_definition": {"ai_recommended": "Biz problem"},
                    "roi_calculation": {"ai_recommended": "ROI model"},
                    "executive_sponsor": {"ai_recommended": "Sponsor name"},
                    "production_commitment": {"ai_recommended": "Commitment text"},
                },
                "custom_blocks": [{"type": "note", "text": "block1"}],
            },
            "stakeholders": {
                "executive_sponsors": [{"name": {"user_input": "Sponsor"}, "title": {"user_input": "VP"}, "description": {"user_input": "Approver"}, "contact": {"user_input": "s@co.com"}}],
                "stakeholders": [{"name": {"user_input": "SH"}, "title": {"user_input": "Mgr"}, "stakeholder_for": {"user_input": "Scope"}, "contact": {"user_input": "sh@co.com"}}],
                "project_team": [{"name": {"user_input": "Dev"}, "title": {"user_input": "Eng"}, "role": {"user_input": "Builder"}, "contact": {"user_input": "d@co.com"}}],
                "escalation_contacts": [{"name": {"user_input": "Esc"}, "title": {"user_input": "Lead"}, "role": {"user_input": "Escalation"}, "contact": {"user_input": "e@co.com"}}],
            },
            "scope_of_work": {
                "items": [{"user_input": "scope item 1"}],
                "out_of_scope": [{"user_input": "excluded 1"}],
                "tasks": [
                    {
                        "task_category": {"ai_recommended": "Planning"},
                        "schedule": {"ai_recommended": "Week 1"},
                        "details": {"ai_recommended": "Detail text"},
                        "personnel": {"ai_recommended": "SA"},
                    },
                ],
            },
            "success_criteria": {
                "items": [{"user_input": "criteria 1"}],
                "groups": [
                    {
                        "category_name": {"ai_recommended": "Objective"},
                        "bullets": [{"ai_recommended": "Goal A"}, {"ai_recommended": "Goal B"}],
                    },
                    {
                        "category_name": {"user_input": "Technical"},
                        "bullets": [{"user_input": "Tech goal"}],
                    },
                ],
            },
            "assumptions": {
                "items": [{"user_input": "assumption 1"}],
                "groups": [
                    {"category_name": {"ai_recommended": "Context"}, "bullets": [{"ai_recommended": "Assumption A"}]},
                ],
            },
            "architecture": {
                "overview": {"ai_recommended": "Arch overview text"},
                "diagram_image_s3_key": {"ai_recommended": "diagrams/v2-arch.png"},
                "services": [
                    {"service_name": {"ai_recommended": "Amazon S3"}, "service_id": "amazon_s3", "priority": 10, "description": {"ai_recommended": "Storage"}, "sizing_rationale": {"ai_recommended": "Artifacts"}},
                    {"service_name": {"ai_recommended": "Amazon Bedrock"}, "service_id": "amazon_bedrock", "priority": 1, "description": {"ai_recommended": "LLM"}, "sizing_rationale": {"ai_recommended": "Core"}},
                    {"service_name": {"ai_recommended": "Amazon DynamoDB"}, "service_id": "amazon_dynamodb", "priority": 5, "description": {"ai_recommended": "NoSQL"}, "sizing_rationale": {"ai_recommended": "State"}},
                ],
                "tools_list": [{"ai_recommended": "Lambda"}, {"ai_recommended": "CDK"}],
            },
            "milestones": {
                "phases": [{"phase": {"user_input": "Phase 1"}, "completion_date": {"user_input": "2026-07-01"}, "deliverables": {"user_input": "Doc"}}],
            },
            "acceptance": {
                "steps": [
                    {
                        "heading": {"ai_recommended": "Step 1"},
                        "content": {"ai_recommended": "Verify deployment"},
                        "bullets": [{"ai_recommended": "Check logs"}, {"ai_recommended": "Run smoke"}],
                    },
                ],
            },
            "cost_breakdown": {
                "calculator_url": {"user_input": "https://calculator.aws"},
                "mrr": {"calculated": 2500},
                "arr": {"calculated": 30000},
                "breakdown_table": [
                    {"category": {"ai_recommended": "Bedrock"}, "mrr": {"calculated": 2000}, "arr": {"calculated": 24000}, "note": {"ai_recommended": "LLM costs"}},
                ],
                "bedrock_extra": {"ai_recommended": "Extra bedrock detail"},
            },
            "resources_cost_estimates": {
                "partner_technical_team": [
                    {"role": {"ai_recommended": "SA"}, "name": {"user_input": "Alice"}},
                    {"role": {"ai_recommended": "Engineer"}, "name": {"user_input": "Bob"}},
                    {"role": {"ai_recommended": "PM"}, "name": {"user_input": "Carol"}},
                ],
                "rate_solution_architect": {"calculated": 200},
                "rate_engineer": {"calculated": 150},
                "rate_other": {"calculated": 100},
                "phase_hours_table": [
                    {"phase": {"ai_recommended": "Discovery"}, "sa_hours": 20, "eng_hours": 10, "other_hours": 5, "total": 35},
                    {"phase": {"ai_recommended": "Build"}, "sa_hours": 30, "eng_hours": 40, "other_hours": 10, "total": 80},
                ],
                "total_hours": {"sa": "50", "eng": "50", "other": "15", "total": "115"},
                "total_cost": {"sa": "10000", "eng": "7500", "other": "1500", "total": "19000"},
                "contribution": {
                    "customer": {"amount": {"user_input": 200}, "pct": {"user_input": 100}},
                    "partner": {"amount": {"ai_recommended": 0}, "pct": {"ai_recommended": 0}},
                    "aws": {"amount": {"calculated": 0}, "pct": {"calculated": 0}},
                },
                "client_signature_customer_name": {"ai_recommended": "TestCorp"},
                "client_signature_person_name": {"ai_recommended": "Jane Doe"},
                "client_signature_designation": {"ai_recommended": "CTO"},
                "client_signature_date": {"ai_recommended": "2026-06-01"},
            },
        },
    }


# ---------------------------------------------------------------------------
# 1. Empty payload does not raise exception
# ---------------------------------------------------------------------------

class TestEmptyPayload:
    def test_none_payload_does_not_raise(self):
        context = _build_context(None)
        assert isinstance(context, dict)

    def test_empty_dict_payload_does_not_raise(self):
        context = _build_context({})
        assert isinstance(context, dict)

    def test_empty_sections_payload_does_not_raise(self):
        context = _build_context({"doc_id": "empty", "sections": {}})
        assert isinstance(context, dict)
        assert context["doc_id"] == "empty"


# ---------------------------------------------------------------------------
# 2. Full v2 sample payload maps to all required template context keys
# ---------------------------------------------------------------------------

class TestFullPayloadContextKeys:
    """Verify that a full v2 payload produces all required template context keys."""

    def test_all_required_keys_present(self):
        context = _build_context(_full_v2_payload())

        required_keys = [
            # Document meta
            "doc_id", "version", "customer", "partner", "date", "cover",
            # Executive summary
            "customer_intro", "problem_statement", "proposed_solution",
            "phases_overview", "current_pain_points", "poc_objectives", "custom_blocks",
            # Business case (flattened)
            "business_case_problem", "business_case_roi",
            "business_case_sponsor", "business_case_commitment",
            # Success criteria & assumptions
            "success_criteria_groups", "success_criteria_items",
            "assumptions_groups", "assumptions_items",
            # Scope of work
            "scope_tasks", "scope_out_of_scope", "scope_items",
            # Architecture
            "architecture_overview", "architecture_diagram_image",
            "architecture_services", "architecture_tools_list",
            # Stakeholders
            "executive_sponsors", "stakeholders", "project_team", "escalation_contacts",
            # Milestones
            "milestones",
            # AWS cost breakdown
            "aws_calculator_url", "aws_mrr", "aws_arr",
            "aws_cost_breakdown_table", "aws_bedrock_extra",
            # Acceptance
            "acceptance_steps",
            # Resources & cost estimates
            "partner_technical_team", "rate_solution_architect", "rate_engineer", "rate_other",
            "phase_hours_table", "total_hours", "total_cost",
            # Contribution
            "contribution",
            # Client signatures
            "client_signature_customer_name", "client_signature_person_name",
            "client_signature_designation", "client_signature_date",
            # Funding
            "funding_eligible", "bedrock_status",
        ]

        for key in required_keys:
            assert key in context, f"Missing required context key: {key}"


# ---------------------------------------------------------------------------
# 3. Schema→template field mapping
# ---------------------------------------------------------------------------

class TestFieldMapping:
    """Verify schema field names map to the correct template context keys."""

    @pytest.fixture()
    def context(self):
        return _build_context(_full_v2_payload())

    def test_business_case_problem_definition_maps(self, context):
        assert context["business_case_problem"] == "Biz problem"

    def test_diagram_image_s3_key_maps(self, context):
        assert context["architecture_diagram_image"] == "diagrams/v2-arch.png"

    def test_tools_list_maps(self, context):
        assert context["architecture_tools_list"] == ["Lambda", "CDK"]

    def test_calculator_url_maps(self, context):
        assert context["aws_calculator_url"] == "https://calculator.aws"

    def test_mrr_maps(self, context):
        assert context["aws_mrr"] == 2500

    def test_arr_maps(self, context):
        assert context["aws_arr"] == 30000

    def test_breakdown_table_maps(self, context):
        assert len(context["aws_cost_breakdown_table"]) == 1
        assert context["aws_cost_breakdown_table"][0]["category"] == "Bedrock"

    def test_bedrock_extra_maps(self, context):
        assert context["aws_bedrock_extra"] == "Extra bedrock detail"

    def test_acceptance_steps_maps(self, context):
        assert len(context["acceptance_steps"]) == 1
        step = context["acceptance_steps"][0]
        assert step["heading"] == "Step 1"
        assert step["content"] == "Verify deployment"
        assert step["bullets"] == ["Check logs", "Run smoke"]

    def test_scope_tasks_maps(self, context):
        assert len(context["scope_tasks"]) == 1
        assert context["scope_tasks"][0]["task_category"] == "Planning"
        assert context["scope_tasks"][0]["details"] == "Detail text"

    def test_scope_out_of_scope_maps(self, context):
        assert context["scope_out_of_scope"] == ["excluded 1"]

    def test_scope_items_maps(self, context):
        assert context["scope_items"] == ["scope item 1"]


# ---------------------------------------------------------------------------
# 4. success_criteria_groups render with category_name and bullets
# ---------------------------------------------------------------------------

class TestSuccessCriteriaGroups:
    def test_groups_have_category_name_and_bullets_text(self):
        context = _build_context(_full_v2_payload())
        groups = context["success_criteria_groups"]

        assert len(groups) == 2

        assert groups[0]["category_name"] == "Objective"
        assert groups[0]["bullets_text"] == "- Goal A\n- Goal B"

        assert groups[1]["category_name"] == "Technical"
        assert groups[1]["bullets_text"] == "- Tech goal"

    def test_success_criteria_items_resolved(self):
        context = _build_context(_full_v2_payload())
        assert context["success_criteria_items"] == ["criteria 1"]


# ---------------------------------------------------------------------------
# 5. partner_technical_team renders as list of {role, name}
# ---------------------------------------------------------------------------

class TestPartnerTechnicalTeam:
    def test_renders_as_role_name_dicts(self):
        context = _build_context(_full_v2_payload())
        team = context["partner_technical_team"]

        assert len(team) == 3
        assert team[0] == {"role": "SA", "name": "Alice"}
        assert team[1] == {"role": "Engineer", "name": "Bob"}
        assert team[2] == {"role": "PM", "name": "Carol"}

    def test_each_member_has_only_role_and_name(self):
        context = _build_context(_full_v2_payload())
        for member in context["partner_technical_team"]:
            assert set(member.keys()) == {"role", "name"}


# ---------------------------------------------------------------------------
# 6. total_hours/total_cost render as {sa, eng, other, total}
# ---------------------------------------------------------------------------

class TestTotalsRendering:
    def test_total_hours_structure(self):
        context = _build_context(_full_v2_payload())
        assert context["total_hours"] == {"sa": "50", "eng": "50", "other": "15", "total": "115"}

    def test_total_cost_structure(self):
        context = _build_context(_full_v2_payload())
        assert context["total_cost"] == {"sa": "10000", "eng": "7500", "other": "1500", "total": "19000"}

    def test_totals_keys_are_sa_eng_other_total(self):
        context = _build_context(_full_v2_payload())
        expected_keys = {"sa", "eng", "other", "total"}
        assert set(context["total_hours"].keys()) == expected_keys
        assert set(context["total_cost"].keys()) == expected_keys


# ---------------------------------------------------------------------------
# 7. Architecture services sorted by priority ascending
# ---------------------------------------------------------------------------

class TestArchitectureServiceSorting:
    def test_services_sorted_by_priority_ascending(self):
        context = _build_context(_full_v2_payload())
        services = context["architecture_services"]

        assert len(services) == 3
        priorities = [s["priority"] for s in services]
        assert priorities == sorted(priorities), f"Services not sorted by priority: {priorities}"

    def test_service_order_matches_expected(self):
        context = _build_context(_full_v2_payload())
        names = [s["service_name"] for s in context["architecture_services"]]
        # priority 1=Bedrock, 5=DynamoDB, 10=S3
        assert names == ["Amazon Bedrock", "Amazon DynamoDB", "Amazon S3"]


# ---------------------------------------------------------------------------
# 8. Missing/failed diagram image does not fail context building
# ---------------------------------------------------------------------------

class TestMissingDiagramImage:
    def test_missing_diagram_key_produces_empty_string(self):
        payload = {
            "sections": {
                "architecture": {
                    "overview": {"ai_recommended": "overview"},
                    "services": [],
                    # diagram_image_s3_key intentionally omitted
                },
            },
        }
        context = _build_context(payload)
        assert context["architecture_diagram_image"] == ""

    def test_empty_diagram_value_produces_empty_string(self):
        payload = {
            "sections": {
                "architecture": {
                    "diagram_image_s3_key": {"ai_recommended": ""},
                    "services": [],
                },
            },
        }
        context = _build_context(payload)
        assert context["architecture_diagram_image"] == ""

    def test_none_diagram_value_produces_empty_string(self):
        payload = {
            "sections": {
                "architecture": {
                    "diagram_image_s3_key": None,
                    "services": [],
                },
            },
        }
        context = _build_context(payload)
        assert context["architecture_diagram_image"] == ""


# ---------------------------------------------------------------------------
# 9. TEMPLATE_S3_KEY constant
# ---------------------------------------------------------------------------

class TestTemplateS3Key:
    def test_template_s3_key_is_v2(self):
        assert TEMPLATE_S3_KEY == "templates/apn-poc-template_v2.docx"


# ---------------------------------------------------------------------------
# 10. No legacy keys present in output
# ---------------------------------------------------------------------------

class TestNoLegacyKeys:
    """Verify that legacy v1 context keys are absent from the output."""

    LEGACY_KEYS = [
        "executive_summary_text",
        "architecture_description",
        "acceptance_text",
        "architecture_tools",
    ]

    def test_no_legacy_keys_in_full_payload(self):
        context = _build_context(_full_v2_payload())
        for key in self.LEGACY_KEYS:
            assert key not in context, f"Legacy key found in context: {key}"

    def test_no_legacy_keys_in_empty_payload(self):
        context = _build_context({})
        for key in self.LEGACY_KEYS:
            assert key not in context, f"Legacy key found in empty context: {key}"
