"""Tests for Architecture Agent — strands.Agent() logical agent refactoring.

Validates:
- Agent initialization with CHILD_MODEL and ARCHITECTURE_PROMPT
- analyze_existing(): .drawio parsing → AWS service extraction → LLM interpretation
- design_new(): project requirements → architecture draft generation
- generate_diagram(): Gateway client integration for diagram generation
- _extract_services_from_drawio(): service extraction logic (kept from v1)

Requirements: 5.1, 5.2, 5.3, 16.1, 16.2, 16.3, 16.4
"""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from agent.lib.schema.document_state import DocumentState
from agent.app.architecture.architecture_agent import (
    ArchitectureAgent,
    ArchitectureResult,
    DiagramArtifacts,
    ProjectContext,
    ARCHITECTURE_PROMPT,
    ARCHITECTURE_PRIORITY_RULES,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_DRAWIO = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<mxfile><diagram name="Arch">'
    '<mxGraphModel><root>'
    '<mxCell id="0"/><mxCell id="1" parent="0"/>'
    '<mxCell id="2" value="AWS Lambda" vertex="1" parent="1">'
    '<mxGeometry x="100" y="100" width="160" height="60" as="geometry"/>'
    '</mxCell>'
    '<mxCell id="3" value="Amazon DynamoDB" vertex="1" parent="1">'
    '<mxGeometry x="300" y="100" width="160" height="60" as="geometry"/>'
    '</mxCell>'
    '<mxCell id="4" value="API Gateway" vertex="1" parent="1">'
    '<mxGeometry x="100" y="200" width="160" height="60" as="geometry"/>'
    '</mxCell>'
    '</root></mxGraphModel></diagram></mxfile>'
)


@pytest.fixture
def empty_doc() -> DocumentState:
    return DocumentState(document_id="test-arch-001")


@pytest.fixture
def sample_project_context() -> ProjectContext:
    return ProjectContext(
        project_goal="GenAI 멀티에이전트 PoC",
        scope_summary="Bedrock 기반 문서 자동 생성 시스템",
        project_type="genai_multi_agent",
        requirements=["실시간 문서 동기화", "비용 자동 계산"],
        constraints=["ap-northeast-2 리전 제한"],
    )


# ---------------------------------------------------------------------------
# Agent initialization
# ---------------------------------------------------------------------------

class TestAgentInitialization:
    """Verify ArchitectureAgent creates a strands.Agent() instance."""

    @patch("agent.app.architecture.architecture_agent.Agent")
    def test_agent_created_with_child_model(self, mock_agent_cls: MagicMock) -> None:
        agent = ArchitectureAgent()
        mock_agent_cls.assert_called_once()
        call_kwargs = mock_agent_cls.call_args.kwargs
        assert "model_id" in call_kwargs
        assert "system_prompt" in call_kwargs

    @patch("agent.app.architecture.architecture_agent.Agent")
    def test_agent_uses_architecture_prompt(self, mock_agent_cls: MagicMock) -> None:
        agent = ArchitectureAgent()
        call_kwargs = mock_agent_cls.call_args.kwargs
        assert call_kwargs["system_prompt"] == ARCHITECTURE_PROMPT


# ---------------------------------------------------------------------------
# _extract_services_from_drawio()
# ---------------------------------------------------------------------------

class TestExtractServicesFromDrawio:
    """Validates: Requirement 16.1 — .drawio parsing and service extraction."""

    @patch("agent.app.architecture.architecture_agent.Agent")
    def test_extracts_services_from_valid_drawio(self, mock_agent_cls: MagicMock) -> None:
        agent = ArchitectureAgent()
        services = agent._extract_services_from_drawio(SAMPLE_DRAWIO)

        assert "lambda" in services
        assert "dynamodb" in services
        assert "api gateway" in services

    @patch("agent.app.architecture.architecture_agent.Agent")
    def test_extracts_from_plain_text_fallback(self, mock_agent_cls: MagicMock) -> None:
        """Falls back to text search when XML parsing fails."""
        agent = ArchitectureAgent()
        services = agent._extract_services_from_drawio(
            "This uses Lambda and S3 and CloudFront"
        )

        assert "lambda" in services
        assert "s3" in services
        assert "cloudfront" in services

    @patch("agent.app.architecture.architecture_agent.Agent")
    def test_empty_content_returns_empty(self, mock_agent_cls: MagicMock) -> None:
        agent = ArchitectureAgent()
        services = agent._extract_services_from_drawio("")
        assert services == []

    @patch("agent.app.architecture.architecture_agent.Agent")
    def test_returns_sorted_unique_services(self, mock_agent_cls: MagicMock) -> None:
        agent = ArchitectureAgent()
        content = "Lambda Lambda S3 S3 DynamoDB"
        services = agent._extract_services_from_drawio(content)
        assert services == sorted(set(services))


# ---------------------------------------------------------------------------
# analyze_existing() — with mocked LLM
# ---------------------------------------------------------------------------

class TestAnalyzeExisting:
    """Validates: Requirements 16.1, 16.2"""

    @pytest.mark.asyncio
    @patch("agent.app.architecture.architecture_agent.Agent")
    async def test_analyze_existing_with_llm(
        self, mock_agent_cls: MagicMock, empty_doc: DocumentState
    ) -> None:
        mock_instance = MagicMock()
        llm_response = json.dumps({
            "services": ["lambda", "dynamodb", "api gateway"],
            "analysis": "서버리스 API 아키텍처",
            "recommendations": ["CloudWatch 모니터링 추가 권장"],
            "architecture_description": "API Gateway → Lambda → DynamoDB 패턴",
            "description": "서버리스 API 처리 흐름",
            "tools": ["AWS Lambda", "Amazon DynamoDB"],
        })
        mock_instance.return_value = llm_response
        mock_agent_cls.return_value = mock_instance

        agent = ArchitectureAgent()
        result = await agent.analyze_existing(SAMPLE_DRAWIO, empty_doc)

        assert isinstance(result, ArchitectureResult)
        assert len(result.services) > 0
        assert result.analysis != ""
        assert isinstance(result.recommendations, list)
        assert result.description == "서버리스 API 처리 흐름"
        assert result.tools == ["AWS Lambda", "Amazon DynamoDB"]

    @pytest.mark.asyncio
    @patch("agent.app.architecture.architecture_agent.Agent")
    async def test_analyze_existing_llm_failure_uses_fallback(
        self, mock_agent_cls: MagicMock, empty_doc: DocumentState
    ) -> None:
        """Falls back to rule-based analysis when LLM fails."""
        mock_instance = MagicMock()
        mock_instance.side_effect = RuntimeError("LLM unavailable")
        mock_agent_cls.return_value = mock_instance

        agent = ArchitectureAgent()
        result = await agent.analyze_existing(SAMPLE_DRAWIO, empty_doc)

        assert len(result.services) > 0
        assert "서비스 식별됨" in result.analysis
        # Rule-based recommendations for missing IAM/CloudWatch
        assert any("IAM" in r for r in result.recommendations)
        assert any("CloudWatch" in r for r in result.recommendations)


# ---------------------------------------------------------------------------
# design_new() — with mocked LLM
# ---------------------------------------------------------------------------

class TestDesignNew:
    """Validates: Requirements 5.2, 16.3"""

    @pytest.mark.asyncio
    @patch("agent.app.architecture.architecture_agent.Agent")
    async def test_design_new_with_llm(
        self,
        mock_agent_cls: MagicMock,
        empty_doc: DocumentState,
        sample_project_context: ProjectContext,
    ) -> None:
        mock_instance = MagicMock()
        llm_response = json.dumps({
            "services": ["lambda", "dynamodb", "bedrock", "s3", "api gateway"],
            "analysis": "GenAI 멀티에이전트 아키텍처 초안",
            "recommendations": ["CloudWatch 모니터링 추가", "KMS 암호화 적용"],
            "architecture_description": "Bedrock 기반 멀티에이전트 시스템",
            "description": "Bedrock과 Lambda를 사용하는 멀티에이전트 시스템",
            "tools": ["Amazon Bedrock", "AWS Lambda"],
        })
        mock_instance.return_value = llm_response
        mock_agent_cls.return_value = mock_instance

        agent = ArchitectureAgent()
        result = await agent.design_new(sample_project_context, empty_doc)

        assert isinstance(result, ArchitectureResult)
        assert len(result.services) > 0
        assert result.analysis != ""
        assert result.description == "Bedrock과 Lambda를 사용하는 멀티에이전트 시스템"
        assert result.tools == ["Amazon Bedrock", "AWS Lambda"]

    @pytest.mark.asyncio
    @patch("agent.app.architecture.architecture_agent.Agent")
    async def test_design_new_llm_failure_adds_required_bedrock(
        self,
        mock_agent_cls: MagicMock,
        empty_doc: DocumentState,
        sample_project_context: ProjectContext,
    ) -> None:
        mock_instance = MagicMock()
        mock_instance.side_effect = RuntimeError("LLM unavailable")
        mock_agent_cls.return_value = mock_instance

        agent = ArchitectureAgent()
        result = await agent.design_new(sample_project_context, empty_doc)

        assert isinstance(result, ArchitectureResult)
        assert result.services[0]["service_id"] == "amazon_bedrock"
        assert result.services[0]["is_required_for_funding"] is True

    @patch("agent.app.architecture.architecture_agent.Agent")
    def test_post_process_services_sorts_and_adds_bedrock(
        self, mock_agent_cls: MagicMock
    ) -> None:
        services = ArchitectureAgent._post_process_services([
            {
                "service_name": "AWS Lambda",
                "service_id": "lambda",
                "description": "API compute",
                "sizing_rationale": "Serverless PoC",
            },
            {"service_name": "Amazon S3", "service_id": "s3"},
        ])

        service_ids = [service["service_id"] for service in services]
        priorities = [service["priority"] for service in services]

        assert service_ids[0] == "amazon_bedrock"
        assert priorities == sorted(priorities)
        assert services[0]["category"] == "genai_core"
        assert services[0]["is_required_for_funding"] is True
        assert service_ids == ["amazon_bedrock", "amazon_s3", "aws_lambda"]
        assert ARCHITECTURE_PRIORITY_RULES["amazon_bedrock"]["priority"] == 1


# ---------------------------------------------------------------------------
# generate_diagram() — with mocked Gateway client
# ---------------------------------------------------------------------------

class TestGenerateDiagram:
    """Validates: Requirement 16.4"""

    @pytest.mark.asyncio
    @patch("agent.app.architecture.architecture_agent.Agent")
    async def test_generate_diagram_success(self, mock_agent_cls: MagicMock) -> None:
        agent = ArchitectureAgent()

        mock_gateway = AsyncMock()
        mock_gateway.call_tool_safe.return_value = (
            {
                "drawio_s3_key": "docs/doc-001/diagrams/architecture.drawio",
                "preview_s3_key": "docs/doc-001/diagrams/architecture.png",
                "services_extracted": ["lambda", "dynamodb"],
            },
            None,
        )

        arch_result = ArchitectureResult(
            services=["lambda", "dynamodb"],
            architecture_description="Test architecture",
        )

        artifacts = await agent.generate_diagram(
            arch_result, mock_gateway, doc_id="doc-001"
        )

        assert isinstance(artifacts, DiagramArtifacts)
        assert "architecture.drawio" in artifacts.drawio_path
        assert "architecture.png" in artifacts.preview_path

        mock_gateway.call_tool_safe.assert_called_once_with(
            "generate_architecture_diagram",
            {
                "doc_id": "doc-001",
                "services": ["lambda", "dynamodb"],
                "architecture_description": "Test architecture",
            },
        )

    @pytest.mark.asyncio
    @patch("agent.app.architecture.architecture_agent.Agent")
    async def test_generate_diagram_with_existing_drawio(
        self, mock_agent_cls: MagicMock
    ) -> None:
        agent = ArchitectureAgent()

        mock_gateway = AsyncMock()
        mock_gateway.call_tool_safe.return_value = (
            {
                "drawio_s3_key": "docs/doc-002/diagrams/architecture.drawio",
                "preview_s3_key": "docs/doc-002/diagrams/architecture.png",
            },
            None,
        )

        arch_result = ArchitectureResult(services=["lambda"])

        artifacts = await agent.generate_diagram(
            arch_result,
            mock_gateway,
            doc_id="doc-002",
            existing_drawio=SAMPLE_DRAWIO,
        )

        call_args = mock_gateway.call_tool_safe.call_args
        assert call_args[0][1]["existing_drawio"] == SAMPLE_DRAWIO
        assert artifacts.drawio_path != ""

    @pytest.mark.asyncio
    @patch("agent.app.architecture.architecture_agent.Agent")
    async def test_generate_diagram_gateway_failure(
        self, mock_agent_cls: MagicMock
    ) -> None:
        """Gateway failure returns empty DiagramArtifacts."""
        agent = ArchitectureAgent()

        mock_gateway = AsyncMock()
        mock_gateway.call_tool_safe.return_value = (
            None,
            "Gateway tool 'generate_architecture_diagram' failed: timeout",
        )

        arch_result = ArchitectureResult(services=["lambda"])

        artifacts = await agent.generate_diagram(
            arch_result, mock_gateway, doc_id="doc-003"
        )

        assert artifacts.drawio_path == ""
        assert artifacts.preview_path == ""


# ---------------------------------------------------------------------------
# Rule-based recommendations
# ---------------------------------------------------------------------------

class TestRuleBasedRecommendations:

    @patch("agent.app.architecture.architecture_agent.Agent")
    def test_recommends_iam_when_missing(self, mock_agent_cls: MagicMock) -> None:
        recs = ArchitectureAgent._rule_based_recommendations(["lambda", "s3"])
        assert any("IAM" in r for r in recs)

    @patch("agent.app.architecture.architecture_agent.Agent")
    def test_recommends_cloudwatch_when_missing(self, mock_agent_cls: MagicMock) -> None:
        recs = ArchitectureAgent._rule_based_recommendations(["lambda", "iam"])
        assert any("CloudWatch" in r for r in recs)

    @patch("agent.app.architecture.architecture_agent.Agent")
    def test_no_iam_recommendation_when_present(self, mock_agent_cls: MagicMock) -> None:
        recs = ArchitectureAgent._rule_based_recommendations(
            ["lambda", "iam", "cloudwatch", "kms"]
        )
        assert not any("IAM" in r for r in recs)


# ---------------------------------------------------------------------------
# LLM response parsing
# ---------------------------------------------------------------------------

class TestParseAgentResponse:

    @patch("agent.app.architecture.architecture_agent.Agent")
    def test_parses_clean_json(self, mock_agent_cls: MagicMock) -> None:
        agent = ArchitectureAgent()
        response = json.dumps({
            "services": ["lambda"],
            "analysis": "test",
            "recommendations": [],
        })
        result = agent._parse_agent_response(response)
        assert result["services"] == ["lambda"]

    @patch("agent.app.architecture.architecture_agent.Agent")
    def test_parses_json_in_code_fence(self, mock_agent_cls: MagicMock) -> None:
        agent = ArchitectureAgent()
        response = '```json\n{"services": ["s3"], "analysis": "ok"}\n```'
        result = agent._parse_agent_response(response)
        assert result["services"] == ["s3"]

    @patch("agent.app.architecture.architecture_agent.Agent")
    def test_invalid_json_returns_empty(self, mock_agent_cls: MagicMock) -> None:
        agent = ArchitectureAgent()
        result = agent._parse_agent_response("not json")
        assert result == {}


# ---------------------------------------------------------------------------
# _build_design_prompt
# ---------------------------------------------------------------------------

class TestBuildDesignPrompt:

    def test_includes_all_context_fields(self) -> None:
        ctx = ProjectContext(
            project_goal="Build PoC",
            scope_summary="Document generation",
            project_type="genai",
            requirements=["real-time sync"],
            constraints=["ap-northeast-2"],
        )
        prompt = ArchitectureAgent._build_design_prompt(ctx)

        assert "Build PoC" in prompt
        assert "Document generation" in prompt
        assert "genai" in prompt
        assert "real-time sync" in prompt
        assert "ap-northeast-2" in prompt

    def test_handles_empty_context(self) -> None:
        ctx = ProjectContext()
        prompt = ArchitectureAgent._build_design_prompt(ctx)
        assert "AWS 아키텍처를 설계" in prompt
