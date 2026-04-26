"""Gateway Lambda: validate_template_constraints

Validates that a Document_State conforms to the APN PoC Project Plan
template — required sections present, correct order, and no obvious
numeric inconsistencies between staffing_plan totals and cost_breakdown.

Input (via event["inputPayload"] JSON):
    {
        "sections": { ... },          # Document_State.sections dict
        "staffing_plan": { ... },      # top-level staffing_plan dict
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


def _check_numeric_consistency(
    staffing_plan: dict, sections: dict
) -> list[dict]:
    """Cross-check staffing_plan totals vs cost_breakdown if present."""
    warnings: list[dict] = []
    cost = sections.get("cost_breakdown", {})
    staffing_cost = cost.get("staffing_cost", {})
    grand_total_from_cost = staffing_cost.get("grand_total", {})

    sp_grand = staffing_plan.get("grand_total_cost", {})
    sp_value = sp_grand.get("calculated")
    cb_value = grand_total_from_cost.get("calculated")

    if sp_value is not None and cb_value is not None:
        if abs(float(sp_value) - float(cb_value)) > 0.01:
            warnings.append({
                "code": "COST_MISMATCH",
                "message": (
                    f"staffing_plan grand_total_cost ({sp_value}) "
                    f"differs from cost_breakdown staffing grand_total ({cb_value})"
                ),
                "section": "cost_breakdown",
            })

    return warnings


def _calculate_completion_score(sections: dict, staffing_plan: dict) -> float:
    """Simple completion score: fraction of required sections with content."""
    if not APN_REQUIRED_SECTIONS:
        return 0.0

    filled = 0
    for key in APN_REQUIRED_SECTIONS:
        section = sections.get(key, {})
        # A section counts as filled if it has any non-empty values
        if section and any(v for v in section.values() if v):
            filled += 1

    # Bonus for staffing_plan having roles
    roles = staffing_plan.get("roles", {})
    if roles:
        filled += 1

    total = len(APN_REQUIRED_SECTIONS) + 1  # +1 for staffing_plan
    return round(filled / total, 2)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point for validate_template_constraints."""
    try:
        raw = event.get("inputPayload", "{}")
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        params = json.loads(raw)

        sections = params.get("sections", {})
        staffing_plan = params.get("staffing_plan", {})

        blocking, _ = _check_required_sections(sections)
        order_warnings = _check_section_order(sections)
        numeric_warnings = _check_numeric_consistency(staffing_plan, sections)
        all_warnings = order_warnings + numeric_warnings

        score = _calculate_completion_score(sections, staffing_plan)

        result = {
            "valid": len(blocking) == 0,
            "blocking_issues": blocking,
            "warnings": all_warnings,
            "completion_score": score,
        }
        return {"outputPayload": json.dumps(result)}

    except Exception as e:
        return {"outputPayload": json.dumps({"error": str(e)})}
