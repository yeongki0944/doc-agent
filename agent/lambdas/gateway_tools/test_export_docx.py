from __future__ import annotations

import io
import json
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


def test_bullet_join_handles_lists_fields_and_scalars():
    assert export_docx._bullet_join([
        {"user_input": "first"},
        {"ai_recommended": "second"},
        "",
        None,
    ]) == "- first\n- second"
    assert export_docx._bullet_join("plain text") == "plain text"
    assert export_docx._bullet_join(3) == "3"


def test_build_staffing_context():
    staffing = {
        "roles": {
            "pm": {
                "display_name": "Project Manager",
                "count": {"ai_recommended": 1},
                "allocation_pct": {"user_input": 50},
                "rate_per_hour": {"calculated": 100},
                "phase_hours": {
                    "discovery": {"user_input": 10},
                    "development": {"ai_recommended": 20},
                    "testing": {"calculated": 5},
                },
                "total_hours": {"calculated": 35},
                "total_cost": {"calculated": 3500},
                "reason": "needed",
            }
        },
        "grand_total_hours": {"calculated": 35},
        "grand_total_cost": {"calculated": 3500},
    }

    context = export_docx._build_staffing_context(staffing)

    assert context["grand_total_hours"] == 35
    assert context["grand_total_cost"] == 3500
    assert context["roles"] == [{
        "role_id": "pm",
        "display_name": "Project Manager",
        "count": 1,
        "allocation_pct": 50,
        "rate_per_hour": 100,
        "discovery_hours": 10,
        "development_hours": 20,
        "testing_hours": 5,
        "total_hours": 35,
        "total_cost": 3500,
        "reason": "needed",
    }]


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


def test_build_context():
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
            "executive_summary": {"summary": {"ai_recommended": "summary text"}},
            "stakeholders": {
                "executive_sponsors": [{"name": "Sponsor", "title": "Director", "description": "Approver", "contact": "sponsor@example.com"}],
                "stakeholders": [{"name": "Stakeholder", "title": "Manager", "stakeholder_for": "Scope", "contact": "stake@example.com"}],
                "project_team": [{"name": "Team", "title": "Engineer", "role": "Delivery", "contact": "team@example.com"}],
                "escalation_contacts": [{"name": "Esc", "title": "Lead", "role": "Escalation", "contact": "esc@example.com"}],
            },
            "scope_of_work": {"items": [{"user_input": "scope item"}]},
            "success_criteria": {"items": [{"user_input": "criteria item"}]},
            "assumptions": {"items": [{"user_input": "assumption item"}]},
            "architecture": {"description": {"ai_recommended": "arch desc"}, "tools": ["Lambda", "DynamoDB"]},
            "milestones": {"phases": [{"phase": {"user_input": "Phase 1"}, "completion_date": {"user_input": "2026-05-01"}, "deliverables": {"user_input": "Doc"}}]},
            "acceptance": {"text": {"ai_recommended": "acceptance text"}},
            "cost_breakdown": {"aws_service_cost": {"monthly_cost_summary": {"calculated": 1234}, "calculator_share_url": "https://calc"}},
            "resources_cost_estimates": {
                "contribution": {
                    "customer": {"amount": {"user_input": 100}, "pct": {"user_input": 100}},
                    "partner": {"amount": {"ai_recommended": 0}, "pct": {"ai_recommended": 0}},
                    "aws": {"amount": {"calculated": 0}, "pct": {"calculated": 0}},
                }
            },
        },
        "staffing_plan": {
            "roles": {
                "sa": {
                    "category": "solution_architect",
                    "phase_hours": {"discovery": {"calculated": 5}, "development": {"calculated": 10}, "testing": {"calculated": 0}},
                    "total_hours": {"calculated": 15},
                    "total_cost": {"calculated": 1500},
                },
                "eng": {
                    "category": "engineer",
                    "phase_hours": {"discovery": {"calculated": 3}, "development": {"calculated": 7}, "testing": {"calculated": 2}},
                    "total_hours": {"calculated": 12},
                    "total_cost": {"calculated": 1200},
                },
            },
            "grand_total_cost": {"calculated": 2700},
        },
    }

    context = export_docx._build_context(params)

    assert context["doc_id"] == "doc-1"
    assert context["version"] == 7
    assert context["customer"] == "ACME"
    assert context["partner"] == "MZC"
    assert context["cover"]["title"] == "PoC Plan"
    assert context["executive_summary"] == "summary text"
    assert context["scope_of_work"] == "- scope item"
    assert context["success_criteria"] == "- criteria item"
    assert context["assumptions"] == "- assumption item"
    assert context["architecture_description"] == "arch desc"
    assert context["architecture_tools"] == "- Lambda\n- DynamoDB"
    assert context["acceptance_text"] == "acceptance text"
    assert context["contribution"]["customer"]["amount"] == 100
    assert context["resources_cost_estimates"]["contribution"]["parties"]["customer"]["amount"] == 100
    assert context["total_hours"] == {"sa": 15, "eng": 12, "other": 0, "total": 27}
    assert context["total_cost"] == {"sa": 1500, "eng": 1200, "other": 0, "total": 2700}
    assert context["rate_solution_architect"] == 100
    assert context["rate_engineer"] == 100
    assert context["phase_hours_table"] == [
        {"phase": "discovery", "sa_hours": 5, "eng_hours": 3, "other_hours": 0, "total": 8},
        {"phase": "development", "sa_hours": 10, "eng_hours": 7, "other_hours": 0, "total": 17},
        {"phase": "testing", "sa_hours": 0, "eng_hours": 2, "other_hours": 0, "total": 2},
    ]
    assert context["executive_sponsors"][0]["description"] == "Approver"
    assert context["stakeholders"][0]["stakeholder_for"] == "Scope"
    assert context["project_team"][0]["role"] == "Delivery"
    assert context["escalation_contacts"][0]["role"] == "Escalation"
    assert context["milestones"][0]["phase"] == "Phase 1"
    assert context["aws_monthly_cost_summary"] == 1234
    assert context["aws_calculator_url"] == "https://calc"
    assert context["staffing"]["grand_total_cost"] == 2700


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
