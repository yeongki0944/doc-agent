"""Formatter Agent — document ordering and DOCX export.

Refactored as a ``strands.Agent()`` logical agent within the Parent Runtime.
Sorts Document_State sections into APN template order, calls Gateway's
``export_docx`` tool via the common ``AgentCoreGatewayClient``, stores
result in S3, and returns a download link.

Requirements: 13.3, 13.4
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

from strands import Agent

from agent.lib.gateway.agentcore_gateway import AgentCoreGatewayClient
from agent.lib.schema.document_state import DocumentState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model configuration
# ---------------------------------------------------------------------------

CHILD_MODEL: str = os.environ.get(
    "CHILD_MODEL",
    "apac.anthropic.claude-3-5-sonnet-20241022-v2:0",
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

APN_SECTION_ORDER = [
    "cover", "executive_summary", "stakeholders", "success_criteria",
    "assumptions", "scope_of_work", "architecture", "milestones",
    "cost_breakdown", "acceptance", "resources_cost_estimates",
]

# ---------------------------------------------------------------------------
# System prompt for the Formatter Agent
# ---------------------------------------------------------------------------

FORMATTER_PROMPT: str = """당신은 APN PoC Project Plan 문서 포맷 및 DOCX export 전문 에이전트입니다.

## 역할
1. Document_State의 섹션을 APN 템플릿 순서에 맞게 정렬합니다.
2. DOCX export를 위한 데이터를 준비합니다.
3. export 결과를 S3에 저장하고 다운로드 링크를 생성합니다.

## APN 템플릿 섹션 순서
1. Cover Page
2. Executive Summary
3. Stakeholders (Sponsor / Stakeholder / Team)
4. Success Criteria / KPIs
5. Assumptions & Risks
6. Scope of Work
7. Architecture
8. Milestones & Deliverables
9. Cost Breakdown
10. Acceptance Criteria
11. Resources & Cost Estimates

## 응답 형식
반드시 아래 JSON 형식으로만 응답하세요.

```json
{
  "analysis": "포맷 검증 결과 요약",
  "section_order_valid": true,
  "recommendations": ["포맷 개선 제안 목록"]
}
```
"""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ExportResult:
    """Result of a DOCX export operation."""
    success: bool = False
    s3_path: Optional[str] = None
    download_url: Optional[str] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Formatter Agent
# ---------------------------------------------------------------------------

class FormatterAgent:
    """Formats and exports Document_State as DOCX.

    Uses a ``strands.Agent()`` instance with CHILD_MODEL for LLM-powered
    formatting analysis. Core logic (section ordering, Gateway tool call)
    is deterministic.

    Requirements: 13.3, 13.4
    """

    def __init__(self) -> None:
        from agent.lib.progress import make_runtime_callback_handler, RuntimeProgressHooks
        self.agent = Agent(
            model=CHILD_MODEL,
            system_prompt=FORMATTER_PROMPT,
            callback_handler=make_runtime_callback_handler("formatter_agent"),
            hooks=[RuntimeProgressHooks("formatter_agent")],
        )

    async def export_docx(
        self,
        doc_state: DocumentState,
        gateway_client: AgentCoreGatewayClient,
    ) -> ExportResult:
        """Sort sections → call Gateway export_docx → return S3 path + download link.

        Steps:
          1. Order sections per APN template sequence
          2. Call the common Gateway client's ``export_docx`` tool
          3. Return S3 path and presigned download URL from the response

        On Gateway failure the current Document_State is preserved (no
        partial mutation) and an error is returned in ``ExportResult``.

        Requirements: 13.3, 13.4
        """
        ordered_sections = self._order_sections(doc_state)

        doc_id = doc_state.document_id
        version = doc_state.version

        params: dict[str, Any] = {
            "doc_id": doc_id,
            "version": version,
            "sections": ordered_sections,
        }

        result, error = await gateway_client.call_tool_safe(
            "export_docx", params
        )

        if error or result is None:
            logger.warning("export_docx Gateway call failed: %s", error)
            return ExportResult(
                success=False,
                error=error or "export_docx tool returned no result",
            )

        return ExportResult(
            success=True,
            s3_path=result.get("s3_key", ""),
            download_url=result.get("download_url", ""),
        )

    def _order_sections(self, doc_state: DocumentState) -> list[dict[str, Any]]:
        """Return sections in APN template order.

        Skips sections that are ``None`` (not yet populated).
        """
        result: list[dict[str, Any]] = []
        sections = doc_state.sections
        for sec_name in APN_SECTION_ORDER:
            section = getattr(sections, sec_name, None)
            if section is not None:
                result.append({
                    "name": sec_name,
                    "data": section.model_dump(),
                })
        return result
