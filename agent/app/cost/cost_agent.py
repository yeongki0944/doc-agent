"""Cost Agent — staffing cost (deterministic) + AWS service cost (Calculator MCP).

Refactored as a ``strands.Agent()`` logical agent within the Parent Runtime.

- Staffing cost uses the calculation module directly (deterministic).
- AWS cost calls Gateway's ``estimate_cost`` tool via the common
  ``AgentCoreGatewayClient`` (not the Protocol stub).
- Fallback card generated on failure or unsupported services.
- ``document_local_summary`` is always preserved so the estimate remains
  readable even when the external calculator share URL expires.

Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from strands import Agent

from agent.lib.calculation.staffing_cost import (
    calculate_role_total_hours,
    calculate_role_total_cost,
    calculate_grand_total,
)
from agent.lib.calculation.recalculate import recalculate_costs
from agent.lib.gateway.agentcore_gateway import AgentCoreGatewayClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model configuration
# ---------------------------------------------------------------------------

CHILD_MODEL: str = os.environ.get(
    "CHILD_MODEL",
    "apac.anthropic.claude-3-5-sonnet-20241022-v2:0",
)

# ---------------------------------------------------------------------------
# System prompt for the Cost Agent
# ---------------------------------------------------------------------------

COST_PROMPT: str = """당신은 APN PoC Project Plan의 비용 계산 전문 에이전트입니다.

## 역할
1. 인건비 계산: staffing_plan의 역할별 count × allocation × rate × hours로 총 비용을 계산합니다.
2. AWS 서비스 비용 계산: 아키텍처에 포함된 AWS 서비스의 월간 비용을 추정합니다.
3. Fallback 처리: Calculator MCP 호출 실패 또는 미지원 서비스 시 요약 카드를 생성합니다.

## 계산 원칙
- 인건비는 staffing_plan 데이터만 사용합니다. stakeholders 섹션은 사용하지 않습니다.
- AWS 비용은 AgentCore Gateway의 estimate_cost 도구를 통해 계산합니다.
- document_local_summary는 항상 보존하여 외부 링크 만료에 대비합니다.

## 응답 형식
반드시 아래 JSON 형식으로만 응답하세요.

```json
{
  "analysis": "비용 분석 요약",
  "recommendations": ["비용 최적화 제안1", "비용 최적화 제안2"]
}
```
"""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class StaffingCostResult:
    roles_summary: list[dict] = field(default_factory=list)
    grand_total: float = 0.0


@dataclass
class AWSCostResult:
    monthly_cost_summary: float = 0.0
    service_breakdown: list[dict] = field(default_factory=list)
    calculator_share_url: Optional[str] = None
    manual_estimate_items: list[dict] = field(default_factory=list)


@dataclass
class FallbackCard:
    services: list[dict] = field(default_factory=list)
    total_estimate: float = 0.0
    reason: str = ""


@dataclass
class DocumentLocalSummary:
    """Document-local cost summary preserved even when external URLs expire.

    Requirement: 8.8
    """
    total_staffing_cost: float = 0.0
    total_aws_monthly_cost: float = 0.0
    total_project_cost: float = 0.0
    generated_at: str = ""


# ---------------------------------------------------------------------------
# Cost Agent
# ---------------------------------------------------------------------------

class CostAgent:
    """Calculates staffing costs and AWS service costs.

    Uses a ``strands.Agent()`` instance with CHILD_MODEL for LLM-powered
    cost analysis and recommendations. Core calculation logic is
    deterministic; the LLM provides supplementary analysis.

    Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8
    """

    def __init__(self) -> None:
        self.agent = Agent(
            model_id=CHILD_MODEL,
            system_prompt=COST_PROMPT,
        )

    # ------------------------------------------------------------------
    # Staffing cost — deterministic (Req 8.1, 8.2, 8.3)
    # ------------------------------------------------------------------

    def calculate_staffing_cost(self, staffing_plan: Any) -> StaffingCostResult:
        """Deterministic staffing cost calculation.

        Uses ``staffing_plan`` data only. Does NOT use ``stakeholders``
        section data — stakeholders is for contact/org info only.

        Requirements: 8.1, 8.2, 8.3
        """
        calc = recalculate_costs(staffing_plan)
        roles_summary = []
        for role_id, vals in calc["roles"].items():
            roles_summary.append({
                "role_id": role_id,
                "total_hours": vals["total_hours"],
                "total_cost": vals["total_cost"],
            })
        return StaffingCostResult(
            roles_summary=roles_summary,
            grand_total=calc["grand_total_cost"],
        )

    # ------------------------------------------------------------------
    # AWS service cost — Gateway estimate_cost (Req 8.4, 8.5, 8.7)
    # ------------------------------------------------------------------

    async def calculate_aws_cost(
        self,
        services: list[dict],
        gateway_client: AgentCoreGatewayClient,
    ) -> AWSCostResult:
        """Call the common Gateway ``estimate_cost`` tool for AWS costs.

        Uses ``AgentCoreGatewayClient`` (the shared Gateway client from
        ``agent/lib/gateway/agentcore_gateway.py``), not the old Protocol
        stub.

        Requirements: 8.4, 8.5, 8.7
        """
        result = AWSCostResult()

        response, error = await gateway_client.call_tool_safe(
            "estimate_cost", {"services": services}
        )

        if error or response is None:
            logger.warning("estimate_cost failed: %s", error)
            # Will generate fallback card instead (Req 8.6)
            result.manual_estimate_items = services
            return result

        result.monthly_cost_summary = response.get("monthly_total", 0)
        result.service_breakdown = response.get("breakdown", [])
        result.calculator_share_url = response.get("share_url")
        result.manual_estimate_items = response.get("manual_items", [])

        return result

    # ------------------------------------------------------------------
    # Fallback card (Req 8.6, 8.7)
    # ------------------------------------------------------------------

    def generate_fallback_card(
        self, services: list[dict], partial_results: dict | None = None
    ) -> FallbackCard:
        """Generate fallback card when Calculator MCP fails or services unsupported.

        Requirements: 8.6, 8.7
        """
        card_services = []
        total = 0.0
        for svc in services:
            est = svc.get("estimated_monthly", 0)
            card_services.append({
                "service_name": svc.get("service_name", "Unknown"),
                "estimated_monthly": est,
                "supported": svc.get("supported", False),
            })
            total += est
        return FallbackCard(
            services=card_services,
            total_estimate=round(total, 2),
            reason="Calculator MCP 호출 실패 또는 미지원 서비스 포함",
        )

    # ------------------------------------------------------------------
    # Document-local summary (Req 8.8)
    # ------------------------------------------------------------------

    def generate_document_local_summary(
        self,
        staffing_result: StaffingCostResult,
        aws_result: AWSCostResult,
    ) -> DocumentLocalSummary:
        """Generate a document-local cost summary.

        Always preserved so the estimate remains readable even when the
        external calculator share URL expires or becomes unavailable.

        Requirement: 8.8
        """
        total_staffing = staffing_result.grand_total
        total_aws = aws_result.monthly_cost_summary
        return DocumentLocalSummary(
            total_staffing_cost=total_staffing,
            total_aws_monthly_cost=total_aws,
            total_project_cost=round(total_staffing + total_aws, 2),
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
