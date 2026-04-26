"""Patch history persistence for doc-agent-patch-history DynamoDB table.

Tracks user message → delegated task → resulting patches with
version_before / version_after for auditable patch lineage.
"""

from __future__ import annotations

import os
from typing import Any, Optional

import boto3

from agent.lib.schema.patch import Patch


class PatchHistoryStore:
    """Read/write interface for the ``doc-agent-patch-history`` DynamoDB table.

    Table schema:
        Partition Key: ``document_id`` (String)
        Sort Key:      ``patch_id`` (String)
    """

    def __init__(
        self,
        table_name: str | None = None,
        region_name: str = "ap-northeast-2",
        *,
        dynamodb_resource: Any | None = None,
    ) -> None:
        self._table_name = table_name or os.environ.get(
            "PATCH_HISTORY_TABLE", "doc-agent-patch-history"
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

    def record_patch(
        self,
        patch: Patch,
        *,
        user_message_id: str = "",
        task_type: str = "",
        version_before: int | None = None,
        version_after: int | None = None,
    ) -> dict:
        """Persist a patch record to the history table.

        Args:
            patch: The Patch object to record.
            user_message_id: ID of the originating user message.
            task_type: The delegated task type (e.g. ``recommend_staffing``).
            version_before: Document version before the patch was applied.
            version_after: Document version after the patch was applied.

        Returns:
            The item dict that was written.
        """
        v_before = version_before if version_before is not None else patch.version_before
        v_after = version_after if version_after is not None else patch.version_after

        item: dict[str, Any] = {
            "document_id": patch.doc_id,
            "patch_id": patch.patch_id,
            "user_message_id": user_message_id,
            "agent": patch.agent,
            "task_type": task_type,
            "operations": [op.model_dump(mode="json") for op in patch.operations],
            "timestamp": patch.timestamp.isoformat(),
        }
        if v_before is not None:
            item["version_before"] = v_before
        if v_after is not None:
            item["version_after"] = v_after

        self._table.put_item(Item=item)
        return item

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_history(
        self,
        document_id: str,
        *,
        limit: int | None = None,
        ascending: bool = True,
    ) -> list[dict]:
        """Retrieve patch history for a document, ordered by patch_id.

        Args:
            document_id: The document to query.
            limit: Maximum number of records to return (optional).
            ascending: Sort direction on the sort key (default ascending).

        Returns:
            List of patch history item dicts.
        """
        query_kwargs: dict[str, Any] = {
            "KeyConditionExpression": boto3.dynamodb.conditions.Key("document_id").eq(document_id),
            "ScanIndexForward": ascending,
        }
        if limit is not None:
            query_kwargs["Limit"] = limit

        response = self._table.query(**query_kwargs)
        return response.get("Items", [])
