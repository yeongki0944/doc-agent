"""Gateway Lambda: generate_architecture_diagram

Generates a .drawio XML diagram and a preview artifact (.png placeholder)
from an architecture description or service list, then stores both in S3.

Input (via event["inputPayload"] JSON):
    {
        "doc_id": "doc-001",
        "services": ["AWS Lambda", "Amazon DynamoDB", ...],
        "architecture_description": "optional text description",
        "existing_drawio": "optional raw .drawio XML to enhance"
    }

Output:
    {
        "drawio_s3_key": "docs/doc-001/diagrams/architecture.drawio",
        "preview_s3_key": "docs/doc-001/diagrams/architecture.png",
        "services_extracted": ["AWS Lambda", "Amazon DynamoDB", ...]
    }
"""

from __future__ import annotations

import json
import os
from typing import Any

import boto3

ARTIFACTS_BUCKET = os.environ.get("ARTIFACTS_BUCKET", "doc-agent-artifacts")
REGION = os.environ.get("AWS_REGION", "ap-northeast-2")


def _build_drawio_xml(services: list[str], description: str = "") -> str:
    """Build a minimal .drawio XML with one node per AWS service."""
    cells: list[str] = []
    x, y = 100, 100
    cell_id = 2  # 0 and 1 are reserved in .drawio

    for svc in services:
        cells.append(
            f'<mxCell id="{cell_id}" value="{svc}" '
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
    """Generate a minimal PNG placeholder for the architecture preview.

    A real implementation would render the .drawio to an image.
    This returns a 1x1 transparent PNG as a placeholder.
    """
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


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point for generate_architecture_diagram."""
    try:
        raw = event.get("inputPayload", "{}")
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        params = json.loads(raw)

        doc_id = params.get("doc_id", "unknown")
        services = params.get("services", [])
        description = params.get("architecture_description", "")
        existing_drawio = params.get("existing_drawio")

        # Use existing .drawio or generate new one
        if existing_drawio:
            drawio_xml = existing_drawio
        else:
            drawio_xml = _build_drawio_xml(services, description)

        # S3 keys
        drawio_key = f"docs/{doc_id}/diagrams/architecture.drawio"
        preview_key = f"docs/{doc_id}/diagrams/architecture.png"

        # Upload to S3
        _upload_to_s3(ARTIFACTS_BUCKET, drawio_key, drawio_xml, "application/xml")

        preview_bytes = _generate_preview_placeholder(services)
        _upload_to_s3(ARTIFACTS_BUCKET, preview_key, preview_bytes, "image/png")

        result = {
            "drawio_s3_key": drawio_key,
            "preview_s3_key": preview_key,
            "services_extracted": services,
        }
        return {"outputPayload": json.dumps(result)}

    except Exception as e:
        return {"outputPayload": json.dumps({"error": str(e)})}
