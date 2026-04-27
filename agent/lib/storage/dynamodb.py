"""DynamoDB Document_State CRUD helper.

Provides two implementations:
- ``DocumentStore``: in-memory placeholder for unit tests / local dev.
- ``DynamoDBDocumentStore``: real DynamoDB backend with optimistic locking.

Supports optimistic locking via version field.
"""

from __future__ import annotations

import os
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

import boto3
from boto3.dynamodb.conditions import Attr

from agent.lib.schema.document_state import DocumentState


class VersionConflictError(Exception):
    """Raised when optimistic locking detects a version mismatch."""
    pass


class DocumentNotFoundError(Exception):
    """Raised when a document is not found."""
    pass


def _to_dynamodb_value(value: Any) -> Any:
    """Convert JSON-serializable values to DynamoDB-safe Python values."""
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, list):
        return [_to_dynamodb_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_dynamodb_value(item) for key, item in value.items()}
    return value


class DocumentStore:
    """In-memory document store (placeholder for DynamoDB)."""

    def __init__(self) -> None:
        self._store: dict[str, dict] = {}

    def get(self, document_id: str) -> DocumentState:
        """Retrieve a document by ID."""
        raw = self._store.get(document_id)
        if raw is None:
            raise DocumentNotFoundError(f"Document {document_id} not found")
        return DocumentState.model_validate(deepcopy(raw))

    def put(self, doc: DocumentState) -> DocumentState:
        """Create or overwrite a document (no version check)."""
        doc.updated_at = datetime.utcnow()
        self._store[doc.document_id] = doc.model_dump(mode="json")
        return doc

    def update(self, doc: DocumentState, expected_version: int) -> DocumentState:
        """Update with optimistic locking.

        Args:
            doc: The updated document state.
            expected_version: The version the caller expects. If the stored
                version differs, a VersionConflictError is raised.

        Returns:
            The saved document with incremented version.
        """
        existing = self._store.get(doc.document_id)
        if existing is not None and existing.get("version", 0) != expected_version:
            raise VersionConflictError(
                f"Version conflict: expected {expected_version}, "
                f"got {existing.get('version')}"
            )
        doc.version = expected_version + 1
        doc.updated_at = datetime.utcnow()
        self._store[doc.document_id] = doc.model_dump(mode="json")
        return doc

    def delete(self, document_id: str) -> None:
        """Delete a document."""
        self._store.pop(document_id, None)

    def exists(self, document_id: str) -> bool:
        """Check if a document exists."""
        return document_id in self._store


class DynamoDBDocumentStore:
    """Real DynamoDB-backed document store with optimistic locking.

    Uses ``boto3.resource("dynamodb")`` for all operations.
    Table name is read from the ``DYNAMODB_TABLE`` env var
    (default: ``doc-agent-documents``).
    """

    def __init__(
        self,
        table_name: str | None = None,
        region_name: str = "ap-northeast-2",
        *,
        dynamodb_resource: Any | None = None,
    ) -> None:
        self._table_name = table_name or os.environ.get(
            "DYNAMODB_TABLE", "doc-agent-documents"
        )
        if dynamodb_resource is not None:
            self._resource = dynamodb_resource
        else:
            self._resource = boto3.resource(
                "dynamodb", region_name=region_name
            )
        self._table = self._resource.Table(self._table_name)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, document_id: str) -> DocumentState:
        """Retrieve a document by ID from DynamoDB."""
        response = self._table.get_item(Key={"document_id": document_id})
        item = response.get("Item")
        if item is None:
            raise DocumentNotFoundError(f"Document {document_id} not found")
        return DocumentState.model_validate(item)

    # ------------------------------------------------------------------
    # Write (unconditional)
    # ------------------------------------------------------------------

    def put(self, doc: DocumentState) -> DocumentState:
        """Create or overwrite a document (no version check)."""
        doc.updated_at = datetime.now(timezone.utc)
        self._table.put_item(Item=_to_dynamodb_value(doc.model_dump(mode="json")))
        return doc

    # ------------------------------------------------------------------
    # Write (optimistic locking)
    # ------------------------------------------------------------------

    def update(self, doc: DocumentState, expected_version: int) -> DocumentState:
        """Update with optimistic locking via ``ConditionExpression``.

        Increments ``version`` and refreshes ``updated_at`` before writing.
        Raises ``VersionConflictError`` when the stored version does not
        match *expected_version* (DynamoDB ``ConditionalCheckFailedException``).
        """
        doc.version = expected_version + 1
        doc.updated_at = datetime.now(timezone.utc)
        item = _to_dynamodb_value(doc.model_dump(mode="json"))

        try:
            self._table.put_item(
                Item=item,
                ConditionExpression=Attr("version").eq(expected_version),
            )
        except self._resource.meta.client.exceptions.ConditionalCheckFailedException:
            raise VersionConflictError(
                f"Version conflict: expected {expected_version}, "
                f"stored version differs"
            )
        return doc

    # ------------------------------------------------------------------
    # Delete / exists
    # ------------------------------------------------------------------

    def delete(self, document_id: str) -> None:
        """Delete a document from DynamoDB."""
        self._table.delete_item(Key={"document_id": document_id})

    def exists(self, document_id: str) -> bool:
        """Check if a document exists (projection to save RCU)."""
        response = self._table.get_item(
            Key={"document_id": document_id},
            ProjectionExpression="document_id",
        )
        return "Item" in response
