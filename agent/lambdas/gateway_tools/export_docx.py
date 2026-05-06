"""Gateway Lambda: export_docx.

Downloads the APN PoC DOCX template from S3, renders it with docxtpl using
Document_State data, uploads the rendered DOCX to S3, and returns a download URL.

v2: Reads from v2 schema paths only. No legacy fallbacks.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import zipfile
from copy import deepcopy
from typing import Any
from xml.etree import ElementTree as ET

import boto3


ARTIFACTS_BUCKET = os.environ.get("ARTIFACTS_BUCKET") or os.environ.get("S3_BUCKET", "doc-agent-artifacts")
TEMPLATE_S3_KEY = os.environ.get("TEMPLATE_S3_KEY", "templates/apn-poc-template_v2.docx")
REGION = os.environ.get("AWS_REGION", "ap-northeast-2")
DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
STRUCTURED_BULLET_L1 = "__DOCAGENT_STRUCTURED_BULLET_L1__"
STRUCTURED_BULLET_L2 = "__DOCAGENT_STRUCTURED_BULLET_L2__"
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{WORD_NS}}}"


def _response(payload: dict[str, Any]) -> dict[str, str]:
    return {"outputPayload": json.dumps(payload, ensure_ascii=False)}


def _error(stage: str, exc: Exception) -> dict[str, str]:
    return _response({
        "error": str(exc),
        "error_type": type(exc).__name__,
        "stage": stage,
    })


def resolve_field_value(field: Any, default: Any = "") -> Any:
    """Resolve a Document_State field-like value to its display value."""
    if isinstance(field, dict) and any(k in field for k in ("user_input", "ai_recommended", "calculated")):
        for key in ("user_input", "ai_recommended", "calculated"):
            value = field.get(key)
            if value is not None and value != "":
                return value
        return default
    if field is None:
        return default
    return field


def join_field_values(value: Any, separator: str = "\n") -> str:
    """Join list-like values into a display string."""
    resolved = resolve_field_value(value)
    if resolved in ("", None):
        return ""
    if isinstance(resolved, str):
        return resolved
    if isinstance(resolved, dict):
        items = resolved.values()
    elif isinstance(resolved, (list, tuple, set)):
        items = resolved
    else:
        return str(resolved)

    parts: list[str] = []
    for item in items:
        item_value = resolve_field_value(item)
        if isinstance(item_value, dict):
            item_value = " / ".join(
                str(resolve_field_value(v))
                for v in item_value.values()
                if resolve_field_value(v) not in ("", None)
            )
        if item_value not in ("", None):
            parts.append(str(item_value))
    return separator.join(parts)


def _bullet_join(value: Any) -> str:
    """Render a list-like value as newline-separated bullets."""
    resolved = resolve_field_value(value)
    if resolved in ("", None):
        return ""
    if isinstance(resolved, str):
        return resolved
    if isinstance(resolved, dict):
        items = resolved.values()
    elif isinstance(resolved, (list, tuple, set)):
        items = resolved
    else:
        return str(resolved)

    bullets: list[str] = []
    for item in items:
        item_value = resolve_field_value(item)
        if isinstance(item_value, dict):
            item_value = " / ".join(
                str(resolve_field_value(v))
                for v in item_value.values()
                if resolve_field_value(v) not in ("", None)
            )
        if item_value not in ("", None):
            bullets.append(f"- {item_value}")
    return "\n".join(bullets)


def money_format(value: Any) -> str:
    """Render a number with thousands separators for DOCX templates."""
    resolved = resolve_field_value(value)
    if resolved in ("", None):
        return ""
    try:
        number = float(resolved)
    except (TypeError, ValueError):
        return str(resolved)
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.2f}".rstrip("0").rstrip(".")


def bool_status(value: Any, true_text: str = "Yes", false_text: str = "No") -> str:
    """Convert a truthy value into a template-friendly status string."""
    return true_text if bool(resolve_field_value(value)) else false_text


def _resolve_field(field: Any, default: Any = "") -> Any:
    """Backward-compatible alias for legacy tests and callers."""
    return resolve_field_value(field, default)


def _section(sections: dict[str, Any], key: str) -> dict[str, Any]:
    section = sections.get(key, {})
    return section if isinstance(section, dict) else {}


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        return dumped if isinstance(dumped, dict) else {}
    return {}


def _safe_int(value: Any, default: int = 99) -> int:
    resolved = resolve_field_value(value, default)
    try:
        return int(float(resolved))
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    resolved = resolve_field_value(value, default)
    try:
        return float(str(resolved).replace(",", ""))
    except (TypeError, ValueError):
        return default


def _structured_bullet_text(item: Any) -> str:
    data = _as_mapping(item)
    if data and "text" in data:
        return str(resolve_field_value(data.get("text", ""), ""))
    return str(resolve_field_value(item, ""))


def _structured_bullet_level(item: Any) -> int:
    data = _as_mapping(item)
    try:
        level = int(data.get("level", 1)) if data else 1
    except (TypeError, ValueError):
        level = 1
    return 2 if level == 2 else 1


def _structured_bullets(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        items = value.values()
    elif isinstance(value, (list, tuple, set)):
        items = value
    elif value in ("", None):
        items = []
    else:
        items = [value]

    result: list[dict[str, Any]] = []
    for item in items:
        text = _structured_bullet_text(item)
        if text not in ("", None):
            result.append({"text": text, "level": _structured_bullet_level(item)})
    return result


def _flatten_structured_bullets(value: Any) -> str:
    lines: list[str] = []
    for item in _structured_bullets(value):
        marker = STRUCTURED_BULLET_L2 if item["level"] == 2 else STRUCTURED_BULLET_L1
        lines.append(f"{marker}{item['text']}")
    return "\n".join(lines)


def _template_bullet_text(item: dict[str, Any]) -> str:
    """Marked text for post-render conversion to the correct Word list level."""
    marker = STRUCTURED_BULLET_L2 if item["level"] == 2 else STRUCTURED_BULLET_L1
    return f"{marker}{item['text']}"


# ---------------------------------------------------------------------------
# Helpers — kept and updated for v2
# ---------------------------------------------------------------------------

def _normalize_contact_entry(entry: Any, label_key: str, fallback_value: str = "") -> dict[str, Any]:
    """Normalize a contact entry dict for template rendering.

    v2: removed role_or_description fallback.
    """
    if not isinstance(entry, dict):
        entry = {}

    label_value = _resolve_field(
        entry.get(label_key, entry.get("description", entry.get("stakeholder_for", ""))),
        fallback_value,
    )
    return {
        "name": _resolve_field(entry.get("name", "")),
        "title": _resolve_field(entry.get("title", "")),
        "description": _resolve_field(entry.get("description", label_value)),
        "stakeholder_for": _resolve_field(entry.get("stakeholder_for", label_value)),
        "role": _resolve_field(entry.get("role", label_value)),
        "contact": _resolve_field(entry.get("contact", "")),
    }


def _group_rows(groups: Any) -> list[dict[str, Any]]:
    """Render CategoryGroup list for template. v2: reads `bullets` not `items`."""
    rows: list[dict[str, Any]] = []
    if not isinstance(groups, list):
        return rows

    for group in groups:
        data = _as_mapping(group)
        if not data:
            continue
        bullets = _structured_bullets(data.get("bullets", data.get("values", data.get("details", []))))
        rows.append({
            "category_name": resolve_field_value(data.get("category_name", data.get("name", ""))),
            "bullets_text": _flatten_structured_bullets(data.get("bullets", [])),
            "bullets": [_template_bullet_text(item) for item in bullets],
            "bullets_structured": bullets,
        })
    return rows


def _scope_task_rows(tasks: Any) -> list[dict[str, Any]]:
    """Render ScopeTask list for template. v2: `details` is a single FieldValue."""
    rows: list[dict[str, Any]] = []
    if not isinstance(tasks, list):
        return rows

    for task in tasks:
        data = _as_mapping(task)
        if not data:
            continue
        rows.append({
            "task_category": resolve_field_value(data.get("task_category", "")),
            "schedule": resolve_field_value(data.get("schedule", "")),
            "details": _flatten_structured_bullets(data.get("details", [])),
            "personnel": _flatten_structured_bullets(data.get("personnel", [])),
        })
    return rows


def _architecture_service_rows(architecture: dict[str, Any]) -> list[dict[str, Any]]:
    services = architecture.get("services", [])
    if not isinstance(services, list):
        services = []

    rows: list[dict[str, Any]] = []
    for service in services:
        data = _as_mapping(service)
        if not data:
            continue
        rows.append({
            "priority": _safe_int(data.get("priority", 99)),
            "service_name": resolve_field_value(data.get("service_name", data.get("name", data.get("service_id", "")))),
            "service_id": resolve_field_value(data.get("service_id", data.get("name", ""))),
            "description": resolve_field_value(data.get("description", "")),
            "sizing_rationale": resolve_field_value(data.get("sizing_rationale", "")),
            "category": resolve_field_value(data.get("category", "")),
            "is_required_for_funding": bool(resolve_field_value(data.get("is_required_for_funding", False))),
        })

    rows.sort(key=lambda item: (item["priority"], item["service_name"]))
    return rows


def _bedrock_present(architecture_services: list[dict[str, Any]]) -> bool:
    for service in architecture_services:
        name = str(service.get("service_name", "")).lower()
        service_id = str(service.get("service_id", "")).lower()
        if "bedrock" in name or "bedrock" in service_id:
            return True
    return False


def _build_contribution(resources_cost_estimates: dict[str, Any]) -> dict[str, Any]:
    contribution = resources_cost_estimates.get("contribution", {})
    if not isinstance(contribution, dict):
        contribution = {}

    parties = {}
    rows = []
    for party in ("customer", "partner", "aws"):
        entry = contribution.get(party, {})
        if not isinstance(entry, dict):
            entry = {}
        party_context = {
            "amount": _resolve_field(entry.get("amount", {}), 0),
            "pct": _resolve_field(entry.get("pct", {}), 0),
        }
        parties[party] = party_context
        rows.append({"party": party, **party_context})

    return {"parties": parties, "rows": rows}


def _resolve_list(items: Any) -> list[str]:
    """Resolve a list[FieldValue] to a list of resolved strings."""
    if not isinstance(items, list):
        return []
    result: list[str] = []
    for item in items:
        resolved = resolve_field_value(item, "")
        if resolved not in ("", None):
            result.append(str(resolved))
    return result


def _acceptance_step_rows(steps: Any) -> list[dict[str, Any]]:
    """Render AcceptanceStep list for template."""
    rows: list[dict[str, Any]] = []
    if not isinstance(steps, list):
        return rows

    for step in steps:
        data = _as_mapping(step)
        if not data:
            continue
        rows.append({
            "heading": resolve_field_value(data.get("heading", "")),
            "content": resolve_field_value(data.get("content", "")),
            "bullets": [_template_bullet_text(item) for item in _structured_bullets(data.get("bullets", []))],
        })
    return rows


def _partner_team_rows(team: Any) -> list[dict[str, Any]]:
    """Render Partner Project Team rows from Stakeholders."""
    rows: list[dict[str, Any]] = []
    if not isinstance(team, list):
        return rows

    for member in team:
        data = _as_mapping(member)
        if not data:
            continue
        rows.append({
            "role": resolve_field_value(data.get("role", "")),
            "name": resolve_field_value(data.get("name", "")),
            "contact": resolve_field_value(data.get("contact", "")),
        })
    return rows


def _role_rate_rows(project_team: Any, resources_cost_estimates: dict[str, Any]) -> list[dict[str, Any]]:
    team_rows = _partner_team_rows(project_team)
    rates = resources_cost_estimates.get("role_rates", [])
    if not isinstance(rates, list):
        rates = []

    rate_by_role: dict[str, Any] = {}
    for row in rates:
        data = _as_mapping(row)
        role = str(resolve_field_value(data.get("role", ""), "")).strip()
        if role:
            rate_by_role[role] = resolve_field_value(data.get("rate", {}), 100)

    grouped: dict[str, dict[str, Any]] = {}
    for member in team_rows:
        role = str(member.get("role", "")).strip() or "Unassigned"
        rate = _safe_float(rate_by_role.get(role, 100), 100.0)
        entry = grouped.setdefault(role, {"role": role, "count": 0, "members": [], "rate": rate})
        entry["count"] += 1
        name = str(member.get("name", "")).strip()
        if name:
            entry["members"].append(name)

    return [
        {**row, "members": ", ".join(row["members"]), "rate_display": money_format(row["rate"])}
        for row in grouped.values()
    ]


def _phase_role_hours(data: dict[str, Any]) -> dict[str, float]:
    role_hours = data.get("role_hours", [])
    if not isinstance(role_hours, list):
        return {}

    result: dict[str, float] = {}
    for item in role_hours:
        row = _as_mapping(item)
        role = str(resolve_field_value(row.get("role", ""), "")).strip()
        if role:
            result[role] = _safe_float(row.get("hours", 0), 0.0)
    return result


def _phase_hours_context(
    table: Any,
    role_rates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build dynamic resource phase-hours context for DOCX rendering.

    The web UI renders dynamic role columns. The DOCX template uses a stable
    row-oriented fallback so removed roles are hidden and old static
    SA/Engineer/Other fields are ignored.
    """
    roles = [str(row.get("role", "")).strip() for row in role_rates if str(row.get("role", "")).strip()]
    rate_by_role = {str(row.get("role", "")): _safe_float(row.get("rate", 100), 100.0) for row in role_rates}
    count_by_role = {str(row.get("role", "")): _safe_int(row.get("count", 0), 0) for row in role_rates}

    phase_rows: list[dict[str, Any]] = []
    detail_rows: list[dict[str, Any]] = []
    total_hours_by_role = {role: 0.0 for role in roles}
    if not isinstance(table, list):
        table = []

    for entry in table:
        data = _as_mapping(entry)
        if not data:
            continue
        phase = resolve_field_value(data.get("phase", ""))
        role_hours_by_role = _phase_role_hours(data)
        display_role_hours: list[dict[str, Any]] = []
        phase_total = 0.0
        for role in roles:
            hours = _safe_float(role_hours_by_role.get(role, 0), 0.0)
            rate = rate_by_role.get(role, 100.0)
            cost = hours * rate
            phase_total += hours
            total_hours_by_role[role] += hours
            role_row = {
                "role": role,
                "hours": hours,
                "hours_display": money_format(hours),
                "rate": rate,
                "rate_display": money_format(rate),
                "cost": cost,
                "cost_display": money_format(cost),
            }
            display_role_hours.append(role_row)
            detail_rows.append({"phase": phase, **role_row})

        phase_rows.append({
            "phase": phase,
            "role_hours": display_role_hours,
            "total": phase_total,
            "total_display": money_format(phase_total),
        })

    total_rows: list[dict[str, Any]] = []
    grand_total_hours = 0.0
    grand_total_cost = 0.0
    for role in roles:
        hours = total_hours_by_role.get(role, 0.0)
        rate = rate_by_role.get(role, 100.0)
        cost = hours * rate
        grand_total_hours += hours
        grand_total_cost += cost
        total_rows.append({
            "role": role,
            "count": count_by_role.get(role, 0),
            "hours": hours,
            "hours_display": money_format(hours),
            "rate": rate,
            "rate_display": money_format(rate),
            "cost": cost,
            "cost_display": money_format(cost),
        })

    return {
        "roles": roles,
        "phase_rows": phase_rows,
        "detail_rows": detail_rows,
        "total_rows": total_rows,
        "grand_total_hours": grand_total_hours,
        "grand_total_hours_display": money_format(grand_total_hours),
        "grand_total_cost": grand_total_cost,
        "grand_total_cost_display": money_format(grand_total_cost),
    }


def _totals_row(data: Any) -> dict[str, str]:
    """Render a TotalsRow-like dict as {sa, eng, other, total} strings."""
    if not isinstance(data, dict):
        return {"sa": "", "eng": "", "other": "", "total": ""}
    return {
        "sa": str(data.get("sa", "")),
        "eng": str(data.get("eng", "")),
        "other": str(data.get("other", "")),
        "total": str(data.get("total", "")),
    }


def _cost_breakdown_table_rows(table: Any) -> list[dict[str, Any]]:
    """Render breakdown_table as list of {category, mrr, arr, note}."""
    rows: list[dict[str, Any]] = []
    if not isinstance(table, list):
        return rows

    for entry in table:
        data = _as_mapping(entry)
        if not data:
            continue
        rows.append({
            "category": resolve_field_value(data.get("category", "")),
            "mrr": resolve_field_value(data.get("mrr", "")),
            "arr": resolve_field_value(data.get("arr", "")),
            "note": resolve_field_value(data.get("note", "")),
        })
    return rows


# ---------------------------------------------------------------------------
# Funding context — v2: reads from cost_breakdown.arr, resources_cost_estimates.total_cost
# ---------------------------------------------------------------------------

def _funding_context(
    cost_breakdown: dict[str, Any],
    resources_cost_estimates: dict[str, Any],
    architecture_services: list[dict[str, Any]],
) -> dict[str, Any]:
    funding_calculation = _section(cost_breakdown, "funding_calculation")

    # v2: read ARR directly from cost_breakdown.arr
    annual_aws_arr_num = _safe_float(cost_breakdown.get("arr", {}), 0.0)
    if annual_aws_arr_num <= 0:
        # fallback to funding_calculation.yr1_arr
        annual_aws_arr_num = _safe_float(funding_calculation.get("yr1_arr", ""), 0.0)

    sow_cost = resolve_field_value(funding_calculation.get("sow_cost", ""), "")
    eligible_amount = resolve_field_value(funding_calculation.get("eligible_amount", ""), "")

    if sow_cost in ("", None):
        # v2: read total_cost from resources_cost_estimates instead of staffing_plan
        total_cost_data = resources_cost_estimates.get("total_cost", {})
        if isinstance(total_cost_data, dict):
            sow_cost = _safe_float(total_cost_data.get("total", 0), 0.0)
        else:
            sow_cost = _safe_float(total_cost_data, 0.0)
        if annual_aws_arr_num > 0:
            sow_cost = round(sow_cost + annual_aws_arr_num, 2)

    sow_cost_num = _safe_float(sow_cost, 0.0)
    eligible_amount_num = _safe_float(eligible_amount, 0.0)

    if eligible_amount_num <= 0:
        if annual_aws_arr_num > 0 and sow_cost_num > 0:
            eligible_amount_num = min(annual_aws_arr_num * 0.25, sow_cost_num, 125000)
        else:
            eligible_amount_num = 0.0

    bedrock_present = _bedrock_present(architecture_services)

    return {
        "yr1_arr": money_format(annual_aws_arr_num),
        "sow_cost": money_format(sow_cost_num),
        "eligible_amount": money_format(eligible_amount_num),
        "funding_eligible": bool_status(eligible_amount_num > 0, "Eligible", "Not eligible"),
        "bedrock_status": bool_status(bedrock_present, "Included", "Missing"),
        "bedrock_present": bedrock_present,
    }


# ---------------------------------------------------------------------------
# Context builder — v2
# ---------------------------------------------------------------------------

def _build_context(params: dict[str, Any]) -> dict[str, Any]:
    """Build the template render context from a v2 DocumentState dict.

    Reads from v2 schema paths only. No legacy fallbacks.
    """
    if not params:
        params = {}

    meta = params.get("meta", {}) if isinstance(params.get("meta", {}), dict) else {}
    sections = params.get("sections", {}) if isinstance(params.get("sections", {}), dict) else {}

    cover = _section(sections, "cover")
    executive_summary = _section(sections, "executive_summary")
    scope_of_work = _section(sections, "scope_of_work")
    success_criteria = _section(sections, "success_criteria")
    assumptions = _section(sections, "assumptions")
    architecture = _section(sections, "architecture")
    milestones = _section(sections, "milestones")
    cost_breakdown = _section(sections, "cost_breakdown")
    acceptance = _section(sections, "acceptance")
    resources_cost_estimates = _section(sections, "resources_cost_estimates")
    stakeholders = _section(sections, "stakeholders")

    # --- Contribution ---
    contribution_context = _build_contribution(resources_cost_estimates)

    # --- Architecture ---
    architecture_services = _architecture_service_rows(architecture)

    # --- Funding (v2: reads from cost_breakdown.arr and resources_cost_estimates.total_cost) ---
    funding = _funding_context(cost_breakdown, resources_cost_estimates, architecture_services)

    # --- Stakeholders ---
    executive_sponsors = stakeholders.get("executive_sponsors", [])
    stakeholder_rows = stakeholders.get("stakeholders", [])
    project_team = stakeholders.get("project_team", [])
    escalation_contacts = stakeholders.get("escalation_contacts", [])
    if not isinstance(executive_sponsors, list):
        executive_sponsors = []
    if not isinstance(stakeholder_rows, list):
        stakeholder_rows = []
    if not isinstance(project_team, list):
        project_team = []
    if not isinstance(escalation_contacts, list):
        escalation_contacts = []

    # --- Milestones ---
    milestones_rows = milestones.get("phases", [])
    if not isinstance(milestones_rows, list):
        milestones_rows = []

    # --- Executive Summary (Phase 1: group model rendered through existing template blocks) ---
    executive_summary_groups = _group_rows(executive_summary.get("groups", []))
    customer_intro = ""
    problem_statement = ""
    proposed_solution = ""
    phases_overview: list[str] = []
    current_pain_points: list[str] = []
    poc_objectives: list[str] = []
    custom_blocks = [
        {
            "heading": group["category_name"],
            "content": "",
            "bullets": group["bullets"],
            "bullets_structured": group.get("bullets_structured", []),
        }
        for group in executive_summary_groups
    ]

    business_case_problem = ""
    business_case_roi = ""
    business_case_sponsor = ""
    business_case_commitment = ""

    # --- Success Criteria / Assumptions (v2: bullets not items) ---
    success_criteria_groups = _group_rows(success_criteria.get("groups", []))
    success_criteria_items = _resolve_list(success_criteria.get("items", []))
    assumptions_groups = _group_rows(assumptions.get("groups", []))
    assumptions_items = _resolve_list(assumptions.get("items", []))

    # --- Scope of Work (v2: tasks, out_of_scope, items) ---
    scope_tasks = _scope_task_rows(scope_of_work.get("tasks", []))
    scope_out_of_scope = _resolve_list(scope_of_work.get("out_of_scope", []))
    scope_items = _resolve_list(scope_of_work.get("items", []))

    # --- Architecture diagram (v2: diagram_image_s3_key → architecture_diagram_image) ---
    architecture_diagram_image = resolve_field_value(architecture.get("diagram_image_s3_key", ""))
    if not isinstance(architecture_diagram_image, str):
        architecture_diagram_image = ""

    # --- Architecture tools_list (v2: list[FieldValue] → resolved list) ---
    architecture_tools_list = _resolve_list(architecture.get("tools_list", []))

    # --- Acceptance (v2: steps → acceptance_steps) ---
    acceptance_steps = _acceptance_step_rows(acceptance.get("steps", []))

    # --- Resources & Cost Estimates (v2: staffing data from resources_cost_estimates) ---
    partner_technical_team = _partner_team_rows(project_team)
    dynamic_role_rates = _role_rate_rows(project_team, resources_cost_estimates)
    phase_hours = _phase_hours_context(resources_cost_estimates.get("phase_hours_table", []), dynamic_role_rates)

    # --- Client signatures (v2: from resources_cost_estimates) ---
    client_signature_customer_name = resolve_field_value(resources_cost_estimates.get("client_signature_customer_name", ""))
    client_signature_person_name = resolve_field_value(resources_cost_estimates.get("client_signature_person_name", ""))
    client_signature_designation = resolve_field_value(resources_cost_estimates.get("client_signature_designation", ""))
    client_signature_date = resolve_field_value(resources_cost_estimates.get("client_signature_date", ""))

    # --- Cost breakdown (v2: flat schema names → aws_ prefixed context keys) ---
    aws_calculator_url = resolve_field_value(cost_breakdown.get("calculator_url", ""))
    aws_mrr = resolve_field_value(cost_breakdown.get("mrr", ""))
    aws_arr = resolve_field_value(cost_breakdown.get("arr", ""))
    aws_cost_breakdown_table = _cost_breakdown_table_rows(cost_breakdown.get("breakdown_table", []))
    aws_bedrock_extra = resolve_field_value(cost_breakdown.get("bedrock_extra", ""))

    return {
        # --- Document meta ---
        "doc_id": params.get("doc_id", "unknown"),
        "version": params.get("version", 0),
        "customer": _resolve_field(meta.get("customer", cover.get("customer", ""))),
        "partner": _resolve_field(meta.get("partner", cover.get("partner", ""))),
        "date": _resolve_field(meta.get("date", cover.get("date", ""))),
        "cover": {key: _resolve_field(value) for key, value in cover.items()},

        # --- Executive Summary ---
        "customer_intro": customer_intro,
        "problem_statement": problem_statement,
        "proposed_solution": proposed_solution,
        "phases_overview": phases_overview,
        "current_pain_points": current_pain_points,
        "poc_objectives": poc_objectives,
        "custom_blocks": custom_blocks,
        "executive_summary_groups": executive_summary_groups,

        # --- Business Case (flattened from nested) ---
        "business_case_problem": business_case_problem,
        "business_case_roi": business_case_roi,
        "business_case_sponsor": business_case_sponsor,
        "business_case_commitment": business_case_commitment,

        # --- Success Criteria ---
        "success_criteria_groups": success_criteria_groups,
        "success_criteria_items": success_criteria_items,

        # --- Assumptions ---
        "assumptions_groups": assumptions_groups,
        "assumptions_items": assumptions_items,

        # --- Scope of Work ---
        "scope_tasks": scope_tasks,
        "scope_out_of_scope": scope_out_of_scope,
        "scope_items": scope_items,

        # --- Architecture ---
        "architecture_overview": resolve_field_value(architecture.get("overview", "")),
        "architecture_diagram_image": architecture_diagram_image,
        "architecture_services": architecture_services,
        "architecture_tools_list": architecture_tools_list,

        # --- Stakeholders ---
        "executive_sponsors": [_normalize_contact_entry(row, "description") for row in executive_sponsors],
        "stakeholders": [_normalize_contact_entry(row, "stakeholder_for") for row in stakeholder_rows],
        "project_team": [_normalize_contact_entry(row, "role") for row in project_team],
        "escalation_contacts": [_normalize_contact_entry(row, "role") for row in escalation_contacts],

        # --- Milestones ---
        "milestones": [
            {
                "phase": _resolve_field(row.get("phase", "")),
                "completion_date": _resolve_field(row.get("completion_date", "")),
                "deliverables": _flatten_structured_bullets(row.get("deliverables", [])),
            }
            for row in milestones_rows
            if isinstance(row, dict)
        ],

        # --- AWS Cost Breakdown (v2: schema names → aws_ prefixed) ---
        "aws_calculator_url": aws_calculator_url,
        "aws_mrr": aws_mrr,
        "aws_arr": aws_arr,
        "aws_cost_breakdown_table": aws_cost_breakdown_table,
        "aws_bedrock_extra": aws_bedrock_extra,

        # --- Acceptance ---
        "acceptance_steps": acceptance_steps,

        # --- Resources & Cost Estimates ---
        "partner_technical_team": partner_technical_team,
        "role_rates": dynamic_role_rates,
        "phase_hours": phase_hours,
        "phase_hours_table": phase_hours["phase_rows"],
        "phase_hours_rows": phase_hours["detail_rows"],
        "phase_hours_totals": phase_hours["total_rows"],
        "grand_total_hours": phase_hours["grand_total_hours_display"],
        "grand_total_cost": phase_hours["grand_total_cost_display"],

        # --- Contribution ---
        "contribution": contribution_context["parties"],

        # --- Client Signatures (v2: from resources_cost_estimates) ---
        "client_signature_customer_name": client_signature_customer_name,
        "client_signature_person_name": client_signature_person_name,
        "client_signature_designation": client_signature_designation,
        "client_signature_date": client_signature_date,

        # --- Funding ---
        "yr1_arr": funding["yr1_arr"],
        "sow_cost": funding["sow_cost"],
        "eligible_amount": funding["eligible_amount"],
        "funding_eligible": funding["funding_eligible"],
        "bedrock_status": funding["bedrock_status"],
        "funding": funding,
    }


def _download_template(s3: Any, bucket: str, template_key: str) -> bytes:
    obj = s3.get_object(Bucket=bucket, Key=template_key)
    body = obj["Body"]
    return body.read() if hasattr(body, "read") else body


def _paragraph_text(paragraph: ET.Element) -> str:
    parts: list[str] = []
    for node in paragraph.iter():
        if node.tag == f"{W}t":
            parts.append(node.text or "")
        elif node.tag == f"{W}br":
            parts.append("\n")
    return "".join(parts)


def _set_paragraph_text(paragraph: ET.Element, text: str) -> None:
    ppr = paragraph.find(f"{W}pPr")
    paragraph.clear()
    if ppr is not None:
        paragraph.append(deepcopy(ppr))
    run = ET.SubElement(paragraph, f"{W}r")
    text_node = ET.SubElement(run, f"{W}t")
    text_node.text = text


def _set_bullet_level(paragraph: ET.Element, level: int) -> None:
    ppr = paragraph.find(f"{W}pPr")
    if ppr is None:
        ppr = ET.Element(f"{W}pPr")
        paragraph.insert(0, ppr)
    num_pr = ppr.find(f"{W}numPr")
    if num_pr is None:
        num_pr = ET.SubElement(ppr, f"{W}numPr")

    ilvl = num_pr.find(f"{W}ilvl")
    if ilvl is None:
        ilvl = ET.SubElement(num_pr, f"{W}ilvl")
    ilvl.set(f"{W}val", "1" if level == 2 else "0")

    num_id = num_pr.find(f"{W}numId")
    if num_id is None:
        num_id = ET.SubElement(num_pr, f"{W}numId")
    # Template numbering numId=5 has level 0 as "•" and level 1 as "o".
    num_id.set(f"{W}val", "5")


def _structured_bullet_lines(text: str) -> list[tuple[int, str]] | None:
    if STRUCTURED_BULLET_L1 not in text and STRUCTURED_BULLET_L2 not in text:
        return None
    lines: list[tuple[int, str]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(STRUCTURED_BULLET_L2):
            lines.append((2, line.removeprefix(STRUCTURED_BULLET_L2).strip()))
        elif line.startswith(STRUCTURED_BULLET_L1):
            lines.append((1, line.removeprefix(STRUCTURED_BULLET_L1).strip()))
    return lines or None


def _postprocess_structured_bullets(docx_bytes: bytes) -> bytes:
    ET.register_namespace("w", WORD_NS)
    with zipfile.ZipFile(io.BytesIO(docx_bytes), "r") as zin:
        files = {name: zin.read(name) for name in zin.namelist()}

    document_xml = "word/document.xml"
    root = ET.fromstring(files[document_xml])
    parent_by_child = {child: parent for parent in root.iter() for child in list(parent)}

    for paragraph in list(root.iter(f"{W}p")):
        lines = _structured_bullet_lines(_paragraph_text(paragraph))
        if not lines:
            continue
        parent = parent_by_child.get(paragraph)
        if parent is None:
            continue
        parent_children = list(parent)
        index = parent_children.index(paragraph)
        parent.remove(paragraph)
        for offset, (level, text) in enumerate(lines):
            new_paragraph = deepcopy(paragraph)
            _set_paragraph_text(new_paragraph, text)
            _set_bullet_level(new_paragraph, level)
            parent.insert(index + offset, new_paragraph)

    files[document_xml] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in files.items():
            zout.writestr(name, data)
    return output.getvalue()


def _render_docx(template_bytes: bytes, context: dict[str, Any]) -> bytes:
    from docxtpl import DocxTemplate

    with tempfile.NamedTemporaryFile(suffix=".docx") as template_file:
        template_file.write(template_bytes)
        template_file.flush()

        doc = DocxTemplate(template_file.name)
        doc.render(context)

        output = io.BytesIO()
        doc.save(output)
        return _postprocess_structured_bullets(output.getvalue())


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point for export_docx."""
    try:
        raw = event.get("inputPayload", "{}")
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        params = json.loads(raw)
    except Exception as exc:
        return _error("parse_input", exc)

    doc_id = params.get("doc_id", "unknown")
    version = params.get("version", 0)
    s3_key = f"docs/{doc_id}/exports/{doc_id}-v{version}.docx"

    try:
        s3 = boto3.client("s3", region_name=REGION)
        template_bytes = _download_template(s3, ARTIFACTS_BUCKET, TEMPLATE_S3_KEY)
    except Exception as exc:
        return _error("download_template", exc)

    try:
        render_context = _build_context(params)
        docx_bytes = _render_docx(template_bytes, render_context)
    except Exception as exc:
        return _error("render_docx", exc)

    try:
        s3.put_object(
            Bucket=ARTIFACTS_BUCKET,
            Key=s3_key,
            Body=docx_bytes,
            ContentType=DOCX_CONTENT_TYPE,
        )
    except Exception as exc:
        return _error("upload_docx", exc)

    try:
        download_url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": ARTIFACTS_BUCKET, "Key": s3_key},
            ExpiresIn=3600,
        )
    except Exception:
        download_url = None

    return _response({
        "s3_key": s3_key,
        "bucket": ARTIFACTS_BUCKET,
        "download_url": download_url,
    })
