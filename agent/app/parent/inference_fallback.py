"""Inference profile fallback mechanism.

Provides a helper that tries the primary inference profile, catches
transient failures, and falls back to a configured alternative profile
or enters degraded mode with a user-visible status message.

When fallback is activated, a ``degraded`` status is published to
``docs/{docId}/status`` via the orchestrator's publish_status method.

Requirements: 1.7
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from agent.lib.schema.patch import AgentStatus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class InferenceProfileUnavailableError(Exception):
    """Raised when both primary and fallback inference profiles fail."""

    def __init__(self, primary: str, fallback: str | None, cause: Exception):
        self.primary = primary
        self.fallback = fallback
        self.cause = cause
        parts = [f"Primary profile '{primary}' unavailable"]
        if fallback:
            parts.append(f"fallback profile '{fallback}' also failed")
        else:
            parts.append("no fallback profile configured")
        super().__init__("; ".join(parts) + f": {cause}")


# ---------------------------------------------------------------------------
# Fallback result
# ---------------------------------------------------------------------------

@dataclass
class FallbackResult:
    """Result of an inference call that may have used a fallback profile."""

    response: Any = None
    model_used: str = ""
    is_fallback: bool = False
    is_degraded: bool = False
    error_message: str = ""


# ---------------------------------------------------------------------------
# InferenceProfileFallback
# ---------------------------------------------------------------------------

class InferenceProfileFallback:
    """Manages inference profile fallback for a single model role.

    Parameters
    ----------
    primary : str
        Primary inference profile ID.
    fallback : str
        Fallback inference profile ID. Empty string means no fallback
        (degraded mode on primary failure).
    role : str
        Human-readable role label (e.g. ``"parent"``, ``"child"``).
    """

    def __init__(self, primary: str, fallback: str = "", role: str = "model") -> None:
        self.primary = primary
        self.fallback = fallback or ""
        self.role = role
        self._degraded = False

    @property
    def is_degraded(self) -> bool:
        return self._degraded

    async def invoke(
        self,
        call_fn: Callable[[str], Awaitable[Any]],
    ) -> FallbackResult:
        """Try the primary profile, fall back if it fails.

        Parameters
        ----------
        call_fn : async callable
            An async function that accepts a model ID string and returns
            the inference result.  It should raise on transient failures
            (e.g. ``botocore.exceptions.ClientError``).

        Returns
        -------
        FallbackResult
            Contains the response, which model was used, and whether
            fallback or degraded mode was activated.
        """
        # --- Try primary ---
        try:
            response = await call_fn(self.primary)
            self._degraded = False
            return FallbackResult(
                response=response,
                model_used=self.primary,
                is_fallback=False,
                is_degraded=False,
            )
        except Exception as primary_err:
            last_error = primary_err
            logger.warning(
                "%s primary profile '%s' failed: %s",
                self.role,
                self.primary,
                primary_err,
            )

        # --- Try fallback (if configured) ---
        if self.fallback:
            try:
                response = await call_fn(self.fallback)
                self._degraded = True
                logger.info(
                    "%s using fallback profile '%s'",
                    self.role,
                    self.fallback,
                )
                return FallbackResult(
                    response=response,
                    model_used=self.fallback,
                    is_fallback=True,
                    is_degraded=True,
                    error_message=(
                        f"{self.role} inference profile이 일시적으로 사용 불가하여 "
                        f"대체 모델({self.fallback})로 전환되었습니다."
                    ),
                )
            except Exception as fallback_err:
                logger.error(
                    "%s fallback profile '%s' also failed: %s",
                    self.role,
                    self.fallback,
                    fallback_err,
                )
                self._degraded = True
                raise InferenceProfileUnavailableError(
                    primary=self.primary,
                    fallback=self.fallback,
                    cause=fallback_err,
                )

        # --- No fallback configured → degraded mode ---
        self._degraded = True
        raise InferenceProfileUnavailableError(
            primary=self.primary,
            fallback=None,
            cause=last_error,
        )

    def build_degraded_status_payload(self, doc_id: str) -> dict:
        """Build the status payload for degraded mode notification.

        Returns a dict suitable for publishing to ``docs/{docId}/status``.
        """
        return {
            "doc_id": doc_id,
            "status": AgentStatus.degraded.value,
            "message": (
                f"{self.role} inference profile이 일시적으로 사용 불가합니다. "
                "일부 기능이 제한될 수 있습니다."
            ),
            "role": self.role,
        }
