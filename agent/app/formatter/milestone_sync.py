"""Milestone synchronization — rebuild milestones when staffing/scope changes.

In production: calls Gateway's build_milestone_summary tool.
Currently: deterministic generation from staffing_plan + scope.
"""

from __future__ import annotations

from agent.lib.schema.document_state import DocumentState


PHASES = ["discovery", "development", "testing"]


def sync_milestones(doc: DocumentState) -> DocumentState:
    """Regenerate milestones section from staffing_plan and scope_of_work."""
    roles = doc.staffing_plan.roles
    if not roles:
        return doc

    role_names = [r.display_name for r in roles.values()]

    milestones = []
    for phase in PHASES:
        total_hours = sum(
            getattr(r.phase_hours, phase).user_input
            or getattr(r.phase_hours, phase).ai_recommended
            or 0
            for r in roles.values()
        )
        milestones.append({
            "phase": phase,
            "total_hours": total_hours,
            "roles": role_names,
            "deliverables": _default_deliverables(phase),
        })

    # Store in milestones section (using extra fields)
    doc.sections.milestones.phases = milestones  # type: ignore
    return doc


def _default_deliverables(phase: str) -> list[str]:
    return {
        "discovery": ["요구사항 문서", "아키텍처 설계서", "프로젝트 계획서"],
        "development": ["에이전트 구현", "API 개발", "UI 구현", "통합"],
        "testing": ["통합 테스트", "UAT", "버그 수정", "최종 문서"],
    }.get(phase, [])
