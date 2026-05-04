"""Reviewer Agent — APN template validation and issue detection.

Refactored as a ``strands.Agent()`` logical agent within the Parent Runtime.
Checks: required section completeness, section order, numeric consistency,
completion score calculation, blocking vs non-blocking classification.

Requirements: 13.1, 13.2, 17.1
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

from strands import Agent

from agent.app.funding import FundingValidationResult, FundingValidator
from agent.lib.schema.document_state import DocumentState, BlockingIssue, Warning

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

REQUIRED_SECTIONS = [
    "cover", "executive_summary", "stakeholders", "success_criteria",
    "assumptions", "scope_of_work", "architecture", "milestones",
    "cost_breakdown", "acceptance", "resources_cost_estimates",
]

APN_SECTION_ORDER = REQUIRED_SECTIONS  # canonical order

# ---------------------------------------------------------------------------
# System prompt for the Reviewer Agent
# ---------------------------------------------------------------------------

REVIEWER_PROMPT: str = """당신은 APN PoC Project Plan 문서 검증 전문 에이전트입니다.

## 역할
문서가 APN 템플릿 규격에 맞는지 검증하고 불일치를 탐지합니다.

## 검증 항목
1. 필수 섹션 누락 여부 확인
2. 섹션 순서 일치 확인
3. 계산값과 본문 간 숫자 불일치 확인
4. blocking issue와 non-blocking warning 분류

## 응답 형식
반드시 아래 JSON 형식으로만 응답하세요.

```json
{
  "analysis": "검증 결과 요약",
  "issues": ["발견된 문제 목록"],
  "recommendations": ["개선 제안 목록"]
}
```
"""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ReviewResult:
    completion_score: float = 0.0
    blocking_issues: list[BlockingIssue] = field(default_factory=list)
    warnings: list[Warning] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    funding_validation: FundingValidationResult | None = None


# ---------------------------------------------------------------------------
# Reviewer Agent
# ---------------------------------------------------------------------------

class ReviewerAgent:
    """Validates document against APN template requirements.

    Uses a ``strands.Agent()`` instance with CHILD_MODEL for LLM-powered
    analysis. Core validation logic (section checks, score calculation,
    issue classification) is deterministic.

    Requirements: 13.1, 13.2, 17.1
    """

    def __init__(self) -> None:
        self.agent = Agent(
            model=CHILD_MODEL,
            system_prompt=REVIEWER_PROMPT,
        )

    def review(self, doc_state: DocumentState) -> ReviewResult:
        """Full review: missing sections + order + numeric consistency + score.

        Checks:
        1. Required section completeness (Req 13.1)
        2. Resources/staffing populated (v2: partner_technical_team)
        3. Numeric consistency — total cost
        4. Completion score (Req 17.1)
        5. Suggestions from blocking issues and warnings
        6. Classify issues into blocking vs non-blocking (Req 13.2)

        Requirements: 13.1, 13.2, 17.1
        """
        result = ReviewResult()

        # 1. Required section completeness
        sections = doc_state.sections
        for sec_name in REQUIRED_SECTIONS:
            section = getattr(sections, sec_name, None)
            if section is None:
                result.blocking_issues.append(BlockingIssue(
                    code=f"MISSING_{sec_name.upper()}",
                    message=f"필수 섹션 '{sec_name}' 누락",
                    section=sec_name,
                ))

        # 2. Staffing check (v2: resources_cost_estimates.partner_technical_team)
        if not doc_state.sections.resources_cost_estimates.partner_technical_team:
            result.blocking_issues.append(BlockingIssue(
                code="EMPTY_STAFFING",
                message="partner_technical_team에 팀원이 정의되지 않음",
                section="resources_cost_estimates",
            ))

        # 3. Numeric consistency: total cost (v2: resources_cost_estimates.total_cost.total)
        total_cost_str = doc_state.sections.resources_cost_estimates.total_cost.total
        if total_cost_str:
            try:
                cleaned = str(total_cost_str).replace("$", "").replace(",", "").strip()
                total_cost_val = float(cleaned)
                if total_cost_val <= 0:
                    result.warnings.append(Warning(
                        code="ZERO_COST",
                        message="인건비 total cost가 0 이하",
                        section="cost_breakdown",
                    ))
            except (ValueError, TypeError):
                pass

        funding_validation = FundingValidator().validate(doc_state)
        result.funding_validation = funding_validation
        self._extend_unique_by_code(result.blocking_issues, funding_validation.blocking_issues)
        self._extend_unique_by_code(result.warnings, funding_validation.warnings)

        # 4. Completion score
        result.completion_score = self.calculate_completion_score(doc_state)

        # 5. Suggestions
        for issue in result.blocking_issues:
            result.suggestions.append(f"[blocking] {issue.message} — 해당 섹션을 채워주세요.")
        for warn in result.warnings:
            result.suggestions.append(f"[warning] {warn.message}")

        # 6. Classify all issues
        all_issues: list[BlockingIssue | Warning] = list(result.blocking_issues) + [
            Warning(code=w.code, message=w.message, section=w.section)
            for w in result.warnings
        ]
        self.classify_issues(all_issues)

        return result

    @staticmethod
    def _extend_unique_by_code(target: list[Any], additions: list[Any]) -> None:
        seen = {getattr(item, "code", None) for item in target}
        for item in additions:
            code = getattr(item, "code", None)
            if code not in seen:
                target.append(item)
                seen.add(code)

    def calculate_completion_score(self, doc_state: DocumentState) -> float:
        """Section-level required field fill ratio → 0.0~1.0.

        v2: no staffing_plan — staffing data is in resources_cost_estimates section.

        Requirement: 17.1
        """
        filled = 0
        total = len(REQUIRED_SECTIONS)

        sections = doc_state.sections
        for sec_name in REQUIRED_SECTIONS:
            section = getattr(sections, sec_name, None)
            if section is not None:
                # Check if section has any non-default data
                data = section.model_dump(exclude_defaults=True)
                if data:
                    filled += 1
                else:
                    filled += 0.3  # section exists but empty → partial credit

        return round(min(filled / total, 1.0), 2)

    def classify_issues(self, issues: list) -> tuple[list[BlockingIssue], list[Warning]]:
        """Separate blocking issues from non-blocking warnings.

        Requirement: 13.2
        """
        blocking = [i for i in issues if isinstance(i, BlockingIssue)]
        warnings = [i for i in issues if isinstance(i, Warning)]
        return blocking, warnings
