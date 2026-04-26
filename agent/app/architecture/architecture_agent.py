"""Architecture Agent — analyze existing or design new architectures.

Refactored as a ``strands.Agent()`` logical agent within the Parent Runtime.
Supports dual entry modes:
  - ``architecture_present``: parse .drawio → extract AWS services → interpret/supplement
    → store original to S3 + generate/reuse preview
  - ``architecture_absent``: generate architecture draft from project requirements

Requirements: 5.1, 5.2, 5.3, 16.1, 16.2, 16.3, 16.4
"""

from __future__ import annotations

import json
import logging
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Optional

from strands import Agent

from agent.lib.gateway.agentcore_gateway import AgentCoreGatewayClient
from agent.lib.schema.document_state import DocumentState, FieldValue, FieldStatus

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model configuration
# ---------------------------------------------------------------------------

CHILD_MODEL: str = os.environ.get(
    "CHILD_MODEL",
    "apac.anthropic.claude-3-5-sonnet-20241022-v2:0",
)

# ---------------------------------------------------------------------------
# AWS service extraction patterns
# ---------------------------------------------------------------------------

AWS_SERVICE_PATTERNS = [
    r"lambda", r"s3", r"dynamodb", r"api\s*gateway", r"appsync",
    r"bedrock", r"sagemaker", r"cloudfront", r"cognito", r"iam",
    r"sns", r"sqs", r"step\s*functions", r"ecs", r"eks", r"ec2",
    r"rds", r"aurora", r"elasticache", r"kinesis", r"eventbridge",
    r"codebuild", r"codepipeline", r"cloudwatch", r"kms",
]

# ---------------------------------------------------------------------------
# System prompt for the Architecture Agent
# ---------------------------------------------------------------------------

ARCHITECTURE_PROMPT: str = """당신은 AWS 아키텍처 분석 및 설계 전문 에이전트입니다.

## 역할
1. 기존 .drawio 아키텍처 다이어그램을 분석하여 AWS 서비스 구성을 해석하고 보완 사항을 제안합니다.
2. 프로젝트 요구사항으로부터 새로운 AWS 아키텍처 초안을 생성합니다.

## 분석 모드 (architecture_present)
.drawio XML에서 추출된 AWS 서비스 목록을 받으면:
- 각 서비스의 역할과 상호 연결을 해석합니다
- 누락된 필수 서비스(IAM, CloudWatch 등)를 식별합니다
- 보안, 모니터링, 비용 최적화 관점의 보완 사항을 제안합니다

## 설계 모드 (architecture_absent)
프로젝트 요구사항을 받으면:
- 프로젝트 유형에 적합한 AWS 서비스 조합을 추천합니다
- 서비스 간 연결 구조를 설계합니다
- 각 서비스 선택 이유를 설명합니다

## 응답 형식
반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트를 포함하지 마세요.

```json
{
  "services": ["서비스1", "서비스2"],
  "analysis": "아키텍처 분석 요약",
  "recommendations": ["보완 사항1", "보완 사항2"],
  "architecture_description": "전체 아키텍처 설명"
}
```
"""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ProjectContext:
    """Context for designing a new architecture."""
    project_goal: str = ""
    scope_summary: str = ""
    project_type: str = ""
    requirements: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)


@dataclass
class ArchitectureResult:
    """Result of architecture analysis or design."""
    services: list[str] = field(default_factory=list)
    analysis: str = ""
    recommendations: list[str] = field(default_factory=list)
    architecture_description: str = ""
    drawio_s3_path: Optional[str] = None
    preview_s3_path: Optional[str] = None


@dataclass
class DiagramArtifacts:
    """S3 paths for generated diagram artifacts."""
    drawio_path: str = ""
    preview_path: str = ""  # .png or .svg


# ---------------------------------------------------------------------------
# Architecture Agent
# ---------------------------------------------------------------------------

class ArchitectureAgent:
    """Analyzes existing architectures or assists in designing new ones.

    Uses a ``strands.Agent()`` instance with CHILD_MODEL for LLM-powered
    architecture analysis and design. Falls back to rule-based logic if
    the LLM call fails.

    Requirements: 5.1, 5.2, 5.3, 16.1, 16.2, 16.3, 16.4
    """

    def __init__(self) -> None:
        self.agent = Agent(
            model_id=CHILD_MODEL,
            system_prompt=ARCHITECTURE_PROMPT,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def analyze_existing(
        self, drawio_content: str, doc_state: DocumentState
    ) -> ArchitectureResult:
        """Parse .drawio XML, extract AWS services, interpret and supplement.

        Steps:
          1. Extract AWS services from .drawio XML content
          2. Use LLM agent to interpret services and suggest improvements
          3. Return structured result with services, analysis, recommendations

        The caller is responsible for uploading the original .drawio to S3
        and wiring preview generation via ``generate_diagram()``.

        Requirements: 16.1, 16.2
        """
        services = self._extract_services_from_drawio(drawio_content)

        # Use LLM for deeper analysis
        llm_result = await self._llm_analyze(services, drawio_content)

        # Merge LLM analysis with extracted services
        result = ArchitectureResult(
            services=llm_result.get("services", services),
            analysis=llm_result.get(
                "analysis",
                f"{len(services)}개 AWS 서비스 식별됨",
            ),
            recommendations=llm_result.get(
                "recommendations",
                self._rule_based_recommendations(services),
            ),
            architecture_description=llm_result.get(
                "architecture_description", ""
            ),
        )

        return result

    async def design_new(
        self,
        project_context: ProjectContext,
        doc_state: DocumentState,
    ) -> ArchitectureResult:
        """Generate an AWS architecture draft from project requirements.

        Used in ``architecture_absent`` mode when no .drawio file is provided.
        The LLM agent recommends AWS services and designs the architecture
        based on the project type, goals, and constraints.

        Requirements: 5.2, 16.3
        """
        prompt = self._build_design_prompt(project_context)

        llm_result = await self._llm_design(prompt)

        result = ArchitectureResult(
            services=llm_result.get("services", []),
            analysis=llm_result.get("analysis", ""),
            recommendations=llm_result.get("recommendations", []),
            architecture_description=llm_result.get(
                "architecture_description", ""
            ),
        )

        return result

    async def generate_diagram(
        self,
        architecture: ArchitectureResult,
        gateway_client: AgentCoreGatewayClient,
        doc_id: str = "",
        existing_drawio: Optional[str] = None,
    ) -> DiagramArtifacts:
        """Call Gateway ``generate_architecture_diagram`` tool.

        Invokes the common Gateway client to generate .drawio + preview
        artifacts and store them in S3.

        Requirements: 16.4
        """
        params: dict[str, Any] = {
            "doc_id": doc_id,
            "services": architecture.services,
            "architecture_description": architecture.architecture_description,
        }
        if existing_drawio:
            params["existing_drawio"] = existing_drawio

        result, error = await gateway_client.call_tool_safe(
            "generate_architecture_diagram", params
        )

        if error or result is None:
            logger.warning(
                "generate_architecture_diagram failed: %s", error
            )
            return DiagramArtifacts()

        return DiagramArtifacts(
            drawio_path=result.get("drawio_s3_key", ""),
            preview_path=result.get("preview_s3_key", ""),
        )

    # ------------------------------------------------------------------
    # Service extraction (kept from v1)
    # ------------------------------------------------------------------

    def _extract_services_from_drawio(self, content: str) -> list[str]:
        """Extract AWS service names from .drawio XML content."""
        found: set[str] = set()
        text_content = content.lower()

        # Try XML parsing
        try:
            root = ET.fromstring(content)
            for elem in root.iter():
                val = elem.get("value", "") or elem.get("label", "") or ""
                text_content += " " + val.lower()
        except ET.ParseError:
            pass

        for pattern in AWS_SERVICE_PATTERNS:
            if re.search(pattern, text_content, re.IGNORECASE):
                found.add(
                    pattern.replace(r"\s*", " ").replace("\\s*", " ").strip()
                )

        return sorted(found)

    # ------------------------------------------------------------------
    # LLM interaction helpers
    # ------------------------------------------------------------------

    async def _llm_analyze(
        self, services: list[str], drawio_content: str
    ) -> dict[str, Any]:
        """Use the LLM agent to analyze extracted services.

        Falls back to rule-based analysis on failure.
        """
        prompt = (
            f"다음 AWS 서비스가 .drawio 아키텍처에서 추출되었습니다:\n"
            f"{json.dumps(services, ensure_ascii=False)}\n\n"
            f"이 아키텍처를 분석하고 보완 사항을 제안해주세요."
        )

        try:
            response = self.agent(prompt)
            return self._parse_agent_response(str(response))
        except Exception as exc:
            logger.warning(
                "LLM analysis failed, using rule-based fallback: %s", exc
            )
            return {
                "services": services,
                "analysis": f"{len(services)}개 AWS 서비스 식별됨",
                "recommendations": self._rule_based_recommendations(services),
            }

    async def _llm_design(self, prompt: str) -> dict[str, Any]:
        """Use the LLM agent to design a new architecture.

        Falls back to empty result on failure.
        """
        try:
            response = self.agent(prompt)
            return self._parse_agent_response(str(response))
        except Exception as exc:
            logger.warning(
                "LLM design failed, returning empty result: %s", exc
            )
            return {}

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse_agent_response(self, response_text: str) -> dict[str, Any]:
        """Parse the JSON response from the LLM agent."""
        text = response_text.strip()

        # Strip markdown code fences if present
        if "```json" in text:
            start = text.index("```json") + len("```json")
            end = text.index("```", start)
            text = text[start:end].strip()
        elif "```" in text:
            start = text.index("```") + len("```")
            end = text.index("```", start)
            text = text[start:end].strip()

        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            logger.warning("Failed to parse LLM response as JSON")
            return {}

    # ------------------------------------------------------------------
    # Rule-based fallbacks
    # ------------------------------------------------------------------

    @staticmethod
    def _rule_based_recommendations(services: list[str]) -> list[str]:
        """Generate recommendations based on missing common services."""
        recommendations: list[str] = []
        lower_services = [s.lower() for s in services]

        if not any("iam" in s for s in lower_services):
            recommendations.append("IAM 역할/정책 정의 추가 권장")
        if not any("cloudwatch" in s for s in lower_services):
            recommendations.append("CloudWatch 모니터링 추가 권장")
        if not any("kms" in s for s in lower_services):
            recommendations.append("KMS 암호화 키 관리 추가 권장")

        return recommendations

    @staticmethod
    def _build_design_prompt(ctx: ProjectContext) -> str:
        """Build a design prompt from project context."""
        parts = [
            "다음 프로젝트 요구사항에 맞는 AWS 아키텍처를 설계해주세요.\n",
        ]
        if ctx.project_goal:
            parts.append(f"프로젝트 목표: {ctx.project_goal}")
        if ctx.scope_summary:
            parts.append(f"범위: {ctx.scope_summary}")
        if ctx.project_type:
            parts.append(f"프로젝트 유형: {ctx.project_type}")
        if ctx.requirements:
            parts.append(f"요구사항: {', '.join(ctx.requirements)}")
        if ctx.constraints:
            parts.append(f"제약사항: {', '.join(ctx.constraints)}")

        return "\n".join(parts)
