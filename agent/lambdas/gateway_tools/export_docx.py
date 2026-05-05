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
from typing import Any

import boto3


ARTIFACTS_BUCKET = os.environ.get("ARTIFACTS_BUCKET") or os.environ.get("S3_BUCKET", "doc-agent-artifacts")
TEMPLATE_S3_KEY = os.environ.get("TEMPLATE_S3_KEY", "templates/apn-poc-template_v2.docx")
REGION = os.environ.get("AWS_REGION", "ap-northeast-2")
DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


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
        prefix = "o " if item["level"] == 2 else "• "
        lines.append(f"{prefix}{item['text']}")
    return "\n".join(lines)


def _template_bullet_text(item: dict[str, Any]) -> str:
    """Text for template paragraphs that already carry Word bullet formatting."""
    return f"o {item['text']}" if item["level"] == 2 else str(item["text"])


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
    """Render partner_technical_team as list of {role, name}."""
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
        })
    return rows


def _role_rate_value(resources_cost_estimates: dict[str, Any], role: str) -> Any:
    for row in resources_cost_estimates.get("role_rates", []) if isinstance(resources_cost_estimates.get("role_rates", []), list) else []:
        data = _as_mapping(row)
        if data.get("role") == role:
            return resolve_field_value(data.get("rate", {}), 100)
    return 100


def _role_rate_rows(project_team: Any, resources_cost_estimates: dict[str, Any]) -> list[dict[str, Any]]:
    team_rows = _partner_team_rows(project_team)
    rates = resources_cost_estimates.get("role_rates", [])
    if not isinstance(rates, list):
        rates = []

    rate_by_role: dict[str, Any] = {}
    for row in rates:
        data = _as_mapping(row)
        role = str(data.get("role", "")).strip()
        if role:
            rate_by_role[role] = resolve_field_value(data.get("rate", {}), 100)

    grouped: dict[str, dict[str, Any]] = {}
    for member in team_rows:
        role = str(member.get("role", "")).strip() or "Unassigned"
        entry = grouped.setdefault(role, {"role": role, "count": 0, "members": [], "rate": rate_by_role.get(role, 100)})
        entry["count"] += 1
        name = str(member.get("name", "")).strip()
        if name:
            entry["members"].append(name)

    return [
        {**row, "members": ", ".join(row["members"])}
        for row in grouped.values()
    ]


def _phase_hours_rows(table: Any) -> list[dict[str, Any]]:
    """Render phase_hours_table as list of {phase, sa_hours, eng_hours, other_hours, total}."""
    rows: list[dict[str, Any]] = []
    if not isinstance(table, list):
        return rows

    for entry in table:
        data = _as_mapping(entry)
        if not data:
            continue
        rows.append({
            "phase": resolve_field_value(data.get("phase", "")),
            "sa_hours": _safe_int(data.get("sa_hours", 0), 0),
            "eng_hours": _safe_int(data.get("eng_hours", 0), 0),
            "other_hours": _safe_int(data.get("other_hours", 0), 0),
            "total": _safe_int(data.get("total", 0), 0),
        })
    return rows


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
    phase_hours_table = _phase_hours_rows(resources_cost_estimates.get("phase_hours_table", []))
    total_hours = _totals_row(resources_cost_estimates.get("total_hours", {}))
    total_cost = _totals_row(resources_cost_estimates.get("total_cost", {}))

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
        "executive_summary": "\n".join(
            f"{group['category_name']}\n{group['bullets_text']}"
            for group in executive_summary_groups
            if group.get("category_name") or group.get("bullets_text")
        ),

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
        "rate_solution_architect": _role_rate_value(resources_cost_estimates, "SA"),
        "rate_engineer": _role_rate_value(resources_cost_estimates, "AI Service Engineer"),
        "rate_other": 100,
        "phase_hours_table": phase_hours_table,
        "total_hours": total_hours,
        "total_cost": total_cost,

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


def _render_docx(template_bytes: bytes, context: dict[str, Any]) -> bytes:
    from docxtpl import DocxTemplate

    with tempfile.NamedTemporaryFile(suffix=".docx") as template_file:
        template_file.write(template_bytes)
        template_file.flush()

        doc = DocxTemplate(template_file.name)
        doc.render(context)

        output = io.BytesIO()
        doc.save(output)
        return output.getvalue()


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
