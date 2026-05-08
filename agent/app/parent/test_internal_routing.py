"""Focused tests for Parent routing intents and deterministic internal tools."""

from __future__ import annotations

from agent.app.parent.internal_tools import calculate_resource_plan, run_submission_lint
from agent.app.parent.task_planner import build_task_plan


def test_review_submission_routes_to_internal_lint():
    plan = build_task_plan("Run a review summary only")

    assert len(plan.tasks) == 1
    assert plan.tasks[0].agent == "internal_tools"
    assert plan.tasks[0].action == "run_submission_lint"


def test_resource_planning_routes_and_extracts_numbers():
    plan = build_task_plan(
        "Calculate resource planning for target funding 50000 arr 200000 sow cost 75000"
    )

    task = plan.tasks[0]
    assert task.agent == "internal_tools"
    assert task.action == "calculate_resource_plan"
    assert task.params["target_funding_amount"] == 50000
    assert task.params["arr"] == 200000
    assert task.params["sow_cost"] == 75000


def test_resource_plan_keeps_wide_matrix_contract():
    result = calculate_resource_plan({
        "target_funding_amount": 50000,
        "arr": 200000,
        "sow_cost": 75000,
    })

    matrix = result["draft_resource_matrix"]
    assert matrix["matrix_orientation"] == "wide"
    assert "phase_hours_table" in matrix
    assert "role_hours" in matrix["phase_hours_table"][0]
    assert result["eligible_funding_amount"] == 50000
    assert result["required_arr"] == 200000


def test_lint_returns_review_panel_shape():
    result = run_submission_lint({"document_id": "doc-test", "sections": {}, "meta": {}})

    assert "readiness_score" in result
    assert set(result["issues"].keys()) == {"critical", "high", "medium", "low"}
    assert "missing_questions" in result
    assert "suggested_patches" in result
    assert result["kb_retrieval"]["mode"] in {"configured", "fallback"}

