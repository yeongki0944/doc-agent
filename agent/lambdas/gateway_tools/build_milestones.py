"""Gateway Lambda: build_milestone_summary

Synchronizes milestones with staffing_plan and scope_of_work.
Generates phase-level schedule, deliverables, and assigned roles.

Input (via event["inputPayload"] JSON):
    {
        "staffing_plan": {
            "roles": { ... }
        },
        "scope_of_work": { ... }
    }

Output:
    {
        "phases": [
            {
                "phase": "discovery",
                "total_hours": 120,
                "roles": ["Project Manager", "Solutions Architect", ...],
                "deliverables": ["요구사항 문서", "아키텍처 설계서", ...]
            },
            ...
        ],
        "total_project_hours": 600
    }
"""

from __future__ import annotations

import json
from typing import Any

PHASES = ("discovery", "development", "testing")

DEFAULT_DELIVERABLES: dict[str, list[str]] = {
    "discovery": ["요구사항 문서", "아키텍처 설계서", "프로젝트 계획서"],
    "development": ["에이전트 구현", "API 개발", "UI 구현", "통합"],
    "testing": ["통합 테스트", "UAT", "버그 수정", "최종 문서"],
}


def _resolve(field_value: dict) -> float:
    """Extract effective numeric value: user_input > ai_recommended > calculated."""
    val = (
        field_value.get("user_input")
        or field_value.get("ai_recommended")
        or field_value.get("calculated")
    )
    return float(val) if val is not None else 0.0


def _build_phases(roles: dict, scope: dict) -> list[dict]:
    """Build phase summaries from staffing_plan roles."""
    phases: list[dict] = []

    for phase in PHASES:
        total_hours = 0.0
        assigned_roles: list[str] = []

        for role_id, role in roles.items():
            phase_hours = role.get("phase_hours", {})
            hours = _resolve(phase_hours.get(phase, {}))
            if hours > 0:
                total_hours += hours
                display_name = role.get("display_name", role_id)
                if display_name not in assigned_roles:
                    assigned_roles.append(display_name)

        # Use scope deliverables if provided, otherwise defaults
        scope_deliverables = scope.get(f"{phase}_deliverables")
        deliverables = (
            scope_deliverables
            if isinstance(scope_deliverables, list)
            else DEFAULT_DELIVERABLES.get(phase, [])
        )

        phases.append({
            "phase": phase,
            "total_hours": round(total_hours, 2),
            "roles": assigned_roles,
            "deliverables": deliverables,
        })

    return phases


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point for build_milestone_summary."""
    try:
        raw = event.get("inputPayload", "{}")
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        params = json.loads(raw)

        staffing_plan = params.get("staffing_plan", {})
        scope = params.get("scope_of_work", {})
        roles = staffing_plan.get("roles", {})

        phases = _build_phases(roles, scope)
        total_hours = sum(p["total_hours"] for p in phases)

        result = {
            "phases": phases,
            "total_project_hours": round(total_hours, 2),
        }
        return {"outputPayload": json.dumps(result)}

    except Exception as e:
        return {"outputPayload": json.dumps({"error": str(e)})}
