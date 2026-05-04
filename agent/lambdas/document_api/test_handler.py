import io
import json
from pathlib import Path
from unittest.mock import MagicMock

from agent.lambdas.document_api import handler as document_api
from agent.lambdas.document_api import runtime_proxy
from agent.lib.storage.dynamodb import VersionConflictError


def _event(doc_id: str = "doc-1", user_id: str = "user-1") -> dict:
    return {
        "requestContext": {"http": {"method": "POST", "path": f"/documents/{doc_id}/export"}},
        "headers": {"X-User-Id": user_id},
        "body": "{}",
    }


def _post_event(path: str, body: dict, user_id: str = "user-1") -> dict:
    return {
        "requestContext": {"http": {"method": "POST", "path": path}},
        "headers": {"X-User-Id": user_id},
        "body": json.dumps(body),
    }


def _body(response: dict) -> dict:
    return json.loads(response["body"])


def _field(user_input=None, ai_recommended=None, calculated=None, status="empty"):
    return {
        "user_input": user_input,
        "ai_recommended": ai_recommended,
        "calculated": calculated,
        "status": status,
        "user_edited": False,
    }


def _doc_item(version: int = 2) -> dict:
    return {
        "document_id": "doc-1",
        "user_id": "user-1",
        "template": "apn_poc_project_plan",
        "mode": "architecture_absent",
        "version": version,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "meta": {
            "customer": _field(ai_recommended="AI Customer", status="recommended"),
            "partner": _field(),
            "date": _field(),
        },
        "sections": {},
        "staffing_plan": {"roles": {}, "grand_total_hours": {"calculated": None}, "grand_total_cost": {"calculated": None}},
        "completion_score": 0,
        "blocking_issues": [],
        "warnings": [],
    }


class FakeConditionalSaver:
    def __init__(self):
        self.calls = []

    def save(self, item, expected_version):
        self.calls.append((item, expected_version))
        item["version"] = expected_version + 1
        return item


def test_chat_alias_invokes_runtime_proxy_without_document_overwrite(monkeypatch):
    table = MagicMock()
    table.get_item.return_value = {
        "Item": {"document_id": "doc-1", "user_id": "user-1", "version": 3}
    }
    monkeypatch.setattr(document_api, "table", table)

    calls = []

    class FakeRuntimeProxy:
        def invoke(self, payload):
            calls.append(payload)
            return {"result": "runtime reply", "version": 4, "status": "ok"}

    monkeypatch.setattr(runtime_proxy, "get_runtime_proxy", lambda: FakeRuntimeProxy())

    response = document_api.handler(
        _post_event(
            "/documents/doc-1/chat",
            {"message": "hello", "history": [{"role": "user", "content": "hi"}]},
        ),
        None,
    )

    assert response["statusCode"] == 200
    assert calls == [{
        "doc_id": "doc-1",
        "prompt": "hello",
        "history": [{"role": "user", "content": "hi"}],
        "user_id": "user-1",
    }]
    assert _body(response) == {
        "agent_response": "runtime reply",
        "version": 4,
        "status": "ok",
    }
    table.put_item.assert_not_called()


def test_document_api_handler_has_no_v1_bedrock_chat_code():
    source = Path(document_api.__file__).read_text(encoding="utf-8")
    assert "invoke_model(" not in source
    assert "invoke_model_with_response_stream(" not in source
    assert "PARENT_SYSTEM" not in source
    assert "STAFFING_PRESET" not in source
    assert "PHASE_HOURS" not in source


def test_chat_alias_auto_creates_shell_only_when_missing(monkeypatch):
    table = MagicMock()
    table.get_item.return_value = {}
    monkeypatch.setattr(document_api, "table", table)
    monkeypatch.setattr(
        document_api,
        "_invoke_runtime",
        lambda payload: {"result": "created", "version": 1, "status": "ok"},
    )

    response = document_api.handler(
        _post_event("/documents/doc-new/chat", {"message": "start"}),
        None,
    )

    assert response["statusCode"] == 200
    table.put_item.assert_called_once()
    saved_item = table.put_item.call_args.kwargs["Item"]
    assert saved_item["document_id"] == "doc-new"
    assert saved_item["user_id"] == "user-1"
    assert saved_item["version"] == 0
    assert saved_item["sections"] == document_api._default_sections()
    assert saved_item["staffing_plan"]["roles"] == {}


def test_invocations_invokes_runtime_proxy(monkeypatch):
    table = MagicMock()
    table.get_item.return_value = {
        "Item": {"document_id": "doc-1", "user_id": "user-1", "version": 3}
    }
    monkeypatch.setattr(document_api, "table", table)

    calls = []

    def fake_invoke_runtime(payload):
        calls.append(payload)
        return {
            "result": "runtime response",
            "version": 5,
            "status": "ok",
            "actions": ["patched"],
        }

    monkeypatch.setattr(document_api, "_invoke_runtime", fake_invoke_runtime)

    response = document_api.handler(
        _post_event(
            "/invocations",
            {"doc_id": "doc-1", "prompt": "continue", "history": []},
        ),
        None,
    )

    assert response["statusCode"] == 200
    assert calls == [{
        "doc_id": "doc-1",
        "prompt": "continue",
        "history": [],
        "user_id": "user-1",
    }]
    assert _body(response) == {
        "agent_response": "runtime response",
        "version": 5,
        "status": "ok",
        "actions": ["patched"],
    }
    table.put_item.assert_not_called()


def test_chat_forbidden_does_not_invoke_runtime(monkeypatch):
    table = MagicMock()
    table.get_item.return_value = {
        "Item": {"document_id": "doc-1", "user_id": "other"}
    }
    monkeypatch.setattr(document_api, "table", table)
    invoke_runtime = MagicMock()
    monkeypatch.setattr(document_api, "_invoke_runtime", invoke_runtime)

    response = document_api.handler(
        _post_event("/documents/doc-1/chat", {"message": "hello"}),
        None,
    )

    assert response["statusCode"] == 403
    invoke_runtime.assert_not_called()
    table.put_item.assert_not_called()


def test_user_input_updates_field_value_and_preserves_ai_recommended(monkeypatch):
    table = MagicMock()
    table.get_item.return_value = {"Item": _doc_item(version=2)}
    monkeypatch.setattr(document_api, "table", table)
    saver = FakeConditionalSaver()
    monkeypatch.setattr(document_api, "_conditional_save_document", saver.save)
    published = []
    monkeypatch.setattr(document_api, "_publish_event", lambda channel, data: published.append((channel, data)))

    response = document_api.handler(
        _post_event(
            "/documents/doc-1/user-input",
            {"path": "meta.customer.user_input", "value": "User Customer"},
        ),
        None,
    )

    assert response["statusCode"] == 200
    assert _body(response) == {"status": "ok", "version": 3}
    saved, expected_version = saver.calls[0]
    assert expected_version == 2
    assert saved["user_id"] == "user-1"
    assert saved["meta"]["customer"]["user_input"] == "User Customer"
    assert saved["meta"]["customer"]["ai_recommended"] == "AI Customer"
    assert saved["meta"]["customer"]["user_edited"] is True
    assert saved["meta"]["customer"]["status"] == "draft"
    assert published[0][0] == "docs/doc-1/patch"
    payload = published[0][1]
    assert payload["type"] == "patch"
    assert payload["version_before"] == 2
    assert payload["version_after"] == 3
    assert {op["path"] for op in payload["operations"]} == {
        "/meta/customer/user_input",
        "/meta/customer/user_edited",
        "/meta/customer/status",
    }


def test_user_input_updates_list_index_field_value(monkeypatch):
    item = _doc_item(version=2)
    item["sections"] = {
        "stakeholders": {
            "stakeholders": [
                {"name": _field(user_input="A", status="draft")},
                {"name": _field(user_input="B", ai_recommended="B AI", status="recommended")},
            ]
        }
    }
    table = MagicMock()
    table.get_item.return_value = {"Item": item}
    monkeypatch.setattr(document_api, "table", table)
    saver = FakeConditionalSaver()
    monkeypatch.setattr(document_api, "_conditional_save_document", saver.save)
    published = []
    monkeypatch.setattr(document_api, "_publish_event", lambda channel, data: published.append(data))

    response = document_api.handler(
        _post_event(
            "/documents/doc-1/user-input",
            {
                "path": "sections.stakeholders.stakeholders.1.name.user_input",
                "value": "Project Stakeholders22",
            },
        ),
        None,
    )

    assert response["statusCode"] == 200
    saved = saver.calls[0][0]
    rows = saved["sections"]["stakeholders"]["stakeholders"]
    assert rows[0]["name"]["user_input"] == "A"
    assert rows[1]["name"]["user_input"] == "Project Stakeholders22"
    assert rows[1]["name"]["ai_recommended"] == "B AI"
    assert rows[1]["name"]["status"] == "draft"
    assert rows[1]["name"]["user_edited"] is True
    assert {op["path"] for op in published[0]["operations"]} == {
        "/sections/stakeholders/stakeholders/1/name/user_input",
        "/sections/stakeholders/stakeholders/1/name/user_edited",
        "/sections/stakeholders/stakeholders/1/name/status",
    }


def test_user_input_updates_nested_list_field_value(monkeypatch):
    item = _doc_item(version=2)
    item["sections"] = {
        "success_criteria": {
            "groups": [
                {
                    "category_name": _field(user_input="Group A"),
                    "bullets": [
                        _field(user_input="Bullet 0"),
                        _field(user_input="Bullet 1", ai_recommended="Bullet AI"),
                    ],
                }
            ]
        }
    }
    table = MagicMock()
    table.get_item.return_value = {"Item": item}
    monkeypatch.setattr(document_api, "table", table)
    saver = FakeConditionalSaver()
    monkeypatch.setattr(document_api, "_conditional_save_document", saver.save)
    monkeypatch.setattr(document_api, "_publish_event", lambda channel, data: None)

    response = document_api.handler(
        _post_event(
            "/documents/doc-1/user-input",
            {
                "path": "sections.success_criteria.groups.0.bullets.1.user_input",
                "value": "Updated bullet",
            },
        ),
        None,
    )

    assert response["statusCode"] == 200
    bullets = saver.calls[0][0]["sections"]["success_criteria"]["groups"][0]["bullets"]
    assert bullets[0]["user_input"] == "Bullet 0"
    assert bullets[1]["user_input"] == "Updated bullet"
    assert bullets[1]["ai_recommended"] == "Bullet AI"
    assert bullets[1]["status"] == "draft"
    assert bullets[1]["user_edited"] is True


def test_user_input_replaces_full_array_without_field_value_wrapping(monkeypatch):
    item = _doc_item(version=2)
    item["sections"] = {"stakeholders": {"stakeholders": []}}
    table = MagicMock()
    table.get_item.return_value = {"Item": item}
    monkeypatch.setattr(document_api, "table", table)
    saver = FakeConditionalSaver()
    monkeypatch.setattr(document_api, "_conditional_save_document", saver.save)
    monkeypatch.setattr(document_api, "_publish_event", lambda channel, data: None)
    replacement = [
        {"name": _field(user_input="A")},
        {"name": _field(user_input="B")},
    ]

    response = document_api.handler(
        _post_event(
            "/documents/doc-1/user-input",
            {"path": "sections.stakeholders.stakeholders", "value": replacement},
        ),
        None,
    )

    assert response["statusCode"] == 200
    saved_value = saver.calls[0][0]["sections"]["stakeholders"]["stakeholders"]
    assert isinstance(saved_value, list)
    assert saved_value == replacement
    assert "user_input" not in saver.calls[0][0]["sections"]["stakeholders"]


def test_user_input_updates_top_level_title_without_field_value_wrapping(monkeypatch):
    item = _doc_item(version=2)
    item["title"] = "Old Title"
    table = MagicMock()
    table.get_item.return_value = {"Item": item}
    monkeypatch.setattr(document_api, "table", table)
    saver = FakeConditionalSaver()
    monkeypatch.setattr(document_api, "_conditional_save_document", saver.save)
    monkeypatch.setattr(document_api, "_publish_event", lambda channel, data: None)

    response = document_api.handler(
        _post_event(
            "/documents/doc-1/user-input",
            {"path": "title", "value": "New Title"},
        ),
        None,
    )

    assert response["statusCode"] == 200
    assert saver.calls[0][0]["title"] == "New Title"
    assert not isinstance(saver.calls[0][0]["title"], dict)


def test_user_input_returns_clear_error_for_invalid_list_index(monkeypatch):
    item = _doc_item(version=2)
    item["sections"] = {
        "stakeholders": {
            "stakeholders": [
                {"name": _field(user_input="A")},
            ]
        }
    }
    table = MagicMock()
    table.get_item.return_value = {"Item": item}
    monkeypatch.setattr(document_api, "table", table)
    saver = FakeConditionalSaver()
    monkeypatch.setattr(document_api, "_conditional_save_document", saver.save)
    publish = MagicMock()
    monkeypatch.setattr(document_api, "_publish_event", publish)

    response = document_api.handler(
        _post_event(
            "/documents/doc-1/user-input",
            {
                "path": "sections.stakeholders.stakeholders.9.name.user_input",
                "value": "No row",
            },
        ),
        None,
    )

    assert response["statusCode"] == 400
    assert _body(response) == {
        "error": "invalid list index",
        "path": "sections.stakeholders.stakeholders.9.name.user_input",
        "segment": "9",
        "reason": "index 9 is out of range for list of length 1",
    }
    assert saver.calls == []
    publish.assert_not_called()


def test_user_input_recalculates_staffing(monkeypatch):
    item = _doc_item(version=4)
    item["staffing_plan"] = {
        "roles": {
            "sa": {
                "role_id": "sa",
                "display_name": "SA",
                "category": "solution_architect",
                "count": _field(ai_recommended=1),
                "allocation_pct": _field(ai_recommended=50),
                "rate_per_hour": _field(ai_recommended=100),
                "phase_hours": {
                    "discovery": _field(ai_recommended=10),
                    "development": _field(ai_recommended=20),
                    "testing": _field(ai_recommended=0),
                },
                "total_hours": {"calculated": 30},
                "total_cost": {"calculated": 1500},
            }
        },
        "grand_total_hours": {"calculated": 30},
        "grand_total_cost": {"calculated": 1500},
    }
    table = MagicMock()
    table.get_item.return_value = {"Item": item}
    monkeypatch.setattr(document_api, "table", table)
    saver = FakeConditionalSaver()
    monkeypatch.setattr(document_api, "_conditional_save_document", saver.save)
    published = []
    monkeypatch.setattr(document_api, "_publish_event", lambda channel, data: published.append(data))

    response = document_api.handler(
        _post_event(
            "/documents/doc-1/user-input",
            {"path": "staffing_plan.roles.sa.phase_hours.testing.user_input", "value": 5},
        ),
        None,
    )

    assert response["statusCode"] == 200
    saved = saver.calls[0][0]
    assert saved["staffing_plan"]["roles"]["sa"]["phase_hours"]["testing"]["user_input"] == 5
    assert saved["staffing_plan"]["roles"]["sa"]["total_hours"]["calculated"] == 35
    assert saved["staffing_plan"]["roles"]["sa"]["total_cost"]["calculated"] == 1750
    assert saved["staffing_plan"]["grand_total_hours"]["calculated"] == 35
    assert saved["staffing_plan"]["grand_total_cost"]["calculated"] == 1750
    paths = {op["path"] for op in published[0]["operations"]}
    assert "/staffing_plan/roles/sa/total_hours" in paths
    assert "/staffing_plan/roles/sa/total_cost" in paths
    assert "/staffing_plan/grand_total_hours" in paths
    assert "/staffing_plan/grand_total_cost" in paths


def test_user_input_version_conflict_returns_409(monkeypatch):
    table = MagicMock()
    table.get_item.return_value = {"Item": _doc_item(version=8)}
    monkeypatch.setattr(document_api, "table", table)

    def raise_conflict(item, expected_version):
        raise VersionConflictError("Version conflict: expected 8")

    monkeypatch.setattr(document_api, "_conditional_save_document", raise_conflict)
    publish = MagicMock()
    monkeypatch.setattr(document_api, "_publish_event", publish)

    response = document_api.handler(
        _post_event(
            "/documents/doc-1/user-input",
            {"path": "meta.customer.user_input", "value": "User Customer"},
        ),
        None,
    )

    assert response["statusCode"] == 409
    assert _body(response)["status"] == "version_conflict"
    publish.assert_not_called()


def test_export_invokes_export_docx_lambda(monkeypatch):
    item = {
        "document_id": "doc-1",
        "user_id": "user-1",
        "version": 7,
        "meta": {"customer": {"user_input": "Acme"}},
        "sections": {"executive_summary": {"text": {"ai_recommended": "Summary"}}},
        "staffing_plan": {"roles": {}},
    }
    table = MagicMock()
    table.get_item.return_value = {"Item": item}
    monkeypatch.setattr(document_api, "table", table)
    monkeypatch.setenv("EXPORT_DOCX_FUNCTION_NAME", "custom-export-fn")

    lambda_client = MagicMock()
    lambda_client.invoke.return_value = {
        "Payload": io.BytesIO(json.dumps({
            "outputPayload": json.dumps({
                "download_url": "https://example.com/doc.docx",
                "s3_key": "docs/doc-1/exports/doc-1-v7.docx",
                "bucket": "artifacts",
            })
        }).encode("utf-8"))
    }
    boto3_mock = MagicMock()
    boto3_mock.client.return_value = lambda_client
    monkeypatch.setattr(document_api, "boto3", boto3_mock)

    response = document_api.handler(_event(), None)

    assert response["statusCode"] == 200
    assert _body(response) == {
        "download_url": "https://example.com/doc.docx",
        "s3_key": "docs/doc-1/exports/doc-1-v7.docx",
        "bucket": "artifacts",
    }
    lambda_client.invoke.assert_called_once()
    invoke_kwargs = lambda_client.invoke.call_args.kwargs
    assert invoke_kwargs["FunctionName"] == "custom-export-fn"
    assert invoke_kwargs["InvocationType"] == "RequestResponse"

    payload = json.loads(invoke_kwargs["Payload"].decode("utf-8"))
    input_payload = json.loads(payload["inputPayload"])
    assert input_payload == {
        "doc_id": "doc-1",
        "version": 7,
        "meta": item["meta"],
        "sections": item["sections"],
        "staffing_plan": item["staffing_plan"],
    }


def test_export_missing_document_returns_404(monkeypatch):
    table = MagicMock()
    table.get_item.return_value = {}
    monkeypatch.setattr(document_api, "table", table)

    response = document_api.handler(_event(), None)

    assert response["statusCode"] == 404
    assert _body(response)["error"] == "not found"


def test_export_forbidden_returns_403(monkeypatch):
    table = MagicMock()
    table.get_item.return_value = {"Item": {"document_id": "doc-1", "user_id": "other"}}
    monkeypatch.setattr(document_api, "table", table)

    response = document_api.handler(_event(), None)

    assert response["statusCode"] == 403
    assert _body(response)["error"] == "forbidden"


def test_export_lambda_invoke_failure_returns_500(monkeypatch):
    table = MagicMock()
    table.get_item.return_value = {"Item": {"document_id": "doc-1", "user_id": "user-1"}}
    monkeypatch.setattr(document_api, "table", table)

    lambda_client = MagicMock()
    lambda_client.invoke.side_effect = RuntimeError("invoke failed")
    boto3_mock = MagicMock()
    boto3_mock.client.return_value = lambda_client
    monkeypatch.setattr(document_api, "boto3", boto3_mock)

    response = document_api.handler(_event(), None)

    assert response["statusCode"] == 500
    body = _body(response)
    assert body["stage"] == "invoke"
    assert "invoke failed" in body["error"]


def test_export_docx_error_payload_returns_500(monkeypatch):
    table = MagicMock()
    table.get_item.return_value = {"Item": {"document_id": "doc-1", "user_id": "user-1"}}
    monkeypatch.setattr(document_api, "table", table)

    lambda_client = MagicMock()
    lambda_client.invoke.return_value = {
        "Payload": io.BytesIO(json.dumps({
            "outputPayload": json.dumps({
                "error": "template missing",
                "stage": "download_template",
            })
        }).encode("utf-8"))
    }
    boto3_mock = MagicMock()
    boto3_mock.client.return_value = lambda_client
    monkeypatch.setattr(document_api, "boto3", boto3_mock)

    response = document_api.handler(_event(), None)

    assert response["statusCode"] == 500
    body = _body(response)
    assert body["error"] == "template missing"
    assert body["stage"] == "download_template"
