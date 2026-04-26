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
  "executive_summary": "single paragraph text",
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
  "assumptions": ["item1", "item2"],
  "scope_of_work": ["item1", "item2"],
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
            model_id=CHILD_MODEL,
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
            executive_summary=_string_value(structured.get("executive_summary")),
            executive_sponsors=_contact_list(structured.get("executive_sponsors")),
            stakeholders=_contact_list(structured.get("stakeholders")),
            project_team=_contact_list(structured.get("project_team")),
            escalation_contacts=_contact_list(structured.get("escalation_contacts")),
            success_criteria=_string_list(structured.get("success_criteria")),
            assumptions=_string_list(structured.get("assumptions")),
            scope_of_work=_string_list(structured.get("scope_of_work")),
            acceptance_text=_string_value(structured.get("acceptance_text")),
            missing_fields=_string_list(structured.get("missing_fields")),
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
            structured["customer"] = user_input
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

    for key in list_fields:
        if key not in normalized:
            normalized[key] = []
    for key in string_fields:
        if key not in normalized:
            normalized[key] = ""
    return normalized
