"""Tests for Cost Agent — strands.Agent() logical agent refactoring.

Validates:
- Agent initialization with CHILD_MODEL and COST_PROMPT
- calculate_staffing_cost() deterministic calculation (staffing_plan only)
- calculate_aws_cost() via common AgentCoreGatewayClient
- generate_fallback_card() for failed/unsupported services
- generate_document_local_summary() always preserved (Req 8.8)

Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from agent.app.cost.cost_agent import (
    CostAgent,
    StaffingCostResult,
    AWSCostResult,
    FallbackCard,
    DocumentLocalSummary,
    COST_PROMPT,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_STAFFING_PLAN = {
    "roles": {
        "project_manager": {
            "count": {"user_input": None, "ai_recommended": 1, "calculated": None},
            "allocation_pct": {"user_input": None, "ai_recommended": 100, "calculated": None},
            "rate_per_hour": {"user_input": None, "ai_recommended": 80.0, "calculated": None},
            "phase_hours": {
                "discovery": {"user_input": None, "ai_recommended": 40, "calculated": None},
                "development": {"user_input": None, "ai_recommended": 80, "calculated": None},
                "testing": {"user_input": None, "ai_recommended": 20, "calculated": None},
            },
        },
        "backend_dev": {
            "count": {"user_input": None, "ai_recommended": 2, "calculated": None},
            "allocation_pct": {"user_input": None, "ai_recommended": 100, "calculated": None},
            "rate_per_hour": {"user_input": None, "ai_recommended": 60.0, "calculated": None},
            "phase_hours": {
                "discovery": {"user_input": None, "ai_recommended": 10, "calculated": None},
                "development": {"user_input": None, "ai_recommended": 120, "calculated": None},
                "testing": {"user_input": None, "ai_recommended": 30, "calculated": None},
            },
        },
    }
}

SAMPLE_SERVICES = [
    {"service_name": "AWS Lambda", "service_code": "aWSLambda", "estimated_monthly": 244.13, "supported": True},
    {"service_name": "Amazon DynamoDB", "service_code": "dynamoDB", "estimated_monthly": 50.0, "supported": True},
    {"service_name": "Custom Service", "estimated_monthly": 100.0, "supported": False},
]


# ---------------------------------------------------------------------------
# Agent initialization
# ---------------------------------------------------------------------------

class TestAgentInitialization:
    """Verify CostAgent creates a strands.Agent() instance."""

    @patch("agent.app.cost.cost_agent.Agent")
    def test_agent_created_with_child_model(self, mock_agent_cls: MagicMock) -> None:
        agent = CostAgent()
        mock_agent_cls.assert_called_once()
        call_kwargs = mock_agent_cls.call_args
        assert "model_id" in call_kwargs.kwargs or len(call_kwargs.args) > 0
        assert "system_prompt" in call_kwargs.kwargs

    @patch("agent.app.cost.cost_agent.Agent")
    def test_agent_uses_cost_prompt(self, mock_agent_cls: MagicMock) -> None:
        agent = CostAgent()
        call_kwargs = mock_agent_cls.call_args.kwargs
        assert call_kwargs["system_prompt"] == COST_PROMPT


# ---------------------------------------------------------------------------
# Staffing cost — deterministic (Req 8.1, 8.2, 8.3)
# ---------------------------------------------------------------------------

class TestCalculateStaffingCost:
    """Verify deterministic staffing cost calculation."""

    @patch("agent.app.cost.cost_agent.Agent")
    def test_calculates_role_totals(self, mock_agent_cls: MagicMock) -> None:
        """Req 8.1: role별 total hours와 total cost 계산."""
        agent = CostAgent()
        result = agent.calculate_staffing_cost(SAMPLE_STAFFING_PLAN)

        assert isinstance(result, StaffingCostResult)
        assert len(result.roles_summary) == 2

        pm = next(r for r in result.roles_summary if r["role_id"] == "project_manager")
        # PM: 40 + 80 + 20 = 140 hours
        assert pm["total_hours"] == 140
        # PM: 1 * (100/100) * 80 * 140 = 11200
        assert pm["total_cost"] == 11200.0

    @patch("agent.app.cost.cost_agent.Agent")
    def test_calculates_grand_total(self, mock_agent_cls: MagicMock) -> None:
        """Req 8.2: grand total cost 계산."""
        agent = CostAgent()
        result = agent.calculate_staffing_cost(SAMPLE_STAFFING_PLAN)

        # PM: 11200.0, Backend: 2 * (100/100) * 60 * 160 = 19200.0
        assert result.grand_total == 11200.0 + 19200.0

    @patch("agent.app.cost.cost_agent.Agent")
    def test_does_not_use_stakeholders(self, mock_agent_cls: MagicMock) -> None:
        """Staffing cost uses staffing_plan only, not stakeholders."""
        agent = CostAgent()
        # Only staffing_plan is passed — no stakeholders parameter
        result = agent.calculate_staffing_cost(SAMPLE_STAFFING_PLAN)
        assert result.grand_total > 0

    @patch("agent.app.cost.cost_agent.Agent")
    def test_empty_staffing_plan(self, mock_agent_cls: MagicMock) -> None:
        agent = CostAgent()
        result = agent.calculate_staffing_cost({"roles": {}})
        assert result.roles_summary == []
        assert result.grand_total == 0.0


# ---------------------------------------------------------------------------
# AWS cost — Gateway estimate_cost (Req 8.4, 8.5, 8.7)
# ---------------------------------------------------------------------------

class TestCalculateAWSCost:
    """Verify AWS cost calculation via common AgentCoreGatewayClient."""

    @pytest.mark.asyncio
    @patch("agent.app.cost.cost_agent.Agent")
    async def test_successful_estimate(self, mock_agent_cls: MagicMock) -> None:
        """Req 8.4, 8.5: successful Gateway estimate_cost call."""
        agent = CostAgent()

        mock_gw = MagicMock()
        mock_gw.call_tool_safe = AsyncMock(return_value=(
            {
                "monthly_total": 294.13,
                "breakdown": [
                    {"service_name": "AWS Lambda", "monthly_cost": 244.13},
                    {"service_name": "Amazon DynamoDB", "monthly_cost": 50.0},
                ],
                "share_url": "https://calculator.aws/#/estimate?id=abc123",
                "manual_items": [],
            },
            None,
        ))

        result = await agent.calculate_aws_cost(SAMPLE_SERVICES, mock_gw)

        assert isinstance(result, AWSCostResult)
        assert result.monthly_cost_summary == 294.13
        assert len(result.service_breakdown) == 2
        assert result.calculator_share_url == "https://calculator.aws/#/estimate?id=abc123"
        assert result.manual_estimate_items == []

        # Verify call_tool_safe was called with correct params
        mock_gw.call_tool_safe.assert_called_once_with(
            "estimate_cost", {"services": SAMPLE_SERVICES}
        )

    @pytest.mark.asyncio
    @patch("agent.app.cost.cost_agent.Agent")
    async def test_gateway_failure_returns_manual_items(self, mock_agent_cls: MagicMock) -> None:
        """Req 8.6: Gateway failure → manual_estimate_items populated."""
        agent = CostAgent()

        mock_gw = MagicMock()
        mock_gw.call_tool_safe = AsyncMock(return_value=(None, "Gateway timeout"))

        result = await agent.calculate_aws_cost(SAMPLE_SERVICES, mock_gw)

        assert result.monthly_cost_summary == 0.0
        assert result.service_breakdown == []
        assert result.calculator_share_url is None
        assert result.manual_estimate_items == SAMPLE_SERVICES

    @pytest.mark.asyncio
    @patch("agent.app.cost.cost_agent.Agent")
    async def test_uses_agentcore_gateway_client(self, mock_agent_cls: MagicMock) -> None:
        """Verify uses AgentCoreGatewayClient (call_tool_safe), not Protocol."""
        agent = CostAgent()

        mock_gw = MagicMock()
        mock_gw.call_tool_safe = AsyncMock(return_value=({"monthly_total": 0, "breakdown": []}, None))

        await agent.calculate_aws_cost([], mock_gw)

        # call_tool_safe is the AgentCoreGatewayClient method
        mock_gw.call_tool_safe.assert_called_once()


# ---------------------------------------------------------------------------
# Fallback card (Req 8.6, 8.7)
# ---------------------------------------------------------------------------

class TestGenerateFallbackCard:
    """Verify fallback card generation."""

    @patch("agent.app.cost.cost_agent.Agent")
    def test_generates_card_from_services(self, mock_agent_cls: MagicMock) -> None:
        """Req 8.6, 8.7: fallback card with service details."""
        agent = CostAgent()
        card = agent.generate_fallback_card(SAMPLE_SERVICES)

        assert isinstance(card, FallbackCard)
        assert len(card.services) == 3
        assert card.total_estimate == round(244.13 + 50.0 + 100.0, 2)
        assert "실패" in card.reason or "미지원" in card.reason

    @patch("agent.app.cost.cost_agent.Agent")
    def test_unsupported_services_marked(self, mock_agent_cls: MagicMock) -> None:
        """Req 8.7: unsupported services reflected in card."""
        agent = CostAgent()
        card = agent.generate_fallback_card(SAMPLE_SERVICES)

        custom = next(s for s in card.services if s["service_name"] == "Custom Service")
        assert custom["supported"] is False

    @patch("agent.app.cost.cost_agent.Agent")
    def test_empty_services(self, mock_agent_cls: MagicMock) -> None:
        agent = CostAgent()
        card = agent.generate_fallback_card([])
        assert card.services == []
        assert card.total_estimate == 0.0


# ---------------------------------------------------------------------------
# Document-local summary (Req 8.8)
# ---------------------------------------------------------------------------

class TestDocumentLocalSummary:
    """Verify document-local cost summary generation."""

    @patch("agent.app.cost.cost_agent.Agent")
    def test_generates_summary(self, mock_agent_cls: MagicMock) -> None:
        """Req 8.8: document-local summary always preserved."""
        agent = CostAgent()

        staffing = StaffingCostResult(
            roles_summary=[{"role_id": "pm", "total_hours": 140, "total_cost": 11200}],
            grand_total=11200.0,
        )
        aws = AWSCostResult(
            monthly_cost_summary=294.13,
            service_breakdown=[],
        )

        summary = agent.generate_document_local_summary(staffing, aws)

        assert isinstance(summary, DocumentLocalSummary)
        assert summary.total_staffing_cost == 11200.0
        assert summary.total_aws_monthly_cost == 294.13
        assert summary.total_project_cost == round(11200.0 + 294.13, 2)
        assert summary.generated_at != ""

    @patch("agent.app.cost.cost_agent.Agent")
    def test_summary_with_zero_aws(self, mock_agent_cls: MagicMock) -> None:
        """Summary works when AWS cost is zero (e.g., gateway failure)."""
        agent = CostAgent()

        staffing = StaffingCostResult(grand_total=5000.0)
        aws = AWSCostResult(monthly_cost_summary=0.0)

        summary = agent.generate_document_local_summary(staffing, aws)

        assert summary.total_project_cost == 5000.0
