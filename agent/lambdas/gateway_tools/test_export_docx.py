from __future__ import annotations

import io
import json
from zipfile import ZipFile
from unittest.mock import MagicMock, patch

from agent.lambdas.gateway_tools import export_docx


def _payload(result: dict) -> dict:
    return json.loads(result["outputPayload"])


def test_resolve_field_priority_and_literals():
    assert export_docx._resolve_field({"user_input": 0, "ai_recommended": 1, "calculated": 2}) == 0
    assert export_docx._resolve_field({"user_input": "", "ai_recommended": "ai", "calculated": "calc"}) == "ai"
    assert export_docx._resolve_field({"user_input": None, "ai_recommended": None, "calculated": "calc"}) == "calc"
    assert export_docx._resolve_field("literal") == "literal"
    assert export_docx._resolve_field(None) == ""


def test_helper_formatting_functions():
    assert export_docx.resolve_field_value({"user_input": "", "ai_recommended": "ai"}) == "ai"
    assert export_docx.join_field_values(["alpha", {"ai_recommended": "beta"}]) == "alpha\nbeta"
    assert export_docx.money_format(1234567) == "1,234,567"
    assert export_docx.money_format({"calculated": 1234567.5}) == "1,234,567.5"
    assert export_docx.bool_status(True) == "Yes"
    assert export_docx.bool_status(False, "On", "Off") == "Off"


def test_bullet_join_handles_lists_fields_and_scalars():
    assert export_docx._bullet_join([
        {"user_input": "first"},
        {"ai_recommended": "second"},
        "",
        None,
    ]) == "- first\n- second"
    assert export_docx._bullet_join("plain text") == "plain text"
    assert export_docx._bullet_join(3) == "3"


def test_partner_team_rows():
    """v2: partner_technical_team renders as list of {role, name}."""
    rows = export_docx._partner_team_rows([
        {"role": {"ai_recommended": "SA"}, "name": {"user_input": "Alice"}},
        {"role": {"ai_recommended": "Engineer"}, "name": {"ai_recommended": "Bob"}},
    ])
    assert rows == [
        {"role": "SA", "name": "Alice"},
        {"role": "Engineer", "name": "Bob"},
    ]


def test_phase_hours_rows():
    """v2: phase_hours_table renders as list of {phase, sa_hours, eng_hours, other_hours, total}."""
    rows = export_docx._phase_hours_rows([
        {"phase": {"ai_recommended": "Discovery"}, "sa_hours": 10, "eng_hours": 5, "other_hours": 2, "total": 17},
        {"phase": {"ai_recommended": "Build"}, "sa_hours": 20, "eng_hours": 15, "other_hours": 0, "total": 35},
    ])
    assert rows == [
        {"phase": "Discovery", "sa_hours": 10, "eng_hours": 5, "other_hours": 2, "total": 17},
        {"phase": "Build", "sa_hours": 20, "eng_hours": 15, "other_hours": 0, "total": 35},
    ]


def test_totals_row():
    """v2: TotalsRow renders as {sa, eng, other, total} strings."""
    result = export_docx._totals_row({"sa": "100", "eng": "200", "other": "50", "total": "350"})
    assert result == {"sa": "100", "eng": "200", "other": "50", "total": "350"}

    # Missing data returns empty strings
    result = export_docx._totals_row({})
    assert result == {"sa": "", "eng": "", "other": "", "total": ""}

    # Non-dict returns empty strings
    result = export_docx._totals_row(None)
    assert result == {"sa": "", "eng": "", "other": "", "total": ""}


def test_build_contribution():
    context = export_docx._build_contribution({
        "contribution": {
            "customer": {"amount": {"user_input": 100}, "pct": {"user_input": 50}},
            "partner": {"amount": {"ai_recommended": 80}, "pct": {"ai_recommended": 40}},
            "aws": {"amount": {"calculated": 20}, "pct": {"calculated": 10}},
        }
    })

    assert context["parties"]["customer"] == {"amount": 100, "pct": 50}
    assert context["parties"]["partner"] == {"amount": 80, "pct": 40}
    assert context["parties"]["aws"] == {"amount": 20, "pct": 10}
    assert context["rows"][0] == {"party": "customer", "amount": 100, "pct": 50}


def test_build_context_v2():
    """v2: _build_context reads from v2 schema paths only. No legacy fallbacks."""
    params = {
        "doc_id": "doc-1",
        "version": 7,
        "meta": {
            "customer": {"user_input": "ACME"},
            "partner": {"user_input": "MZC"},
            "date": {"user_input": "2026-04-26"},
        },
        "sections": {
            "cover": {"title": "PoC Plan"},
            "executive_summary": {
                "customer_intro": {"ai_recommended": "Customer intro"},
                "problem_statement": {"ai_recommended": "Problem statement"},
                "proposed_solution": {"ai_recommended": "Proposed solution"},
                "phases_overview": [
                    {"ai_recommended": "Discovery"},
                    {"ai_recommended": "Build"},
                ],
                "current_pain_points": [
                    {"user_input": "Pain 1"},
                ],
                "poc_objectives": [
                    {"ai_recommended": "Objective 1"},
                ],
                "business_case": {
                    "problem_definition": {"ai_recommended": "Business problem"},
                    "roi_calculation": {"ai_recommended": "ROI model"},
                    "executive_sponsor": {"ai_recommended": "Executive sponsor"},
                    "production_commitment": {"ai_recommended": "Production commitment"},
                },
                "custom_blocks": [{"type": "note", "text": "custom"}],
            },
            "stakeholders": {
                "executive_sponsors": [{"name": {"user_input": "Sponsor"}, "title": {"user_input": "Director"}, "description": {"user_input": "Approver"}, "contact": {"user_input": "sponsor@example.com"}}],
                "stakeholders": [{"name": {"user_input": "Stakeholder"}, "title": {"user_input": "Manager"}, "stakeholder_for": {"user_input": "Scope"}, "contact": {"user_input": "stake@example.com"}}],
                "project_team": [{"name": {"user_input": "Team"}, "title": {"user_input": "Engineer"}, "role": {"user_input": "Delivery"}, "contact": {"user_input": "team@example.com"}}],
                "escalation_contacts": [{"name": {"user_input": "Esc"}, "title": {"user_input": "Lead"}, "role": {"user_input": "Escalation"}, "contact": {"user_input": "esc@example.com"}}],
            },
            "scope_of_work": {
                "items": [{"user_input": "scope item"}],
                "out_of_scope": [{"user_input": "excluded item"}],
                "tasks": [
                    {
                        "task_category": {"ai_recommended": "Planning"},
                        "schedule": {"ai_recommended": "Week 1"},
                        "details": {"ai_recommended": "Task detail"},
                        "personnel": {"ai_recommended": "SA"},
                    }
                ],
            },
            "success_criteria": {
                "items": [{"user_input": "criteria item"}],
                "groups": [
                    {"category_name": {"ai_recommended": "Project Objective"}, "bullets": [{"ai_recommended": "Goal 1"}]},
                ],
            },
            "assumptions": {
                "items": [{"user_input": "assumption item"}],
                "groups": [
                    {"category_name": {"ai_recommended": "Business Context"}, "bullets": [{"ai_recommended": "Assumption 1"}]},
                ],
            },
            "architecture": {
                "overview": {"ai_recommended": "arch overview"},
                "diagram_image_s3_key": {"ai_recommended": "diagrams/arch.png"},
                "services": [
                    {
                        "service_name": {"ai_recommended": "Amazon S3"},
                        "service_id": "amazon_s3",
                        "priority": 11,
                        "description": {"ai_recommended": "Object storage"},
                        "sizing_rationale": {"ai_recommended": "Artifacts"},
                    },
                    {
                        "service_name": {"ai_recommended": "Amazon Bedrock"},
                        "service_id": "amazon_bedrock",
                        "priority": 1,
                        "description": {"ai_recommended": "Foundation model"},
                        "sizing_rationale": {"ai_recommended": "Required"},
                    },
                ],
                "tools_list": [{"ai_recommended": "Lambda"}, {"ai_recommended": "DynamoDB"}],
            },
            "milestones": {
                "phases": [{"phase": {"user_input": "Phase 1"}, "completion_date": {"user_input": "2026-05-01"}, "deliverables": {"user_input": "Doc"}}],
            },
            "acceptance": {
                "steps": [
                    {
                        "heading": {"ai_recommended": "Step 1"},
                        "content": {"ai_recommended": "Verify deployment"},
                        "bullets": [{"ai_recommended": "Check logs"}, {"ai_recommended": "Run smoke test"}],
                    }
                ],
            },
            "cost_breakdown": {
                "calculator_url": {"user_input": "https://calc"},
                "mrr": {"calculated": 1234},
                "arr": {"calculated": 14808},
                "breakdown_table": [
                    {"category": {"ai_recommended": "Bedrock"}, "mrr": {"calculated": 1000}, "arr": {"calculated": 12000}, "note": {"ai_recommended": "LLM"}},
                ],
                "bedrock_extra": {"ai_recommended": "Extra bedrock info"},
            },
            "resources_cost_estimates": {
                "partner_technical_team": [
                    {"role": {"ai_recommended": "SA"}, "name": {"user_input": "Alice"}},
                    {"role": {"ai_recommended": "Engineer"}, "name": {"user_input": "Bob"}},
                ],
                "rate_solution_architect": {"calculated": 150},
                "rate_engineer": {"calculated": 120},
                "rate_other": {"calculated": 100},
                "phase_hours_table": [
                    {"phase": {"ai_recommended": "Discovery"}, "sa_hours": 10, "eng_hours": 5, "other_hours": 2, "total": 17},
                ],
                "total_hours": {"sa": "40", "eng": "60", "other": "10", "total": "110"},
                "total_cost": {"sa": "6000", "eng": "7200", "other": "1000", "total": "14200"},
                "contribution": {
                    "customer": {"amount": {"user_input": 100}, "pct": {"user_input": 100}},
                    "partner": {"amount": {"ai_recommended": 0}, "pct": {"ai_recommended": 0}},
                    "aws": {"amount": {"calculated": 0}, "pct": {"calculated": 0}},
                },
                "client_signature_customer_name": {"ai_recommended": "ACME"},
                "client_signature_person_name": {"ai_recommended": "Jane"},
                "client_signature_designation": {"ai_recommended": "Director"},
                "client_signature_date": {"ai_recommended": "2026-04-26"},
            },
        },
    }

    context = export_docx._build_context(params)

    # --- Document meta ---
    assert context["doc_id"] == "doc-1"
    assert context["version"] == 7
    assert context["customer"] == "ACME"
    assert context["partner"] == "MZC"
    assert context["cover"]["title"] == "PoC Plan"

    # --- Executive Summary (v2 keys) ---
    assert context["customer_intro"] == "Customer intro"
    assert context["problem_statement"] == "Problem statement"
    assert context["proposed_solution"] == "Proposed solution"
    assert context["phases_overview"] == ["Discovery", "Build"]
    assert context["current_pain_points"] == ["Pain 1"]
    assert context["poc_objectives"] == ["Objective 1"]
    assert context["custom_blocks"] == [{"type": "note", "text": "custom"}]

    # --- Business Case (flattened from nested) ---
    assert context["business_case_problem"] == "Business problem"
    assert context["business_case_roi"] == "ROI model"
    assert context["business_case_sponsor"] == "Executive sponsor"
    assert context["business_case_commitment"] == "Production commitment"

    # --- Success Criteria (v2: bullets not items) ---
    assert context["success_criteria_groups"][0]["category_name"] == "Project Objective"
    assert context["success_criteria_groups"][0]["bullets_text"] == "- Goal 1"
    assert context["success_criteria_items"] == ["criteria item"]

    # --- Assumptions (v2: bullets not items) ---
    assert context["assumptions_groups"][0]["category_name"] == "Business Context"
    assert context["assumptions_items"] == ["assumption item"]

    # --- Scope of Work (v2: tasks, out_of_scope, items) ---
    assert context["scope_tasks"][0]["task_category"] == "Planning"
    assert context["scope_tasks"][0]["details"] == "Task detail"
    assert context["scope_out_of_scope"] == ["excluded item"]
    assert context["scope_items"] == ["scope item"]

    # --- Architecture (v2: overview, diagram_image_s3_key, tools_list) ---
    assert context["architecture_overview"] == "arch overview"
    assert context["architecture_diagram_image"] == "diagrams/arch.png"
    assert context["architecture_tools_list"] == ["Lambda", "DynamoDB"]
    assert [s["service_name"] for s in context["architecture_services"]] == ["Amazon Bedrock", "Amazon S3"]

    # --- Stakeholders ---
    assert context["executive_sponsors"][0]["description"] == "Approver"
    assert context["stakeholders"][0]["stakeholder_for"] == "Scope"
    assert context["project_team"][0]["role"] == "Delivery"
    assert context["escalation_contacts"][0]["role"] == "Escalation"

    # --- Milestones ---
    assert context["milestones"][0]["phase"] == "Phase 1"

    # --- AWS Cost Breakdown (v2: schema names → aws_ prefixed) ---
    assert context["aws_calculator_url"] == "https://calc"
    assert context["aws_mrr"] == 1234
    assert context["aws_arr"] == 14808
    assert context["aws_cost_breakdown_table"][0]["category"] == "Bedrock"
    assert context["aws_bedrock_extra"] == "Extra bedrock info"

    # --- Acceptance (v2: steps) ---
    assert context["acceptance_steps"][0]["heading"] == "Step 1"
    assert context["acceptance_steps"][0]["content"] == "Verify deployment"
    assert context["acceptance_steps"][0]["bullets"] == ["Check logs", "Run smoke test"]

    # --- Resources & Cost Estimates (v2: from resources_cost_estimates) ---
    assert context["partner_technical_team"] == [
        {"role": "SA", "name": "Alice"},
        {"role": "Engineer", "name": "Bob"},
    ]
    assert context["rate_solution_architect"] == 150
    assert context["rate_engineer"] == 120
    assert context["rate_other"] == 100
    assert context["phase_hours_table"] == [
        {"phase": "Discovery", "sa_hours": 10, "eng_hours": 5, "other_hours": 2, "total": 17},
    ]
    assert context["total_hours"] == {"sa": "40", "eng": "60", "other": "10", "total": "110"}
    assert context["total_cost"] == {"sa": "6000", "eng": "7200", "other": "1000", "total": "14200"}

    # --- Contribution ---
    assert context["contribution"]["customer"]["amount"] == 100

    # --- Client Signatures (v2: from resources_cost_estimates) ---
    assert context["client_signature_customer_name"] == "ACME"
    assert context["client_signature_person_name"] == "Jane"
    assert context["client_signature_designation"] == "Director"
    assert context["client_signature_date"] == "2026-04-26"

    # --- Funding ---
    assert context["bedrock_status"] == "Included"
    assert context["funding_eligible"] == "Eligible"

    # --- No legacy keys ---
    assert "executive_summary_text" not in context
    assert "executive_summary" not in context
    assert "architecture_description" not in context
    assert "acceptance_text" not in context
    assert "architecture_tools" not in context
    assert "signature_customer_name" not in context
    assert "staffing" not in context
    assert "aws_monthly_cost_summary" not in context
    assert "scope_of_work" not in context
    assert "success_criteria" not in context
    assert "assumptions" not in context


def test_build_context_preserves_all_stakeholder_rows():
    context = export_docx._build_context({
        "sections": {
            "stakeholders": {
                "executive_sponsors": [
                    {"name": {"user_input": "James, Kong"}, "title": {"user_input": "CAIO"}, "description": {"user_input": "Head of AI Business"}, "contact": {"user_input": "jameskong@megazone.com"}},
                ],
                "stakeholders": [
                    {"name": {"user_input": "Project Stakeholders"}, "title": {"user_input": "Project Manager"}, "stakeholder_for": {"user_input": "QA"}, "contact": {"user_input": "Project Stakeholders@mail.com"}},
                    {"name": {"user_input": "Project Stakeholders2"}, "title": {"user_input": "Director"}, "stakeholder_for": {"user_input": "PMO"}, "contact": {"user_input": "Project Stakeholders@gmail.com"}},
                ],
                "project_team": [
                    {"name": {"user_input": "Partner Project Team"}, "title": {"user_input": "Director"}, "role": {"user_input": "Architect"}, "contact": {"user_input": "Partner Project Team@gmail.com"}},
                    {"name": {"user_input": "Partner Project Team22"}, "title": {"user_input": "123"}, "role": {"user_input": "Partner Project Team"}, "contact": {"user_input": "Partner Project Team@ㅁgmail.223"}},
                ],
                "escalation_contacts": [
                    {"name": {"user_input": "123"}, "title": {"user_input": "Director"}, "role": {"user_input": "Engagement Partner"}, "contact": {"user_input": "gmail.com"}},
                    {"name": {"user_input": "123123"}, "title": {"user_input": "Director"}, "role": {"user_input": "Architect"}, "contact": {"user_input": "test.mail"}},
                ],
            }
        }
    })

    assert len(context["executive_sponsors"]) == 1
    assert len(context["stakeholders"]) == 2
    assert len(context["project_team"]) == 2
    assert len(context["escalation_contacts"]) == 2
    assert context["stakeholders"][1] == {
        "name": "Project Stakeholders2",
        "title": "Director",
        "description": "PMO",
        "stakeholder_for": "PMO",
        "role": "PMO",
        "contact": "Project Stakeholders@gmail.com",
    }
    assert context["project_team"][1]["role"] == "Partner Project Team"
    assert context["escalation_contacts"][1]["contact"] == "test.mail"


def test_v2_template_uses_stakeholder_table_row_loops():
    with ZipFile("agent/templates/apn-poc-template_v2.docx") as template:
        document_xml = template.read("word/document.xml").decode("utf-8")

    expected_fragments = [
        "{%tr for row in executive_sponsors %}",
        "{{ row.name }}",
        "{{ row.title }}",
        "{{ row.description }}",
        "{{ row.contact }}",
        "{%tr for row in stakeholders %}",
        "{{ row.stakeholder_for }}",
        "{%tr for row in project_team %}",
        "{{ row.role }}",
        "{%tr for row in escalation_contacts %}",
        "{%tr endfor %}",
    ]
    for fragment in expected_fragments:
        assert fragment in document_xml


def test_build_context_handles_missing_optional_fields():
    """v2: empty sections produce empty defaults, no exceptions."""
    context = export_docx._build_context({
        "doc_id": "doc-2",
        "sections": {},
    })

    assert context["customer_intro"] == ""
    assert context["problem_statement"] == ""
    assert context["proposed_solution"] == ""
    assert context["phases_overview"] == []
    assert context["current_pain_points"] == []
    assert context["poc_objectives"] == []
    assert context["success_criteria_groups"] == []
    assert context["assumptions_groups"] == []
    assert context["scope_tasks"] == []
    assert context["scope_out_of_scope"] == []
    assert context["scope_items"] == []
    assert context["architecture_services"] == []
    assert context["architecture_diagram_image"] == ""
    assert context["architecture_tools_list"] == []
    assert context["acceptance_steps"] == []
    assert context["partner_technical_team"] == []
    assert context["phase_hours_table"] == []
    assert context["total_hours"] == {"sa": "", "eng": "", "other": "", "total": ""}
    assert context["total_cost"] == {"sa": "", "eng": "", "other": "", "total": ""}
    assert context["client_signature_customer_name"] == ""
    assert context["client_signature_person_name"] == ""
    assert context["funding_eligible"] == "Not eligible"


def test_group_rows_reads_bullets_not_items():
    """v2: _group_rows reads `bullets` from CategoryGroup, not `items`."""
    groups = [
        {"category_name": {"ai_recommended": "Category A"}, "bullets": [{"ai_recommended": "Bullet 1"}, {"ai_recommended": "Bullet 2"}]},
        {"category_name": {"user_input": "Category B"}, "bullets": [{"user_input": "Bullet 3"}]},
    ]
    rows = export_docx._group_rows(groups)
    assert len(rows) == 2
    assert rows[0]["category_name"] == "Category A"
    assert rows[0]["bullets_text"] == "- Bullet 1\n- Bullet 2"
    assert rows[1]["category_name"] == "Category B"
    assert rows[1]["bullets_text"] == "- Bullet 3"


def test_scope_task_rows_details_is_single_field_value():
    """v2: ScopeTask.details is a single FieldValue, not a list."""
    tasks = [
        {
            "task_category": {"ai_recommended": "Planning"},
            "schedule": {"ai_recommended": "Week 1"},
            "details": {"ai_recommended": "Single detail text"},
            "personnel": {"ai_recommended": "SA"},
        }
    ]
    rows = export_docx._scope_task_rows(tasks)
    assert len(rows) == 1
    assert rows[0]["details"] == "Single detail text"
    assert rows[0]["task_category"] == "Planning"


def test_template_s3_key_is_v2():
    """v2: TEMPLATE_S3_KEY points to the v2 template."""
    assert export_docx.TEMPLATE_S3_KEY == "templates/apn-poc-template_v2.docx"


def test_architecture_service_sorting_and_funding_formatting():
    context = export_docx._build_context({
        "sections": {
            "architecture": {
                "services": [
                    {"service_name": "Amazon S3", "service_id": "amazon_s3", "priority": 11, "description": "Storage", "sizing_rationale": "Keep artifacts"},
                    {"service_name": "Amazon Bedrock", "service_id": "amazon_bedrock", "priority": 1, "description": "LLM", "sizing_rationale": "Required"},
                ]
            },
            "cost_breakdown": {
                "funding_calculation": {
                    "yr1_arr": {"calculated": 1000000},
                    "sow_cost": {"calculated": 250000},
                    "eligible_amount": {"calculated": 125000},
                },
                "aws_service_cost": {"monthly_cost_summary": {"calculated": 1234}},
            },
        },
        "staffing_plan": {"grand_total_cost": {"calculated": 100000}},
    })

    assert [service["service_name"] for service in context["architecture_services"]] == ["Amazon Bedrock", "Amazon S3"]
    assert context["yr1_arr"] == "1,000,000"
    assert context["sow_cost"] == "250,000"
    assert context["eligible_amount"] == "125,000"


@patch("agent.lambdas.gateway_tools.export_docx._render_docx")
@patch("agent.lambdas.gateway_tools.export_docx.boto3")
def test_handler_downloads_template_renders_and_uploads(mock_boto3, mock_render):
    mock_s3 = MagicMock()
    mock_s3.get_object.return_value = {"Body": io.BytesIO(b"template-bytes")}
    mock_s3.generate_presigned_url.return_value = "https://download"
    mock_boto3.client.return_value = mock_s3
    mock_render.return_value = b"rendered-docx"

    result = _payload(export_docx.handler({
        "inputPayload": json.dumps({
            "doc_id": "doc-1",
            "version": 3,
            "meta": {"customer": {"user_input": "ACME"}},
            "sections": {},
            "staffing_plan": {"roles": {}},
        })
    }, None))

    assert result == {
        "s3_key": "docs/doc-1/exports/doc-1-v3.docx",
        "bucket": export_docx.ARTIFACTS_BUCKET,
        "download_url": "https://download",
    }
    mock_s3.get_object.assert_called_once_with(
        Bucket=export_docx.ARTIFACTS_BUCKET,
        Key=export_docx.TEMPLATE_S3_KEY,
    )
    mock_render.assert_called_once()
    assert mock_render.call_args.args[0] == b"template-bytes"
    mock_s3.put_object.assert_called_once_with(
        Bucket=export_docx.ARTIFACTS_BUCKET,
        Key="docs/doc-1/exports/doc-1-v3.docx",
        Body=b"rendered-docx",
        ContentType=export_docx.DOCX_CONTENT_TYPE,
    )


def test_handler_returns_structured_error_for_bad_json():
    result = _payload(export_docx.handler({"inputPayload": "not json"}, None))

    assert result["stage"] == "parse_input"
    assert result["error_type"] == "JSONDecodeError"
    assert "error" in result
