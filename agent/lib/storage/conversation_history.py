"""Conversation history persistence for doc-agent-conversation-history DynamoDB table.

Stores document-level conversation history with bounded window support.
The server is the canonical store; the frontend uses localStorage as a cache only.

Table schema:
    Partition Key: ``document_id`` (String)
    Sort Key:      ``session_id`` (String)
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key


class ConversationHistoryStore:
    """Read/write interface for conversation history.

    Supports both a real DynamoDB backend and an in-memory mode for tests.
    """

    DEFAULT_BOUNDED_WINDOW = 20

    def __init__(
        self,
        table_name: str | None = None,
        region_name: str = "ap-northeast-2",
        *,
        dynamodb_resource: Any | None = None,
    ) -> None:
        self._table_name = table_name or os.environ.get(
            "CONVERSATION_HISTORY_TABLE", "doc-agent-conversation-history"
        )
        if dynamodb_resource is not None:
            self._resource = dynamodb_resource
        else:
            self._resource = boto3.resource(
                "dynamodb", region_name=region_name
            )
        self._table = self._resource.Table(self._table_name)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def save(
        self,
        document_id: str,
        session_id: str,
        messages: list[dict],
        *,
        bounded_window: int | None = None,
    ) -> dict:
        """Save conversation history for a document/session.

        Args:
            document_id: The document this conversation belongs to.
            session_id: Session identifier.
            messages: Full list of messages to persist.
            bounded_window: Max messages to include in API calls (default 20).

        Returns:
            The item dict that was written.
        """
        bw = bounded_window if bounded_window is not None else self.DEFAULT_BOUNDED_WINDOW

        item: dict[str, Any] = {
            "document_id": document_id,
            "session_id": session_id,
            "messages": messages,
            "bounded_window": bw,
            "total_count": len(messages),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._table.put_item(Item=item)
        return item

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def load(
        self,
        document_id: str,
        session_id: str | None = None,
    ) -> dict | None:
        """Load conversation history for a document.

        If session_id is provided, fetches that specific session.
        Otherwise, fetches the most recent session for the document.

        Returns:
            The history item dict, or None if not found.
        """
        if session_id:
            response = self._table.get_item(
                Key={"document_id": document_id, "session_id": session_id}
            )
            return response.get("Item")

        # No session_id — query all sessions for this doc, get latest
        response = self._table.query(
            KeyConditionExpression=Key("document_id").eq(document_id),
            ScanIndexForward=False,  # descending by session_id
            Limit=1,
        )
        items = response.get("Items", [])
        return items[0] if items else None

    def load_bounded(
        self,
        document_id: str,
        session_id: str | None = None,
    ) -> list[dict]:
        """Load only the bounded window of recent messages.

        Convenience method that returns the last N messages where N
        is the stored ``bounded_window`` value.

        Returns:
            List of recent messages (up to bounded_window), or empty list.
        """
        item = self.load(document_id, session_id)
        if not item:
            return []
        messages = item.get("messages", [])
        bw = item.get("bounded_window", self.DEFAULT_BOUNDED_WINDOW)
        return messages[-bw:]

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete(self, document_id: str, session_id: str) -> None:
        """Delete a specific conversation history entry."""
        self._table.delete_item(
            Key={"document_id": document_id, "session_id": session_id}
        )
