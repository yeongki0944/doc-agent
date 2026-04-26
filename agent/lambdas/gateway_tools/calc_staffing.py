"""Gateway Lambda: calculate_staffing_cost

Deterministic staffing cost calculation.  Uses the same pure functions
from ``agent.lib.calculation.staffing_cost`` to compute per-role hours
and costs, then assembles a cost summary for the cost_breakdown section.

Input (via event["inputPayload"] JSON):
    {
        "staffing_plan": {
            "roles": {
                "project_manager": {
                    "count": { "user_input": null, "ai_recommended": 1, ... },
                    "allocation_pct": { ... },
                    "rate_per_hour": { ... },
                    "phase_hours": {
                        "discovery": { ... },
                        "development": { ... },
                        "testing": { ... }
                    }
                },
                ...
            }
        }
    }

Output:
    {
        "roles_summary": [
            { "role_id": "project_manager", "display_name": "...",
              "total_hours": 140, "rate_per_hour": 81.78, "total_cost": 11449.20 }
        ],
        "grand_total_hours": 560,
        "grand_total_cost": 45796.80
    }
"""

from __future__ import annotations

import json
from typing import Any


def _resolve(field_value: dict) -> float:
    """Extract effective numeric value: user_input > ai_recommended > calculated."""
    val = (
        field_value.get("user_input")
        or field_value.get("ai_recommended")
        or field_value.get("calculated")
    )
    return float(val) if val is not None else 0.0


PHASES = ("discovery", "development", "testing")


def _calculate_role(role_id: str, role: dict) -> dict:
    """Calculate total hours and cost for a single role."""
    count = int(_resolve(role.get("count", {})))
    alloc = _resolve(role.get("allocation_pct", {}))
    rate = _resolve(role.get("rate_per_hour", {}))

    phase_hours = role.get("phase_hours", {})
    hours_per_phase = {p: _resolve(phase_hours.get(p, {})) for p in PHASES}
    total_hours = sum(hours_per_phase.values())
    total_cost = round(count * (alloc / 100) * rate * total_hours, 2)

    return {
        "role_id": role_id,
        "display_name": role.get("display_name", role_id),
        "total_hours": total_hours,
        "rate_per_hour": rate,
        "total_cost": total_cost,
    }


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point for calculate_staffing_cost."""
    try:
        raw = event.get("inputPayload", "{}")
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        params = json.loads(raw)

        staffing_plan = params.get("staffing_plan", {})
        roles = staffing_plan.get("roles", {})

        roles_summary: list[dict] = []
        grand_hours = 0.0
        grand_cost = 0.0

        for role_id, role in roles.items():
            summary = _calculate_role(role_id, role)
            roles_summary.append(summary)
            grand_hours += summary["total_hours"]
            grand_cost += summary["total_cost"]

        result = {
            "roles_summary": roles_summary,
            "grand_total_hours": round(grand_hours, 2),
            "grand_total_cost": round(grand_cost, 2),
        }
        return {"outputPayload": json.dumps(result)}

    except Exception as e:
        return {"outputPayload": json.dumps({"error": str(e)})}
