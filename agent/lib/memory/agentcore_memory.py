"""AgentCore Memory — boto3 bedrock-agentcore backed memory layer.

Replaces v1's in-memory placeholder (memory.py) with actual
AgentCore Memory API calls for short-term and long-term memory.

Short-term: session conversation events via create_memory_event.
Long-term: customer characteristics, security requirements, region
           constraints via batch_create_memory_records.
Retrieval: customer-scoped namespace queries via retrieve_memory_records.

Degraded mode (Req 2.5): All Memory API calls are wrapped with
try/except. On failure the system continues with bounded session
history only and publishes a warning status via the on_degraded
callback.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

import boto3

logger = logging.getLogger(__name__)


class AgentCoreMemory:
    """Wrapper around boto3 bedrock-agentcore Memory APIs.

    Args:
        memory_id: The AgentCore Memory instance identifier.
        region: AWS region for the bedrock-agentcore client.
        on_degraded: Optional callback invoked when a Memory API call
            fails.  Signature: ``(method_name: str, error: Exception) -> None``.
            The orchestrator uses this to publish a warning/degraded
            status to ``docs/{docId}/status``.
    """

    def __init__(
        self,
        memory_id: str,
        region: str = "ap-northeast-2",
        on_degraded: Optional[Callable[[str, Exception], None]] = None,
    ) -> None:
        self.client = boto3.client("bedrock-agentcore", region_name=region)
        self.memory_id = memory_id
        self.on_degraded = on_degraded

    # ------------------------------------------------------------------
    # Safe wrapper — catches exceptions and triggers degraded callback
    # ------------------------------------------------------------------

    def _safe_call(
        self,
        method_name: str,
        fn: Callable[[], Any],
        default: Any = None,
    ) -> Any:
        """Execute *fn* and return its result.

        On any exception the error is logged, the ``on_degraded``
        callback is invoked (if set), and *default* is returned so the
        caller can continue in degraded mode.
        """
        try:
            return fn()
        except Exception as exc:
            logger.warning(
                "Memory API %s failed (degraded mode): %s", method_name, exc
            )
            if self.on_degraded is not None:
                try:
                    self.on_degraded(method_name, exc)
                except Exception:
                    logger.exception("on_degraded callback itself failed")
            return default

    # ------------------------------------------------------------------
    # Short-term (session events)
    # ------------------------------------------------------------------

    def store_session_event(
        self, session_id: str, actor_id: str, content: str
    ) -> bool:
        """Store a session conversation event (short-term memory).

        Uses the ``create_memory_event`` API to persist the current
        turn so AgentCore can manage session context automatically.

        Returns ``True`` on success, ``False`` if the call failed
        (degraded mode).
        """
        result = self._safe_call(
            "store_session_event",
            lambda: self.client.create_memory_event(
                memoryId=self.memory_id,
                actorId=actor_id,
                sessionId=session_id,
                messages=[{"role": "user", "content": content}],
            ),
            default=None,
        )
        return result is not None

    # ------------------------------------------------------------------
    # Long-term (customer facts)
    # ------------------------------------------------------------------

    def store_long_term_facts(self, customer: str, facts: list[dict]) -> bool:
        """Batch-store long-term facts scoped to a customer namespace.

        Each fact dict must contain a ``"value"`` key whose text will
        be stored under ``/customers/{customer}/``.

        Returns ``True`` on success, ``False`` on failure (degraded).
        """
        records = [
            {
                "content": {"text": f["value"]},
                "namespace": f"/customers/{customer}/",
            }
            for f in facts
        ]
        result = self._safe_call(
            "store_long_term_facts",
            lambda: self.client.batch_create_memory_records(
                memoryId=self.memory_id,
                records=records,
            ),
            default=None,
        )
        return result is not None

    # ------------------------------------------------------------------
    # Retrieval (customer-scoped)
    # ------------------------------------------------------------------

    def retrieve_customer_context(
        self, customer: str, query: str
    ) -> list[dict]:
        """Retrieve long-term memory records scoped to a customer.

        Searches within the ``/customers/{customer}/`` namespace and
        returns matching records for use as supplemental context.

        Returns an empty list on failure (degraded mode).
        """
        response = self._safe_call(
            "retrieve_customer_context",
            lambda: self.client.retrieve_memory_records(
                memoryId=self.memory_id,
                query=query,
                namespace=f"/customers/{customer}/",
            ),
            default={},
        )
        return response.get("records", [])
