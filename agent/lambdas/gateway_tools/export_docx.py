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


def _resolve_field(field: Any, default: Any = "") -> Any:
    """Resolve a Document_State FieldValue to its display value."""
    if isinstance(field, dict) and any(k in field for k in ("user_input", "ai_recommended", "calculated")):
        for key in ("user_input", "ai_recommended", "calculated"):
            value = field.get(key)
            if value is not None and value != "":
                return value
        return default
    if field is None:
        return default
    return field


def _bullet_join(value: Any) -> str:
    """Render a list-like value as newline-separated bullets."""
    resolved = _resolve_field(value)
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
        item_value = _resolve_field(item)
        if isinstance(item_value, dict):
            item_value = " / ".join(str(_resolve_field(v)) for v in item_value.values() if _resolve_field(v) not in ("", None))
        if item_value not in ("", None):
            bullets.append(f"- {item_value}")
    return "\n".join(bullets)


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
    staffing_summary = _build_staffing_totals(staffing_plan)
    contribution_context = _build_contribution(resources_cost_estimates)
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

    return {
        "doc_id": params.get("doc_id", "unknown"),
        "version": params.get("version", 0),
        "customer": _resolve_field(meta.get("customer", cover.get("customer", ""))),
        "partner": _resolve_field(meta.get("partner", cover.get("partner", ""))),
        "date": _resolve_field(meta.get("date", cover.get("date", ""))),
        "cover": {key: _resolve_field(value) for key, value in cover.items()},
        "executive_summary": _resolve_field(executive_summary.get("text", executive_summary.get("summary", ""))),
        "scope_of_work": _bullet_join(scope_of_work.get("items", scope_of_work.get("deliverables", ""))),
        "success_criteria": _bullet_join(success_criteria.get("items", "")),
        "assumptions": _bullet_join(assumptions.get("items", assumptions.get("risks", assumptions.get("dependencies", "")))),
        "architecture_description": _resolve_field(architecture.get("description", "")),
        "architecture_tools": _bullet_join(architecture.get("tools", "")),
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
