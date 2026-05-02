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
    return TaskPlan(
        tasks=[Task(agent="discovery_agent", action="collect_info", params={"message": user_message})],
        chat_response="",
    )


def build_task_plan(user_message: str) -> TaskPlan:
    """Analyze user message via LLM and produce a TaskPlan.

    Uses Bedrock Sonnet to classify intent based on the agent registry.
    Falls back to discovery_agent if LLM call fails.
    """
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
