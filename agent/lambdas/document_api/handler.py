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
        return None, _response(401, {"error": "user_id required (X-User-Id header)"})
    return user_id, None


def _check_ownership(item: dict, user_id: str) -> Optional[dict]:
    """소유권 검증. 위반 시 403 응답, OK면 None."""
    owner = item.get("user_id")
    if owner and owner != user_id:
        return _response(403, {"error": "forbidden"})
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
        return "", _response(403, {"error": "forbidden"})
    if PERMISSION_ORDER[role] < PERMISSION_ORDER[required]:
        return role, _response(403, {
            "error": "insufficient_permission",
            "required": required,
            "permission": role,
        })
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
        return user_id, "", None, _response(404, {"error": "not found"})
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


def _document_lint_result(item: dict) -> dict:
    sections = item.get("sections", {}) if isinstance(item.get("sections"), dict) else {}
    meta = item.get("meta", {}) if isinstance(item.get("meta"), dict) else {}
    cost = sections.get("cost_breakdown", {}) if isinstance(sections.get("cost_breakdown"), dict) else {}
    architecture = sections.get("architecture", {}) if isinstance(sections.get("architecture"), dict) else {}
    resources = sections.get("resources_cost_estimates", {}) if isinstance(sections.get("resources_cost_estimates"), dict) else {}
    executive = sections.get("executive_summary", {}) if isinstance(sections.get("executive_summary"), dict) else {}

    issues = {"critical": [], "high": [], "medium": [], "low": []}
    missing_questions: list[str] = []
    suggested_patches: list[dict] = []

    required_sections = [
        "cover", "executive_summary", "stakeholders", "success_criteria",
        "assumptions", "scope_of_work", "architecture", "milestones",
        "cost_breakdown", "acceptance", "resources_cost_estimates",
    ]
    for section in required_sections:
        value = sections.get(section)
        if value in (None, {}, []):
            issue = _make_issue(
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
        "bedrock" in str(_resolve_field_value((svc or {}).get("service_name", ""))).lower()
        or "bedrock" in str((svc or {}).get("service_id", "")).lower()
        for svc in services
        if isinstance(svc, dict)
    )
    if not has_bedrock:
        issues["critical"].append(_make_issue(
            "critical",
            "BEDROCK_EVIDENCE_MISSING",
            "Amazon Bedrock inclusion needs more evidence before submission.",
            "architecture",
            "Which Amazon Bedrock models, guardrails, or usage assumptions are in scope?",
        ))
        missing_questions.append("Which Amazon Bedrock models, guardrails, or usage assumptions are in scope?")

    calculator_url = cost.get("calculator_url", {})
    mrr = _to_float(cost.get("mrr", 0))
    arr = _to_float(cost.get("arr", 0))
    funding = cost.get("funding_calculation", {}) if isinstance(cost.get("funding_calculation"), dict) else {}
    sow_cost = _to_float(funding.get("sow_cost"))
    if sow_cost <= 0:
        total_cost = resources.get("total_cost", {}) if isinstance(resources.get("total_cost"), dict) else {}
        sow_cost = _to_float(total_cost.get("total"))
    if not _has_resolved_value(calculator_url):
        issues["high"].append(_make_issue(
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
            "value": _confirmed_field_value(round(mrr * 12, 2)),
            "reason": "ARR can be calculated from MRR when MRR is provided.",
        })
    if arr <= 0:
        issues["high"].append(_make_issue(
            "high",
            "ARR_MISSING",
            "ARR / funding basis is a submission readiness issue.",
            "cost_breakdown",
            "What is the Year 1 ARR basis for this PoC?",
        ))
    if sow_cost <= 0:
        issues["high"].append(_make_issue(
            "high",
            "SOW_COST_MISSING",
            "SOW cost basis is recommended before submission.",
            "resources_cost_estimates",
            "What SOW cost should be used for funding eligibility?",
        ))

    overview = architecture.get("overview", {})
    if services and not _has_resolved_value(overview):
        issues["medium"].append(_make_issue(
            "medium",
            "ARCHITECTURE_OVERVIEW_MISSING",
            "Architecture and service sizing needs more evidence before submission.",
            "architecture",
            "How do the listed AWS services support the target workload and sizing?",
        ))

    # Architecture ↔ Cost alignment — services must be reflected in cost basis.
    if services:
        breakdown_table = cost.get("breakdown_table") if isinstance(cost, dict) else None
        if not isinstance(breakdown_table, list):
            breakdown_table = []
        if not breakdown_table and not _has_resolved_value(calculator_url):
            issues["medium"].append(_make_issue(
                "medium",
                "ARCHITECTURE_COST_ALIGNMENT_MISSING",
                "Architecture lists AWS services but cost basis has neither a Calculator URL nor a breakdown table.",
                "cost_breakdown",
                "Which AWS services map to which cost breakdown rows (or Calculator URL)?",
            ))
        # Bedrock specific — if the architecture lists Bedrock but the cost
        # basis has no Bedrock-related row nor calculator URL, flag it.
        arch_service_names = []
        for svc in services:
            if isinstance(svc, dict):
                name = _resolve_field_value(svc.get("service_name")) or svc.get("service_id", "")
            else:
                name = svc
            if name:
                arch_service_names.append(str(name))
        arch_has_bedrock = any("bedrock" in s.lower() for s in arch_service_names)
        cost_has_bedrock_row = False
        for row in breakdown_table:
            if not isinstance(row, dict):
                continue
            label = ""
            for key in ("service_name", "service", "category", "name"):
                val = _resolve_field_value(row.get(key))
                if val:
                    label = str(val)
                    break
            if "bedrock" in label.lower():
                cost_has_bedrock_row = True
                break
        if arch_has_bedrock and not cost_has_bedrock_row and not _has_resolved_value(calculator_url):
            issues["medium"].append(_make_issue(
                "medium",
                "BEDROCK_COST_NOT_REFLECTED",
                "Architecture lists Amazon Bedrock but cost basis has no Bedrock row or Calculator URL.",
                "cost_breakdown",
                "Add a Bedrock cost row or a Calculator URL that covers Bedrock usage.",
            ))

    business_groups = executive.get("groups", []) if isinstance(executive.get("groups"), list) else []
    if not business_groups:
        issues["medium"].append(_make_issue(
            "medium",
            "BUSINESS_CASE_MISSING",
            "Business Case & Commitment is recommended before submission.",
            "executive_summary",
            "What business problem, ROI basis, sponsor, and production commitment should be documented?",
        ))

    assumptions = sections.get("assumptions", {}) if isinstance(sections.get("assumptions"), dict) else {}
    if assumptions in ({}, {"groups": [], "items": []}):
        issues["medium"].append(_make_issue(
            "medium",
            "RISK_GOVERNANCE_MISSING",
            "Risk assessment and governance assumptions are recommended before submission.",
            "assumptions",
            "What risks, governance controls, and customer assumptions should be included?",
        ))

    customer = meta.get("customer", {})
    if not _has_resolved_value(customer):
        issues["low"].append(_make_issue(
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
        """Update thinking message in DynamoDB + send refresh signal."""
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
        return None, f"invoke_error: {type(exc).__name__}: {exc}"

    body = _read_lambda_payload(resp.get("Payload"))
    if resp.get("FunctionError"):
        return None, f"lambda_error: {body}"

    output_raw = body.get("outputPayload", body) if isinstance(body, dict) else {}
    if isinstance(output_raw, str):
        try:
            parsed = json.loads(output_raw)
        except Exception as exc:
            return None, f"parse_error: {exc}"
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
        # Build an in-process engineer-friendly draft so the caller always has
        # something renderable even if the downstream Lambda is unavailable.
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
        return _response(200, {
            "document_id": doc_id,
            "permission": permission,
            "mode": "engineer_draft",
            "drawio_s3_key": "",
            "preview_s3_key": "",
            "services_extracted": names,
            "engineer_draft": fallback_draft,
            "warnings": [error or "unknown error"],
        })

    result["document_id"] = doc_id
    result["permission"] = permission
    return _response(200, result)


def _handle_create_calculator_link(doc_id: str, body: dict, event: dict) -> dict:
    _user_id, permission, item, err = _load_document_for_action(doc_id, event, "read")
    if err:
        return err

    services = body.get("services")
    if not isinstance(services, list) or not services:
        services = _services_from_document(item)

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
        # In-process fallback that preserves document_local_summary even
        # when the downstream Lambda is unreachable.
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
        return _response(200, {
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
            "warnings": [error or "unknown error"],
        })

    result["document_id"] = doc_id
    result["permission"] = permission
    return _response(200, result)


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
        # In-process minimal fallback: return empty explanations but do not
        # fail the request — the frontend can keep existing text.
        return _response(200, {
            "document_id": doc_id,
            "permission": permission,
            "mode": "static",
            "explanations": [],
            "warnings": [
                "explain_aws_services Lambda unavailable",
                error or "unknown error",
            ],
        })

    result["document_id"] = doc_id
    result["permission"] = permission
    return _response(200, result)


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
    print(f"[export] start doc_id={doc_id} version={version}")

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
        print(f"[export] error stage=invoke error={exc}")
        return _response(500, {"error": str(exc), "stage": "invoke"})

    try:
        lambda_body = _read_lambda_payload(invoke_resp.get("Payload"))
        if invoke_resp.get("FunctionError"):
            print(f"[export] error stage=lambda error={lambda_body}")
            return _response(500, {
                "error": "export lambda failed",
                "stage": "lambda",
                "details": lambda_body,
            })

        output_payload = lambda_body.get("outputPayload", "{}")
        if isinstance(output_payload, str):
            output = json.loads(output_payload)
        elif isinstance(output_payload, dict):
            output = output_payload
        else:
            output = {}
    except Exception as exc:
        print(f"[export] error stage=parse_response error={exc}")
        return _response(500, {"error": str(exc), "stage": "parse_response"})

    if output.get("error"):
        print(f"[export] error stage={output.get('stage', 'export_docx')} error={output.get('error')}")
        return _response(500, output)

    if not output.get("download_url"):
        print(f"[export] error stage=missing_download_url error={output}")
        return _response(500, {
            "error": "export did not return download_url",
            "stage": "missing_download_url",
            "details": output,
        })

    print(f"[export] success s3_key={output.get('s3_key')}")
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
    except Exception as exc:
        print(f"[approved_samples] attach to lint failed: {exc}")
    result["document_id"] = doc_id
    result["permission"] = permission
    return _response(200, result)


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
    return _response(200, result)


def _handle_get_section_recommendations(doc_id: str, event: dict) -> dict:
    _user_id, permission, _item, err = _load_document_for_action(doc_id, event, "read")
    if err:
        return err
    query = event.get("queryStringParameters") or {}
    section = ""
    if isinstance(query, dict):
        section = str(query.get("section", "") or "")
    recommendations = _get_section_recommendations(section)
    return _response(200, {
        "document_id": doc_id,
        "permission": permission,
        "section": section,
        "recommendations": recommendations,
        "source": "static_presets",
    })


def _handle_calculate_resource_plan(doc_id: str, body: dict, event: dict) -> dict:
    _user_id, permission, _item, err = _load_document_for_action(doc_id, event, "read")
    if err:
        return err
    result = _resource_plan(body)
    result["document_id"] = doc_id
    result["permission"] = permission
    return _response(200, result)


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
