"""AgentCore Memory — boto3 bedrock-agentcore backed memory layer.

Short-term: session conversation events via create_event.
Long-term: customer facts via batch_create_memory_records.
Retrieval: customer-scoped namespace queries via retrieve_memory_records.

Degraded mode: All Memory API calls are wrapped with try/except.
On failure the system continues with bounded session history only.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import boto3

logger = logging.getLogger(__name__)


class AgentCoreMemory:
    """Wrapper around boto3 bedrock-agentcore Memory APIs.

    Args:
        memory_id: The AgentCore Memory instance identifier.
        region: AWS region for the bedrock-agentcore client.
        on_degraded: Optional callback invoked when a Memory API call fails.
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

    def _safe_call(self, method_name: str, fn: Callable[[], Any], default: Any = None) -> Any:
        try:
            return fn()
        except Exception as exc:
            logger.warning("Memory API %s failed (degraded mode): %s", method_name, exc)
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
        self, session_id: str, actor_id: str, content: str, role: str = "USER"
    ) -> bool:
        """Store a session conversation event (short-term memory).

        Uses create_event API with conversational payload.
        """
        result = self._safe_call(
            "store_session_event",
            lambda: self.client.create_event(
                memoryId=self.memory_id,
                actorId=actor_id,
                sessionId=session_id,
                eventTimestamp=datetime.now(timezone.utc),
                payload=[
                    {
                        "conversational": {
                            "content": {"text": content},
                            "role": role.upper(),
                        }
                    }
                ],
            ),
            default=None,
        )
        return result is not None

    # ------------------------------------------------------------------
    # Long-term (customer facts)
    # ------------------------------------------------------------------

    def store_long_term_facts(self, customer: str, facts: list[dict]) -> bool:
        """Batch-store long-term facts scoped to a customer namespace."""
        records = [
            {
                "requestIdentifier": str(uuid.uuid4()),
                "namespaces": [f"/customers/{customer}/"],
                "content": {"text": f["value"]},
                "timestamp": datetime.now(timezone.utc),
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
        self, customer: str, query: str, top_k: int = 5
    ) -> list[dict]:
        """Retrieve long-term memory records scoped to a customer."""
        response = self._safe_call(
            "retrieve_customer_context",
            lambda: self.client.retrieve_memory_records(
                memoryId=self.memory_id,
                namespacePath=f"/customers/{customer}/",
                searchCriteria={
                    "searchQuery": query,
                    "topK": top_k,
                },
            ),
            default={},
        )
        return response.get("records", [])
