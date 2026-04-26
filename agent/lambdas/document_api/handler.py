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
from typing import Any, Optional

import boto3

TABLE_NAME = os.environ.get("DOCUMENTS_TABLE", "doc-agent-documents")
HISTORY_TABLE_NAME = os.environ.get("CONVERSATION_HISTORY_TABLE", "doc-agent-conversation-history")
APPSYNC_HTTP_URL = os.environ.get("APPSYNC_HTTP_URL", "")
REGION = "ap-northeast-2"
PARENT_MODEL = "global.anthropic.claude-opus-4-6-v1"
CHILD_MODEL = "apac.anthropic.claude-3-5-sonnet-20241022-v2:0"

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
    user_id, err = _require_user(event)
    if err:
        return err

    message = body.get("message", "")
    if not message:
        return _response(400, {"error": "message is required"})

    resp = table.get_item(Key={"document_id": doc_id})
    item = resp.get("Item")

    if item:
        forbidden = _check_ownership(item, user_id)
        if forbidden:
            return forbidden
    else:
        # Auto-create on first chat
        item = {
            "document_id": doc_id,
            "user_id": user_id,
            "title": "새 문서",
            "version": 0,
            "created_at": _now_iso(),
            "mode": "architecture_absent",
            "template": "apn_poc_project_plan",
            "meta": {},
            "sections": {},
            "staffing_plan": {"roles": {}, "grand_total_hours": {"calculated": None}, "grand_total_cost": {"calculated": None}},
            "completion_score": 0,
            "blocking_issues": [],
            "warnings": [],
        }

    actions = []

    doc_context = ""
    meta = item.get("meta", {})
    if meta:
        parts = []
        if meta.get("customer", {}).get("user_input"):
            parts.append(f"고객사: {meta['customer']['user_input']}")
        if meta.get("partner", {}).get("user_input"):
            parts.append(f"파트너: {meta['partner']['user_input']}")
        if meta.get("project_goal", {}).get("user_input"):
            parts.append(f"프로젝트 목표: {meta['project_goal']['user_input']}")
        if meta.get("scope", {}).get("user_input"):
            parts.append(f"범위: {meta['scope']['user_input']}")
        if parts:
            doc_context = "\n\n[현재까지 수집된 정보]\n" + "\n".join(parts)

    history = body.get("history", [])

    # Retrieve long-term memory for customer context
    customer_name = meta.get("customer", {}).get("user_input", "")
    memory_context = ""
    if AGENTCORE_MEMORY_ID and customer_name:
        memories = _memory_retrieve(customer_name, message)
        if memories:
            memory_context = "\n\n[장기 메모리 — 이전 대화에서 학습한 정보]\n" + "\n".join(f"- {m}" for m in memories)

    enriched_msg = message
    if doc_context or memory_context:
        enriched_msg = doc_context + memory_context + "\n\n[사용자 메시지]\n" + message

    # Store user message in short-term memory
    if AGENTCORE_MEMORY_ID:
        _memory_store_event(session_id=doc_id, actor_id=user_id, content=message, role="USER")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    system_with_date = f"오늘 날짜: {today}\n\n{PARENT_SYSTEM}"

    try:
        raw = _invoke_bedrock(PARENT_MODEL, system_with_date, enriched_msg, max_tokens=4000, history=history)
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            plan = json.loads(raw[start:end])
        else:
            plan = {"chat_response": raw, "extracted_info": {}, "should_recommend_staffing": False}
    except Exception as e:
        print(f"[bedrock error] {type(e).__name__}: {e}")
        plan = {"chat_response": "프로젝트 정보를 분석 중입니다. 더 자세히 알려주세요.", "extracted_info": {}, "should_recommend_staffing": False}

    info = plan.get("extracted_info", {})
    meta = item.get("meta", {})
    fv = lambda v: {"user_input": v, "status": "confirmed"}
    if info.get("customer"):
        meta["customer"] = fv(info["customer"])
        actions.append(f"고객사: {info['customer']}")
    if info.get("partner"):
        meta["partner"] = fv(info["partner"])
        actions.append(f"파트너: {info['partner']}")
    if info.get("project_goal"):
        meta["project_goal"] = fv(info["project_goal"])
        actions.append("목표 저장")
    if info.get("scope"):
        meta["scope"] = fv(info["scope"])
        actions.append("범위 저장")
    item["meta"] = meta

    if plan.get("should_recommend_staffing", False):
        item["staffing_plan"] = _build_staffing()
        item["completion_score"] = 0.35
        actions.append("팀 구성 추천 (6개 역할)")

    section_updates = plan.get("section_updates", {})
    if section_updates:
        sections = item.get("sections", {})
        sections_en = item.get("sections_en", {})
        for sec_name, sec_data in section_updates.items():
            if sec_data and isinstance(sec_data, dict):
                existing = sections.get(sec_name, {})
                if isinstance(existing, dict):
                    existing.update(sec_data)
                else:
                    existing = sec_data
                sections[sec_name] = existing
                # Translate to English
                translated = _translate_section(existing)
                if translated:
                    sections_en[sec_name] = translated
                actions.append(f"{sec_name} 섹션 업데이트")
        item["sections"] = sections
        item["sections_en"] = sections_en

        cover_updates = section_updates.get("cover", {})
        if cover_updates and isinstance(cover_updates, dict):
            if cover_updates.get("customer"):
                meta["customer"] = fv(cover_updates["customer"])
            if cover_updates.get("partner"):
                meta["partner"] = fv(cover_updates["partner"])
            if cover_updates.get("date"):
                meta["date"] = fv(cover_updates["date"])
            item["meta"] = meta

    item["version"] = int(item.get("version", 0)) + 1
    item["user_id"] = user_id
    item["updated_at"] = _now_iso()

    # Auto-generate title from available info
    # Priority: [고객사] 프로젝트명 > [고객사] PoC Plan > 프로젝트명 > 새 문서
    meta = item.get("meta", {})
    cover = item.get("sections", {}).get("cover", {})
    customer = meta.get("customer", {}).get("user_input") or ""
    project_title = cover.get("title") or cover.get("goal") or ""
    if customer and project_title:
        item["title"] = f"[{customer}] {project_title}"
    elif customer:
        item["title"] = f"[{customer}] PoC Plan"
    elif project_title:
        item["title"] = project_title
    # else: keep existing title (default "새 문서")

    _save_to_ddb(item)

    chat_resp = plan.get("chat_response", "")
    next_q = plan.get("next_question")
    if next_q:
        chat_resp += f"\n\n{next_q}"
    if actions:
        chat_resp += f"\n\n✅ {', '.join(actions)}"

    # Store agent response in short-term memory + long-term facts
    if AGENTCORE_MEMORY_ID:
        _memory_store_event(session_id=doc_id, actor_id="agent", content=chat_resp, role="ASSISTANT")
        # Store extracted info as long-term facts
        customer_for_facts = info.get("customer") or meta.get("customer", {}).get("user_input", "")
        if customer_for_facts:
            facts = []
            if info.get("project_goal"):
                facts.append(f"프로젝트 목표: {info['project_goal']}")
            if info.get("scope"):
                facts.append(f"프로젝트 범위: {info['scope']}")
            if info.get("partner"):
                facts.append(f"파트너: {info['partner']}")
            cover_data = item.get("sections", {}).get("cover", {})
            if cover_data.get("aws_services"):
                facts.append(f"AWS 서비스: {cover_data['aws_services']}")
            if facts:
                _memory_store_facts(customer_for_facts, facts)

    # Stream the chat response via AppSync Events
    chat_channel = f"docs/{doc_id}/chat"
    if APPSYNC_HTTP_URL and chat_resp:
        # Send in sentence-sized chunks for streaming effect
        sentences = chat_resp.replace("\n\n", "\n").split("\n")
        for sentence in sentences:
            if sentence.strip():
                _publish_event(chat_channel, {"type": "chat_chunk", "text": sentence + "\n"})
        _publish_event(chat_channel, {
            "type": "chat_done",
            "actions": actions,
            "document": json.loads(_json(item)),
        })

    return _response(200, {
        "agent_response": chat_resp,
        "actions": actions,
        "document": json.loads(_json(item)),
    })


def _handle_invocations(body: dict, event: dict) -> dict:
    user_id, err = _require_user(event)
    if err:
        return err

    doc_id = body.get("doc_id", "")
    prompt = body.get("prompt", "")
    history = body.get("history", [])

    if not doc_id or not prompt:
        return _response(400, {"error": "doc_id and prompt are required"})

    # Ownership check (only if doc exists)
    resp = table.get_item(Key={"document_id": doc_id})
    item = resp.get("Item")
    if item:
        forbidden = _check_ownership(item, user_id)
        if forbidden:
            return forbidden

    try:
        from agent.app.parent.runtime import invoke
        runtime_result = invoke({
            "doc_id": doc_id,
            "prompt": prompt,
            "history": history,
            "user_id": user_id,
        })
        status_code = 200 if runtime_result.get("status") == "ok" else 500
        return _response(status_code, {
            "agent_response": runtime_result.get("result", ""),
            "version": runtime_result.get("version", 0),
            "status": runtime_result.get("status", "error"),
        })
    except ImportError:
        return _handle_chat(doc_id, {"message": prompt, "history": history}, event)


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
            user_id, err = _require_user(event)
            if err:
                return err
            body = json.loads(event.get("body", "{}"))
            resp = table.get_item(Key={"document_id": doc_id})
            item = resp.get("Item", {"document_id": doc_id, "version": 0, "user_id": user_id})
            forbidden = _check_ownership(item, user_id)
            if forbidden:
                return forbidden
            _set_nested(item, body.get("path", ""), body.get("value"))
            item["version"] = int(item.get("version", 0)) + 1
            item["user_id"] = user_id
            item["updated_at"] = _now_iso()
            _save_to_ddb(item)
            return _response(200, {"status": "ok", "version": int(item["version"])})

        elif method == "POST" and action == "review":
            user_id, err = _require_user(event)
            if err:
                return err
            return _response(200, {"status": "review_requested", "doc_id": doc_id})

        elif method == "POST" and action == "export":
            user_id, err = _require_user(event)
            if err:
                return err
            return _response(200, {"status": "export_requested", "doc_id": doc_id})

        else:
            return _response(400, {"error": f"unknown: {method} {path}"})

    except Exception as e:
        return _response(500, {"error": str(e)})