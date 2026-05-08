"""ProgressPublisher — real-time agent progress reporting.

Publishes progress events to DynamoDB (persistence) and AppSync (real-time).
Used by all sub-agents to report what they're doing step by step.

Three levels of granularity are supported, all sharing the same AppSync
``/docs/{docId}/chat`` channel so the frontend can render them in a single
thinking timeline:

1. High-level checkpoints from the Orchestrator / handler.py:
   ``type: "progress"`` (e.g. "📋 정보 수집 시작")
2. Model call events emitted from Strands hooks:
   ``type: "model_call_start" | "model_call_end"``
3. Tool call events emitted from Strands hooks:
   ``type: "tool_call_start" | "tool_call_end"``
4. Token / reasoning deltas emitted from Strands callback_handler (batched):
   ``type: "token_delta" | "reasoning_delta"``

Usage (high-level):

    progress = ProgressPublisher(doc_id="doc-xxx", table=dynamodb_table)
    progress.publish("discovery_agent", "고객사 '광동' 확인")

Usage (sub-agent wiring):

    from agent.lib.progress import (
        make_runtime_callback_handler,
        RuntimeProgressHooks,
    )

    self.agent = Agent(
        model=CHILD_MODEL,
        system_prompt=PROMPT,
        callback_handler=make_runtime_callback_handler("discovery_agent"),
        hooks=[RuntimeProgressHooks("discovery_agent")],
    )

At request entry the Orchestrator sets the contextvar so any downstream
Strands Agent invocation picks up the current publisher automatically:

    from agent.lib.progress import set_current_publisher
    set_current_publisher(ProgressPublisher(doc_id=..., table=...))
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import threading
import time
import urllib.request
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AppSync config
# ---------------------------------------------------------------------------

def _get_appsync_config() -> tuple[str, str]:
    """Lazy load AppSync config — ensures env vars are set by entrypoint."""
    return (
        os.environ.get("APPSYNC_HTTP_ENDPOINT", "") or os.environ.get("APPSYNC_HTTP_URL", ""),
        os.environ.get("APPSYNC_API_KEY", ""),
    )


# ---------------------------------------------------------------------------
# ProgressPublisher — thread-safe with batched delta publishing
# ---------------------------------------------------------------------------

# Token/reasoning deltas are extremely frequent (one per Bedrock stream chunk).
# We batch them within a short window to protect AppSync throttling and to
# keep the frontend from being flooded with tiny events.
_DELTA_BATCH_WINDOW_SEC = 0.12  # 120ms
_DELTA_MAX_CHARS = 400          # flush a batch if it exceeds this size


class ProgressPublisher:
    """Publishes agent progress to DynamoDB + AppSync.

    Thread-safe. Owns a small background flusher for token / reasoning
    deltas so that very frequent deltas do not spam AppSync.
    """

    def __init__(self, doc_id: str, table: Any = None) -> None:
        self.doc_id = doc_id
        self._table = table
        self._lock = threading.Lock()
        # Pending delta batches, keyed by (agent, kind) — kind ∈ {"token", "reasoning"}
        self._delta_buffer: dict[tuple[str, str], list[str]] = {}
        self._last_flush_at: dict[tuple[str, str], float] = {}

    # ------------------------------------------------------------------
    # High-level progress (orchestrator / sub-agent checkpoints)
    # ------------------------------------------------------------------

    def publish(self, agent: str, message: str, step: str = "") -> None:
        """Publish a progress event."""
        print(f"[progress] agent={agent} step={step} message={message}")
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
        self._post_appsync({
            "type": "progress",
            "agent": agent,
            "step": step,
            "message": message,
        })

    def complete(self, agent: str, message: str = "") -> None:
        """Mark agent as complete for this step."""
        self.publish(agent, message or f"✅ {agent} 완료", step="done")

    # ------------------------------------------------------------------
    # Strands hook-sourced events
    # ------------------------------------------------------------------

    def model_call_start(self, agent: str, model_id: str = "") -> None:
        self._post_appsync({
            "type": "model_call_start",
            "agent": agent,
            "model_id": model_id,
            "message": f"🧠 {agent} — 모델 호출 시작",
        })

    def model_call_end(
        self,
        agent: str,
        model_id: str = "",
        usage: dict | None = None,
        duration_ms: int | None = None,
    ) -> None:
        self._post_appsync({
            "type": "model_call_end",
            "agent": agent,
            "model_id": model_id,
            "usage": usage or {},
            "duration_ms": duration_ms or 0,
            "message": f"✅ {agent} — 모델 응답 완료",
        })

    def tool_call_start(self, agent: str, tool_name: str, tool_input: Any = None) -> None:
        safe_input = _safe_truncate(tool_input, 200) if tool_input is not None else ""
        self._post_appsync({
            "type": "tool_call_start",
            "agent": agent,
            "tool_name": tool_name,
            "tool_input_preview": safe_input,
            "message": f"🔧 {agent} → 도구 '{tool_name}' 호출",
        })

    def tool_call_end(
        self,
        agent: str,
        tool_name: str,
        success: bool = True,
        tool_output: Any = None,
        error: str = "",
    ) -> None:
        safe_output = _safe_truncate(tool_output, 200) if tool_output is not None else ""
        self._post_appsync({
            "type": "tool_call_end",
            "agent": agent,
            "tool_name": tool_name,
            "success": success,
            "tool_output_preview": safe_output,
            "error": _safe_truncate(error, 200) if error else "",
            "message": (
                f"✅ {agent} ← 도구 '{tool_name}' 완료"
                if success
                else f"⚠ {agent} ← 도구 '{tool_name}' 실패"
            ),
        })

    # ------------------------------------------------------------------
    # Batched delta publishing (token / reasoning stream)
    # ------------------------------------------------------------------

    def token_delta(self, agent: str, text: str) -> None:
        """Buffer a chat-token delta; flush on window/size."""
        if not text:
            return
        self._append_delta(agent, "token", text)

    def reasoning_delta(self, agent: str, text: str) -> None:
        """Buffer a reasoning (Claude thinking) delta; flush on window/size."""
        if not text:
            return
        self._append_delta(agent, "reasoning", text)

    def flush(self) -> None:
        """Flush all pending delta batches immediately."""
        keys_to_flush: list[tuple[str, str]] = []
        with self._lock:
            keys_to_flush = list(self._delta_buffer.keys())
        for key in keys_to_flush:
            self._flush_key(key, force=True)

    def _append_delta(self, agent: str, kind: str, text: str) -> None:
        key = (agent, kind)
        now = time.time()
        should_flush = False
        with self._lock:
            buf = self._delta_buffer.setdefault(key, [])
            buf.append(text)
            last = self._last_flush_at.get(key, 0.0)
            total_chars = sum(len(t) for t in buf)
            if (now - last) >= _DELTA_BATCH_WINDOW_SEC or total_chars >= _DELTA_MAX_CHARS:
                should_flush = True
        if should_flush:
            self._flush_key(key, force=False)

    def _flush_key(self, key: tuple[str, str], force: bool) -> None:
        agent, kind = key
        with self._lock:
            buf = self._delta_buffer.get(key) or []
            if not buf:
                return
            combined = "".join(buf)
            self._delta_buffer[key] = []
            self._last_flush_at[key] = time.time()
        if not combined:
            return
        event_type = "token_delta" if kind == "token" else "reasoning_delta"
        self._post_appsync({
            "type": event_type,
            "agent": agent,
            "delta": combined,
        })

    # ------------------------------------------------------------------
    # AppSync HTTP POST
    # ------------------------------------------------------------------

    def _post_appsync(self, event: dict) -> None:
        appsync_url, api_key = _get_appsync_config()
        if not appsync_url or not api_key:
            logger.debug("progress: AppSync not configured")
            return
        try:
            url = f"{appsync_url}/event"
            channel = f"/docs/{self.doc_id}/chat"
            payload = json.dumps({
                "channel": channel,
                "events": [json.dumps(event)],
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
            urllib.request.urlopen(req, timeout=2)
        except Exception as e:
            # Never raise — progress is best-effort
            logger.debug("progress AppSync publish failed: %s", e)


# ---------------------------------------------------------------------------
# Context propagation — Strands callbacks/hooks discover the active publisher
# via a ContextVar set by the orchestrator at request entry.
# ---------------------------------------------------------------------------

_current_publisher: contextvars.ContextVar[Optional[ProgressPublisher]] = contextvars.ContextVar(
    "doc_agent_current_progress_publisher", default=None
)


def set_current_publisher(publisher: Optional[ProgressPublisher]) -> contextvars.Token:
    """Set the current publisher and return a reset token."""
    return _current_publisher.set(publisher)


def reset_current_publisher(token: contextvars.Token) -> None:
    try:
        _current_publisher.reset(token)
    except Exception:
        pass


def get_current_publisher() -> Optional[ProgressPublisher]:
    return _current_publisher.get()


# ---------------------------------------------------------------------------
# Strands callback_handler factory
# ---------------------------------------------------------------------------

def make_runtime_callback_handler(agent_name: str) -> Callable[..., None]:
    """Build a Strands-compatible callback_handler for an agent.

    Forwards token and reasoning deltas to the current ``ProgressPublisher``
    (if any) via batched publishing. Silently no-ops when no publisher is
    set so unit tests running without a Runtime context are unaffected.
    """

    def _handler(**kwargs: Any) -> None:
        publisher = get_current_publisher()
        if publisher is None:
            return
        try:
            reasoning_text = kwargs.get("reasoningText")
            data = kwargs.get("data")
            complete = bool(kwargs.get("complete"))
            # Reasoning stream (Claude extended thinking)
            if isinstance(reasoning_text, str) and reasoning_text:
                publisher.reasoning_delta(agent_name, reasoning_text)
            # Response token stream
            if isinstance(data, str) and data:
                publisher.token_delta(agent_name, data)
            # Flush all batches when the turn ends
            if complete:
                publisher.flush()
        except Exception as exc:
            # Never break model streaming because of progress emission
            logger.debug("callback_handler error: %s", exc)

    return _handler


# ---------------------------------------------------------------------------
# Strands HookProvider — before/after model and tool calls
# ---------------------------------------------------------------------------

class RuntimeProgressHooks:
    """Strands HookProvider that emits model/tool call events.

    Registers callbacks on the four event types that matter for a live
    thinking timeline: ``BeforeModelCallEvent``, ``AfterModelCallEvent``,
    ``BeforeToolCallEvent``, ``AfterToolCallEvent``.
    """

    def __init__(self, agent_name: str) -> None:
        self.agent_name = agent_name
        self._model_call_started_at: dict[str, float] = {}
        self._tool_call_started_at: dict[str, float] = {}

    def register_hooks(self, registry: Any) -> None:
        """Strands calls this at Agent construction to register hooks.

        We import the event types lazily so importing progress.py does not
        require strands to be installed (useful for Lambda handler which
        imports ProgressPublisher but not strands).
        """
        try:
            from strands.hooks.events import (
                BeforeModelCallEvent,
                AfterModelCallEvent,
                BeforeToolCallEvent,
                AfterToolCallEvent,
            )
        except Exception as exc:
            logger.debug("RuntimeProgressHooks: strands hooks unavailable: %s", exc)
            return

        registry.add_callback(BeforeModelCallEvent, self._on_before_model)
        registry.add_callback(AfterModelCallEvent, self._on_after_model)
        registry.add_callback(BeforeToolCallEvent, self._on_before_tool)
        registry.add_callback(AfterToolCallEvent, self._on_after_tool)

    # --- Model ---

    def _on_before_model(self, event: Any) -> None:
        publisher = get_current_publisher()
        if publisher is None:
            return
        model_id = _extract_attr(event, "model_id", "modelId", "model", default="")
        invocation_id = _extract_attr(event, "invocation_id", "id", default="")
        self._model_call_started_at[str(invocation_id)] = time.time()
        try:
            publisher.model_call_start(self.agent_name, str(model_id))
        except Exception:
            pass

    def _on_after_model(self, event: Any) -> None:
        publisher = get_current_publisher()
        if publisher is None:
            return
        model_id = _extract_attr(event, "model_id", "modelId", "model", default="")
        invocation_id = _extract_attr(event, "invocation_id", "id", default="")
        started = self._model_call_started_at.pop(str(invocation_id), None)
        duration_ms = int((time.time() - started) * 1000) if started else 0
        usage_raw = _extract_attr(event, "usage", default=None)
        usage: dict = {}
        if isinstance(usage_raw, dict):
            usage = {
                k: v for k, v in usage_raw.items()
                if isinstance(v, (int, float, str))
            }
        try:
            publisher.model_call_end(
                self.agent_name,
                model_id=str(model_id),
                usage=usage,
                duration_ms=duration_ms,
            )
            # Flush any pending deltas when a model call completes so users see
            # the full reasoning/tokens for the turn.
            publisher.flush()
        except Exception:
            pass

    # --- Tool ---

    def _on_before_tool(self, event: Any) -> None:
        publisher = get_current_publisher()
        if publisher is None:
            return
        tool_name, tool_input = _extract_tool_info(event)
        invocation_id = _extract_attr(event, "invocation_id", "id", default="")
        self._tool_call_started_at[str(invocation_id)] = time.time()
        try:
            publisher.tool_call_start(self.agent_name, str(tool_name), tool_input)
        except Exception:
            pass

    def _on_after_tool(self, event: Any) -> None:
        publisher = get_current_publisher()
        if publisher is None:
            return
        tool_name, _tool_input = _extract_tool_info(event)
        invocation_id = _extract_attr(event, "invocation_id", "id", default="")
        self._tool_call_started_at.pop(str(invocation_id), None)
        tool_output = _extract_attr(event, "result", "tool_result", "output", default=None)
        error = _extract_attr(event, "error", default="")
        success = not error
        try:
            publisher.tool_call_end(
                self.agent_name,
                str(tool_name),
                success=success,
                tool_output=tool_output,
                error=str(error) if error else "",
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_truncate(value: Any, max_len: int = 200) -> str:
    try:
        if isinstance(value, (dict, list)):
            s = json.dumps(value, ensure_ascii=False)
        else:
            s = str(value)
    except Exception:
        s = repr(value)
    if len(s) > max_len:
        return s[:max_len] + "..."
    return s


def _extract_attr(obj: Any, *names: str, default: Any = None) -> Any:
    """Try attribute access then dict access for each candidate name."""
    for name in names:
        try:
            val = getattr(obj, name)
            if val is not None:
                return val
        except Exception:
            pass
        try:
            if isinstance(obj, dict) and name in obj:
                val = obj[name]
                if val is not None:
                    return val
        except Exception:
            pass
    return default


def _extract_tool_info(event: Any) -> tuple[str, Any]:
    """Best-effort extraction of (tool_name, tool_input) from a Strands event."""
    # 1. Flat attrs
    tool_name = _extract_attr(event, "tool_name", "name", default="")
    tool_input = _extract_attr(event, "tool_input", "input", default=None)
    if tool_name:
        return str(tool_name), tool_input
    # 2. Nested ``tool_use`` dict
    tu = _extract_attr(event, "tool_use", "toolUse", default=None)
    if isinstance(tu, dict):
        return str(tu.get("name") or tu.get("toolName") or ""), tu.get("input")
    # 3. Nested selected_tool
    sel = _extract_attr(event, "selected_tool", "tool", default=None)
    if isinstance(sel, dict):
        return str(sel.get("name") or ""), sel.get("input")
    if sel is not None:
        return str(getattr(sel, "name", "") or ""), getattr(sel, "input", None)
    return "", None
