"""Parent-side deterministic tools used when Gateway is unavailable.

These helpers intentionally mirror the document_api MCP-style contracts without
importing Lambda handlers into AgentCore Runtime. They do not perform AWS calls.
"""

from __future__ import annotations

import os
from typing import Any


RESOURCE_PLAN_WARNING = (
    "This is a Resource Planning draft. Final values must be reviewed with AWS "
    "Calculator, Bedrock usage assumption, SOW cost, customer scope, and sales owner."
)


def confirmed_field_value(value: Any) -> dict[str, Any]:
    return {
        "user_input": None,
        "ai_recommended": None,
        "calculated": value,
        "status": "confirmed",
        "user_edited": False,
    }


def resolve_field_value(value: Any) -> Any:
    if isinstance(value, dict) and any(
        key in value for key in ("user_input", "ai_recommended", "calculated")
    ):
        for key in ("user_input", "ai_recommended", "calculated"):
            candidate = value.get(key)
            if candidate not in (None, ""):
                return candidate
        return ""
    return value


def has_resolved_value(value: Any) -> bool:
    return resolve_field_value(value) not in (None, "", [], {})


def to_float(value: Any, default: float = 0.0) -> float:
    resolved = resolve_field_value(value)
    if resolved in (None, ""):
        return default
    try:
        return float(str(resolved).replace("$", "").replace(",", ""))
    except (TypeError, ValueError):
        return default


def approved_samples_fallback() -> dict[str, Any]:
    kb_id = os.environ.get("APPROVED_SAMPLES_KB_ID", "")
    data_source = os.environ.get("APPROVED_SAMPLES_DATA_SOURCE_ID", "")
    if kb_id:
        return {
            "mode": "configured",
            "message": "Approved samples knowledge base is configured.",
            "kb_id_present": True,
            "data_source_present": bool(data_source),
        }
    return {
        "mode": "fallback",
        "message": (
            "Approved samples Knowledge Base is not configured. Proceeding with "
            "deterministic APN/GenAI IC/SOW readiness checks only."
        ),
        "kb_id_present": False,
        "data_source_present": False,
    }


def make_issue(
    severity: str,
    code: str,
    message: str,
    section: str,
    question: str = "",
) -> dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "section": section,
        "question": question,
    }


def run_submission_lint(document: dict[str, Any]) -> dict[str, Any]:
    sections = document.get("sections", {}) if isinstance(document.get("sections"), dict) else {}
    meta = document.get("meta", {}) if isinstance(document.get("meta"), dict) else {}
    cost = sections.get("cost_breakdown", {}) if isinstance(sections.get("cost_breakdown"), dict) else {}
    architecture = sections.get("architecture", {}) if isinstance(sections.get("architecture"), dict) else {}
    resources = sections.get("resources_cost_estimates", {}) if isinstance(sections.get("resources_cost_estimates"), dict) else {}
    executive = sections.get("executive_summary", {}) if isinstance(sections.get("executive_summary"), dict) else {}

    issues: dict[str, list[dict[str, Any]]] = {
        "critical": [],
        "high": [],
        "medium": [],
        "low": [],
    }
    missing_questions: list[str] = []
    suggested_patches: list[dict[str, Any]] = []

    for section in (
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
    ):
        value = sections.get(section)
        if value in (None, {}, []):
            issue = make_issue(
                "high",
                f"{section.upper()}_INCOMPLETE",
                f"{section} is a submission readiness issue and is recommended before submission.",
                section,
                f"What content should be added to {section}?",
            )
            issues["high"].append(issue)
            missing_questions.append(issue["question"])

    services = architecture.get("services", []) if isinstance(architecture.get("services"), list) else []
    has_bedrock = any(
        "bedrock" in str(resolve_field_value((svc or {}).get("service_name", ""))).lower()
        or "bedrock" in str((svc or {}).get("service_id", "")).lower()
        for svc in services
        if isinstance(svc, dict)
    )
    if not has_bedrock:
        question = "Which Amazon Bedrock models, guardrails, or usage assumptions are in scope?"
        issues["critical"].append(make_issue(
            "critical",
            "BEDROCK_EVIDENCE_MISSING",
            "Amazon Bedrock inclusion needs more evidence before submission.",
            "architecture",
            question,
        ))
        missing_questions.append(question)

    calculator_url = cost.get("calculator_url", {})
    mrr = to_float(cost.get("mrr", 0))
    arr = to_float(cost.get("arr", 0))
    funding = cost.get("funding_calculation", {}) if isinstance(cost.get("funding_calculation"), dict) else {}
    sow_cost = to_float(funding.get("sow_cost"))
    if sow_cost <= 0:
        total_cost = resources.get("total_cost", {}) if isinstance(resources.get("total_cost"), dict) else {}
        sow_cost = to_float(total_cost.get("total"))

    if not has_resolved_value(calculator_url):
        issues["high"].append(make_issue(
            "high",
            "CALCULATOR_URL_MISSING",
            "AWS Calculator evidence is recommended before submission.",
            "cost_breakdown",
            "What AWS Calculator URL or cost basis should be referenced?",
        ))
    if arr <= 0 and mrr > 0:
        suggested_patches.append({
            "op": "replace",
            "path": "/sections/cost_breakdown/arr",
            "value": confirmed_field_value(round(mrr * 12, 2)),
            "reason": "ARR can be calculated from MRR when MRR is provided.",
        })
    if arr <= 0:
        issues["high"].append(make_issue(
            "high",
            "ARR_MISSING",
            "ARR / funding basis is a submission readiness issue.",
            "cost_breakdown",
            "What is the Year 1 ARR basis for this PoC?",
        ))
    if sow_cost <= 0:
        issues["high"].append(make_issue(
            "high",
            "SOW_COST_MISSING",
            "SOW cost basis is recommended before submission.",
            "resources_cost_estimates",
            "What SOW cost should be used for funding eligibility?",
        ))

    overview = architecture.get("overview", {})
    if services and not has_resolved_value(overview):
        issues["medium"].append(make_issue(
            "medium",
            "ARCHITECTURE_OVERVIEW_MISSING",
            "Architecture and service sizing needs more evidence before submission.",
            "architecture",
            "How do the listed AWS services support the target workload and sizing?",
        ))

    business_groups = executive.get("groups", []) if isinstance(executive.get("groups"), list) else []
    if not business_groups:
        issues["medium"].append(make_issue(
            "medium",
            "BUSINESS_CASE_MISSING",
            "Business Case & Commitment is recommended before submission.",
            "executive_summary",
            "What business problem, ROI basis, sponsor, and production commitment should be documented?",
        ))

    assumptions = sections.get("assumptions", {}) if isinstance(sections.get("assumptions"), dict) else {}
    if assumptions in ({}, {"groups": [], "items": []}):
        issues["medium"].append(make_issue(
            "medium",
            "RISK_GOVERNANCE_MISSING",
            "Risk assessment and governance assumptions are recommended before submission.",
            "assumptions",
            "What risks, governance controls, and customer assumptions should be included?",
        ))

    if not has_resolved_value(meta.get("customer", {})):
        issues["low"].append(make_issue(
            "low",
            "CUSTOMER_MISSING",
            "Customer name should be confirmed before submission.",
            "meta",
            "What is the customer name?",
        ))

    penalty = (
        len(issues["critical"]) * 22
        + len(issues["high"]) * 12
        + len(issues["medium"]) * 7
        + len(issues["low"]) * 3
    )
    readiness_score = max(0, min(100, 100 - penalty))

    if arr > 0 and sow_cost > 0:
        eligible = min(arr * 0.25, sow_cost, 125000)
        suggested_patches.append({
            "op": "replace",
            "path": "/sections/cost_breakdown/funding_calculation",
            "value": {
                **funding,
                "yr1_arr": arr,
                "sow_cost": sow_cost,
                "eligible_amount": round(eligible, 2),
                "formula": "min(Year 1 ARR * 25%, SOW Cost, 125000)",
            },
            "reason": "Update deterministic funding calculation basis.",
        })

    return {
        "readiness_score": readiness_score,
        "issues": issues,
        "missing_questions": missing_questions,
        "suggested_patches": suggested_patches,
        "kb_retrieval": approved_samples_fallback(),
    }


def calculate_resource_plan(body: dict[str, Any]) -> dict[str, Any]:
    target = to_float(body.get("target_funding_amount"))
    mrr = to_float(body.get("mrr"))
    arr = to_float(body.get("arr"))
    sow_cost = to_float(body.get("sow_cost"))
    assumptions = body.get("assumptions") or []

    required_arr = round(target / 0.25, 2) if target > 0 else 0.0
    effective_arr = arr if arr > 0 else (mrr * 12 if mrr > 0 else required_arr)
    required_sow_cost = target
    cap_limited = target > 125000
    eligible_amount = round(
        min(effective_arr * 0.25, sow_cost if sow_cost > 0 else required_sow_cost, 125000),
        2,
    )

    role_rates = [
        {"role": "Solution Architect", "rate": confirmed_field_value(180)},
        {"role": "Engineer", "rate": confirmed_field_value(150)},
        {"role": "Project Manager", "rate": confirmed_field_value(130)},
    ]
    phase_hours_table = [
        {
            "phase": confirmed_field_value("Discovery & Design"),
            "role_hours": [
                {"role": "Solution Architect", "hours": 24},
                {"role": "Engineer", "hours": 16},
                {"role": "Project Manager", "hours": 8},
            ],
            "total": 48,
        },
        {
            "phase": confirmed_field_value("Build & Integration"),
            "role_hours": [
                {"role": "Solution Architect", "hours": 32},
                {"role": "Engineer", "hours": 80},
                {"role": "Project Manager", "hours": 16},
            ],
            "total": 128,
        },
        {
            "phase": confirmed_field_value("Validation & Handover"),
            "role_hours": [
                {"role": "Solution Architect", "hours": 16},
                {"role": "Engineer", "hours": 32},
                {"role": "Project Manager", "hours": 12},
            ],
            "total": 60,
        },
    ]

    total_cost = 0.0
    rate_by_role = {row["role"]: to_float(row["rate"]) for row in role_rates}
    for phase in phase_hours_table:
        for row in phase["role_hours"]:
            total_cost += to_float(row.get("hours")) * rate_by_role.get(row.get("role"), 0.0)

    contribution = {
        "customer": {
            "amount": confirmed_field_value(max(round(total_cost - target, 2), 0)),
            "pct": confirmed_field_value(""),
        },
        "partner": {"amount": confirmed_field_value(0), "pct": confirmed_field_value("")},
        "aws": {
            "amount": confirmed_field_value(min(target, 125000)),
            "pct": confirmed_field_value(""),
        },
    }

    warnings = [RESOURCE_PLAN_WARNING]
    if cap_limited:
        warnings.append("$125K cap applies; requested target funding exceeds the maximum formula cap.")
    if sow_cost and sow_cost < target:
        warnings.append("SOW cost is below the target funding amount, so SOW cost limits eligibility.")
    if effective_arr * 0.25 < target:
        warnings.append("ARR is below the amount required to support the target funding amount under the 25% rule.")

    return {
        "target_funding_amount": target,
        "required_arr": required_arr,
        "sow_cost_requirement": required_sow_cost,
        "cap_check": {"cap": 125000, "cap_limited": cap_limited},
        "eligible_funding_amount": eligible_amount,
        "formula": "Eligible Funding Amount = min(Year 1 ARR * 25%, SOW Cost, 125000)",
        "draft_resource_matrix": {
            "role_rates": role_rates,
            "phase_hours_table": phase_hours_table,
            "matrix_orientation": "wide",
        },
        "contribution_distribution": contribution,
        "assumptions": assumptions,
        "warnings": warnings,
    }


def resource_plan_patches(result: dict[str, Any]) -> list[dict[str, Any]]:
    matrix = result.get("draft_resource_matrix") if isinstance(result, dict) else {}
    if not isinstance(matrix, dict):
        matrix = {}
    return [
        {
            "op": "replace",
            "path": "/sections/resources_cost_estimates/role_rates",
            "value": matrix.get("role_rates", []),
            "source": "calculated",
        },
        {
            "op": "replace",
            "path": "/sections/resources_cost_estimates/phase_hours_table",
            "value": matrix.get("phase_hours_table", []),
            "source": "calculated",
        },
        {
            "op": "replace",
            "path": "/sections/resources_cost_estimates/contribution",
            "value": result.get("contribution_distribution", {}),
            "source": "calculated",
        },
        {
            "op": "replace",
            "path": "/sections/cost_breakdown/funding_calculation",
            "value": {
                "target_funding_amount": result.get("target_funding_amount", 0),
                "required_arr": result.get("required_arr", 0),
                "sow_cost_requirement": result.get("sow_cost_requirement", 0),
                "eligible_amount": result.get("eligible_funding_amount", 0),
                "formula": result.get("formula", ""),
                "cap_check": result.get("cap_check", {}),
            },
            "source": "calculated",
        },
    ]

