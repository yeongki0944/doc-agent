import io
import json
from unittest.mock import MagicMock

from agent.lambdas.document_api import handler as document_api


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


def test_chat_alias_invokes_runtime_proxy_without_document_overwrite(monkeypatch):
    table = MagicMock()
    table.get_item.return_value = {
        "Item": {"document_id": "doc-1", "user_id": "user-1", "version": 3}
    }
    monkeypatch.setattr(document_api, "table", table)

    calls = []

    def fake_invoke_runtime(payload):
        calls.append(payload)
        return {"result": "runtime reply", "version": 4, "status": "ok"}

    monkeypatch.setattr(document_api, "_invoke_runtime", fake_invoke_runtime)
    monkeypatch.setattr(
        document_api,
        "_invoke_bedrock",
        MagicMock(side_effect=AssertionError("chat must not invoke Bedrock")),
    )

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
    assert saved_item["sections"] == {}
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
