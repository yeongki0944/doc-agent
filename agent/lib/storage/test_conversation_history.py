"""Tests for ConversationHistoryStore — mocked boto3 DynamoDB resource."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agent.lib.storage.conversation_history import ConversationHistoryStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_resource() -> tuple[MagicMock, MagicMock]:
    """Create a mock boto3 DynamoDB resource with a mock table."""
    resource = MagicMock()
    table = MagicMock()
    resource.Table.return_value = table
    return resource, table


def _sample_messages(n: int = 5) -> list[dict]:
    msgs = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "agent"
        msgs.append({
            "id": f"msg-{i:03d}",
            "role": role,
            "content": f"Message {i}",
            "timestamp": f"2025-07-01T10:{i:02d}:00Z",
        })
    return msgs


# ---------------------------------------------------------------------------
# Save / Load round-trip tests
# ---------------------------------------------------------------------------

class TestConversationHistorySave:
    """save() — table.put_item with correct structure."""

    def test_save_writes_correct_item(self):
        resource, table = _make_mock_resource()
        store = ConversationHistoryStore(dynamodb_resource=resource)

        messages = _sample_messages(3)
        result = store.save("doc-001", "sess-001", messages)

        table.put_item.assert_called_once()
        item = table.put_item.call_args[1]["Item"]
        assert item["document_id"] == "doc-001"
        assert item["session_id"] == "sess-001"
        assert item["total_count"] == 3
        assert item["bounded_window"] == 20
        assert len(item["messages"]) == 3

    def test_save_custom_bounded_window(self):
        resource, table = _make_mock_resource()
        store = ConversationHistoryStore(dynamodb_resource=resource)

        messages = _sample_messages(5)
        result = store.save("doc-001", "sess-001", messages, bounded_window=10)

        item = table.put_item.call_args[1]["Item"]
        assert item["bounded_window"] == 10

    def test_save_returns_item_dict(self):
        resource, table = _make_mock_resource()
        store = ConversationHistoryStore(dynamodb_resource=resource)

        messages = _sample_messages(2)
        result = store.save("doc-001", "sess-001", messages)

        assert result["document_id"] == "doc-001"
        assert result["session_id"] == "sess-001"
        assert result["total_count"] == 2
        assert "updated_at" in result

    def test_save_empty_messages(self):
        resource, table = _make_mock_resource()
        store = ConversationHistoryStore(dynamodb_resource=resource)

        result = store.save("doc-001", "sess-001", [])

        item = table.put_item.call_args[1]["Item"]
        assert item["total_count"] == 0
        assert item["messages"] == []


class TestConversationHistoryLoad:
    """load() — get_item or query depending on session_id."""

    def test_load_with_session_id_uses_get_item(self):
        resource, table = _make_mock_resource()
        messages = _sample_messages(3)
        table.get_item.return_value = {
            "Item": {
                "document_id": "doc-001",
                "session_id": "sess-001",
                "messages": messages,
                "bounded_window": 20,
                "total_count": 3,
            }
        }

        store = ConversationHistoryStore(dynamodb_resource=resource)
        result = store.load("doc-001", "sess-001")

        table.get_item.assert_called_once_with(
            Key={"document_id": "doc-001", "session_id": "sess-001"}
        )
        assert result is not None
        assert result["total_count"] == 3
        assert len(result["messages"]) == 3

    def test_load_without_session_id_queries_latest(self):
        resource, table = _make_mock_resource()
        messages = _sample_messages(2)
        table.query.return_value = {
            "Items": [{
                "document_id": "doc-001",
                "session_id": "sess-latest",
                "messages": messages,
                "bounded_window": 20,
                "total_count": 2,
            }]
        }

        store = ConversationHistoryStore(dynamodb_resource=resource)
        result = store.load("doc-001")

        table.query.assert_called_once()
        assert result is not None
        assert result["session_id"] == "sess-latest"

    def test_load_returns_none_when_not_found(self):
        resource, table = _make_mock_resource()
        table.get_item.return_value = {}

        store = ConversationHistoryStore(dynamodb_resource=resource)
        result = store.load("doc-001", "sess-missing")

        assert result is None

    def test_load_returns_none_when_no_sessions_exist(self):
        resource, table = _make_mock_resource()
        table.query.return_value = {"Items": []}

        store = ConversationHistoryStore(dynamodb_resource=resource)
        result = store.load("doc-nonexistent")

        assert result is None


class TestConversationHistoryLoadBounded:
    """load_bounded() — returns only the last N messages."""

    def test_load_bounded_returns_last_n_messages(self):
        resource, table = _make_mock_resource()
        messages = _sample_messages(30)
        table.get_item.return_value = {
            "Item": {
                "document_id": "doc-001",
                "session_id": "sess-001",
                "messages": messages,
                "bounded_window": 20,
                "total_count": 30,
            }
        }

        store = ConversationHistoryStore(dynamodb_resource=resource)
        result = store.load_bounded("doc-001", "sess-001")

        assert len(result) == 20
        # Should be the last 20 messages
        assert result[0]["id"] == "msg-010"
        assert result[-1]["id"] == "msg-029"

    def test_load_bounded_returns_all_when_fewer_than_window(self):
        resource, table = _make_mock_resource()
        messages = _sample_messages(5)
        table.get_item.return_value = {
            "Item": {
                "document_id": "doc-001",
                "session_id": "sess-001",
                "messages": messages,
                "bounded_window": 20,
                "total_count": 5,
            }
        }

        store = ConversationHistoryStore(dynamodb_resource=resource)
        result = store.load_bounded("doc-001", "sess-001")

        assert len(result) == 5

    def test_load_bounded_returns_empty_when_not_found(self):
        resource, table = _make_mock_resource()
        table.get_item.return_value = {}

        store = ConversationHistoryStore(dynamodb_resource=resource)
        result = store.load_bounded("doc-001", "sess-missing")

        assert result == []


class TestConversationHistoryRoundTrip:
    """Save then load — verify data integrity."""

    def test_save_and_load_roundtrip(self):
        """Save messages, then load them back — verify structure matches."""
        resource, table = _make_mock_resource()
        store = ConversationHistoryStore(dynamodb_resource=resource)

        messages = _sample_messages(10)
        store.save("doc-001", "sess-001", messages, bounded_window=5)

        # Capture what was written
        saved_item = table.put_item.call_args[1]["Item"]

        # Mock the load to return what was saved
        table.get_item.return_value = {"Item": saved_item}
        loaded = store.load("doc-001", "sess-001")

        assert loaded is not None
        assert loaded["document_id"] == "doc-001"
        assert loaded["session_id"] == "sess-001"
        assert loaded["total_count"] == 10
        assert loaded["bounded_window"] == 5
        assert len(loaded["messages"]) == 10

    def test_save_and_load_bounded_roundtrip(self):
        """Save 25 messages with window=10, load_bounded returns last 10."""
        resource, table = _make_mock_resource()
        store = ConversationHistoryStore(dynamodb_resource=resource)

        messages = _sample_messages(25)
        store.save("doc-001", "sess-001", messages, bounded_window=10)

        saved_item = table.put_item.call_args[1]["Item"]
        table.get_item.return_value = {"Item": saved_item}

        bounded = store.load_bounded("doc-001", "sess-001")
        assert len(bounded) == 10
        assert bounded[0]["id"] == "msg-015"
        assert bounded[-1]["id"] == "msg-024"


class TestConversationHistoryDelete:
    """delete() — removes a specific entry."""

    def test_delete_calls_delete_item(self):
        resource, table = _make_mock_resource()
        store = ConversationHistoryStore(dynamodb_resource=resource)

        store.delete("doc-001", "sess-001")

        table.delete_item.assert_called_once_with(
            Key={"document_id": "doc-001", "session_id": "sess-001"}
        )


class TestConversationHistoryConfig:
    """Constructor configuration — table name, env var."""

    def test_default_table_name(self):
        resource, table = _make_mock_resource()
        ConversationHistoryStore(dynamodb_resource=resource)
        resource.Table.assert_called_with("doc-agent-conversation-history")

    def test_custom_table_name(self):
        resource, table = _make_mock_resource()
        ConversationHistoryStore(
            table_name="my-history-table", dynamodb_resource=resource
        )
        resource.Table.assert_called_with("my-history-table")

    def test_table_name_from_env_var(self):
        resource, table = _make_mock_resource()
        from unittest.mock import patch
        with patch.dict("os.environ", {"CONVERSATION_HISTORY_TABLE": "env-history"}):
            ConversationHistoryStore(dynamodb_resource=resource)
        resource.Table.assert_called_with("env-history")
