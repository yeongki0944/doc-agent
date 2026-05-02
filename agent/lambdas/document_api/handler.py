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
    field["status"] = "user_modified"
    return field


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


def _set_user_input_field(doc: dict, path: str, value: Any) -> tuple[str, dict]:
    parts = _path_parts(path)
    if parts[0] not in {"meta", "sections", "staffing_plan"}:
        raise ValueError("path must target meta, sections, or staffing_plan")
    if any(part in {"version", "document_id", "user_id"} for part in parts):
        raise ValueError("path targets a protected field")

    target_parts = parts[:-1] if parts[-1] == "user_input" else parts
    if not target_parts:
        raise ValueError("path must target a field")

    parent = doc
    for part in target_parts[:-1]:
        child = parent.get(part)
        if child is None:
            child = {}
            parent[part] = child
        if not isinstance(child, dict):
            raise ValueError(f"path segment is not editable: {part}")
        parent = child

    field_key = target_parts[-1]
    existing = parent.get(field_key)
    updated = _field_value_with_user_input(existing, value)
    parent[field_key] = updated
    return "/" + "/".join([*target_parts, "user_input"]), updated


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
        "meta": {},
        "sections": {},
        "staffing_plan": {
            "roles": {},
            "grand_total_hours": {"calculated": None},
            "grand_total_cost": {"calculated": None},
        },
        "completion_score": 0,
        "blocking_issues": [],
        "warnings": [],
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
    title = body.get("title") or "새 문서"

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
        "meta": {},
        "sections": {},
        "staffing_plan": {
            "roles": {},
            "grand_total_hours": {"calculated": None},
            "grand_total_cost": {"calculated": None},
        },
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

    # Set agent_status in DynamoDB
    _update_agent_status(doc_id, "processing", "task_planner", "🔍 메시지 분석 중...")

    # Publish "processing" status via AppSync
    _publish_event(f"/docs/{doc_id}/chat", {
        "type": "status",
        "status": "processing",
        "message": "🔍 메시지 분석 중...",
    })

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
    """Background chat processing — invoked asynchronously by _handle_chat."""
    doc_id = payload["doc_id"]
    message = payload["message"]
    history = payload.get("history", [])
    user_id = payload["user_id"]
    chat_channel = f"/docs/{doc_id}/chat"
    thinking_steps = []  # Collect all progress steps for history persistence

    try:
        # Step 1: Analyze message intent
        step1 = f"🔍 \"{message[:50]}{'...' if len(message) > 50 else ''}\" 분석 중..."
        thinking_steps.append(step1)
        _update_agent_status(doc_id, "processing", "task_planner", "🔍 메시지 의도 분석 중...")
        _publish_event(chat_channel, {
            "type": "progress", "agent": "task_planner", "step": "start", "message": step1,
        })

        # Step 2: Determine intent via LLM router (quick call)
        # Note: task_planner is not available in Lambda env (agent package is in Runtime only)
        # Use message keywords to show approximate plan
        msg_lower = message.lower()
        plan_parts = []
        if any(kw in msg_lower for kw in ["고객사", "파트너", "프로젝트", "목표", "범위", "예산", "일정"]):
            plan_parts.append("📋 정보 수집")
        if any(kw in msg_lower for kw in ["overview", "summary", "요약", "개요"]):
            plan_parts.append("✏️ Executive Summary 작성")
        if any(kw in msg_lower for kw in ["scope", "범위", "작업"]):
            plan_parts.append("✏️ Scope 작성")
        if any(kw in msg_lower for kw in ["success", "kpi", "성공", "기준"]):
            plan_parts.append("✏️ Success Criteria 작성")
        if any(kw in msg_lower for kw in ["assumptions", "가정", "리스크"]):
            plan_parts.append("✏️ Assumptions 작성")
        if any(kw in msg_lower for kw in ["team", "팀", "staffing", "인원"]):
            plan_parts.append("👥 팀 구성")
        if any(kw in msg_lower for kw in ["cost", "비용", "예산"]):
            plan_parts.append("💰 비용 산정")
        if any(kw in msg_lower for kw in ["architecture", "아키텍처"]):
            plan_parts.append("🏗️ 아키텍처")
        if any(kw in msg_lower for kw in ["milestone", "마일스톤", "일정"]):
            plan_parts.append("📅 마일스톤")
        if any(kw in msg_lower for kw in ["acceptance", "인수", "수락"]):
            plan_parts.append("✏️ Acceptance 작성")
        if not plan_parts:
            plan_parts.append("🔍 분석")
        plan_desc = ", ".join(plan_parts)
        step2 = f"📋 작업 계획: {plan_desc}"
        thinking_steps.append(step2)
        _publish_event(chat_channel, {
            "type": "progress", "agent": "task_planner", "step": "planned", "message": step2,
        })

        # Step 3: Execute via Runtime
        step3 = "🧠 에이전트가 작업을 수행하고 있습니다..."
        thinking_steps.append(step3)
        _update_agent_status(doc_id, "processing", "runtime", "🧠 에이전트 실행 중...")
        _publish_event(chat_channel, {
            "type": "progress", "agent": "runtime", "step": "executing", "message": step3,
        })
        runtime_result = _invoke_runtime({
            "doc_id": doc_id,
            "prompt": message,
            "history": history,
            "user_id": user_id,
        })
        print(f"[async_chat] runtime result: status={runtime_result.get('status')} result_len={len(runtime_result.get('result', ''))}")

        # Step 4: Runtime complete — extract execution log
        agent_response = runtime_result.get("result", "")
        execution_log = runtime_result.get("execution_log", [])

        # Convert execution_log to detailed thinking steps
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
        for entry in execution_log:
            agent_name = entry.get("agent", "")
            label = agent_labels.get(agent_name, agent_name)
            action = entry.get("action", "")
            success = entry.get("success", True)
            patches = entry.get("patches_count", 0)
            if success:
                thinking_steps.append(f"  ├─ {label}: {action} 완료 ✅ ({patches}건 변경)")
            else:
                thinking_steps.append(f"  └─ {label}: {action} 실패 ⚠️")

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
            updated_doc = json.loads(_json(updated_doc))

        # Step 6: Save agent response to conversation history (source of truth)
        thinking_steps.append("✅ 완료")
        now = _now_iso()

        # Thinking block message (persisted for history restoration)
        thinking_msg = {
            "id": f"thinking-{uuid.uuid4().hex[:8]}",
            "role": "agent",
            "content": "✅ 완료",
            "timestamp": now,
            "type": "thinking",
            "thinking_steps": thinking_steps,
        }

        agent_msg = {
            "id": f"agent-{uuid.uuid4().hex[:8]}",
            "role": "agent",
            "content": agent_response or "처리 완료",
            "timestamp": now,
        }
        # Append to existing history
        try:
            hist_resp = history_table.get_item(Key={"document_id": doc_id, "session_id": "default"})
            hist_item = hist_resp.get("Item", {})
            existing_msgs = hist_item.get("messages", [])
            # Also save the user message if not already there
            user_msg_exists = any(m.get("content") == message for m in existing_msgs[-3:])
            if not user_msg_exists:
                existing_msgs.append({
                    "id": f"user-{uuid.uuid4().hex[:8]}",
                    "role": "user",
                    "content": message,
                    "timestamp": now,
                })
            existing_msgs.append(thinking_msg)
            existing_msgs.append(agent_msg)
            history_item = {
                "document_id": doc_id,
                "session_id": "default",
                "user_id": user_id,
                "messages": existing_msgs,
                "bounded_window": DEFAULT_BOUNDED_WINDOW,
                "total_count": len(existing_msgs),
                "updated_at": now,
            }
            history_table.put_item(Item=json.loads(_json(history_item), parse_float=Decimal))
        except Exception as hist_err:
            print(f"[async_chat] history save failed: {hist_err}")

        # Step 5: Publish final result via AppSync
        _publish_event(chat_channel, {
            "type": "chat_done",
            "text": agent_response or "처리 완료",
            "document": updated_doc,
            "status": "idle",
        })

        print(f"[async_chat] published chat_done for {doc_id}")

        # Step 6: Set agent_status to idle
        _update_agent_status(doc_id, "idle", "", "")

    except Exception as e:
        print(f"[async_chat] error: {e}")
        _update_agent_status(doc_id, "error", "", str(e)[:200])
        _publish_event(chat_channel, {
            "type": "chat_done",
            "text": f"처리 중 오류가 발생했습니다: {str(e)[:200]}",
            "document": None,
            "status": "error",
        })

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

    try:
        patch_path, updated_field = _set_user_input_field(doc_dict, path, value)
    except ValueError as exc:
        return _response(400, {"error": str(exc)})

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

        elif method == "POST" and action == "review":
            user_id, err = _require_user(event)
            if err:
                return err
            return _response(200, {"status": "review_requested", "doc_id": doc_id})

        elif method == "POST" and action == "export":
            return _handle_export(doc_id, event)

        else:
            return _response(400, {"error": f"unknown: {method} {path}"})

    except Exception as e:
        return _response(500, {"error": str(e)})
