"""Discovery Agent — project info collection and structuring.

Refactored as a ``strands.Agent()`` logical agent within the Parent Runtime.
Collects project information via LLM-powered analysis, identifies missing
fields, and distinguishes draft-required vs export-required inputs.

Requirements: 6.1, 6.2, 6.3, 6.4
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from strands import Agent

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
# Field classification constants
# ---------------------------------------------------------------------------

DRAFT_REQUIRED_FIELDS: list[str] = [
    "customer",
    "project_goal",
    "scope_summary",
    "architecture_available",
]

EXPORT_REQUIRED_FIELDS: list[str] = [
    "sponsor",
    "stakeholders",
    "team_detail",
    "phase_schedule",
    "cost_resources",
]

# ---------------------------------------------------------------------------
# System prompt for the Discovery Agent
# ---------------------------------------------------------------------------

DISCOVERY_PROMPT: str = """당신은 APN PoC Project Plan 문서 생성을 위한 프로젝트 정보 수집 전문 에이전트입니다.

## 역할
사용자의 입력에서 프로젝트 정보를 추출하고 구조화합니다.

## 추출 대상 필드
다음 필드를 사용자 입력에서 추출하세요:

### Draft-required (초안 생성 필수):
- customer: 고객사명
- project_goal: 프로젝트 목표
- scope_summary: 프로젝트 범위 요약
- architecture_available: 기존 아키텍처 자료 유무 (true/false)

### Export-required (DOCX export 필수):
- sponsor: 프로젝트 스폰서
- stakeholders: 이해관계자 목록
- team_detail: 팀 구성 상세
- phase_schedule: 단계별 일정
- cost_resources: 비용/리소스 정보
- executive_summary: 문서 Executive Summary 단락
- executive_sponsors: executive sponsor 연락처 목록
- project_team: 프로젝트 팀 연락처 목록
- escalation_contacts: escalation 연락처 목록
- success_criteria: 성공 기준 목록
- assumptions: 가정 사항 목록
- scope_of_work: 작업 범위 목록
- acceptance_text: 검수/승인 문구
- executive_summary.customer_intro/problem_statement/proposed_solution/phases_overview/business_case
- success_criteria.groups, assumptions.groups, scope_of_work.tasks

## 응답 형식
반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트를 포함하지 마세요.

```json
{
  "extracted_fields": {
    "customer": "추출된 고객사명 또는 null",
    "project_goal": "추출된 목표 또는 null",
    "scope_summary": "추출된 범위 또는 null",
    "architecture_available": true/false/null,
    "sponsor": "추출된 스폰서 또는 null",
    "stakeholders": "추출된 이해관계자 또는 null",
    "team_detail": "추출된 팀 상세 또는 null",
    "phase_schedule": "추출된 일정 또는 null",
    "cost_resources": "추출된 비용 정보 또는 null"
  },
  "executive_summary": {
    "customer_intro": "...",
    "problem_statement": "...",
    "proposed_solution": "...",
    "phases_overview": ["..."],
    "business_case": {
      "problem_definition": "...",
      "roi_calculation": "...",
      "executive_sponsor": "...",
      "production_commitment": "..."
    }
  },
  "executive_sponsors": [
    {"name": "...", "title": "...", "description": "...", "contact": "..."}
  ],
  "stakeholders": [
    {"name": "...", "title": "...", "stakeholder_for": "...", "contact": "..."}
  ],
  "project_team": [
    {"name": "...", "title": "...", "role": "...", "contact": "..."}
  ],
  "escalation_contacts": [
    {"name": "...", "title": "...", "role": "...", "contact": "..."}
  ],
  "success_criteria": ["item1", "item2"],
  "success_criteria_groups": [{"category_name": "Project Objective", "items": ["..."]}],
  "assumptions": ["item1", "item2"],
  "assumption_groups": [{"category_name": "Business Context", "items": ["..."]}],
  "scope_of_work": ["item1", "item2"],
  "scope_tasks": [{"task_category": "...", "schedule": "...", "details": ["..."], "personnel": "..."}],
  "acceptance_text": "single paragraph acceptance text, or empty string",
  "missing_fields": ["fields to ask user"],
  "follow_up_questions": ["누락된 필수 항목에 대한 재질문 목록"]
}
```
"""

# ---------------------------------------------------------------------------
# Follow-up question templates
# ---------------------------------------------------------------------------

_FOLLOW_UP_TEMPLATES: dict[str, str] = {
    "customer": "고객사명을 알려주세요.",
    "project_goal": "프로젝트의 주요 목표는 무엇인가요?",
    "scope_summary": "프로젝트 범위를 간략히 설명해주세요.",
    "architecture_available": "기존 아키텍처 자료(.drawio 등)가 있나요?",
    "sponsor": "프로젝트 스폰서 정보를 입력해주세요.",
    "stakeholders": "주요 이해관계자 목록을 알려주세요.",
    "team_detail": "팀 구성 상세 정보를 입력해주세요.",
    "phase_schedule": "단계별 일정 정보를 입력해주세요.",
    "cost_resources": "비용 및 리소스 정보를 입력해주세요.",
}

SUCCESS_CRITERIA_GROUP_LABELS = [
    "Strategy Development & Planning",
    "Technical Framework Design",
    "Implementation Roadmap",
    "Knowledge Transfer",
    "Project Objective",
]

ASSUMPTION_GROUP_LABELS = [
    "Business Context",
    "Technical Environment",
    "Project Execution",
    "Scope Boundaries",
    "Future Considerations",
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class MissingFields:
    """Classification of missing fields into draft-required vs export-required."""
    draft_required: list[str] = field(default_factory=list)
    export_required: list[str] = field(default_factory=list)


@dataclass
class DiscoveryResult:
    """Result of the discovery/collection process."""
    structured_input: dict[str, Any] = field(default_factory=dict)
    missing: MissingFields = field(default_factory=MissingFields)
    follow_up_questions: list[str] = field(default_factory=list)
    can_generate_draft: bool = False
    executive_summary: str = ""
    executive_sponsors: list[dict[str, str]] = field(default_factory=list)
    stakeholders: list[dict[str, str]] = field(default_factory=list)
    project_team: list[dict[str, str]] = field(default_factory=list)
    escalation_contacts: list[dict[str, str]] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    scope_of_work: list[str] = field(default_factory=list)
    acceptance_text: str = ""
    missing_fields: list[str] = field(default_factory=list)
    executive_summary_fields: dict[str, Any] = field(default_factory=dict)
    business_case: dict[str, Any] = field(default_factory=dict)
    success_criteria_groups: list[dict[str, Any]] = field(default_factory=list)
    assumption_groups: list[dict[str, Any]] = field(default_factory=list)
    scope_tasks: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Discovery Agent
# ---------------------------------------------------------------------------

class DiscoveryAgent:
    """Collects and structures project information from user input.

    Uses a ``strands.Agent()`` instance with CHILD_MODEL for LLM-powered
    input analysis. Falls back to keyword-based extraction if the LLM
    call fails.
    """

    def __init__(self) -> None:
        self.agent = Agent(
            model=CHILD_MODEL,
            system_prompt=DISCOVERY_PROMPT,
        )

    async def collect_info(
        self, user_input: str, doc_state: DocumentState
    ) -> DiscoveryResult:
        """Analyze input, identify missing items, structure or ask follow-ups.

        1. Send user input to the LLM agent for structured extraction
        2. Merge extracted fields with existing doc_state
        3. Classify missing fields (draft-required vs export-required)
        4. Generate follow-up questions for missing draft-required fields
        5. Determine if draft generation can proceed

        Requirements: 6.1, 6.2, 6.3, 6.4
        """
        # Step 1: Extract structured fields from user input
        extracted = await self._extract_fields(user_input)

        # Step 2: Merge with existing document state
        structured = self._merge_with_state(extracted, doc_state)

        # Step 3: Classify missing fields
        missing = self.classify_missing_fields(doc_state, structured)

        # Step 4: Generate follow-up questions for draft-required missing fields
        questions: list[str] = []
        for f in missing.draft_required:
            questions.append(_FOLLOW_UP_TEMPLATES.get(f, f"{f} 정보를 입력해주세요."))

        # Step 5: export-required missing → additional questions (Req 6.3)
        for f in missing.export_required:
            questions.append(_FOLLOW_UP_TEMPLATES.get(f, f"{f} 정보를 입력해주세요."))

        # draft-required만 누락 여부로 초안 생성 가능 판단 (Req 6.4)
        can_draft = len(missing.draft_required) == 0

        return DiscoveryResult(
            structured_input=structured,
            missing=missing,
            follow_up_questions=questions,
            can_generate_draft=can_draft,
            executive_summary=_executive_summary_text(structured.get("executive_summary")),
            executive_sponsors=_contact_list(structured.get("executive_sponsors")),
            stakeholders=_contact_list(structured.get("stakeholders")),
            project_team=_contact_list(structured.get("project_team")),
            escalation_contacts=_contact_list(structured.get("escalation_contacts")),
            success_criteria=_string_list(structured.get("success_criteria")),
            assumptions=_string_list(structured.get("assumptions")),
            scope_of_work=_string_list(structured.get("scope_of_work")),
            acceptance_text=_string_value(structured.get("acceptance_text")),
            missing_fields=_string_list(structured.get("missing_fields")),
            executive_summary_fields=_executive_summary_fields(structured.get("executive_summary")),
            business_case=_business_case(structured.get("executive_summary"), structured.get("business_case")),
            success_criteria_groups=_category_groups(
                structured.get("success_criteria_groups") or structured.get("success_criteria"),
                SUCCESS_CRITERIA_GROUP_LABELS,
            ),
            assumption_groups=_category_groups(
                structured.get("assumption_groups") or structured.get("assumptions"),
                ASSUMPTION_GROUP_LABELS,
            ),
            scope_tasks=_scope_tasks(structured.get("scope_tasks") or structured.get("scope_of_work")),
        )

    def classify_missing_fields(
        self,
        doc_state: DocumentState,
        collected: dict[str, Any] | None = None,
    ) -> MissingFields:
        """Classify missing fields into draft-required vs export-required.

        draft-required (초안 생성 필수):
            고객사명, 프로젝트 목표, 대략적 범위, 아키텍처 유무

        export-required (DOCX export 필수):
            Sponsor, Stakeholder, Team 상세, phase별 일정, 비용/리소스 정보

        When only export-required fields are missing, draft generation
        is NOT blocked (Req 6.4).
        """
        collected = collected or {}
        meta = doc_state.meta

        # --- Draft-required fields ---
        draft_missing: list[str] = []

        # customer: check collected dict AND doc_state.meta.customer
        if not collected.get("customer") and not _has_value(meta.customer):
            draft_missing.append("customer")

        # project_goal: check collected dict
        if not collected.get("project_goal"):
            draft_missing.append("project_goal")

        # scope_summary: check collected dict
        if not collected.get("scope_summary"):
            draft_missing.append("scope_summary")

        # architecture_available: check collected dict
        if collected.get("architecture_available") is None:
            draft_missing.append("architecture_available")

        # --- Export-required fields ---
        export_missing: list[str] = []
        for f in EXPORT_REQUIRED_FIELDS:
            if not collected.get(f):
                export_missing.append(f)

        return MissingFields(
            draft_required=draft_missing,
            export_required=export_missing,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _extract_fields(self, user_input: str) -> dict[str, Any]:
        """Use the LLM agent to extract structured fields from user input.

        Falls back to keyword-based extraction if the LLM call fails.
        """
        try:
            response = self.agent(user_input)
            return self._parse_agent_response(str(response))
        except Exception as exc:
            logger.warning(
                "LLM extraction failed, falling back to keyword extraction: %s",
                exc,
            )
            return self._keyword_extract(user_input)

    def _parse_agent_response(self, response_text: str) -> dict[str, Any]:
        """Parse the JSON response from the LLM agent."""
        # Try to find JSON block in the response
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
            parsed = json.loads(text)
            extracted = dict(parsed.get("extracted_fields", {}))
            for key, value in parsed.items():
                if key not in ("extracted_fields", "follow_up_questions"):
                    extracted[key] = value
            return _normalize_extracted(extracted)
        except (json.JSONDecodeError, ValueError):
            logger.warning("Failed to parse LLM response as JSON, using keyword fallback")
            return {}

    @staticmethod
    def _keyword_extract(user_input: str) -> dict[str, Any]:
        """Fallback keyword-based extraction when LLM is unavailable."""
        structured: dict[str, Any] = {}
        input_lower = user_input.lower()

        if any(kw in input_lower for kw in ["고객", "customer", "회사"]):
            structured["customer"] = _extract_customer_value(user_input)
        if any(kw in input_lower for kw in ["목표", "goal", "목적"]):
            structured["project_goal"] = user_input
        if any(kw in input_lower for kw in ["범위", "scope"]):
            structured["scope_summary"] = user_input
        if any(kw in input_lower for kw in ["아키텍처", "architecture", "drawio"]):
            structured["architecture_available"] = True

        return structured

    @staticmethod
    def _merge_with_state(
        extracted: dict[str, Any], doc_state: DocumentState
    ) -> dict[str, Any]:
        """Merge newly extracted fields with existing document state values."""
        merged = dict(extracted)

        # Carry forward existing meta.customer if not newly extracted
        if "customer" not in merged and _has_value(doc_state.meta.customer):
            merged["customer"] = (
                doc_state.meta.customer.user_input
                or doc_state.meta.customer.ai_recommended
            )

        return merged


def _has_value(field_value: FieldValue) -> bool:
    """Check if a FieldValue has any meaningful value set."""
    return bool(field_value.user_input or field_value.ai_recommended)


def _extract_customer_value(user_input: str) -> str:
    """Extract the customer name from simple Korean/English edit phrases."""
    text = user_input.strip()
    patterns = [
        r"([A-Za-z0-9가-힣_.&-]+)\s*고객사",
        r"고객사(?:명)?(?:는|은|를|을|로|으로|:|=)?\s*([A-Za-z0-9가-힣_.& -]+?)(?:\s*(?:으로|로)?\s*(?:수정|변경|설정|해줘|해주세요)|\s*입니다|\s*이다|$)",
        r"customer(?:\s+name)?\s*(?:is|to|=|:)?\s*([A-Za-z0-9가-힣_.& -]+?)(?:\s*(?:please|$))",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip(" .,:;은는이가을를")
            if value:
                return value
    return text


def _string_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [_string_value(v) for v in value if _string_value(v)]
    if isinstance(value, str):
        return [value] if value else []
    return [_string_value(value)]


def _executive_summary_text(value: Any) -> str:
    if isinstance(value, dict):
        return _string_value(
            value.get("summary")
            or value.get("text")
            or value.get("proposed_solution")
            or value.get("problem_statement")
        )
    return _string_value(value)


def _executive_summary_fields(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "customer_intro": _string_value(value.get("customer_intro")),
        "problem_statement": _string_value(value.get("problem_statement")),
        "proposed_solution": _string_value(value.get("proposed_solution")),
        "phases_overview": _string_list(value.get("phases_overview")),
    }


def _business_case(summary_value: Any, explicit_value: Any = None) -> dict[str, Any]:
    source = explicit_value
    if source is None and isinstance(summary_value, dict):
        source = summary_value.get("business_case")
    if not isinstance(source, dict):
        return {}
    return {
        "problem_definition": _string_value(source.get("problem_definition")),
        "roi_calculation": _string_value(source.get("roi_calculation")),
        "executive_sponsor": _string_value(source.get("executive_sponsor")),
        "production_commitment": _string_value(source.get("production_commitment")),
    }


def _category_groups(value: Any, default_labels: list[str]) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        groups = []
        for index, item in enumerate(value):
            groups.append({
                "category_name": _string_value(item.get("category_name") or item.get("name") or default_labels[min(index, len(default_labels) - 1)]),
                "items": _string_list(item.get("items")),
            })
        return groups
    items = _string_list(value)
    if not items:
        return []
    return [{"category_name": default_labels[0], "items": items}]


def _scope_tasks(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        return [
            {
                "task_category": _string_value(item.get("task_category") or item.get("category")),
                "schedule": _string_value(item.get("schedule")),
                "details": _string_list(item.get("details")),
                "personnel": _string_value(item.get("personnel")),
            }
            for item in value
        ]
    items = _string_list(value)
    if not items:
        return []
    return [{"task_category": "Scope Boundaries", "schedule": "", "details": items, "personnel": ""}]


def _contact_list(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    contacts: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        contacts.append({
            "name": _string_value(item.get("name")),
            "title": _string_value(item.get("title")),
            "description": _string_value(item.get("description")),
            "stakeholder_for": _string_value(item.get("stakeholder_for")),
            "role": _string_value(item.get("role")),
            "contact": _string_value(item.get("contact")),
        })
    return contacts


def _normalize_extracted(extracted: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    list_fields = {
        "executive_sponsors",
        "stakeholders",
        "project_team",
        "escalation_contacts",
        "success_criteria",
        "assumptions",
        "scope_of_work",
        "success_criteria_groups",
        "assumption_groups",
        "scope_tasks",
        "missing_fields",
    }
    string_fields = {"executive_summary", "acceptance_text"}

    for key, value in extracted.items():
        if value is None:
            if key in list_fields:
                normalized[key] = []
            elif key in string_fields:
                normalized[key] = ""
            continue
        normalized[key] = value

    return normalized
