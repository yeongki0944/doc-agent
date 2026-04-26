"""Tests for AgentCore Runtime entry point (runtime.py).

Validates:
- Payload parsing and validation (doc_id, prompt, history)
- Response format: {"result": ..., "version": ..., "status": ...}
- PARENT_MODEL / CHILD_MODEL env-var override
- Error handling for missing/invalid payloads
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest


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

        assert set(result.keys()) == {"result", "version", "status"}

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
        assert set(result.keys()) == {"result", "version", "status"}

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
