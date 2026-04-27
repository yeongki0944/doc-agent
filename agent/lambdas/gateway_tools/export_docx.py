"""Gateway Lambda: export_docx.

Downloads the APN PoC DOCX template from S3, renders it with docxtpl using
Document_State data, uploads the rendered DOCX to S3, and returns a download URL.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
from typing import Any

import boto3


ARTIFACTS_BUCKET = os.environ.get("ARTIFACTS_BUCKET") or os.environ.get("S3_BUCKET", "doc-agent-artifacts")
TEMPLATE_S3_KEY = os.environ.get("TEMPLATE_S3_KEY", "templates/apn-poc-template.docx")
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


def _phase_hours(role: dict[str, Any], phase: str) -> Any:
    return _resolve_field(role.get("phase_hours", {}).get(phase, {}), 0)


def _build_staffing_context(staffing_plan: dict[str, Any]) -> dict[str, Any]:
    roles = staffing_plan.get("roles", {})
    if not isinstance(roles, dict):
        roles = {}

    role_rows: list[dict[str, Any]] = []
    for role_id, role in roles.items():
        if not isinstance(role, dict):
            continue
        role_rows.append({
            "role_id": role.get("role_id") or role_id,
            "display_name": role.get("display_name") or role_id,
            "count": _resolve_field(role.get("count", {}), 0),
            "allocation_pct": _resolve_field(role.get("allocation_pct", {}), 0),
            "rate_per_hour": _resolve_field(role.get("rate_per_hour", {}), 0),
            "discovery_hours": _phase_hours(role, "discovery"),
            "development_hours": _phase_hours(role, "development"),
            "testing_hours": _phase_hours(role, "testing"),
            "total_hours": _resolve_field(role.get("total_hours", {}), 0),
            "total_cost": _resolve_field(role.get("total_cost", {}), 0),
            "reason": role.get("reason", ""),
        })

    return {
        "roles": role_rows,
        "grand_total_hours": _resolve_field(staffing_plan.get("grand_total_hours", {}), 0),
        "grand_total_cost": _resolve_field(staffing_plan.get("grand_total_cost", {}), 0),
    }


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


def _group_rows(groups: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not isinstance(groups, list):
        return rows

    for group in groups:
        data = _as_mapping(group)
        if not data:
            continue
        items = data.get("items", data.get("values", data.get("details", [])))
        rows.append({
            "category_name": resolve_field_value(data.get("category_name", data.get("name", ""))),
            "items_text": _bullet_join(items),
            "items": items if isinstance(items, list) else ([items] if items not in ("", None) else []),
        })
    return rows


def _scope_task_rows(tasks: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not isinstance(tasks, list):
        return rows

    for task in tasks:
        data = _as_mapping(task)
        if not data:
            continue
        details = data.get("details", data.get("items", []))
        rows.append({
            "task_category": resolve_field_value(data.get("task_category", data.get("category", ""))),
            "schedule": resolve_field_value(data.get("schedule", "")),
            "details_text": _bullet_join(details),
            "details": details if isinstance(details, list) else ([details] if details not in ("", None) else []),
            "personnel": resolve_field_value(data.get("personnel", "")),
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


def _funding_context(
    cost_breakdown: dict[str, Any],
    staffing_summary: dict[str, Any],
    architecture_services: list[dict[str, Any]],
) -> dict[str, Any]:
    funding_calculation = _section(cost_breakdown, "funding_calculation")
    monthly_aws_cost_num = _safe_float(_section(cost_breakdown, "aws_service_cost").get("monthly_cost_summary", {}), 0.0)
    annual_aws_arr_num = _safe_float(funding_calculation.get("yr1_arr", ""), 0.0)
    if annual_aws_arr_num <= 0 and monthly_aws_cost_num > 0:
        annual_aws_arr_num = round(monthly_aws_cost_num * 12, 2)

    sow_cost = resolve_field_value(funding_calculation.get("sow_cost", ""), "")
    eligible_amount = resolve_field_value(funding_calculation.get("eligible_amount", ""), "")

    if sow_cost in ("", None):
        sow_cost = _safe_float(staffing_summary.get("total_cost", {}).get("total", 0), 0.0)
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


def _signature_context(sections: dict[str, Any]) -> dict[str, Any]:
    client_signatures = _section(sections, "client_signatures")
    return {
        "signature_customer_name": resolve_field_value(client_signatures.get("customer_name", "")),
        "signature_person_name": resolve_field_value(client_signatures.get("authorized_person_name", "")),
        "signature_designation": resolve_field_value(client_signatures.get("designation", "")),
        "signature_date": resolve_field_value(client_signatures.get("sign_date", "")),
    }


def _normalize_contact_entry(entry: Any, label_key: str, fallback_value: str = "") -> dict[str, Any]:
    if not isinstance(entry, dict):
        entry = {}

    label_value = _resolve_field(
        entry.get(label_key, entry.get("role_or_description", entry.get("description", entry.get("stakeholder_for", "")))),
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


def _role_category_key(role: dict[str, Any]) -> str:
    category = role.get("category", "other")
    if hasattr(category, "value"):
        category = category.value
    category = str(category)
    if category == "solution_architect":
        return "sa"
    if category == "engineer":
        return "eng"
    return "other"


def _build_phase_hours_table(staffing_plan: dict[str, Any]) -> list[dict[str, Any]]:
    roles = staffing_plan.get("roles", {})
    if not isinstance(roles, dict):
        roles = {}

    phase_names: list[str] = []
    seen: set[str] = set()
    for role in roles.values():
        if not isinstance(role, dict):
            continue
        phase_hours = role.get("phase_hours", {})
        if not isinstance(phase_hours, dict):
            continue
        for phase in phase_hours.keys():
            if phase not in seen:
                seen.add(phase)
                phase_names.append(phase)

    preferred_order = ["discovery", "development", "testing"]
    ordered = [phase for phase in preferred_order if phase in seen]
    ordered.extend([phase for phase in phase_names if phase not in preferred_order])

    phase_rows: list[dict[str, Any]] = []
    for phase in ordered:
        sa_hours = 0
        eng_hours = 0
        other_hours = 0
        for role in roles.values():
            if not isinstance(role, dict):
                continue
            phase_hours = role.get("phase_hours", {})
            if not isinstance(phase_hours, dict):
                continue
            hours = _resolve_field(phase_hours.get(phase, {}), 0)
            category_key = _role_category_key(role)
            if category_key == "sa":
                sa_hours += hours
            elif category_key == "eng":
                eng_hours += hours
            else:
                other_hours += hours
        phase_rows.append({
            "phase": phase,
            "sa_hours": sa_hours,
            "eng_hours": eng_hours,
            "other_hours": other_hours,
            "total": sa_hours + eng_hours + other_hours,
        })

    return phase_rows


def _build_staffing_totals(staffing_plan: dict[str, Any]) -> dict[str, Any]:
    roles = staffing_plan.get("roles", {})
    if not isinstance(roles, dict):
        roles = {}

    totals = {
        "sa": {"hours": 0, "cost": 0},
        "eng": {"hours": 0, "cost": 0},
        "other": {"hours": 0, "cost": 0},
    }

    for role in roles.values():
        if not isinstance(role, dict):
            continue
        category_key = _role_category_key(role)
        totals[category_key]["hours"] += _resolve_field(role.get("total_hours", {}), 0)
        totals[category_key]["cost"] += _resolve_field(role.get("total_cost", {}), 0)

    total_hours = {
        "sa": totals["sa"]["hours"],
        "eng": totals["eng"]["hours"],
        "other": totals["other"]["hours"],
        "total": totals["sa"]["hours"] + totals["eng"]["hours"] + totals["other"]["hours"],
    }
    total_cost = {
        "sa": totals["sa"]["cost"],
        "eng": totals["eng"]["cost"],
        "other": totals["other"]["cost"],
        "total": totals["sa"]["cost"] + totals["eng"]["cost"] + totals["other"]["cost"],
    }

    def _rate(category: str) -> float:
        hours = totals[category]["hours"]
        cost = totals[category]["cost"]
        if hours:
            return round(cost / hours, 2)
        return 0

    return {
        "total_hours": total_hours,
        "total_cost": total_cost,
        "rates": {
            "rate_solution_architect": _rate("sa"),
            "rate_engineer": _rate("eng"),
            "rate_other": _rate("other"),
        },
        "phase_hours_table": _build_phase_hours_table(staffing_plan),
    }


def _build_context(params: dict[str, Any]) -> dict[str, Any]:
    meta = params.get("meta", {}) if isinstance(params.get("meta", {}), dict) else {}
    sections = params.get("sections", {}) if isinstance(params.get("sections", {}), dict) else {}
    staffing_plan = params.get("staffing_plan", {}) if isinstance(params.get("staffing_plan", {}), dict) else {}

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
    client_signatures = _section(sections, "client_signatures")
    staffing_summary = _build_staffing_totals(staffing_plan)
    contribution_context = _build_contribution(resources_cost_estimates)

    architecture_services = _architecture_service_rows(architecture)
    funding_context = _funding_context(cost_breakdown, staffing_summary, architecture_services)
    signature_context = _signature_context(sections)

    executive_sponsors = stakeholders.get("executive_sponsors", [])
    stakeholder_rows = stakeholders.get("stakeholders", [])
    project_team = stakeholders.get("project_team", [])
    escalation_contacts = stakeholders.get("escalation_contacts", [])
    milestones_rows = milestones.get("phases", [])
    if not isinstance(executive_sponsors, list):
        executive_sponsors = []
    if not isinstance(stakeholder_rows, list):
        stakeholder_rows = []
    if not isinstance(project_team, list):
        project_team = []
    if not isinstance(escalation_contacts, list):
        escalation_contacts = []
    if not isinstance(milestones_rows, list):
        milestones_rows = []

    executive_summary_text = resolve_field_value(executive_summary.get("text", executive_summary.get("summary", "")))
    customer_intro = resolve_field_value(executive_summary.get("customer_intro", ""))
    problem_statement = resolve_field_value(executive_summary.get("problem_statement", ""))
    proposed_solution = resolve_field_value(executive_summary.get("proposed_solution", ""))
    phases_overview = executive_summary.get("phases_overview", [])
    if not isinstance(phases_overview, list):
        phases_overview = []
    business_case = _section(executive_summary, "business_case")
    business_case_problem = resolve_field_value(business_case.get("problem_definition", ""))
    business_case_roi = resolve_field_value(business_case.get("roi_calculation", ""))
    business_case_sponsor = resolve_field_value(business_case.get("executive_sponsor", ""))
    business_case_commitment = resolve_field_value(business_case.get("production_commitment", ""))

    success_criteria_groups = _group_rows(success_criteria.get("groups", []))
    if not success_criteria_groups:
        success_criteria_groups = _group_rows(success_criteria.get("items", []))
    assumptions_groups = _group_rows(assumptions.get("groups", []))
    if not assumptions_groups:
        assumptions_groups = _group_rows(assumptions.get("items", []))
    scope_tasks = _scope_task_rows(scope_of_work.get("tasks", []))
    if not scope_tasks:
        scope_tasks = _scope_task_rows(scope_of_work.get("items", []))

    return {
        "doc_id": params.get("doc_id", "unknown"),
        "version": params.get("version", 0),
        "customer": _resolve_field(meta.get("customer", cover.get("customer", ""))),
        "partner": _resolve_field(meta.get("partner", cover.get("partner", ""))),
        "date": _resolve_field(meta.get("date", cover.get("date", ""))),
        "cover": {key: _resolve_field(value) for key, value in cover.items()},
        "executive_summary": executive_summary_text,
        "executive_summary_text": executive_summary_text,
        "customer_intro": customer_intro,
        "problem_statement": problem_statement,
        "proposed_solution": proposed_solution,
        "phases_overview": phases_overview,
        "business_case_problem": business_case_problem,
        "business_case_roi": business_case_roi,
        "business_case_sponsor": business_case_sponsor,
        "business_case_commitment": business_case_commitment,
        "scope_of_work": _bullet_join(scope_of_work.get("items", scope_of_work.get("deliverables", ""))),
        "success_criteria": _bullet_join(success_criteria.get("items", "")),
        "success_criteria_groups": success_criteria_groups,
        "assumptions": _bullet_join(assumptions.get("items", assumptions.get("risks", assumptions.get("dependencies", "")))),
        "assumptions_groups": assumptions_groups,
        "assumption_groups": assumptions_groups,
        "scope_tasks": scope_tasks,
        "architecture_overview": resolve_field_value(architecture.get("overview", architecture.get("description", ""))),
        "architecture_description": resolve_field_value(architecture.get("description", architecture.get("overview", ""))),
        "architecture_services": architecture_services,
        "architecture_tools": _bullet_join(architecture.get("tools", [service["service_name"] for service in architecture_services])),
        "architecture": {
            "overview": resolve_field_value(architecture.get("overview", "")),
            "description": resolve_field_value(architecture.get("description", "")),
            "services": architecture_services,
            "tools": _bullet_join(architecture.get("tools", [service["service_name"] for service in architecture_services])),
        },
        "acceptance_text": _resolve_field(acceptance.get("text", "")),
        "executive_sponsors": [_normalize_contact_entry(row, "description") for row in executive_sponsors],
        "stakeholders": [_normalize_contact_entry(row, "stakeholder_for") for row in stakeholder_rows],
        "project_team": [_normalize_contact_entry(row, "role") for row in project_team],
        "escalation_contacts": [_normalize_contact_entry(row, "role") for row in escalation_contacts],
        "milestones": [
            {
                "phase": _resolve_field(row.get("phase", "")),
                "completion_date": _resolve_field(row.get("completion_date", "")),
                "deliverables": _resolve_field(row.get("deliverables", "")),
            }
            for row in milestones_rows
            if isinstance(row, dict)
        ],
        "phase_hours_table": staffing_summary["phase_hours_table"],
        "total_hours": staffing_summary["total_hours"],
        "total_cost": staffing_summary["total_cost"],
        **staffing_summary["rates"],
        "yr1_arr": funding_context["yr1_arr"],
        "sow_cost": funding_context["sow_cost"],
        "eligible_amount": funding_context["eligible_amount"],
        "funding_eligible": funding_context["funding_eligible"],
        "bedrock_status": funding_context["bedrock_status"],
        "funding": funding_context,
        "aws_monthly_cost_summary": _resolve_field(cost_breakdown.get("aws_service_cost", {}).get("monthly_cost_summary", {}), 0),
        "aws_calculator_url": _resolve_field(cost_breakdown.get("aws_service_cost", {}).get("calculator_share_url", "")),
        "contribution": contribution_context["parties"],
        "resources_cost_estimates": {
            **resources_cost_estimates,
            "contribution": contribution_context,
        },
        "cost_breakdown": cost_breakdown,
        "acceptance": {
            "text": _resolve_field(acceptance.get("text", "")),
            **{key: _resolve_field(value) for key, value in acceptance.items() if key != "text"},
        },
        "staffing": _build_staffing_context(staffing_plan),
        "client_signatures": {
            "customer_name": signature_context["signature_customer_name"],
            "authorized_person_name": signature_context["signature_person_name"],
            "designation": signature_context["signature_designation"],
            "sign_date": signature_context["signature_date"],
            **{key: _resolve_field(value) for key, value in client_signatures.items()},
        },
        **signature_context,
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
