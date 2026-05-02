"""ProgressPublisher — real-time agent progress reporting.

Publishes progress events to DynamoDB (persistence) and AppSync (real-time).
Used by all sub-agents to report what they're doing step by step.

Usage:
    progress = ProgressPublisher(doc_id="doc-xxx", table=dynamodb_table)
    progress.publish("discovery_agent", "고객사 '광동' 확인")
    progress.publish("discovery_agent", "meta.customer 변경 완료")
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _get_appsync_config():
    """Lazy load AppSync config — ensures env vars are set by entrypoint."""
    return (
        os.environ.get("APPSYNC_HTTP_ENDPOINT", "") or os.environ.get("APPSYNC_HTTP_URL", ""),
        os.environ.get("APPSYNC_API_KEY", ""),
    )


class ProgressPublisher:
    """Publishes agent progress to DynamoDB + AppSync."""

    def __init__(self, doc_id: str, table: Any = None) -> None:
        self.doc_id = doc_id
        self._table = table

    def publish(self, agent: str, message: str, step: str = "") -> None:
        """Publish a progress event."""
        print(f"[progress] agent={agent} step={step} message={message}")

        # 1. Update DynamoDB
        if self._table:
            try:
                self._table.update_item(
                    Key={"document_id": self.doc_id},
                    UpdateExpression="SET agent_status = :s, agent_active = :a, agent_message = :m",
                    ExpressionAttributeValues={
                        ":s": "processing",
                        ":a": agent,
                        ":m": message,
                    },
                )
            except Exception as e:
                logger.debug("progress DynamoDB update failed: %s", e)

        # 2. Publish to AppSync
        self._publish_appsync(agent, message, step)

    def complete(self, agent: str, message: str = "") -> None:
        """Mark agent as complete for this step."""
        self.publish(agent, message or f"✅ {agent} 완료", step="done")

    def _publish_appsync(self, agent: str, message: str, step: str) -> None:
        appsync_url, api_key = _get_appsync_config()
        print(f"[progress] appsync config: url={bool(appsync_url)} key={bool(api_key)}")
        if not appsync_url or not api_key:
            logger.debug("progress: AppSync not configured (url=%s key=%s)", bool(appsync_url), bool(api_key))
            return
        try:
            url = f"{appsync_url}/event"
            channel = f"/docs/{self.doc_id}/chat"
            payload = json.dumps({
                "channel": channel,
                "events": [json.dumps({
                    "type": "progress",
                    "agent": agent,
                    "step": step,
                    "message": message,
                })],
            })
            req = urllib.request.Request(
                url,
                data=payload.encode(),
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": api_key,
                },
            )
            urllib.request.urlopen(req, timeout=3)
        except Exception as e:
            print(f"[progress] AppSync publish failed: {e}")
            logger.debug("progress AppSync publish failed: %s", e)
