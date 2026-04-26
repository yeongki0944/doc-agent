"""Tests for Discovery Agent — strands.Agent() logical agent refactoring.

Validates:
- Agent initialization with CHILD_MODEL and DISCOVERY_PROMPT
- collect_info() input analysis, missing field detection, structuring
- classify_missing_fields() draft-required vs export-required classification
- draft-required only missing does not block draft generation (Req 6.4)

Requirements: 6.1, 6.2, 6.3, 6.4
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock
import json

import pytest

from agent.lib.schema.document_state import (
    DocumentState,
    DocumentMeta,
    FieldValue,
    FieldStatus,
)
from agent.app.discovery.discovery_agent import (
    DiscoveryAgent,
    DiscoveryResult,
    MissingFields,
    DRAFT_REQUIRED_FIELDS,
    EXPORT_REQUIRED_FIELDS,
    DISCOVERY_PROMPT,
    _has_value,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def empty_doc() -> DocumentState:
    """A fresh empty DocumentState."""
    return DocumentState(document_id="test-doc-001")


@pytest.fixture
def doc_with_customer() -> DocumentState:
    """DocumentState with customer already set."""
    doc = DocumentState(document_id="test-doc-002")
    doc.meta.customer = FieldValue(
        user_input="ABC Corp",
        status=FieldStatus.confirmed,
    )
    return doc


# ---------------------------------------------------------------------------
# Agent initialization
# ---------------------------------------------------------------------------

class TestAgentInitialization:
    """Verify DiscoveryAgent creates a strands.Agent() instance."""

    @patch("agent.app.discovery.discovery_agent.Agent")
    def test_agent_created_with_child_model(self, mock_agent_cls: MagicMock) -> None:
        agent = DiscoveryAgent()
        mock_agent_cls.assert_called_once()
        call_kwargs = mock_agent_cls.call_args
        assert "model_id" in call_kwargs.kwargs or len(call_kwargs.args) > 0
        # Verify system_prompt is set
        assert "system_prompt" in call_kwargs.kwargs

    @patch("agent.app.discovery.discovery_agent.Agent")
    def test_agent_uses_discovery_prompt(self, mock_agent_cls: MagicMock) -> None:
        agent = DiscoveryAgent()
        call_kwargs = mock_agent_cls.call_args.kwargs
        assert call_kwargs["system_prompt"] == DISCOVERY_PROMPT


# ---------------------------------------------------------------------------
# classify_missing_fields()
# ---------------------------------------------------------------------------

class TestClassifyMissingFields:
    """Validates: Requirements 6.1, 6.4"""

    @patch("agent.app.discovery.discovery_agent.Agent")
    def test_all_missing_on_empty_state(
        self, mock_agent_cls: MagicMock, empty_doc: DocumentState
    ) -> None:
        agent = DiscoveryAgent()
        missing = agent.classify_missing_fields(empty_doc)

        assert set(missing.draft_required) == set(DRAFT_REQUIRED_FIELDS)
        assert set(missing.export_required) == set(EXPORT_REQUIRED_FIELDS)

    @patch("agent.app.discovery.discovery_agent.Agent")
    def test_customer_from_doc_state_not_missing(
        self, mock_agent_cls: MagicMock, doc_with_customer: DocumentState
    ) -> None:
        agent = DiscoveryAgent()
        missing = agent.classify_missing_fields(doc_with_customer)

        assert "customer" not in missing.draft_required

    @patch("agent.app.discovery.discovery_agent.Agent")
    def test_collected_fields_reduce_missing(
        self, mock_agent_cls: MagicMock, empty_doc: DocumentState
    ) -> None:
        agent = DiscoveryAgent()
        collected = {
            "customer": "ABC Corp",
            "project_goal": "Build GenAI PoC",
            "scope_summary": "Multi-agent system",
            "architecture_available": True,
        }
        missing = agent.classify_missing_fields(empty_doc, collected)

        assert len(missing.draft_required) == 0
        # Export-required still missing
        assert len(missing.export_required) == len(EXPORT_REQUIRED_FIELDS)

    @patch("agent.app.discovery.discovery_agent.Agent")
    def test_export_only_missing_allows_draft(
        self, mock_agent_cls: MagicMock, empty_doc: DocumentState
    ) -> None:
        """Req 6.4: export-required만 누락 시 초안 생성 차단하지 않음."""
        agent = DiscoveryAgent()
        collected = {
            "customer": "ABC Corp",
            "project_goal": "Build GenAI PoC",
            "scope_summary": "Multi-agent system",
            "architecture_available": False,
        }
        missing = agent.classify_missing_fields(empty_doc, collected)

        assert len(missing.draft_required) == 0
        assert len(missing.export_required) > 0

    @patch("agent.app.discovery.discovery_agent.Agent")
    def test_partial_draft_fields_missing(
        self, mock_agent_cls: MagicMock, empty_doc: DocumentState
    ) -> None:
        agent = DiscoveryAgent()
        collected = {"customer": "ABC Corp", "project_goal": "Build PoC"}
        missing = agent.classify_missing_fields(empty_doc, collected)

        assert "scope_summary" in missing.draft_required
        assert "architecture_available" in missing.draft_required
        assert "customer" not in missing.draft_required
        assert "project_goal" not in missing.draft_required


# ---------------------------------------------------------------------------
# collect_info() — with mocked LLM
# ---------------------------------------------------------------------------

class TestCollectInfo:
    """Validates: Requirements 6.1, 6.2, 6.3, 6.4"""

    @pytest.mark.asyncio
    @patch("agent.app.discovery.discovery_agent.Agent")
    async def test_collect_info_with_complete_input(
        self, mock_agent_cls: MagicMock, empty_doc: DocumentState
    ) -> None:
        """Req 6.2: 최소 입력 수집 시 구조화하여 저장."""
        mock_instance = MagicMock()
        llm_response = json.dumps({
            "extracted_fields": {
                "customer": "ABC Corp",
                "project_goal": "GenAI 멀티에이전트 PoC",
                "scope_summary": "Bedrock 기반 문서 생성",
                "architecture_available": True,
            },
            "follow_up_questions": [],
        })
        mock_instance.return_value = llm_response
        mock_agent_cls.return_value = mock_instance

        agent = DiscoveryAgent()
        result = await agent.collect_info(
            "ABC Corp 고객사의 GenAI 멀티에이전트 PoC 프로젝트입니다. "
            "Bedrock 기반 문서 생성이 범위이고 기존 아키텍처가 있습니다.",
            empty_doc,
        )

        assert result.can_generate_draft is True
        assert len(result.missing.draft_required) == 0
        assert result.structured_input.get("customer") == "ABC Corp"

    @pytest.mark.asyncio
    @patch("agent.app.discovery.discovery_agent.Agent")
    async def test_collect_info_parses_docx_schema_fields(
        self, mock_agent_cls: MagicMock, empty_doc: DocumentState
    ) -> None:
        mock_instance = MagicMock()
        llm_response = json.dumps({
            "extracted_fields": {
                "customer": "ABC Corp",
                "project_goal": "GenAI PoC",
                "scope_summary": "문서 자동화",
                "architecture_available": False,
            },
            "executive_summary": "Executive summary paragraph",
            "executive_sponsors": [
                {"name": "Kim", "title": "VP", "description": "Sponsor", "contact": "kim@example.com"},
            ],
            "stakeholders": [
                {"name": "Lee", "title": "Owner", "stakeholder_for": "Business", "contact": ""},
            ],
            "project_team": [
                {"name": "Park", "title": "SA", "role": "Architecture", "contact": "park@example.com"},
            ],
            "escalation_contacts": [],
            "success_criteria": ["PoC success"],
            "assumptions": ["AWS account ready"],
            "scope_of_work": ["Build prototype"],
            "acceptance_text": "Customer sign-off",
            "missing_fields": ["phase_schedule"],
        })
        mock_instance.return_value = llm_response
        mock_agent_cls.return_value = mock_instance

        agent = DiscoveryAgent()
        result = await agent.collect_info("ABC Corp GenAI PoC", empty_doc)

        assert result.executive_summary == "Executive summary paragraph"
        assert result.executive_sponsors[0]["name"] == "Kim"
        assert result.stakeholders[0]["stakeholder_for"] == "Business"
        assert result.project_team[0]["role"] == "Architecture"
        assert result.escalation_contacts == []
        assert result.success_criteria == ["PoC success"]
        assert result.assumptions == ["AWS account ready"]
        assert result.scope_of_work == ["Build prototype"]
        assert result.acceptance_text == "Customer sign-off"
        assert result.missing_fields == ["phase_schedule"]

    @patch("agent.app.discovery.discovery_agent.Agent")
    def test_parse_docx_schema_missing_values_default_empty(
        self, mock_agent_cls: MagicMock
    ) -> None:
        agent = DiscoveryAgent()
        parsed = agent._parse_agent_response(json.dumps({
            "executive_summary": None,
            "executive_sponsors": None,
            "success_criteria": None,
            "acceptance_text": None,
        }))

        assert parsed["executive_summary"] == ""
        assert parsed["executive_sponsors"] == []
        assert parsed["success_criteria"] == []
        assert parsed["acceptance_text"] == ""

    @pytest.mark.asyncio
    @patch("agent.app.discovery.discovery_agent.Agent")
    async def test_collect_info_with_partial_input(
        self, mock_agent_cls: MagicMock, empty_doc: DocumentState
    ) -> None:
        """Req 6.1, 6.3: 누락 항목 판별 및 재질문 생성."""
        mock_instance = MagicMock()
        llm_response = json.dumps({
            "extracted_fields": {
                "customer": "XYZ Inc",
            },
            "follow_up_questions": [],
        })
        mock_instance.return_value = llm_response
        mock_agent_cls.return_value = mock_instance

        agent = DiscoveryAgent()
        result = await agent.collect_info("XYZ Inc 프로젝트입니다.", empty_doc)

        assert result.can_generate_draft is False
        assert "project_goal" in result.missing.draft_required
        assert len(result.follow_up_questions) > 0

    @pytest.mark.asyncio
    @patch("agent.app.discovery.discovery_agent.Agent")
    async def test_collect_info_llm_failure_uses_keyword_fallback(
        self, mock_agent_cls: MagicMock, empty_doc: DocumentState
    ) -> None:
        """Falls back to keyword extraction when LLM fails."""
        mock_instance = MagicMock()
        mock_instance.side_effect = RuntimeError("LLM unavailable")
        mock_agent_cls.return_value = mock_instance

        agent = DiscoveryAgent()
        result = await agent.collect_info(
            "ABC 고객사의 목표는 GenAI PoC이고 범위는 문서 생성입니다.",
            empty_doc,
        )

        # Keyword fallback should extract customer, goal, scope
        assert "customer" in result.structured_input
        assert "project_goal" in result.structured_input
        assert "scope_summary" in result.structured_input

    @pytest.mark.asyncio
    @patch("agent.app.discovery.discovery_agent.Agent")
    async def test_collect_info_merges_existing_customer(
        self, mock_agent_cls: MagicMock, doc_with_customer: DocumentState
    ) -> None:
        """Existing doc_state customer is carried forward."""
        mock_instance = MagicMock()
        llm_response = json.dumps({
            "extracted_fields": {
                "project_goal": "Build PoC",
            },
            "follow_up_questions": [],
        })
        mock_instance.return_value = llm_response
        mock_agent_cls.return_value = mock_instance

        agent = DiscoveryAgent()
        result = await agent.collect_info("목표는 PoC 구축입니다.", doc_with_customer)

        assert result.structured_input.get("customer") == "ABC Corp"
        assert "customer" not in result.missing.draft_required

    @pytest.mark.asyncio
    @patch("agent.app.discovery.discovery_agent.Agent")
    async def test_export_required_questions_generated(
        self, mock_agent_cls: MagicMock, empty_doc: DocumentState
    ) -> None:
        """Req 6.3: export-required 누락 시 재질문 생성."""
        mock_instance = MagicMock()
        llm_response = json.dumps({
            "extracted_fields": {
                "customer": "ABC Corp",
                "project_goal": "PoC",
                "scope_summary": "문서 생성",
                "architecture_available": False,
            },
            "follow_up_questions": [],
        })
        mock_instance.return_value = llm_response
        mock_agent_cls.return_value = mock_instance

        agent = DiscoveryAgent()
        result = await agent.collect_info("ABC Corp PoC 문서 생성", empty_doc)

        # Draft can proceed
        assert result.can_generate_draft is True
        # But export-required questions are still generated
        assert len(result.follow_up_questions) > 0
        assert len(result.missing.export_required) > 0


# ---------------------------------------------------------------------------
# _has_value helper
# ---------------------------------------------------------------------------

class TestHasValue:
    def test_empty_field_value(self) -> None:
        assert _has_value(FieldValue()) is False

    def test_field_with_user_input(self) -> None:
        assert _has_value(FieldValue(user_input="test")) is True

    def test_field_with_ai_recommended(self) -> None:
        assert _has_value(FieldValue(ai_recommended="test")) is True

    def test_field_with_only_calculated(self) -> None:
        # calculated alone doesn't count as "has value" for discovery
        assert _has_value(FieldValue(calculated="test")) is False


# ---------------------------------------------------------------------------
# Keyword extraction fallback
# ---------------------------------------------------------------------------

class TestKeywordExtraction:
    @patch("agent.app.discovery.discovery_agent.Agent")
    def test_extracts_customer_keywords(self, mock_agent_cls: MagicMock) -> None:
        agent = DiscoveryAgent()
        result = agent._keyword_extract("ABC 고객사 프로젝트")
        assert "customer" in result

    @patch("agent.app.discovery.discovery_agent.Agent")
    def test_extracts_goal_keywords(self, mock_agent_cls: MagicMock) -> None:
        agent = DiscoveryAgent()
        result = agent._keyword_extract("프로젝트 목표는 AI 도입")
        assert "project_goal" in result

    @patch("agent.app.discovery.discovery_agent.Agent")
    def test_extracts_scope_keywords(self, mock_agent_cls: MagicMock) -> None:
        agent = DiscoveryAgent()
        result = agent._keyword_extract("프로젝트 범위는 문서 생성")
        assert "scope_summary" in result

    @patch("agent.app.discovery.discovery_agent.Agent")
    def test_extracts_architecture_keywords(self, mock_agent_cls: MagicMock) -> None:
        agent = DiscoveryAgent()
        result = agent._keyword_extract("기존 아키텍처 파일이 있습니다")
        assert result.get("architecture_available") is True

    @patch("agent.app.discovery.discovery_agent.Agent")
    def test_no_keywords_returns_empty(self, mock_agent_cls: MagicMock) -> None:
        agent = DiscoveryAgent()
        result = agent._keyword_extract("안녕하세요")
        assert len(result) == 0


# ---------------------------------------------------------------------------
# LLM response parsing
# ---------------------------------------------------------------------------

class TestParseAgentResponse:
    @patch("agent.app.discovery.discovery_agent.Agent")
    def test_parses_clean_json(self, mock_agent_cls: MagicMock) -> None:
        agent = DiscoveryAgent()
        response = json.dumps({
            "extracted_fields": {"customer": "ABC Corp"},
            "follow_up_questions": [],
        })
        result = agent._parse_agent_response(response)
        assert result["customer"] == "ABC Corp"

    @patch("agent.app.discovery.discovery_agent.Agent")
    def test_parses_json_in_code_fence(self, mock_agent_cls: MagicMock) -> None:
        agent = DiscoveryAgent()
        response = '```json\n{"extracted_fields": {"customer": "XYZ"}}\n```'
        result = agent._parse_agent_response(response)
        assert result["customer"] == "XYZ"

    @patch("agent.app.discovery.discovery_agent.Agent")
    def test_invalid_json_returns_empty(self, mock_agent_cls: MagicMock) -> None:
        agent = DiscoveryAgent()
        result = agent._parse_agent_response("not json at all")
        assert result == {}

    @patch("agent.app.discovery.discovery_agent.Agent")
    def test_null_values_filtered_out(self, mock_agent_cls: MagicMock) -> None:
        agent = DiscoveryAgent()
        response = json.dumps({
            "extracted_fields": {
                "customer": "ABC",
                "project_goal": None,
            },
        })
        result = agent._parse_agent_response(response)
        assert "customer" in result
        assert "project_goal" not in result
