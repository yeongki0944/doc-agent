"""Apply staffing recommendation to Document_State as ai_recommended."""

from __future__ import annotations

from agent.lib.schema.document_state import (
    DocumentState, FieldValue, FieldStatus,
    StaffingPlan, StaffingRole, PhaseHours,
)
from agent.app.staffing.staffing_agent import StaffingRecommendation
from agent.lib.calculation.recalculate import recalculate_costs


def apply_recommendation(doc: DocumentState, rec: StaffingRecommendation) -> DocumentState:
    """Write recommendation into doc.staffing_plan as ai_recommended values."""
    roles: dict[str, StaffingRole] = {}

    for role_id, data in rec.roles.items():
        ph = data.get("phase_hours", {})
        role = StaffingRole(
            role_id=role_id,
            display_name=data.get("display_name", role_id),
            count=FieldValue(ai_recommended=data["count"], status=FieldStatus.recommended),
            allocation_pct=FieldValue(ai_recommended=data["allocation_pct"], status=FieldStatus.recommended),
            rate_per_hour=FieldValue(ai_recommended=data["rate_per_hour"], status=FieldStatus.recommended),
            phase_hours=PhaseHours(
                discovery=FieldValue(ai_recommended=ph.get("discovery", 0), status=FieldStatus.recommended),
                development=FieldValue(ai_recommended=ph.get("development", 0), status=FieldStatus.recommended),
                testing=FieldValue(ai_recommended=ph.get("testing", 0), status=FieldStatus.recommended),
            ),
            reason=data.get("reason"),
            source_patterns=data.get("source_patterns", []),
        )
        roles[role_id] = role

    doc.staffing_plan = StaffingPlan(roles=roles)

    # Recalculate derived fields
    calc = recalculate_costs(doc.staffing_plan)
    for rid, vals in calc["roles"].items():
        if rid in doc.staffing_plan.roles:
            doc.staffing_plan.roles[rid].total_hours.calculated = vals["total_hours"]
            doc.staffing_plan.roles[rid].total_cost.calculated = vals["total_cost"]
    doc.staffing_plan.grand_total_hours.calculated = calc["grand_total_hours"]
    doc.staffing_plan.grand_total_cost.calculated = calc["grand_total_cost"]

    return doc
