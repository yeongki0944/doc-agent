"""Tests for Staffing Agent — strands.Agent() logical agent refactoring.

Validates:
- Agent initialization with CHILD_MODEL and STAFFING_PROMPT
- recommend(): preset selection → role recommendation in 4-property pattern
- validate_rates(): rate_card.json bounds checking
- _detect_project_type(): keyword-based project type detection
- Rate clamping to rate_card bounds

Requirements: 7.1, 7.2, 7.4, 7.5, 7.6
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from agent.app.staffing.staffing_agent import (
    StaffingAgent,
    StaffingRecommendation,
    RateViolation,
    STAFFING_PROMPT,
    categorize_role,
)


# ---------------------------------------------------------------------------
# Agent initialization
# ---------------------------------------------------------------------------

class TestAgentInitialization:
    """Verify StaffingAgent creates a strands.Agent() instance."""

    @patch("agent.app.staffing.staffing_agent.Agent")
    def test_agent_created_with_child_model(self, mock_agent_cls: MagicMock) -> None:
        agent = StaffingAgent()
        mock_agent_cls.assert_called_once()
        call_kwargs = mock_agent_cls.call_args.kwargs
        assert "model_id" in call_kwargs
        assert "system_prompt" in call_kwargs

    @patch("agent.app.staffing.staffing_agent.Agent")
    def test_agent_uses_staffing_prompt(self, mock_agent_cls: MagicMock) -> None:
        agent = StaffingAgent()
        call_kwargs = mock_agent_cls.call_args.kwargs
        assert call_kwargs["system_prompt"] == STAFFING_PROMPT

    @patch("agent.app.staffing.staffing_agent.Agent")
    def test_presets_loaded(self, mock_agent_cls: MagicMock) -> None:
        agent = StaffingAgent()
        assert len(agent.role_catalog) > 0
        assert len(agent.rate_card) > 0
        assert len(agent.staffing_presets) > 0


# ---------------------------------------------------------------------------
# recommend() — 4-property pattern output
# ---------------------------------------------------------------------------

class TestRecommend:
    """Validates: Requirements 7.1, 7.2, 7.5"""

    @patch("agent.app.staffing.staffing_agent.Agent")
    def test_recommend_returns_staffing_recommendation(self, mock_agent_cls: MagicMock) -> None:
        agent = StaffingAgent()
        rec = agent.recommend("GenAI 멀티에이전트 PoC 프로젝트")
        assert isinstance(rec, StaffingRecommendation)
        assert rec.project_type == "genai_multi_agent"

    @patch("agent.app.staffing.staffing_agent.Agent")
    def test_recommend_includes_six_roles(self, mock_agent_cls: MagicMock) -> None:
        """Req 7.5: default 6 roles for GenAI multi-agent PoC."""
        agent = StaffingAgent()
        rec = agent.recommend("멀티에이전트 기반 시스템")
        expected_roles = {
            "project_manager", "solutions_architect", "ml_engineer",
            "backend_developer", "frontend_developer", "qa_engineer",
        }
        assert set(rec.roles.keys()) == expected_roles

    @patch("agent.app.staffing.staffing_agent.Agent")
    def test_recommend_outputs_4_property_pattern(self, mock_agent_cls: MagicMock) -> None:
        """Req 7.2: each field uses user_input/ai_recommended/calculated/status."""
        agent = StaffingAgent()
        rec = agent.recommend("에이전트 프로젝트")

        for role_id, role_data in rec.roles.items():
            # Check count field
            count = role_data["count"]
            assert "user_input" in count
            assert "ai_recommended" in count
            assert "calculated" in count
            assert "status" in count
            assert count["user_input"] is None
            assert count["status"] == "recommended"
            assert count["ai_recommended"] is not None

            # Check rate_per_hour field
            rate = role_data["rate_per_hour"]
            assert rate["status"] == "recommended"
            assert rate["ai_recommended"] is not None

            # Check phase_hours
            for phase, ph in role_data["phase_hours"].items():
                assert "user_input" in ph
                assert "ai_recommended" in ph
                assert "calculated" in ph
                assert "status" in ph

    @patch("agent.app.staffing.staffing_agent.Agent")
    def test_recommend_includes_reason_and_source(self, mock_agent_cls: MagicMock) -> None:
        """Req 7.2: reason and source_patterns included."""
        agent = StaffingAgent()
        rec = agent.recommend("에이전트 프로젝트")

        for role_data in rec.roles.values():
            assert "reason" in role_data
            assert "source_patterns" in role_data
            assert len(role_data["source_patterns"]) > 0
            assert "confidence" in role_data

    @patch("agent.app.staffing.staffing_agent.Agent")
    def test_recommend_sets_role_category(self, mock_agent_cls: MagicMock) -> None:
        agent = StaffingAgent()
        rec = agent.recommend("에이전트 프로젝트")

        assert rec.roles["solutions_architect"]["category"] == "solution_architect"
        assert rec.roles["ml_engineer"]["category"] == "engineer"
        assert rec.roles["project_manager"]["category"] == "other"


# ---------------------------------------------------------------------------
# validate_rates()
# ---------------------------------------------------------------------------

class TestValidateRates:
    """Validates: Requirement 7.4"""

    @patch("agent.app.staffing.staffing_agent.Agent")
    def test_no_violations_for_preset_rates(self, mock_agent_cls: MagicMock) -> None:
        """Preset rates are clamped, so no violations expected."""
        agent = StaffingAgent()
        rec = agent.recommend("멀티에이전트 프로젝트")
        assert len(rec.violations) == 0

    @patch("agent.app.staffing.staffing_agent.Agent")
    def test_detects_rate_below_min(self, mock_agent_cls: MagicMock) -> None:
        agent = StaffingAgent()
        rec = StaffingRecommendation(
            project_type="test",
            roles={
                "project_manager": {
                    "rate_per_hour": {"ai_recommended": 10.0},
                },
            },
        )
        violations = agent.validate_rates(rec)
        assert len(violations) == 1
        assert violations[0].role_id == "project_manager"
        assert violations[0].value == 10.0

    @patch("agent.app.staffing.staffing_agent.Agent")
    def test_detects_rate_above_max(self, mock_agent_cls: MagicMock) -> None:
        agent = StaffingAgent()
        rec = StaffingRecommendation(
            project_type="test",
            roles={
                "project_manager": {
                    "rate_per_hour": {"ai_recommended": 999.0},
                },
            },
        )
        violations = agent.validate_rates(rec)
        assert len(violations) == 1
        assert violations[0].value == 999.0


# ---------------------------------------------------------------------------
# _detect_project_type()
# ---------------------------------------------------------------------------

class TestDetectProjectType:

    @patch("agent.app.staffing.staffing_agent.Agent")
    def test_detects_genai_multi_agent(self, mock_agent_cls: MagicMock) -> None:
        agent = StaffingAgent()
        assert agent._detect_project_type("멀티에이전트 PoC") == "genai_multi_agent"

    @patch("agent.app.staffing.staffing_agent.Agent")
    def test_detects_genai_single(self, mock_agent_cls: MagicMock) -> None:
        agent = StaffingAgent()
        assert agent._detect_project_type("RAG 기반 챗봇") == "genai_single"

    @patch("agent.app.staffing.staffing_agent.Agent")
    def test_detects_data_analytics(self, mock_agent_cls: MagicMock) -> None:
        agent = StaffingAgent()
        assert agent._detect_project_type("데이터 분석 대시보드") == "data_analytics"

    @patch("agent.app.staffing.staffing_agent.Agent")
    def test_defaults_to_genai_multi_agent(self, mock_agent_cls: MagicMock) -> None:
        agent = StaffingAgent()
        assert agent._detect_project_type("unknown project") == "genai_multi_agent"


class TestCategorizeRole:

    def test_known_role_ids(self) -> None:
        assert categorize_role("solution_architect") == "solution_architect"
        assert categorize_role("ml_engineer") == "engineer"
        assert categorize_role("project_manager") == "other"

    def test_fallback_matching(self) -> None:
        assert categorize_role("principal_architect") == "solution_architect"
        assert categorize_role("java_developer") == "engineer"
        assert categorize_role("business_analyst") == "other"


# ---------------------------------------------------------------------------
# Rate clamping
# ---------------------------------------------------------------------------

class TestRateClamping:
    """Validates: Requirement 7.4 — rates clamped to rate_card bounds."""

    @patch("agent.app.staffing.staffing_agent.Agent")
    def test_rates_within_card_bounds(self, mock_agent_cls: MagicMock) -> None:
        agent = StaffingAgent()
        rec = agent.recommend("에이전트 프로젝트")

        for role_id, role_data in rec.roles.items():
            card = agent.rate_card.get(role_id)
            if card:
                rate = role_data["rate_per_hour"]["ai_recommended"]
                assert rate >= card["min"], f"{role_id} rate {rate} < min {card['min']}"
                assert rate <= card["max"], f"{role_id} rate {rate} > max {card['max']}"
