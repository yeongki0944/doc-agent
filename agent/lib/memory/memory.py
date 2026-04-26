"""AgentCore Memory — short-term and long-term memory layers.

Short-term: session conversation context.
Long-term: customer characteristics, region constraints, etc.

In production, backed by AgentCore Memory service.
Currently in-memory placeholder.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MemoryEntry:
    key: str
    value: Any
    scope: str = "session"  # session | customer


class AgentMemory:
    """In-memory placeholder for AgentCore Memory."""

    def __init__(self) -> None:
        self._short_term: dict[str, list[dict]] = {}  # session_id → messages
        self._long_term: dict[str, dict[str, Any]] = {}  # customer_name → facts

    # --- Short-term (session context) ---

    def add_message(self, session_id: str, role: str, content: str) -> None:
        self._short_term.setdefault(session_id, []).append({"role": role, "content": content})

    def get_messages(self, session_id: str) -> list[dict]:
        return self._short_term.get(session_id, [])

    # --- Long-term (customer facts) ---

    def store_fact(self, customer: str, key: str, value: Any) -> None:
        self._long_term.setdefault(customer, {})[key] = value

    def get_facts(self, customer: str) -> dict[str, Any]:
        return self._long_term.get(customer, {})

    def lookup_customer(self, customer: str) -> dict[str, Any] | None:
        """Look up long-term memory for a customer at session start."""
        facts = self._long_term.get(customer)
        return dict(facts) if facts else None
