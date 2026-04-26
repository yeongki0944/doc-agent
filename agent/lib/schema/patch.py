"""Patch and AppSync message types.

Defines Patch, PatchOperation, and AgentStatus used for real-time
document synchronization via AppSync Events channels.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_serializer


class AgentStatus(str, Enum):
    """Agent processing status published to docs/{docId}/status."""
    processing = "processing"
    idle = "idle"
    error = "error"
    degraded = "degraded"


class PatchOperation(BaseModel):
    """Single JSON-Patch-style operation."""
    op: str = "replace"  # replace | add | remove
    path: str = ""
    value: Any = None
    source: Optional[str] = None  # user_input | ai_recommended | calculated


class Patch(BaseModel):
    """A batch of patch operations published to docs/{docId}/patch."""
    patch_id: str = ""
    doc_id: str = ""
    agent: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    operations: list[PatchOperation] = Field(default_factory=list)
    version: int = 0
    version_before: Optional[int] = None
    version_after: Optional[int] = None

    @field_serializer("timestamp")
    def _serialize_timestamp(self, v: datetime, _info: Any) -> str:
        return v.isoformat()
