"""Document API Lambda — Bedrock-powered chat + CRUD.

Models:
  Parent Orchestrator: global.anthropic.claude-opus-4-6-v1
  Child agents:        apac.anthropic.claude-3-5-sonnet-20241022-v2:0
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from typing import Any

import boto3

TABLE_NAME = os.environ.get("DOCUMENTS_TABLE", "doc-agent-documents")
HISTORY_TABLE_NAME = os.environ.get("CONVERSATION_HISTORY_TABLE", "doc-agent-conversation-history")
REGION = "ap-northeast-2"
PARENT_MODEL = "global.anthropic.claude-opus-4-6-v1"
CHILD_MODEL = "apac.anthropic.claude-3-5-sonnet-20241022-v2:0"

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)
history_table = dynamodb.Table(HISTORY_TABLE_NAME)
bedrock = boto3.client("bedrock-runtime", region_name=REGION)

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
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
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


def _invoke_bedrock(model_id: str, system: str, user_msg: str, max_tokens: int = 2000, history: list = None) -> str:
    """Call Bedrock and return assistant text. Supports multi-turn history."""
    messages = []
    # Add conversation history for context continuity
    if history:
        for h in history[-20:]:  # bounded window
            role = h.get("role", "user")
            content = h.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
    # Add current user message
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


def _build_staffing() -> dict:
    """Build staffing plan from preset."""
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
    """Save item to DynamoDB, converting floats to Decimal."""
    raw = _json(item)
    table.put_item(Item=json.loads(raw, parse_float=Decimal))


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
    "cover": {"title": "프로젝트명", "customer": "고객사명", "partner": "파트너명", "goal": "목표", "period": "기간", "budget": "예산", "version": "버전", "date": "작성일", "aws_services": "AWS 서비스"},
    "executive_summary": {"summary": "요약 내용"},
    "scope_of_work": {"scope": "범위 내용"},
    "success_criteria": {"criteria": "성공 기준 내용"},
    "assumptions": {"assumptions": "가정 및 리스크 내용"},
    "architecture": {"services": "서비스 목록", "description": "설명"},
    "milestones": {"phases": "마일스톤 내용"},
    "acceptance": {"criteria": "인수 기준 내용"}
  },
  "chat_response": "사용자에게 보여줄 한국어 응답 메시지",
  "next_question": "다음에 물어볼 질문 또는 null",
  "should_recommend_staffing": true/false
}

규칙:
- 고객사명, 프로젝트 목표, 범위 등 정보를 추출하세요
- 사용자가 특정 섹션(Cover, Overview 등) 작성/업데이트를 요청하면 section_updates에 해당 섹션 데이터를 포함하세요
- section_updates에는 변경이 있는 섹션만 포함하세요. 변경이 없으면 section_updates를 빈 객체 {}로 두세요
- 정보가 부족하면 next_question으로 재질문하세요
- 프로젝트 정보가 충분하면 should_recommend_staffing을 true로 설정하세요
- chat_response는 친절하고 전문적인 한국어로 작성하세요
- 반드시 유효한 JSON만 출력하세요"""


DEFAULT_BOUNDED_WINDOW = 20


def _handle_save_history(doc_id: str, body: dict) -> dict:
    """POST /documents/{docId}/history — save conversation history."""
    from datetime import datetime, timezone

    session_id = body.get("session_id", "default")
    messages = body.get("messages", [])
    bounded_window = body.get("bounded_window", DEFAULT_BOUNDED_WINDOW)

    item = {
        "document_id": doc_id,
        "session_id": session_id,
        "messages": messages,
        "bounded_window": bounded_window,
        "total_count": len(messages),
        "updated_at": datetime.now(timezone.utc).isoformat(),
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
    """GET /documents/{docId}/history — load conversation history."""
    # Optional session_id from query string
    qs = event.get("queryStringParameters") or {}
    session_id = qs.get("session_id")

    if session_id:
        resp = history_table.get_item(
            Key={"document_id": doc_id, "session_id": session_id}
        )
        item = resp.get("Item")
    else:
        # Get most recent session
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


def _handle_chat(doc_id: str, body: dict) -> dict:
    """POST /documents/{docId}/chat — Bedrock-powered chat.

    Uses direct Bedrock invoke for Lambda deployment.
    AgentCore Runtime integration is used when running via /invocations
    with the full agent package available.
    """
    message = body.get("message", "")
    if not message:
        return _response(400, {"error": "message is required"})

    # Get or create doc
    resp = table.get_item(Key={"document_id": doc_id})
    item = resp.get("Item", {
        "document_id": doc_id, "version": 0, "mode": "architecture_absent",
        "template": "apn_poc_project_plan", "meta": {}, "sections": {},
        "staffing_plan": {"roles": {}, "grand_total_hours": {"calculated": None}, "grand_total_cost": {"calculated": None}},
        "completion_score": 0, "blocking_issues": [], "warnings": [],
    })

    actions = []

    # Build context from existing document state
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

    # Get conversation history from request
    history = body.get("history", [])

    # Build enriched message with document context
    enriched_msg = message
    if doc_context:
        enriched_msg = doc_context + "\n\n[사용자 메시지]\n" + message

    # Call Parent Orchestrator (Opus 4.6) with history
    try:
        raw = _invoke_bedrock(PARENT_MODEL, PARENT_SYSTEM, enriched_msg, max_tokens=1000, history=history)
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            plan = json.loads(raw[start:end])
        else:
            plan = {"chat_response": raw, "extracted_info": {}, "should_recommend_staffing": False}
    except Exception:
        plan = {"chat_response": "프로젝트 정보를 분석 중입니다. 더 자세히 알려주세요.", "extracted_info": {}, "should_recommend_staffing": True}

    # Apply extracted info
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

    # Staffing recommendation
    if plan.get("should_recommend_staffing", False):
        item["staffing_plan"] = _build_staffing()
        item["completion_score"] = 0.35
        actions.append("팀 구성 추천 (6개 역할)")

    # Apply section updates from Bedrock response
    section_updates = plan.get("section_updates", {})
    if section_updates:
        sections = item.get("sections", {})
        for sec_name, sec_data in section_updates.items():
            if sec_data and isinstance(sec_data, dict):
                existing = sections.get(sec_name, {})
                if isinstance(existing, dict):
                    existing.update(sec_data)
                else:
                    existing = sec_data
                sections[sec_name] = existing
                actions.append(f"{sec_name} 섹션 업데이트")
        item["sections"] = sections

        # Sync cover fields to meta so CoverSection FieldRows reflect changes
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
    _save_to_ddb(item)

    # Build response
    chat_resp = plan.get("chat_response", "")
    next_q = plan.get("next_question")
    if next_q:
        chat_resp += f"\n\n{next_q}"
    if actions:
        chat_resp += f"\n\n✅ {', '.join(actions)}"

    return _response(200, {
        "agent_response": chat_resp,
        "actions": actions,
        "document": json.loads(_json(item)),
    })


def _handle_invocations(body: dict) -> dict:
    """POST /invocations — proxy to AgentCore Runtime or fallback to Bedrock.

    When running in Lambda (no agent package), falls back to direct
    Bedrock chat. When running with full agent package (AgentCore Runtime),
    uses the v2 orchestration pipeline.
    """
    doc_id = body.get("doc_id", "")
    prompt = body.get("prompt", "")
    history = body.get("history", [])

    if not doc_id or not prompt:
        return _response(400, {"error": "doc_id and prompt are required"})

    # Try AgentCore Runtime (v2), fallback to direct Bedrock (v1)
    try:
        from agent.app.parent.runtime import invoke
        runtime_result = invoke({
            "doc_id": doc_id,
            "prompt": prompt,
            "history": history,
        })
        status_code = 200 if runtime_result.get("status") == "ok" else 500
        return _response(status_code, {
            "agent_response": runtime_result.get("result", ""),
            "version": runtime_result.get("version", 0),
            "status": runtime_result.get("status", "error"),
        })
    except ImportError:
        # Lambda environment — fallback to v1 Bedrock chat
        return _handle_chat(doc_id, {"message": prompt, "history": history})


def handler(event: dict, context: Any) -> dict:
    rc = event.get("requestContext", {})
    http = rc.get("http", {})
    method = http.get("method", event.get("httpMethod", "GET"))
    path = http.get("path", event.get("rawPath", "/"))

    if method == "OPTIONS":
        return _response(204, "")

    parts = [p for p in path.strip("/").split("/") if p]

    # POST /invocations — AgentCore Runtime proxy
    if method == "POST" and len(parts) == 1 and parts[0] == "invocations":
        body = json.loads(event.get("body", "{}"))
        return _handle_invocations(body)

    if len(parts) < 2 or parts[0] != "documents":
        return _response(400, {"error": "invalid path"})

    doc_id = parts[1]
    action = parts[2] if len(parts) >= 3 else ""

    try:
        if method == "GET" and not action:
            resp = table.get_item(Key={"document_id": doc_id})
            item = resp.get("Item")
            if not item:
                return _response(404, {"error": "not found"})
            return _response(200, item)

        elif method == "POST" and action == "chat":
            body = json.loads(event.get("body", "{}"))
            return _handle_chat(doc_id, body)

        elif method == "POST" and action == "history":
            body = json.loads(event.get("body", "{}"))
            return _handle_save_history(doc_id, body)

        elif method == "GET" and action == "history":
            return _handle_load_history(doc_id, event)

        elif method == "POST" and action == "user-input":
            body = json.loads(event.get("body", "{}"))
            resp = table.get_item(Key={"document_id": doc_id})
            item = resp.get("Item", {"document_id": doc_id, "version": 0})
            _set_nested(item, body.get("path", ""), body.get("value"))
            item["version"] = int(item.get("version", 0)) + 1
            _save_to_ddb(item)
            return _response(200, {"status": "ok", "version": int(item["version"])})

        elif method == "POST" and action == "review":
            return _response(200, {"status": "review_requested", "doc_id": doc_id})

        elif method == "POST" and action == "export":
            return _response(200, {"status": "export_requested", "doc_id": doc_id})

        else:
            return _response(400, {"error": f"unknown: {method} {path}"})

    except Exception as e:
        return _response(500, {"error": str(e)})
