"""Tests for PatchHistoryStore — mocked boto3 DynamoDB resource."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, call

import pytest

from agent.lib.schema.patch import Patch, PatchOperation
from agent.lib.storage.patch_history import PatchHistoryStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_resource() -> tuple[MagicMock, MagicMock]:
    """Create a mock boto3 DynamoDB resource with a mock table."""
    resource = MagicMock()
    table = MagicMock()
    resource.Table.return_value = table
    return resource, table


def _sample_patch(
    doc_id: str = "doc-001",
    patch_id: str = "p-20250701-001",
    agent: str = "staffing_agent",
    version_before: int | None = 41,
    version_after: int | None = 42,
) -> Patch:
    return Patch(
        patch_id=patch_id,
        doc_id=doc_id,
        agent=agent,
        timestamp=datetime(2025, 7, 1, 10, 30, 0, tzinfo=timezone.utc),
        operations=[
            PatchOperation(
                op="replace",
                path="/staffing_plan/roles/project_manager/count/ai_recommended",
                value=1,
                source="ai_recommended",
            )
        ],
        version=42,
        version_before=version_before,
        version_after=version_after,
    )


# ---------------------------------------------------------------------------
# record_patch tests
# ---------------------------------------------------------------------------

class TestRecordPatch:
    """record_patch() — writes a patch record to DynamoDB."""

    def test_record_patch_writes_complete_item(self):
        resource, table = _make_mock_resource()
        store = PatchHistoryStore(dynamodb_resource=resource)
        patch = _sample_patch()

        result = store.record_patch(
            patch,
            user_message_id="msg-001",
            task_type="recommend_staffing",
        )

        table.put_item.assert_called_once()
        item = table.put_item.call_args[1]["Item"]
        assert item["document_id"] == "doc-001"
        assert item["patch_id"] == "p-20250701-001"
        assert item["user_message_id"] == "msg-001"
        assert item["agent"] == "staffing_agent"
        assert item["task_type"] == "recommend_staffing"
        assert item["version_before"] == 41
        assert item["version_after"] == 42
        assert len(item["operations"]) == 1
        assert item["operations"][0]["op"] == "replace"

    def test_record_patch_uses_explicit_version_overrides(self):
        resource, table = _make_mock_resource()
        store = PatchHistoryStore(dynamodb_resource=resource)
        patch = _sample_patch(version_before=10, version_after=11)

        store.record_patch(
            patch,
            version_before=99,
            version_after=100,
        )

        item = table.put_item.call_args[1]["Item"]
        assert item["version_before"] == 99
        assert item["version_after"] == 100

    def test_record_patch_omits_none_versions(self):
        resource, table = _make_mock_resource()
        store = PatchHistoryStore(dynamodb_resource=resource)
        patch = _sample_patch(version_before=None, version_after=None)

        store.record_patch(patch)

        item = table.put_item.call_args[1]["Item"]
        assert "version_before" not in item
        assert "version_after" not in item

    def test_record_patch_returns_written_item(self):
        resource, table = _make_mock_resource()
        store = PatchHistoryStore(dynamodb_resource=resource)
        patch = _sample_patch()

        result = store.record_patch(patch, user_message_id="msg-001")

        assert result["document_id"] == "doc-001"
        assert result["patch_id"] == "p-20250701-001"

    def test_record_patch_serializes_timestamp_as_iso(self):
        resource, table = _make_mock_resource()
        store = PatchHistoryStore(dynamodb_resource=resource)
        patch = _sample_patch()

        store.record_patch(patch)

        item = table.put_item.call_args[1]["Item"]
        assert item["timestamp"] == "2025-07-01T10:30:00+00:00"


# ---------------------------------------------------------------------------
# get_history tests
# ---------------------------------------------------------------------------

class TestGetHistory:
    """get_history() — queries patch history by document_id."""

    def test_get_history_returns_items(self):
        resource, table = _make_mock_resource()
        table.query.return_value = {
            "Items": [
                {"document_id": "doc-001", "patch_id": "p-001"},
                {"document_id": "doc-001", "patch_id": "p-002"},
            ]
        }
        store = PatchHistoryStore(dynamodb_resource=resource)

        result = store.get_history("doc-001")

        assert len(result) == 2
        assert result[0]["patch_id"] == "p-001"
        assert result[1]["patch_id"] == "p-002"

    def test_get_history_returns_empty_list_when_no_items(self):
        resource, table = _make_mock_resource()
        table.query.return_value = {"Items": []}
        store = PatchHistoryStore(dynamodb_resource=resource)

        result = store.get_history("doc-999")
        assert result == []

    def test_get_history_passes_limit(self):
        resource, table = _make_mock_resource()
        table.query.return_value = {"Items": []}
        store = PatchHistoryStore(dynamodb_resource=resource)

        store.get_history("doc-001", limit=5)

        query_kwargs = table.query.call_args[1]
        assert query_kwargs["Limit"] == 5

    def test_get_history_ascending_by_default(self):
        resource, table = _make_mock_resource()
        table.query.return_value = {"Items": []}
        store = PatchHistoryStore(dynamodb_resource=resource)

        store.get_history("doc-001")

        query_kwargs = table.query.call_args[1]
        assert query_kwargs["ScanIndexForward"] is True

    def test_get_history_descending(self):
        resource, table = _make_mock_resource()
        table.query.return_value = {"Items": []}
        store = PatchHistoryStore(dynamodb_resource=resource)

        store.get_history("doc-001", ascending=False)

        query_kwargs = table.query.call_args[1]
        assert query_kwargs["ScanIndexForward"] is False


# ---------------------------------------------------------------------------
# Configuration tests
# ---------------------------------------------------------------------------

class TestPatchHistoryStoreConfig:
    """Constructor configuration — table name, env var."""

    def test_default_table_name(self):
        resource, table = _make_mock_resource()
        PatchHistoryStore(dynamodb_resource=resource)
        resource.Table.assert_called_with("doc-agent-patch-history")

    def test_custom_table_name(self):
        resource, table = _make_mock_resource()
        PatchHistoryStore(table_name="custom-history", dynamodb_resource=resource)
        resource.Table.assert_called_with("custom-history")

    def test_table_name_from_env_var(self):
        resource, table = _make_mock_resource()
        import os
        from unittest.mock import patch as mock_patch
        with mock_patch.dict(os.environ, {"PATCH_HISTORY_TABLE": "env-history"}):
            PatchHistoryStore(dynamodb_resource=resource)
        resource.Table.assert_called_with("env-history")


# ---------------------------------------------------------------------------
# Patch history version tracking tests
# ---------------------------------------------------------------------------

class TestPatchHistoryVersionTracking:
    """Verify version_before / version_after lineage tracking."""

    def test_multiple_patches_track_version_lineage(self):
        """Sequential patches record correct version_before → version_after."""
        resource, table = _make_mock_resource()
        store = PatchHistoryStore(dynamodb_resource=resource)

        patch1 = _sample_patch(patch_id="p-001", version_before=0, version_after=1)
        patch2 = _sample_patch(patch_id="p-002", version_before=1, version_after=2)

        store.record_patch(patch1, user_message_id="msg-001", task_type="discovery")
        store.record_patch(patch2, user_message_id="msg-001", task_type="staffing")

        assert table.put_item.call_count == 2
        item1 = table.put_item.call_args_list[0][1]["Item"]
        item2 = table.put_item.call_args_list[1][1]["Item"]
        assert item1["version_before"] == 0
        assert item1["version_after"] == 1
        assert item2["version_before"] == 1
        assert item2["version_after"] == 2

    def test_record_patch_preserves_all_operations(self):
        """Multiple operations in a single patch are all persisted."""
        resource, table = _make_mock_resource()
        store = PatchHistoryStore(dynamodb_resource=resource)

        patch = Patch(
            patch_id="p-multi",
            doc_id="doc-001",
            agent="cost_agent",
            operations=[
                PatchOperation(op="replace", path="/sections/cost_breakdown/staffing_cost", value=100, source="calculated"),
                PatchOperation(op="replace", path="/staffing_plan/grand_total_cost/calculated", value=100, source="calculated"),
            ],
            version=5,
            version_before=4,
            version_after=5,
        )

        store.record_patch(patch, task_type="calculate_cost")

        item = table.put_item.call_args[1]["Item"]
        assert len(item["operations"]) == 2
        assert item["operations"][0]["path"] == "/sections/cost_breakdown/staffing_cost"
        assert item["operations"][1]["path"] == "/staffing_plan/grand_total_cost/calculated"
