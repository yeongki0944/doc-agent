"""Tests for inference profile fallback mechanism.

Validates:
- Primary profile success returns result without fallback
- Primary failure + configured fallback → uses fallback, marks degraded
- Primary failure + no fallback → raises InferenceProfileUnavailableError
- Both primary and fallback failure → raises InferenceProfileUnavailableError
- Degraded status payload construction
- Orchestrator integration: InferenceProfileUnavailableError → degraded status published

Requirements: 1.7
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from agent.app.parent.inference_fallback import (
    FallbackResult,
    InferenceProfileFallback,
    InferenceProfileUnavailableError,
)
from agent.lib.schema.patch import AgentStatus


# ---------------------------------------------------------------------------
# InferenceProfileFallback unit tests
# ---------------------------------------------------------------------------

class TestInferenceProfileFallback:

    @pytest.mark.asyncio
    async def test_primary_success_returns_primary_result(self):
        fb = InferenceProfileFallback(
            primary="global.anthropic.claude-opus-4-6-v1",
            fallback="fallback-model",
            role="parent",
        )

        async def call_fn(model_id: str):
            return {"output": "hello", "model": model_id}

        result = await fb.invoke(call_fn)

        assert result.response == {"output": "hello", "model": "global.anthropic.claude-opus-4-6-v1"}
        assert result.model_used == "global.anthropic.claude-opus-4-6-v1"
        assert result.is_fallback is False
        assert result.is_degraded is False
        assert fb.is_degraded is False

    @pytest.mark.asyncio
    async def test_primary_failure_with_fallback_uses_fallback(self):
        fb = InferenceProfileFallback(
            primary="primary-model",
            fallback="fallback-model",
            role="child",
        )
        call_count = 0

        async def call_fn(model_id: str):
            nonlocal call_count
            call_count += 1
            if model_id == "primary-model":
                raise RuntimeError("primary unavailable")
            return {"output": "fallback response", "model": model_id}

        result = await fb.invoke(call_fn)

        assert call_count == 2
        assert result.model_used == "fallback-model"
        assert result.is_fallback is True
        assert result.is_degraded is True
        assert result.error_message  # non-empty degraded message
        assert "fallback-model" in result.error_message
        assert fb.is_degraded is True

    @pytest.mark.asyncio
    async def test_primary_failure_no_fallback_raises(self):
        fb = InferenceProfileFallback(
            primary="primary-model",
            fallback="",
            role="parent",
        )

        async def call_fn(model_id: str):
            raise RuntimeError("model unavailable")

        with pytest.raises(InferenceProfileUnavailableError) as exc_info:
            await fb.invoke(call_fn)

        assert exc_info.value.primary == "primary-model"
        assert exc_info.value.fallback is None
        assert fb.is_degraded is True

    @pytest.mark.asyncio
    async def test_both_primary_and_fallback_fail_raises(self):
        fb = InferenceProfileFallback(
            primary="primary-model",
            fallback="fallback-model",
            role="parent",
        )

        async def call_fn(model_id: str):
            raise RuntimeError(f"{model_id} unavailable")

        with pytest.raises(InferenceProfileUnavailableError) as exc_info:
            await fb.invoke(call_fn)

        assert exc_info.value.primary == "primary-model"
        assert exc_info.value.fallback == "fallback-model"
        assert fb.is_degraded is True

    @pytest.mark.asyncio
    async def test_primary_success_clears_degraded_state(self):
        fb = InferenceProfileFallback(
            primary="primary-model",
            fallback="fallback-model",
            role="parent",
        )
        # Simulate prior degraded state
        fb._degraded = True

        async def call_fn(model_id: str):
            return "ok"

        result = await fb.invoke(call_fn)

        assert result.is_degraded is False
        assert fb.is_degraded is False

    def test_build_degraded_status_payload(self):
        fb = InferenceProfileFallback(
            primary="primary-model",
            fallback="fallback-model",
            role="parent",
        )

        payload = fb.build_degraded_status_payload("doc-001")

        assert payload["doc_id"] == "doc-001"
        assert payload["status"] == "degraded"
        assert payload["role"] == "parent"
        assert "message" in payload

    def test_default_fallback_is_empty(self):
        fb = InferenceProfileFallback(primary="primary-model", role="test")
        assert fb.fallback == ""
        assert fb.is_degraded is False


# ---------------------------------------------------------------------------
# InferenceProfileUnavailableError tests
# ---------------------------------------------------------------------------

class TestInferenceProfileUnavailableError:

    def test_error_message_with_fallback(self):
        cause = RuntimeError("timeout")
        err = InferenceProfileUnavailableError(
            primary="primary-model",
            fallback="fallback-model",
            cause=cause,
        )
        assert "primary-model" in str(err)
        assert "fallback-model" in str(err)
        assert err.cause is cause

    def test_error_message_without_fallback(self):
        cause = RuntimeError("timeout")
        err = InferenceProfileUnavailableError(
            primary="primary-model",
            fallback=None,
            cause=cause,
        )
        assert "primary-model" in str(err)
        assert "no fallback" in str(err)


# ---------------------------------------------------------------------------
# FallbackResult tests
# ---------------------------------------------------------------------------

class TestFallbackResult:

    def test_default_values(self):
        r = FallbackResult()
        assert r.response is None
        assert r.model_used == ""
        assert r.is_fallback is False
        assert r.is_degraded is False
        assert r.error_message == ""


# ---------------------------------------------------------------------------
# Runtime env var tests for fallback models
# ---------------------------------------------------------------------------

class TestFallbackEnvVars:

    def test_default_parent_fallback_is_empty(self):
        from agent.app.parent.runtime import PARENT_MODEL_FALLBACK
        assert PARENT_MODEL_FALLBACK == ""

    def test_default_child_fallback_is_empty(self):
        from agent.app.parent.runtime import CHILD_MODEL_FALLBACK
        assert CHILD_MODEL_FALLBACK == ""

    def test_parent_fallback_env_override(self):
        with patch.dict(os.environ, {"PARENT_MODEL_FALLBACK": "custom-parent-fallback"}):
            import importlib
            import agent.app.parent.runtime as runtime_mod
            importlib.reload(runtime_mod)
            assert runtime_mod.PARENT_MODEL_FALLBACK == "custom-parent-fallback"
            importlib.reload(runtime_mod)

    def test_child_fallback_env_override(self):
        with patch.dict(os.environ, {"CHILD_MODEL_FALLBACK": "custom-child-fallback"}):
            import importlib
            import agent.app.parent.runtime as runtime_mod
            importlib.reload(runtime_mod)
            assert runtime_mod.CHILD_MODEL_FALLBACK == "custom-child-fallback"
            importlib.reload(runtime_mod)


# ---------------------------------------------------------------------------
# Orchestrator integration: degraded status on inference failure
# ---------------------------------------------------------------------------

class TestOrchestratorDegradedStatus:

    @pytest.mark.asyncio
    async def test_inference_unavailable_publishes_degraded_status(self):
        from agent.app.parent.orchestrator import ParentOrchestrator
        from agent.lib.storage.dynamodb import DocumentStore

        store = DocumentStore()
        orch = ParentOrchestrator(document_store=store, memory=None)

        # Force handle_message to raise InferenceProfileUnavailableError
        # by making _fetch_document_state raise it
        async def broken_fetch(doc_id):
            raise InferenceProfileUnavailableError(
                primary="primary-model",
                fallback=None,
                cause=RuntimeError("unavailable"),
            )

        orch._fetch_document_state = broken_fetch

        plan = await orch.handle_message("doc-001", "test", [])

        # Should return degraded message
        assert "inference profile" in plan.chat_response

        # Should have published degraded status
        statuses = [s["status"] for s in orch._status_log]
        assert "degraded" in statuses

        # Should return to IDLE
        from agent.app.parent.orchestrator import OrchestratorState
        assert orch.state == OrchestratorState.IDLE

    @pytest.mark.asyncio
    async def test_degraded_status_payload_contains_doc_id(self):
        from agent.app.parent.orchestrator import ParentOrchestrator
        from agent.lib.storage.dynamodb import DocumentStore

        store = DocumentStore()
        orch = ParentOrchestrator(document_store=store, memory=None)

        async def broken_fetch(doc_id):
            raise InferenceProfileUnavailableError(
                primary="test-primary",
                fallback="test-fallback",
                cause=RuntimeError("unavailable"),
            )

        orch._fetch_document_state = broken_fetch

        await orch.handle_message("doc-xyz", "test", [])

        degraded_entries = [
            s for s in orch._status_log if s["status"] == "degraded"
        ]
        assert len(degraded_entries) == 1
        assert degraded_entries[0]["doc_id"] == "doc-xyz"
        assert degraded_entries[0]["primary"] == "test-primary"
        assert degraded_entries[0]["fallback"] == "test-fallback"


# ---------------------------------------------------------------------------
# AgentStatus.degraded enum value test
# ---------------------------------------------------------------------------

class TestAgentStatusDegraded:

    def test_degraded_enum_exists(self):
        assert hasattr(AgentStatus, "degraded")
        assert AgentStatus.degraded.value == "degraded"

    def test_all_statuses(self):
        values = {s.value for s in AgentStatus}
        assert values == {"processing", "idle", "error", "degraded"}


# ---------------------------------------------------------------------------
# Recovery after degraded state
# ---------------------------------------------------------------------------

class TestFallbackRecovery:

    @pytest.mark.asyncio
    async def test_degraded_then_primary_recovers(self):
        """After fallback is used, a subsequent primary success should clear degraded."""
        fb = InferenceProfileFallback(
            primary="primary-model",
            fallback="fallback-model",
            role="parent",
        )
        call_count = 0

        async def call_fn(model_id: str):
            nonlocal call_count
            call_count += 1
            if call_count <= 2 and model_id == "primary-model":
                raise RuntimeError("primary unavailable")
            return {"output": "ok", "model": model_id}

        # First call: primary fails → fallback used → degraded
        result1 = await fb.invoke(call_fn)
        assert result1.is_degraded is True
        assert result1.model_used == "fallback-model"
        assert fb.is_degraded is True

        # Second call: primary succeeds → degraded cleared
        result2 = await fb.invoke(call_fn)
        assert result2.is_degraded is False
        assert result2.model_used == "primary-model"
        assert fb.is_degraded is False

    @pytest.mark.asyncio
    async def test_fallback_empty_string_vs_none(self):
        """Empty string fallback should behave the same as no fallback."""
        fb_empty = InferenceProfileFallback(primary="p", fallback="", role="test")
        fb_default = InferenceProfileFallback(primary="p", role="test")

        assert fb_empty.fallback == ""
        assert fb_default.fallback == ""

        async def failing_fn(model_id: str):
            raise RuntimeError("fail")

        with pytest.raises(InferenceProfileUnavailableError) as exc1:
            await fb_empty.invoke(failing_fn)
        assert exc1.value.fallback is None

        with pytest.raises(InferenceProfileUnavailableError) as exc2:
            await fb_default.invoke(failing_fn)
        assert exc2.value.fallback is None


# ---------------------------------------------------------------------------
# Orchestrator fallback instances
# ---------------------------------------------------------------------------

class TestOrchestratorFallbackInstances:

    def test_orchestrator_has_parent_and_child_fallback(self):
        from agent.app.parent.orchestrator import ParentOrchestrator
        from agent.lib.storage.dynamodb import DocumentStore

        store = DocumentStore()
        orch = ParentOrchestrator(document_store=store, memory=None)

        assert orch.parent_fallback is not None
        assert orch.child_fallback is not None
        assert orch.parent_fallback.role == "parent"
        assert orch.child_fallback.role == "child"

    def test_orchestrator_fallback_uses_correct_models(self):
        from agent.app.parent.orchestrator import ParentOrchestrator
        from agent.app.parent.runtime import PARENT_MODEL, CHILD_MODEL
        from agent.lib.storage.dynamodb import DocumentStore

        store = DocumentStore()
        orch = ParentOrchestrator(document_store=store, memory=None)

        assert orch.parent_fallback.primary == PARENT_MODEL
        assert orch.child_fallback.primary == CHILD_MODEL
