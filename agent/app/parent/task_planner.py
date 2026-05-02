"""Task planner — analyzes user messages and builds task plans.

Parses user intent from messages and creates ordered task lists
for the Parent Orchestrator to delegate.
"""

from __future__ import annotations

from agent.app.parent.orchestrator import Task, TaskPlan


# Keyword → agent/action mapping for simple intent detection
_INTENT_MAP: list[tuple[list[str], str, str]] = [
    (["아키텍처", "architecture", "drawio", ".drawio"], "architecture_agent", "analyze"),
    (["팀", "team", "역할", "role", "staffing", "인원"], "staffing_agent", "recommend"),
    (["비용", "cost", "단가", "rate", "예산"], "cost_agent", "calculate"),
    (["리뷰", "review", "검증", "검사"], "reviewer_agent", "review"),
    (["export", "docx", "다운로드", "내보내기"], "formatter_agent", "export"),
    (["일정", "milestone", "마일스톤", "deliverable"], "milestone_agent", "build"),
]


def _is_conversation_message(message: str) -> bool:
    msg = message.strip().lower()
    if not msg:
        return False
    if msg.isdigit():
        return True
    return any(
        phrase in msg
        for phrase in [
            "안녕",
            "hello",
            "hi",
            "고마워",
            "감사",
            "다른 이야기",
            "잡담",
            "뭐 할 수",
            "무엇을 할 수",
            "help",
        ]
    )


def build_task_plan(user_message: str) -> TaskPlan:
    """Analyze user message and produce a TaskPlan.

    Simple keyword-based intent detection. In production this would
    be replaced by LLM-based intent classification.
    """
    msg_lower = user_message.lower()
    tasks: list[Task] = []

    if _is_conversation_message(user_message):
        return TaskPlan(
            tasks=[
                Task(
                    agent="conversation_agent",
                    action="respond",
                    params={"message": user_message},
                )
            ],
        )

    for keywords, agent, action in _INTENT_MAP:
        if any(kw in msg_lower for kw in keywords):
            tasks.append(Task(agent=agent, action=action, params={"message": user_message}))

    # Default: if no intent matched, route to discovery
    if not tasks:
        tasks.append(Task(agent="discovery_agent", action="collect_info", params={"message": user_message}))

    return TaskPlan(
        tasks=tasks,
        chat_response="",
    )
