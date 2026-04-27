"""Document API Lambda — Bedrock-powered chat + CRUD.

Models:
  Parent Orchestrator: global.anthropic.claude-opus-4-6-v1
  Child agents:        apac.anthropic.claude-3-5-sonnet-20241022-v2:0
"""

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
from pydantic import ValidationError

from agent.lib.calculation.recalculate import recalculate_costs
from agent.lib.schema.document_state import DocumentState
from agent.lib.schema.patch import Patch, PatchOperation
from agent.lib.storage.dynamodb import VersionConflictError

TABLE_NAME = os.environ.get("DOCUMENTS_TABLE", "doc-agent-documents")
HISTORY_TABLE_NAME = os.environ.get("CONVERSATION_HISTORY_TABLE", "doc-agent-conversation-history")
APPSYNC_HTTP_URL = os.environ.get("APPSYNC_HTTP_URL", "")
REGION = "ap-northeast-2"
PARENT_MODEL = "global.anthropic.claude-opus-4-6-v1"
CHILD_MODEL = "apac.anthropic.claude-3-5-sonnet-20241022-v2:0"
DEFAULT_EXPORT_DOCX_FUNCTION_NAME = "doc-agent-export-docx"

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)
history_table = dynamodb.Table(HISTORY_TABLE_NAME)
bedrock = boto3.client("bedrock-runtime", region_name=REGION)

# --- AgentCore Memory ---
AGENTCORE_MEMORY_ID = os.environ.get("AGENTCORE_MEMORY_ID", "")
_agentcore_client = None

def _get_agentcore_client():
    global _agentcore_client
    if _agentcore_client is None and AGENTCORE_MEMORY_ID:
        _agentcore_client = boto3.client("bedrock-agentcore", region_name=REGION)
    return _agentcore_client

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

# --- Inline preset data ---
STAFFING_PRESET = {
    "project_manager": {"display_name": "Project Manager", "count": 1, "alloc": 50, "rate": 81.78},
    "solutions_architect": {"display_name": "Solutions Architect", "count": 1, "alloc": 60, "rate": 105.00},
    "ml_engineer": {"display_name": "ML Engineer", "count": 2, "alloc": 100, "rate": 95.00},
    "backend_developer": {"display_name": "Backend Developer", "count": 2, "alloc": 100, "rate": 75.00},
    "frontend_developer": {"display_name": "Frontend Developer", "count": 1, "alloc": 80, "rate": 70.00},
    "qa_engineer": {"display_name": "QA Engineer", "count": 1, "alloc": 60, "rate": 60.00},
}
PHASE_HOURS = {"discovery": 40, "development": 120, "testing": 40}


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


def _calculated_patch(doc: dict, path: str, value: Any) -> PatchOperation | None:
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
    return PatchOperation(op="replace", path="/" + "/".join(parts), value=parent[key])


def _staffing_recalculation_patches(doc: dict) -> list[PatchOperation]:
    if not isinstance(doc.get("staffing_plan"), dict):
        return []

    result = recalculate_costs(doc["staffing_plan"])
    operations: list[PatchOperation] = []
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
            result[field_name],
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


# --- Bedrock ---

def _invoke_bedrock(model_id: str, system: str, user_msg: str, max_tokens: int = 2000, history: list = None) -> str:
    messages = []
    if history:
        for h in history[-20:]:
            role = h.get("role", "user")
            content = h.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_msg})
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
    }
    resp = bedrock.invoke_model(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(body),
    )
    result = json.loads(resp["body"].read())
    return result["content"][0]["text"]


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


TRANSLATE_SYSTEM = """You are a professional translator for AWS APN PoC Project Plan documents.
Translate the given Korean JSON values into natural, professional English suitable for AWS partner documentation.

Rules:
- Translate ONLY the values, keep all JSON keys exactly as-is
- Use formal business English appropriate for AWS documentation
- Keep technical terms (AWS service names, acronyms) unchanged
- Maintain the same JSON structure
- Output valid JSON only, no explanation"""


def _translate_section(section_data: dict) -> dict:
    """Translate a section's Korean content to English using Bedrock."""
    try:
        prompt = f"Translate the values in this JSON to English:\n{json.dumps(section_data, ensure_ascii=False)}"
        raw = _invoke_bedrock(CHILD_MODEL, TRANSLATE_SYSTEM, prompt, max_tokens=2000)
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(raw[start:end])
    except Exception as e:
        print(f"[translate error] {e}")
    return {}


def _invoke_bedrock_stream(model_id: str, system: str, user_msg: str, channel: str, max_tokens: int = 2000, history: list = None) -> str:
    """Invoke Bedrock with streaming, publishing chunks to AppSync channel. Returns full text."""
    messages = []
    if history:
        for h in history[-20:]:
            role = h.get("role", "user")
            content = h.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_msg})
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
    }

    # Publish "thinking" status
    _publish_event(channel, {"type": "status", "status": "thinking", "message": "🧠 AI가 분석하고 있습니다..."})

    resp = bedrock.invoke_model_with_response_stream(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(body),
    )

    full_text = ""
    buffer = ""
    chunk_count = 0

    for event in resp["body"]:
        chunk = event.get("chunk")
        if not chunk:
            continue
        payload = json.loads(chunk["bytes"])
        if payload.get("type") == "content_block_delta":
            delta = payload.get("delta", {})
            text = delta.get("text", "")
            if text:
                full_text += text
                buffer += text
                chunk_count += 1
                # Publish every ~50 chars or every 3 chunks for smooth streaming
                if len(buffer) >= 50 or chunk_count % 3 == 0:
                    _publish_event(channel, {"type": "chat_chunk", "text": buffer})
                    buffer = ""

    # Flush remaining buffer
    if buffer:
        _publish_event(channel, {"type": "chat_chunk", "text": buffer})

    return full_text


def _build_staffing() -> dict:
    roles = {}
    gh, gc = 0, 0
    fv = lambda v: {"user_input": None, "ai_recommended": v, "calculated": None, "status": "recommended"}
    for rid, p in STAFFING_PRESET.items():
        th = sum(PHASE_HOURS.values())
        cost = round(p["count"] * (p["alloc"] / 100) * p["rate"] * th, 2)
        gh += th
        gc += cost
        roles[rid] = {
            "role_id": rid, "display_name": p["display_name"],
            "count": fv(p["count"]), "allocation_pct": fv(p["alloc"]),
            "rate_per_hour": fv(p["rate"]),
            "phase_hours": {ph: fv(h) for ph, h in PHASE_HOURS.items()},
            "total_hours": {"calculated": th}, "total_cost": {"calculated": cost},
            "reason": "GenAI 멀티에이전트 PoC preset 기반 추천",
            "source_patterns": ["preset_genai_multi_agent"],
        }
    return {"roles": roles, "grand_total_hours": {"calculated": gh}, "grand_total_cost": {"calculated": round(gc, 2)}}


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


def _runtime_response(runtime_result: dict) -> dict:
    body = {
        "agent_response": runtime_result.get("result", ""),
        "version": runtime_result.get("version", 0),
        "status": runtime_result.get("status", "error"),
    }
    if "actions" in runtime_result:
        body["actions"] = runtime_result["actions"]
    status_code = 200 if body["status"] == "ok" else 500
    return _response(status_code, body)


def _invoke_runtime(payload: dict) -> dict:
    from agent.lambdas.document_api.runtime_proxy import get_runtime_proxy

    return get_runtime_proxy().invoke(payload)


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
    return _runtime_response(runtime_result)


PARENT_SYSTEM = """당신은 APN PoC Project Plan 문서 생성을 돕는 Parent Orchestrator입니다.
사용자 메시지를 분석하여 다음 JSON 형식으로 응답하세요:

{
  "intent": "discovery|staffing|architecture|cost|review|export|general|update_section",
  "extracted_info": {
    "customer": "고객사명 또는 null",
    "partner": "파트너명 또는 null",
    "project_goal": "프로젝트 목표 또는 null",
    "scope": "범위 요약 또는 null"
  },
  "section_updates": {
    "cover": {"title": "...", "customer": "...", "partner": "...", "goal": "...", "period": "...", "budget": "...", "version": "...", "date": "...", "aws_services": "..."},
    "executive_summary": {"summary": "..."},
    "scope_of_work": {"in_scope": "...", "out_of_scope": "...", "deliverables": "..."},
    "success_criteria": {"kpi_1": "...", "kpi_2": "...", "acceptance_threshold": "..."},
    "assumptions": {"assumptions": "...", "risks": "...", "dependencies": "..."},
    "architecture": {"services": "...", "description": "...", "data_flow": "..."},
    "milestones": {"phase_1": "...", "phase_2": "...", "phase_3": "..."},
    "acceptance": {"criteria_1": "...", "criteria_2": "...", "sign_off_process": "..."}
  },
  "chat_response": "사용자에게 보여줄 한국어 응답 메시지",
  "next_question": "다음에 물어볼 질문 또는 null",
  "should_recommend_staffing": true/false
}

규칙:
- 고객사명, 프로젝트 목표, 범위 등 정보를 추출하세요
- 사용자가 특정 섹션 작성/업데이트를 요청하면 section_updates에 해당 섹션 데이터를 포함하세요
- 사용자가 "작성해줘", "알아서 작성해줘" 등 요청하면 현재까지 수집된 정보를 바탕으로 해당 섹션을 직접 작성하세요. 정보가 부족해도 합리적인 초안을 작성하세요.
- section_updates에는 변경이 있는 섹션만 포함하세요. 변경이 없으면 section_updates를 빈 객체 {}로 두세요
- 정보가 부족하더라도 "더 자세히 알려주세요"라고만 하지 말고, 가능한 범위에서 초안을 작성한 뒤 보완할 부분을 안내하세요
- 프로젝트 정보가 충분하면 should_recommend_staffing을 true로 설정하세요
- chat_response는 친절하고 전문적인 한국어로 작성하세요
- section_updates의 모든 값도 반드시 한국어로 작성하세요. 영어로 작성하지 마세요. (영어 번역은 별도 프로세스에서 처리됩니다)
- 반드시 유효한 JSON만 출력하세요"""


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

def _handle_chat(doc_id: str, body: dict, event: dict) -> dict:
    message = body.get("message", "")
    if not message:
        return _response(400, {"error": "message is required"})

    return _handle_runtime_invocation(
        doc_id,
        message,
        body.get("history", []),
        event,
        create_shell_if_missing=True,
    )


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
        PatchOperation(op="replace", path=patch_path, value=value, source="user_input"),
        PatchOperation(
            op="replace",
            path=f"{field_path}/user_edited",
            value=True,
            source="user_input",
        ),
        PatchOperation(
            op="replace",
            path=f"{field_path}/status",
            value=updated_field["status"],
            source="user_input",
        ),
    ]
    if patch_path.startswith("/staffing_plan/"):
        operations.extend(_staffing_recalculation_patches(doc_dict))

    try:
        DocumentState.model_validate(doc_dict)
        saved = _conditional_save_document(doc_dict, expected_version)
    except VersionConflictError as exc:
        return _response(409, {"error": str(exc), "status": "version_conflict"})
    except ValidationError as exc:
        return _response(400, {"error": "invalid document update", "details": exc.errors()})

    patch = Patch(
        patch_id=f"patch-{uuid.uuid4().hex[:12]}",
        doc_id=doc_id,
        agent="document_api",
        operations=operations,
        version=saved["version"],
        version_before=expected_version,
        version_after=saved["version"],
    )
    _publish_event(f"docs/{doc_id}/patch", {"type": "patch", **patch.model_dump(mode="json")})

    return _response(200, {"status": "ok", "version": saved["version"]})


def handler(event: dict, context: Any) -> dict:
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
