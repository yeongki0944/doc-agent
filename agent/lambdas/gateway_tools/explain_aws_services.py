"""Gateway Lambda: explain_aws_services

Returns short, review-ready explanations for a list of AWS services,
grouped by category with reference links. Designed to plug into the
AWS Documentation MCP server (``awslabs.aws-documentation-mcp-server``)
when configured, and fall back to a curated static catalogue or a
Bedrock LLM-generated explanation otherwise.

Contract:

Input (event["inputPayload"] JSON):
    {
        "services": ["Amazon Bedrock", "AWS Lambda", ...],
        "use_case": "RAG chatbot",       # optional, steers LLM fallback
        "language": "en" | "ko"          # optional, default "en"
    }

Output:
    {
        "mode": "mcp" | "static" | "llm_fallback",
        "explanations": [
            {
                "service_id": "amazon_bedrock",
                "service_name": "Amazon Bedrock",
                "summary": "Managed foundation model service for GenAI.",
                "category": "GenAI",
                "reference_urls": ["https://docs.aws.amazon.com/bedrock/"],
                "source": "static"
            }, ...
        ],
        "warnings": ["..."]
    }

Fallback behaviour:
  - If ``AWS_DOCS_MCP_ENDPOINT`` is not set, use the static catalogue.
  - If a service is missing from the static catalogue and ``BEDROCK_EXPLAIN_FALLBACK``
    is not ``"off"``, a single Bedrock call fills in the gap.
  - If Bedrock call fails, return a minimal placeholder with a warning.
  - Result always includes a ``warnings`` list describing any degradation.
"""

from __future__ import annotations

import json
import os
from typing import Any

import boto3

REGION = os.environ.get("AWS_REGION", "ap-northeast-2")
AWS_DOCS_MCP_ENDPOINT = os.environ.get("AWS_DOCS_MCP_ENDPOINT", "")
BEDROCK_EXPLAIN_FALLBACK = os.environ.get("BEDROCK_EXPLAIN_FALLBACK", "on").lower()
EXPLAIN_MODEL_ID = os.environ.get(
    "EXPLAIN_MODEL_ID",
    "apac.anthropic.claude-3-5-sonnet-20241022-v2:0",
)


# ---------------------------------------------------------------------------
# Static catalogue (curated short summaries — always safe to return)
# ---------------------------------------------------------------------------

_STATIC_CATALOG: dict[str, dict[str, Any]] = {
    "amazon_bedrock": {
        "service_name": "Amazon Bedrock",
        "summary": "Managed foundation model service for GenAI workloads with guardrails and knowledge bases.",
        "category": "GenAI",
        "reference_urls": ["https://docs.aws.amazon.com/bedrock/"],
    },
    "amazon_opensearch_service": {
        "service_name": "Amazon OpenSearch Service",
        "summary": "Search and analytics service; commonly used as the vector store for RAG pipelines.",
        "category": "Retrieval",
        "reference_urls": ["https://docs.aws.amazon.com/opensearch-service/"],
    },
    "amazon_s3": {
        "service_name": "Amazon S3",
        "summary": "Object storage for source documents, exports and model artefacts.",
        "category": "Storage",
        "reference_urls": ["https://docs.aws.amazon.com/s3/"],
    },
    "aws_lambda": {
        "service_name": "AWS Lambda",
        "summary": "Serverless compute used for API glue, workflow orchestration and GenAI tool invocations.",
        "category": "Compute",
        "reference_urls": ["https://docs.aws.amazon.com/lambda/"],
    },
    "amazon_api_gateway": {
        "service_name": "Amazon API Gateway",
        "summary": "Managed HTTP/WebSocket front door for exposing Lambdas and workflows to clients.",
        "category": "Edge",
        "reference_urls": ["https://docs.aws.amazon.com/apigateway/"],
    },
    "amazon_dynamodb": {
        "service_name": "Amazon DynamoDB",
        "summary": "Managed key-value store for document state, conversation history, and sessions.",
        "category": "Retrieval",
        "reference_urls": ["https://docs.aws.amazon.com/dynamodb/"],
    },
    "amazon_cloudwatch": {
        "service_name": "Amazon CloudWatch",
        "summary": "Monitoring and observability for logs, metrics and alarms.",
        "category": "Observability",
        "reference_urls": ["https://docs.aws.amazon.com/cloudwatch/"],
    },
    "aws_iam": {
        "service_name": "AWS IAM",
        "summary": "Access control and permissions for AWS resources.",
        "category": "Security",
        "reference_urls": ["https://docs.aws.amazon.com/iam/"],
    },
    "aws_kms": {
        "service_name": "AWS KMS",
        "summary": "Managed encryption keys used to protect data at rest.",
        "category": "Security",
        "reference_urls": ["https://docs.aws.amazon.com/kms/"],
    },
    "amazon_rds": {
        "service_name": "Amazon RDS",
        "summary": "Managed relational database (often PostgreSQL/MySQL) for transactional data.",
        "category": "Retrieval",
        "reference_urls": ["https://docs.aws.amazon.com/rds/"],
    },
    "amazon_ecs": {
        "service_name": "Amazon ECS",
        "summary": "Managed container orchestration on Fargate or EC2.",
        "category": "Compute",
        "reference_urls": ["https://docs.aws.amazon.com/ecs/"],
    },
    "amazon_cognito": {
        "service_name": "Amazon Cognito",
        "summary": "User identity, authentication and access control for web/mobile apps.",
        "category": "Security",
        "reference_urls": ["https://docs.aws.amazon.com/cognito/"],
    },
    "amazon_appsync": {
        "service_name": "AWS AppSync",
        "summary": "Managed GraphQL / Events API; used here for real-time patch delivery.",
        "category": "Edge",
        "reference_urls": ["https://docs.aws.amazon.com/appsync/"],
    },
    "amazon_bedrock_agentcore": {
        "service_name": "Amazon Bedrock AgentCore",
        "summary": "Runtime for hosting long-running agent workflows with memory and gateway tools.",
        "category": "GenAI",
        "reference_urls": ["https://docs.aws.amazon.com/bedrock/latest/userguide/agents.html"],
    },
    "amazon_sagemaker": {
        "service_name": "Amazon SageMaker",
        "summary": "ML platform for training and hosting models beyond foundation model inference.",
        "category": "GenAI",
        "reference_urls": ["https://docs.aws.amazon.com/sagemaker/"],
    },
}


def _normalize_service_id(name: str) -> str:
    lc = (name or "").strip().lower()
    if not lc:
        return ""
    # Strip common prefixes/spaces/punctuation to form an id.
    lc = lc.replace("&", "and").replace("/", " ")
    lc = " ".join(lc.split())
    lc = lc.replace(" ", "_").replace("-", "_")
    # Known aliases
    aliases = {
        "bedrock": "amazon_bedrock",
        "opensearch": "amazon_opensearch_service",
        "amazon_opensearch": "amazon_opensearch_service",
        "s3": "amazon_s3",
        "lambda": "aws_lambda",
        "api_gateway": "amazon_api_gateway",
        "apigateway": "amazon_api_gateway",
        "dynamodb": "amazon_dynamodb",
        "cloudwatch": "amazon_cloudwatch",
        "iam": "aws_iam",
        "kms": "aws_kms",
        "rds": "amazon_rds",
        "ecs": "amazon_ecs",
        "cognito": "amazon_cognito",
        "appsync": "amazon_appsync",
        "agentcore": "amazon_bedrock_agentcore",
        "sagemaker": "amazon_sagemaker",
    }
    if lc in aliases:
        return aliases[lc]
    return lc


def _static_explanation(name: str) -> dict[str, Any] | None:
    service_id = _normalize_service_id(name)
    entry = _STATIC_CATALOG.get(service_id)
    if not entry:
        return None
    return {
        "service_id": service_id,
        "service_name": entry["service_name"],
        "summary": entry["summary"],
        "category": entry["category"],
        "reference_urls": list(entry.get("reference_urls") or []),
        "source": "static",
    }


def _bedrock_explanation(name: str, use_case: str, language: str) -> dict[str, Any] | None:
    """One-shot Bedrock call to fill in unknown services."""
    try:
        client = boto3.client("bedrock-runtime", region_name=REGION)
        prompt_lang = "Korean" if (language or "").lower().startswith("ko") else "English"
        system = (
            f"You are an AWS solutions architect. Reply in {prompt_lang}. "
            "Return ONE JSON object with keys: summary (<=240 chars), "
            "category (one of Compute, GenAI, Retrieval, Storage, Edge, Messaging, "
            "Security, Observability, Other), reference_url (string). "
            "No markdown, no extra text."
        )
        user_text = (
            f"AWS service: {name}\n"
            f"Use case context: {use_case or 'general AWS workload'}"
        )
        resp = client.invoke_model(
            modelId=EXPLAIN_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 250,
                "system": system,
                "messages": [{"role": "user", "content": user_text}],
            }),
        )
        payload = json.loads(resp["body"].read())
        text = ""
        for block in payload.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                break
        # Extract JSON from model response.
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:].strip()
        obj = json.loads(text) if text else {}
        if not isinstance(obj, dict):
            return None
        return {
            "service_id": _normalize_service_id(name),
            "service_name": name,
            "summary": str(obj.get("summary", ""))[:400],
            "category": str(obj.get("category", "Other")),
            "reference_urls": [str(obj.get("reference_url"))] if obj.get("reference_url") else [],
            "source": "llm_fallback",
        }
    except Exception as exc:
        print(f"[explain_aws_services] Bedrock fallback failed for {name}: {exc}")
        return None


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point for explain_aws_services."""
    try:
        raw = event.get("inputPayload", "{}")
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        params = json.loads(raw) if isinstance(raw, str) else (raw or {})

        services_raw = params.get("services", [])
        use_case = str(params.get("use_case") or "")
        language = str(params.get("language") or "en")

        # Normalize the service list — accept list[str] or list[dict{service_name}]
        service_names: list[str] = []
        if isinstance(services_raw, list):
            seen: set[str] = set()
            for svc in services_raw:
                if isinstance(svc, dict):
                    name = str(svc.get("service_name") or svc.get("name") or svc.get("service_id") or "").strip()
                elif isinstance(svc, str):
                    name = svc.strip()
                else:
                    name = ""
                if not name:
                    continue
                key = name.lower()
                if key in seen:
                    continue
                seen.add(key)
                service_names.append(name)

        warnings: list[str] = []
        explanations: list[dict[str, Any]] = []
        source_mode = "static"

        # AWS Docs MCP support is stubbed — real MCP client would be added here.
        # For now, unconditionally fall through to static and optional LLM.
        if AWS_DOCS_MCP_ENDPOINT:
            warnings.append(
                "AWS_DOCS_MCP_ENDPOINT is set but MCP client is not wired in this "
                "Lambda — using static catalogue with LLM fallback."
            )

        if not service_names:
            warnings.append("No services provided")
            return {"outputPayload": json.dumps({
                "mode": "static",
                "explanations": [],
                "warnings": warnings,
            })}

        for name in service_names:
            static_item = _static_explanation(name)
            if static_item:
                explanations.append(static_item)
                continue

            # Unknown service — optionally call Bedrock once.
            if BEDROCK_EXPLAIN_FALLBACK != "off":
                llm_item = _bedrock_explanation(name, use_case, language)
                if llm_item:
                    explanations.append(llm_item)
                    source_mode = "llm_fallback"
                    warnings.append(
                        f"Static catalogue missed {name}; filled via Bedrock LLM fallback."
                    )
                    continue

            # Minimal placeholder (never drop a service from the response).
            explanations.append({
                "service_id": _normalize_service_id(name),
                "service_name": name,
                "summary": "",
                "category": "Other",
                "reference_urls": [],
                "source": "unknown",
            })
            warnings.append(f"No explanation available for {name}")

        return {"outputPayload": json.dumps({
            "mode": source_mode,
            "explanations": explanations,
            "warnings": warnings,
        })}

    except Exception as e:
        return {"outputPayload": json.dumps({
            "mode": "static",
            "explanations": [],
            "warnings": [f"handler_error: {type(e).__name__}: {e}"],
            "error": str(e),
        })}
