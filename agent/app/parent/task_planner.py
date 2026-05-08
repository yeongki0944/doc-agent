"""Task planner — LLM-based intent classification with agent registry.

Replaces keyword-based routing with Bedrock LLM call that receives
the full agent registry as context and autonomously decides which
agent(s) to invoke.

The agent registry is loaded from agent/data/presets/agent_registry.json
and injected into the LLM system prompt. This allows routing changes
via JSON config without code modifications.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import boto3

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Task/TaskPlan — duplicated here to avoid importing orchestrator
# (which triggers BedrockAgentCoreApp binding)
# ---------------------------------------------------------------------------

@dataclass
class Task:
    agent: str = ""
    action: str = ""
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskPlan:
    tasks: list[Task] = field(default_factory=list)
    patch_proposals: list = field(default_factory=list)
    chat_response: str = ""
    status_updates: list = field(default_factory=list)
    new_version: int = 0
    execution_log: list = field(default_factory=list)
    status: str = "completed"
    changed_sections: list[str] = field(default_factory=list)
    created_change_request_ids: list[str] = field(default_factory=list)
    tool_results: dict[str, Any] = field(default_factory=dict)
    degraded_messages: list[str] = field(default_factory=list)

# ---------------------------------------------------------------------------
# Agent registry (loaded once at module level)
# ---------------------------------------------------------------------------

_REGISTRY_PATH = Path(__file__).resolve().parents[2] / "data" / "presets" / "agent_registry.json"

def _load_registry() -> dict:
    try:
        return json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error("Failed to load agent registry: %s", e)
        return {"agents": []}

_AGENT_REGISTRY = _load_registry()

# ---------------------------------------------------------------------------
# LLM configuration
# ---------------------------------------------------------------------------

REGION = os.environ.get("AWS_REGION", "ap-northeast-2")
ROUTER_MODEL = os.environ.get(
    "ROUTER_MODEL",
    os.environ.get("CHILD_MODEL", "apac.anthropic.claude-3-5-sonnet-20241022-v2:0"),
)

_bedrock_client = None

def _get_bedrock():
    global _bedrock_client
    if _bedrock_client is None:
        _bedrock_client = boto3.client("bedrock-runtime", region_name=REGION)
    return _bedrock_client


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """당신은 APN PoC Project Plan 문서 생성 시스템의 라우터입니다.
사용자 메시지를 분석하여 어떤 에이전트를 호출할지 결정하세요.

## 사용 가능한 에이전트
{registry}

## 규칙
1. 사용자 메시지의 의도를 파악하여 가장 적합한 에이전트를 선택하세요.
2. 복수 에이전트가 필요하면 실행 순서대로 나열하세요.
3. section_writer_agent를 선택할 때는 반드시 params.section에 작성할 섹션 이름을 포함하세요.
4. 사용자가 "작성해줘", "만들어줘", "생성해줘" 등 섹션 작성을 요청하면 section_writer_agent를 사용하세요.
5. 프로젝트 정보(고객사, 파트너, 목표 등)를 제공하는 메시지는 discovery_agent를 사용하세요.
6. 인사, 잡담, 일반 질문은 conversation_agent를 사용하세요.
7. 하나의 메시지에 여러 의도가 있으면 (예: "고객사는 ABC이고 Overview 작성해줘") 여러 에이전트를 순서대로 나열하세요.

## 응답 형식 (반드시 유효한 JSON만 출력)
{{
  "tasks": [
    {{"agent": "에이전트명", "action": "액션명", "params": {{"message": "원본 메시지", ...추가 파라미터}}}}
  ]
}}"""


def _build_system_prompt() -> str:
    registry_text = json.dumps(_AGENT_REGISTRY["agents"], ensure_ascii=False, indent=2)
    return _SYSTEM_PROMPT.format(registry=registry_text)


# ---------------------------------------------------------------------------
# LLM-based task planning
# ---------------------------------------------------------------------------

def _call_llm(user_message: str) -> dict:
    """Call Bedrock to classify intent and produce task plan."""
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 500,
        "system": _build_system_prompt(),
        "messages": [{"role": "user", "content": user_message}],
    }
    try:
        resp = _get_bedrock().invoke_model(
            modelId=ROUTER_MODEL,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body),
        )
        raw = json.loads(resp["body"].read())["content"][0]["text"]
        # Extract JSON from response
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(raw[start:end])
    except Exception as e:
        logger.error("LLM router call failed: %s", e)
    return {}


def _fallback_plan(user_message: str) -> TaskPlan:
    """Fallback when LLM call fails — route to discovery_agent."""
    rule_based = _rule_based_plan(user_message)
    if rule_based:
        return rule_based
    return TaskPlan(
        tasks=[Task(agent="discovery_agent", action="collect_info", params={"message": user_message})],
        chat_response="",
    )


def _rule_based_plan(user_message: str) -> TaskPlan | None:
    """Route high-signal MCP workflow intents before calling the LLM router."""
    message = user_message or ""
    msg_lower = message.lower()

    if _contains_any(msg_lower, ("review_submission", "submission lint", "review", "lint", "readiness", "리뷰", "검토", "검증")):
        return TaskPlan(tasks=[
            Task(agent="internal_tools", action="run_submission_lint", params={"message": message})
        ])

    if _contains_any(msg_lower, ("resource_planning", "resource planning", "funding", "funding amount", "arr", "mrr", "sow cost", "리소스", "펀딩", "지원금", "비용 계획")):
        params = {"message": message, **_extract_resource_numbers(message)}
        if _contains_any(msg_lower, ("apply", "update document", "save", "반영", "적용", "저장")):
            params["apply"] = True
        return TaskPlan(tasks=[
            Task(agent="internal_tools", action="calculate_resource_plan", params=params)
        ])

    if _contains_any(msg_lower, ("team", "staffing", "팀 구성", "인력", "역할", "role")):
        return TaskPlan(tasks=[
            Task(agent="staffing_agent", action="recommend", params={"message": message})
        ])

    if _contains_any(msg_lower, ("create_change_request", "change request", "변경 요청", "cr 생성")):
        return TaskPlan(tasks=[
            Task(agent="internal_tools", action="create_change_request", params={"message": message})
        ])

    if _contains_any(msg_lower, ("apply_document_patch", "json patch", "patch 적용", "패치 적용")):
        return TaskPlan(tasks=[
            Task(agent="internal_tools", action="apply_document_patch", params={"message": message})
        ])

    if _contains_any(msg_lower, ("export_docx", "docx", "export", "download", "내보내기", "다운로드")):
        return TaskPlan(tasks=[
            Task(agent="formatter_agent", action="export_docx", params={"message": message})
        ])

    if _contains_any(msg_lower, ("architecture_design", "architecture design", "architecture", "아키텍처", "서비스 구성", "drawio", ".drawio")):
        action = "analyze_existing" if _contains_any(msg_lower, ("drawio", ".drawio", "업로드", "file", "파일")) else "design_new"
        return TaskPlan(tasks=[
            Task(agent="architecture_agent", action=action, params={"message": message})
        ])

    if _contains_any(msg_lower, ("aws_service_explanation", "explain aws", "aws service", "서비스 설명", "bedrock 설명", "lambda 설명")):
        return TaskPlan(tasks=[
            Task(agent="internal_tools", action="aws_service_explanation", params={"message": message})
        ])

    if _contains_any(msg_lower, ("section_recommendation", "section recommendation", "섹션 추천", "섹션 보완")):
        return TaskPlan(tasks=[
            Task(agent="section_writer_agent", action="recommend", params={"message": message})
        ])

    if _contains_any(msg_lower, ("fast_edit", "quick edit", "빠른 수정", "간단히 수정")):
        return TaskPlan(tasks=[
            Task(agent="internal_tools", action="fast_edit", params={"message": message})
        ])

    if _contains_any(msg_lower, ("guided_draft", "guided draft", "초안", "draft", "작성 시작")):
        return TaskPlan(tasks=[
            Task(agent="discovery_agent", action="collect_info", params={"message": message})
        ])

    return None


def _contains_any(message: str, needles: tuple[str, ...]) -> bool:
    return any(needle in message for needle in needles)


def _extract_resource_numbers(message: str) -> dict[str, float]:
    params: dict[str, float] = {}
    patterns = {
        "target_funding_amount": r"(?:target[_ ]?funding[_ ]?amount|funding|지원금|펀딩)\D{0,20}(\d[\d,]*(?:\.\d+)?)",
        "arr": r"\barr\D{0,20}(\d[\d,]*(?:\.\d+)?)",
        "mrr": r"\bmrr\D{0,20}(\d[\d,]*(?:\.\d+)?)",
        "sow_cost": r"(?:sow[_ ]?cost|sow cost|sow|계약금액)\D{0,20}(\d[\d,]*(?:\.\d+)?)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if match:
            try:
                params[key] = float(match.group(1).replace(",", ""))
            except ValueError:
                continue
    if "target_funding_amount" not in params:
        numbers = re.findall(r"\d[\d,]*(?:\.\d+)?", message)
        if numbers and _contains_any(message.lower(), ("funding", "지원금", "펀딩")):
            try:
                params["target_funding_amount"] = float(numbers[0].replace(",", ""))
            except ValueError:
                pass
    return params


def build_task_plan(user_message: str) -> TaskPlan:
    """Analyze user message via LLM and produce a TaskPlan.

    Uses Bedrock Sonnet to classify intent based on the agent registry.
    Falls back to discovery_agent if LLM call fails.
    """
    rule_based = _rule_based_plan(user_message)
    if rule_based:
        return rule_based

    result = _call_llm(user_message)

    if not result or "tasks" not in result:
        logger.warning("LLM router returned no tasks, falling back to discovery")
        return _fallback_plan(user_message)

    tasks: list[Task] = []
    for t in result["tasks"]:
        agent = t.get("agent", "")
        action = t.get("action", "")
        params = t.get("params", {})
        # Ensure message is always in params
        if "message" not in params:
            params["message"] = user_message
        if agent and action:
            tasks.append(Task(agent=agent, action=action, params=params))

    if not tasks:
        return _fallback_plan(user_message)

    return TaskPlan(tasks=tasks, chat_response="")
