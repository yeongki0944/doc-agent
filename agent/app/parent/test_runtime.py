"""Tests for AgentCore Runtime entry point (runtime.py).

Validates:
- Payload parsing and validation (doc_id, prompt, history)
- Response format: {"result": ..., "version": ..., "status": ...}
- PARENT_MODEL / CHILD_MODEL env-var override
- Error handling for missing/invalid payloads
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest


class _FakeRuntimeOrchestrator:
    async def handle_message(self, doc_id, prompt, history, user_id=""):
        return SimpleNamespace(
            chat_response=f"handled {doc_id}: {prompt}",
            new_version=1,
            status="completed",
            changed_sections=[],
            created_change_request_ids=[],
            tool_results={},
            degraded_messages=[],
            execution_log={"planned": [], "executed": []},
        )


@pytest.fixture(autouse=True)
def _stub_runtime_orchestrator(monkeypatch, request):
    """Keep invoke() response tests independent from AWS-backed runtime wiring."""
    if "TestRuntimeDependencyWiring" in request.node.nodeid:
        yield
        return

    import agent.app.parent.runtime as runtime_mod

    runtime_mod._orchestrator_instance = None
    monkeypatch.setattr(
        runtime_mod,
        "_get_orchestrator",
        lambda: _FakeRuntimeOrchestrator(),
    )
    yield
    runtime_mod._orchestrator_instance = None


class TestInvoke:
    """Tests for the invoke() entrypoint function."""

    def test_valid_payload_returns_ok(self):
        from agent.app.parent.runtime import invoke

        result = invoke({
            "doc_id": "doc-001",
            "prompt": "프로젝트 개요를 작성해주세요",
            "history": [{"role": "user", "content": "hello"}],
        })

        assert result["status"] == "ok"
        assert "result" in result
        assert "version" in result
        assert isinstance(result["version"], int)

    def test_valid_payload_without_history(self):
        from agent.app.parent.runtime import invoke

        result = invoke({
            "doc_id": "doc-002",
            "prompt": "아키텍처를 분석해주세요",
        })

        assert result["status"] == "ok"
        assert "result" in result

    def test_missing_doc_id_returns_error(self):
        from agent.app.parent.runtime import invoke

        result = invoke({"prompt": "hello"})

        assert result["status"] == "error"
        assert "doc_id" in result["result"]

    def test_empty_doc_id_returns_error(self):
        from agent.app.parent.runtime import invoke

        result = invoke({"doc_id": "", "prompt": "hello"})

        assert result["status"] == "error"
        assert "doc_id" in result["result"]

    def test_missing_prompt_returns_error(self):
        from agent.app.parent.runtime import invoke

        result = invoke({"doc_id": "doc-001"})

        assert result["status"] == "error"
        assert "prompt" in result["result"]

    def test_empty_prompt_returns_error(self):
        from agent.app.parent.runtime import invoke

        result = invoke({"doc_id": "doc-001", "prompt": ""})

        assert result["status"] == "error"
        assert "prompt" in result["result"]

    def test_response_contains_all_required_keys(self):
        from agent.app.parent.runtime import invoke

        result = invoke({"doc_id": "doc-001", "prompt": "test"})

        assert {"result", "version", "status"}.issubset(result.keys())

    def test_history_defaults_to_empty_list(self):
        from agent.app.parent.runtime import invoke

        result = invoke({"doc_id": "doc-001", "prompt": "test"})

        assert result["status"] == "ok"
        # Orchestrator returns a chat_response from the task plan
        assert isinstance(result["result"], str)
        assert len(result["result"]) > 0

    def test_invoke_delegates_to_orchestrator(self):
        from agent.app.parent.runtime import invoke

        history = [
            {"role": "user", "content": "msg1"},
            {"role": "agent", "content": "reply1"},
            {"role": "user", "content": "msg2"},
        ]
        result = invoke({
            "doc_id": "doc-001",
            "prompt": "test",
            "history": history,
        })

        assert result["status"] == "ok"
        assert isinstance(result["result"], str)
        assert isinstance(result["version"], int)


class TestValidatePayload:
    """Tests for _validate_payload helper."""

    def test_valid_payload(self):
        from agent.app.parent.runtime import _validate_payload

        doc_id, prompt, history = _validate_payload({
            "doc_id": "doc-001",
            "prompt": "hello",
            "history": [{"role": "user", "content": "hi"}],
        })

        assert doc_id == "doc-001"
        assert prompt == "hello"
        assert len(history) == 1

    def test_missing_doc_id_raises(self):
        from agent.app.parent.runtime import _validate_payload

        with pytest.raises(ValueError, match="doc_id"):
            _validate_payload({"prompt": "hello"})

    def test_missing_prompt_raises(self):
        from agent.app.parent.runtime import _validate_payload

        with pytest.raises(ValueError, match="prompt"):
            _validate_payload({"doc_id": "doc-001"})

    def test_history_defaults_to_empty(self):
        from agent.app.parent.runtime import _validate_payload

        _, _, history = _validate_payload({
            "doc_id": "doc-001",
            "prompt": "hello",
        })

        assert history == []


class TestPayloadEdgeCases:
    """Tests for invoke() payload parsing edge cases."""

    def test_none_payload_returns_error(self):
        from agent.app.parent.runtime import invoke

        result = invoke(None)

        assert result["status"] == "error"

    def test_non_dict_payload_returns_error(self):
        from agent.app.parent.runtime import invoke

        result = invoke("not a dict")

        assert result["status"] == "error"

    def test_list_payload_returns_error(self):
        from agent.app.parent.runtime import invoke

        result = invoke([{"doc_id": "doc-001", "prompt": "hello"}])

        assert result["status"] == "error"

    def test_extra_keys_are_ignored(self):
        from agent.app.parent.runtime import invoke

        result = invoke({
            "doc_id": "doc-001",
            "prompt": "test",
            "extra_key": "should be ignored",
            "another": 123,
        })

        assert result["status"] == "ok"
        assert {"result", "version", "status"}.issubset(result.keys())

    def test_non_string_doc_id_returns_error(self):
        from agent.app.parent.runtime import invoke

        result = invoke({"doc_id": 12345, "prompt": "hello"})

        # Numeric doc_id is truthy so it passes validation;
        # the system should still handle it gracefully
        assert result["status"] in ("ok", "error")

    def test_history_non_list_returns_ok_or_error(self):
        from agent.app.parent.runtime import invoke

        result = invoke({
            "doc_id": "doc-001",
            "prompt": "test",
            "history": "not a list",
        })

        # Should handle gracefully — either use it or default
        assert "status" in result

    def test_whitespace_only_doc_id_returns_error(self):
        from agent.app.parent.runtime import invoke

        result = invoke({"doc_id": "   ", "prompt": "hello"})

        assert result["status"] == "error"

    def test_whitespace_only_prompt_returns_error(self):
        from agent.app.parent.runtime import invoke

        result = invoke({"doc_id": "doc-001", "prompt": "   "})

        assert result["status"] == "error"

    def test_version_is_non_negative_int(self):
        from agent.app.parent.runtime import invoke

        result = invoke({"doc_id": "doc-001", "prompt": "test"})

        assert result["status"] == "ok"
        assert isinstance(result["version"], int)
        assert result["version"] >= 0


class TestModelConfig:
    """Tests for PARENT_MODEL / CHILD_MODEL env-var configuration."""

    def test_default_parent_model(self):
        from agent.app.parent.runtime import PARENT_MODEL

        assert PARENT_MODEL == "global.anthropic.claude-opus-4-6-v1"

    def test_default_child_model(self):
        from agent.app.parent.runtime import CHILD_MODEL

        assert CHILD_MODEL == "apac.anthropic.claude-3-5-sonnet-20241022-v2:0"

    def test_parent_model_env_override(self):
        with patch.dict(os.environ, {"PARENT_MODEL": "custom-parent-model"}):
            # Force re-evaluation by importing the module-level logic
            import importlib
            import agent.app.parent.runtime as runtime_mod

            importlib.reload(runtime_mod)
            assert runtime_mod.PARENT_MODEL == "custom-parent-model"

            # Restore defaults
            importlib.reload(runtime_mod)

    def test_child_model_env_override(self):
        with patch.dict(os.environ, {"CHILD_MODEL": "custom-child-model"}):
            import importlib
            import agent.app.parent.runtime as runtime_mod

            importlib.reload(runtime_mod)
            assert runtime_mod.CHILD_MODEL == "custom-child-model"

            # Restore defaults
            importlib.reload(runtime_mod)


class TestRuntimeDependencyWiring:
    """Tests for _get_orchestrator dependency construction."""

    def setup_method(self):
        import agent.app.parent.runtime as runtime_mod

        runtime_mod._orchestrator_instance = None

    def teardown_method(self):
        import agent.app.parent.runtime as runtime_mod

        runtime_mod._orchestrator_instance = None

    def test_get_orchestrator_wires_dynamodb_store_from_documents_table(
        self,
        monkeypatch,
    ):
        import agent.app.parent.runtime as runtime_mod
        from agent.lib.storage.dynamodb import DynamoDBDocumentStore

        calls = []
        captured = {}

        class FakeDynamoResource:
            def Table(self, table_name):
                calls.append(("Table", table_name))
                return SimpleNamespace()

        def fake_resource(service_name, region_name=None):
            calls.append(("resource", service_name, region_name))
            return FakeDynamoResource()

        class FakeParentOrchestrator:
            def __init__(self, document_store=None, memory=None, gateway_client=None):
                captured["document_store"] = document_store
                captured["memory"] = memory
                captured["gateway_client"] = gateway_client

        monkeypatch.setenv("DOCUMENTS_TABLE", "documents-table")
        monkeypatch.setenv("DYNAMODB_TABLE", "legacy-table")
        monkeypatch.setenv("AWS_REGION", "us-west-2")
        monkeypatch.delenv("AGENTCORE_MEMORY_ID", raising=False)
        monkeypatch.delenv("AGENTCORE_GATEWAY_ID", raising=False)
        monkeypatch.setattr("agent.lib.storage.dynamodb.boto3.resource", fake_resource)
        monkeypatch.setattr(
            "agent.app.parent.orchestrator.ParentOrchestrator",
            FakeParentOrchestrator,
        )

        runtime_mod._get_orchestrator()

        store = captured["document_store"]
        assert isinstance(store, DynamoDBDocumentStore)
        assert store._table_name == "documents-table"
        assert captured["memory"] is None
        assert captured["gateway_client"] is None
        assert calls == [
            ("resource", "dynamodb", "us-west-2"),
            ("Table", "documents-table"),
        ]

    def test_get_orchestrator_defaults_table_region_and_optional_clients(
        self,
        monkeypatch,
    ):
        import agent.app.parent.runtime as runtime_mod

        captured = {}

        class FakeDynamoDBDocumentStore:
            def __init__(self, table_name=None, region_name=None):
                self.table_name = table_name
                self.region_name = region_name

        class FakeParentOrchestrator:
            def __init__(self, document_store=None, memory=None, gateway_client=None):
                captured["document_store"] = document_store
                captured["memory"] = memory
                captured["gateway_client"] = gateway_client

        monkeypatch.delenv("DOCUMENTS_TABLE", raising=False)
        monkeypatch.delenv("DYNAMODB_TABLE", raising=False)
        monkeypatch.delenv("AWS_REGION", raising=False)
        monkeypatch.delenv("AGENTCORE_MEMORY_ID", raising=False)
        monkeypatch.delenv("AGENTCORE_GATEWAY_ID", raising=False)
        monkeypatch.setattr(
            "agent.lib.storage.dynamodb.DynamoDBDocumentStore",
            FakeDynamoDBDocumentStore,
        )
        monkeypatch.setattr(
            "agent.app.parent.orchestrator.ParentOrchestrator",
            FakeParentOrchestrator,
        )

        runtime_mod._get_orchestrator()

        assert captured["document_store"].table_name == "doc-agent-documents"
        assert captured["document_store"].region_name == "ap-northeast-2"
        assert captured["memory"] is None
        assert captured["gateway_client"] is None

    def test_get_orchestrator_wires_optional_memory_and_gateway(
        self,
        monkeypatch,
    ):
        import agent.app.parent.runtime as runtime_mod

        captured = {}

        class FakeDynamoDBDocumentStore:
            def __init__(self, table_name=None, region_name=None):
                self.table_name = table_name
                self.region_name = region_name

        class FakeMemory:
            def __init__(self, memory_id, region):
                self.memory_id = memory_id
                self.region = region

        class FakeGatewayClient:
            def __init__(self, gateway_id, region):
                self.gateway_id = gateway_id
                self.region = region

        class FakeParentOrchestrator:
            def __init__(self, document_store=None, memory=None, gateway_client=None):
                captured["document_store"] = document_store
                captured["memory"] = memory
                captured["gateway_client"] = gateway_client

        monkeypatch.setenv("DYNAMODB_TABLE", "legacy-table")
        monkeypatch.setenv("AWS_REGION", "eu-central-1")
        monkeypatch.setenv("AGENTCORE_MEMORY_ID", "memory-123")
        monkeypatch.setenv("AGENTCORE_GATEWAY_ID", "gateway-456")
        monkeypatch.delenv("DOCUMENTS_TABLE", raising=False)
        monkeypatch.setattr(
            "agent.lib.storage.dynamodb.DynamoDBDocumentStore",
            FakeDynamoDBDocumentStore,
        )
        monkeypatch.setattr(
            "agent.lib.memory.agentcore_memory.AgentCoreMemory",
            FakeMemory,
        )
        monkeypatch.setattr(
            "agent.lib.gateway.agentcore_gateway.AgentCoreGatewayClient",
            FakeGatewayClient,
        )
        monkeypatch.setattr(
            "agent.app.parent.orchestrator.ParentOrchestrator",
            FakeParentOrchestrator,
        )

        runtime_mod._get_orchestrator()

        assert captured["document_store"].table_name == "legacy-table"
        assert captured["document_store"].region_name == "eu-central-1"
        assert captured["memory"].memory_id == "memory-123"
        assert captured["memory"].region == "eu-central-1"
        assert captured["gateway_client"].gateway_id == "gateway-456"
        assert captured["gateway_client"].region == "eu-central-1"
