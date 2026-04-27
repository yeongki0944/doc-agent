"""Tests for Reviewer Agent — strands.Agent() logical agent refactoring.

Validates:
- Agent initialization with CHILD_MODEL and REVIEWER_PROMPT
- review(): required section completeness, staffing plan check, numeric consistency
- calculate_completion_score(): section-level fill ratio → 0.0~1.0
- classify_issues(): blocking vs non-blocking separation
- Suggestions generation from blocking issues and warnings

Requirements: 13.1, 13.2, 17.1
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from agent.lib.schema.document_state import (
    ArchitectureService,
    DocumentState,
    Sections,
    StaffingPlan,
    StaffingRole,
    FieldValue,
    FieldStatus,
    PhaseHours,
    CalculatedOnly,
    BlockingIssue,
    Warning as DocWarning,
    CoverSection,
    ServiceCategory,
)
from agent.app.reviewer.reviewer_agent import (
    ReviewerAgent,
    ReviewResult,
    REQUIRED_SECTIONS,
    REVIEWER_PROMPT,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def empty_doc() -> DocumentState:
    """A fresh empty DocumentState with default sections."""
    return DocumentState(document_id="test-review-001")


@pytest.fixture
def populated_doc() -> DocumentState:
    """DocumentState with some sections populated and staffing roles."""
    doc = DocumentState(document_id="test-review-002")
    # Populate cover with some data
    doc.sections.cover = CoverSection(title="Test Project")
    # Add a staffing role
    doc.staffing_plan = StaffingPlan(
        roles={
            "pm": StaffingRole(
                role_id="pm",
                display_name="PM",
                count=FieldValue(ai_recommended=1, status=FieldStatus.recommended),
                allocation_pct=FieldValue(ai_recommended=100, status=FieldStatus.recommended),
                rate_per_hour=FieldValue(ai_recommended=80.0, status=FieldStatus.recommended),
                phase_hours=PhaseHours(
                    discovery=FieldValue(ai_recommended=40, status=FieldStatus.recommended),
                    development=FieldValue(ai_recommended=80, status=FieldStatus.recommended),
                    testing=FieldValue(ai_recommended=20, status=FieldStatus.recommended),
                ),
            ),
        },
        grand_total_cost=CalculatedOnly(calculated=11200.0),
    )
    return doc


# ---------------------------------------------------------------------------
# Agent initialization
# ---------------------------------------------------------------------------

class TestAgentInitialization:
    """Verify ReviewerAgent creates a strands.Agent() instance."""

    @patch("agent.app.reviewer.reviewer_agent.Agent")
    def test_agent_created_with_child_model(self, mock_agent_cls: MagicMock) -> None:
        agent = ReviewerAgent()
        mock_agent_cls.assert_called_once()
        call_kwargs = mock_agent_cls.call_args.kwargs
        assert "model" in call_kwargs
        assert "system_prompt" in call_kwargs

    @patch("agent.app.reviewer.reviewer_agent.Agent")
    def test_agent_uses_reviewer_prompt(self, mock_agent_cls: MagicMock) -> None:
        agent = ReviewerAgent()
        call_kwargs = mock_agent_cls.call_args.kwargs
        assert call_kwargs["system_prompt"] == REVIEWER_PROMPT


# ---------------------------------------------------------------------------
# calculate_completion_score() — Req 17.1
# ---------------------------------------------------------------------------

class TestCalculateCompletionScore:
    """Validates: Requirement 17.1 — completion score 0.0~1.0."""

    @patch("agent.app.reviewer.reviewer_agent.Agent")
    def test_empty_doc_has_partial_score(self, mock_agent_cls: MagicMock, empty_doc: DocumentState) -> None:
        """Empty doc: sections exist but have no data → partial credit each."""
        agent = ReviewerAgent()
        score = agent.calculate_completion_score(empty_doc)
        # All sections exist (partial credit 0.3 each) but no staffing roles
        # total = len(REQUIRED_SECTIONS) + 1 = 12
        # filled = 11 * 0.3 + 0 (no staffing) = 3.3
        # score = 3.3 / 12 = 0.275
        assert 0.0 <= score <= 1.0
        assert score < 0.5  # mostly empty

    @patch("agent.app.reviewer.reviewer_agent.Agent")
    def test_populated_doc_has_higher_score(self, mock_agent_cls: MagicMock, populated_doc: DocumentState) -> None:
        """Doc with some data and staffing roles should score higher."""
        agent = ReviewerAgent()
        score = agent.calculate_completion_score(populated_doc)
        assert 0.0 <= score <= 1.0
        # Has staffing roles (+1) and cover with data (+1), rest partial
        assert score > 0.0

    @patch("agent.app.reviewer.reviewer_agent.Agent")
    def test_score_never_exceeds_one(self, mock_agent_cls: MagicMock) -> None:
        """Score should be capped at 1.0."""
        agent = ReviewerAgent()
        # Create a fully populated doc
        doc = DocumentState(document_id="full-doc")
        # Add data to all sections
        doc.sections.cover = CoverSection(title="Full Project", subtitle="Complete")
        doc.sections.executive_summary = CoverSection(summary="Summary text")
        doc.sections.stakeholders = CoverSection(contacts="Team info")
        doc.sections.success_criteria = CoverSection(kpis="KPI list")
        doc.sections.assumptions = CoverSection(risks="Risk list")
        doc.sections.scope_of_work = CoverSection(scope="Scope detail")
        doc.sections.architecture = CoverSection(services="Lambda, S3")
        doc.sections.milestones = CoverSection(phases="Phase 1, Phase 2")
        doc.sections.cost_breakdown = CoverSection(total="50000")
        doc.sections.acceptance = CoverSection(criteria="Acceptance criteria")
        doc.sections.resources_cost_estimates = CoverSection(estimates="Cost estimates")
        # Add staffing
        doc.staffing_plan = StaffingPlan(
            roles={"pm": StaffingRole(role_id="pm", display_name="PM")},
        )
        score = agent.calculate_completion_score(doc)
        assert score <= 1.0

    @patch("agent.app.reviewer.reviewer_agent.Agent")
    def test_score_is_zero_point_range(self, mock_agent_cls: MagicMock) -> None:
        """Score should be rounded to 2 decimal places."""
        agent = ReviewerAgent()
        doc = DocumentState(document_id="test-round")
        score = agent.calculate_completion_score(doc)
        assert score == round(score, 2)


# ---------------------------------------------------------------------------
# classify_issues() — Req 13.2
# ---------------------------------------------------------------------------

class TestClassifyIssues:
    """Validates: Requirement 13.2 — blocking vs non-blocking."""

    @patch("agent.app.reviewer.reviewer_agent.Agent")
    def test_separates_blocking_from_warnings(self, mock_agent_cls: MagicMock) -> None:
        agent = ReviewerAgent()
        issues = [
            BlockingIssue(code="MISSING_COVER", message="Cover 누락", section="cover"),
            DocWarning(code="ZERO_COST", message="비용 0", section="cost_breakdown"),
            BlockingIssue(code="EMPTY_STAFFING", message="Staffing 비어있음", section="staffing_plan"),
        ]
        blocking, warnings = agent.classify_issues(issues)
        assert len(blocking) == 2
        assert len(warnings) == 1
        assert all(isinstance(b, BlockingIssue) for b in blocking)
        assert all(isinstance(w, DocWarning) for w in warnings)

    @patch("agent.app.reviewer.reviewer_agent.Agent")
    def test_empty_issues_returns_empty_lists(self, mock_agent_cls: MagicMock) -> None:
        agent = ReviewerAgent()
        blocking, warnings = agent.classify_issues([])
        assert blocking == []
        assert warnings == []

    @patch("agent.app.reviewer.reviewer_agent.Agent")
    def test_all_blocking(self, mock_agent_cls: MagicMock) -> None:
        agent = ReviewerAgent()
        issues = [
            BlockingIssue(code="A", message="Issue A"),
            BlockingIssue(code="B", message="Issue B"),
        ]
        blocking, warnings = agent.classify_issues(issues)
        assert len(blocking) == 2
        assert len(warnings) == 0

    @patch("agent.app.reviewer.reviewer_agent.Agent")
    def test_all_warnings(self, mock_agent_cls: MagicMock) -> None:
        agent = ReviewerAgent()
        issues = [
            DocWarning(code="W1", message="Warning 1"),
            DocWarning(code="W2", message="Warning 2"),
        ]
        blocking, warnings = agent.classify_issues(issues)
        assert len(blocking) == 0
        assert len(warnings) == 2


# ---------------------------------------------------------------------------
# review() — full review flow (Req 13.1, 13.2, 17.1)
# ---------------------------------------------------------------------------

class TestReview:
    """Validates: Requirements 13.1, 13.2, 17.1"""

    @patch("agent.app.reviewer.reviewer_agent.Agent")
    def test_review_empty_doc_has_blocking_issues(self, mock_agent_cls: MagicMock, empty_doc: DocumentState) -> None:
        """Req 13.1: empty doc should have EMPTY_STAFFING blocking issue."""
        agent = ReviewerAgent()
        result = agent.review(empty_doc)

        assert isinstance(result, ReviewResult)
        # Empty staffing plan → blocking issue
        codes = [i.code for i in result.blocking_issues]
        assert "EMPTY_STAFFING" in codes

    @patch("agent.app.reviewer.reviewer_agent.Agent")
    def test_review_populated_doc_no_empty_staffing(self, mock_agent_cls: MagicMock, populated_doc: DocumentState) -> None:
        """Doc with staffing roles should not have EMPTY_STAFFING issue."""
        agent = ReviewerAgent()
        result = agent.review(populated_doc)

        codes = [i.code for i in result.blocking_issues]
        assert "EMPTY_STAFFING" not in codes

    @patch("agent.app.reviewer.reviewer_agent.Agent")
    def test_review_includes_completion_score(self, mock_agent_cls: MagicMock, populated_doc: DocumentState) -> None:
        """Req 17.1: review result includes completion score."""
        agent = ReviewerAgent()
        result = agent.review(populated_doc)

        assert 0.0 <= result.completion_score <= 1.0

    @patch("agent.app.reviewer.reviewer_agent.Agent")
    def test_review_generates_suggestions(self, mock_agent_cls: MagicMock, empty_doc: DocumentState) -> None:
        """Review should generate suggestions from blocking issues."""
        agent = ReviewerAgent()
        result = agent.review(empty_doc)

        assert len(result.suggestions) > 0
        assert any("[blocking]" in s for s in result.suggestions)

    @patch("agent.app.reviewer.reviewer_agent.Agent")
    def test_review_zero_cost_warning(self, mock_agent_cls: MagicMock) -> None:
        """Grand total cost ≤ 0 should produce ZERO_COST warning."""
        doc = DocumentState(document_id="test-zero-cost")
        doc.staffing_plan = StaffingPlan(
            roles={"pm": StaffingRole(role_id="pm", display_name="PM")},
            grand_total_cost=CalculatedOnly(calculated=0),
        )
        agent = ReviewerAgent()
        result = agent.review(doc)

        warning_codes = [w.code for w in result.warnings]
        assert "ZERO_COST" in warning_codes

    @patch("agent.app.reviewer.reviewer_agent.Agent")
    def test_review_positive_cost_no_warning(self, mock_agent_cls: MagicMock, populated_doc: DocumentState) -> None:
        """Positive grand total cost should not produce ZERO_COST warning."""
        agent = ReviewerAgent()
        result = agent.review(populated_doc)

        warning_codes = [w.code for w in result.warnings]
        assert "ZERO_COST" not in warning_codes

    @patch("agent.app.reviewer.reviewer_agent.Agent")
    def test_review_result_types(self, mock_agent_cls: MagicMock, empty_doc: DocumentState) -> None:
        """Verify ReviewResult field types."""
        agent = ReviewerAgent()
        result = agent.review(empty_doc)

        assert isinstance(result.completion_score, float)
        assert isinstance(result.blocking_issues, list)
        assert isinstance(result.warnings, list)
        assert isinstance(result.suggestions, list)

    @patch("agent.app.reviewer.reviewer_agent.Agent")
    def test_review_includes_funding_validation(self, mock_agent_cls: MagicMock, populated_doc: DocumentState) -> None:
        agent = ReviewerAgent()

        result = agent.review(populated_doc)

        assert result.funding_validation is not None
        codes = {issue.code for issue in result.blocking_issues}
        assert "BEDROCK_MISSING" in codes

    @patch("agent.app.reviewer.reviewer_agent.Agent")
    def test_review_does_not_duplicate_funding_issue_codes(self, mock_agent_cls: MagicMock, populated_doc: DocumentState) -> None:
        populated_doc.sections.architecture.services = [
            ArchitectureService(
                service_name=FieldValue(user_input="Amazon Bedrock"),
                category=ServiceCategory.genai_core,
            )
        ]
        agent = ReviewerAgent()

        first = agent.review(populated_doc)
        second = agent.review(populated_doc)

        assert len([i for i in first.blocking_issues if i.code == "CALCULATOR_URL_MISSING"]) == 1
        assert len([i for i in second.blocking_issues if i.code == "CALCULATOR_URL_MISSING"]) == 1
