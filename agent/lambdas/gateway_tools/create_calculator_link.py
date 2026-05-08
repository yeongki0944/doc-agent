"""Gateway Lambda: create_calculator_link

Produces a shareable AWS Calculator link for a list of AWS services and
configurations. Designed to plug into a separately-implemented Node.js
Calculator Link Lambda (configured via ``CALCULATOR_LINK_LAMBDA_NAME``)
while preserving deterministic document-local summary and fallback card
behaviour required by the Reviewer.

Contract:

Input (event["inputPayload"] JSON):
    {
        "doc_id": "doc-001",
        "services": [
            {
                "service_name": "AWS Lambda",
                "service_code": "aWSLambda",    # calculator.aws code
                "config": {"requests_per_month": 1000000}
            },
            ...
        ],
        "region": "ap-northeast-2",
        "existing_link": "https://calculator.aws/#/estimate?id=..."   # optional
    }

Output:
    {
        "mode": "node_lambda" | "mcp" | "fallback",
        "calculator_share_url": "https://calculator.aws/#/estimate?id=..." | null,
        "service_breakdown": [
            {
                "service_name": "AWS Lambda",
                "service_code": "aWSLambda",
                "monthly_cost": 244.13 | null,
                "supported_by_calculator": true | false,
                "note": "..."
            }, ...
        ],
        "manual_estimate_items": [...],
        "document_local_summary": {
            "monthly_cost_total": 1113.68,
            "currency": "USD",
            "region": "ap-northeast-2",
            "generated_at": "ISO8601"
        },
        "fallback_card": {
            "type": "fallback",
            "message": "...",
            "items": [...]
        } | null,
        "warnings": ["..."]
    }

Fallback behaviour:
  - If ``CALCULATOR_LINK_LAMBDA_NAME`` is not configured, return a fallback
    card plus manual_estimate_items so the document remains readable.
  - If the configured Node.js Lambda errors or returns a malformed payload,
    return the fallback card with a warning but keep the deterministic
    document-local summary populated from any numeric ``config.monthly_cost``
    hints supplied by the caller.
  - document_local_summary is ALWAYS populated with best-effort values —
    this is the APN-required "preserve local cost summary" guarantee.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import boto3

REGION = os.environ.get("AWS_REGION", "ap-northeast-2")
CALCULATOR_LINK_LAMBDA_NAME = os.environ.get("CALCULATOR_LINK_LAMBDA_NAME", "")
CALCULATOR_MCP_ENDPOINT = os.environ.get("CALCULATOR_MCP_ENDPOINT", "")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_services(raw: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for svc in raw:
        if not isinstance(svc, dict):
            if isinstance(svc, str) and svc.strip():
                out.append({"service_name": svc.strip(), "service_code": "", "config": {}})
            continue
        name = svc.get("service_name") or svc.get("name") or svc.get("service_id") or ""
        if not name:
            continue
        item: dict[str, Any] = {
            "service_name": str(name),
            "service_code": str(svc.get("service_code") or svc.get("code") or ""),
            "config": svc.get("config") if isinstance(svc.get("config"), dict) else {},
        }
        # Optional monthly_cost hint from caller (used to populate local summary)
        hint = svc.get("monthly_cost_hint")
        if hint is None:
            hint = (svc.get("config") or {}).get("monthly_cost")
        try:
            item["monthly_cost_hint"] = float(hint) if hint is not None else None
        except (TypeError, ValueError):
            item["monthly_cost_hint"] = None
        out.append(item)
    return out


def _build_fallback_card(
    services: list[dict[str, Any]],
    partial_results: dict[str, float] | None = None,
    reason: str = "",
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for svc in services:
        name = svc.get("service_name", "Unknown")
        code = svc.get("service_code", "")
        estimated = (partial_results or {}).get(code)
        if estimated is None:
            estimated = svc.get("monthly_cost_hint")
        items.append({
            "service_name": name,
            "service_code": code,
            "monthly_cost": estimated,
            "note": "Estimate unavailable — manual review required" if estimated is None else None,
        })
    return {
        "type": "fallback",
        "message": reason or "Calculator link unavailable",
        "items": items,
    }


def _document_local_summary(
    services: list[dict[str, Any]],
    region: str,
    breakdown: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Preserve a document-local cost summary regardless of external calls.

    Uses breakdown monthly_cost when available, otherwise ``monthly_cost_hint``
    supplied by the caller. Missing values are treated as 0 for the summary
    but the per-service entry still records ``null`` in the breakdown.
    """
    total = 0.0
    rows: list[dict[str, Any]] = []
    lookup = {}
    for row in breakdown or []:
        code = str(row.get("service_code") or "")
        name = str(row.get("service_name") or "")
        key = code or name
        if key:
            lookup[key] = row.get("monthly_cost")

    for svc in services:
        name = svc.get("service_name", "Unknown")
        code = svc.get("service_code", "")
        key = code or name
        monthly = lookup.get(key)
        if monthly is None:
            monthly = svc.get("monthly_cost_hint")
        try:
            monthly_num = float(monthly) if monthly is not None else None
        except (TypeError, ValueError):
            monthly_num = None
        if monthly_num is not None:
            total += monthly_num
        rows.append({
            "service_name": name,
            "service_code": code,
            "monthly_cost": monthly_num,
        })

    return {
        "monthly_cost_total": round(total, 2),
        "currency": "USD",
        "region": region or REGION,
        "generated_at": _now_iso(),
        "rows": rows,
    }


def _invoke_node_lambda(
    function_name: str,
    services: list[dict[str, Any]],
    region: str,
    existing_link: str,
) -> dict[str, Any]:
    """Invoke the separately-deployed Node.js Calculator Link Lambda.

    The Node Lambda contract is documented so it can be implemented
    independently:

    Request payload:
        {
            "services": [...],         # same normalized shape as input
            "region": "...",
            "existing_link": "..." | ""
        }

    Expected response:
        {
            "calculator_share_url": "https://calculator.aws/#/estimate?id=...",
            "service_breakdown": [...],      # at minimum service_code + monthly_cost
            "manual_estimate_items": [...],
            "warnings": [...]                # optional
        }
    """
    client = boto3.client("lambda", region_name=REGION)
    payload = {
        "services": services,
        "region": region or REGION,
        "existing_link": existing_link or "",
    }
    resp = client.invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode("utf-8"),
    )
    if resp.get("FunctionError"):
        raise RuntimeError(
            f"Node Calculator Lambda returned FunctionError={resp['FunctionError']}"
        )
    body = resp["Payload"].read()
    if isinstance(body, (bytes, bytearray)):
        body = body.decode("utf-8")
    parsed = json.loads(body or "{}")
    # Accept API-Gateway-style wrapped body too.
    if isinstance(parsed, dict) and "body" in parsed and "statusCode" in parsed:
        try:
            parsed = json.loads(parsed.get("body") or "{}")
        except Exception:
            parsed = {}
    if not isinstance(parsed, dict):
        raise RuntimeError("Node Calculator Lambda returned non-object payload")
    return parsed


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point for create_calculator_link."""
    try:
        raw = event.get("inputPayload", "{}")
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        params = json.loads(raw) if isinstance(raw, str) else (raw or {})

        services = _normalize_services(params.get("services", []))
        region = str(params.get("region") or REGION)
        existing_link = str(params.get("existing_link") or "")

        warnings: list[str] = []
        calculator_share_url: str | None = None
        service_breakdown: list[dict[str, Any]] = []
        manual_items: list[dict[str, Any]] = []
        fallback_card: dict[str, Any] | None = None
        mode = "fallback"

        if not services:
            warnings.append("No services provided")
            local_summary = _document_local_summary([], region, [])
            fallback_card = _build_fallback_card([], reason="No services provided")
            return {"outputPayload": json.dumps({
                "mode": "fallback",
                "calculator_share_url": None,
                "service_breakdown": [],
                "manual_estimate_items": [],
                "document_local_summary": local_summary,
                "fallback_card": fallback_card,
                "warnings": warnings,
            })}

        # 1) Try Node.js Calculator Link Lambda if configured.
        if CALCULATOR_LINK_LAMBDA_NAME:
            try:
                result = _invoke_node_lambda(
                    CALCULATOR_LINK_LAMBDA_NAME,
                    services,
                    region,
                    existing_link,
                )
                calculator_share_url = result.get("calculator_share_url") or None
                raw_breakdown = result.get("service_breakdown") or []
                if isinstance(raw_breakdown, list):
                    service_breakdown = raw_breakdown
                raw_manual = result.get("manual_estimate_items") or []
                if isinstance(raw_manual, list):
                    manual_items = raw_manual
                extra_warnings = result.get("warnings") or []
                if isinstance(extra_warnings, list):
                    warnings.extend(str(w) for w in extra_warnings if w)
                mode = "node_lambda"
            except Exception as exc:
                warnings.append(f"Calculator Link Lambda failed: {type(exc).__name__}: {exc}")
                fallback_card = _build_fallback_card(
                    services,
                    reason="Calculator Link Lambda invocation failed",
                )
                mode = "fallback"

        # 2) Future: MCP endpoint support. Currently not implemented in Python —
        # a future change can POST to CALCULATOR_MCP_ENDPOINT here. We record
        # the intent so callers can see the config was seen.
        elif CALCULATOR_MCP_ENDPOINT:
            warnings.append(
                "CALCULATOR_MCP_ENDPOINT is set but MCP client is not wired in "
                "this Lambda — using fallback. Configure CALCULATOR_LINK_LAMBDA_NAME "
                "instead to use the Node.js Calculator Link Lambda."
            )
            fallback_card = _build_fallback_card(
                services,
                reason="Calculator MCP client not implemented in this Lambda",
            )
            mode = "fallback"

        # 3) No link generator configured.
        else:
            warnings.append(
                "CALCULATOR_LINK_LAMBDA_NAME not configured — returning fallback only"
            )
            fallback_card = _build_fallback_card(
                services,
                reason="No calculator link backend configured",
            )
            mode = "fallback"

        # Always preserve document-local summary.
        document_local = _document_local_summary(services, region, service_breakdown)

        # If we had no breakdown, populate it from services so the frontend
        # can still render a table.
        if not service_breakdown:
            service_breakdown = [
                {
                    "service_name": s.get("service_name", ""),
                    "service_code": s.get("service_code", ""),
                    "monthly_cost": s.get("monthly_cost_hint"),
                    "supported_by_calculator": False,
                    "note": "No external calculator backend available"
                            if mode == "fallback" else None,
                }
                for s in services
            ]

        return {"outputPayload": json.dumps({
            "mode": mode,
            "calculator_share_url": calculator_share_url,
            "service_breakdown": service_breakdown,
            "manual_estimate_items": manual_items,
            "document_local_summary": document_local,
            "fallback_card": fallback_card,
            "warnings": warnings,
        })}

    except Exception as e:
        return {"outputPayload": json.dumps({
            "mode": "fallback",
            "error": str(e),
            "warnings": [f"handler_error: {type(e).__name__}: {e}"],
            "calculator_share_url": None,
            "service_breakdown": [],
            "manual_estimate_items": [],
            "document_local_summary": {
                "monthly_cost_total": 0,
                "currency": "USD",
                "region": REGION,
                "generated_at": _now_iso(),
                "rows": [],
            },
            "fallback_card": {
                "type": "fallback",
                "message": f"handler_error: {type(e).__name__}",
                "items": [],
            },
        })}
