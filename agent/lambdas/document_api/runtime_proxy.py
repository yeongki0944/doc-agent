"""Runtime invocation proxy for document_api.

The document API owns HTTP compatibility, auth, CRUD, and history.
Document mutations from chat go through the v2 ParentOrchestrator
runtime path behind this proxy.
"""

from __future__ import annotations

import os
from typing import Any, Protocol


class RuntimeProxy(Protocol):
    def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...


class LocalRuntimeProxy:
    """Call the in-process AgentCore Runtime entrypoint.

    This is the default for local development and unit tests. Deployed
    environments can swap this proxy with an endpoint-backed implementation
    without changing document_api routing.
    """

    def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        from agent.app.parent.runtime import invoke

        return invoke(payload)


def get_runtime_proxy() -> RuntimeProxy:
    proxy_mode = os.environ.get("DOCUMENT_API_RUNTIME_PROXY", "local")
    if proxy_mode != "local":
        raise RuntimeError(f"unsupported runtime proxy mode: {proxy_mode}")
    return LocalRuntimeProxy()
