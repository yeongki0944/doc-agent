"""Unit tests for the new Architecture / Calculator / Service-explanation MCP contracts.

Covered handlers:
  - generate_diagram.handler          (with engineer-friendly fallback)
  - create_calculator_link.handler    (with Calculator Link Node Lambda or fallback)
  - explain_aws_services.handler      (with static catalogue + Bedrock fallback)
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from agent.lambdas.gateway_tools.generate_diagram import handler as diagram_handler
from agent.lambdas.gateway_tools.create_calculator_link import handler as calculator_handler
from agent.lambdas.gateway_tools.explain_aws_services import handler as explain_handler


def _invoke(handler_fn, params: dict) -> dict:
    event = {"inputPayload": json.dumps(params)}
    result = handler_fn(event, None)
    assert "outputPayload" in result
    return json.loads(result["outputPayload"])


# ---------------------------------------------------------------------------
# generate_architecture_diagram
# ---------------------------------------------------------------------------

class TestGenerateDiagram:
    @patch("agent.lambdas.gateway_tools.generate_diagram.boto3")
    def test_happy_path_uploads_drawio_and_preview(self, mock_boto3):
        s3 = MagicMock()
        mock_boto3.client.return_value = s3

        result = _invoke(diagram_handler, {
            "doc_id": "doc-1",
            "services": ["Amazon Bedrock", "AWS Lambda", "Amazon S3"],
            "architecture_description": "Bedrock-based RAG pipeline",
            "use_case": "RAG chatbot",
        })

        assert result["mode"] == "drawio"
        assert result["drawio_s3_key"].endswith(".drawio")
        assert result["preview_s3_key"].endswith(".png")
        assert s3.put_object.call_count == 2
        # Engineer draft is still provided for alignment checks.
        assert "engineer_draft" in result
        assert len(result["engineer_draft"]["layers"]) >= 1

    def test_no_services_returns_engineer_draft_only(self):
        result = _invoke(diagram_handler, {
            "doc_id": "doc-1",
            "services": [],
            "use_case": "RAG chatbot",
        })
        assert result["mode"] == "engineer_draft"
        assert result["drawio_s3_key"] == ""
        assert result["preview_s3_key"] == ""
        assert "engineer_draft" in result
        assert "no services provided" in result["engineer_draft"]["warning"].lower()

    def test_skip_drawio_returns_engineer_draft_only(self):
        result = _invoke(diagram_handler, {
            "doc_id": "doc-1",
            "services": ["Amazon Bedrock"],
            "skip_drawio": True,
        })
        assert result["mode"] == "engineer_draft"
        assert result["drawio_s3_key"] == ""
        assert result["engineer_draft"]["layers"][0]["services"] == ["Amazon Bedrock"]

    @patch("agent.lambdas.gateway_tools.generate_diagram.boto3")
    def test_s3_failure_falls_back_to_engineer_draft(self, mock_boto3):
        s3 = MagicMock()
        s3.put_object.side_effect = RuntimeError("access denied")
        mock_boto3.client.return_value = s3

        result = _invoke(diagram_handler, {
            "doc_id": "doc-1",
            "services": ["AWS Lambda"],
        })
        assert result["mode"] == "engineer_draft"
        assert result["drawio_s3_key"] == ""
        assert "engineer_draft" in result
        assert "failed" in result["engineer_draft"]["warning"].lower()


# ---------------------------------------------------------------------------
# create_calculator_link
# ---------------------------------------------------------------------------

class TestCreateCalculatorLink:
    def test_fallback_when_no_backend_configured(self, monkeypatch):
        monkeypatch.delenv("CALCULATOR_LINK_LAMBDA_NAME", raising=False)
        monkeypatch.delenv("CALCULATOR_MCP_ENDPOINT", raising=False)
        # Force the module-level caches to re-read env
        monkeypatch.setattr(
            "agent.lambdas.gateway_tools.create_calculator_link.CALCULATOR_LINK_LAMBDA_NAME",
            "",
        )
        monkeypatch.setattr(
            "agent.lambdas.gateway_tools.create_calculator_link.CALCULATOR_MCP_ENDPOINT",
            "",
        )

        result = _invoke(calculator_handler, {
            "doc_id": "doc-1",
            "services": [
                {"service_name": "AWS Lambda", "service_code": "aWSLambda",
                 "monthly_cost_hint": 244.13},
                {"service_name": "Amazon S3", "service_code": "amazonS3",
                 "monthly_cost_hint": 12.50},
            ],
            "region": "ap-northeast-2",
        })

        assert result["mode"] == "fallback"
        assert result["calculator_share_url"] is None
        assert result["document_local_summary"]["monthly_cost_total"] == 256.63
        assert result["document_local_summary"]["currency"] == "USD"
        assert result["fallback_card"]["type"] == "fallback"
        assert any("not configured" in w.lower() or "no calculator" in w.lower()
                   for w in result["warnings"])

    @patch("agent.lambdas.gateway_tools.create_calculator_link.boto3")
    def test_node_lambda_invocation_success(self, mock_boto3, monkeypatch):
        monkeypatch.setattr(
            "agent.lambdas.gateway_tools.create_calculator_link.CALCULATOR_LINK_LAMBDA_NAME",
            "user-calculator-link-lambda",
        )

        fake_client = MagicMock()
        payload = MagicMock()
        payload.read.return_value = json.dumps({
            "calculator_share_url": "https://calculator.aws/#/estimate?id=abc123",
            "service_breakdown": [
                {"service_name": "AWS Lambda", "service_code": "aWSLambda",
                 "monthly_cost": 244.13, "supported_by_calculator": True},
            ],
            "manual_estimate_items": [],
            "warnings": [],
        }).encode()
        fake_client.invoke.return_value = {"Payload": payload}
        mock_boto3.client.return_value = fake_client

        result = _invoke(calculator_handler, {
            "doc_id": "doc-1",
            "services": [
                {"service_name": "AWS Lambda", "service_code": "aWSLambda"},
            ],
            "region": "ap-northeast-2",
        })

        assert result["mode"] == "node_lambda"
        assert result["calculator_share_url"] == "https://calculator.aws/#/estimate?id=abc123"
        assert result["document_local_summary"]["monthly_cost_total"] == 244.13
        # Fallback card should be None when the Node Lambda succeeded.
        assert result["fallback_card"] is None

    @patch("agent.lambdas.gateway_tools.create_calculator_link.boto3")
    def test_node_lambda_failure_returns_fallback(self, mock_boto3, monkeypatch):
        monkeypatch.setattr(
            "agent.lambdas.gateway_tools.create_calculator_link.CALCULATOR_LINK_LAMBDA_NAME",
            "user-calculator-link-lambda",
        )
        fake_client = MagicMock()
        fake_client.invoke.side_effect = RuntimeError("access denied")
        mock_boto3.client.return_value = fake_client

        result = _invoke(calculator_handler, {
            "doc_id": "doc-1",
            "services": [
                {"service_name": "AWS Lambda", "service_code": "aWSLambda",
                 "monthly_cost_hint": 244.13},
            ],
            "region": "ap-northeast-2",
        })
        assert result["mode"] == "fallback"
        assert result["fallback_card"] is not None
        # Local summary still populated from monthly_cost_hint
        assert result["document_local_summary"]["monthly_cost_total"] == 244.13
        assert any("Calculator Link Lambda failed" in w for w in result["warnings"])

    def test_empty_services_returns_safe_fallback(self):
        result = _invoke(calculator_handler, {"services": []})
        assert result["mode"] == "fallback"
        assert result["calculator_share_url"] is None
        assert result["document_local_summary"]["monthly_cost_total"] == 0
        assert result["fallback_card"]["items"] == []


# ---------------------------------------------------------------------------
# explain_aws_services
# ---------------------------------------------------------------------------

class TestExplainAwsServices:
    def test_static_catalog_hits(self, monkeypatch):
        monkeypatch.setattr(
            "agent.lambdas.gateway_tools.explain_aws_services.AWS_DOCS_MCP_ENDPOINT",
            "",
        )
        monkeypatch.setattr(
            "agent.lambdas.gateway_tools.explain_aws_services.BEDROCK_EXPLAIN_FALLBACK",
            "off",
        )

        result = _invoke(explain_handler, {
            "services": ["Amazon Bedrock", "AWS Lambda", "Amazon S3"],
            "use_case": "RAG chatbot",
        })

        assert result["mode"] == "static"
        ids = [e["service_id"] for e in result["explanations"]]
        assert "amazon_bedrock" in ids
        assert "aws_lambda" in ids
        assert "amazon_s3" in ids
        for e in result["explanations"]:
            assert e["summary"]
            assert e["reference_urls"]
            assert e["source"] == "static"

    def test_unknown_service_without_llm_returns_placeholder(self, monkeypatch):
        monkeypatch.setattr(
            "agent.lambdas.gateway_tools.explain_aws_services.AWS_DOCS_MCP_ENDPOINT",
            "",
        )
        monkeypatch.setattr(
            "agent.lambdas.gateway_tools.explain_aws_services.BEDROCK_EXPLAIN_FALLBACK",
            "off",
        )
        result = _invoke(explain_handler, {
            "services": ["Amazon Bogus Service"],
        })
        assert result["mode"] == "static"
        assert len(result["explanations"]) == 1
        ex = result["explanations"][0]
        assert ex["source"] == "unknown"
        assert ex["summary"] == ""
        assert any("No explanation" in w for w in result["warnings"])

    def test_mcp_endpoint_warns_but_still_returns(self, monkeypatch):
        monkeypatch.setattr(
            "agent.lambdas.gateway_tools.explain_aws_services.AWS_DOCS_MCP_ENDPOINT",
            "https://docs-mcp.example.com",
        )
        monkeypatch.setattr(
            "agent.lambdas.gateway_tools.explain_aws_services.BEDROCK_EXPLAIN_FALLBACK",
            "off",
        )
        result = _invoke(explain_handler, {"services": ["Amazon Bedrock"]})
        assert result["mode"] == "static"
        # Warning that MCP is set but client not wired
        assert any("mcp" in w.lower() for w in result["warnings"])

    def test_empty_services_returns_empty(self):
        result = _invoke(explain_handler, {"services": []})
        assert result["mode"] == "static"
        assert result["explanations"] == []
