"""Tests for AgentCoreGatewayClient — mocked boto3 bedrock-agentcore client.

Covers:
- Initialization and client creation
- call_tool: success, API error, invalid response payload, tool-level error
- call_tool_safe: success, failure returns (None, error_message)
- on_error callback invoked on failure
- Document_State preservation on failure (no partial mutations)

Requirements: 3.1, 3.3, 3.4, 3.5, 3.6
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio

from agent.lib.gateway.agentcore_gateway import (
    AgentCoreGatewayClient,
    GatewayToolError,
)

GATEWAY_ID = "gw-test-001"
REGION = "ap-northeast-2"


@pytest.fixture()
def mock_client():
    with patch("agent.lib.gateway.agentcore_gateway.boto3") as mock_boto3:
        client = MagicMock()
        mock_boto3.client.return_value = client
        yield client


@pytest.fixture()
def gateway(mock_client):
    return AgentCoreGatewayClient(gateway_id=GATEWAY_ID, region=REGION)


# --- Initialization ---


def test_init_creates_bedrock_agentcore_client():
    with patch("agent.lib.gateway.agentcore_gateway.boto3") as mock_boto3:
        gw = AgentCoreGatewayClient(gateway_id=GATEWAY_ID, region=REGION)
        mock_boto3.client.assert_called_once_with(
            "bedrock-agentcore", region_name=REGION
        )
        assert gw.gateway_id == GATEWAY_ID


def test_init_default_region():
    with patch("agent.lib.gateway.agentcore_gateway.boto3") as mock_boto3:
        AgentCoreGatewayClient(gateway_id=GATEWAY_ID)
        mock_boto3.client.assert_called_once_with(
            "bedrock-agentcore", region_name="ap-northeast-2"
        )


def test_init_on_error_default_is_none():
    with patch("agent.lib.gateway.agentcore_gateway.boto3"):
        gw = AgentCoreGatewayClient(gateway_id=GATEWAY_ID)
        assert gw.on_error is None


# --- call_tool (success) ---


@pytest.mark.asyncio
async def test_call_tool_success(gateway, mock_client):
    mock_client.invoke_gateway_tool.return_value = {
        "outputPayload": json.dumps({
            "monthly_total": 1113.68,
            "breakdown": [{"service": "Lambda", "cost": 244.13}],
        })
    }

    result = await gateway.call_tool("estimate_cost", {"services": ["Lambda"]})

    mock_client.invoke_gateway_tool.assert_called_once_with(
        gatewayId=GATEWAY_ID,
        toolName="estimate_cost",
        inputPayload=json.dumps({"services": ["Lambda"]}),
    )
    assert result["monthly_total"] == 1113.68
    assert len(result["breakdown"]) == 1


@pytest.mark.asyncio
async def test_call_tool_bytes_payload(gateway, mock_client):
    """Response payload can be bytes."""
    payload = json.dumps({"result": "ok"}).encode("utf-8")
    mock_client.invoke_gateway_tool.return_value = {"outputPayload": payload}

    result = await gateway.call_tool("validate_template_constraints", {})
    assert result["result"] == "ok"


# --- call_tool (failure) ---


@pytest.mark.asyncio
async def test_call_tool_raises_on_api_error(gateway, mock_client):
    mock_client.invoke_gateway_tool.side_effect = RuntimeError("Service unavailable")

    with pytest.raises(GatewayToolError) as exc_info:
        await gateway.call_tool("estimate_cost", {})

    assert "estimate_cost" in str(exc_info.value)
    assert "Service unavailable" in str(exc_info.value)


@pytest.mark.asyncio
async def test_call_tool_raises_on_invalid_json_response(gateway, mock_client):
    mock_client.invoke_gateway_tool.return_value = {
        "outputPayload": "not-valid-json{{"
    }

    with pytest.raises(GatewayToolError) as exc_info:
        await gateway.call_tool("export_docx", {})

    assert "Invalid response payload" in str(exc_info.value)


@pytest.mark.asyncio
async def test_call_tool_raises_on_tool_level_error(gateway, mock_client):
    mock_client.invoke_gateway_tool.return_value = {
        "outputPayload": json.dumps({"error": "Calculator MCP timeout"})
    }

    with pytest.raises(GatewayToolError) as exc_info:
        await gateway.call_tool("estimate_cost", {"services": ["Bedrock"]})

    assert "Calculator MCP timeout" in str(exc_info.value)


# --- call_tool_safe (success) ---


@pytest.mark.asyncio
async def test_call_tool_safe_success(gateway, mock_client):
    mock_client.invoke_gateway_tool.return_value = {
        "outputPayload": json.dumps({"score": 0.85})
    }

    result, error = await gateway.call_tool_safe(
        "validate_template_constraints", {"doc_state": {}}
    )

    assert result == {"score": 0.85}
    assert error is None


# --- call_tool_safe (failure — returns tuple, no raise) ---


@pytest.mark.asyncio
async def test_call_tool_safe_returns_none_on_api_error(gateway, mock_client):
    mock_client.invoke_gateway_tool.side_effect = RuntimeError("Network error")

    result, error = await gateway.call_tool_safe("estimate_cost", {})

    assert result is None
    assert "estimate_cost" in error
    assert "Network error" in error


@pytest.mark.asyncio
async def test_call_tool_safe_returns_none_on_tool_error(gateway, mock_client):
    mock_client.invoke_gateway_tool.return_value = {
        "outputPayload": json.dumps({"error": "Unsupported service"})
    }

    result, error = await gateway.call_tool_safe("estimate_cost", {})

    assert result is None
    assert "Unsupported service" in error


# --- on_error callback ---


@pytest.mark.asyncio
async def test_on_error_callback_invoked_on_safe_failure(mock_client):
    callback = MagicMock()
    with patch("agent.lib.gateway.agentcore_gateway.boto3") as mock_boto3:
        mock_boto3.client.return_value = mock_client
        gw = AgentCoreGatewayClient(
            gateway_id=GATEWAY_ID, region=REGION, on_error=callback
        )

    mock_client.invoke_gateway_tool.side_effect = RuntimeError("fail")

    await gw.call_tool_safe("estimate_cost", {})

    callback.assert_called_once()
    args = callback.call_args[0]
    assert args[0] == "estimate_cost"
    assert isinstance(args[1], GatewayToolError)


@pytest.mark.asyncio
async def test_on_error_not_invoked_on_call_tool_raise(mock_client):
    """call_tool raises directly — on_error is NOT invoked (only call_tool_safe uses it)."""
    callback = MagicMock()
    with patch("agent.lib.gateway.agentcore_gateway.boto3") as mock_boto3:
        mock_boto3.client.return_value = mock_client
        gw = AgentCoreGatewayClient(
            gateway_id=GATEWAY_ID, region=REGION, on_error=callback
        )

    mock_client.invoke_gateway_tool.side_effect = RuntimeError("fail")

    with pytest.raises(GatewayToolError):
        await gw.call_tool("estimate_cost", {})

    callback.assert_not_called()


@pytest.mark.asyncio
async def test_broken_on_error_callback_does_not_crash(mock_client):
    """Even if the on_error callback raises, call_tool_safe should not crash."""
    def bad_callback(tool_name, exc):
        raise ValueError("callback broken")

    with patch("agent.lib.gateway.agentcore_gateway.boto3") as mock_boto3:
        mock_boto3.client.return_value = mock_client
        gw = AgentCoreGatewayClient(
            gateway_id=GATEWAY_ID, region=REGION, on_error=bad_callback
        )

    mock_client.invoke_gateway_tool.side_effect = RuntimeError("API fail")

    result, error = await gw.call_tool_safe("estimate_cost", {})
    assert result is None
    assert error is not None


# --- Document_State preservation on failure (Req 3.6) ---


@pytest.mark.asyncio
async def test_document_state_preserved_on_call_tool_failure(gateway, mock_client):
    """Req 3.6: Document_State must not be partially mutated on failure.

    Simulates a caller holding a doc_state dict — after call_tool raises,
    the dict must remain unchanged.
    """
    doc_state = {
        "version": 10,
        "sections": {"cover": {"title": "Original"}},
        "staffing_plan": {"roles": {}},
    }
    doc_state_snapshot = json.dumps(doc_state, sort_keys=True)

    mock_client.invoke_gateway_tool.side_effect = RuntimeError("boom")

    with pytest.raises(GatewayToolError):
        await gateway.call_tool("estimate_cost", {"doc_state": doc_state})

    # doc_state must be identical — no partial mutation
    assert json.dumps(doc_state, sort_keys=True) == doc_state_snapshot


@pytest.mark.asyncio
async def test_document_state_preserved_on_call_tool_safe_failure(gateway, mock_client):
    """Req 3.6: call_tool_safe also preserves Document_State on failure."""
    doc_state = {
        "version": 5,
        "sections": {"architecture": {"services": ["Lambda"]}},
    }
    doc_state_snapshot = json.dumps(doc_state, sort_keys=True)

    mock_client.invoke_gateway_tool.side_effect = RuntimeError("timeout")

    result, error = await gateway.call_tool_safe("generate_architecture_diagram", {"doc_state": doc_state})

    assert result is None
    assert error is not None
    assert json.dumps(doc_state, sort_keys=True) == doc_state_snapshot


# --- call_tool_safe edge cases ---


@pytest.mark.asyncio
async def test_call_tool_safe_empty_output_payload(gateway, mock_client):
    """Empty outputPayload should parse as empty dict."""
    mock_client.invoke_gateway_tool.return_value = {"outputPayload": "{}"}

    result, error = await gateway.call_tool_safe("validate_template_constraints", {})

    assert result == {}
    assert error is None


@pytest.mark.asyncio
async def test_call_tool_safe_missing_output_payload(gateway, mock_client):
    """Missing outputPayload key defaults to empty dict."""
    mock_client.invoke_gateway_tool.return_value = {}

    result, error = await gateway.call_tool_safe("validate_template_constraints", {})

    assert result == {}
    assert error is None


# --- on_error callback as error status publisher (Req 3.4) ---


@pytest.mark.asyncio
async def test_on_error_receives_tool_name_for_status_publish(mock_client):
    """Req 3.4: on_error callback receives tool_name so orchestrator can
    publish error status to docs/{docId}/status channel."""
    published_errors = []

    def status_publisher(tool_name: str, exc: Exception):
        published_errors.append({"tool": tool_name, "error": str(exc)})

    with patch("agent.lib.gateway.agentcore_gateway.boto3") as mock_boto3:
        mock_boto3.client.return_value = mock_client
        gw = AgentCoreGatewayClient(
            gateway_id=GATEWAY_ID, region=REGION, on_error=status_publisher
        )

    mock_client.invoke_gateway_tool.return_value = {
        "outputPayload": json.dumps({"error": "Service quota exceeded"})
    }

    result, error = await gw.call_tool_safe("calculate_staffing_cost", {})

    assert result is None
    assert len(published_errors) == 1
    assert published_errors[0]["tool"] == "calculate_staffing_cost"
    assert "Service quota exceeded" in published_errors[0]["error"]


# --- GatewayToolError ---


def test_gateway_tool_error_attributes():
    err = GatewayToolError("estimate_cost", "timeout")
    assert err.tool_name == "estimate_cost"
    assert err.cause == "timeout"
    assert "estimate_cost" in str(err)
    assert "timeout" in str(err)


def test_gateway_tool_error_with_exception_cause():
    """GatewayToolError can wrap an Exception as cause."""
    original = RuntimeError("connection refused")
    err = GatewayToolError("export_docx", original)
    assert err.tool_name == "export_docx"
    assert err.cause is original
    assert "export_docx" in str(err)
