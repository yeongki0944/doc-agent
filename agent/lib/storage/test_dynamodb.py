"""Tests for DynamoDBDocumentStore — mocked boto3 DynamoDB resource."""

from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from agent.lib.schema.document_state import DocumentState
from agent.lib.storage.dynamodb import (
    DynamoDBDocumentStore,
    DocumentNotFoundError,
    DocumentStore,
    VersionConflictError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_resource() -> MagicMock:
    """Create a mock boto3 DynamoDB resource with a mock table."""
    resource = MagicMock()
    table = MagicMock()
    resource.Table.return_value = table

    # Wire up ConditionalCheckFailedException on the client
    exc_cls = type("ConditionalCheckFailedException", (Exception,), {})
    resource.meta.client.exceptions.ConditionalCheckFailedException = exc_cls

    return resource, table, exc_cls


def _sample_doc(doc_id: str = "doc-001", version: int = 0) -> DocumentState:
    return DocumentState(document_id=doc_id, version=version)


def _iter_values(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _iter_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_values(item)
    else:
        yield value


# ---------------------------------------------------------------------------
# DynamoDBDocumentStore tests
# ---------------------------------------------------------------------------

class TestDynamoDBDocumentStoreGet:
    """get() — table.get_item with Key={"document_id": ...}."""

    def test_get_returns_document_state(self):
        resource, table, _ = _make_mock_resource()
        doc = _sample_doc()
        table.get_item.return_value = {"Item": doc.model_dump(mode="json")}

        store = DynamoDBDocumentStore(dynamodb_resource=resource)
        result = store.get("doc-001")

        table.get_item.assert_called_once_with(Key={"document_id": "doc-001"})
        assert isinstance(result, DocumentState)
        assert result.document_id == "doc-001"

    def test_get_raises_not_found_when_item_missing(self):
        resource, table, _ = _make_mock_resource()
        table.get_item.return_value = {}

        store = DynamoDBDocumentStore(dynamodb_resource=resource)
        with pytest.raises(DocumentNotFoundError, match="doc-999"):
            store.get("doc-999")


class TestDynamoDBDocumentStorePut:
    """put() — unconditional table.put_item."""

    def test_put_calls_put_item_and_updates_timestamp(self):
        resource, table, _ = _make_mock_resource()
        store = DynamoDBDocumentStore(dynamodb_resource=resource)

        doc = _sample_doc()
        before = datetime.now(timezone.utc)
        result = store.put(doc)

        table.put_item.assert_called_once()
        item_arg = table.put_item.call_args[1]["Item"]
        assert item_arg["document_id"] == "doc-001"
        assert result.updated_at >= before

    def test_put_converts_floats_to_decimal(self):
        resource, table, _ = _make_mock_resource()
        store = DynamoDBDocumentStore(dynamodb_resource=resource)

        doc = _sample_doc()
        doc.sections.cost_breakdown.funding_calculation.funding_cap = 125000.5
        store.put(doc)

        item_arg = table.put_item.call_args[1]["Item"]
        values = list(_iter_values(item_arg))
        assert Decimal("125000.5") in values
        assert not any(isinstance(value, float) for value in values)


class TestDynamoDBDocumentStoreUpdate:
    """update() — optimistic locking via ConditionExpression."""

    def test_update_increments_version_and_writes(self):
        resource, table, _ = _make_mock_resource()
        store = DynamoDBDocumentStore(dynamodb_resource=resource)

        doc = _sample_doc(version=5)
        result = store.update(doc, expected_version=5)

        assert result.version == 6
        call_kwargs = table.put_item.call_args[1]
        assert "ConditionExpression" in call_kwargs
        assert call_kwargs["Item"]["version"] == 6

    def test_update_raises_version_conflict_on_condition_failure(self):
        resource, table, exc_cls = _make_mock_resource()
        table.put_item.side_effect = exc_cls("condition failed")

        store = DynamoDBDocumentStore(dynamodb_resource=resource)
        doc = _sample_doc(version=3)

        with pytest.raises(VersionConflictError, match="Version conflict"):
            store.update(doc, expected_version=3)

    def test_update_refreshes_updated_at(self):
        resource, table, _ = _make_mock_resource()
        store = DynamoDBDocumentStore(dynamodb_resource=resource)

        doc = _sample_doc()
        before = datetime.now(timezone.utc)
        result = store.update(doc, expected_version=0)

        assert result.updated_at >= before


class TestDynamoDBDocumentStoreDeleteExists:
    """delete() and exists() operations."""

    def test_delete_calls_delete_item(self):
        resource, table, _ = _make_mock_resource()
        store = DynamoDBDocumentStore(dynamodb_resource=resource)

        store.delete("doc-001")
        table.delete_item.assert_called_once_with(Key={"document_id": "doc-001"})

    def test_exists_returns_true_when_item_present(self):
        resource, table, _ = _make_mock_resource()
        table.get_item.return_value = {"Item": {"document_id": "doc-001"}}

        store = DynamoDBDocumentStore(dynamodb_resource=resource)
        assert store.exists("doc-001") is True

    def test_exists_returns_false_when_item_absent(self):
        resource, table, _ = _make_mock_resource()
        table.get_item.return_value = {}

        store = DynamoDBDocumentStore(dynamodb_resource=resource)
        assert store.exists("doc-999") is False


class TestDynamoDBDocumentStoreConfig:
    """Constructor configuration — table name, env var, region."""

    def test_default_table_name(self):
        resource, table, _ = _make_mock_resource()
        store = DynamoDBDocumentStore(dynamodb_resource=resource)
        resource.Table.assert_called_with("doc-agent-documents")

    def test_custom_table_name(self):
        resource, table, _ = _make_mock_resource()
        store = DynamoDBDocumentStore(
            table_name="my-custom-table", dynamodb_resource=resource
        )
        resource.Table.assert_called_with("my-custom-table")

    def test_table_name_from_env_var(self):
        resource, table, _ = _make_mock_resource()
        with patch.dict("os.environ", {"DYNAMODB_TABLE": "env-table"}):
            store = DynamoDBDocumentStore(dynamodb_resource=resource)
        resource.Table.assert_called_with("env-table")

    def test_explicit_table_name_overrides_env(self):
        resource, table, _ = _make_mock_resource()
        with patch.dict("os.environ", {"DYNAMODB_TABLE": "env-table"}):
            store = DynamoDBDocumentStore(
                table_name="explicit-table", dynamodb_resource=resource
            )
        resource.Table.assert_called_with("explicit-table")


class TestConcurrentUpdateScenarios:
    """Simulate concurrent update scenarios with optimistic locking."""

    def test_concurrent_updates_second_writer_gets_conflict(self):
        """Two writers read the same version; first succeeds, second fails."""
        resource, table, exc_cls = _make_mock_resource()
        store = DynamoDBDocumentStore(dynamodb_resource=resource)

        # First writer succeeds
        doc_a = _sample_doc(version=5)
        result_a = store.update(doc_a, expected_version=5)
        assert result_a.version == 6

        # Second writer tries with same expected_version=5 but DynamoDB rejects
        table.put_item.side_effect = exc_cls("condition failed")
        doc_b = _sample_doc(version=5)
        with pytest.raises(VersionConflictError, match="Version conflict"):
            store.update(doc_b, expected_version=5)

    def test_sequential_updates_succeed_with_correct_versions(self):
        """Sequential updates with correct version tracking succeed."""
        resource, table, _ = _make_mock_resource()
        store = DynamoDBDocumentStore(dynamodb_resource=resource)

        doc = _sample_doc(version=0)
        result1 = store.update(doc, expected_version=0)
        assert result1.version == 1

        result2 = store.update(result1, expected_version=1)
        assert result2.version == 2

        result3 = store.update(result2, expected_version=2)
        assert result3.version == 3

    def test_update_new_document_without_existing_record(self):
        """Updating a document that doesn't exist yet succeeds if no condition conflict."""
        resource, table, _ = _make_mock_resource()
        store = DynamoDBDocumentStore(dynamodb_resource=resource)

        doc = _sample_doc(version=0)
        result = store.update(doc, expected_version=0)
        assert result.version == 1
        table.put_item.assert_called_once()


class TestInMemoryDocumentStoreStillWorks:
    """Sanity check: the original in-memory DocumentStore is unchanged."""

    def test_put_get_roundtrip(self):
        store = DocumentStore()
        doc = _sample_doc()
        store.put(doc)
        result = store.get("doc-001")
        assert result.document_id == "doc-001"

    def test_update_optimistic_lock(self):
        store = DocumentStore()
        doc = _sample_doc()
        store.put(doc)
        updated = store.update(doc, expected_version=0)
        assert updated.version == 1

    def test_update_version_conflict(self):
        store = DocumentStore()
        doc = _sample_doc()
        store.put(doc)
        with pytest.raises(VersionConflictError):
            store.update(doc, expected_version=99)

    def test_get_raises_not_found_for_missing_document(self):
        store = DocumentStore()
        with pytest.raises(DocumentNotFoundError, match="doc-missing"):
            store.get("doc-missing")

    def test_concurrent_in_memory_updates_second_fails(self):
        """Simulate concurrent updates: first succeeds, second gets conflict."""
        store = DocumentStore()
        doc = _sample_doc(version=0)
        store.put(doc)

        # Both "readers" see version 0
        doc_a = store.get("doc-001")
        doc_b = store.get("doc-001")

        # First writer succeeds
        store.update(doc_a, expected_version=0)

        # Second writer fails — stored version is now 1
        with pytest.raises(VersionConflictError):
            store.update(doc_b, expected_version=0)
