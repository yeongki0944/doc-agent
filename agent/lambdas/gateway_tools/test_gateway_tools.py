"""Unit tests for the 6 Gateway tool Lambda handlers.

Each handler follows the contract:
  - Input: event["inputPayload"] (JSON string)
  - Output: {"outputPayload": json.dumps(result)}
  - Errors: {"outputPayload": json.dumps({"error": message})}
"""

from __future__ import annotations

import io
import json
from unittest.mock import patch, MagicMock

import pytest

from agent.lambdas.gateway_tools.validate_template import (
    handler as validate_handler,
    APN_REQUIRED_SECTIONS,
)
from agent.lambdas.gateway_tools.calc_staffing import handler as calc_handler
from agent.lambdas.gateway_tools.build_milestones import handler as milestones_handler
from agent.lambdas.gateway_tools.estimate_cost import handler as cost_handler
from agent.lambdas.gateway_tools.generate_diagram import handler as diagram_handler
from agent.lambdas.gateway_tools.export_docx import handler as docx_handler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _invoke(handler_fn, params: dict) -> dict:
    """Call a handler with inputPayload and parse the outputPayload."""
    event = {"inputPayload": json.dumps(params)}
    result = handler_fn(event, None)
    assert "outputPayload" in result
    return json.loads(result["outputPayload"])


SAMPLE_STAFFING_PLAN = {
    "roles": {
        "project_manager": {
            "display_name": "Project Manager",
            "count": {"user_input": None, "ai_recommended": 1, "calculated": None},
            "allocation_pct": {"user_input": None, "ai_recommended": 50, "calculated": None},
            "rate_per_hour": {"user_input": None, "ai_recommended": 81.78, "calculated": None},
            "phase_hours": {
                "discovery": {"user_input": None, "ai_recommended": 40, "calculated": None},
                "development": {"user_input": None, "ai_recommended": 80, "calculated": None},
                "testing": {"user_input": None, "ai_recommended": 20, "calculated": None},
            },
        },
    },
}


# ---------------------------------------------------------------------------
# validate_template
# ---------------------------------------------------------------------------

class TestValidateTemplate:
    def test_all_sections_present(self):
        sections = {k: {"some_field": "value"} for k in APN_REQUIRED_SECTIONS}
        result = _invoke(validate_handler, {
            "sections": sections,
            "staffing_plan": {"roles": {"pm": {}}},
        })
        assert result["valid"] is True
        assert result["blocking_issues"] == []

    def test_missing_section_is_blocking(self):
        sections = {k: {} for k in APN_REQUIRED_SECTIONS if k != "cover"}
        result = _invoke(validate_handler, {"sections": sections, "staffing_plan": {}})
        assert result["valid"] is False
        codes = [i["code"] for i in result["blocking_issues"]]
        assert "MISSING_SECTION" in codes

    def test_section_order_warning(self):
        # Reverse order
        sections = {k: {"v": 1} for k in reversed(APN_REQUIRED_SECTIONS)}
        result = _invoke(validate_handler, {"sections": sections, "staffing_plan": {}})
        warning_codes = [w["code"] for w in result["warnings"]]
        assert "SECTION_ORDER" in warning_codes

    def test_cost_mismatch_warning(self):
        sections = {k: {} for k in APN_REQUIRED_SECTIONS}
        sections["cost_breakdown"] = {
            "staffing_cost": {"grand_total": {"calculated": 100.0}},
        }
        sp = {"grand_total_cost": {"calculated": 200.0}, "roles": {}}
        result = _invoke(validate_handler, {"sections": sections, "staffing_plan": sp})
        warning_codes = [w["code"] for w in result["warnings"]]
        assert "COST_MISMATCH" in warning_codes

    def test_completion_score_range(self):
        result = _invoke(validate_handler, {"sections": {}, "staffing_plan": {}})
        assert 0.0 <= result["completion_score"] <= 1.0

    def test_error_on_invalid_input(self):
        event = {"inputPayload": "not valid json{{{"}
        resp = validate_handler(event, None)
        output = json.loads(resp["outputPayload"])
        assert "error" in output


# ---------------------------------------------------------------------------
# calc_staffing
# ---------------------------------------------------------------------------

class TestCalcStaffing:
    def test_single_role_calculation(self):
        result = _invoke(calc_handler, {"staffing_plan": SAMPLE_STAFFING_PLAN})
        assert len(result["roles_summary"]) == 1
        role = result["roles_summary"][0]
        assert role["role_id"] == "project_manager"
        # 40 + 80 + 20 = 140 hours
        assert role["total_hours"] == 140
        # 1 * 0.5 * 81.78 * 140 = 5724.60
        assert role["total_cost"] == 5724.6
        assert result["grand_total_hours"] == 140
        assert result["grand_total_cost"] == 5724.6

    def test_empty_staffing_plan(self):
        result = _invoke(calc_handler, {"staffing_plan": {"roles": {}}})
        assert result["roles_summary"] == []
        assert result["grand_total_hours"] == 0
        assert result["grand_total_cost"] == 0

    def test_user_input_takes_priority(self):
        plan = {
            "roles": {
                "dev": {
                    "display_name": "Developer",
                    "count": {"user_input": 2, "ai_recommended": 1, "calculated": None},
                    "allocation_pct": {"user_input": 100, "ai_recommended": 50, "calculated": None},
                    "rate_per_hour": {"user_input": 100, "ai_recommended": 75, "calculated": None},
                    "phase_hours": {
                        "discovery": {"user_input": 10, "ai_recommended": 40, "calculated": None},
                        "development": {"user_input": 20, "ai_recommended": 80, "calculated": None},
                        "testing": {"user_input": 10, "ai_recommended": 20, "calculated": None},
                    },
                },
            },
        }
        result = _invoke(calc_handler, {"staffing_plan": plan})
        role = result["roles_summary"][0]
        # user_input: 10+20+10 = 40 hours, 2 * 1.0 * 100 * 40 = 8000
        assert role["total_hours"] == 40
        assert role["total_cost"] == 8000.0

    def test_error_on_invalid_input(self):
        event = {"inputPayload": "bad json"}
        resp = calc_handler(event, None)
        output = json.loads(resp["outputPayload"])
        assert "error" in output


# ---------------------------------------------------------------------------
# build_milestones
# ---------------------------------------------------------------------------

class TestBuildMilestones:
    def test_phases_generated(self):
        result = _invoke(milestones_handler, {
            "staffing_plan": SAMPLE_STAFFING_PLAN,
            "scope_of_work": {},
        })
        assert len(result["phases"]) == 3
        phase_names = [p["phase"] for p in result["phases"]]
        assert phase_names == ["discovery", "development", "testing"]

    def test_role_assignment(self):
        result = _invoke(milestones_handler, {
            "staffing_plan": SAMPLE_STAFFING_PLAN,
            "scope_of_work": {},
        })
        # PM has hours in all phases
        for phase in result["phases"]:
            assert "Project Manager" in phase["roles"]

    def test_default_deliverables(self):
        result = _invoke(milestones_handler, {
            "staffing_plan": SAMPLE_STAFFING_PLAN,
            "scope_of_work": {},
        })
        discovery = result["phases"][0]
        assert "요구사항 문서" in discovery["deliverables"]

    def test_total_hours(self):
        result = _invoke(milestones_handler, {
            "staffing_plan": SAMPLE_STAFFING_PLAN,
            "scope_of_work": {},
        })
        # 40 + 80 + 20 = 140
        assert result["total_project_hours"] == 140

    def test_empty_roles(self):
        result = _invoke(milestones_handler, {
            "staffing_plan": {"roles": {}},
            "scope_of_work": {},
        })
        assert result["total_project_hours"] == 0


# ---------------------------------------------------------------------------
# estimate_cost
# ---------------------------------------------------------------------------

class TestEstimateCost:
    def test_fallback_when_mcp_unavailable(self):
        """Without MCP endpoint, should produce fallback card."""
        result = _invoke(cost_handler, {
            "services": [
                {"service_name": "AWS Lambda", "service_code": "aWSLambda"},
            ],
        })
        assert result["monthly_cost_summary"] == 0
        assert result["fallback_card"] is not None
        assert len(result["manual_estimate_items"]) == 1

    def test_empty_services(self):
        result = _invoke(cost_handler, {"services": []})
        assert result["monthly_cost_summary"] == 0
        assert result["service_breakdown"] == []

    def test_error_on_invalid_input(self):
        event = {"inputPayload": "{{bad"}
        resp = cost_handler(event, None)
        output = json.loads(resp["outputPayload"])
        assert "error" in output


# ---------------------------------------------------------------------------
# generate_diagram
# ---------------------------------------------------------------------------

class TestGenerateDiagram:
    @patch("agent.lambdas.gateway_tools.generate_diagram.boto3")
    def test_generates_drawio_and_preview(self, mock_boto3):
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        result = _invoke(diagram_handler, {
            "doc_id": "doc-test",
            "services": ["AWS Lambda", "Amazon DynamoDB"],
        })
        assert result["drawio_s3_key"] == "docs/doc-test/diagrams/architecture.drawio"
        assert result["preview_s3_key"] == "docs/doc-test/diagrams/architecture.png"
        assert result["services_extracted"] == ["AWS Lambda", "Amazon DynamoDB"]
        assert mock_s3.put_object.call_count == 2

    @patch("agent.lambdas.gateway_tools.generate_diagram.boto3")
    def test_uses_existing_drawio(self, mock_boto3):
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        custom_xml = "<mxfile>custom</mxfile>"
        result = _invoke(diagram_handler, {
            "doc_id": "doc-test",
            "services": [],
            "existing_drawio": custom_xml,
        })
        # Should upload the custom XML, not generate new
        call_args = mock_s3.put_object.call_args_list[0]
        assert custom_xml.encode("utf-8") == call_args[1]["Body"]


# ---------------------------------------------------------------------------
# export_docx
# ---------------------------------------------------------------------------

class TestExportDocx:
    @patch("agent.lambdas.gateway_tools.export_docx._render_docx")
    @patch("agent.lambdas.gateway_tools.export_docx.boto3")
    def test_generates_and_uploads(self, mock_boto3, mock_render_docx):
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {"Body": io.BytesIO(b"template-bytes")}
        mock_s3.generate_presigned_url.return_value = "https://presigned.url"
        mock_boto3.client.return_value = mock_s3
        mock_render_docx.return_value = b"rendered-docx"

        result = _invoke(docx_handler, {
            "doc_id": "doc-001",
            "version": 5,
            "meta": {"customer": {"user_input": "TestCorp"}},
            "sections": {},
            "staffing_plan": {"roles": {}},
        })
        assert result["s3_key"] == "docs/doc-001/exports/doc-001-v5.docx"
        assert result["bucket"] == "doc-agent-artifacts"
        assert result["download_url"] == "https://presigned.url"
        mock_render_docx.assert_called_once()
        mock_s3.put_object.assert_called_once()

    def test_error_on_invalid_input(self):
        event = {"inputPayload": "not json"}
        resp = docx_handler(event, None)
        output = json.loads(resp["outputPayload"])
        assert "error" in output


# ---------------------------------------------------------------------------
# generate_diagram — error handling
# ---------------------------------------------------------------------------

class TestGenerateDiagramErrors:
    def test_error_on_invalid_input(self):
        event = {"inputPayload": "{{bad json"}
        resp = diagram_handler(event, None)
        output = json.loads(resp["outputPayload"])
        assert "error" in output


# ---------------------------------------------------------------------------
# build_milestones — error handling
# ---------------------------------------------------------------------------

class TestBuildMilestonesErrors:
    def test_error_on_invalid_input(self):
        event = {"inputPayload": "not json!!"}
        resp = milestones_handler(event, None)
        output = json.loads(resp["outputPayload"])
        assert "error" in output
