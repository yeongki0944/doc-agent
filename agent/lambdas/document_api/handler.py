"""Document API Lambda — CRUD, history, and runtime proxy routing."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from copy import deepcopy
from typing import Any, Optional

import boto3
from boto3.dynamodb.conditions import Attr
TABLE_NAME = os.environ.get("DOCUMENTS_TABLE", "doc-agent-documents")
HISTORY_TABLE_NAME = os.environ.get("CONVERSATION_HISTORY_TABLE", "doc-agent-conversation-history")
APPSYNC_HTTP_URL = os.environ.get("APPSYNC_HTTP_URL", "")
REGION = "ap-northeast-2"
DEFAULT_EXPORT_DOCX_FUNCTION_NAME = "doc-agent-export-docx"
AGENTCORE_RUNTIME_NAME = os.environ.get("AGENTCORE_RUNTIME_NAME", "doc_agent_runtime_demo")
AGENTCORE_RUNTIME_ARN = os.environ.get("AGENTCORE_RUNTIME_ARN", "")

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)
history_table = dynamodb.Table(HISTORY_TABLE_NAME)


class VersionConflictError(Exception):
    """Raised when a conditional DynamoDB document update loses the version race."""


class EditablePathError(ValueError):
    """Raised when a user-input path cannot be traversed safely."""

    def __init__(self, error: str, path: str, segment: str, reason: str | None = None):
        super().__init__(error)
        self.error = error
        self.path = path
        self.segment = segment
        self.reason = reason or error

    def to_response_body(self) -> dict[str, str]:
        return {
            "error": self.error,
            "path": self.path,
            "segment": self.segment,
            "reason": self.reason,
        }

# --- AgentCore Memory ---
AGENTCORE_MEMORY_ID = os.environ.get("AGENTCORE_MEMORY_ID", "")
_agentcore_client = None
_agentcore_control_client = None
_agentcore_runtime_arn = AGENTCORE_RUNTIME_ARN

def _get_agentcore_client():
    global _agentcore_client
    if _agentcore_client is None and AGENTCORE_MEMORY_ID:
        _agentcore_client = boto3.client("bedrock-agentcore", region_name=REGION)
    return _agentcore_client


def _get_agentcore_runtime_client():
    global _agentcore_client
    if _agentcore_client is None:
        _agentcore_client = boto3.client("bedrock-agentcore", region_name=REGION)
    return _agentcore_client


def _get_agentcore_control_client():
    global _agentcore_control_client
    if _agentcore_control_client is None:
        _agentcore_control_client = boto3.client("bedrock-agentcore-control", region_name=REGION)
    return _agentcore_control_client


def _resolve_agentcore_runtime_arn() -> str:
    global _agentcore_runtime_arn
    if _agentcore_runtime_arn:
        return _agentcore_runtime_arn

    client = _get_agentcore_control_client()
    resp = client.list_agent_runtimes()
    for runtime in resp.get("agentRuntimes", resp.get("agentRuntimeSummaries", [])):
        if runtime.get("agentRuntimeName") == AGENTCORE_RUNTIME_NAME:
            _agentcore_runtime_arn = runtime.get("agentRuntimeArn", "")
            if _agentcore_runtime_arn:
                return _agentcore_runtime_arn
            runtime_id = runtime.get("agentRuntimeId", "")
            if runtime_id:
                account_id = boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]
                _agentcore_runtime_arn = f"arn:aws:bedrock-agentcore:{REGION}:{account_id}:runtime/{runtime_id}"
                return _agentcore_runtime_arn
    raise RuntimeError(f"AgentCore Runtime not found: {AGENTCORE_RUNTIME_NAME}")

def _memory_store_event(session_id: str, actor_id: str, content: str, role: str = "USER") -> bool:
    """Store a conversation event in AgentCore Memory (short-term)."""
    client = _get_agentcore_client()
    if not client:
        return False
    try:
        client.create_event(
            memoryId=AGENTCORE_MEMORY_ID,
            actorId=actor_id,
            sessionId=session_id,
            eventTimestamp=datetime.now(timezone.utc),
            payload=[{"conversational": {"content": {"text": content}, "role": role}}],
        )
        return True
    except Exception as e:
        print(f"[memory] store_event failed: {e}")
        return False

def _memory_store_facts(customer: str, facts: list[str]) -> bool:
    """Store long-term facts about a customer in AgentCore Memory."""
    client = _get_agentcore_client()
    if not client or not facts:
        return False
    try:
        records = [
            {"requestIdentifier": uuid.uuid4().hex[:12], "namespaces": [f"/customers/{customer}/"], "content": {"text": f}, "timestamp": datetime.now(timezone.utc)}
            for f in facts
        ]
        client.batch_create_memory_records(memoryId=AGENTCORE_MEMORY_ID, records=records)
        return True
    except Exception as e:
        print(f"[memory] store_facts failed: {e}")
        return False

def _memory_retrieve(customer: str, query: str, top_k: int = 5) -> list[str]:
    """Retrieve relevant long-term memory for a customer."""
    client = _get_agentcore_client()
    if not client:
        return []
    try:
        resp = client.retrieve_memory_records(
            memoryId=AGENTCORE_MEMORY_ID,
            namespace=f"/customers/{customer}/",
            searchCriteria={"searchQuery": query, "topK": top_k},
        )
        return [r.get("content", {}).get("text", "") for r in resp.get("records", []) if r.get("content", {}).get("text")]
    except Exception as e:
        print(f"[memory] retrieve failed: {e}")
        return []

# --- Helpers ---

class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return int(o) if o % 1 == 0 else float(o)
        return super().default(o)


def _json(obj: Any) -> str:
    return json.dumps(obj, cls=DecimalEncoder, ensure_ascii=False)


def _response(status: int, body: Any) -> dict:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET,POST,DELETE,PUT,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type,X-User-Id,Authorization",
        },
        "body": _json(body),
    }


# ---------------------------------------------------------------------------
# Standard response envelope (hardened)
# ---------------------------------------------------------------------------
#
# Applied to NEW hardened APIs only — existing endpoints keep their current
# response shape to avoid breaking the frontend. The standard envelope adds:
#   status         — "completed" | "partial_completed" | "failed"
#   message        — short human-readable summary
#   warnings       — list of strings; present whenever degraded
#   missing_inputs — list of strings; present when inputs were insufficient
#   error_reason   — short error class/description; present only on failed
#   changed_sections / change_request_id — when applicable
#
# The envelope is purely additive: callers can still read their existing
# fields (readiness_score, mode, etc.). Any existing "status" value set by
# the caller is preserved as-is; this function does NOT overwrite it.

_ENVELOPE_DEFAULTS = {
    "completed": "Request completed.",
    "partial_completed": "Request completed with partial results.",
    "failed": "Request failed.",
}

_STANDARD_STATUSES = frozenset({"completed", "partial_completed", "failed"})


def _standard_envelope(
    *,
    status: str,
    message: str | None = None,
    warnings: list | None = None,
    missing_inputs: list | None = None,
    error_reason: str | None = None,
    changed_sections: list | None = None,
    change_request_id: str | None = None,
) -> dict:
    """Build the standard response envelope fields.

    Callers merge these into their payload dict. Fields with default values
    are omitted so existing API shapes stay clean.
    """
    if status not in _STANDARD_STATUSES:
        status = "failed"
    env: dict[str, Any] = {
        "standard_status": status,
        "message": message or _ENVELOPE_DEFAULTS[status],
    }
    if warnings:
        env["warnings"] = [str(w) for w in warnings if w]
    if missing_inputs:
        env["missing_inputs"] = [str(x) for x in missing_inputs if x]
    if error_reason:
        env["error_reason"] = str(error_reason)
    if changed_sections:
        env["changed_sections"] = [str(s) for s in changed_sections if s]
    if change_request_id:
        env["change_request_id"] = str(change_request_id)
    return env


def _ok(body: dict | None = None, **envelope_kwargs) -> dict:
    """Return 200 with standard ``completed`` envelope merged into body."""
    payload: dict[str, Any] = dict(body or {})
    payload.update(_standard_envelope(status="completed", **envelope_kwargs))
    return _response(200, payload)


def _partial(body: dict | None = None, *, warnings: list | None = None, **envelope_kwargs) -> dict:
    """Return 200 with standard ``partial_completed`` envelope.

    ``warnings`` is required in practice — a partial result without a reason
    is effectively fake success. We keep the parameter optional for call-site
    convenience but will emit a single default warning if omitted.
    """
    payload: dict[str, Any] = dict(body or {})
    if not warnings:
        warnings = ["partial result — see mode/fallback for details"]
    payload.update(_standard_envelope(
        status="partial_completed",
        warnings=warnings,
        **envelope_kwargs,
    ))
    return _response(200, payload)


def _failed(
    status_code: int,
    *,
    error_reason: str,
    message: str | None = None,
    warnings: list | None = None,
    missing_inputs: list | None = None,
    extra: dict | None = None,
) -> dict:
    """Return non-2xx with the standard ``failed`` envelope.

    Keeps the legacy ``error`` and optional ``stage`` fields that existing
    frontend error paths already read.
    """
    payload: dict[str, Any] = dict(extra or {})
    payload.setdefault("error", error_reason)
    payload.update(_standard_envelope(
        status="failed",
        message=message,
        warnings=warnings,
        missing_inputs=missing_inputs,
        error_reason=error_reason,
    ))
    return _response(status_code, payload)


def _safe_error_reason(exc: BaseException, max_len: int = 160) -> str:
    """Produce a short, log-safe error description.

    Avoids dumping full payloads or tracebacks. Only exception class +
    truncated message is returned so logs and API responses do not leak
    secrets or large blobs.
    """
    text = str(exc)
    if len(text) > max_len:
        text = text[:max_len] + "..."
    return f"{type(exc).__name__}: {text}"


def _log(action: str, level: str, **fields: Any) -> None:
    """Consistent, secret-safe log line.

    Format: ``[doc-api:<action>] level=<lvl> key1=v1 key2=v2``
    Values longer than 160 chars are truncated with ``...``.
    Only scalar values are included — dicts/lists are summarised by type.
    """
    parts = [f"[doc-api:{action}] level={level}"]
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, (dict, list, tuple, set)):
            val_repr = f"{type(value).__name__}(len={len(value)})"
        elif isinstance(value, bool):
            val_repr = "true" if value else "false"
        else:
            val_repr = str(value)
        if len(val_repr) > 160:
            val_repr = val_repr[:160] + "..."
        parts.append(f"{key}={val_repr}")
    print(" ".join(parts))


def _set_nested(obj: dict, path: str, value: Any) -> None:
    parts = [p for p in path.strip("/").split("/") if p]
    cur = obj
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    if parts:
        cur[parts[-1]] = value


def _get_nested(obj: dict, parts: list[str]) -> Any:
    cur: Any = obj
    for part in parts:
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _path_parts(path: str) -> list[str]:
    normalized = path.strip().strip("/")
    if not normalized:
        raise ValueError("path is required")
    return [part for part in normalized.replace("/", ".").split(".") if part]


def _is_field_value(value: Any) -> bool:
    return isinstance(value, dict) and any(
        key in value
        for key in ("user_input", "ai_recommended", "calculated", "status")
    )


def _field_value_with_user_input(existing: Any, value: Any) -> dict:
    if _is_field_value(existing):
        field = deepcopy(existing)
    else:
        field = {
            "user_input": None,
            "ai_recommended": None,
            "calculated": None,
            "status": "empty",
        }
    field["user_input"] = value
    field["user_edited"] = True
    field["status"] = "draft"
    return field


def _default_field_value() -> dict:
    """Return an empty FieldValue dict (no value set)."""
    return {
        "user_input": None,
        "ai_recommended": None,
        "calculated": None,
        "status": "empty",
        "user_edited": False,
    }


def _confirmed_field_value(value: Any) -> dict:
    """Return a FieldValue with a pre-set calculated value and confirmed status."""
    return {
        "user_input": None,
        "ai_recommended": None,
        "calculated": value,
        "status": "confirmed",
        "user_edited": False,
    }


def _structured_bullet(text: Any = None, level: int = 1) -> dict:
    return {
        "text": _confirmed_field_value(text) if text not in (None, "") else _default_field_value(),
        "level": 2 if level == 2 else 1,
    }


def _default_meta() -> dict:
    """Return the default meta dict for new documents."""
    return {
        "customer": _default_field_value(),
        "partner": _confirmed_field_value("MegazoneCloud"),
        "date": _default_field_value(),
    }


def _default_sections() -> dict:
    """Return the default sections dict for new documents."""
    return {
        "cover": {},
        "executive_summary": {
            "groups": [
                {
                    "category_name": _confirmed_field_value("Customer Overview"),
                    "bullets": [_structured_bullet("Customer description"), _structured_bullet("Business context")],
                },
                {
                    "category_name": _confirmed_field_value("Current Challenges"),
                    "bullets": [_structured_bullet("Manual process"), _structured_bullet("Search delay")],
                },
                {
                    "category_name": _confirmed_field_value("Proposed Solution"),
                    "bullets": [_structured_bullet("Amazon Bedrock-based solution"), _structured_bullet("RAG/OpenSearch/S3 architecture")],
                },
            ],
        },
        "stakeholders": {
            "executive_sponsors": [
                {
                    "name": _confirmed_field_value("James, Kong"),
                    "title": _confirmed_field_value("CAIO"),
                    "description": _confirmed_field_value("Head of AI Business"),
                    "stakeholder_for": _default_field_value(),
                    "role": _default_field_value(),
                    "contact": _confirmed_field_value("jameskong@megazone.com"),
                }
            ],
            "stakeholders": [],
            "project_team": [],
            "escalation_contacts": [],
        },
        "success_criteria": {"groups": [], "items": []},
        "assumptions": {"groups": [], "items": []},
        "scope_of_work": {"tasks": [], "out_of_scope": [], "items": []},
        "architecture": {"overview": _default_field_value(), "diagram_image_s3_key": _default_field_value(), "services": [], "tools_list": []},
        "milestones": {"phases": []},
        "cost_breakdown": {
            "calculator_url": _default_field_value(),
            "mrr": _default_field_value(),
            "arr": _default_field_value(),
            "breakdown_table": [],
            "bedrock_extra": _default_field_value(),
            "funding_calculation": {},
        },
        "acceptance": {"steps": []},
        "resources_cost_estimates": {
            "role_rates": [],
            "phase_hours_table": [],
            "total_hours": {"sa": "", "eng": "", "other": "", "total": ""},
            "total_cost": {"sa": "", "eng": "", "other": "", "total": ""},
            "contribution": {
                "customer": {"amount": _default_field_value(), "pct": _default_field_value()},
                "partner": {"amount": _default_field_value(), "pct": _default_field_value()},
                "aws": {"amount": _default_field_value(), "pct": _default_field_value()},
            },
            "client_signature_customer_name": _default_field_value(),
            "client_signature_person_name": _default_field_value(),
            "client_signature_designation": _default_field_value(),
            "client_signature_date": _default_field_value(),
        },
    }


def _resolved_number(value: Any) -> float:
    if isinstance(value, dict):
        value = value.get("user_input") if value.get("user_input") is not None else (
            value.get("ai_recommended") if value.get("ai_recommended") is not None else value.get("calculated")
        )
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _patch_operation(op: str, path: str, value: Any = None, source: str | None = None) -> dict:
    item = {"op": op, "path": path, "value": value}
    if source is not None:
        item["source"] = source
    return item


def _resolve_field_value(value: Any) -> Any:
    if isinstance(value, dict) and any(k in value for k in ("user_input", "ai_recommended", "calculated")):
        for key in ("user_input", "ai_recommended", "calculated"):
            candidate = value.get(key)
            if candidate not in (None, ""):
                return candidate
        return ""
    return value


def _has_resolved_value(value: Any) -> bool:
    resolved = _resolve_field_value(value)
    return resolved not in (None, "", [], {})


def _to_float(value: Any, default: float = 0.0) -> float:
    resolved = _resolve_field_value(value)
    if resolved in (None, ""):
        return default
    try:
        return float(str(resolved).replace("$", "").replace(",", ""))
    except (TypeError, ValueError):
        return default


def _json_pointer_parts(path: str) -> list[str]:
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError("json patch path must start with '/'")
    parts = path.strip("/").split("/") if path.strip("/") else []
    return [p.replace("~1", "/").replace("~0", "~") for p in parts]


def _ensure_patch_path_allowed(parts: list[str]) -> None:
    if not parts:
        raise ValueError("json patch path must not target document root")
    root = parts[0]
    if root in PROTECTED_PATCH_ROOTS or root not in MUTABLE_PATCH_ROOTS:
        raise ValueError(f"patch path root is not mutable: {root}")


def _json_patch_parent(doc: Any, parts: list[str]) -> tuple[Any, str]:
    if not parts:
        raise ValueError("json patch path is empty")
    _ensure_patch_path_allowed(parts)
    cur = doc
    for part in parts[:-1]:
        if isinstance(cur, dict):
            if part not in cur:
                cur[part] = {}
            cur = cur[part]
        elif isinstance(cur, list):
            index = _list_index(part, "/" + "/".join(parts))
            if index >= len(cur):
                raise ValueError(f"list index out of range: {part}")
            cur = cur[index]
        else:
            raise ValueError(f"cannot traverse scalar patch segment: {part}")
    return cur, parts[-1]


def _apply_json_patch_operation(doc: dict, operation: dict) -> None:
    op = operation.get("op")
    path = operation.get("path")
    if op not in {"add", "replace", "remove"}:
        raise ValueError(f"unsupported json patch op: {op}")
    parts = _json_pointer_parts(path)
    parent, key = _json_patch_parent(doc, parts)

    if isinstance(parent, dict):
        if op == "remove":
            if key not in parent:
                raise ValueError(f"patch path does not exist: {path}")
            del parent[key]
            return
        if op == "replace" and key not in parent:
            raise ValueError(f"patch path does not exist: {path}")
        parent[key] = operation.get("value")
        return

    if isinstance(parent, list):
        if key == "-" and op == "add":
            parent.append(operation.get("value"))
            return
        index = _list_index(key, path)
        if op == "add":
            if index > len(parent):
                raise ValueError(f"list index out of range: {path}")
            parent.insert(index, operation.get("value"))
            return
        if index >= len(parent):
            raise ValueError(f"list index out of range: {path}")
        if op == "remove":
            del parent[index]
            return
        parent[index] = operation.get("value")
        return

    raise ValueError(f"cannot patch scalar parent: {path}")


def _apply_json_patch_copy(item: dict, operations: list[dict]) -> dict:
    if not isinstance(operations, list) or not operations:
        raise ValueError("json_patch must be a non-empty list")
    patched = deepcopy(item)
    for operation in operations:
        if not isinstance(operation, dict):
            raise ValueError("json_patch operations must be objects")
        _apply_json_patch_operation(patched, operation)
    return patched


def _patch_section(path: str) -> str:
    try:
        parts = _json_pointer_parts(path)
    except ValueError:
        return ""
    if len(parts) >= 2 and parts[0] == "sections":
        return parts[1]
    return parts[0] if parts else ""


def _set_user_input_field(doc: dict, path: str, value: Any) -> tuple[str, dict]:
    parts = _path_parts(path)
    if parts[0] not in {"meta", "sections", "staffing_plan"}:
        raise ValueError("path must target meta, sections, or staffing_plan")
    if any(part in {"version", "document_id", "user_id"} for part in parts):
        raise ValueError("path targets a protected field")

    target_parts = parts[:-1] if parts[-1] == "user_input" else parts
    if not target_parts:
        raise ValueError("path must target a field")

    parent: Any = doc
    for part in target_parts[:-1]:
        child = _get_editable_child(parent, part, path, create_missing_dict=True)
        if not isinstance(child, (dict, list)):
            raise EditablePathError(
                "path segment is not editable",
                path,
                part,
                "path segment resolved to a scalar value",
            )
        parent = child

    field_key = target_parts[-1]
    if isinstance(parent, dict):
        existing = parent.get(field_key)
    else:
        existing = _get_editable_child(parent, field_key, path, create_missing_dict=False)
    updated = _field_value_with_user_input(existing, value)
    _set_editable_child(parent, field_key, updated, path)
    return "/" + "/".join([*target_parts, "user_input"]), updated


def _list_index(segment: str, path: str) -> int:
    if not segment.isdigit():
        raise EditablePathError(
            "invalid list index",
            path,
            segment,
            "list path segment must be a non-negative integer",
        )
    return int(segment)


def _get_editable_child(container: Any, segment: str, path: str, *, create_missing_dict: bool) -> Any:
    if isinstance(container, dict):
        if segment not in container:
            if create_missing_dict:
                container[segment] = {}
            else:
                raise EditablePathError(
                    "path segment not found",
                    path,
                    segment,
                    "dict key does not exist",
                )
        return container[segment]

    if isinstance(container, list):
        index = _list_index(segment, path)
        if index >= len(container):
            raise EditablePathError(
                "invalid list index",
                path,
                segment,
                f"index {index} is out of range for list of length {len(container)}",
            )
        return container[index]

    raise EditablePathError(
        "path segment is not editable",
        path,
        segment,
        "parent container is neither dict nor list",
    )


def _set_editable_child(container: Any, segment: str, value: Any, path: str) -> None:
    if isinstance(container, dict):
        container[segment] = value
        return

    if isinstance(container, list):
        index = _list_index(segment, path)
        if index >= len(container):
            raise EditablePathError(
                "invalid list index",
                path,
                segment,
                f"index {index} is out of range for list of length {len(container)}",
            )
        container[index] = value
        return

    raise EditablePathError(
        "path segment is not editable",
        path,
        segment,
        "parent container is neither dict nor list",
    )


def _set_raw_user_input_path(doc: dict, path: str, value: Any) -> str:
    parts = _path_parts(path)
    if parts[0] not in {"meta", "sections", "staffing_plan"}:
        raise ValueError("path must target meta, sections, or staffing_plan")

    parent: Any = doc
    for part in parts[:-1]:
        child = _get_editable_child(parent, part, path, create_missing_dict=True)
        if not isinstance(child, (dict, list)):
            raise EditablePathError(
                "path segment is not editable",
                path,
                part,
                "path segment resolved to a scalar value",
            )
        parent = child

    _set_editable_child(parent, parts[-1], value, path)
    return "/" + "/".join(parts)


def _calculated_patch(doc: dict, path: str, value: Any) -> dict | None:
    parts = _path_parts(path)
    parent = _get_nested(doc, parts[:-1])
    if not isinstance(parent, dict):
        return None
    key = parts[-1]
    existing = parent.get(key)
    if isinstance(existing, dict):
        existing["calculated"] = value
    else:
        parent[key] = {"calculated": value}
    return _patch_operation("replace", "/" + "/".join(parts), parent[key], "calculated")


def _staffing_recalculation_patches(doc: dict) -> list[dict]:
    if not isinstance(doc.get("staffing_plan"), dict):
        return []

    staffing = doc["staffing_plan"]
    result = {
        "roles": {},
        "grand_total_hours": 0.0,
        "grand_total_cost": 0.0,
    }
    for role_id, role in (staffing.get("roles") or {}).items():
        count = _resolved_number(role.get("count"))
        allocation = _resolved_number(role.get("allocation_pct")) / 100
        rate = _resolved_number(role.get("rate_per_hour"))
        phase_hours = role.get("phase_hours") or {}
        hours = sum(_resolved_number(v) for v in phase_hours.values())
        total_hours = round(hours, 2)
        total_cost = round(count * allocation * rate * total_hours, 2)
        result["roles"][role_id] = {
            "total_hours": total_hours,
            "total_cost": total_cost,
        }
        result["grand_total_hours"] += total_hours
        result["grand_total_cost"] += total_cost

    operations: list[dict] = []
    for role_id, totals in result["roles"].items():
        for field_name in ("total_hours", "total_cost"):
            op = _calculated_patch(
                doc,
                f"staffing_plan.roles.{role_id}.{field_name}",
                totals[field_name],
            )
            if op:
                operations.append(op)

    for field_name in ("grand_total_hours", "grand_total_cost"):
        op = _calculated_patch(
            doc,
            f"staffing_plan.{field_name}",
            round(result[field_name], 2),
        )
        if op:
            operations.append(op)
    return operations


def _conditional_save_document(item: dict, expected_version: int) -> dict:
    item["version"] = expected_version + 1
    item["updated_at"] = _now_iso()
    raw = _json(item)
    try:
        table.put_item(
            Item=json.loads(raw, parse_float=Decimal),
            ConditionExpression=Attr("version").eq(expected_version),
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException as exc:
        raise VersionConflictError(
            f"Version conflict: expected {expected_version}, stored version differs"
        ) from exc
    return item


# --- User ID extraction (Phase 3에서 JWT claims로 교체 예정) ---

def get_user_id(event: dict) -> Optional[str]:
    headers = event.get("headers") or {}
    return (
        headers.get("x-user-id")
        or headers.get("X-User-Id")
        or headers.get("X-USER-ID")
    )


def _require_user(event: dict):
    user_id = get_user_id(event)
    if not user_id:
        body = {"error": "user_id required (X-User-Id header)"}
        body.update(_standard_envelope(
            status="failed",
            message="Authentication required.",
            error_reason="missing_user_id",
            missing_inputs=["X-User-Id header"],
        ))
        return None, _response(401, body)
    return user_id, None


def _check_ownership(item: dict, user_id: str) -> Optional[dict]:
    """소유권 검증. 위반 시 403 응답, OK면 None."""
    owner = item.get("user_id")
    if owner and owner != user_id:
        body = {"error": "forbidden"}
        body.update(_standard_envelope(
            status="failed",
            message="Forbidden.",
            error_reason="ownership_denied",
        ))
        return _response(403, body)
    return None


PERMISSION_ORDER = {
    "read": 0,
    "suggest": 1,
    "edit": 2,
    "master": 3,
}

CHANGE_REQUEST_STATUSES = {"pending", "approved", "rejected"}
PROTECTED_PATCH_ROOTS = {
    "document_id",
    "user_id",
    "version",
    "created_at",
    "updated_at",
    "change_requests",
}
MUTABLE_PATCH_ROOTS = {
    "title",
    "mode",
    "template",
    "meta",
    "sections",
    "completion_score",
    "blocking_issues",
    "warnings",
    "agent_status",
    "agent_active",
    "agent_message",
    "settings",
}


def _permission_value(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("role") or value.get("permission") or value.get("level")
    role = str(value or "").strip().lower()
    return role if role in PERMISSION_ORDER else ""


def _document_permission(item: dict, user_id: str) -> str:
    """Resolve current user's placeholder permission.

    Owner is treated as master. Non-owner permissions are read from either
    ``document_permissions`` or ``permissions`` so Cognito/group wiring can be
    added later without changing the API contract.
    """
    if item.get("user_id") == user_id or item.get("owner_id") == user_id:
        return "master"

    for key in ("document_permissions", "permissions"):
        permissions = item.get(key)
        if not isinstance(permissions, dict):
            continue
        role = _permission_value(permissions.get(user_id))
        if role:
            return role

    if user_id in (item.get("masters") or []):
        return "master"
    if user_id in (item.get("editors") or []):
        return "edit"
    if user_id in (item.get("suggesters") or []):
        return "suggest"
    if user_id in (item.get("readers") or []):
        return "read"
    return ""


def _authorize_document(item: dict, user_id: str, required: str) -> tuple[str, Optional[dict]]:
    role = _document_permission(item, user_id)
    if not role:
        body = {"error": "forbidden"}
        body.update(_standard_envelope(
            status="failed",
            message="Forbidden.",
            error_reason="forbidden",
        ))
        return "", _response(403, body)
    if PERMISSION_ORDER[role] < PERMISSION_ORDER[required]:
        body = {
            "error": "insufficient_permission",
            "required": required,
            "permission": role,
        }
        body.update(_standard_envelope(
            status="failed",
            message=f"Requires {required} permission.",
            error_reason="insufficient_permission",
        ))
        return role, _response(403, body)
    return role, None


def _document_requires_review(item: dict) -> bool:
    settings = item.get("settings") if isinstance(item.get("settings"), dict) else {}
    permission_settings = item.get("permission_settings") if isinstance(item.get("permission_settings"), dict) else {}
    return bool(
        settings.get("require_review")
        or settings.get("requires_review")
        or item.get("review_required")
        or permission_settings.get("require_review")
    )


def _update_agent_status(doc_id: str, status: str, active: str = "", message: str = "") -> None:
    """Update agent_status fields in DynamoDB for a document."""
    try:
        table.update_item(
            Key={"document_id": doc_id},
            UpdateExpression="SET agent_status = :s, agent_active = :a, agent_message = :m",
            ExpressionAttributeValues={":s": status, ":a": active, ":m": message},
        )
    except Exception as e:
        print(f"[agent_status] update failed: {e}")


def _append_history_message(doc_id: str, user_id: str, msg: dict) -> None:
    """Atomic append a single message to conversation history."""
    try:
        history_table.update_item(
            Key={"document_id": doc_id, "session_id": "default"},
            UpdateExpression="SET messages = list_append(if_not_exists(messages, :empty), :new_msg), "
                             "total_count = if_not_exists(total_count, :zero) + :one, "
                             "user_id = :uid, updated_at = :now",
            ExpressionAttributeValues={
                ":new_msg": [msg],
                ":empty": [],
                ":one": 1,
                ":zero": 0,
                ":uid": user_id,
                ":now": _now_iso(),
            },
        )
    except Exception as e:
        print(f"[history_append] failed: {e}")


def _publish_refresh(doc_id: str) -> None:
    """Send a refresh signal via AppSync — tells frontend to re-fetch from DynamoDB."""
    _publish_event(f"/docs/{doc_id}/chat", {
        "type": "refresh",
        "target": "history",
    })


def _publish_event(channel: str, data: dict) -> None:
    """Publish an event to AppSync Events API via HTTP POST."""
    if not APPSYNC_HTTP_URL:
        return
    try:
        import urllib.request
        url = f"{APPSYNC_HTTP_URL}/event"
        payload = json.dumps({
            "channel": f"/{channel}" if not channel.startswith("/") else channel,
            "events": [json.dumps(data)],
        })
        # Use SigV4 signing via boto3
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest
        session = boto3.Session()
        credentials = session.get_credentials().get_frozen_credentials()
        request = AWSRequest(method="POST", url=url, data=payload, headers={"Content-Type": "application/json"})
        SigV4Auth(credentials, "appsync", REGION).add_auth(request)
        req = urllib.request.Request(url, data=payload.encode(), method="POST")
        for k, v in dict(request.headers).items():
            req.add_header(k, v)
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f"[appsync publish error] {e}")


def _save_to_ddb(item: dict) -> None:
    raw = _json(item)
    table.put_item(Item=json.loads(raw, parse_float=Decimal))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _document_shell(doc_id: str, user_id: str) -> dict:
    now = _now_iso()
    return {
        "document_id": doc_id,
        "user_id": user_id,
        "title": "새 문서",
        "version": 0,
        "created_at": now,
        "updated_at": now,
        "mode": "architecture_absent",
        "template": "apn_poc_project_plan",
        "meta": _default_meta(),
        "sections": _default_sections(),
        "completion_score": 0,
        "blocking_issues": [],
        "warnings": [],
    }


def _load_document_for_action(doc_id: str, event: dict, required: str) -> tuple[str, str, dict | None, Optional[dict]]:
    user_id, err = _require_user(event)
    if err:
        return "", "", None, err
    resp = table.get_item(Key={"document_id": doc_id})
    item = resp.get("Item")
    if not item:
        body = {"error": "not found"}
        body.update(_standard_envelope(
            status="failed",
            message="Document not found.",
            error_reason="not_found",
        ))
        return user_id, "", None, _response(404, body)
    permission, auth_err = _authorize_document(item, user_id, required)
    if auth_err:
        return user_id, permission, None, auth_err
    return user_id, permission, item, None


def _publish_document_patch(doc_id: str, operations: list[dict], saved: dict, expected_version: int, agent: str) -> None:
    _publish_event(f"docs/{doc_id}/patch", {
        "type": "patch",
        "patch_id": f"patch-{uuid.uuid4().hex[:12]}",
        "doc_id": doc_id,
        "agent": agent,
        "operations": operations,
        "version": saved["version"],
        "version_before": expected_version,
        "version_after": saved["version"],
    })


def _change_request_from_patch(
    doc_id: str,
    requester: str,
    operations: list[dict],
    *,
    summary: str = "",
    changes: list[dict] | None = None,
) -> dict:
    now = _now_iso()
    normalized_changes = changes if isinstance(changes, list) else []
    if not normalized_changes:
        normalized_changes = [
            {
                "section": _patch_section(op.get("path", "")),
                "as_is": None,
                "to_be": op.get("value"),
                "reason": op.get("reason", ""),
                "json_patch": [op],
            }
            for op in operations
        ]
    return {
        "change_request_id": f"cr-{uuid.uuid4().hex[:12]}",
        "document_id": doc_id,
        "requester": requester,
        "status": "pending",
        "summary": summary or f"{len(operations)} proposed document change(s)",
        "changes": normalized_changes,
        "json_patch": operations,
        "created_at": now,
        "updated_at": now,
    }


def _save_change_request(item: dict, expected_version: int, change_request: dict) -> dict:
    updated = deepcopy(item)
    requests = updated.get("change_requests")
    if not isinstance(requests, list):
        requests = []
    requests.append(change_request)
    updated["change_requests"] = requests
    return _conditional_save_document(updated, expected_version)


def _find_change_request(item: dict, change_request_id: str) -> tuple[int, dict] | tuple[None, None]:
    requests = item.get("change_requests")
    if not isinstance(requests, list):
        return None, None
    for index, request in enumerate(requests):
        if request.get("change_request_id") == change_request_id:
            return index, request
    return None, None


# ---------------------------------------------------------------------------
# Approved sample retrieval + section recommendations
# ---------------------------------------------------------------------------
#
# Metadata model (per approved-sample excerpt):
#   sample_id (str)         - stable identifier
#   customer (str)          - short generic label ("Retail Customer"), never a real name
#   industry (str)          - e.g. "Retail / Commerce"
#   use_case_type (str)     - e.g. "rag_search", "agentic_workflow"
#   section (str)           - DocumentState section key
#   services (list[str])    - AWS services referenced
#   tags (list[str])        - free-form tags
#   s3_key (str)            - where the full approved doc lives (or "" if not in S3)
#   language (str)          - "en" / "ko"
#   excerpt (str)           - short excerpt / summary, SAFE to return over API
#
# When APPROVED_SAMPLES_KB_ID is missing, `_query_approved_samples` returns a
# filtered subset of the static fallback list. It never returns full document
# content — only metadata and excerpts.

_FALLBACK_APPROVED_SAMPLES: list[dict] = [
    {
        "sample_id": "apn-rag-retail-exec-summary",
        "customer": "Retail Customer",
        "industry": "Retail / Commerce",
        "use_case_type": "rag_search",
        "section": "executive_summary",
        "services": ["Amazon Bedrock", "Amazon OpenSearch Service", "Amazon S3"],
        "tags": ["apn", "genai_ic", "rag"],
        "s3_key": "",
        "language": "en",
        "excerpt": (
            "Approved pattern: Bedrock-based RAG search reduces manual lookup time "
            "and clarifies production readiness criteria."
        ),
    },
    {
        "sample_id": "apn-agent-fin-success-criteria",
        "customer": "Finance Customer",
        "industry": "Finance / Insurance",
        "use_case_type": "agentic_workflow",
        "section": "success_criteria",
        "services": ["Amazon Bedrock", "AWS Lambda", "Amazon DynamoDB"],
        "tags": ["apn", "genai_ic", "agentic"],
        "s3_key": "",
        "language": "en",
        "excerpt": (
            "Approved success criteria pattern: response accuracy >=90%, "
            "average latency <3s, validated RAG pipeline on customer data."
        ),
    },
    {
        "sample_id": "sow-mfg-assumptions",
        "customer": "Manufacturing Customer",
        "industry": "Manufacturing",
        "use_case_type": "assistant",
        "section": "assumptions",
        "services": ["Amazon Bedrock", "Amazon S3"],
        "tags": ["sow", "risk"],
        "s3_key": "",
        "language": "en",
        "excerpt": (
            "Approved assumptions pattern: production deployment out of scope in PoC, "
            "customer provides data access, change requests follow agreed process."
        ),
    },
    {
        "sample_id": "apn-architecture-bedrock-rag",
        "customer": "Generic Customer",
        "industry": "Cross-industry",
        "use_case_type": "rag_search",
        "section": "architecture",
        "services": [
            "Amazon Bedrock",
            "Amazon OpenSearch Service",
            "AWS Lambda",
            "Amazon S3",
            "Amazon API Gateway",
        ],
        "tags": ["apn", "architecture"],
        "s3_key": "",
        "language": "en",
        "excerpt": (
            "Approved architecture pattern: API Gateway -> Lambda -> Bedrock with "
            "OpenSearch vector store and S3 source documents."
        ),
    },
    {
        "sample_id": "apn-cost-breakdown-poc",
        "customer": "Generic Customer",
        "industry": "Cross-industry",
        "use_case_type": "poc",
        "section": "cost_breakdown",
        "services": ["Amazon Bedrock", "AWS Lambda", "Amazon S3"],
        "tags": ["apn", "genai_ic", "funding"],
        "s3_key": "",
        "language": "en",
        "excerpt": (
            "Approved cost pattern: AWS Calculator URL referenced, Year 1 ARR and "
            "SOW cost provided; eligible funding = min(ARR*25%, SOW cost, 125K)."
        ),
    },
]


def _matches_filter(sample: dict, key: str, value: Any) -> bool:
    if value in (None, "", []):
        return True
    sv = sample.get(key)
    if isinstance(value, list):
        wanted = {str(v).strip().lower() for v in value if v}
        if not wanted:
            return True
        if isinstance(sv, list):
            have = {str(s).strip().lower() for s in sv}
            return bool(wanted & have)
        return str(sv).strip().lower() in wanted
    return str(sv).strip().lower() == str(value).strip().lower()


def _query_fallback_samples(
    section: str = "",
    industry: str = "",
    use_case_type: str = "",
    services: Optional[list] = None,
    query: str = "",
    top_k: int = 3,
) -> list[dict]:
    """Filter the static fallback list. Returns short metadata+excerpt items."""
    results = []
    for sample in _FALLBACK_APPROVED_SAMPLES:
        if not _matches_filter(sample, "section", section):
            continue
        if not _matches_filter(sample, "industry", industry):
            continue
        if not _matches_filter(sample, "use_case_type", use_case_type):
            continue
        if services:
            wanted = {str(s).strip().lower() for s in services if s}
            have = {str(s).strip().lower() for s in (sample.get("services") or [])}
            if wanted and not (wanted & have):
                continue
        if query:
            qlc = str(query).lower()
            haystack = " ".join([
                sample.get("excerpt", ""),
                " ".join(sample.get("tags") or []),
                sample.get("use_case_type", ""),
                sample.get("industry", ""),
            ]).lower()
            if qlc not in haystack and not any(tok in haystack for tok in qlc.split() if len(tok) > 2):
                # Keep at lower priority — do not discard hard
                pass
        results.append({
            "sample_id": sample["sample_id"],
            "metadata": {
                "customer": sample.get("customer", ""),
                "industry": sample.get("industry", ""),
                "use_case_type": sample.get("use_case_type", ""),
                "section": sample.get("section", ""),
                "services": list(sample.get("services") or []),
                "tags": list(sample.get("tags") or []),
                "s3_key": sample.get("s3_key", ""),
                "language": sample.get("language", "en"),
            },
            "excerpt": sample.get("excerpt", ""),
        })
    return results[: max(1, int(top_k or 3))]


def _query_approved_samples(
    section: str = "",
    industry: str = "",
    use_case_type: str = "",
    services: Optional[list] = None,
    query: str = "",
    top_k: int = 3,
) -> dict:
    """Retrieve approved-sample excerpts.

    If ``APPROVED_SAMPLES_KB_ID`` is configured and the Bedrock Agent Runtime
    retrieve API is callable, use it. Otherwise return a filtered subset of
    the static fallback list. Never returns full document bodies — only
    short excerpts and metadata.
    """
    kb_id = os.environ.get("APPROVED_SAMPLES_KB_ID", "")
    data_source = os.environ.get("APPROVED_SAMPLES_DATA_SOURCE_ID", "")

    if kb_id:
        try:
            client = boto3.client("bedrock-agent-runtime", region_name=REGION)
            filters = []
            if section:
                filters.append(" ".join(["section", section]))
            if industry:
                filters.append(" ".join(["industry", industry]))
            if use_case_type:
                filters.append(" ".join(["use_case_type", use_case_type]))
            retrieval_query = query or " ".join(filters) or section or "approved sample"
            resp = client.retrieve(
                knowledgeBaseId=kb_id,
                retrievalQuery={"text": retrieval_query[:500]},
                retrievalConfiguration={
                    "vectorSearchConfiguration": {"numberOfResults": max(1, int(top_k or 3))},
                },
            )
            hits = []
            for r in resp.get("retrievalResults", []) or []:
                md = r.get("metadata", {}) or {}
                content = (r.get("content", {}) or {}).get("text", "") or ""
                # Return short excerpts only (max 400 chars) — never full docs.
                excerpt = content[:400]
                hits.append({
                    "sample_id": str(md.get("sample_id") or md.get("id") or ""),
                    "metadata": {
                        "customer": str(md.get("customer", "")),
                        "industry": str(md.get("industry", "")),
                        "use_case_type": str(md.get("use_case_type", "")),
                        "section": str(md.get("section", section or "")),
                        "services": list(md.get("services") or []),
                        "tags": list(md.get("tags") or []),
                        "s3_key": str(md.get("s3_key") or (r.get("location", {}) or {}).get("s3Location", {}).get("uri", "")),
                        "language": str(md.get("language", "en")),
                        "score": r.get("score"),
                    },
                    "excerpt": excerpt,
                })
            return {
                "mode": "kb",
                "message": "Approved samples retrieved from Bedrock Knowledge Base.",
                "kb_id_present": True,
                "data_source_present": bool(data_source),
                "examples": hits,
            }
        except Exception as exc:
            print(f"[approved_samples] KB retrieve failed, using fallback: {exc}")
            return {
                "mode": "fallback",
                "message": f"KB retrieve failed; using static fallback. ({type(exc).__name__})",
                "kb_id_present": True,
                "data_source_present": bool(data_source),
                "examples": _query_fallback_samples(section, industry, use_case_type, services, query, top_k),
            }

    return {
        "mode": "fallback",
        "message": (
            "Approved samples Knowledge Base is not configured. "
            "Returning static fallback metadata/excerpts only."
        ),
        "kb_id_present": False,
        "data_source_present": False,
        "examples": _query_fallback_samples(section, industry, use_case_type, services, query, top_k),
    }


def _approved_samples_fallback() -> dict:
    """Backward-compatible status shim used by ``_document_lint_result``.

    Returns the mode/message/kb_id_present summary without executing a full
    retrieval. Downstream consumers that want hits should call
    ``_query_approved_samples`` directly.
    """
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
            "Approved samples Knowledge Base is not configured. "
            "Proceeding with deterministic APN/GenAI IC/SOW readiness checks only."
        ),
        "kb_id_present": False,
        "data_source_present": False,
    }


# ---------------------------------------------------------------------------
# Section recommendations (preset / dropdown options)
# ---------------------------------------------------------------------------

_SECTION_RECOMMENDATIONS: dict[str, list[dict]] = {
    "success_criteria": [
        {
            "id": "success_criteria.rag_quality",
            "label": "RAG response quality targets",
            "description": "Typical APN-approved success criteria around GenAI answer quality.",
            "prompt_hint": "Define measurable RAG quality targets.",
            "aws_services": ["Amazon Bedrock", "Amazon OpenSearch Service"],
            "sample_objectives": [
                "Achieve response accuracy of 90% or higher",
                "Maintain average response latency under 3 seconds",
                "Validate RAG pipeline with customer-provided documents",
            ],
        },
        {
            "id": "success_criteria.cost_effectiveness",
            "label": "Cost effectiveness",
            "description": "Budget-oriented success criteria aligned with GenAI IC funding review.",
            "prompt_hint": "Tie success criteria to monthly AWS cost budget.",
            "aws_services": ["Amazon Bedrock", "AWS Lambda", "Amazon S3"],
            "sample_objectives": [
                "Operate within estimated monthly AWS cost budget",
                "Demonstrate cost savings compared to current process",
                "Provide detailed cost breakdown and optimization recommendations",
            ],
        },
        {
            "id": "success_criteria.security",
            "label": "Security and data protection",
            "description": "Security-oriented success criteria suitable for SOW.",
            "prompt_hint": "Cover encryption, access control, compliance.",
            "aws_services": ["AWS IAM", "AWS KMS", "Amazon Bedrock"],
            "sample_objectives": [
                "Implement data encryption at rest and in transit",
                "Validate access control and authentication mechanisms",
                "Ensure compliance with customer security policies",
            ],
        },
    ],
    "assumptions": [
        {
            "id": "assumptions.business_context",
            "label": "Business context",
            "description": "Assumptions about customer participation and scope agreement.",
            "sample_objectives": [
                "Customer will provide necessary business requirements and system documentation",
                "Key stakeholders will participate in regular meetings and reviews",
                "Project scope and objectives are agreed upon before execution begins",
            ],
        },
        {
            "id": "assumptions.technical_environment",
            "label": "Technical environment",
            "description": "Assumptions about AWS service availability and integration.",
            "aws_services": ["Amazon Bedrock"],
            "sample_objectives": [
                "Amazon Bedrock is available in the target AWS region",
                "Customer will provide access to required data sources and systems",
                "Existing infrastructure supports integration with AWS services",
            ],
        },
        {
            "id": "assumptions.scope_boundaries",
            "label": "Scope boundaries",
            "description": "Out-of-scope items typical in APN / GenAI IC PoC SOW.",
            "sample_objectives": [
                "Production deployment is out of scope for this PoC phase",
                "Performance testing is limited to defined test scenarios",
                "Third-party system integration is limited to agreed interfaces",
            ],
        },
    ],
    "executive_summary": [
        {
            "id": "executive_summary.customer_overview",
            "label": "Customer overview",
            "description": "Short customer context and business driver summary.",
            "sample_objectives": [
                "Customer description",
                "Business context",
            ],
        },
        {
            "id": "executive_summary.proposed_solution",
            "label": "Proposed solution",
            "description": "Bedrock + RAG proposal framing for APN.",
            "aws_services": ["Amazon Bedrock", "Amazon OpenSearch Service", "Amazon S3"],
            "sample_objectives": [
                "Amazon Bedrock-based solution",
                "RAG / OpenSearch / S3 architecture",
            ],
        },
        {
            "id": "executive_summary.business_value",
            "label": "Business value",
            "description": "Efficiency and ROI-oriented framing for GenAI IC reviewers.",
            "sample_objectives": [
                "Improve operational efficiency",
                "Reduce time spent on repetitive work",
            ],
        },
    ],
    "architecture": [
        {
            "id": "architecture.bedrock_rag",
            "label": "Bedrock + RAG reference",
            "description": "Commonly approved architecture shape for GenAI PoC.",
            "aws_services": [
                "Amazon Bedrock",
                "Amazon OpenSearch Service",
                "AWS Lambda",
                "Amazon S3",
                "Amazon API Gateway",
            ],
            "sample_objectives": [
                "Customer client calls API Gateway",
                "Lambda orchestrates Bedrock with OpenSearch retrieval",
                "S3 stores source documents and exports",
            ],
        },
        {
            "id": "architecture.agentic_workflow",
            "label": "Agentic workflow",
            "description": "Multi-agent pattern using Bedrock AgentCore.",
            "aws_services": ["Amazon Bedrock", "AWS Lambda", "Amazon DynamoDB"],
            "sample_objectives": [
                "Parent orchestrator routes to discovery / architecture / cost subagents",
                "AgentCore Memory holds customer context",
                "DynamoDB stores document state and history",
            ],
        },
    ],
    "cost_breakdown": [
        {
            "id": "cost_breakdown.calculator_reference",
            "label": "AWS Calculator reference",
            "description": "APN / GenAI IC expects a Calculator URL and Year 1 ARR basis.",
            "sample_objectives": [
                "Provide AWS Calculator URL",
                "Document Year 1 ARR basis",
                "Document SOW cost basis",
            ],
        },
        {
            "id": "cost_breakdown.funding_formula",
            "label": "Funding formula",
            "description": "Deterministic funding calculation used by the Reviewer lint.",
            "sample_objectives": [
                "Eligible Funding Amount = min(Year 1 ARR * 25%, SOW Cost, 125,000)",
            ],
        },
    ],
    "scope_of_work": [
        {
            "id": "scope_of_work.core_tasks",
            "label": "Core tasks",
            "description": "Typical PoC task list.",
            "sample_objectives": [
                "Discovery and requirements analysis",
                "Build RAG / Bedrock workflow",
                "Validation and handover",
            ],
        },
    ],
    "stakeholders": [
        {
            "id": "stakeholders.core_roles",
            "label": "Core stakeholder roles",
            "description": "Typical roles aligned with APN submission.",
            "sample_objectives": [
                "Executive sponsor",
                "Project manager",
                "Solutions architect",
                "Security reviewer",
            ],
        },
    ],
    "milestones": [
        {
            "id": "milestones.three_phase_poc",
            "label": "3-phase PoC",
            "description": "Default phase structure reused by Resource Planning.",
            "sample_objectives": [
                "Discovery and Design",
                "Build and Integration",
                "Validation and Handover",
            ],
        },
    ],
    "acceptance": [
        {
            "id": "acceptance.criteria",
            "label": "Acceptance criteria",
            "description": "Commonly approved acceptance-check steps.",
            "sample_objectives": [
                "Functional checks pass against defined PoC scope",
                "Non-functional targets met within budget and latency bounds",
                "Documentation and handover complete",
            ],
        },
    ],
}


def _get_section_recommendations(section: str) -> list[dict]:
    """Return preset / dropdown recommendations for a section.

    This is the static baseline. A future version can enrich this with
    per-customer DynamoDB metadata or Bedrock KB context without changing
    the response shape.
    """
    key = (section or "").strip()
    if not key:
        return []
    return [dict(item) for item in _SECTION_RECOMMENDATIONS.get(key, [])]


def _make_issue(severity: str, code: str, message: str, section: str, question: str = "") -> dict:
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "section": section,
        "question": question,
    }


_REVIEW_RULE_CATALOG: list[dict] = [
    {
        "rule_id": "BUSINESS_CASE_COMMITMENT",
        "category": "Business Case & Commitment",
        "title": "Business case and sponsor commitment",
        "description": "Confirms the customer problem, expected business value, sponsor ownership, and path from PoC to production are documented.",
        "severity": "High",
        "pass_criteria": "Business driver, measurable value, sponsor or owner, and production commitment are present.",
        "warning_criteria": "Some business value or stakeholder evidence exists but commitment or measurable value is incomplete.",
        "fail_criteria": "Business case exists only as generic language or lacks ownership and value evidence.",
        "related_sections": ["executive_summary", "stakeholders", "success_criteria"],
        "evidence_terms": {
            "business problem or value": ["business", "problem", "value", "roi", "efficiency", "improve", "reduce"],
            "customer/sponsor commitment": ["sponsor", "owner", "stakeholder", "commitment", "customer"],
            "production path": ["production", "go-live", "deployment", "operate"],
        },
    },
    {
        "rule_id": "SUCCESS_CRITERIA_MEASURABLE",
        "category": "Business Case & Commitment",
        "title": "Measurable success criteria",
        "description": "Checks that success criteria are measurable enough to support readiness review and SOW acceptance.",
        "severity": "High",
        "pass_criteria": "Quantified KPIs, acceptance thresholds, and validation method are present.",
        "warning_criteria": "Success criteria exist but are partially qualitative or lack validation details.",
        "fail_criteria": "Success criteria are missing or do not define measurable outcomes.",
        "related_sections": ["success_criteria", "acceptance"],
        "evidence_terms": {
            "quantified KPI": ["%", "percent", "latency", "accuracy", "seconds", "minutes", "target", "threshold"],
            "validation method": ["validate", "test", "measure", "acceptance", "criteria"],
        },
    },
    {
        "rule_id": "PRODUCTION_USAGE_ASSUMPTIONS",
        "category": "Production Usage & Cost Assumptions",
        "title": "Production usage assumptions",
        "description": "Verifies that workload volume, usage pattern, and production-cost assumptions are explicit.",
        "severity": "High",
        "pass_criteria": "Usage volume, traffic or user assumptions, and operating period are documented.",
        "warning_criteria": "Some production or usage assumptions exist but sizing is incomplete.",
        "fail_criteria": "Production usage assumptions are absent from cost and architecture sections.",
        "related_sections": ["cost_breakdown", "architecture", "assumptions"],
        "evidence_terms": {
            "usage volume": ["user", "request", "token", "document", "volume", "traffic", "monthly"],
            "production assumption": ["production", "workload", "usage", "operating", "mrr", "arr"],
        },
    },
    {
        "rule_id": "COST_ASSUMPTION_BASIS",
        "category": "Production Usage & Cost Assumptions",
        "title": "Cost assumption basis",
        "description": "Checks that AWS costs are supported by calculator evidence or a service-level estimate basis.",
        "severity": "Critical",
        "pass_criteria": "AWS Calculator URL or service-level cost table and monthly/yearly basis are present.",
        "warning_criteria": "Cost values exist but the source or service-level basis is partial.",
        "fail_criteria": "Cost basis is missing or cannot be traced to calculator/service assumptions.",
        "related_sections": ["cost_breakdown", "resources_cost_estimates"],
        "evidence_terms": {
            "calculator or estimate": ["calculator", "estimate", "cost", "monthly", "arr", "mrr"],
            "service-level basis": ["breakdown", "service", "bedrock", "lambda", "s3", "opensearch"],
        },
    },
    {
        "rule_id": "BEDROCK_EVIDENCE_MISSING",
        "category": "Architecture & Service Sizing",
        "title": "Amazon Bedrock evidence",
        "description": "Confirms Amazon Bedrock is explicitly included where this is a GenAI IC/APN readiness review.",
        "severity": "Critical",
        "pass_criteria": "Amazon Bedrock, model usage, or related GenAI service evidence is present.",
        "warning_criteria": "GenAI intent exists but Bedrock usage detail is thin.",
        "fail_criteria": "Bedrock evidence is missing from the architecture.",
        "related_sections": ["architecture"],
        "evidence_terms": {
            "Amazon Bedrock": ["bedrock"],
            "model or generative AI usage": ["model", "llm", "genai", "generative", "rag", "agent"],
        },
    },
    {
        "rule_id": "ARCHITECTURE_SERVICE_SIZING",
        "category": "Architecture & Service Sizing",
        "title": "Architecture and service sizing",
        "description": "Checks that listed AWS services are tied to workload, sizing, and implementation purpose.",
        "severity": "High",
        "pass_criteria": "Architecture overview, service list, and sizing rationale are present.",
        "warning_criteria": "Services are listed but sizing or implementation rationale is incomplete.",
        "fail_criteria": "Architecture does not explain how services support the workload.",
        "related_sections": ["architecture"],
        "evidence_terms": {
            "service list": ["service", "bedrock", "lambda", "s3", "opensearch", "api gateway", "dynamodb"],
            "sizing rationale": ["sizing", "capacity", "throughput", "latency", "volume", "scale"],
            "architecture overview": ["overview", "architecture", "flow", "component"],
        },
    },
    {
        "rule_id": "DEPLOYMENT_SCALING_PLAN",
        "category": "Deployment & Scaling Plan",
        "title": "Deployment and scaling plan",
        "description": "Validates that deployment approach, scaling behavior, and operational ownership are documented.",
        "severity": "Medium",
        "pass_criteria": "Deployment steps, scale assumptions, and operations/handover plan are present.",
        "warning_criteria": "Deployment plan exists but scaling or ownership details are partial.",
        "fail_criteria": "Deployment/scaling plan is missing.",
        "related_sections": ["scope_of_work", "milestones", "architecture"],
        "evidence_terms": {
            "deployment steps": ["deploy", "deployment", "release", "handover", "environment"],
            "scaling plan": ["scale", "scaling", "autoscale", "capacity", "concurrency"],
            "owner or operation": ["operate", "owner", "support", "handover"],
        },
    },
    {
        "rule_id": "MILESTONES_DELIVERABLES",
        "category": "Deployment & Scaling Plan",
        "title": "Milestones and deliverables",
        "description": "Checks that timeline, phases, and deliverables are specific enough for SOW execution.",
        "severity": "Medium",
        "pass_criteria": "Phases, dates or durations, deliverables, and acceptance checkpoints are present.",
        "warning_criteria": "Milestones exist but deliverables or checkpoints are incomplete.",
        "fail_criteria": "Milestones and deliverables are missing.",
        "related_sections": ["milestones", "scope_of_work", "acceptance"],
        "evidence_terms": {
            "phase or timeline": ["phase", "week", "date", "duration", "milestone"],
            "deliverable": ["deliverable", "output", "handover", "document"],
            "acceptance checkpoint": ["acceptance", "review", "sign-off", "complete"],
        },
    },
    {
        "rule_id": "RISK_GOVERNANCE_MISSING",
        "category": "Risk Assessment & Governance",
        "title": "Risk assessment and governance",
        "description": "Confirms risk, assumptions, security, data governance, and customer responsibilities are covered.",
        "severity": "High",
        "pass_criteria": "Risks, mitigations, governance/security controls, and customer dependencies are present.",
        "warning_criteria": "Risk or governance content exists but mitigation or ownership is incomplete.",
        "fail_criteria": "Risk and governance evidence is missing.",
        "related_sections": ["assumptions", "scope_of_work", "architecture"],
        "evidence_terms": {
            "risk or assumption": ["risk", "assumption", "dependency", "constraint"],
            "mitigation or governance": ["mitigation", "governance", "security", "privacy", "compliance", "control"],
            "customer responsibility": ["customer", "provide", "access", "data"],
        },
    },
    {
        "rule_id": "SCOPE_BOUNDARY",
        "category": "Risk Assessment & Governance",
        "title": "Scope boundaries and exclusions",
        "description": "Checks that in-scope and out-of-scope work are clear enough to avoid SOW ambiguity.",
        "severity": "Medium",
        "pass_criteria": "In-scope, out-of-scope, dependencies, and change control are documented.",
        "warning_criteria": "Scope exists but exclusions or change control are partial.",
        "fail_criteria": "Scope boundary is missing.",
        "related_sections": ["scope_of_work", "assumptions"],
        "evidence_terms": {
            "in scope": ["scope", "in-scope", "task", "activity"],
            "out of scope": ["out-of-scope", "excluded", "exclusion", "not included"],
            "change control": ["change", "request", "approval"],
        },
    },
    {
        "rule_id": "ARR_MISSING",
        "category": "Funding / ARR / SOW Cost",
        "title": "Year 1 ARR basis",
        "description": "Validates that Year 1 ARR or MRR-derived ARR is available for funding formula review.",
        "severity": "Critical",
        "pass_criteria": "Year 1 ARR is present or can be calculated from MRR.",
        "warning_criteria": "MRR exists but ARR should be confirmed before submission.",
        "fail_criteria": "ARR and MRR are both missing or zero.",
        "related_sections": ["cost_breakdown"],
        "evidence_terms": {
            "ARR or MRR": ["arr", "mrr", "annual recurring", "monthly recurring"],
        },
    },
    {
        "rule_id": "SOW_COST_MISSING",
        "category": "Funding / ARR / SOW Cost",
        "title": "SOW cost basis",
        "description": "Checks that SOW cost is present for eligibility calculation and customer funding discussion.",
        "severity": "Critical",
        "pass_criteria": "SOW cost or total resource estimate is present.",
        "warning_criteria": "Resource cost exists but SOW cost should be explicitly confirmed.",
        "fail_criteria": "SOW cost basis is missing.",
        "related_sections": ["cost_breakdown", "resources_cost_estimates"],
        "evidence_terms": {
            "SOW or total cost": ["sow", "total_cost", "total cost", "eligible", "funding"],
        },
    },
    {
        "rule_id": "FUNDING_FORMULA",
        "category": "Funding / ARR / SOW Cost",
        "title": "Funding formula calculation",
        "description": "Verifies that the eligible funding amount can be calculated from ARR, SOW cost, and cap.",
        "severity": "High",
        "pass_criteria": "ARR, SOW cost, eligible amount, and formula are consistent.",
        "warning_criteria": "Inputs exist but eligible amount or formula needs confirmation.",
        "fail_criteria": "Funding formula cannot be evaluated from available inputs.",
        "related_sections": ["cost_breakdown", "resources_cost_estimates"],
        "evidence_terms": {
            "formula": ["min", "25%", "125000", "eligible", "funding"],
            "inputs": ["arr", "sow", "cost"],
        },
    },
    {
        "rule_id": "APN_TEMPLATE_COMPLETENESS",
        "category": "APN Template Completeness",
        "title": "APN template required sections",
        "description": "Checks that all APN v2 document sections have content for submission readiness.",
        "severity": "High",
        "pass_criteria": "All required APN v2 sections contain meaningful content.",
        "warning_criteria": "Most required sections are populated but one or more sections are thin.",
        "fail_criteria": "Required APN v2 sections are missing.",
        "related_sections": [
            "cover", "executive_summary", "stakeholders", "success_criteria",
            "assumptions", "scope_of_work", "architecture", "milestones",
            "cost_breakdown", "acceptance", "resources_cost_estimates",
        ],
        "evidence_terms": {
            "required section content": ["project", "summary", "scope", "architecture", "cost", "acceptance", "resource"],
        },
    },
    {
        "rule_id": "CUSTOMER_METADATA",
        "category": "APN Template Completeness",
        "title": "Customer and project metadata",
        "description": "Confirms customer/project identity fields are populated for generated APN documents.",
        "severity": "Low",
        "pass_criteria": "Customer and project metadata are confirmed.",
        "warning_criteria": "Some metadata exists but customer or project fields need confirmation.",
        "fail_criteria": "Customer/project metadata is missing.",
        "related_sections": ["meta", "cover"],
        "evidence_terms": {
            "customer": ["customer", "client"],
            "project": ["project", "title", "name"],
        },
    },
    {
        "rule_id": "ARCHITECTURE_COST_ALIGNMENT_MISSING",
        "category": "Architecture-Cost Alignment",
        "title": "Architecture-cost alignment",
        "description": "Ensures services in architecture are reflected in cost evidence.",
        "severity": "High",
        "pass_criteria": "Architecture services map to calculator URL or service-level cost rows.",
        "warning_criteria": "Some cost evidence exists but service mapping is incomplete.",
        "fail_criteria": "Architecture services have no cost basis.",
        "related_sections": ["architecture", "cost_breakdown"],
        "evidence_terms": {
            "architecture service": ["bedrock", "lambda", "s3", "opensearch", "api gateway", "dynamodb"],
            "cost mapping": ["calculator", "breakdown", "cost", "estimate"],
        },
    },
    {
        "rule_id": "BEDROCK_COST_NOT_REFLECTED",
        "category": "Architecture-Cost Alignment",
        "title": "Bedrock cost reflected",
        "description": "Checks that Bedrock usage in architecture is reflected in cost assumptions or calculator evidence.",
        "severity": "Medium",
        "pass_criteria": "Bedrock appears in both architecture and cost basis, or calculator URL covers service costs.",
        "warning_criteria": "Bedrock appears in architecture and general cost evidence exists, but Bedrock-specific basis is thin.",
        "fail_criteria": "Bedrock appears in architecture but no Bedrock cost row or calculator URL is present.",
        "related_sections": ["architecture", "cost_breakdown"],
        "evidence_terms": {
            "Bedrock architecture": ["bedrock"],
            "Bedrock cost basis": ["bedrock", "calculator", "token", "model", "cost"],
        },
    },
]


_REVIEW_RULE_SEED_VERSION = "2026-05-09.v1"
_REVIEW_RULE_SOURCE_DOCUMENTS = [
    "AWS펀드 프로그램.txt",
    "GenAIIC PLD 펀딩 가이드 2025.txt",
    "SOW Pre-Submission Checklist for MegazoneCloud (한글본).docx.txt",
]
_REVIEW_RULE_ITEM_PREFIX = "review_rule#"
_REVIEW_RULE_CUSTOM_TYPE = "review_rule_custom"
_REVIEW_RULE_OVERRIDE_TYPE = "review_rule_override"
_REVIEW_RULE_SEVERITIES = {"Critical", "High", "Medium", "Low", "Info"}
_REVIEW_RULE_EVALUATION_TYPES = {"static", "llm", "hybrid"}


def _seed_rule(
    rule_id: str,
    category_en: str,
    category_kr: str,
    title_en: str,
    title_kr: str,
    description_en: str,
    description_kr: str,
    severity: str,
    evaluation_type: str,
    related_sections: list[str],
    pass_criteria_en: list[str],
    pass_criteria_kr: list[str],
    warning_criteria_en: list[str],
    warning_criteria_kr: list[str],
    fail_criteria_en: list[str],
    fail_criteria_kr: list[str],
    recommendation_template_en: str,
    recommendation_template_kr: str,
    source: str,
    evidence_terms: dict[str, list[str]] | None = None,
) -> dict:
    now = "2026-05-09T00:00:00+00:00"
    return {
        "rule_id": rule_id,
        "enabled": True,
        "custom": False,
        "category_en": category_en,
        "category_kr": category_kr,
        "title_en": title_en,
        "title_kr": title_kr,
        "description_en": description_en,
        "description_kr": description_kr,
        "severity": severity,
        "evaluation_type": evaluation_type,
        "related_sections": related_sections,
        "pass_criteria_en": pass_criteria_en,
        "pass_criteria_kr": pass_criteria_kr,
        "warning_criteria_en": warning_criteria_en,
        "warning_criteria_kr": warning_criteria_kr,
        "fail_criteria_en": fail_criteria_en,
        "fail_criteria_kr": fail_criteria_kr,
        "recommendation_template_en": recommendation_template_en,
        "recommendation_template_kr": recommendation_template_kr,
        "source": source,
        "created_at": now,
        "updated_at": now,
        "created_by": "system",
        "updated_by": "system",
        "evidence_terms": evidence_terms or {},
    }


_REVIEW_RULE_CATALOG = [
    _seed_rule("bedrock_included", "GenAI IC Eligibility", "GenAI IC 자격", "Amazon Bedrock is included as a core service", "Amazon Bedrock이 핵심 서비스로 포함되어 있는가", "The project must clearly include Amazon Bedrock as a core GenAI service.", "프로젝트에는 Amazon Bedrock이 핵심 GenAI 서비스로 명확히 포함되어야 합니다.", "Critical", "hybrid", ["architecture", "scope_of_work", "cost_breakdown"], ["Amazon Bedrock is explicitly listed as a core service.", "Bedrock usage is tied to the use case."], ["Amazon Bedrock이 핵심 서비스로 명시되어 있습니다.", "Bedrock 사용 목적이 Use Case와 연결되어 있습니다."], ["Bedrock is mentioned but its role is unclear."], ["Bedrock은 언급되었지만 역할이 불명확합니다."], ["Amazon Bedrock is not mentioned."], ["Amazon Bedrock이 언급되지 않았습니다."], "Add Amazon Bedrock as a core service and explain how it powers the GenAI use case.", "Amazon Bedrock을 핵심 서비스로 추가하고 GenAI Use Case에서 어떤 역할을 하는지 설명하십시오.", "AWS Fund Program / GenAIIC PLD Funding Guide", {"Amazon Bedrock": ["bedrock"], "use case linkage": ["use case", "workflow", "rag", "agent", "genai", "generative"]}),
    _seed_rule("funding_amount_rule", "Funding", "펀딩", "Funding amount follows min(25% ARR, SOW Cost, $125K)", "펀딩 금액이 25% ARR, SOW Cost, $125K 중 작은 값 기준을 따르는가", "The requested funding amount should be justified against ARR, SOW Cost, and the $125K cap.", "요청 펀딩 금액은 ARR, SOW Cost, $125K 한도 기준으로 검증되어야 합니다.", "Critical", "static", ["cost_breakdown", "resources_cost_estimates"], ["ARR, SOW Cost, and requested funding amount are present.", "The calculated eligible funding amount is clear."], ["ARR, SOW Cost, 요청 펀딩 금액이 모두 존재합니다.", "지원 가능 금액 계산 결과가 명확합니다."], ["Some funding inputs exist but calculation is incomplete."], ["일부 펀딩 입력값은 있으나 계산이 불완전합니다."], ["Funding amount is requested without ARR or SOW Cost basis."], ["ARR 또는 SOW Cost 근거 없이 펀딩 금액이 요청되었습니다."], "Add ARR, SOW Cost, requested funding amount, and calculate min(ARR x 25%, SOW Cost, $125K).", "ARR, SOW Cost, 요청 펀딩 금액을 추가하고 min(ARR x 25%, SOW Cost, $125K)를 계산하십시오.", "AWS Fund Program", {"funding inputs": ["arr", "sow", "funding", "eligible", "125"]}),
    _seed_rule("calculator_link_exists", "AWS ARR", "AWS ARR", "AWS Calculator link is provided", "AWS Calculator 링크가 제공되었는가", "The Project Plan/SOW should include an AWS Online Calculator link for possible AWS services.", "Project Plan/SOW에는 가능한 AWS 서비스에 대한 AWS Online Calculator 링크가 포함되어야 합니다.", "Critical", "static", ["cost_breakdown"], ["A valid AWS Calculator URL is present."], ["유효한 AWS Calculator URL이 존재합니다."], ["A calculator reference exists but URL is missing or invalid."], ["Calculator 언급은 있으나 URL이 없거나 유효하지 않습니다."], ["No AWS Calculator link is provided."], ["AWS Calculator 링크가 제공되지 않았습니다."], "Add an AWS Calculator share URL for all supported AWS services.", "지원 가능한 AWS 서비스에 대한 AWS Calculator 공유 URL을 추가하십시오.", "GenAIIC PLD Funding Guide", {"calculator URL": ["calculator", "https://", "calculator.aws"]}),
    _seed_rule("bedrock_cost_estimate_exists", "AWS ARR", "AWS ARR", "Bedrock cost is estimated separately when not available in Calculator", "Calculator에 없는 Bedrock 비용이 별도 산정되었는가", "If Bedrock is not available in the Calculator estimate, a separate spreadsheet-style estimate should be included.", "Bedrock 비용이 Calculator에 포함되지 않는 경우 별도 산정 근거가 포함되어야 합니다.", "Critical", "hybrid", ["cost_breakdown", "assumptions"], ["Bedrock token usage assumptions are documented.", "Bedrock monthly or annual cost estimate is present."], ["Bedrock Token 사용 가정이 문서화되어 있습니다.", "Bedrock 월간 또는 연간 비용 산정이 존재합니다."], ["Bedrock cost exists but token assumptions are weak."], ["Bedrock 비용은 있으나 Token 가정이 약합니다."], ["No Bedrock cost or token estimate is provided."], ["Bedrock 비용 또는 Token 산정이 제공되지 않았습니다."], "Add Bedrock input/output token assumptions and estimated monthly/annual cost.", "Bedrock input/output token 가정과 월/연 비용 산정을 추가하십시오.", "GenAIIC PLD Funding Guide / SOW Checklist", {"Bedrock cost": ["bedrock", "cost", "mrr", "arr"], "token assumptions": ["token", "input", "output"]}),
    _seed_rule("total_arr_documented", "AWS ARR", "AWS ARR", "Total AWS ARR is documented", "전체 AWS ARR이 문서화되었는가", "The document should state total AWS ARR, combining Calculator-based and separate estimates if needed.", "문서에는 Calculator 기반 비용과 별도 산정을 합산한 전체 AWS ARR이 명시되어야 합니다.", "Critical", "static", ["cost_breakdown"], ["Total AWS ARR is explicitly stated."], ["전체 AWS ARR이 명확히 기재되어 있습니다."], ["MRR exists but ARR is not clearly calculated."], ["MRR은 있으나 ARR 계산이 명확하지 않습니다."], ["No AWS ARR or MRR basis is provided."], ["AWS ARR 또는 MRR 근거가 제공되지 않았습니다."], "Add total AWS MRR/ARR and show how it was calculated.", "전체 AWS MRR/ARR과 계산 방식을 추가하십시오.", "GenAIIC PLD Funding Guide", {"ARR or MRR": ["arr", "mrr", "annual", "monthly"]}),
    _seed_rule("genai_arr_percentage", "AWS ARR", "AWS ARR", "Core GenAI service percentage in ARR is documented", "전체 ARR 중 핵심 GenAI 서비스 비중이 문서화되었는가", "The document should mention the percentage of core AWS GenAI services in total AWS ARR.", "문서에는 전체 AWS ARR 중 핵심 GenAI 서비스 비중이 명시되어야 합니다.", "High", "llm", ["cost_breakdown"], ["Core GenAI service percentage is stated."], ["핵심 GenAI 서비스 비중이 명시되어 있습니다."], ["GenAI service costs are present but percentage is not calculated."], ["GenAI 서비스 비용은 있으나 비중 계산이 없습니다."], ["No GenAI ARR percentage or comparable explanation is provided."], ["GenAI ARR 비중 또는 유사 설명이 없습니다."], "Add the percentage of core AWS GenAI services within total AWS ARR.", "전체 AWS ARR 중 핵심 AWS GenAI 서비스 비중을 추가하십시오.", "GenAIIC PLD Funding Guide", {"GenAI percentage": ["%", "percentage", "genai", "bedrock"]}),
    _seed_rule("sow_cost_breakdown_exists", "SOW Cost", "SOW 비용", "SOW cost breakdown is documented", "SOW Cost Breakdown이 문서화되었는가", "The document should break down SOW cost by activity, role, phase, or partner/customer contribution.", "문서에는 활동, 역할, 단계 또는 Partner/Customer 분담 기준으로 SOW 비용이 분해되어야 합니다.", "Critical", "hybrid", ["resources_cost_estimates"], ["SOW cost breakdown exists.", "Role/rate/hour or contribution basis is clear."], ["SOW 비용 분해가 존재합니다.", "Role/rate/hour 또는 비용 분담 기준이 명확합니다."], ["Total SOW cost exists but detailed breakdown is weak."], ["총 SOW 비용은 있으나 상세 분해가 약합니다."], ["No SOW cost breakdown is provided."], ["SOW 비용 분해가 제공되지 않았습니다."], "Add a SOW cost breakdown by role, rate, hours, phase, and contribution owner.", "역할, 단가, 시간, 단계, 비용 분담 주체 기준으로 SOW 비용 분해를 추가하십시오.", "GenAIIC PLD Funding Guide / SOW Checklist", {"SOW cost breakdown": ["role", "rate", "hour", "phase", "total_cost", "contribution"]}),
    _seed_rule("partner_customer_cost_split", "SOW Cost", "SOW 비용", "Partner and customer cost split is clear", "Partner / Customer 비용 분담이 명확한가", "The cost split between AWS partner and customer should be clear where applicable.", "해당되는 경우 AWS Partner와 Customer 간 비용 분담이 명확해야 합니다.", "High", "llm", ["resources_cost_estimates", "cost_breakdown"], ["Partner/customer contribution split is documented."], ["Partner/Customer 비용 분담이 문서화되어 있습니다."], ["Contribution is implied but not clearly stated."], ["비용 분담이 암시되어 있으나 명확하지 않습니다."], ["No cost split or contribution ownership is provided."], ["비용 분담 또는 부담 주체가 제공되지 않았습니다."], "Add partner/customer contribution details for SOW cost.", "SOW 비용에 대한 Partner/Customer 분담 내용을 추가하십시오.", "GenAIIC PLD Funding Guide", {"cost split": ["partner", "customer", "contribution", "split"]}),
    _seed_rule("use_case_defined", "Use Case", "유스케이스", "Customer use case is clearly described", "고객 Use Case가 명확히 설명되었는가", "The document should clearly describe the customer use case and target business workflow.", "문서에는 고객 Use Case와 대상 업무 흐름이 명확히 설명되어야 합니다.", "Critical", "llm", ["executive_summary", "scope_of_work", "architecture"], ["Use case is specific and tied to customer business workflow."], ["Use Case가 구체적이며 고객 업무 흐름과 연결되어 있습니다."], ["Use case is present but generic."], ["Use Case는 있으나 일반적입니다."], ["Use case is missing or unclear."], ["Use Case가 없거나 불명확합니다."], "Add a concise customer-specific GenAI use case description.", "고객별 GenAI Use Case 설명을 구체적으로 추가하십시오.", "GenAIIC PLD Funding Guide / SOW Checklist", {"use case": ["use case", "workflow", "business", "customer", "업무"]}),
    _seed_rule("business_problem_defined", "Business Case & Commitment", "비즈니스 케이스 및 커밋먼트", "Customer problem and pain point are specific", "고객 문제와 Pain Point가 구체적인가", "The document should describe why the customer is investing and what problem is being solved.", "문서에는 고객이 왜 투자하는지와 어떤 문제를 해결하려는지 설명되어야 합니다.", "High", "llm", ["executive_summary"], ["Specific pain points, current workload, time, cost, or error rate are described."], ["구체적인 Pain Point, 현재 업무량, 시간, 비용, 오류율 등이 설명되어 있습니다."], ["Pain point exists but lacks measurable detail."], ["Pain Point는 있으나 정량적 세부정보가 부족합니다."], ["No specific customer problem is described."], ["구체적인 고객 문제가 설명되지 않았습니다."], "Add specific customer pain points such as manual workload, search time, error rate, or cost.", "수작업량, 검색 시간, 오류율, 비용 등 구체적인 고객 Pain Point를 추가하십시오.", "SOW Pre-Submission Checklist", {"pain point": ["problem", "pain", "manual", "time", "cost", "error"]}),
    _seed_rule("business_value_quantified", "Business Case & Commitment", "비즈니스 케이스 및 커밋먼트", "Business value is quantified", "비즈니스 가치가 수치화되었는가", "The document should quantify expected business value such as time savings, cost reduction, or productivity improvement.", "문서에는 시간 절감, 비용 절감, 생산성 개선 등 기대 비즈니스 가치가 수치화되어야 합니다.", "High", "llm", ["executive_summary", "success_criteria"], ["Business value is expressed with numbers or measurable outcomes."], ["비즈니스 가치가 수치 또는 측정 가능한 결과로 표현되어 있습니다."], ["Business value is described qualitatively only."], ["비즈니스 가치가 정성적으로만 설명되어 있습니다."], ["No business value is stated."], ["비즈니스 가치가 명시되지 않았습니다."], "Add quantified value such as time saved, cost saved, automation rate, or accuracy improvement.", "절감 시간, 절감 비용, 자동화율, 정확도 개선 등 수치화된 가치를 추가하십시오.", "SOW Pre-Submission Checklist", {"quantified value": ["%", "save", "reduce", "increase", "accuracy", "automation", "cost"]}),
    _seed_rule("roi_basis_exists", "Business Case & Commitment", "비즈니스 케이스 및 커밋먼트", "ROI basis is documented", "ROI 계산 근거가 있는가", "The document should include ROI logic such as before/after effort, cost savings, or TCO comparison.", "문서에는 전후 업무량, 비용 절감, TCO 비교 등 ROI 계산 논리가 포함되어야 합니다.", "High", "llm", ["executive_summary", "success_criteria", "cost_breakdown"], ["ROI calculation or value formula is present."], ["ROI 계산 또는 가치 산식이 존재합니다."], ["ROI is implied but not calculated."], ["ROI가 암시되어 있으나 계산되지 않았습니다."], ["No ROI basis is provided."], ["ROI 근거가 제공되지 않았습니다."], "Add a simple ROI calculation using time saved, hourly cost, annual volume, or TCO.", "절감 시간, 시간당 비용, 연간 처리량 또는 TCO 기반의 간단한 ROI 계산을 추가하십시오.", "SOW Pre-Submission Checklist", {"ROI basis": ["roi", "tco", "saving", "before", "after", "cost"]}),
    _seed_rule("executive_sponsor_exists", "Business Case & Commitment", "비즈니스 케이스 및 커밋먼트", "Executive sponsor is identified", "Executive Sponsor가 명시되었는가", "The document should identify the executive sponsor or decision owner where available.", "문서에는 가능하면 Executive Sponsor 또는 의사결정 책임자가 명시되어야 합니다.", "Medium", "llm", ["stakeholders", "executive_summary"], ["Executive sponsor or decision owner is identified."], ["Executive Sponsor 또는 의사결정 책임자가 식별되어 있습니다."], ["Stakeholders exist but sponsor is unclear."], ["이해관계자는 있으나 Sponsor가 불명확합니다."], ["No sponsor or decision owner is identified."], ["Sponsor 또는 의사결정자가 식별되지 않았습니다."], "Add executive sponsor or decision owner information if available.", "가능한 경우 Executive Sponsor 또는 의사결정자 정보를 추가하십시오.", "SOW Pre-Submission Checklist", {"sponsor": ["sponsor", "decision", "owner", "executive", "stakeholder"]}),
    _seed_rule("production_commitment_exists", "Business Case & Commitment", "비즈니스 케이스 및 커밋먼트", "Production commitment or production path is documented", "Production 전환 계획 또는 커밋먼트가 문서화되었는가", "The document should describe the plan or condition for moving from PoC to production.", "문서에는 PoC 이후 Production 전환 계획 또는 조건이 설명되어야 합니다.", "Critical", "llm", ["executive_summary", "milestones", "acceptance"], ["Production timeline, condition, or commitment is documented."], ["Production 일정, 조건 또는 커밋먼트가 문서화되어 있습니다."], ["Production is mentioned but timeline or condition is weak."], ["Production은 언급되었으나 일정 또는 조건이 약합니다."], ["No production path or commitment is documented."], ["Production 전환 경로 또는 커밋먼트가 문서화되지 않았습니다."], "Add a production transition plan or condition after successful PoC.", "PoC 성공 후 Production 전환 계획 또는 조건을 추가하십시오.", "SOW Pre-Submission Checklist / GenAIIC PLD Funding Guide", {"production path": ["production", "go-live", "rollout", "commitment", "timeline"]}),
    _seed_rule("success_criteria_measurable", "Success Criteria", "성공 기준", "Success criteria are measurable", "성공 기준이 정량적으로 측정 가능한가", "Success criteria should include measurable KPIs such as accuracy, latency, automation rate, or satisfaction.", "성공 기준에는 정확도, 응답시간, 자동화율, 만족도 등 측정 가능한 KPI가 포함되어야 합니다.", "High", "llm", ["success_criteria"], ["Success criteria include clear numeric targets."], ["성공 기준에 명확한 정량 목표가 포함되어 있습니다."], ["Success criteria exist but are mostly qualitative."], ["성공 기준은 있으나 대부분 정성적입니다."], ["No measurable success criteria are provided."], ["측정 가능한 성공 기준이 제공되지 않았습니다."], "Add measurable targets such as accuracy, response time, automation rate, or user satisfaction.", "정확도, 응답시간, 자동화율, 사용자 만족도 등 측정 가능한 목표를 추가하십시오.", "SOW Pre-Submission Checklist", {"numeric targets": ["%", "accuracy", "latency", "response", "automation", "satisfaction", "kpi"]}),
    _seed_rule("usage_volume_exists", "Production Usage & Cost Assumptions", "프로덕션 사용량 및 비용 가정", "Production request volume is documented", "프로덕션 요청량이 문서화되었는가", "The document should include expected users, request volume, peak usage, or usage period.", "문서에는 예상 사용자 수, 요청량, 피크 사용량 또는 사용 시간대가 포함되어야 합니다.", "Critical", "llm", ["assumptions", "cost_breakdown"], ["Expected user count and daily/monthly request volume are provided."], ["예상 사용자 수와 일/월 요청량이 제공되어 있습니다."], ["Usage is described qualitatively but lacks concrete numbers."], ["사용량이 정성적으로만 설명되고 구체적인 수치가 부족합니다."], ["No production usage volume is provided."], ["프로덕션 사용량 가정이 제공되지 않았습니다."], "Add expected users, daily requests, peak concurrency, and usage period.", "예상 사용자 수, 일 요청량, 피크 동시성, 사용 시간대를 추가하십시오.", "SOW Pre-Submission Checklist", {"usage volume": ["user", "request", "daily", "monthly", "peak", "concurrency"]}),
    _seed_rule("token_assumption_exists", "Production Usage & Cost Assumptions", "프로덕션 사용량 및 비용 가정", "Bedrock token assumptions are documented", "Bedrock Token 사용 가정이 문서화되었는가", "The document should include input/output token assumptions for Bedrock usage.", "문서에는 Bedrock 사용에 대한 input/output token 가정이 포함되어야 합니다.", "Critical", "llm", ["assumptions", "cost_breakdown"], ["Input/output token assumptions and monthly token volume are provided."], ["Input/output token 가정과 월간 token 사용량이 제공되어 있습니다."], ["Token usage exists but calculation is incomplete."], ["Token 사용량은 있으나 계산이 불완전합니다."], ["No Bedrock token assumption is provided."], ["Bedrock Token 가정이 제공되지 않았습니다."], "Add average input/output tokens, requests per user, users, and monthly token calculation.", "평균 input/output token, 사용자별 요청 수, 사용자 수, 월간 token 계산을 추가하십시오.", "SOW Pre-Submission Checklist", {"token assumptions": ["token", "input", "output", "monthly", "request"]}),
    _seed_rule("data_volume_exists", "Production Usage & Cost Assumptions", "프로덕션 사용량 및 비용 가정", "Data volume and retention assumptions are documented", "데이터 규모와 보관 가정이 문서화되었는가", "The document should include data size, document count, storage, vector index, or retention assumptions.", "문서에는 데이터 크기, 문서 수, 스토리지, 벡터 인덱스, 보관 기간 가정이 포함되어야 합니다.", "High", "llm", ["assumptions", "architecture", "cost_breakdown"], ["Data volume and retention assumptions are documented."], ["데이터 규모와 보관 가정이 문서화되어 있습니다."], ["Data source is described but volume or retention is missing."], ["데이터 소스는 설명되었으나 규모 또는 보관 기간이 없습니다."], ["No data volume or retention assumption is provided."], ["데이터 규모 또는 보관 가정이 제공되지 않았습니다."], "Add document count, data size, vector index size, and retention period.", "문서 수, 데이터 크기, 벡터 인덱스 크기, 보관 기간을 추가하십시오.", "SOW Pre-Submission Checklist", {"data volume": ["data", "document", "storage", "vector", "retention", "gb", "tb"]}),
    _seed_rule("growth_assumption_exists", "Production Usage & Cost Assumptions", "프로덕션 사용량 및 비용 가정", "Growth assumption is documented", "성장률 또는 확장 가정이 문서화되었는가", "The document should describe expected usage growth or rollout-driven growth.", "문서에는 예상 사용량 증가율 또는 Rollout 기반 확장 가정이 포함되어야 합니다.", "Medium", "llm", ["assumptions", "deployment", "cost_breakdown"], ["Growth rate or rollout growth assumption is provided."], ["성장률 또는 Rollout 기반 증가 가정이 제공되어 있습니다."], ["Growth is implied but not quantified."], ["성장은 암시되어 있으나 정량화되지 않았습니다."], ["No growth assumption is provided."], ["성장률 또는 확장 가정이 제공되지 않았습니다."], "Add monthly growth rate or phased rollout growth assumptions.", "월간 성장률 또는 단계별 Rollout 증가 가정을 추가하십시오.", "SOW Pre-Submission Checklist", {"growth": ["growth", "rollout", "increase", "scale", "%"]}),
    _seed_rule("cost_assumption_detailed", "Production Usage & Cost Assumptions", "프로덕션 사용량 및 비용 가정", "Cost assumptions are detailed by service and usage", "서비스/사용량별 비용 가정이 구체적인가", "Cost estimates should be tied to usage assumptions and service-level details.", "비용 산정은 사용량 가정 및 서비스별 상세 내역과 연결되어야 합니다.", "High", "hybrid", ["cost_breakdown"], ["Cost is documented by service and usage basis."], ["서비스별 및 사용량 기준으로 비용이 문서화되어 있습니다."], ["Cost is listed but assumptions are weak."], ["비용은 나열되어 있으나 가정이 약합니다."], ["No detailed cost assumptions are provided."], ["상세 비용 가정이 제공되지 않았습니다."], "Add service-level cost assumptions including volume, unit, and calculation basis.", "서비스별 사용량, 단위, 계산 기준을 포함한 비용 가정을 추가하십시오.", "SOW Pre-Submission Checklist", {"service cost basis": ["service", "cost", "volume", "unit", "calculation", "breakdown"]}),
    _seed_rule("architecture_diagram_exists", "Architecture & Service Sizing", "아키텍처 및 서비스 사이징", "Architecture diagram is included", "아키텍처 다이어그램이 포함되어 있는가", "The Project Plan/SOW should include an architecture diagram for the use case.", "Project Plan/SOW에는 Use Case에 대한 아키텍처 다이어그램이 포함되어야 합니다.", "Critical", "static", ["architecture"], ["Architecture diagram or diagram artifact exists."], ["아키텍처 다이어그램 또는 다이어그램 아티팩트가 존재합니다."], ["Architecture is described in text but diagram is missing."], ["아키텍처가 텍스트로 설명되었으나 다이어그램이 없습니다."], ["No architecture diagram or equivalent artifact is provided."], ["아키텍처 다이어그램 또는 동등한 아티팩트가 제공되지 않았습니다."], "Add an architecture diagram showing AWS services, data flow, and integration points.", "AWS 서비스, 데이터 흐름, 연동 지점을 보여주는 아키텍처 다이어그램을 추가하십시오.", "GenAIIC PLD Funding Guide / SOW Checklist", {"diagram": ["diagram", "drawio", "image", "architecture"]}),
    _seed_rule("architecture_services_defined", "Architecture & Service Sizing", "아키텍처 및 서비스 사이징", "AWS services and their roles are clearly described", "AWS 서비스와 역할이 명확히 설명되었는가", "The document should describe each key AWS service and why it is used.", "문서에는 주요 AWS 서비스와 사용 이유가 설명되어야 합니다.", "High", "llm", ["architecture"], ["Key AWS services and purposes are clearly described."], ["주요 AWS 서비스와 목적이 명확히 설명되어 있습니다."], ["Services are listed but roles are unclear."], ["서비스는 나열되었으나 역할이 불명확합니다."], ["No clear AWS service description is provided."], ["명확한 AWS 서비스 설명이 제공되지 않았습니다."], "Add service-by-service purpose and role descriptions.", "서비스별 목적과 역할 설명을 추가하십시오.", "SOW Pre-Submission Checklist", {"service roles": ["service", "description", "purpose", "role", "used"]}),
    _seed_rule("architecture_cost_alignment", "Architecture & Service Sizing", "아키텍처 및 서비스 사이징", "Architecture services match cost estimate services", "아키텍처 서비스와 비용 산정 서비스가 일치하는가", "All services in the architecture should be reflected in cost estimates, and cost items should appear in architecture.", "아키텍처에 있는 모든 서비스는 비용 산정에 반영되어야 하며, 비용 항목도 아키텍처에 나타나야 합니다.", "Critical", "hybrid", ["architecture", "cost_breakdown"], ["Architecture services and cost services are aligned."], ["아키텍처 서비스와 비용 산정 서비스가 일치합니다."], ["Minor services are missing from one side."], ["일부 부가 서비스가 한쪽에서 누락되었습니다."], ["Major service mismatch exists between architecture and cost estimate."], ["아키텍처와 비용 산정 사이에 주요 서비스 불일치가 있습니다."], "Align architecture services and cost estimate line items, especially Bedrock, OpenSearch, Redshift, Redis, Kafka/MSK, NAT Gateway, and storage.", "Bedrock, OpenSearch, Redshift, Redis, Kafka/MSK, NAT Gateway, Storage 등 주요 서비스를 기준으로 아키텍처와 비용 항목을 정합화하십시오.", "SOW Pre-Submission Checklist", {"architecture-cost mapping": ["bedrock", "opensearch", "redshift", "redis", "kafka", "msk", "nat", "storage", "cost"]}),
    _seed_rule("service_sizing_rationale", "Architecture & Service Sizing", "아키텍처 및 서비스 사이징", "Key service sizing rationale is documented", "주요 서비스의 사이징 근거가 문서화되었는가", "The document should justify service sizing decisions using workload, data volume, latency, accuracy, or scale needs.", "문서에는 워크로드, 데이터 규모, 지연시간, 정확도, 확장 요구사항을 기반으로 서비스 사이징 근거가 포함되어야 합니다.", "High", "llm", ["architecture", "cost_breakdown"], ["Sizing rationale is provided for major services."], ["주요 서비스에 대한 사이징 근거가 제공되어 있습니다."], ["Sizing is present but rationale is weak."], ["사이징은 있으나 근거가 약합니다."], ["No sizing rationale is provided."], ["사이징 근거가 제공되지 않았습니다."], "Add sizing rationale for major services using workload, data, latency, accuracy, and scale assumptions.", "워크로드, 데이터, 지연시간, 정확도, 확장 가정을 활용해 주요 서비스 사이징 근거를 추가하십시오.", "SOW Pre-Submission Checklist", {"sizing rationale": ["sizing", "workload", "latency", "accuracy", "scale", "volume"]}),
    _seed_rule("capacity_mode_explained", "Architecture & Service Sizing", "아키텍처 및 서비스 사이징", "Capacity mode choices are explained", "용량 모드 선택 이유가 설명되었는가", "Capacity mode choices such as on-demand, provisioned, or autoscaling should be explained where relevant.", "온디맨드, 프로비저닝, 오토스케일링 등 용량 모드 선택 이유가 관련 서비스에 대해 설명되어야 합니다.", "Medium", "llm", ["architecture", "cost_breakdown"], ["Capacity mode decisions are explained for relevant services."], ["관련 서비스에 대한 용량 모드 선택 이유가 설명되어 있습니다."], ["Capacity mode is implied but not explained."], ["용량 모드가 암시되어 있으나 설명이 부족합니다."], ["No capacity mode rationale is provided."], ["용량 모드 선택 근거가 제공되지 않았습니다."], "Explain why each major service uses on-demand, provisioned, or autoscaling capacity.", "각 주요 서비스가 온디맨드, 프로비저닝, 오토스케일링 중 어떤 용량 모드를 사용하는지와 이유를 설명하십시오.", "SOW Pre-Submission Checklist", {"capacity mode": ["on-demand", "provisioned", "autoscaling", "capacity"]}),
    _seed_rule("scope_phase_deliverables", "Scope of Work", "작업 범위", "SOW phases and deliverables are documented", "SOW 단계와 산출물이 문서화되었는가", "The document should include clear phases, tasks, and deliverables.", "문서에는 명확한 단계, 작업, 산출물이 포함되어야 합니다.", "High", "llm", ["scope_of_work", "milestones"], ["Phases, tasks, and deliverables are clearly documented."], ["단계, 작업, 산출물이 명확히 문서화되어 있습니다."], ["Phases exist but deliverables are weak."], ["단계는 있으나 산출물이 약합니다."], ["No clear SOW phases or deliverables are provided."], ["명확한 SOW 단계 또는 산출물이 제공되지 않았습니다."], "Add phase-level tasks and deliverables such as Analysis/Design, Development, Deployment, and Stabilization.", "Analysis/Design, Development, Deployment, Stabilization 등 단계별 작업과 산출물을 추가하십시오.", "SOW Pre-Submission Checklist", {"phases and deliverables": ["phase", "task", "deliverable", "development", "deployment"]}),
    _seed_rule("deployment_rollout_plan", "Deployment & Scaling Plan", "배포 및 확장 계획", "Phased rollout plan is documented", "단계별 Rollout 계획이 문서화되었는가", "The document should describe pilot-to-production rollout stages.", "문서에는 파일럿에서 프로덕션까지의 단계별 Rollout 계획이 설명되어야 합니다.", "Medium", "llm", ["milestones", "acceptance", "assumptions"], ["Rollout phases and timeline are documented."], ["Rollout 단계와 일정이 문서화되어 있습니다."], ["Deployment is mentioned but rollout is vague."], ["배포는 언급되었으나 Rollout이 모호합니다."], ["No rollout plan is provided."], ["Rollout 계획이 제공되지 않았습니다."], "Add staged rollout from pilot users to production users with dates or months.", "파일럿 사용자에서 프로덕션 사용자로 확대되는 단계별 Rollout 일정 또는 기간을 추가하십시오.", "SOW Pre-Submission Checklist", {"rollout": ["rollout", "pilot", "production", "date", "month"]}),
    _seed_rule("scaling_strategy_exists", "Deployment & Scaling Plan", "배포 및 확장 계획", "Scaling strategy is documented", "확장 전략이 문서화되었는가", "The document should describe how the system scales with traffic, users, or workload.", "문서에는 트래픽, 사용자, 워크로드 증가에 따른 확장 전략이 설명되어야 합니다.", "Medium", "llm", ["architecture", "assumptions"], ["Autoscaling or capacity expansion strategy is documented."], ["오토스케일링 또는 용량 확장 전략이 문서화되어 있습니다."], ["Scaling is mentioned without clear threshold or method."], ["확장이 언급되었으나 임계치 또는 방법이 명확하지 않습니다."], ["No scaling strategy is provided."], ["확장 전략이 제공되지 않았습니다."], "Add scaling strategy such as autoscaling thresholds, capacity ranges, or growth-driven scaling.", "오토스케일링 임계치, 용량 범위, 성장 기반 확장 전략을 추가하십시오.", "SOW Pre-Submission Checklist", {"scaling": ["scale", "autoscaling", "threshold", "capacity", "traffic"]}),
    _seed_rule("budget_by_phase_exists", "Deployment & Scaling Plan", "배포 및 확장 계획", "Budget or cost by rollout phase is documented", "단계별 예산 또는 비용 전망이 문서화되었는가", "The document should show how cost changes across rollout phases when applicable.", "해당되는 경우 Rollout 단계별 비용 변화가 문서화되어야 합니다.", "Medium", "llm", ["cost_breakdown", "milestones"], ["Budget or cost by rollout phase is documented."], ["단계별 예산 또는 비용 전망이 문서화되어 있습니다."], ["Total cost exists but phase-level budget is missing."], ["총 비용은 있으나 단계별 예산이 없습니다."], ["No phase-level budget or cost outlook is provided."], ["단계별 예산 또는 비용 전망이 제공되지 않았습니다."], "Add cost outlook by rollout phase if production scale is part of the proposal.", "Production 확장이 포함된 경우 Rollout 단계별 비용 전망을 추가하십시오.", "SOW Pre-Submission Checklist", {"phase budget": ["phase", "budget", "cost", "rollout"]}),
    _seed_rule("risk_assessment_required", "Risk Assessment & Governance", "리스크 평가 및 거버넌스", "Risk assessment is completed for regulated or high-risk use cases", "규제/고위험 Use Case에 대한 리스크 평가가 완료되었는가", "Regulated or high-risk use cases should include risk and governance assessment.", "규제 산업 또는 고위험 Use Case에는 리스크 및 거버넌스 평가가 포함되어야 합니다.", "High", "llm", ["assumptions", "architecture", "acceptance"], ["Risk assessment is documented or explicitly not applicable."], ["리스크 평가가 문서화되었거나 명확히 해당 없음으로 설명되어 있습니다."], ["Risk is mentioned but controls are weak."], ["리스크는 언급되었으나 통제가 약합니다."], ["High-risk use case has no risk assessment."], ["고위험 Use Case임에도 리스크 평가가 없습니다."], "Add risk assessment for regulated/high-risk AI use cases, or state why it is not applicable.", "규제/고위험 AI Use Case에 대한 리스크 평가를 추가하거나 해당 없음 사유를 명시하십시오.", "SOW Pre-Submission Checklist", {"risk assessment": ["risk", "regulated", "governance", "control", "not applicable"]}),
    _seed_rule("human_in_loop_defined", "Risk Assessment & Governance", "리스크 평가 및 거버넌스", "Human-in-the-loop control is documented when needed", "필요 시 Human-in-the-loop 통제가 문서화되었는가", "High-impact recommendations or decisions should include human review controls where needed.", "중요한 추천 또는 의사결정에는 필요한 경우 사람의 검토 통제가 포함되어야 합니다.", "High", "llm", ["architecture", "acceptance", "assumptions"], ["Human review process is documented where applicable."], ["해당되는 경우 사람의 검토 프로세스가 문서화되어 있습니다."], ["Human review is implied but not operationalized."], ["사람의 검토가 암시되어 있으나 운영 방식이 없습니다."], ["High-risk AI decision flow has no human review control."], ["고위험 AI 의사결정 흐름에 사람의 검토 통제가 없습니다."], "Add human-in-the-loop review process for high-risk recommendations or decisions.", "고위험 추천 또는 의사결정에 대한 Human-in-the-loop 검토 프로세스를 추가하십시오.", "SOW Pre-Submission Checklist", {"human review": ["human", "review", "approval", "decision"]}),
    _seed_rule("audit_logging_defined", "Risk Assessment & Governance", "리스크 평가 및 거버넌스", "Audit logging requirement is documented", "감사 로그 요건이 문서화되었는가", "The document should describe audit logging requirements for AI decisions or critical workflows when relevant.", "관련되는 경우 AI 판단 또는 중요 업무 흐름에 대한 감사 로그 요건이 설명되어야 합니다.", "Medium", "llm", ["architecture", "assumptions"], ["Audit logging requirement is documented or explicitly not applicable."], ["감사 로그 요건이 문서화되었거나 명확히 해당 없음으로 설명되어 있습니다."], ["Logging is mentioned but audit retention or scope is unclear."], ["로그는 언급되었으나 감사 보관 또는 범위가 불명확합니다."], ["No audit logging requirement is provided for relevant use cases."], ["관련 Use Case에 대한 감사 로그 요건이 제공되지 않았습니다."], "Add audit logging scope, retention, and review requirement where applicable.", "해당되는 경우 감사 로그 범위, 보관 기간, 검토 요건을 추가하십시오.", "SOW Pre-Submission Checklist", {"audit logging": ["audit", "logging", "retention", "log"]}),
    _seed_rule("compliance_requirements_defined", "Risk Assessment & Governance", "리스크 평가 및 거버넌스", "Compliance requirements are documented", "컴플라이언스 요건이 문서화되었는가", "The document should describe compliance requirements such as PIPA, GDPR, HIPAA, PCI-DSS where applicable.", "해당되는 경우 PIPA, GDPR, HIPAA, PCI-DSS 등 컴플라이언스 요건이 설명되어야 합니다.", "High", "llm", ["assumptions", "architecture"], ["Relevant compliance requirements are documented or explicitly not applicable."], ["관련 컴플라이언스 요건이 문서화되었거나 명확히 해당 없음으로 설명되어 있습니다."], ["Compliance is mentioned but requirements are incomplete."], ["컴플라이언스가 언급되었으나 요건이 불완전합니다."], ["Regulated use case has no compliance consideration."], ["규제 대상 Use Case임에도 컴플라이언스 고려사항이 없습니다."], "Add applicable compliance requirements and data protection controls.", "적용 가능한 컴플라이언스 요건과 데이터 보호 통제를 추가하십시오.", "SOW Pre-Submission Checklist", {"compliance": ["compliance", "pipa", "gdpr", "hipaa", "pci", "privacy"]}),
    _seed_rule("model_validation_plan_exists", "Risk Assessment & Governance", "리스크 평가 및 거버넌스", "Model accuracy/testing plan is documented", "모델 정확도/검증 계획이 문서화되었는가", "The document should include testing or validation plan for model accuracy, safety, or fairness where applicable.", "문서에는 해당되는 경우 모델 정확도, 안전성, 공정성 검증 계획이 포함되어야 합니다.", "Medium", "llm", ["success_criteria", "acceptance"], ["Model validation plan and target metrics are documented."], ["모델 검증 계획과 목표 지표가 문서화되어 있습니다."], ["Validation is mentioned but test set, metric, or process is weak."], ["검증은 언급되었으나 테스트셋, 지표, 절차가 약합니다."], ["No model validation or testing plan is provided."], ["모델 검증 또는 테스트 계획이 제공되지 않았습니다."], "Add validation dataset, metric, target threshold, and review process.", "검증 데이터셋, 지표, 목표 임계치, 검토 절차를 추가하십시오.", "SOW Pre-Submission Checklist", {"model validation": ["validation", "accuracy", "test", "metric", "threshold"]}),
    _seed_rule("cross_document_consistency", "Final Check", "최종 점검", "Cross-document consistency is verified", "문서 간 모순이 없는지 교차 검증되었는가", "The document should not contain contradictions across use case, architecture, cost, scope, and timeline.", "Use Case, 아키텍처, 비용, 범위, 일정 사이에 모순이 없어야 합니다.", "High", "llm", ["executive_summary", "scope_of_work", "architecture", "cost_breakdown", "milestones"], ["No major contradiction is found across sections."], ["섹션 간 주요 모순이 발견되지 않습니다."], ["Minor inconsistency exists but does not block submission."], ["작은 불일치가 있으나 제출을 막을 수준은 아닙니다."], ["Major contradiction exists across sections."], ["섹션 간 주요 모순이 존재합니다."], "Align use case, architecture, cost, scope, resource plan, and timeline.", "Use Case, 아키텍처, 비용, 범위, 리소스 계획, 일정을 정합화하십시오.", "SOW Pre-Submission Checklist", {"consistency": ["use case", "architecture", "cost", "scope", "timeline"]}),
    _seed_rule("apfp_submission_info_exists", "APFP", "APFP", "APFP submission information is prepared", "APFP 제출 정보가 준비되었는가", "The document should support APFP submission fields such as project name, business description, dates, currency, total cost, and requested funding amount.", "문서는 프로젝트명, 비즈니스 설명, 일정, 통화, 총 비용, 요청 펀딩 금액 등 APFP 제출 정보를 뒷받침해야 합니다.", "Medium", "llm", ["cover", "executive_summary", "milestones", "cost_breakdown"], ["Key APFP submission information is present."], ["주요 APFP 제출 정보가 존재합니다."], ["Some APFP fields are present but incomplete."], ["일부 APFP 필드는 있으나 불완전합니다."], ["APFP submission information is mostly missing."], ["APFP 제출 정보가 대부분 누락되었습니다."], "Add APFP-ready project name, business description, start/end dates, total cost, and requested funding amount.", "APFP 제출용 프로젝트명, 비즈니스 설명, 시작/종료일, 총 비용, 요청 펀딩 금액을 추가하십시오.", "GenAIIC PLD Funding Guide", {"APFP fields": ["project", "business", "date", "currency", "total cost", "funding"]}),
    _seed_rule("claim_timeline_awareness", "APFP", "APFP", "Claim timeline and completion evidence requirements are understood", "Claim 기한과 완료 증빙 요건이 반영되었는가", "The project should consider claim submission timing and completion sign-off requirements after project completion.", "프로젝트 완료 후 Claim 제출 기한과 완료 증빙/Sign-off 요건을 고려해야 합니다.", "Low", "llm", ["milestones", "acceptance"], ["Claim or completion evidence requirements are mentioned where relevant."], ["관련되는 경우 Claim 또는 완료 증빙 요건이 언급되어 있습니다."], ["Completion is mentioned but claim timing is not considered."], ["완료는 언급되었으나 Claim 기한은 고려되지 않았습니다."], ["No claim or completion evidence awareness is shown."], ["Claim 또는 완료 증빙 요건에 대한 고려가 없습니다."], "Add completion sign-off and claim timing awareness if needed for APFP process.", "APFP 절차상 필요한 경우 완료 Sign-off와 Claim 기한 고려사항을 추가하십시오.", "GenAIIC PLD Funding Guide", {"claim evidence": ["claim", "completion", "sign-off", "evidence"]}),
]


def _review_catalog_public() -> list[dict]:
    public_keys = {
        "rule_id", "enabled", "custom", "category_en", "category_kr",
        "title_en", "title_kr", "description_en", "description_kr",
        "severity", "evaluation_type", "related_sections",
        "pass_criteria_en", "pass_criteria_kr", "warning_criteria_en",
        "warning_criteria_kr", "fail_criteria_en", "fail_criteria_kr",
        "recommendation_template_en", "recommendation_template_kr", "source",
        "created_at", "updated_at", "created_by", "updated_by",
    }
    return [{k: deepcopy(rule[k]) for k in public_keys if k in rule} for rule in _REVIEW_RULE_CATALOG]


def _review_text(value: Any) -> str:
    value = _resolve_field_value(value)
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, dict):
        parts = [_review_text(v) for v in value.values()]
        return " ".join(p for p in parts if p)
    if isinstance(value, list):
        parts = [_review_text(v) for v in value]
        return " ".join(p for p in parts if p)
    return str(value)


def _review_has_content(value: Any) -> bool:
    return bool(_review_text(value).strip())


def _review_snippet(text: str, limit: int = 220) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _collect_review_evidence(value: Any, section: str, terms: list[str], field_path: str = "", limit: int = 4) -> list[dict]:
    matches: list[dict] = []
    term_lowers = [str(t).lower() for t in terms if str(t).strip()]

    def visit(node: Any, path: str) -> None:
        if len(matches) >= limit:
            return
        resolved = _resolve_field_value(node)
        if isinstance(resolved, dict):
            for key, child in resolved.items():
                visit(child, f"{path}.{key}" if path else str(key))
            return
        if isinstance(resolved, list):
            for index, child in enumerate(resolved):
                visit(child, f"{path}.{index}" if path else str(index))
            return
        text = _review_text(resolved)
        if not text:
            return
        haystack = text.lower()
        if term_lowers and not any(term in haystack for term in term_lowers):
            return
        matches.append({
            "section": section,
            "text": _review_snippet(text),
            "field_path": field_path or (f"sections.{section}.{path}" if section != "meta" else f"meta.{path}") if path else (field_path or section),
        })

    visit(value, "")
    return matches


def _rule_evidence_context(item: dict) -> dict:
    sections = item.get("sections", {}) if isinstance(item.get("sections"), dict) else {}
    meta = item.get("meta", {}) if isinstance(item.get("meta"), dict) else {}
    return {
        "sections": sections,
        "meta": meta,
        "cost": sections.get("cost_breakdown", {}) if isinstance(sections.get("cost_breakdown"), dict) else {},
        "architecture": sections.get("architecture", {}) if isinstance(sections.get("architecture"), dict) else {},
        "resources": sections.get("resources_cost_estimates", {}) if isinstance(sections.get("resources_cost_estimates"), dict) else {},
    }


def _section_value_for_rule(ctx: dict, section: str) -> Any:
    if section == "meta":
        return ctx.get("meta", {})
    return ctx.get("sections", {}).get(section)


def _architecture_service_names(architecture: dict) -> list[str]:
    services = architecture.get("services", []) if isinstance(architecture.get("services"), list) else []
    names: list[str] = []
    for svc in services:
        if isinstance(svc, dict):
            name = _resolve_field_value(svc.get("service_name")) or svc.get("service_id", "")
        else:
            name = svc
        if name:
            names.append(str(name))
    return names


def _cost_breakdown_rows(cost: dict) -> list[dict]:
    rows = cost.get("breakdown_table") if isinstance(cost, dict) else None
    return rows if isinstance(rows, list) else []


def _cost_has_bedrock_row(cost: dict) -> bool:
    for row in _cost_breakdown_rows(cost):
        if not isinstance(row, dict):
            continue
        for key in ("service_name", "service", "category", "name"):
            label = _review_text(row.get(key))
            if "bedrock" in label.lower():
                return True
    return False


def _field_path_value(root: dict, dotted_path: str) -> Any:
    node: Any = root
    for part in dotted_path.split("."):
        if isinstance(node, dict):
            node = node.get(part)
        else:
            return None
    return node


def _has_url(value: Any) -> bool:
    text = _review_text(value).lower()
    return text.startswith("http://") or text.startswith("https://") or "calculator.aws" in text


def _has_architecture_diagram(architecture: dict) -> bool:
    for key in ("diagram_image_s3_key", "drawio_s3_key", "preview_s3_key", "preview_url", "diagram_url"):
        if _has_resolved_value(architecture.get(key)):
            return True
    return False


def _resource_total_cost(resources: dict) -> float:
    if not isinstance(resources, dict):
        return 0.0
    total_cost = resources.get("total_cost", {}) if isinstance(resources.get("total_cost"), dict) else {}
    return _to_float(total_cost.get("total"))


def _evaluate_review_rule(rule: dict, item: dict, ctx: dict, suggested_patches: list[dict]) -> dict:
    related_sections = list(rule.get("related_sections") or [])
    evidence_terms = rule.get("evidence_terms") if isinstance(rule.get("evidence_terms"), dict) else {}
    section_values = {section: _section_value_for_rule(ctx, section) for section in related_sections}
    referenced_sections = [section for section, value in section_values.items() if _review_has_content(value)]

    evidence_found: list[dict] = []
    missing_evidence: list[str] = []
    for label, terms in evidence_terms.items():
        label_terms = terms if isinstance(terms, list) else [str(terms)]
        label_matches: list[dict] = []
        for section, value in section_values.items():
            label_matches.extend(_collect_review_evidence(value, section, label_terms, limit=2))
            if label_matches:
                break
        if label_matches:
            evidence_found.extend(label_matches)
        else:
            missing_evidence.append(str(label))

    if not evidence_found:
        for section, value in section_values.items():
            evidence_found.extend(_collect_review_evidence(value, section, [], limit=1))
            if evidence_found:
                break

    cost = ctx["cost"]
    architecture = ctx["architecture"]
    resources = ctx["resources"]
    calculator_url = cost.get("calculator_url", {}) if isinstance(cost, dict) else {}
    mrr = _to_float(cost.get("mrr", 0)) if isinstance(cost, dict) else 0.0
    arr = _to_float(cost.get("arr", 0)) if isinstance(cost, dict) else 0.0
    funding = cost.get("funding_calculation", {}) if isinstance(cost.get("funding_calculation"), dict) else {}
    sow_cost = _to_float(funding.get("sow_cost"))
    if sow_cost <= 0 and isinstance(resources, dict):
        total_cost = resources.get("total_cost", {}) if isinstance(resources.get("total_cost"), dict) else {}
        sow_cost = _to_float(total_cost.get("total"))
    service_names = _architecture_service_names(architecture)
    has_services = bool(service_names)
    arch_has_bedrock = any("bedrock" in name.lower() for name in service_names)
    has_calculator = _has_resolved_value(calculator_url)
    cost_rows = _cost_breakdown_rows(cost)

    special_status: str | None = None
    special_missing: list[str] = []
    rule_id = rule["rule_id"]
    if rule_id in {"BEDROCK_EVIDENCE_MISSING", "bedrock_included"}:
        special_status = "PASS" if arch_has_bedrock else ("FAIL" if _review_has_content(architecture) else "NOT_CHECKED")
        if not arch_has_bedrock:
            special_missing.append("Amazon Bedrock in architecture services or overview")
    elif rule_id in {"ARR_MISSING", "total_arr_documented"}:
        if arr > 0:
            special_status = "PASS"
        elif mrr > 0:
            special_status = "WARNING"
            special_missing.append("Confirmed Year 1 ARR value")
        else:
            special_status = "FAIL" if _review_has_content(cost) else "NOT_CHECKED"
            special_missing.append("Year 1 ARR or MRR basis")
    elif rule_id == "SOW_COST_MISSING":
        special_status = "PASS" if sow_cost > 0 else ("FAIL" if _review_has_content(cost) or _review_has_content(resources) else "NOT_CHECKED")
        if sow_cost <= 0:
            special_missing.append("SOW cost or total resource estimate")
    elif rule_id in {"FUNDING_FORMULA", "funding_amount_rule"}:
        eligible = _to_float(funding.get("eligible_amount")) if isinstance(funding, dict) else 0.0
        if arr > 0 and sow_cost > 0 and eligible > 0:
            special_status = "PASS"
        elif arr > 0 and sow_cost > 0:
            special_status = "WARNING"
            special_missing.append("Confirmed eligible funding amount/formula")
        else:
            special_status = "FAIL" if _review_has_content(cost) or _review_has_content(resources) else "NOT_CHECKED"
            special_missing.append("ARR and SOW cost inputs for funding formula")
    elif rule_id == "calculator_link_exists":
        if _has_url(calculator_url):
            special_status = "PASS"
        elif "calculator" in _review_text(cost).lower():
            special_status = "WARNING"
            special_missing.append("Valid AWS Calculator URL")
        else:
            special_status = "FAIL" if _review_has_content(cost) else "NOT_CHECKED"
            special_missing.append("AWS Calculator share URL")
    elif rule_id == "bedrock_cost_estimate_exists":
        has_bedrock_cost = _cost_has_bedrock_row(cost) or ("bedrock" in _review_text(cost).lower() and ("cost" in _review_text(cost).lower() or arr > 0 or mrr > 0))
        has_token_assumption = "token" in (_review_text(cost) + " " + _review_text(ctx["sections"].get("assumptions", {}))).lower()
        if has_bedrock_cost and has_token_assumption:
            special_status = "PASS"
        elif has_bedrock_cost or has_token_assumption:
            special_status = "WARNING"
            special_missing.append("Bedrock token assumptions and monthly/annual cost estimate")
        else:
            special_status = "FAIL" if _review_has_content(cost) else "NOT_CHECKED"
            special_missing.append("Bedrock token/cost estimate")
    elif rule_id == "sow_cost_breakdown_exists":
        resource_text = _review_text(resources).lower()
        has_total = sow_cost > 0 or _resource_total_cost(resources) > 0
        has_breakdown = any(term in resource_text for term in ("role", "rate", "hour", "phase", "contribution"))
        if has_total and has_breakdown:
            special_status = "PASS"
        elif has_total or has_breakdown:
            special_status = "WARNING"
            special_missing.append("Role/rate/hour/phase contribution breakdown")
        else:
            special_status = "FAIL" if _review_has_content(resources) else "NOT_CHECKED"
            special_missing.append("SOW cost breakdown")
    elif rule_id == "architecture_diagram_exists":
        if _has_architecture_diagram(architecture):
            special_status = "PASS"
        elif _review_has_content(architecture):
            special_status = "WARNING"
            special_missing.append("Architecture diagram artifact")
        else:
            special_status = "NOT_CHECKED"
            special_missing.append("Architecture diagram artifact")
    elif rule_id in {"ARCHITECTURE_COST_ALIGNMENT_MISSING", "architecture_cost_alignment"}:
        if has_services and (has_calculator or cost_rows):
            special_status = "PASS" if has_calculator else "WARNING"
        elif has_services:
            special_status = "FAIL"
            special_missing.append("Calculator URL or service-level cost rows mapped to architecture services")
        else:
            special_status = "NOT_CHECKED"
            special_missing.append("Architecture services")
    elif rule_id == "BEDROCK_COST_NOT_REFLECTED":
        if not arch_has_bedrock:
            special_status = "NOT_CHECKED"
            special_missing.append("Bedrock architecture evidence")
        elif has_calculator or _cost_has_bedrock_row(cost):
            special_status = "PASS"
        else:
            special_status = "FAIL"
            special_missing.append("Bedrock-specific cost row or calculator URL")
    elif rule_id == "APN_TEMPLATE_COMPLETENESS":
        empty_sections = [section for section, value in section_values.items() if not _review_has_content(value)]
        if not empty_sections:
            special_status = "PASS"
        elif len(empty_sections) <= 2 and len(empty_sections) < len(section_values):
            special_status = "WARNING"
        else:
            special_status = "FAIL" if len(empty_sections) < len(section_values) else "NOT_CHECKED"
        special_missing.extend([f"{section} content" for section in empty_sections])

    if special_missing:
        missing_evidence = list(dict.fromkeys(special_missing + missing_evidence))

    if special_status:
        status = special_status
    elif not any(_review_has_content(value) for value in section_values.values()):
        status = "NOT_CHECKED"
    elif not missing_evidence and evidence_found:
        status = "PASS"
    elif evidence_found:
        status = "WARNING"
    else:
        status = "FAIL"

    recommendation_by_status_en = {
        "PASS": "No immediate fix required; keep the evidence current before submission.",
        "WARNING": rule.get("recommendation_template_en") or "Add the missing evidence and confirm assumptions before submission.",
        "FAIL": rule.get("recommendation_template_en") or "Add the required evidence; this is recommended before submission.",
        "NOT_CHECKED": "Populate the related section so this rule can be evaluated before submission.",
    }
    recommendation_by_status_kr = {
        "PASS": "즉시 수정은 필요하지 않습니다. 제출 전 근거가 최신 상태인지 확인하십시오.",
        "WARNING": rule.get("recommendation_template_kr") or "누락된 근거를 추가하고 제출 전 가정을 확인하십시오.",
        "FAIL": rule.get("recommendation_template_kr") or "필수 근거를 추가하십시오. 제출 전 보완을 권장합니다.",
        "NOT_CHECKED": "관련 섹션을 작성한 뒤 제출 전 이 규칙을 다시 평가하십시오.",
    }
    judgment_by_status_en = {
        "PASS": "Evidence is strong enough for this rule.",
        "WARNING": "Partial evidence is present, but the document should be strengthened before submission.",
        "FAIL": "Required evidence is missing or too weak for this rule.",
        "NOT_CHECKED": "The related section has no usable evidence, so this rule was not checked.",
    }
    judgment_by_status_kr = {
        "PASS": "이 규칙에 필요한 근거가 충분합니다.",
        "WARNING": "일부 근거는 있으나 제출 전 보완을 권장합니다.",
        "FAIL": "필수 근거가 누락되었거나 충분하지 않습니다.",
        "NOT_CHECKED": "관련 섹션에 평가 가능한 근거가 없어 확인하지 못했습니다.",
    }

    suggested_patch = None
    if rule_id == "ARR_MISSING" and arr <= 0 and mrr > 0:
        suggested_patch = {
            "op": "replace",
            "path": "/sections/cost_breakdown/arr",
            "value": _confirmed_field_value(round(mrr * 12, 2)),
            "reason": "ARR can be calculated from MRR when MRR is provided.",
        }
    elif rule_id == "FUNDING_FORMULA" and arr > 0 and sow_cost > 0:
        eligible = min(arr * 0.25, sow_cost, 125000)
        suggested_patch = {
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
        }
    if suggested_patch:
        suggested_patches.append(suggested_patch)

    if status == "FAIL":
        fallback_missing_en = rule.get("fail_criteria_en") or missing_evidence
        fallback_missing_kr = rule.get("fail_criteria_kr") or missing_evidence
    elif status == "WARNING":
        fallback_missing_en = rule.get("warning_criteria_en") or missing_evidence
        fallback_missing_kr = rule.get("warning_criteria_kr") or missing_evidence
    else:
        fallback_missing_en = missing_evidence
        fallback_missing_kr = missing_evidence

    return {
        "rule_id": rule["rule_id"],
        "category": rule.get("category_en", rule.get("category", "")),
        "title": rule.get("title_en", rule.get("title", "")),
        "category_en": rule.get("category_en", rule.get("category", "")),
        "category_kr": rule.get("category_kr", ""),
        "title_en": rule.get("title_en", rule.get("title", "")),
        "title_kr": rule.get("title_kr", ""),
        "status": status,
        "severity": rule["severity"],
        "llm_judgment": judgment_by_status_en[status],
        "llm_judgment_en": judgment_by_status_en[status],
        "llm_judgment_kr": judgment_by_status_kr[status],
        "evidence_found": evidence_found[:4],
        "missing_evidence": missing_evidence,
        "missing_evidence_en": [str(x) for x in fallback_missing_en],
        "missing_evidence_kr": [str(x) for x in fallback_missing_kr],
        "recommendation": recommendation_by_status_en[status],
        "recommendation_en": recommendation_by_status_en[status],
        "recommendation_kr": recommendation_by_status_kr[status],
        "referenced_sections": referenced_sections,
        "suggested_patch_available": suggested_patch is not None,
        "suggested_patch": suggested_patch,
    }


def _review_summary(evaluations: list[dict]) -> dict:
    counts = {"pass": 0, "warning": 0, "fail": 0, "not_checked": 0}
    for evaluation in evaluations:
        key = str(evaluation.get("status", "NOT_CHECKED")).lower()
        if key in counts:
            counts[key] += 1
    counts["total"] = len(evaluations)
    return counts


def _review_categories(evaluations: list[dict]) -> list[dict]:
    by_category: dict[str, dict] = {}
    for evaluation in evaluations:
        category = str(evaluation.get("category_en") or evaluation.get("category") or "Uncategorized")
        bucket = by_category.setdefault(category, {
            "category": category,
            "category_en": category,
            "category_kr": str(evaluation.get("category_kr") or ""),
            "pass": 0,
            "warning": 0,
            "fail": 0,
            "not_checked": 0,
            "total": 0,
        })
        key = str(evaluation.get("status", "NOT_CHECKED")).lower()
        if key in bucket:
            bucket[key] += 1
        bucket["total"] += 1
    return list(by_category.values())


def _issues_from_rule_evaluations(evaluations: list[dict]) -> dict:
    issues = {"critical": [], "high": [], "medium": [], "low": []}
    severity_map = {"Critical": "critical", "High": "high", "Medium": "medium", "Low": "low", "Info": "low"}
    for evaluation in evaluations:
        status = evaluation.get("status")
        if status not in {"FAIL", "WARNING"}:
            continue
        bucket = severity_map.get(str(evaluation.get("severity")), "medium")
        section = (evaluation.get("referenced_sections") or evaluation.get("referenced_sections") or [""])[0]
        missing = evaluation.get("missing_evidence") or []
        question = f"What evidence should be added for {evaluation.get('title_en') or evaluation.get('title')}?"
        if missing:
            question = f"What evidence should be added for {', '.join(str(m) for m in missing[:3])}?"
        issues[bucket].append(_make_issue(
            bucket,
            str(evaluation.get("rule_id")),
            str(evaluation.get("recommendation") or evaluation.get("llm_judgment") or ""),
            str(section or ""),
            question,
        ))
    return issues


def _review_readiness_score(evaluations: list[dict]) -> int:
    weights = {
        "Critical": {"FAIL": 18, "WARNING": 9, "NOT_CHECKED": 6},
        "High": {"FAIL": 12, "WARNING": 6, "NOT_CHECKED": 4},
        "Medium": {"FAIL": 7, "WARNING": 3, "NOT_CHECKED": 2},
        "Low": {"FAIL": 3, "WARNING": 1, "NOT_CHECKED": 1},
        "Info": {"FAIL": 1, "WARNING": 0, "NOT_CHECKED": 0},
    }
    penalty = 0
    for evaluation in evaluations:
        penalty += weights.get(str(evaluation.get("severity")), weights["Medium"]).get(str(evaluation.get("status")), 0)
    return max(0, min(100, 100 - penalty))


def _review_rule_storage_key(rule_id: str) -> str:
    return f"{_REVIEW_RULE_ITEM_PREFIX}{rule_id}"


def _normalize_review_rule(rule: dict, *, custom: bool, user_id: str = "system") -> dict:
    now = _now_iso()
    normalized = deepcopy(rule)
    normalized["rule_id"] = str(normalized.get("rule_id", "")).strip()
    normalized["enabled"] = bool(normalized.get("enabled", True))
    normalized["custom"] = bool(custom)
    normalized["severity"] = str(normalized.get("severity", "Medium"))
    normalized["evaluation_type"] = str(normalized.get("evaluation_type", "llm"))
    normalized["related_sections"] = [str(s) for s in normalized.get("related_sections", []) if s]
    for key in (
        "pass_criteria_en", "pass_criteria_kr", "warning_criteria_en",
        "warning_criteria_kr", "fail_criteria_en", "fail_criteria_kr",
    ):
        value = normalized.get(key, [])
        if isinstance(value, str):
            value = [value]
        normalized[key] = [str(v) for v in value if v]
    for key in (
        "category_en", "category_kr", "title_en", "title_kr",
        "description_en", "description_kr", "recommendation_template_en",
        "recommendation_template_kr", "source",
    ):
        normalized[key] = str(normalized.get(key, "") or "")
    normalized.setdefault("created_at", now)
    normalized["updated_at"] = now
    normalized.setdefault("created_by", user_id)
    normalized["updated_by"] = user_id
    return normalized


def _validate_review_rule(rule: dict, *, creating: bool) -> list[str]:
    missing: list[str] = []
    required = [
        "rule_id", "category_en", "category_kr", "title_en", "title_kr",
        "description_en", "description_kr", "severity", "evaluation_type",
        "related_sections", "pass_criteria_en", "pass_criteria_kr",
        "warning_criteria_en", "warning_criteria_kr", "fail_criteria_en",
        "fail_criteria_kr", "recommendation_template_en",
        "recommendation_template_kr", "source",
    ]
    for key in required:
        value = rule.get(key)
        if value in (None, "", []):
            missing.append(key)
    if str(rule.get("severity", "")) not in _REVIEW_RULE_SEVERITIES:
        missing.append("severity must be one of Critical, High, Medium, Low, Info")
    if str(rule.get("evaluation_type", "")) not in _REVIEW_RULE_EVALUATION_TYPES:
        missing.append("evaluation_type must be one of static, llm, hybrid")
    if creating and not bool(rule.get("custom")):
        missing.append("custom must be true")
    return missing


def _builtin_review_rule_map() -> dict[str, dict]:
    return {rule["rule_id"]: deepcopy(rule) for rule in _REVIEW_RULE_CATALOG}


def _scan_review_rule_items(item_type: str) -> list[dict]:
    try:
        resp = table.scan(FilterExpression=Attr("item_type").eq(item_type))
    except Exception as exc:
        _log("review_rules", "warn", scan_error=_safe_error_reason(exc), item_type=item_type)
        return []
    if not isinstance(resp, dict):
        return []
    items = resp.get("Items", [])
    while resp.get("LastEvaluatedKey"):
        resp = table.scan(
            FilterExpression=Attr("item_type").eq(item_type),
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        items.extend(resp.get("Items", []))
    return items


def _load_review_rules(*, include_disabled: bool = True) -> list[dict]:
    rules = _builtin_review_rule_map()
    for item in _scan_review_rule_items(_REVIEW_RULE_OVERRIDE_TYPE):
        rule_id = str(item.get("rule_id", ""))
        if rule_id in rules and "enabled" in item:
            rules[rule_id]["enabled"] = bool(item.get("enabled"))
            rules[rule_id]["updated_at"] = str(item.get("updated_at", rules[rule_id].get("updated_at", "")))
            rules[rule_id]["updated_by"] = str(item.get("updated_by", rules[rule_id].get("updated_by", "")))
    for item in _scan_review_rule_items(_REVIEW_RULE_CUSTOM_TYPE):
        rule = {k: v for k, v in item.items() if k not in {"document_id", "item_type"}}
        if rule.get("rule_id"):
            rules[str(rule["rule_id"])] = _normalize_review_rule(rule, custom=True, user_id=str(rule.get("updated_by") or "system"))
    result = list(rules.values())
    if not include_disabled:
        result = [rule for rule in result if bool(rule.get("enabled", True))]
    return sorted(result, key=lambda r: (str(r.get("category_en", "")), str(r.get("rule_id", ""))))


def _find_review_rule(rule_id: str, *, include_disabled: bool = True) -> dict | None:
    for rule in _load_review_rules(include_disabled=include_disabled):
        if rule.get("rule_id") == rule_id:
            return rule
    return None


def _filter_review_rules(rules: list[dict], params: dict | None) -> list[dict]:
    params = params or {}
    enabled = params.get("enabled")
    category = str(params.get("category", "") or "").strip().lower()
    severity = str(params.get("severity", "") or "").strip().lower()
    custom = params.get("custom")
    query = str(params.get("q", "") or "").strip().lower()

    def bool_param(value: Any) -> bool | None:
        if value is None or value == "":
            return None
        return str(value).lower() in {"1", "true", "yes", "y"}

    enabled_bool = bool_param(enabled)
    custom_bool = bool_param(custom)
    filtered = []
    for rule in rules:
        if enabled_bool is not None and bool(rule.get("enabled", True)) != enabled_bool:
            continue
        if custom_bool is not None and bool(rule.get("custom", False)) != custom_bool:
            continue
        if severity and str(rule.get("severity", "")).lower() != severity:
            continue
        if category and category not in f"{rule.get('category_en', '')} {rule.get('category_kr', '')}".lower():
            continue
        if query:
            haystack = " ".join(str(rule.get(k, "")) for k in (
                "rule_id", "category_en", "category_kr", "title_en", "title_kr",
                "description_en", "description_kr", "source",
            )).lower()
            if query not in haystack:
                continue
        filtered.append(rule)
    return filtered


def _public_review_rule(rule: dict) -> dict:
    return {k: deepcopy(v) for k, v in rule.items() if k not in {"evidence_terms", "document_id", "item_type"}}


def _handle_list_review_rules(event: dict) -> dict:
    _user_id, err = _require_user(event)
    if err:
        return err
    rules = _filter_review_rules(_load_review_rules(include_disabled=True), event.get("queryStringParameters") or {})
    return _response(200, {
        "version": _REVIEW_RULE_SEED_VERSION,
        "source_documents": _REVIEW_RULE_SOURCE_DOCUMENTS,
        "rules": [_public_review_rule(rule) for rule in rules],
        "total": len(rules),
    })


def _handle_get_review_rule(rule_id: str, event: dict) -> dict:
    _user_id, err = _require_user(event)
    if err:
        return err
    rule = _find_review_rule(rule_id, include_disabled=True)
    if not rule:
        return _response(404, {"error": "review rule not found", "rule_id": rule_id})
    return _response(200, _public_review_rule(rule))


def _handle_create_review_rule(body: dict, event: dict) -> dict:
    user_id, err = _require_user(event)
    if err:
        return err
    rule = _normalize_review_rule(body, custom=True, user_id=user_id)
    validation_errors = _validate_review_rule(rule, creating=True)
    if validation_errors:
        return _response(400, {"error": "invalid review rule", "missing_inputs": validation_errors})
    if _find_review_rule(rule["rule_id"], include_disabled=True):
        return _response(409, {"error": "duplicate rule_id", "rule_id": rule["rule_id"]})
    item = deepcopy(rule)
    item["document_id"] = _review_rule_storage_key(rule["rule_id"])
    item["item_type"] = _REVIEW_RULE_CUSTOM_TYPE
    table.put_item(Item=json.loads(_json(item), parse_float=Decimal))
    return _response(201, _public_review_rule(rule))


def _handle_update_review_rule(rule_id: str, body: dict, event: dict) -> dict:
    user_id, err = _require_user(event)
    if err:
        return err
    existing = _find_review_rule(rule_id, include_disabled=True)
    if not existing:
        return _response(404, {"error": "review rule not found", "rule_id": rule_id})
    if not existing.get("custom"):
        enabled = bool(body.get("enabled", existing.get("enabled", True)))
        item = {
            "document_id": _review_rule_storage_key(rule_id),
            "item_type": _REVIEW_RULE_OVERRIDE_TYPE,
            "rule_id": rule_id,
            "enabled": enabled,
            "updated_at": _now_iso(),
            "updated_by": user_id,
        }
        table.put_item(Item=item)
        updated = deepcopy(existing)
        updated["enabled"] = enabled
        updated["updated_at"] = item["updated_at"]
        updated["updated_by"] = user_id
        return _response(200, _public_review_rule(updated))
    merged = deepcopy(existing)
    merged.update(body)
    merged["rule_id"] = rule_id
    merged["custom"] = True
    rule = _normalize_review_rule(merged, custom=True, user_id=user_id)
    validation_errors = _validate_review_rule(rule, creating=False)
    if validation_errors:
        return _response(400, {"error": "invalid review rule", "missing_inputs": validation_errors})
    item = deepcopy(rule)
    item["document_id"] = _review_rule_storage_key(rule_id)
    item["item_type"] = _REVIEW_RULE_CUSTOM_TYPE
    table.put_item(Item=json.loads(_json(item), parse_float=Decimal))
    return _response(200, _public_review_rule(rule))


def _handle_delete_review_rule(rule_id: str, event: dict) -> dict:
    user_id, err = _require_user(event)
    if err:
        return err
    existing = _find_review_rule(rule_id, include_disabled=True)
    if not existing:
        return _response(404, {"error": "review rule not found", "rule_id": rule_id})
    if existing.get("custom"):
        table.delete_item(Key={"document_id": _review_rule_storage_key(rule_id)})
        return _response(200, {"status": "deleted", "rule_id": rule_id})
    item = {
        "document_id": _review_rule_storage_key(rule_id),
        "item_type": _REVIEW_RULE_OVERRIDE_TYPE,
        "rule_id": rule_id,
        "enabled": False,
        "updated_at": _now_iso(),
        "updated_by": user_id,
    }
    table.put_item(Item=item)
    return _response(200, {"status": "disabled", "rule_id": rule_id})


def _document_lint_result(item: dict) -> dict:
    ctx = _rule_evidence_context(item)
    missing_questions: list[str] = []
    suggested_patches: list[dict] = []
    enabled_rules = _load_review_rules(include_disabled=False)
    rule_evaluations = [
        _evaluate_review_rule(rule, item, ctx, suggested_patches)
        for rule in enabled_rules
    ]
    issues = _issues_from_rule_evaluations(rule_evaluations)
    for issue_group in issues.values():
        for issue in issue_group:
            if issue.get("question"):
                missing_questions.append(issue["question"])
    readiness_score = _review_readiness_score(rule_evaluations)

    return {
        "readiness_score": readiness_score,
        "summary": _review_summary(rule_evaluations),
        "categories": _review_categories(rule_evaluations),
        "rule_catalog": [_public_review_rule(rule) for rule in enabled_rules],
        "rule_evaluations": rule_evaluations,
        "issues": issues,
        "missing_questions": missing_questions,
        "suggested_patches": suggested_patches,
        "kb_retrieval": _approved_samples_fallback(),
    }


def _resource_plan(body: dict) -> dict:
    target = _to_float(body.get("target_funding_amount"))
    mrr = _to_float(body.get("mrr"))
    arr = _to_float(body.get("arr"))
    sow_cost = _to_float(body.get("sow_cost"))
    assumptions = body.get("assumptions") or []

    required_arr = round(target / 0.25, 2) if target > 0 else 0.0
    effective_arr = arr if arr > 0 else (mrr * 12 if mrr > 0 else required_arr)
    required_sow_cost = target
    cap_limited = target > 125000
    eligible_amount = round(min(effective_arr * 0.25, sow_cost if sow_cost > 0 else required_sow_cost, 125000), 2)

    role_rates = [
        {"role": "Solution Architect", "rate": _confirmed_field_value(180)},
        {"role": "Engineer", "rate": _confirmed_field_value(150)},
        {"role": "Project Manager", "rate": _confirmed_field_value(130)},
    ]
    phase_hours_table = [
        {
            "phase": _confirmed_field_value("Discovery & Design"),
            "role_hours": [
                {"role": "Solution Architect", "hours": 24},
                {"role": "Engineer", "hours": 16},
                {"role": "Project Manager", "hours": 8},
            ],
            "total": 48,
        },
        {
            "phase": _confirmed_field_value("Build & Integration"),
            "role_hours": [
                {"role": "Solution Architect", "hours": 32},
                {"role": "Engineer", "hours": 80},
                {"role": "Project Manager", "hours": 16},
            ],
            "total": 128,
        },
        {
            "phase": _confirmed_field_value("Validation & Handover"),
            "role_hours": [
                {"role": "Solution Architect", "hours": 16},
                {"role": "Engineer", "hours": 32},
                {"role": "Project Manager", "hours": 12},
            ],
            "total": 60,
        },
    ]
    total_cost = 0.0
    rate_by_role = {row["role"]: _to_float(row["rate"]) for row in role_rates}
    for phase in phase_hours_table:
        for row in phase["role_hours"]:
            total_cost += _to_float(row.get("hours")) * rate_by_role.get(row.get("role"), 0.0)

    contribution = {
        "customer": {"amount": _confirmed_field_value(max(round(total_cost - target, 2), 0)), "pct": _confirmed_field_value("")},
        "partner": {"amount": _confirmed_field_value(0), "pct": _confirmed_field_value("")},
        "aws": {"amount": _confirmed_field_value(min(target, 125000)), "pct": _confirmed_field_value("")},
    }

    warnings = [
        "This is a Resource Planning draft. Final values must be reviewed with AWS Calculator, Bedrock usage assumption, SOW cost, customer scope, and sales owner."
    ]
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


def _runtime_response(runtime_result: dict, document: dict | None = None) -> dict:
    body = {
        "agent_response": runtime_result.get("result", ""),
        "version": runtime_result.get("version", 0),
        "status": runtime_result.get("status", "error"),
    }
    if "actions" in runtime_result:
        body["actions"] = runtime_result["actions"]
    if document:
        body["document"] = document
    status_code = 200 if body["status"] == "ok" else 500
    print(f"[runtime_response] status={body['status']} response_len={len(body['agent_response'])} has_document={document is not None}")
    return _response(status_code, body)


def _invoke_runtime(payload: dict) -> dict:
    try:
        from agent.lambdas.document_api.runtime_proxy import get_runtime_proxy

        return get_runtime_proxy().invoke(payload)
    except ModuleNotFoundError:
        runtime_arn = _resolve_agentcore_runtime_arn()
        resp = _get_agentcore_runtime_client().invoke_agent_runtime(
            agentRuntimeArn=runtime_arn,
            contentType="application/json",
            accept="application/json",
            payload=json.dumps(payload).encode("utf-8"),
        )
        raw = resp["response"].read()
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        if not raw:
            return {"result": "", "version": 0, "status": "error"}
        return json.loads(raw)


def _handle_runtime_invocation(
    doc_id: str,
    prompt: str,
    history: list,
    event: dict,
    *,
    create_shell_if_missing: bool,
) -> dict:
    user_id, err = _require_user(event)
    if err:
        return err

    if not doc_id or not prompt:
        return _response(400, {"error": "doc_id and prompt are required"})

    resp = table.get_item(Key={"document_id": doc_id})
    item = resp.get("Item")

    if item:
        forbidden = _check_ownership(item, user_id)
        if forbidden:
            return forbidden
    elif create_shell_if_missing:
        _save_to_ddb(_document_shell(doc_id, user_id))

    runtime_result = _invoke_runtime({
        "doc_id": doc_id,
        "prompt": prompt,
        "history": history,
        "user_id": user_id,
    })
    print(f"[runtime] result keys={list(runtime_result.keys())} status={runtime_result.get('status')} result_len={len(runtime_result.get('result', ''))} result_preview={runtime_result.get('result', '')[:200]}")

    # Re-fetch document from DynamoDB after Runtime processing
    # Runtime may have updated the document via patches
    updated_resp = table.get_item(Key={"document_id": doc_id})
    updated_doc = updated_resp.get("Item")
    if updated_doc:
        # Convert Decimal to JSON-safe format
        updated_doc = json.loads(_json(updated_doc))

    return _runtime_response(runtime_result, document=updated_doc)


DEFAULT_BOUNDED_WINDOW = 20


# --- Document CRUD: Multi-doc support ---

def _handle_create_document(event: dict) -> dict:
    user_id, err = _require_user(event)
    if err:
        return err

    body = json.loads(event.get("body") or "{}")
    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    year = datetime.now(timezone.utc).strftime("%Y")
    default_title = f"{year} APN PoC Project Plan_미정_미정_{today_str}"
    title = body.get("title") or default_title

    doc_id = f"doc-{uuid.uuid4().hex[:12]}"
    now = _now_iso()

    item = {
        "document_id": doc_id,
        "user_id": user_id,
        "title": title,
        "version": 0,
        "created_at": now,
        "updated_at": now,
        "mode": "architecture_absent",
        "template": "apn_poc_project_plan",
        "meta": _default_meta(),
        "sections": _default_sections(),
        "completion_score": 0,
        "blocking_issues": [],
        "warnings": [],
    }
    _save_to_ddb(item)

    return _response(200, {
        "document_id": doc_id,
        "title": title,
        "user_id": user_id,
        "created_at": now,
        "updated_at": now,
    })


def _handle_list_documents(event: dict) -> dict:
    user_id, err = _require_user(event)
    if err:
        return err

    qs = event.get("queryStringParameters") or {}
    limit = int(qs.get("limit", "50"))

    resp = table.query(
        IndexName="user_id-updated_at-index",
        KeyConditionExpression="user_id = :uid",
        ExpressionAttributeValues={":uid": user_id},
        ScanIndexForward=False,
        Limit=limit,
    )

    items = [
        {
            "document_id": item.get("document_id"),
            "title": item.get("title", "제목 없음"),
            "updated_at": item.get("updated_at"),
            "created_at": item.get("created_at"),
            "completion_score": float(item.get("completion_score", 0) or 0),
        }
        for item in resp.get("Items", [])
    ]

    return _response(200, {"documents": items, "count": len(items)})


# --- History ---

def _handle_save_history(doc_id: str, body: dict, event: dict) -> dict:
    user_id, err = _require_user(event)
    if err:
        return err

    # Ownership check
    doc_resp = table.get_item(Key={"document_id": doc_id})
    doc_item = doc_resp.get("Item")
    if doc_item:
        forbidden = _check_ownership(doc_item, user_id)
        if forbidden:
            return forbidden

    session_id = body.get("session_id", "default")
    messages = body.get("messages", [])
    bounded_window = body.get("bounded_window", DEFAULT_BOUNDED_WINDOW)

    item = {
        "document_id": doc_id,
        "session_id": session_id,
        "user_id": user_id,
        "messages": messages,
        "bounded_window": bounded_window,
        "total_count": len(messages),
        "updated_at": _now_iso(),
    }
    raw = _json(item)
    history_table.put_item(Item=json.loads(raw, parse_float=Decimal))
    return _response(200, {
        "status": "ok",
        "document_id": doc_id,
        "session_id": session_id,
        "total_count": len(messages),
        "bounded_window": bounded_window,
    })


def _handle_load_history(doc_id: str, event: dict) -> dict:
    user_id, err = _require_user(event)
    if err:
        return err

    # Ownership check
    doc_resp = table.get_item(Key={"document_id": doc_id})
    doc_item = doc_resp.get("Item")
    if doc_item:
        forbidden = _check_ownership(doc_item, user_id)
        if forbidden:
            return forbidden

    qs = event.get("queryStringParameters") or {}
    session_id = qs.get("session_id")

    if session_id:
        resp = history_table.get_item(
            Key={"document_id": doc_id, "session_id": session_id}
        )
        item = resp.get("Item")
    else:
        from boto3.dynamodb.conditions import Key
        resp = history_table.query(
            KeyConditionExpression=Key("document_id").eq(doc_id),
            ScanIndexForward=False,
            Limit=1,
        )
        items = resp.get("Items", [])
        item = items[0] if items else None

    if not item:
        return _response(200, {
            "document_id": doc_id,
            "session_id": session_id or "",
            "messages": [],
            "bounded_window": DEFAULT_BOUNDED_WINDOW,
            "total_count": 0,
        })
    return _response(200, item)


# --- Chat ---

_lambda_client = None

def _get_lambda_client():
    global _lambda_client
    if _lambda_client is None:
        _lambda_client = boto3.client("lambda", region_name=REGION)
    return _lambda_client


def _handle_chat(doc_id: str, body: dict, event: dict) -> dict:
    """Async chat: immediately returns 202, triggers background processing."""
    message = body.get("message", "")
    if not message:
        return _response(400, {"error": "message is required"})

    user_id, err = _require_user(event)
    if err:
        return err

    # Ensure document exists
    resp = table.get_item(Key={"document_id": doc_id})
    item = resp.get("Item")
    if item:
        forbidden = _check_ownership(item, user_id)
        if forbidden:
            return forbidden
    else:
        _save_to_ddb(_document_shell(doc_id, user_id))

    # Save user message to history (DynamoDB = source of truth)
    _append_history_message(doc_id, user_id, {
        "id": f"user-{uuid.uuid4().hex[:8]}",
        "role": "user",
        "content": message,
        "timestamp": _now_iso(),
    })

    # Set agent_status in DynamoDB
    _update_agent_status(doc_id, "processing", "task_planner", "🔍 메시지 분석 중...")

    # Signal frontend to refresh
    _publish_refresh(doc_id)

    # Invoke self asynchronously
    fn_name = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "doc-agent-document-api")
    _get_lambda_client().invoke(
        FunctionName=fn_name,
        InvocationType="Event",
        Payload=json.dumps({
            "_async_chat": True,
            "doc_id": doc_id,
            "message": message,
            "history": body.get("history", []),
            "user_id": user_id,
        }),
    )

    return _response(202, {"status": "processing", "message": "처리 중..."})


def _handle_async_chat(payload: dict) -> dict:
    """Background chat processing — DynamoDB is source of truth."""
    doc_id = payload["doc_id"]
    message = payload["message"]
    history = payload.get("history", [])
    user_id = payload["user_id"]
    chat_channel = f"/docs/{doc_id}/chat"
    thinking_steps = []
    thinking_msg_id = f"thinking-{uuid.uuid4().hex[:8]}"

    def _progress(step: str, agent: str = "runtime"):
        """Update thinking message in DynamoDB + publish progress to AppSync.

        Sends two AppSync events:
        1. ``progress`` with the step text — frontend updates the thinking
           box immediately without any REST fetch.
        2. ``refresh`` to signal history polling as a backup.
        """
        thinking_steps.append(step)
        _update_agent_status(doc_id, "processing", agent, step)
        # Update the thinking message in history (replace entire message)
        try:
            # First, try to find and update existing thinking message
            hist_resp = history_table.get_item(Key={"document_id": doc_id, "session_id": "default"})
            hist_item = hist_resp.get("Item", {})
            messages = hist_item.get("messages", [])

            # Find existing thinking message or append new one
            thinking_found = False
            for i, m in enumerate(messages):
                if m.get("id") == thinking_msg_id:
                    messages[i] = {
                        "id": thinking_msg_id,
                        "role": "agent",
                        "content": step,
                        "timestamp": _now_iso(),
                        "type": "thinking",
                        "thinking_steps": list(thinking_steps),
                    }
                    thinking_found = True
                    break

            if not thinking_found:
                messages.append({
                    "id": thinking_msg_id,
                    "role": "agent",
                    "content": step,
                    "timestamp": _now_iso(),
                    "type": "thinking",
                    "thinking_steps": list(thinking_steps),
                })

            history_table.put_item(Item=json.loads(_json({
                "document_id": doc_id,
                "session_id": "default",
                "user_id": user_id,
                "messages": messages,
                "bounded_window": DEFAULT_BOUNDED_WINDOW,
                "total_count": len(messages),
                "updated_at": _now_iso(),
            }), parse_float=Decimal))
        except Exception as e:
            print(f"[progress] DynamoDB update failed: {e}")

        # Publish the step immediately to AppSync so the frontend can update
        # the thinking message without waiting for a REST fetch round-trip.
        _publish_event(f"/docs/{doc_id}/chat", {
            "type": "progress",
            "agent": agent,
            "step": step,
            "thinking_id": thinking_msg_id,
            "thinking_steps": list(thinking_steps),
        })
        # Backup: refresh signal for clients without WebSocket.
        _publish_refresh(doc_id)

    try:
        # Step 1: Analyze message
        _progress(f"🔍 메시지 분석: \"{message[:60]}{'...' if len(message) > 60 else ''}\"", "task_planner")

        # Step 2: Execute via Runtime
        _progress("🧠 Runtime 실행 중...", "runtime")
        runtime_result = _invoke_runtime({
            "doc_id": doc_id,
            "prompt": message,
            "history": history,
            "user_id": user_id,
        })
        print(f"[async_chat] runtime result: status={runtime_result.get('status')} result_len={len(runtime_result.get('result', ''))} keys={list(runtime_result.keys())} execution_log_type={type(runtime_result.get('execution_log')).__name__}")

        # Step 3: Extract execution log and build detailed thinking steps
        agent_response = runtime_result.get("result", "")
        execution_log = runtime_result.get("execution_log", {})
        planned = execution_log.get("planned", []) if isinstance(execution_log, dict) else []
        executed = execution_log.get("executed", []) if isinstance(execution_log, dict) else (execution_log if isinstance(execution_log, list) else [])

        agent_labels = {
            "discovery_agent": "📋 정보 수집",
            "section_writer_agent": "✏️ 섹션 작성",
            "staffing_agent": "👥 팀 구성",
            "cost_agent": "💰 비용 산정",
            "architecture_agent": "🏗️ 아키텍처",
            "reviewer_agent": "🔎 리뷰",
            "formatter_agent": "📄 DOCX",
            "conversation_agent": "💬 대화",
        }

        # Show LLM router's plan
        if planned:
            plan_names = [agent_labels.get(p.get("agent", ""), p.get("agent", "")) for p in planned]
            thinking_steps.append(f"📋 LLM 라우터 판단: {', '.join(plan_names)}")

        # Show executed agents with results
        executed_agents = set()
        if executed:
            thinking_steps.append("🧠 서브에이전트 실행:")
            for i, entry in enumerate(executed):
                agent_name = entry.get("agent", "")
                executed_agents.add(agent_name)
                label = agent_labels.get(agent_name, agent_name)
                action = entry.get("action", "")
                success = entry.get("success", True)
                patches = entry.get("patches_count", 0)
                is_last = (i == len(executed) - 1) and not any(p.get("agent", "") not in executed_agents for p in planned)
                prefix = "  └─" if is_last else "  ├─"
                if success:
                    thinking_steps.append(f"{prefix} {label}: {action} 완료 ✅ ({patches}건 변경)")
                else:
                    thinking_steps.append(f"{prefix} {label}: {action} 실패 ⚠️")

        # Show planned but not executed agents
        for p in planned:
            if p.get("agent", "") not in executed_agents:
                label = agent_labels.get(p.get("agent", ""), p.get("agent", ""))
                thinking_steps.append(f"  ⊘ {label}: 실행되지 않음 (Runtime이 불필요로 판단)")

        thinking_steps.append("✅ 작업 완료")
        _publish_event(chat_channel, {
            "type": "progress", "agent": "runtime", "step": "complete",
            "message": "✅ 작업 완료 — 결과를 정리하고 있습니다...",
        })

        # Step 5: Saving results
        thinking_steps.append("💾 결과 저장 중...")
        _update_agent_status(doc_id, "processing", "saving", "💾 결과 저장 중...")

        # Step 5: Re-fetch updated document from DynamoDB
        updated_resp = table.get_item(Key={"document_id": doc_id})
        updated_doc = updated_resp.get("Item")
        if updated_doc:
            # Auto-generate title: {년도} APN PoC Project Plan_{고객사}_{프로젝트명}_{YYYYMMDD}
            meta = updated_doc.get("meta", {})
            cover = updated_doc.get("sections", {}).get("cover", {})
            customer = meta.get("customer", {}).get("user_input") or "미정"
            project_name = cover.get("title") or cover.get("goal") or "미정"
            year = datetime.now(timezone.utc).strftime("%Y")
            today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
            new_title = f"{year} APN PoC Project Plan_{customer}_{project_name}_{today_str}"
            if updated_doc.get("title") != new_title:
                table.update_item(
                    Key={"document_id": doc_id},
                    UpdateExpression="SET title = :t",
                    ExpressionAttributeValues={":t": new_title},
                )
                updated_doc["title"] = new_title
            updated_doc = json.loads(_json(updated_doc))

        # Step 6: Finalize thinking + save agent response
        _progress("✅ 작업 완료", "saving")
        now = _now_iso()

        # Final update of thinking message with all steps
        thinking_steps.append("✅ 완료")
        _progress("✅ 완료", "complete")

        # Append agent response
        _append_history_message(doc_id, user_id, {
            "id": f"agent-{uuid.uuid4().hex[:8]}",
            "role": "agent",
            "content": agent_response or "처리 완료",
            "timestamp": now,
        })

        # Step 7: Set idle + refresh
        _update_agent_status(doc_id, "idle", "", "")
        _publish_refresh(doc_id)

        print(f"[async_chat] completed for {doc_id}")

    except Exception as e:
        print(f"[async_chat] error: {e}")
        _update_agent_status(doc_id, "error", "", str(e)[:200])
        _append_history_message(doc_id, user_id, {
            "id": f"error-{uuid.uuid4().hex[:8]}",
            "role": "agent",
            "content": f"처리 중 오류가 발생했습니다: {str(e)[:200]}",
            "timestamp": _now_iso(),
        })
        _publish_refresh(doc_id)

    return _response(200, {"status": "ok"})


def _handle_invocations(body: dict, event: dict) -> dict:
    doc_id = body.get("doc_id", "")
    prompt = body.get("prompt", "")
    history = body.get("history", [])

    return _handle_runtime_invocation(
        doc_id,
        prompt,
        history,
        event,
        create_shell_if_missing=False,
    )


def _read_lambda_payload(payload: Any) -> dict:
    raw = payload.read() if hasattr(payload, "read") else payload
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    if not raw:
        return {}
    return json.loads(raw)


DEFAULT_GENERATE_DIAGRAM_FUNCTION_NAME = "doc-agent-generate-diagram"
DEFAULT_CREATE_CALCULATOR_LINK_FUNCTION_NAME = "doc-agent-create-calculator-link"
DEFAULT_EXPLAIN_AWS_SERVICES_FUNCTION_NAME = "doc-agent-explain-aws-services"


def _invoke_gateway_tool(function_name: str, payload: dict) -> tuple[dict | None, str | None]:
    """Invoke a gateway-tool style Lambda (inputPayload / outputPayload JSON)."""
    try:
        client = boto3.client("lambda", region_name=REGION)
        resp = client.invoke(
            FunctionName=function_name,
            InvocationType="RequestResponse",
            Payload=json.dumps({"inputPayload": _json(payload)}).encode("utf-8"),
        )
    except Exception as exc:
        return None, f"invoke_error: {_safe_error_reason(exc)}"

    body = _read_lambda_payload(resp.get("Payload"))
    if resp.get("FunctionError"):
        # Emit only a short error class + snippet — avoid dumping large payloads.
        if isinstance(body, dict):
            err_cls = str(body.get("errorType") or body.get("error") or "LambdaFunctionError")
            err_msg = str(body.get("errorMessage") or body.get("message") or "")[:160]
            return None, f"lambda_error: {err_cls}: {err_msg}"
        return None, f"lambda_error: {str(body)[:160]}"

    output_raw = body.get("outputPayload", body) if isinstance(body, dict) else {}
    if isinstance(output_raw, str):
        try:
            parsed = json.loads(output_raw)
        except Exception as exc:
            return None, f"parse_error: {_safe_error_reason(exc)}"
    elif isinstance(output_raw, dict):
        parsed = output_raw
    else:
        return None, f"unexpected_payload_type: {type(output_raw).__name__}"
    return parsed, None


def _services_from_document(item: dict) -> list[dict]:
    """Extract AWS services from the architecture section for MCP calls."""
    sections = item.get("sections", {}) if isinstance(item.get("sections"), dict) else {}
    arch = sections.get("architecture", {}) if isinstance(sections.get("architecture"), dict) else {}
    out: list[dict] = []
    for svc in arch.get("services", []) or []:
        if not isinstance(svc, dict):
            if isinstance(svc, str) and svc.strip():
                out.append({"service_name": svc.strip()})
            continue
        name = _resolve_field_value(svc.get("service_name")) or svc.get("service_id", "")
        if not name:
            continue
        out.append({
            "service_name": str(name),
            "service_id": svc.get("service_id", ""),
            "service_code": svc.get("service_code", ""),
            "config": svc.get("config") if isinstance(svc.get("config"), dict) else {},
        })
    return out


def _handle_generate_architecture_diagram(doc_id: str, body: dict, event: dict) -> dict:
    _user_id, permission, item, err = _load_document_for_action(doc_id, event, "read")
    if err:
        return err

    # Prefer caller-supplied services; otherwise read from DocumentState.
    services = body.get("services")
    if not isinstance(services, list) or not services:
        services = _services_from_document(item)

    missing_inputs: list[str] = []
    if not services:
        missing_inputs.append("services")

    payload = {
        "doc_id": doc_id,
        "services": services,
        "architecture_description": str(body.get("architecture_description", "")),
        "use_case": str(body.get("use_case", "")),
        "existing_drawio": body.get("existing_drawio"),
        "skip_drawio": bool(body.get("skip_drawio", False)),
    }
    function_name = os.environ.get(
        "GENERATE_DIAGRAM_FUNCTION_NAME",
        DEFAULT_GENERATE_DIAGRAM_FUNCTION_NAME,
    )
    result, error = _invoke_gateway_tool(function_name, payload)
    if result is None:
        # Downstream Lambda unreachable — build an in-process engineer draft.
        names = []
        for svc in services:
            if isinstance(svc, dict):
                n = svc.get("service_name") or svc.get("name") or ""
            else:
                n = str(svc)
            n = str(n).strip()
            if n:
                names.append(n)
        fallback_draft = {
            "use_case": str(body.get("use_case", "")),
            "layers": [{"name": "All", "services": names}] if names else [],
            "flows": [],
            "notes": ["downstream Lambda unavailable — in-process fallback"],
            "warning": "generate_architecture_diagram invoke failed",
        }
        _log("generate_architecture_diagram", "warn",
             doc_id=doc_id, error_reason=error or "unknown")
        return _partial({
            "document_id": doc_id,
            "permission": permission,
            "mode": "engineer_draft",
            "drawio_s3_key": "",
            "preview_s3_key": "",
            "services_extracted": names,
            "engineer_draft": fallback_draft,
            "changed_sections": [],
        }, warnings=[
            "generate_architecture_diagram Lambda unavailable — engineer draft returned",
            error or "unknown error",
        ], missing_inputs=missing_inputs or None)

    # Downstream succeeded — but it may still have returned engineer_draft
    # mode (empty services, skip_drawio, or S3 failure). Treat that as
    # partial_completed so the frontend does not claim full success.
    result["document_id"] = doc_id
    result["permission"] = permission
    mode = str(result.get("mode") or "")
    tool_warnings = []
    draft = result.get("engineer_draft") or {}
    if isinstance(draft, dict) and draft.get("warning"):
        tool_warnings.append(str(draft["warning"]))
    if result.get("error"):
        tool_warnings.append(str(result["error"]))

    _log("generate_architecture_diagram", "info",
         doc_id=doc_id, mode=mode, services=len(services))

    if mode == "drawio" and result.get("drawio_s3_key"):
        return _ok(result, message="Architecture diagram generated.",
                   warnings=tool_warnings or None)
    return _partial(
        result,
        message="Architecture engineer draft returned.",
        warnings=tool_warnings or [
            "drawio artefact unavailable — engineer draft returned",
        ],
        missing_inputs=missing_inputs or None,
    )


def _handle_create_calculator_link(doc_id: str, body: dict, event: dict) -> dict:
    _user_id, permission, item, err = _load_document_for_action(doc_id, event, "read")
    if err:
        return err

    services = body.get("services")
    if not isinstance(services, list) or not services:
        services = _services_from_document(item)

    missing_inputs: list[str] = []
    if not services:
        missing_inputs.append("services")

    payload = {
        "doc_id": doc_id,
        "services": services,
        "region": str(body.get("region", REGION)),
        "existing_link": str(body.get("existing_link", "")),
    }
    function_name = os.environ.get(
        "CREATE_CALCULATOR_LINK_FUNCTION_NAME",
        DEFAULT_CREATE_CALCULATOR_LINK_FUNCTION_NAME,
    )
    result, error = _invoke_gateway_tool(function_name, payload)
    if result is None:
        # Downstream unreachable — local fallback preserves document_local_summary.
        fallback_rows = []
        total = 0.0
        for svc in services:
            name = svc.get("service_name", "") if isinstance(svc, dict) else str(svc)
            hint = svc.get("monthly_cost_hint") if isinstance(svc, dict) else None
            try:
                hint_num = float(hint) if hint is not None else None
            except (TypeError, ValueError):
                hint_num = None
            if hint_num is not None:
                total += hint_num
            fallback_rows.append({
                "service_name": name,
                "service_code": svc.get("service_code", "") if isinstance(svc, dict) else "",
                "monthly_cost": hint_num,
            })
        _log("create_calculator_link", "warn",
             doc_id=doc_id, error_reason=error or "unknown")
        return _partial({
            "document_id": doc_id,
            "permission": permission,
            "mode": "fallback",
            "calculator_share_url": None,
            "service_breakdown": [],
            "manual_estimate_items": [],
            "document_local_summary": {
                "monthly_cost_total": round(total, 2),
                "currency": "USD",
                "region": payload["region"],
                "generated_at": _now_iso(),
                "rows": fallback_rows,
            },
            "fallback_card": {
                "type": "fallback",
                "message": "Calculator Link Lambda unavailable",
                "items": fallback_rows,
            },
            "changed_sections": [],
        }, warnings=[
            "Calculator Link Lambda unavailable — document-local summary only",
            error or "unknown error",
        ], missing_inputs=missing_inputs or None)

    # Downstream responded — inspect mode and warnings to decide envelope.
    result["document_id"] = doc_id
    result["permission"] = permission
    mode = str(result.get("mode") or "")
    downstream_warnings = []
    if isinstance(result.get("warnings"), list):
        downstream_warnings = [str(w) for w in result["warnings"] if w]

    _log("create_calculator_link", "info",
         doc_id=doc_id, mode=mode, services=len(services))

    if mode in {"node_lambda", "mcp"} and result.get("calculator_share_url"):
        return _ok(result,
                   message="Calculator link created.",
                   warnings=downstream_warnings or None)
    return _partial(
        result,
        message="Calculator link unavailable — fallback summary returned.",
        warnings=downstream_warnings or [
            "No calculator backend configured — fallback card returned",
        ],
        missing_inputs=missing_inputs or None,
    )


def _handle_explain_aws_services(doc_id: str, body: dict, event: dict) -> dict:
    _user_id, permission, item, err = _load_document_for_action(doc_id, event, "read")
    if err:
        return err

    services = body.get("services")
    if not isinstance(services, list) or not services:
        services = [
            s.get("service_name") if isinstance(s, dict) else str(s)
            for s in _services_from_document(item)
        ]
        services = [s for s in services if s]

    missing_inputs: list[str] = []
    if not services:
        missing_inputs.append("services")

    payload = {
        "services": services,
        "use_case": str(body.get("use_case", "")),
        "language": str(body.get("language", "en")),
    }
    function_name = os.environ.get(
        "EXPLAIN_AWS_SERVICES_FUNCTION_NAME",
        DEFAULT_EXPLAIN_AWS_SERVICES_FUNCTION_NAME,
    )
    result, error = _invoke_gateway_tool(function_name, payload)
    if result is None:
        _log("explain_aws_services", "warn",
             doc_id=doc_id, error_reason=error or "unknown")
        return _partial({
            "document_id": doc_id,
            "permission": permission,
            "mode": "static",
            "explanations": [],
            "changed_sections": [],
        }, warnings=[
            "explain_aws_services Lambda unavailable",
            error or "unknown error",
        ], missing_inputs=missing_inputs or None)

    result["document_id"] = doc_id
    result["permission"] = permission
    mode = str(result.get("mode") or "")
    downstream_warnings = []
    if isinstance(result.get("warnings"), list):
        downstream_warnings = [str(w) for w in result["warnings"] if w]

    explanations = result.get("explanations") or []
    placeholders = sum(
        1 for e in explanations
        if isinstance(e, dict) and e.get("source") == "unknown"
    )

    _log("explain_aws_services", "info",
         doc_id=doc_id, mode=mode,
         explanations=len(explanations), unknown=placeholders)

    # No services OR any unknown placeholder OR llm_fallback → partial.
    if not explanations or placeholders > 0 or mode == "llm_fallback":
        return _partial(
            result,
            message="Service explanations completed with gaps.",
            warnings=downstream_warnings or [
                "one or more services had no static explanation",
            ],
            missing_inputs=missing_inputs or None,
        )
    return _ok(result,
               message="Service explanations returned.",
               warnings=downstream_warnings or None)


def _handle_export(doc_id: str, event: dict) -> dict:
    user_id, err = _require_user(event)
    if err:
        return err

    resp = table.get_item(Key={"document_id": doc_id})
    item = resp.get("Item")
    if not item:
        return _response(404, {"error": "not found"})

    forbidden = _check_ownership(item, user_id)
    if forbidden:
        return forbidden

    version = int(item.get("version", 0))
    _log("export", "info", doc_id=doc_id, version=version, stage="start")

    payload = {
        "doc_id": doc_id,
        "version": version,
        "meta": item.get("meta", {}),
        "sections": item.get("sections", {}),
        "staffing_plan": item.get("staffing_plan", {}),
    }
    function_name = os.environ.get(
        "EXPORT_DOCX_FUNCTION_NAME",
        DEFAULT_EXPORT_DOCX_FUNCTION_NAME,
    )

    try:
        lambda_client = boto3.client("lambda", region_name=REGION)
        invoke_resp = lambda_client.invoke(
            FunctionName=function_name,
            InvocationType="RequestResponse",
            Payload=json.dumps(
                {"inputPayload": _json(payload)},
            ).encode("utf-8"),
        )
    except Exception as exc:
        reason = _safe_error_reason(exc)
        _log("export", "error", doc_id=doc_id, stage="invoke", error_reason=reason)
        return _failed(500, error_reason=reason,
                       message="Export Lambda invocation failed.",
                       extra={"stage": "invoke"})

    try:
        lambda_body = _read_lambda_payload(invoke_resp.get("Payload"))
        if invoke_resp.get("FunctionError"):
            if isinstance(lambda_body, dict):
                err_cls = str(lambda_body.get("errorType") or "LambdaFunctionError")
                err_msg = str(lambda_body.get("errorMessage") or "")[:160]
                reason = f"{err_cls}: {err_msg}"
            else:
                reason = str(lambda_body)[:160]
            _log("export", "error", doc_id=doc_id, stage="lambda", error_reason=reason)
            return _failed(500, error_reason=reason,
                           message="Export Lambda returned an error.",
                           extra={"stage": "lambda"})

        output_payload = lambda_body.get("outputPayload", "{}")
        if isinstance(output_payload, str):
            output = json.loads(output_payload)
        elif isinstance(output_payload, dict):
            output = output_payload
        else:
            output = {}
    except Exception as exc:
        reason = _safe_error_reason(exc)
        _log("export", "error", doc_id=doc_id, stage="parse_response", error_reason=reason)
        return _failed(500, error_reason=reason,
                       message="Export response parse failed.",
                       extra={"stage": "parse_response"})

    if output.get("error"):
        stage = str(output.get("stage", "export_docx"))
        reason = str(output.get("error"))[:160]
        _log("export", "error", doc_id=doc_id, stage=stage, error_reason=reason)
        return _failed(500, error_reason=reason,
                       message="Export failed in downstream stage.",
                       extra={"stage": stage, "details": output})

    if not output.get("download_url"):
        _log("export", "error", doc_id=doc_id, stage="missing_download_url")
        return _failed(500, error_reason="missing_download_url",
                       message="Export did not return download_url.",
                       extra={"stage": "missing_download_url", "details": output})

    _log("export", "info", doc_id=doc_id, s3_key=output.get("s3_key"))
    # Keep the export success shape unchanged for backward compatibility with
    # the frontend and existing tests — envelope fields are intentionally NOT
    # merged in here. Error paths above still include the standard envelope.
    return _response(200, output)


def _handle_get_document_state(doc_id: str, event: dict) -> dict:
    user_id, permission, item, err = _load_document_for_action(doc_id, event, "read")
    if err:
        return err
    return _response(200, {
        "document": item,
        "permission": permission,
        "user_id": user_id,
    })


def _handle_propose_document_patch(doc_id: str, body: dict, event: dict) -> dict:
    _user_id, permission, item, err = _load_document_for_action(doc_id, event, "suggest")
    if err:
        return err
    operations = body.get("json_patch") or body.get("patch") or body.get("operations") or []
    try:
        _apply_json_patch_copy(json.loads(_json(item)), operations)
    except Exception as exc:
        return _response(400, {"error": str(exc), "status": "invalid_patch"})

    requires_review = _document_requires_review(item)
    direct_apply_allowed = PERMISSION_ORDER[permission] >= PERMISSION_ORDER["edit"] and not requires_review
    return _response(200, {
        "status": "ok",
        "document_id": doc_id,
        "permission": permission,
        "direct_apply_allowed": direct_apply_allowed,
        "change_request_required": not direct_apply_allowed,
        "summary": body.get("summary", f"{len(operations)} proposed document change(s)"),
        "json_patch": operations,
    })


def _handle_apply_document_patch(doc_id: str, body: dict, event: dict) -> dict:
    user_id, permission, item, err = _load_document_for_action(doc_id, event, "suggest")
    if err:
        return err

    operations = body.get("json_patch") or body.get("patch") or body.get("operations") or []
    if permission == "suggest" or (permission == "edit" and _document_requires_review(item)):
        try:
            _apply_json_patch_copy(json.loads(_json(item)), operations)
        except Exception as exc:
            return _response(400, {"error": str(exc), "status": "invalid_patch"})
        change_request = _change_request_from_patch(
            doc_id,
            user_id,
            operations,
            summary=body.get("summary", ""),
            changes=body.get("changes"),
        )
        try:
            saved = _save_change_request(item, int(item.get("version", 0)), change_request)
        except Exception as exc:
            if "VersionConflict" in type(exc).__name__:
                return _response(409, {"error": str(exc), "status": "version_conflict"})
            raise
        return _response(202, {
            "status": "change_request_created",
            "change_request": change_request,
            "version": saved["version"],
        })

    if PERMISSION_ORDER[permission] < PERMISSION_ORDER["edit"]:
        return _response(403, {"error": "insufficient_permission", "required": "edit", "permission": permission})

    expected_version = int(body.get("expected_version", item.get("version", 0)))
    if expected_version != int(item.get("version", 0)):
        return _response(409, {"error": "version mismatch", "status": "version_conflict"})
    try:
        patched = _apply_json_patch_copy(json.loads(_json(item)), operations)
        saved = _conditional_save_document(patched, expected_version)
    except Exception as exc:
        if "VersionConflict" in type(exc).__name__:
            return _response(409, {"error": str(exc), "status": "version_conflict"})
        return _response(400, {"error": str(exc), "status": "invalid_patch"})

    _publish_document_patch(doc_id, operations, saved, expected_version, "document_api")
    return _response(200, {"status": "applied", "version": saved["version"], "operations": operations})


def _handle_create_change_request(doc_id: str, body: dict, event: dict) -> dict:
    user_id, permission, item, err = _load_document_for_action(doc_id, event, "suggest")
    if err:
        return err
    operations = body.get("json_patch") or body.get("patch") or body.get("operations") or []
    try:
        _apply_json_patch_copy(json.loads(_json(item)), operations)
    except Exception as exc:
        return _response(400, {"error": str(exc), "status": "invalid_patch"})
    change_request = _change_request_from_patch(
        doc_id,
        user_id,
        operations,
        summary=body.get("summary", ""),
        changes=body.get("changes"),
    )
    try:
        saved = _save_change_request(item, int(item.get("version", 0)), change_request)
    except Exception as exc:
        if "VersionConflict" in type(exc).__name__:
            return _response(409, {"error": str(exc), "status": "version_conflict"})
        raise
    return _response(201, {
        "status": "pending",
        "permission": permission,
        "change_request": change_request,
        "version": saved["version"],
    })


def _handle_approve_change_request(doc_id: str, body: dict, event: dict) -> dict:
    user_id, _permission, item, err = _load_document_for_action(doc_id, event, "master")
    if err:
        return err
    change_request_id = body.get("change_request_id", "")
    index, change_request = _find_change_request(item, change_request_id)
    if change_request is None:
        return _response(404, {"error": "change request not found"})
    if change_request.get("status") != "pending":
        return _response(409, {"error": "change request is not pending", "status": change_request.get("status")})

    operations = change_request.get("json_patch") or []
    expected_version = int(item.get("version", 0))
    try:
        patched = _apply_json_patch_copy(json.loads(_json(item)), operations)
        patched["change_requests"][index]["status"] = "approved"
        patched["change_requests"][index]["reviewed_by"] = user_id
        patched["change_requests"][index]["reviewed_at"] = _now_iso()
        patched["change_requests"][index]["updated_at"] = patched["change_requests"][index]["reviewed_at"]
        saved = _conditional_save_document(patched, expected_version)
    except Exception as exc:
        if "VersionConflict" in type(exc).__name__:
            return _response(409, {"error": str(exc), "status": "version_conflict"})
        return _response(400, {"error": str(exc), "status": "invalid_patch"})

    _publish_document_patch(doc_id, operations, saved, expected_version, "change_request")
    return _response(200, {
        "status": "approved",
        "change_request_id": change_request_id,
        "version": saved["version"],
    })


def _handle_reject_change_request(doc_id: str, body: dict, event: dict) -> dict:
    user_id, _permission, item, err = _load_document_for_action(doc_id, event, "master")
    if err:
        return err
    change_request_id = body.get("change_request_id", "")
    index, change_request = _find_change_request(item, change_request_id)
    if change_request is None:
        return _response(404, {"error": "change request not found"})
    if change_request.get("status") != "pending":
        return _response(409, {"error": "change request is not pending", "status": change_request.get("status")})

    expected_version = int(item.get("version", 0))
    updated = deepcopy(item)
    now = _now_iso()
    updated["change_requests"][index]["status"] = "rejected"
    updated["change_requests"][index]["reviewed_by"] = user_id
    updated["change_requests"][index]["reviewed_at"] = now
    updated["change_requests"][index]["updated_at"] = now
    if body.get("reason"):
        updated["change_requests"][index]["rejection_reason"] = body["reason"]
    try:
        saved = _conditional_save_document(updated, expected_version)
    except Exception as exc:
        if "VersionConflict" in type(exc).__name__:
            return _response(409, {"error": str(exc), "status": "version_conflict"})
        raise
    return _response(200, {
        "status": "rejected",
        "change_request_id": change_request_id,
        "version": saved["version"],
    })


def _handle_run_submission_lint(doc_id: str, event: dict) -> dict:
    _user_id, permission, item, err = _load_document_for_action(doc_id, event, "read")
    if err:
        return err
    doc_dict = json.loads(_json(item))
    result = _document_lint_result(doc_dict)
    kb_warnings: list[str] = []
    # Attach short top-hit excerpts for the Reviewer — safe metadata only.
    try:
        sections = doc_dict.get("sections", {}) if isinstance(doc_dict.get("sections"), dict) else {}
        arch = sections.get("architecture", {}) if isinstance(sections.get("architecture"), dict) else {}
        services = []
        for svc in arch.get("services", []) or []:
            if isinstance(svc, dict):
                name = _resolve_field_value(svc.get("service_name")) or svc.get("service_id", "")
                if name:
                    services.append(str(name))
        sample_hits = _query_approved_samples(services=services, top_k=3)
        result["kb_retrieval"] = sample_hits
        if isinstance(sample_hits, dict) and sample_hits.get("mode") == "fallback":
            kb_warnings.append(
                "Approved samples KB not configured — using static fallback"
            )
    except Exception as exc:
        _log("run_submission_lint", "warn",
             doc_id=doc_id, kb_attach_error=_safe_error_reason(exc))
        kb_warnings.append("Failed to attach KB excerpts")
    result["document_id"] = doc_id
    result["permission"] = permission

    issues = result.get("issues") or {}
    critical = len(issues.get("critical") or [])
    high = len(issues.get("high") or [])
    missing = result.get("missing_questions") or []
    readiness = result.get("readiness_score")

    _log("run_submission_lint", "info",
         doc_id=doc_id, readiness=readiness,
         critical=critical, high=high, missing=len(missing))

    # Lint is read-only so always completes; partial only when KB attach failed.
    if critical or high:
        # Lint ran to completion; issues are findings, not partial-completion.
        return _ok(
            result,
            message=f"Submission lint completed ({critical} critical, {high} high).",
            warnings=kb_warnings or None,
            missing_inputs=[str(q) for q in missing] or None,
        )
    if kb_warnings:
        return _partial(
            result,
            message="Submission lint completed with KB attach warning.",
            warnings=kb_warnings,
            missing_inputs=[str(q) for q in missing] or None,
        )
    return _ok(
        result,
        message="Submission lint completed.",
        missing_inputs=[str(q) for q in missing] or None,
    )


def _handle_query_approved_samples(doc_id: str, body: dict, event: dict) -> dict:
    _user_id, permission, _item, err = _load_document_for_action(doc_id, event, "read")
    if err:
        return err
    services = body.get("services") or []
    if isinstance(services, str):
        services = [services]
    result = _query_approved_samples(
        section=str(body.get("section", "")),
        industry=str(body.get("industry", "")),
        use_case_type=str(body.get("use_case_type", "")),
        services=list(services) if isinstance(services, list) else [],
        query=str(body.get("query", "")),
        top_k=int(body.get("top_k", 3) or 3),
    )
    result["document_id"] = doc_id
    result["permission"] = permission
    mode = str(result.get("mode") or "")

    _log("query_approved_samples", "info",
         doc_id=doc_id, mode=mode,
         examples=len(result.get("examples") or []))

    if mode in {"kb", "configured"}:
        return _ok(result, message="Approved samples retrieved.")
    # fallback / unknown → partial with reason from result.message
    warning = str(result.get("message") or "Using static fallback")
    return _partial(result, warnings=[warning],
                    message="Approved samples returned from fallback.")


def _handle_get_section_recommendations(doc_id: str, event: dict) -> dict:
    _user_id, permission, _item, err = _load_document_for_action(doc_id, event, "read")
    if err:
        return err
    query = event.get("queryStringParameters") or {}
    section = ""
    if isinstance(query, dict):
        section = str(query.get("section", "") or "")
    missing_inputs = [] if section else ["section"]
    recommendations = _get_section_recommendations(section)
    payload = {
        "document_id": doc_id,
        "permission": permission,
        "section": section,
        "recommendations": recommendations,
        "source": "static_presets",
    }
    _log("section_recommendations", "info",
         doc_id=doc_id, section=section or "",
         count=len(recommendations))
    if not section:
        return _partial(payload,
                        warnings=["section query parameter is required"],
                        missing_inputs=missing_inputs,
                        message="section query parameter missing.")
    if not recommendations:
        return _partial(payload,
                        warnings=[f"no static presets for section '{section}'"],
                        message="No static presets for this section.")
    return _ok(payload, message="Section recommendations returned.")


def _handle_calculate_resource_plan(doc_id: str, body: dict, event: dict) -> dict:
    _user_id, permission, _item, err = _load_document_for_action(doc_id, event, "read")
    if err:
        return err

    # Accept numeric strings too; validate required inputs.
    target = _to_float(body.get("target_funding_amount"))
    mrr = _to_float(body.get("mrr"))
    arr = _to_float(body.get("arr"))
    sow_cost = _to_float(body.get("sow_cost"))

    missing_inputs: list[str] = []
    if target <= 0:
        missing_inputs.append("target_funding_amount")
    if arr <= 0 and mrr <= 0:
        missing_inputs.append("arr_or_mrr")
    if sow_cost <= 0:
        missing_inputs.append("sow_cost")

    result = _resource_plan(body)
    result["document_id"] = doc_id
    result["permission"] = permission
    warnings = [str(w) for w in (result.get("warnings") or []) if w]

    _log("calculate_resource_plan", "info",
         doc_id=doc_id, target=target, arr=arr, sow_cost=sow_cost,
         missing=len(missing_inputs))

    if missing_inputs:
        return _partial(
            result,
            message="Resource plan draft with missing inputs.",
            warnings=warnings or None,
            missing_inputs=missing_inputs,
        )
    return _ok(
        result,
        message="Resource plan draft computed.",
        warnings=warnings or None,
    )


def _handle_user_input(doc_id: str, body: dict, event: dict) -> dict:
    user_id, err = _require_user(event)
    if err:
        return err

    path = body.get("path", "")
    value = body.get("value")
    try:
        _path_parts(path)
    except ValueError as exc:
        return _response(400, {"error": str(exc)})

    resp = table.get_item(Key={"document_id": doc_id})
    item = resp.get("Item")
    if not item:
        return _response(404, {"error": "not found"})

    forbidden = _check_ownership(item, user_id)
    if forbidden:
        return forbidden

    expected_version = int(item.get("version", 0))
    doc_dict = json.loads(_json(item))

    # Top-level title update: when path is "title" and value is a string,
    # update doc_dict["title"] directly (not wrapped in FieldValue).
    if path == "title" and isinstance(value, str):
        doc_dict["title"] = value
        operations = [_patch_operation("replace", "/title", value, "user_input")]

        try:
            saved = _conditional_save_document(doc_dict, expected_version)
        except Exception as exc:
            if "VersionConflict" in type(exc).__name__:
                return _response(409, {"error": str(exc), "status": "version_conflict"})
            raise

        _publish_event(f"docs/{doc_id}/patch", {
            "type": "patch",
            "patch_id": f"patch-{uuid.uuid4().hex[:12]}",
            "doc_id": doc_id,
            "agent": "document_api",
            "operations": operations,
            "version": saved["version"],
            "version_before": expected_version,
            "version_after": saved["version"],
        })

        return _response(200, {"status": "ok", "version": saved["version"]})

    # Direct array/object replacement: if value is list or dict and path
    # does NOT end with .user_input, set the value directly without
    # wrapping in a FieldValue envelope.
    if isinstance(value, (list, dict)) and not path.rstrip("/").endswith(".user_input"):
        try:
            patch_path = _set_raw_user_input_path(doc_dict, path, value)
        except EditablePathError as exc:
            return _response(400, exc.to_response_body())
        except ValueError as exc:
            return _response(400, {"error": str(exc), "path": path})

        operations = [_patch_operation("replace", patch_path, value, "user_input")]

        try:
            saved = _conditional_save_document(doc_dict, expected_version)
        except Exception as exc:
            if "VersionConflict" in type(exc).__name__:
                return _response(409, {"error": str(exc), "status": "version_conflict"})
            raise

        _publish_event(f"docs/{doc_id}/patch", {
            "type": "patch",
            "patch_id": f"patch-{uuid.uuid4().hex[:12]}",
            "doc_id": doc_id,
            "agent": "document_api",
            "operations": operations,
            "version": saved["version"],
            "version_before": expected_version,
            "version_after": saved["version"],
        })

        return _response(200, {"status": "ok", "version": saved["version"]})

    # Scalar value or path ending in .user_input — wrap in FieldValue
    try:
        patch_path, updated_field = _set_user_input_field(doc_dict, path, value)
    except EditablePathError as exc:
        return _response(400, exc.to_response_body())
    except ValueError as exc:
        return _response(400, {"error": str(exc), "path": path})

    field_path = patch_path.rsplit("/", 1)[0]
    operations = [
        _patch_operation("replace", patch_path, value, "user_input"),
        _patch_operation("replace", f"{field_path}/user_edited", True, "user_input"),
        _patch_operation("replace", f"{field_path}/status", updated_field["status"], "user_input"),
    ]
    if patch_path.startswith("/staffing_plan/"):
        operations.extend(_staffing_recalculation_patches(doc_dict))

    try:
        saved = _conditional_save_document(doc_dict, expected_version)
    except Exception as exc:
        if "VersionConflict" in type(exc).__name__:
            return _response(409, {"error": str(exc), "status": "version_conflict"})
        raise

    _publish_event(f"docs/{doc_id}/patch", {
        "type": "patch",
        "patch_id": f"patch-{uuid.uuid4().hex[:12]}",
        "doc_id": doc_id,
        "agent": "document_api",
        "operations": operations,
        "version": saved["version"],
        "version_before": expected_version,
        "version_after": saved["version"],
    })

    return _response(200, {"status": "ok", "version": saved["version"]})


def handler(event: dict, context: Any) -> dict:
    # Handle async chat invocation (self-invoked)
    if event.get("_async_chat"):
        return _handle_async_chat(event)

    rc = event.get("requestContext", {})
    http = rc.get("http", {})
    method = http.get("method", event.get("httpMethod", "GET"))
    path = http.get("path", event.get("rawPath", "/"))

    if method == "OPTIONS":
        return _response(204, "")

    parts = [p for p in path.strip("/").split("/") if p]

    # POST /invocations
    if method == "POST" and len(parts) == 1 and parts[0] == "invocations":
        body = json.loads(event.get("body", "{}"))
        return _handle_invocations(body, event)

    # /documents (collection)
    if len(parts) == 1 and parts[0] == "documents":
        if method == "POST":
            return _handle_create_document(event)
        if method == "GET":
            return _handle_list_documents(event)
        return _response(405, {"error": "method not allowed"})

    # /review_rules (collection)
    if len(parts) == 1 and parts[0] == "review_rules":
        if method == "GET":
            return _handle_list_review_rules(event)
        if method == "POST":
            body = json.loads(event.get("body", "{}"))
            return _handle_create_review_rule(body, event)
        return _response(405, {"error": "method not allowed"})

    # /review_rules/{rule_id}
    if len(parts) == 2 and parts[0] == "review_rules":
        rule_id = parts[1]
        if method == "GET":
            return _handle_get_review_rule(rule_id, event)
        if method == "PUT":
            body = json.loads(event.get("body", "{}"))
            return _handle_update_review_rule(rule_id, body, event)
        if method == "DELETE":
            return _handle_delete_review_rule(rule_id, event)
        return _response(405, {"error": "method not allowed"})

    if len(parts) < 2 or parts[0] != "documents":
        return _response(400, {"error": "invalid path"})

    doc_id = parts[1]
    action = parts[2] if len(parts) >= 3 else ""

    try:
        if method == "GET" and not action:
            user_id, err = _require_user(event)
            if err:
                return err
            resp = table.get_item(Key={"document_id": doc_id})
            item = resp.get("Item")
            if not item:
                return _response(404, {"error": "not found"})
            forbidden = _check_ownership(item, user_id)
            if forbidden:
                return forbidden
            return _response(200, item)

        elif method == "DELETE" and not action:
            user_id, err = _require_user(event)
            if err:
                return err
            resp = table.get_item(Key={"document_id": doc_id})
            item = resp.get("Item")
            if not item:
                return _response(404, {"error": "not found"})
            forbidden = _check_ownership(item, user_id)
            if forbidden:
                return forbidden
            table.delete_item(Key={"document_id": doc_id})
            return _response(200, {"status": "deleted", "document_id": doc_id})

        elif method == "POST" and action == "chat":
            body = json.loads(event.get("body", "{}"))
            return _handle_chat(doc_id, body, event)

        elif method == "POST" and action == "history":
            body = json.loads(event.get("body", "{}"))
            return _handle_save_history(doc_id, body, event)

        elif method == "GET" and action == "history":
            return _handle_load_history(doc_id, event)

        elif method == "POST" and action == "user-input":
            body = json.loads(event.get("body", "{}"))
            return _handle_user_input(doc_id, body, event)

        elif action == "get_document_state" and method in {"GET", "POST"}:
            return _handle_get_document_state(doc_id, event)

        elif method == "POST" and action == "propose_document_patch":
            body = json.loads(event.get("body", "{}"))
            return _handle_propose_document_patch(doc_id, body, event)

        elif method == "POST" and action == "apply_document_patch":
            body = json.loads(event.get("body", "{}"))
            return _handle_apply_document_patch(doc_id, body, event)

        elif method == "POST" and action == "create_change_request":
            body = json.loads(event.get("body", "{}"))
            return _handle_create_change_request(doc_id, body, event)

        elif method == "POST" and action == "approve_change_request":
            body = json.loads(event.get("body", "{}"))
            return _handle_approve_change_request(doc_id, body, event)

        elif method == "POST" and action == "reject_change_request":
            body = json.loads(event.get("body", "{}"))
            return _handle_reject_change_request(doc_id, body, event)

        elif method == "POST" and action == "run_submission_lint":
            return _handle_run_submission_lint(doc_id, event)

        elif method == "POST" and action == "query_approved_samples":
            body = json.loads(event.get("body", "{}"))
            return _handle_query_approved_samples(doc_id, body, event)

        elif method == "GET" and action == "section_recommendations":
            return _handle_get_section_recommendations(doc_id, event)

        elif method == "POST" and action == "calculate_resource_plan":
            body = json.loads(event.get("body", "{}"))
            return _handle_calculate_resource_plan(doc_id, body, event)

        elif method == "POST" and action == "review":
            user_id, err = _require_user(event)
            if err:
                return err
            return _response(200, {"status": "review_requested", "doc_id": doc_id})

        elif method == "POST" and action == "generate_architecture_diagram":
            body = json.loads(event.get("body", "{}"))
            return _handle_generate_architecture_diagram(doc_id, body, event)

        elif method == "POST" and action == "create_calculator_link":
            body = json.loads(event.get("body", "{}"))
            return _handle_create_calculator_link(doc_id, body, event)

        elif method == "POST" and action == "explain_aws_services":
            body = json.loads(event.get("body", "{}"))
            return _handle_explain_aws_services(doc_id, body, event)

        elif method == "POST" and action == "export":
            return _handle_export(doc_id, event)

        else:
            return _response(400, {"error": f"unknown: {method} {path}"})

    except Exception as e:
        return _response(500, {"error": str(e)})
