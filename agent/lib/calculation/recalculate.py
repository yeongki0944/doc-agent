"""Recalculation trigger for staffing plan changes.

When any staffing_plan field changes, this module recalculates all
derived (calculated) fields in bulk.
"""

from __future__ import annotations

from agent.lib.calculation.staffing_cost import (
    calculate_role_total_hours,
    calculate_role_total_cost,
    calculate_grand_total,
)


def _resolve(field_value: dict | object) -> float:
    """Extract the effective numeric value from a FieldValue-like dict or object.

    Priority: user_input > ai_recommended > calculated, fallback 0.
    """
    if isinstance(field_value, dict):
        val = field_value.get("user_input") or field_value.get("ai_recommended") or field_value.get("calculated")
    else:
        val = getattr(field_value, "user_input", None) or getattr(field_value, "ai_recommended", None) or getattr(field_value, "calculated", None)
    return float(val) if val is not None else 0.0


def recalculate_costs(staffing_plan: dict | object) -> dict:
    """Recalculate all derived fields in a staffing plan.

    Accepts either a dict (JSON-like) or a StaffingPlan Pydantic model.

    Returns:
        dict with updated calculated values:
        {
            "roles": { role_id: {"total_hours": float, "total_cost": float}, ... },
            "grand_total_hours": float,
            "grand_total_cost": float,
        }
    """
    if isinstance(staffing_plan, dict):
        roles = staffing_plan.get("roles", {})
    else:
        roles = staffing_plan.roles if hasattr(staffing_plan, "roles") else {}
        if not isinstance(roles, dict):
            roles = {k: v for k, v in roles.items()} if hasattr(roles, "items") else {}

    result_roles: dict[str, dict] = {}
    all_costs: list[float] = []
    all_hours: list[float] = []

    for role_id, role in roles.items():
        if isinstance(role, dict):
            ph = role.get("phase_hours", {})
            phase_dict = {
                phase: _resolve(ph.get(phase, {}))
                for phase in ("discovery", "development", "testing")
            }
            count = int(_resolve(role.get("count", {})))
            alloc = _resolve(role.get("allocation_pct", {}))
            rate = _resolve(role.get("rate_per_hour", {}))
        else:
            ph = role.phase_hours if hasattr(role, "phase_hours") else None
            phase_dict = {}
            if ph:
                for phase in ("discovery", "development", "testing"):
                    phase_dict[phase] = _resolve(getattr(ph, phase, {}))
            count = int(_resolve(getattr(role, "count", {})))
            alloc = _resolve(getattr(role, "allocation_pct", {}))
            rate = _resolve(getattr(role, "rate_per_hour", {}))

        total_hours = calculate_role_total_hours(phase_dict)
        total_cost = calculate_role_total_cost(count, alloc, rate, total_hours)

        result_roles[role_id] = {"total_hours": total_hours, "total_cost": total_cost}
        all_hours.append(total_hours)
        all_costs.append(total_cost)

    return {
        "roles": result_roles,
        "grand_total_hours": round(sum(all_hours), 2),
        "grand_total_cost": calculate_grand_total(all_costs),
    }
