"""AgentCore Gateway client — common MCP tool invocation layer.

Replaces v1's ``agent/app/cost/gateway_client.py`` stub with a shared
Gateway client that Cost, Architecture, Formatter, and Parent agents
all use to invoke MCP tools registered on AgentCore Gateway.

Registered tools (6):
  validate_template_constraints, generate_architecture_diagram,
  estimate_cost, calculate_staffing_cost, export_docx,
  build_milestone_summary

Failure handling (Requirements 3.4, 3.5, 3.6):
  - ``call_tool`` raises ``GatewayToolError`` on failure.
  - ``call_tool_safe`` returns ``(None, error_message)`` on failure.
  - Both methods guarantee no partial Document_State mutation — the
    caller receives either a complete result or an error, never a
    half-applied change.
  - The optional ``on_error`` callback lets the orchestrator publish
    an error status to ``docs/{docId}/status``.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Optional

import boto3

logger = logging.getLogger(__name__)


class GatewayToolError(Exception):
    """Raised when an AgentCore Gateway tool invocation fails.

    Attributes:
        tool_name: The MCP tool that was called.
        cause: The underlying exception or error message.
    """

    def __init__(self, tool_name: str, cause: str | Exception) -> None:
        self.tool_name = tool_name
        self.cause = cause
        super().__init__(f"Gateway tool '{tool_name}' failed: {cause}")


class AgentCoreGatewayClient:
    """Shared client for invoking MCP tools via AgentCore Gateway.

    Args:
        gateway_id: The AgentCore Gateway identifier.
        region: AWS region for the ``bedrock-agentcore`` client.
        on_error: Optional callback invoked when a tool call fails.
            Signature: ``(tool_name: str, error: Exception) -> None``.
            The orchestrator uses this to publish an error status to
            ``docs/{docId}/status`` and present alternatives to the user.
    """

    def __init__(
        self,
        gateway_id: str,
        region: str = "ap-northeast-2",
        on_error: Optional[Callable[[str, Exception], None]] = None,
    ) -> None:
        self.client = boto3.client("bedrock-agentcore", region_name=region)
        self.gateway_id = gateway_id
        self.on_error = on_error

    # ------------------------------------------------------------------
    # Internal — raw Gateway invocation
    # ------------------------------------------------------------------

    def _invoke_tool(self, tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        """Low-level Gateway tool invocation.

        Calls the ``invoke_gateway_tool`` API on the ``bedrock-agentcore``
        client and returns the parsed JSON response payload.

        Raises ``GatewayToolError`` on any failure.
        """
        try:
            response = self.client.invoke_gateway_tool(
                gatewayId=self.gateway_id,
                toolName=tool_name,
                inputPayload=json.dumps(params),
            )
        except Exception as exc:
            raise GatewayToolError(tool_name, exc) from exc

        # Parse the response payload
        try:
            raw_payload = response.get("outputPayload", "{}")
            if isinstance(raw_payload, (bytes, bytearray)):
                raw_payload = raw_payload.decode("utf-8")
            result: dict[str, Any] = json.loads(raw_payload)
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as exc:
            raise GatewayToolError(
                tool_name, f"Invalid response payload: {exc}"
            ) from exc

        # Check for tool-level error in the response
        if "error" in result:
            raise GatewayToolError(tool_name, result["error"])

        return result

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def call_tool(
        self, tool_name: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Invoke an MCP tool via AgentCore Gateway.

        Returns the parsed response dict on success.
        Raises ``GatewayToolError`` on failure — the caller's
        Document_State is never partially mutated.
        """
        try:
            return self._invoke_tool(tool_name, params)
        except GatewayToolError:
            raise
        except Exception as exc:
            raise GatewayToolError(tool_name, exc) from exc

    async def call_tool_safe(
        self, tool_name: str, params: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Invoke an MCP tool, returning ``(result, None)`` on success
        or ``(None, error_message)`` on failure.

        This variant never raises — it catches all errors, logs them,
        invokes the ``on_error`` callback (if set), and returns a
        descriptive error string so the caller can generate a fallback
        (e.g. ``FallbackCard`` for cost estimation).

        Document_State is preserved on failure: no partial mutations.
        """
        try:
            result = self._invoke_tool(tool_name, params)
            return result, None
        except GatewayToolError as exc:
            error_msg = str(exc)
            logger.warning("Gateway tool call failed (safe): %s", error_msg)
            self._notify_error(tool_name, exc)
            return None, error_msg
        except Exception as exc:
            error_msg = f"Gateway tool '{tool_name}' unexpected error: {exc}"
            logger.warning("Gateway tool call failed (safe): %s", error_msg)
            wrapped = GatewayToolError(tool_name, exc)
            self._notify_error(tool_name, wrapped)
            return None, error_msg

    # ------------------------------------------------------------------
    # Error notification
    # ------------------------------------------------------------------

    def _notify_error(self, tool_name: str, error: Exception) -> None:
        """Invoke the ``on_error`` callback if registered."""
        if self.on_error is not None:
            try:
                self.on_error(tool_name, error)
            except Exception:
                logger.exception("on_error callback itself failed")
