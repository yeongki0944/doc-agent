"""Gateway Lambda: generate_architecture_diagram

Generates a .drawio XML diagram and a preview artifact (.png placeholder)
from an architecture description or service list, then stores both in S3.

Falls back to an *engineer-friendly architecture draft* (plain structured
JSON that the frontend and Reviewer can render without Draw.io) if diagram
generation is skipped or fails.

Input (via event["inputPayload"] JSON):
    {
        "doc_id": "doc-001",
        "services": ["AWS Lambda", "Amazon DynamoDB", ...],
        "architecture_description": "optional text description",
        "existing_drawio": "optional raw .drawio XML to enhance",
        "use_case": "RAG chatbot",               # optional
        "skip_drawio": false                       # optional — force engineer draft only
    }

Output:
    {
        "mode": "drawio" | "engineer_draft",
        "drawio_s3_key": "docs/doc-001/diagrams/architecture.drawio" | "",
        "preview_s3_key": "docs/doc-001/diagrams/architecture.png"    | "",
        "services_extracted": ["AWS Lambda", ...],
        "engineer_draft": {
            "use_case": "RAG chatbot",
            "layers": [
                {"name": "Edge", "services": ["Amazon API Gateway"]},
                ...
            ],
            "flows": [
                "Client calls API Gateway",
                "API Gateway invokes AWS Lambda",
                ...
            ],
            "notes": ["..."],
            "warning": "drawio generation skipped/failed — engineer draft only"
        }
    }
"""

from __future__ import annotations

import json
import os
from typing import Any

import boto3

ARTIFACTS_BUCKET = os.environ.get("ARTIFACTS_BUCKET", "doc-agent-artifacts")
REGION = os.environ.get("AWS_REGION", "ap-northeast-2")

# Optional: Draw.io MCP endpoint. If configured a future revision can POST
# a draft here and receive a higher-quality diagram. Currently unused —
# we still return drawio XML built locally, and engineer draft as fallback.
DRAWIO_MCP_ENDPOINT = os.environ.get("DRAWIO_MCP_ENDPOINT", "")


# ---------------------------------------------------------------------------
# Service → layer categorisation (engineer-friendly)
# ---------------------------------------------------------------------------

_LAYER_RULES: list[tuple[str, list[str]]] = [
    ("Edge",        ["api gateway", "cloudfront", "appsync"]),
    ("Compute",     ["lambda", "ecs", "eks", "ec2", "step functions"]),
    ("GenAI",       ["bedrock", "agentcore", "sagemaker"]),
    ("Retrieval",   ["opensearch", "kendra", "aurora", "rds", "dynamodb"]),
    ("Storage",     ["s3", "efs"]),
    ("Messaging",   ["sqs", "sns", "eventbridge", "kinesis"]),
    ("Security",    ["iam", "kms", "waf", "secrets manager", "cognito"]),
    ("Observability", ["cloudwatch", "x-ray", "xray"]),
]


def _classify_layer(name: str) -> str:
    lc = name.lower()
    for layer, keywords in _LAYER_RULES:
        if any(k in lc for k in keywords):
            return layer
    return "Other"


def _normalize_service_list(raw: Any) -> list[str]:
    out: list[str] = []
    if not isinstance(raw, list):
        return out
    seen: set[str] = set()
    for svc in raw:
        if isinstance(svc, dict):
            name = svc.get("service_name") or svc.get("name") or svc.get("service_id") or ""
        else:
            name = str(svc)
        name = (name or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def _build_engineer_draft(
    services: list[str],
    architecture_description: str,
    use_case: str,
    warning: str = "",
) -> dict[str, Any]:
    """Build an engineer-friendly architecture draft.

    This is the safe fallback when Draw.io generation cannot be produced or
    its quality is insufficient. The frontend Architecture Preview can render
    it as a layered list + numbered flow, and the Reviewer can use it for
    architecture-cost alignment checks without needing any image rendering.
    """
    layers_map: dict[str, list[str]] = {}
    for svc in services:
        layer = _classify_layer(svc)
        layers_map.setdefault(layer, []).append(svc)

    ordered_layers = [
        name for name, _ in _LAYER_RULES + [("Other", [])] if name in layers_map
    ]
    layers = [{"name": name, "services": layers_map[name]} for name in ordered_layers]

    # Build a generic flow skeleton based on which layers are present.
    flows: list[str] = []
    if "Edge" in layers_map:
        flows.append("Client calls edge layer (" + ", ".join(layers_map["Edge"]) + ")")
    if "Compute" in layers_map:
        src = layers_map.get("Edge", ["Client"])[0]
        flows.append(
            f"{src} invokes compute layer ("
            + ", ".join(layers_map["Compute"])
            + ")"
        )
    if "GenAI" in layers_map:
        src = layers_map.get("Compute", ["Caller"])[0]
        flows.append(
            f"{src} calls GenAI service ("
            + ", ".join(layers_map["GenAI"])
            + ")"
        )
    if "Retrieval" in layers_map:
        src = layers_map.get("Compute", ["Caller"])[0]
        flows.append(
            f"{src} retrieves context from ("
            + ", ".join(layers_map["Retrieval"])
            + ")"
        )
    if "Storage" in layers_map:
        flows.append(
            "Source artefacts stored in "
            + ", ".join(layers_map["Storage"])
        )
    if "Observability" in layers_map:
        flows.append(
            "Operational signals emitted to "
            + ", ".join(layers_map["Observability"])
        )

    notes: list[str] = []
    if architecture_description:
        notes.append(architecture_description.strip()[:500])
    if "Security" not in layers_map:
        notes.append("Security (IAM / KMS) layer not listed — confirm access control and encryption.")
    if "Observability" not in layers_map:
        notes.append("Observability (CloudWatch) not listed — add monitoring before production.")

    draft: dict[str, Any] = {
        "use_case": use_case or "",
        "layers": layers,
        "flows": flows,
        "notes": notes,
    }
    if warning:
        draft["warning"] = warning
    return draft


# ---------------------------------------------------------------------------
# Draw.io XML builder
# ---------------------------------------------------------------------------

def _build_drawio_xml(services: list[str], description: str = "") -> str:
    """Build a minimal .drawio XML with one node per AWS service."""
    cells: list[str] = []
    x, y = 100, 100
    cell_id = 2  # 0 and 1 are reserved in .drawio

    for svc in services:
        safe = (svc or "").replace('"', "&quot;")
        cells.append(
            f'<mxCell id="{cell_id}" value="{safe}" '
            f'style="rounded=1;whiteSpace=wrap;" '
            f'vertex="1" parent="1">'
            f'<mxGeometry x="{x}" y="{y}" width="160" height="60" as="geometry"/>'
            f'</mxCell>'
        )
        x += 200
        if x > 700:
            x = 100
            y += 100
        cell_id += 1

    body = "\n".join(cells)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<mxfile><diagram name="Architecture">'
        '<mxGraphModel><root>'
        '<mxCell id="0"/><mxCell id="1" parent="0"/>'
        f'{body}'
        '</root></mxGraphModel></diagram></mxfile>'
    )


def _generate_preview_placeholder(services: list[str]) -> bytes:
    """Generate a minimal PNG placeholder for the architecture preview."""
    # Minimal valid 1x1 transparent PNG
    return (
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
        b'\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89'
        b'\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01'
        b'\r\n\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
    )


def _upload_to_s3(bucket: str, key: str, body: bytes | str, content_type: str) -> None:
    """Upload content to S3."""
    s3 = boto3.client("s3", region_name=REGION)
    if isinstance(body, str):
        body = body.encode("utf-8")
    s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType=content_type)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point for generate_architecture_diagram."""
    try:
        raw = event.get("inputPayload", "{}")
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        params = json.loads(raw) if isinstance(raw, str) else (raw or {})

        doc_id = str(params.get("doc_id") or "unknown")
        services_in = params.get("services", [])
        description = str(params.get("architecture_description") or "")
        use_case = str(params.get("use_case") or "")
        existing_drawio = params.get("existing_drawio")
        skip_drawio = bool(params.get("skip_drawio") or False)

        services = _normalize_service_list(services_in)

        # If no services at all, we cannot produce a meaningful drawio file —
        # return the engineer draft with a warning (still mode="engineer_draft").
        if not services and not existing_drawio:
            draft = _build_engineer_draft(
                services, description, use_case,
                warning="no services provided — engineer draft only",
            )
            return {"outputPayload": json.dumps({
                "mode": "engineer_draft",
                "drawio_s3_key": "",
                "preview_s3_key": "",
                "services_extracted": [],
                "engineer_draft": draft,
            })}

        # If caller explicitly requested no drawio, return engineer draft only.
        if skip_drawio:
            draft = _build_engineer_draft(
                services, description, use_case,
                warning="skip_drawio=true — engineer draft only",
            )
            return {"outputPayload": json.dumps({
                "mode": "engineer_draft",
                "drawio_s3_key": "",
                "preview_s3_key": "",
                "services_extracted": services,
                "engineer_draft": draft,
            })}

        # Attempt drawio generation. On failure we still return engineer draft.
        try:
            drawio_xml = existing_drawio if existing_drawio else _build_drawio_xml(services, description)
            drawio_key = f"docs/{doc_id}/diagrams/architecture.drawio"
            preview_key = f"docs/{doc_id}/diagrams/architecture.png"

            _upload_to_s3(ARTIFACTS_BUCKET, drawio_key, drawio_xml, "application/xml")
            preview_bytes = _generate_preview_placeholder(services)
            _upload_to_s3(ARTIFACTS_BUCKET, preview_key, preview_bytes, "image/png")

            # Engineer draft is still returned alongside — frontend and
            # Reviewer can use it regardless of drawio quality.
            draft = _build_engineer_draft(services, description, use_case)
            return {"outputPayload": json.dumps({
                "mode": "drawio",
                "drawio_s3_key": drawio_key,
                "preview_s3_key": preview_key,
                "services_extracted": services,
                "engineer_draft": draft,
            })}
        except Exception as draw_err:
            draft = _build_engineer_draft(
                services, description, use_case,
                warning=f"drawio generation failed: {type(draw_err).__name__}",
            )
            return {"outputPayload": json.dumps({
                "mode": "engineer_draft",
                "drawio_s3_key": "",
                "preview_s3_key": "",
                "services_extracted": services,
                "engineer_draft": draft,
                "error": str(draw_err),
            })}

    except Exception as e:
        return {"outputPayload": json.dumps({"error": str(e)})}
