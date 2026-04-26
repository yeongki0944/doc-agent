"""Tests for OnPublish Lambda v2 patch validation.

Covers:
- Path validation (valid/invalid Document_State paths)
- Source validation (allowed/disallowed values)
- Version validation against DynamoDB
- Error publishing on validation failure
- Version conflict info in error responses

Requirements: 10.5, 10.6, 9.3
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from agent.lambdas.on_publish.handler import (
    VALID_SOURCES,
    handler,
    validate_path,
    validate_source,
)


# ---------------------------------------------------------------------------
# validate_path unit tests
# ---------------------------------------------------------------------------

class TestValidatePath:
    """Path validation against Document_State schema."""

    @pytest.mark.parametrize("path", [
        "/meta/customer/user_input",
        "/meta/partner/ai_recommended",
        "/meta/date/status",
        "/sections/cover/title",
        "/sections/executive_summary/content",
        "/sections/stakeholders/sponsor",
        "/sections/success_criteria/kpis",
        "/sections/assumptions/items",
        "/sections/scope_of_work/phases",
        "/sections/architecture/services",
        "/sections/milestones/phases",
        "/sections/cost_breakdown/staffing_cost",
        "/sections/acceptance/criteria",
        "/sections/resources_cost_estimates/items",
        "/staffing_plan/roles/project_manager/count/ai_recommended",
        "/staffing_plan/grand_total_hours/calculated",
        "/completion_score",
        "/blocking_issues",
        "/warnings",
        "/mode",
        "/version",
    ])
    def test_valid_paths(self, path: str):
        assert validate_path(path) is True

    @pytest.mark.parametrize("path", [
        "",
        "no_leading_slash",
        "/unknown_top_level/foo",
        "/sections/nonexistent_section/field",
        "/meta/unknown_key/value",
        "/document_id",
        "/template",
    ])
    def test_invalid_paths(self, path: str):
        assert validate_path(path) is False


# ---------------------------------------------------------------------------
# validate_source unit tests
# ---------------------------------------------------------------------------

class TestValidateSource:
    """Source field validation."""

    @pytest.mark.parametrize("source", [None, "user_input", "ai_recommended", "calculated"])
    def test_valid_sources(self, source):
        assert validate_source(source) is True

    @pytest.mark.parametrize("source", ["unknown", "system", "auto", ""])
    def test_invalid_sources(self, source):
        assert validate_source(source) is False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(doc_id="doc-001", version=1, operations=None):
    """Build a minimal OnPublish event payload."""
    if operations is None:
        operations = [{"op": "replace", "path": "/meta/customer/user_input", "value": "Acme", "source": "user_input"}]
    return {
        "payload": {
            "doc_id": doc_id,
            "version": version,
            "operations": operations,
        }
    }


def _mock_table(current_version: int | None = 1):
    """Create a mock DynamoDB table that returns *current_version*."""
    table = MagicMock()
    if current_version is not None:
        table.get_item.return_value = {"Item": {"version": current_version}}
    else:
        table.get_item.return_value = {}
    return table


# ---------------------------------------------------------------------------
# Handler integration tests
# ---------------------------------------------------------------------------

class TestHandlerValidPatch:
    """Patches that pass all validation."""

    def test_valid_patch_passes(self):
        table = _mock_table(current_version=1)
        event = _make_event(version=1)
        result = handler(event, None, _table=table)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["blocked"] is False

    def test_valid_patch_with_no_source(self):
        """source=None is allowed."""
        table = _mock_table(current_version=5)
        event = _make_event(version=5, operations=[
            {"op": "replace", "path": "/completion_score", "value": 0.8},
        ])
        result = handler(event, None, _table=table)

        assert result["statusCode"] == 200

    def test_valid_patch_multiple_operations(self):
        table = _mock_table(current_version=3)
        event = _make_event(version=3, operations=[
            {"op": "replace", "path": "/meta/customer/user_input", "value": "X", "source": "user_input"},
            {"op": "replace", "path": "/staffing_plan/roles/pm/count/ai_recommended", "value": 2, "source": "ai_recommended"},
            {"op": "replace", "path": "/sections/cost_breakdown/staffing_cost", "value": {}, "source": "calculated"},
        ])
        result = handler(event, None, _table=table)

        assert result["statusCode"] == 200


class TestHandlerInvalidPath:
    """Patches with invalid operation paths."""

    def test_invalid_path_blocked(self):
        table = _mock_table(current_version=1)
        event = _make_event(version=1, operations=[
            {"op": "replace", "path": "/invalid/path", "value": "x"},
        ])
        result = handler(event, None, _table=table)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["blocked"] is True
        assert any("invalid path" in e for e in body["errors"])

    def test_invalid_section_key_blocked(self):
        table = _mock_table(current_version=1)
        event = _make_event(version=1, operations=[
            {"op": "replace", "path": "/sections/nonexistent/field", "value": "x"},
        ])
        result = handler(event, None, _table=table)

        assert result["statusCode"] == 400

    def test_invalid_meta_key_blocked(self):
        table = _mock_table(current_version=1)
        event = _make_event(version=1, operations=[
            {"op": "replace", "path": "/meta/unknown/value", "value": "x"},
        ])
        result = handler(event, None, _table=table)

        assert result["statusCode"] == 400


class TestHandlerInvalidSource:
    """Patches with invalid source values."""

    def test_invalid_source_blocked(self):
        table = _mock_table(current_version=1)
        event = _make_event(version=1, operations=[
            {"op": "replace", "path": "/meta/customer/user_input", "value": "x", "source": "unknown_source"},
        ])
        result = handler(event, None, _table=table)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["blocked"] is True
        assert any("invalid source" in e for e in body["errors"])


class TestHandlerVersionValidation:
    """Version mismatch detection against DynamoDB."""

    def test_version_mismatch_blocked(self):
        table = _mock_table(current_version=5)
        event = _make_event(version=3)
        result = handler(event, None, _table=table)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["blocked"] is True
        assert any("version mismatch" in e for e in body["errors"])
        assert body["version_conflict"] == {"expected": 3, "actual": 5}

    def test_version_match_passes(self):
        table = _mock_table(current_version=10)
        event = _make_event(version=10)
        result = handler(event, None, _table=table)

        assert result["statusCode"] == 200

    def test_document_not_found_passes(self):
        """If document doesn't exist in DynamoDB, allow patch through."""
        table = _mock_table(current_version=None)
        event = _make_event(version=1)
        result = handler(event, None, _table=table)

        assert result["statusCode"] == 200

    def test_dynamodb_error_non_fatal(self):
        """DynamoDB errors should not block the patch (graceful degradation)."""
        table = MagicMock()
        table.get_item.side_effect = Exception("DynamoDB timeout")
        event = _make_event(version=1)
        result = handler(event, None, _table=table)

        # Should pass through since DynamoDB check is non-fatal
        assert result["statusCode"] == 200


class TestHandlerErrorPublishing:
    """Error status publishing on validation failure."""

    @patch("agent.lambdas.on_publish.handler._publish_error_status")
    def test_error_status_published_on_path_failure(self, mock_publish):
        table = _mock_table(current_version=1)
        event = _make_event(version=1, operations=[
            {"op": "replace", "path": "/bad/path", "value": "x"},
        ])
        handler(event, None, _table=table)

        mock_publish.assert_called_once()
        call_args = mock_publish.call_args
        assert call_args[0][0] == "doc-001"  # doc_id
        assert any("invalid path" in e for e in call_args[0][1])  # errors

    @patch("agent.lambdas.on_publish.handler._publish_error_status")
    def test_error_status_published_on_version_conflict(self, mock_publish):
        table = _mock_table(current_version=5)
        event = _make_event(version=2)
        handler(event, None, _table=table)

        mock_publish.assert_called_once()
        call_args = mock_publish.call_args
        assert call_args[0][2] == {"expected": 2, "actual": 5}  # version_info

    @patch("agent.lambdas.on_publish.handler._publish_error_status")
    def test_no_error_published_on_success(self, mock_publish):
        table = _mock_table(current_version=1)
        event = _make_event(version=1)
        handler(event, None, _table=table)

        mock_publish.assert_not_called()


class TestHandlerMultipleErrors:
    """Multiple validation errors collected in single response."""

    def test_path_and_source_errors_combined(self):
        table = _mock_table(current_version=1)
        event = _make_event(version=1, operations=[
            {"op": "replace", "path": "/bad/path", "value": "x", "source": "bad_source"},
        ])
        result = handler(event, None, _table=table)

        body = json.loads(result["body"])
        assert len(body["errors"]) == 2  # one path error + one source error

    def test_path_source_and_version_errors(self):
        table = _mock_table(current_version=99)
        event = _make_event(version=1, operations=[
            {"op": "replace", "path": "/bad", "value": "x", "source": "nope"},
        ])
        result = handler(event, None, _table=table)

        body = json.loads(result["body"])
        # path error + source error + version mismatch
        assert len(body["errors"]) == 3


class TestHandlerEdgeCases:
    """Edge cases and error handling."""

    def test_empty_operations_passes(self):
        table = _mock_table(current_version=1)
        event = _make_event(version=1, operations=[])
        result = handler(event, None, _table=table)

        assert result["statusCode"] == 200

    def test_event_without_payload_wrapper(self):
        """Event may come without 'payload' wrapper."""
        table = _mock_table(current_version=1)
        event = {
            "doc_id": "doc-001",
            "version": 1,
            "operations": [{"op": "replace", "path": "/mode", "value": "architecture_present"}],
        }
        result = handler(event, None, _table=table)

        assert result["statusCode"] == 200

    def test_handler_exception_returns_500(self):
        """Unexpected exceptions return 500."""
        event = {"payload": None}  # will cause AttributeError
        result = handler(event, None)

        assert result["statusCode"] == 500
        body = json.loads(result["body"])
        assert body["blocked"] is True

    def test_version_without_doc_id_reports_error(self):
        """version present but doc_id missing should report an error."""
        table = _mock_table(current_version=1)
        event = {
            "payload": {
                "doc_id": "",
                "version": 5,
                "operations": [{"op": "replace", "path": "/mode", "value": "architecture_present"}],
            }
        }
        result = handler(event, None, _table=table)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert any("doc_id is required" in e for e in body["errors"])
