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

    return {
        "doc_id": params.get("doc_id", "unknown"),
        "version": params.get("version", 0),
        "customer": _resolve_field(meta.get("customer", cover.get("customer", ""))),
        "partner": _resolve_field(meta.get("partner", cover.get("partner", ""))),
        "date": _resolve_field(meta.get("date", cover.get("date", ""))),
        "cover": {key: _resolve_field(value) for key, value in cover.items()},
        "executive_summary": {
            "text": _resolve_field(executive_summary.get("text", executive_summary.get("summary", ""))),
            "summary": _resolve_field(executive_summary.get("summary", executive_summary.get("text", ""))),
        },
        "scope_of_work": {
            "items": _bullet_join(scope_of_work.get("items", "")),
            "in_scope": _bullet_join(scope_of_work.get("in_scope", "")),
            "out_of_scope": _bullet_join(scope_of_work.get("out_of_scope", "")),
            "deliverables": _bullet_join(scope_of_work.get("deliverables", "")),
        },
        "success_criteria": {
            "items": _bullet_join(success_criteria.get("items", "")),
            **{key: _resolve_field(value) for key, value in success_criteria.items() if key != "items"},
        },
        "assumptions": {
            "items": _bullet_join(assumptions.get("items", "")),
            "risks": _bullet_join(assumptions.get("risks", "")),
            "dependencies": _bullet_join(assumptions.get("dependencies", "")),
        },
        "architecture": {
            "description": _resolve_field(architecture.get("description", "")),
            "services": _bullet_join(architecture.get("services", "")),
            "data_flow": _resolve_field(architecture.get("data_flow", "")),
            "tools": _bullet_join(architecture.get("tools", "")),
        },
        "milestones": {
            "phases": milestones.get("phases", []),
            **{key: _resolve_field(value) for key, value in milestones.items() if key != "phases"},
        },
        "cost_breakdown": cost_breakdown,
        "acceptance": {
            "text": _resolve_field(acceptance.get("text", "")),
            **{key: _resolve_field(value) for key, value in acceptance.items() if key != "text"},
        },
        "resources_cost_estimates": {
            **resources_cost_estimates,
            "contribution": _build_contribution(resources_cost_estimates),
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
