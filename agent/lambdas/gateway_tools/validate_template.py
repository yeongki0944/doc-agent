"""Gateway Lambda: validate_template_constraints

Validates that a Document_State conforms to the APN PoC Project Plan
template — required sections present, correct order, and no obvious
numeric inconsistencies between resources_cost_estimates totals and
cost_breakdown.

Input (via event["inputPayload"] JSON):
    {
        "sections": { ... },          # Document_State.sections dict
        "completion_score": 0.65       # optional, for cross-check
    }

Output:
    {
        "valid": true/false,
        "blocking_issues": [...],
        "warnings": [...],
        "completion_score": 0.65
    }
"""

from __future__ import annotations

import json
from typing import Any

# APN template required section keys in canonical order
APN_REQUIRED_SECTIONS = [
    "cover",
    "executive_summary",
    "stakeholders",
    "success_criteria",
    "assumptions",
    "scope_of_work",
    "architecture",
    "milestones",
    "cost_breakdown",
    "acceptance",
    "resources_cost_estimates",
]


def _check_required_sections(sections: dict) -> tuple[list[dict], list[dict]]:
    """Check that all required APN sections exist."""
    blocking: list[dict] = []
    present_keys = list(sections.keys())

    for key in APN_REQUIRED_SECTIONS:
        if key not in present_keys:
            blocking.append({
                "code": "MISSING_SECTION",
                "message": f"Required section '{key}' is missing",
                "section": key,
            })

    return blocking, []


def _check_section_order(sections: dict) -> list[dict]:
    """Check that present sections follow APN canonical order."""
    warnings: list[dict] = []
    present_keys = [k for k in sections.keys() if k in APN_REQUIRED_SECTIONS]
    expected_order = [k for k in APN_REQUIRED_SECTIONS if k in present_keys]

    if present_keys != expected_order:
        warnings.append({
            "code": "SECTION_ORDER",
            "message": "Sections are not in APN template order",
            "section": None,
        })

    return warnings


def _to_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace("$", "").replace(",", ""))
    except (TypeError, ValueError):
        return None


def _check_numeric_consistency(
    sections: dict
) -> list[dict]:
    """Cross-check v2 resource totals vs cost_breakdown if both are present."""
    warnings: list[dict] = []
    cost = sections.get("cost_breakdown", {})
    resources = sections.get("resources_cost_estimates", {})
    funding = cost.get("funding_calculation", {}) if isinstance(cost, dict) else {}
    total_cost = resources.get("total_cost", {}) if isinstance(resources, dict) else {}

    resource_value = total_cost.get("total") if isinstance(total_cost, dict) else total_cost
    sow_value = funding.get("sow_cost") if isinstance(funding, dict) else None

    resource_number = _to_number(resource_value)
    sow_number = _to_number(sow_value)

    if resource_number is not None and sow_number is not None:
        if abs(resource_number - sow_number) > 0.01:
            warnings.append({
                "code": "COST_MISMATCH",
                "message": (
                    f"resources_cost_estimates total_cost ({resource_value}) "
                    f"differs from cost_breakdown funding sow_cost ({sow_value})"
                ),
                "section": "cost_breakdown",
            })

    return warnings


def _calculate_completion_score(sections: dict) -> float:
    """Simple completion score: fraction of required sections with content."""
    if not APN_REQUIRED_SECTIONS:
        return 0.0

    filled = 0
    for key in APN_REQUIRED_SECTIONS:
        section = sections.get(key, {})
        # A section counts as filled if it has any non-empty values
        if section and any(v for v in section.values() if v):
            filled += 1

    return round(filled / len(APN_REQUIRED_SECTIONS), 2)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point for validate_template_constraints."""
    try:
        raw = event.get("inputPayload", "{}")
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        params = json.loads(raw)

        sections = params.get("sections", {})

        blocking, _ = _check_required_sections(sections)
        order_warnings = _check_section_order(sections)
        numeric_warnings = _check_numeric_consistency(sections)
        all_warnings = order_warnings + numeric_warnings

        score = _calculate_completion_score(sections)

        result = {
            "valid": len(blocking) == 0,
            "blocking_issues": blocking,
            "warnings": all_warnings,
            "completion_score": score,
        }
        return {"outputPayload": json.dumps(result)}

    except Exception as e:
        return {"outputPayload": json.dumps({"error": str(e)})}
