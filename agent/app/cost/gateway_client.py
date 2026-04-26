"""AgentCore Gateway client — MCP tool invocation.

In production: calls AgentCore Gateway HTTP/MCP endpoint.
Currently: stub implementation for development.
"""

from __future__ import annotations

from typing import Any


class StubGatewayClient:
    """Stub Gateway client for development."""

    async def call_tool(self, tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        """Stub: returns placeholder responses based on tool name."""
        if tool_name == "estimate_cost":
            return {
                "monthly_total": 0,
                "breakdown": [],
                "share_url": None,
                "manual_items": params.get("services", []),
            }
        elif tool_name == "calculate_staffing_cost":
            return {"result": "stub"}
        else:
            return {"error": f"Unknown tool: {tool_name}"}
