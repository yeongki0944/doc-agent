"""AgentCore Runtime entry point — Parent Orchestrator.

Deploys the Parent Orchestrator on AgentCore Runtime using
``BedrockAgentCoreApp`` + ``@app.entrypoint``.

The ``/invocations`` POST endpoint receives ``doc_id``, ``prompt``,
and bounded ``history`` (recent N turns).  Document state mutations
are delivered exclusively via the AppSync ``docs/{docId}/patch``
channel; the HTTP response carries only the chat reply and metadata.

Environment variables
---------------------
PARENT_MODEL : str
    Inference profile for the Parent Orchestrator.
    Default: ``global.anthropic.claude-opus-4-6-v1``
CHILD_MODEL : str
    Inference profile for sub-agents (Sonnet 3.5 v2).
    Default: ``apac.anthropic.claude-3-5-sonnet-20241022-v2:0``
PARENT_MODEL_FALLBACK : str
    Fallback inference profile for the Parent Orchestrator when primary is unavailable.
    Default: ``""`` (empty — degraded mode if primary fails)
CHILD_MODEL_FALLBACK : str
    Fallback inference profile for sub-agents when primary is unavailable.
    Default: ``""`` (empty — degraded mode if primary fails)
"""

from __future__ import annotations

import logging
import os
from typing import Any

from bedrock_agentcore import BedrockAgentCoreApp

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configurable model inference profiles (overridable via env vars)
# ---------------------------------------------------------------------------

PARENT_MODEL: str = os.environ.get(
    "PARENT_MODEL",
    "global.anthropic.claude-opus-4-6-v1",
)

CHILD_MODEL: str = os.environ.get(
    "CHILD_MODEL",
    "apac.anthropic.claude-3-5-sonnet-20241022-v2:0",
)

PARENT_MODEL_FALLBACK: str = os.environ.get(
    "PARENT_MODEL_FALLBACK",
    "",
)

CHILD_MODEL_FALLBACK: str = os.environ.get(
    "CHILD_MODEL_FALLBACK",
    "",
)

# ---------------------------------------------------------------------------
# AgentCore Runtime application
# ---------------------------------------------------------------------------

app = BedrockAgentCoreApp()


def _validate_payload(payload: dict[str, Any]) -> tuple[str, str, list[dict]]:
    """Extract and validate required fields from the invocation payload.

    Returns
    -------
    tuple[str, str, list[dict]]
        ``(doc_id, prompt, history)``

    Raises
    ------
    ValueError
        If ``doc_id`` or ``prompt`` is missing / empty.
    """
    doc_id = payload.get("doc_id")
    if not doc_id or (isinstance(doc_id, str) and not doc_id.strip()):
        raise ValueError("payload must include a non-empty 'doc_id'")

    prompt = payload.get("prompt")
    if not prompt or (isinstance(prompt, str) and not prompt.strip()):
        raise ValueError("payload must include a non-empty 'prompt'")

    history: list[dict] = payload.get("history", [])
    return doc_id, prompt, history


@app.entrypoint
def invoke(payload: dict) -> dict:
    """AgentCore Runtime entry point.

    Called via ``POST /invocations`` through API Gateway.

    Parameters
    ----------
    payload : dict
        Expected keys:
        - ``doc_id``  (str, required) — target document identifier
        - ``prompt``  (str, required) — user chat message
        - ``history`` (list[dict], optional) — bounded recent N turns

    Returns
    -------
    dict
        ``{"result": <chat_response>, "version": <new_version>, "status": "ok"}``

    Processing steps (delegated to :class:`ParentOrchestrator`):
        1. Retrieve long-term context from AgentCore Memory
        2. Fetch ``Document_State`` + version from DynamoDB
        3. Build task plan → delegate to sub-agents
        4. Generate patches → apply with optimistic lock to DynamoDB
        5. Publish patches / status / chat via AppSync Events
        6. Store session events in AgentCore Memory
    """
    try:
        if not isinstance(payload, dict):
            return {"result": "payload must be a JSON object (dict)", "version": 0, "status": "error"}
        doc_id, prompt, history = _validate_payload(payload)
    except ValueError as exc:
        return {"result": str(exc), "version": 0, "status": "error"}

    logger.info(
        "invoke called — doc_id=%s, prompt_len=%d, history_turns=%d",
        doc_id,
        len(prompt),
        len(history),
    )

    # ------------------------------------------------------------------
    # Delegate to ParentOrchestrator.handle_message()
    # ------------------------------------------------------------------
    import asyncio
    from agent.app.parent.orchestrator import ParentOrchestrator

    orchestrator = _get_orchestrator()

    try:
        plan = asyncio.run(
            orchestrator.handle_message(doc_id, prompt, history)
        )
    except RuntimeError:
        # Already inside a running event loop (e.g. AgentCore Runtime)
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            plan = pool.submit(
                asyncio.run,
                orchestrator.handle_message(doc_id, prompt, history),
            ).result()

    return {
        "result": plan.chat_response,
        "version": plan.new_version,
        "status": "ok",
    }


# ---------------------------------------------------------------------------
# Orchestrator singleton
# ---------------------------------------------------------------------------

_orchestrator_instance: "ParentOrchestrator | None" = None


def _get_orchestrator() -> "ParentOrchestrator":
    """Return a module-level ParentOrchestrator singleton.

    Lazily initialized on first call. The document store and memory
    instances are shared across invocations within the same Runtime.

    When ``AGENTCORE_MEMORY_ID`` is set, an :class:`AgentCoreMemory`
    instance is created and wired into the orchestrator for long-term
    context retrieval and session event storage (Req 2.1, 2.2, 2.3).
    """
    global _orchestrator_instance
    if _orchestrator_instance is None:
        from agent.app.parent.orchestrator import ParentOrchestrator
        from agent.lib.memory.agentcore_memory import AgentCoreMemory

        memory = None
        memory_id = os.environ.get("AGENTCORE_MEMORY_ID", "")
        if memory_id:
            memory = AgentCoreMemory(
                memory_id=memory_id,
                region=os.environ.get("AWS_REGION", "ap-northeast-2"),
            )
            logger.info("AgentCoreMemory initialized with memory_id=%s", memory_id)
        else:
            logger.info("AGENTCORE_MEMORY_ID not set — running without Memory")

        _orchestrator_instance = ParentOrchestrator(memory=memory)
    return _orchestrator_instance
