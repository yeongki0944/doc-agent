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

ARCHITECTURE_PRIORITY_RULES: dict[str, dict[str, Any]] = {
    "amazon_bedrock": {"name": "Amazon Bedrock", "priority": 1, "category": "genai_core", "is_required_for_funding": True},
    "amazon_sagemaker": {"name": "Amazon SageMaker", "priority": 2, "category": "genai_core", "is_required_for_funding": False},
    "amazon_opensearch": {"name": "Amazon OpenSearch", "priority": 10, "category": "data", "is_required_for_funding": False},
    "amazon_s3": {"name": "Amazon S3", "priority": 11, "category": "data", "is_required_for_funding": False},
    "amazon_rds": {"name": "Amazon RDS", "priority": 12, "category": "data", "is_required_for_funding": False},
    "amazon_dynamodb": {"name": "Amazon DynamoDB", "priority": 13, "category": "data", "is_required_for_funding": False},
    "aws_lambda": {"name": "AWS Lambda", "priority": 20, "category": "compute", "is_required_for_funding": False},
    "amazon_ec2": {"name": "Amazon EC2", "priority": 21, "category": "compute", "is_required_for_funding": False},
    "amazon_ecs": {"name": "Amazon ECS", "priority": 22, "category": "compute", "is_required_for_funding": False},
    "amazon_api_gateway": {"name": "Amazon API Gateway", "priority": 30, "category": "network", "is_required_for_funding": False},
    "elastic_load_balancing": {"name": "Elastic Load Balancing", "priority": 31, "category": "network", "is_required_for_funding": False},
    "amazon_vpc": {"name": "Amazon VPC", "priority": 32, "category": "network", "is_required_for_funding": False},
    "aws_iam": {"name": "AWS IAM", "priority": 40, "category": "security", "is_required_for_funding": False},
    "aws_kms": {"name": "AWS KMS", "priority": 41, "category": "security", "is_required_for_funding": False},
    "aws_waf": {"name": "AWS WAF", "priority": 42, "category": "security", "is_required_for_funding": False},
    "amazon_cloudwatch": {"name": "Amazon CloudWatch", "priority": 50, "category": "monitoring", "is_required_for_funding": False},
}

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
  "overview": "overall architecture overview",
  "services": [
    {
      "service_name": "Amazon Bedrock",
      "service_id": "amazon_bedrock",
      "description": "service role",
      "sizing_rationale": "why this size/service is appropriate"
    }
  ],
  "analysis": "아키텍처 분석 요약",
  "recommendations": ["보완 사항1", "보완 사항2"],
  "architecture_description": "전체 아키텍처 설명",
  "description": "single paragraph architecture description",
  "tools": ["AWS Lambda", "DynamoDB"]
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
    analysis: str = ""
    recommendations: list[str] = field(default_factory=list)
    architecture_description: str = ""
    description: str = ""
    overview: str = ""
    services: list[Any] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
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
            model=CHILD_MODEL,
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
            services=self._post_process_services(llm_result.get("services", services)),
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
            description=llm_result.get("description", ""),
            overview=llm_result.get("overview", ""),
            tools=llm_result.get("tools", []),
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
            services=self._post_process_services(llm_result.get("services", [])),
            analysis=llm_result.get("analysis", ""),
            recommendations=llm_result.get("recommendations", []),
            architecture_description=llm_result.get(
                "architecture_description", ""
            ),
            description=llm_result.get("description", ""),
            overview=llm_result.get("overview", ""),
            tools=llm_result.get("tools", []),
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

    @staticmethod
    def _normalize_service_id(value: Any) -> str:
        raw = str(value or "").lower()
        raw = raw.replace("amazon web services", "aws")
        raw = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
        aliases = {
            "bedrock": "amazon_bedrock",
            "amazon_bedrock": "amazon_bedrock",
            "sagemaker": "amazon_sagemaker",
            "amazon_sagemaker": "amazon_sagemaker",
            "opensearch": "amazon_opensearch",
            "amazon_opensearch": "amazon_opensearch",
            "s3": "amazon_s3",
            "amazon_s3": "amazon_s3",
            "rds": "amazon_rds",
            "amazon_rds": "amazon_rds",
            "dynamodb": "amazon_dynamodb",
            "amazon_dynamodb": "amazon_dynamodb",
            "lambda": "aws_lambda",
            "aws_lambda": "aws_lambda",
            "ec2": "amazon_ec2",
            "amazon_ec2": "amazon_ec2",
            "ecs": "amazon_ecs",
            "amazon_ecs": "amazon_ecs",
            "api_gateway": "amazon_api_gateway",
            "amazon_api_gateway": "amazon_api_gateway",
            "elastic_load_balancing": "elastic_load_balancing",
            "elb": "elastic_load_balancing",
            "vpc": "amazon_vpc",
            "amazon_vpc": "amazon_vpc",
            "iam": "aws_iam",
            "aws_iam": "aws_iam",
            "kms": "aws_kms",
            "aws_kms": "aws_kms",
            "waf": "aws_waf",
            "aws_waf": "aws_waf",
            "cloudwatch": "amazon_cloudwatch",
            "amazon_cloudwatch": "amazon_cloudwatch",
        }
        return aliases.get(raw, raw)

    @classmethod
    def _service_name_from_id(cls, service_id: str, fallback: str = "") -> str:
        return ARCHITECTURE_PRIORITY_RULES.get(service_id, {}).get("name", fallback or service_id.replace("_", " ").title())

    @classmethod
    def _post_process_services(cls, services: Any) -> list[dict[str, Any]]:
        if not isinstance(services, list):
            services = []

        normalized: dict[str, dict[str, Any]] = {}
        for service in services:
            if isinstance(service, dict):
                name = service.get("service_name") or service.get("name") or service.get("service_id") or ""
                service_id = cls._normalize_service_id(service.get("service_id") or name)
                description = service.get("description", "")
                sizing_rationale = service.get("sizing_rationale", "")
            else:
                name = str(service)
                service_id = cls._normalize_service_id(name)
                description = ""
                sizing_rationale = ""

            if not service_id:
                continue
            rule = ARCHITECTURE_PRIORITY_RULES.get(service_id, {})
            normalized[service_id] = {
                "service_name": cls._service_name_from_id(service_id, str(name)),
                "service_id": service_id,
                "priority": rule.get("priority", 99),
                "category": rule.get("category", "compute"),
                "description": description,
                "sizing_rationale": sizing_rationale,
                "is_required_for_funding": rule.get("is_required_for_funding", False),
            }

        if "amazon_bedrock" not in normalized:
            rule = ARCHITECTURE_PRIORITY_RULES["amazon_bedrock"]
            normalized["amazon_bedrock"] = {
                "service_name": rule["name"],
                "service_id": "amazon_bedrock",
                "priority": rule["priority"],
                "category": rule["category"],
                "description": "Core GenAI foundation model service required for GenAIIC funding review.",
                "sizing_rationale": "Required GenAI workload foundation service.",
                "is_required_for_funding": True,
            }

        return sorted(normalized.values(), key=lambda item: (item["priority"], item["service_name"]))

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
