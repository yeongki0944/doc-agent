"""OnPublish Lambda — validates patches before AppSync Events delivery.

Validation rules (v2 upgrade):
1. operations[].path must be a valid Document_State path
2. version must match current DynamoDB version (version validation)
3. source must be one of: user_input, ai_recommended, calculated

On failure: patch is blocked, error published to docs/{docId}/status channel
with version conflict information.

Note: OnPublish performs version *validation*. The actual optimistic locking
happens at the Parent Orchestrator's DynamoDB update time.

Requirements: 10.5, 10.6, 9.3
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_SOURCES = {"user_input", "ai_recommended", "calculated"}

# Valid top-level path prefixes derived from Document_State schema.
VALID_PATH_PREFIXES = (
    "/meta/",
    "/sections/",
    "/staffing_plan/",
    "/completion_score",
    "/blocking_issues",
    "/warnings",
    "/mode",
    "/version",
)

# Valid section keys under /sections/ (from document_state.py Sections model).
VALID_SECTION_KEYS = {
    "cover",
    "executive_summary",
    "stakeholders",
    "success_criteria",
    "assumptions",
    "scope_of_work",
    "architecture",
    "milestones",
    "cost_breakdown",
    "acceptance",
    "resources_cost_estimates",
}

# Valid meta keys under /meta/.
VALID_META_KEYS = {"customer", "partner", "date"}

DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "doc-agent-documents")
APPSYNC_HTTP_ENDPOINT = os.environ.get("APPSYNC_HTTP_ENDPOINT", "")
APPSYNC_API_KEY = os.environ.get("APPSYNC_API_KEY", "")


# ---------------------------------------------------------------------------
# DynamoDB helpers
# ---------------------------------------------------------------------------

def _get_dynamodb_table():
    """Return a DynamoDB Table resource (lazy-initialised)."""
    region = os.environ.get("AWS_REGION", "ap-northeast-2")
    dynamodb = boto3.resource("dynamodb", region_name=region)
    return dynamodb.Table(DYNAMODB_TABLE)


def _get_current_version(doc_id: str, *, table=None) -> int | None:
    """Fetch the current version of a document from DynamoDB.

    Returns ``None`` when the document does not exist.
    """
    if table is None:
        table = _get_dynamodb_table()
    response = table.get_item(
        Key={"document_id": doc_id},
        ProjectionExpression="version",
    )
    item = response.get("Item")
    if item is None:
        return None
    return int(item.get("version", 0))


# ---------------------------------------------------------------------------
# Status publishing helper
# ---------------------------------------------------------------------------

def _publish_error_status(doc_id: str, errors: list[str], version_info: dict | None = None) -> None:
    """Publish an error status to ``docs/{docId}/status`` via AppSync Events.

    In environments without AppSync configured the error is logged instead.
    """
    channel = f"docs/{doc_id}/status"
    payload: dict[str, Any] = {
        "doc_id": doc_id,
        "status": "error",
        "errors": errors,
    }
    if version_info:
        payload["version_conflict"] = version_info

    if APPSYNC_HTTP_ENDPOINT:
        try:
            _appsync_publish(channel, payload)
        except Exception:
            logger.exception("Failed to publish error status to AppSync")
    else:
        logger.info(
            "publish_status [dev] channel=%s payload=%s",
            channel,
            json.dumps(payload, default=str),
        )


def _appsync_publish(channel: str, payload: dict) -> None:
    """HTTP POST to AppSync Events endpoint."""
    import urllib.request

    url = f"{APPSYNC_HTTP_ENDPOINT}/event"
    body = json.dumps({"channel": channel, "events": [json.dumps(payload)]}).encode()
    headers = {
        "Content-Type": "application/json",
    }
    if APPSYNC_API_KEY:
        headers["x-api-key"] = APPSYNC_API_KEY

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=5) as resp:
        resp.read()


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_path(path: str) -> bool:
    """Check that *path* is a valid Document_State JSON-Patch path.

    Rules:
    - Must start with one of the known top-level prefixes.
    - ``/sections/<key>/...`` must reference a known section key.
    - ``/meta/<key>/...`` must reference a known meta key.
    """
    if not path or not path.startswith("/"):
        return False

    # Top-level prefix check
    if not any(path.startswith(p) for p in VALID_PATH_PREFIXES):
        return False

    # Deeper validation for /sections/ paths
    if path.startswith("/sections/"):
        remainder = path[len("/sections/"):]
        section_key = remainder.split("/")[0] if remainder else ""
        if section_key not in VALID_SECTION_KEYS:
            return False

    # Deeper validation for /meta/ paths
    if path.startswith("/meta/"):
        remainder = path[len("/meta/"):]
        meta_key = remainder.split("/")[0] if remainder else ""
        if meta_key not in VALID_META_KEYS:
            return False

    return True


def validate_source(source: str | None) -> bool:
    """Check that *source* is ``None`` or one of the allowed values."""
    return source is None or source in VALID_SOURCES


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------

def handler(event: dict[str, Any], context: Any, *, _table=None) -> dict[str, Any]:
    """Lambda handler for AppSync Events OnPublish.

    Parameters
    ----------
    event : dict
        The AppSync Events payload containing the patch.
    context : Any
        Lambda context (unused).
    _table : optional
        Injected DynamoDB table for testing.
    """
    try:
        patch = event.get("payload", event)
        doc_id = patch.get("doc_id", "")
        operations = patch.get("operations", [])
        patch_version = patch.get("version")

        errors: list[str] = []

        # --- 1. Validate operations ---
        for i, op in enumerate(operations):
            path = op.get("path", "")
            source = op.get("source")

            if not validate_path(path):
                errors.append(f"op[{i}]: invalid path '{path}'")

            if not validate_source(source):
                errors.append(f"op[{i}]: invalid source '{source}', allowed: {sorted(VALID_SOURCES)}")

        # --- 2. Version validation against DynamoDB ---
        version_info: dict[str, Any] | None = None
        if doc_id and patch_version is not None:
            try:
                current_version = _get_current_version(doc_id, table=_table)
                if current_version is not None and int(patch_version) != current_version:
                    version_info = {
                        "expected": int(patch_version),
                        "actual": current_version,
                    }
                    errors.append(
                        f"version mismatch: patch version {patch_version} "
                        f"!= current version {current_version}"
                    )
            except Exception as exc:
                logger.warning("DynamoDB version check failed for doc_id=%s: %s", doc_id, exc)
                # Non-fatal: allow patch through if DynamoDB is unreachable
        elif patch_version is not None and not doc_id:
            errors.append("doc_id is required for version validation")

        # --- 3. Result ---
        if errors:
            logger.warning("Patch blocked for doc_id=%s: %s", doc_id, errors)
            _publish_error_status(doc_id, errors, version_info)
            return {
                "statusCode": 400,
                "body": json.dumps({
                    "blocked": True,
                    "errors": errors,
                    "version_conflict": version_info,
                }),
            }

        return {
            "statusCode": 200,
            "body": json.dumps({"blocked": False, "version": patch_version}),
        }

    except Exception as e:
        logger.exception("OnPublish handler error")
        error_msg = str(e)
        try:
            payload = event.get("payload") or event
            doc_id = payload.get("doc_id", "unknown") if isinstance(payload, dict) else "unknown"
        except Exception:
            doc_id = "unknown"
        _publish_error_status(doc_id, [error_msg])
        return {
            "statusCode": 500,
            "body": json.dumps({"blocked": True, "error": error_msg}),
        }
