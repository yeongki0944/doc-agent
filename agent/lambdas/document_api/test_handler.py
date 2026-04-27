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


def _body(response: dict) -> dict:
    return json.loads(response["body"])


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
