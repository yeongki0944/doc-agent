"""Tests for AgentCoreMemory wrapper — mocked boto3 bedrock-agentcore client.

Covers:
- Initialization and client creation
- store_session_event, store_long_term_facts, retrieve_customer_context
- Degraded mode: all API calls wrapped with try/except, on_degraded callback
  invoked on failure, default values returned so system continues

Requirements: 2.1, 2.2, 2.3, 2.5
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent.lib.memory.agentcore_memory import AgentCoreMemory

MEMORY_ID = "mem-test-001"
REGION = "ap-northeast-2"


@pytest.fixture()
def mock_client():
    with patch("agent.lib.memory.agentcore_memory.boto3") as mock_boto3:
        client = MagicMock()
        mock_boto3.client.return_value = client
        yield client


@pytest.fixture()
def memory(mock_client):
    return AgentCoreMemory(memory_id=MEMORY_ID, region=REGION)


# --- Initialization ---


def test_init_creates_bedrock_agentcore_client():
    with patch("agent.lib.memory.agentcore_memory.boto3") as mock_boto3:
        mem = AgentCoreMemory(memory_id=MEMORY_ID, region=REGION)
        mock_boto3.client.assert_called_once_with(
            "bedrock-agentcore", region_name=REGION
        )
        assert mem.memory_id == MEMORY_ID


def test_init_default_region():
    with patch("agent.lib.memory.agentcore_memory.boto3") as mock_boto3:
        AgentCoreMemory(memory_id=MEMORY_ID)
        mock_boto3.client.assert_called_once_with(
            "bedrock-agentcore", region_name="ap-northeast-2"
        )


def test_init_on_degraded_default_is_none():
    with patch("agent.lib.memory.agentcore_memory.boto3"):
        mem = AgentCoreMemory(memory_id=MEMORY_ID)
        assert mem.on_degraded is None


# --- store_session_event ---


def test_store_session_event_calls_create_memory_event(memory, mock_client):
    result = memory.store_session_event(
        session_id="sess-001", actor_id="user-abc", content="Hello agent"
    )

    mock_client.create_memory_event.assert_called_once_with(
        memoryId=MEMORY_ID,
        actorId="user-abc",
        sessionId="sess-001",
        messages=[{"role": "user", "content": "Hello agent"}],
    )
    assert result is True


# --- store_long_term_facts ---


def test_store_long_term_facts_calls_batch_create(memory, mock_client):
    facts = [
        {"value": "Prefers ap-northeast-2 region"},
        {"value": "Requires HIPAA compliance"},
    ]
    result = memory.store_long_term_facts(customer="acme-corp", facts=facts)

    mock_client.batch_create_memory_records.assert_called_once_with(
        memoryId=MEMORY_ID,
        records=[
            {
                "content": {"text": "Prefers ap-northeast-2 region"},
                "namespace": "/customers/acme-corp/",
            },
            {
                "content": {"text": "Requires HIPAA compliance"},
                "namespace": "/customers/acme-corp/",
            },
        ],
    )
    assert result is True


def test_store_long_term_facts_empty_list(memory, mock_client):
    result = memory.store_long_term_facts(customer="acme-corp", facts=[])

    mock_client.batch_create_memory_records.assert_called_once_with(
        memoryId=MEMORY_ID,
        records=[],
    )
    assert result is True


# --- retrieve_customer_context ---


def test_retrieve_customer_context_returns_records(memory, mock_client):
    mock_client.retrieve_memory_records.return_value = {
        "records": [
            {"content": {"text": "Uses EKS"}, "score": 0.95},
            {"content": {"text": "Seoul region only"}, "score": 0.88},
        ]
    }

    result = memory.retrieve_customer_context(
        customer="acme-corp", query="infrastructure preferences"
    )

    mock_client.retrieve_memory_records.assert_called_once_with(
        memoryId=MEMORY_ID,
        query="infrastructure preferences",
        namespace="/customers/acme-corp/",
    )
    assert len(result) == 2
    assert result[0]["content"]["text"] == "Uses EKS"


def test_retrieve_customer_context_empty_response(memory, mock_client):
    mock_client.retrieve_memory_records.return_value = {}

    result = memory.retrieve_customer_context(
        customer="new-customer", query="anything"
    )

    assert result == []


def test_retrieve_customer_context_no_records_key(memory, mock_client):
    mock_client.retrieve_memory_records.return_value = {"metadata": {}}

    result = memory.retrieve_customer_context(
        customer="new-customer", query="anything"
    )

    assert result == []


# ---------------------------------------------------------------------------
# Degraded mode tests (Req 2.5)
# ---------------------------------------------------------------------------


class TestDegradedMode:
    """Memory API failures should not crash the system.

    All API calls are wrapped with try/except via _safe_call.
    On failure: default value returned, on_degraded callback invoked.
    """

    def test_store_session_event_returns_false_on_failure(self, memory, mock_client):
        mock_client.create_memory_event.side_effect = RuntimeError("API down")

        result = memory.store_session_event(
            session_id="s1", actor_id="a1", content="hi"
        )

        assert result is False

    def test_store_long_term_facts_returns_false_on_failure(self, memory, mock_client):
        mock_client.batch_create_memory_records.side_effect = RuntimeError("timeout")

        result = memory.store_long_term_facts(
            customer="acme", facts=[{"value": "fact1"}]
        )

        assert result is False

    def test_retrieve_customer_context_returns_empty_on_failure(self, memory, mock_client):
        mock_client.retrieve_memory_records.side_effect = RuntimeError("network error")

        result = memory.retrieve_customer_context(customer="acme", query="test")

        assert result == []

    def test_on_degraded_callback_invoked_on_store_session_failure(self, mock_client):
        callback = MagicMock()
        with patch("agent.lib.memory.agentcore_memory.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_client
            mem = AgentCoreMemory(
                memory_id=MEMORY_ID, region=REGION, on_degraded=callback
            )

        mock_client.create_memory_event.side_effect = RuntimeError("fail")

        mem.store_session_event(session_id="s1", actor_id="a1", content="hi")

        callback.assert_called_once()
        args = callback.call_args[0]
        assert args[0] == "store_session_event"
        assert isinstance(args[1], RuntimeError)

    def test_on_degraded_callback_invoked_on_store_facts_failure(self, mock_client):
        callback = MagicMock()
        with patch("agent.lib.memory.agentcore_memory.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_client
            mem = AgentCoreMemory(
                memory_id=MEMORY_ID, region=REGION, on_degraded=callback
            )

        mock_client.batch_create_memory_records.side_effect = RuntimeError("fail")

        mem.store_long_term_facts(customer="acme", facts=[{"value": "x"}])

        callback.assert_called_once()
        assert callback.call_args[0][0] == "store_long_term_facts"

    def test_on_degraded_callback_invoked_on_retrieve_failure(self, mock_client):
        callback = MagicMock()
        with patch("agent.lib.memory.agentcore_memory.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_client
            mem = AgentCoreMemory(
                memory_id=MEMORY_ID, region=REGION, on_degraded=callback
            )

        mock_client.retrieve_memory_records.side_effect = RuntimeError("fail")

        mem.retrieve_customer_context(customer="acme", query="q")

        callback.assert_called_once()
        assert callback.call_args[0][0] == "retrieve_customer_context"

    def test_broken_on_degraded_callback_does_not_crash(self, mock_client):
        """Even if the callback itself raises, the system should not crash."""
        def bad_callback(method, exc):
            raise ValueError("callback broken")

        with patch("agent.lib.memory.agentcore_memory.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_client
            mem = AgentCoreMemory(
                memory_id=MEMORY_ID, region=REGION, on_degraded=bad_callback
            )

        mock_client.create_memory_event.side_effect = RuntimeError("API fail")

        # Should not raise even though callback is broken
        result = mem.store_session_event(session_id="s1", actor_id="a1", content="hi")
        assert result is False

    def test_no_callback_still_returns_default_on_failure(self, memory, mock_client):
        """Without on_degraded callback, failures still return defaults."""
        assert memory.on_degraded is None

        mock_client.create_memory_event.side_effect = RuntimeError("fail")
        assert memory.store_session_event("s1", "a1", "hi") is False

        mock_client.retrieve_memory_records.side_effect = RuntimeError("fail")
        assert memory.retrieve_customer_context("c", "q") == []
