"""Gateway Lambda: estimate_cost

Wraps the Calculator MCP (aws-calculator-mcp) to estimate AWS service
costs.  Produces a per-service breakdown, a shareable calculator URL,
and falls back to manual_estimate_items when a service is unsupported.

Input (via event["inputPayload"] JSON):
    {
        "doc_id": "doc-001",
        "services": [
            {
                "service_name": "AWS Lambda",
                "service_code": "aWSLambda",
                "config": { "requests_per_month": 1000000, ... }
            },
            ...
        ],
        "region": "ap-northeast-2"
    }

Output:
    {
        "monthly_cost_summary": 1113.68,
        "service_breakdown": [
            {
                "service_name": "AWS Lambda",
                "service_code": "aWSLambda",
                "monthly_cost": 244.13,
                "supported_by_calculator": true
            },
            ...
        ],
        "calculator_share_url": "https://calculator.aws/#/estimate?id=...",
        "manual_estimate_items": [...],
        "fallback_card": null
    }
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# In production this would call the Calculator MCP server.
# The MCP endpoint is configured via environment variable.
CALCULATOR_MCP_ENDPOINT = os.environ.get("CALCULATOR_MCP_ENDPOINT", "")


def _call_calculator_mcp(services: list[dict], region: str) -> dict[str, Any]:
    """Call the Calculator MCP to get cost estimates.

    In production this invokes the aws-calculator-mcp server.
    Returns per-service costs and a shareable URL.

    Raises RuntimeError if the MCP call fails.
    """
    # Placeholder: a real implementation would use an MCP client
    # to communicate with the aws-calculator-mcp server.
    raise RuntimeError(
        "Calculator MCP endpoint not configured — "
        "set CALCULATOR_MCP_ENDPOINT environment variable"
    )


def _build_fallback_card(
    services: list[dict],
    partial_results: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Build a fallback cost summary card when Calculator MCP fails."""
    items = []
    for svc in services:
        name = svc.get("service_name", "Unknown")
        code = svc.get("service_code", "")
        estimated = (partial_results or {}).get(code)
        items.append({
            "service_name": name,
            "service_code": code,
            "monthly_cost": estimated,
            "note": "Estimate unavailable — manual review required" if estimated is None else None,
        })
    return {
        "type": "fallback",
        "message": "Calculator MCP unavailable or partially failed",
        "items": items,
    }


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point for estimate_cost."""
    try:
        raw = event.get("inputPayload", "{}")
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        params = json.loads(raw)

        services = params.get("services", [])
        region = params.get("region", "ap-northeast-2")

        breakdown: list[dict] = []
        manual_items: list[dict] = []
        total = 0.0
        share_url: str | None = None
        fallback_card: dict | None = None

        try:
            mcp_result = _call_calculator_mcp(services, region)
            breakdown = mcp_result.get("breakdown", [])
            share_url = mcp_result.get("share_url")
            total = sum(item.get("monthly_cost", 0) for item in breakdown)
        except Exception as mcp_err:
            logger.warning("Calculator MCP failed: %s", mcp_err)
            # Build fallback for all services
            for svc in services:
                manual_items.append({
                    "service_name": svc.get("service_name", "Unknown"),
                    "service_code": svc.get("service_code", ""),
                    "monthly_cost": None,
                    "supported_by_calculator": False,
                })
            fallback_card = _build_fallback_card(services)

        result = {
            "monthly_cost_summary": round(total, 2),
            "service_breakdown": breakdown,
            "calculator_share_url": share_url,
            "manual_estimate_items": manual_items,
            "fallback_card": fallback_card,
        }
        return {"outputPayload": json.dumps(result)}

    except Exception as e:
        return {"outputPayload": json.dumps({"error": str(e)})}
