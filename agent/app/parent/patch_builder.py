"""Patch builder — converts agent results into Patch objects.

Transforms the output of child agents into JSON-Patch-style
operations for AppSync Events publication.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from agent.lib.schema.patch import Patch, PatchOperation


_patch_counter = 0


def _next_patch_id() -> str:
    global _patch_counter
    _patch_counter += 1
    ts = datetime.utcnow().strftime("%Y%m%d")
    return f"p-{ts}-{_patch_counter:04d}"


def build_patch(
    doc_id: str,
    agent: str,
    version: int,
    operations: list[dict[str, Any]],
) -> Patch:
    """Build a Patch from raw operation dicts.

    Args:
        doc_id: Document ID.
        agent: Name of the agent that produced the changes.
        version: Current document version (for optimistic locking).
        operations: List of dicts with keys: op, path, value, source.
    """
    ops = [
        PatchOperation(
            op=op.get("op", "replace"),
            path=op.get("path", ""),
            value=op.get("value"),
            source=op.get("source"),
        )
        for op in operations
    ]
    return Patch(
        patch_id=_next_patch_id(),
        doc_id=doc_id,
        agent=agent,
        version=version,
        operations=ops,
    )
