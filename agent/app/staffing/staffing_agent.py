"""Staffing Agent — preset-based role/rate recommendation.

Refactored as a ``strands.Agent()`` logical agent within the Parent Runtime.
Selects the best preset based on project type rules, then builds
a staffing recommendation with ai_recommended values in the 4-property
pattern format (user_input / ai_recommended / calculated / status).

Team UI tab is a view over ``staffing_plan`` (top-level, outside sections).
``stakeholders`` section is for contact/org info only.

Requirements: 7.1, 7.2, 7.4, 7.5, 7.6
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from strands import Agent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model configuration
# ---------------------------------------------------------------------------

CHILD_MODEL: str = os.environ.get(
    "CHILD_MODEL",
    "apac.anthropic.claude-3-5-sonnet-20241022-v2:0",
)

PRESETS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "presets"

ROLE_CATEGORY_MAP = {
    "solution_architect": "solution_architect",
    "senior_solution_architect": "solution_architect",
    "lead_architect": "solution_architect",
    "ml_architect": "solution_architect",
    "architect": "solution_architect",
    "solutions_architect": "solution_architect",

    "data_engineer": "engineer",
    "ml_engineer": "engineer",
    "backend_engineer": "engineer",
    "frontend_engineer": "engineer",
    "devops_engineer": "engineer",
    "qa_engineer": "engineer",
    "engineer": "engineer",
    "backend_developer": "engineer",
    "frontend_developer": "engineer",

    "project_manager": "other",
    "delivery_manager": "other",
    "technical_writer": "other",
}

# ---------------------------------------------------------------------------
# System prompt for the Staffing Agent
# ---------------------------------------------------------------------------

STAFFING_PROMPT: str = """당신은 APN PoC Project Plan의 인력 구성 추천 전문 에이전트입니다.

## 역할
프로젝트 유형과 범위에 맞는 역할/인원/단가 조합을 추천합니다.
사전 분석된 preset 데이터를 기반으로 추천하며, 필요 시 보정 이유를 설명합니다.

## 추천 원칙
1. staffing_presets.json에서 프로젝트 유형에 맞는 preset을 선택합니다.
2. rate_card.json의 단가 범위(min~max)를 벗어나지 않습니다.
3. 각 역할에 대해 count, allocation_pct, rate_per_hour, phase별 hours를 추천합니다.
4. 추천 이유(reason)와 출처 패턴(source_patterns)을 포함합니다.

## 기본 프로젝트 유형
GenAI 멀티에이전트 PoC — 6개 역할:
- Project Manager, Solutions Architect, ML Engineer
- Backend Developer, Frontend Developer, QA Engineer

## 응답 형식
반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트를 포함하지 마세요.

```json
{
  "project_type": "genai_multi_agent",
  "adjustments": [
    {"role_id": "...", "field": "...", "reason": "보정 이유"}
  ],
  "summary": "전체 추천 요약"
}
```
"""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RateViolation:
    role_id: str
    field: str
    value: float
    min_val: float
    max_val: float


@dataclass
class StaffingRecommendation:
    """Recommendation result with roles in 4-property pattern format."""
    project_type: str
    roles: dict[str, dict[str, Any]] = field(default_factory=dict)
    violations: list[RateViolation] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_json(name: str) -> dict:
    with open(PRESETS_DIR / name) as f:
        return json.load(f)


def categorize_role(role_id: str) -> str:
    rid = role_id.lower()
    if rid in ROLE_CATEGORY_MAP:
        return ROLE_CATEGORY_MAP[rid]
    if "architect" in rid:
        return "solution_architect"
    if "engineer" in rid or "developer" in rid:
        return "engineer"
    return "other"


# ---------------------------------------------------------------------------
# Staffing Agent
# ---------------------------------------------------------------------------

class StaffingAgent:
    """Preset-based role/rate recommendation agent.

    Uses a ``strands.Agent()`` instance with CHILD_MODEL for LLM-powered
    adjustment reasoning. Core recommendation logic is deterministic
    (preset selection + rate validation); the LLM provides supplementary
    reasoning and context-aware adjustments.

    Requirements: 7.1, 7.2, 7.4, 7.5, 7.6
    """

    def __init__(self) -> None:
        self.agent = Agent(
            model_id=CHILD_MODEL,
            system_prompt=STAFFING_PROMPT,
        )
        self.role_catalog = _load_json("role_catalog.json")
        self.rate_card = _load_json("rate_card.json")
        self.staffing_presets = _load_json("staffing_presets.json")
        self.phase_patterns = _load_json("phase_hour_patterns.json")
        self.type_rules = _load_json("project_type_rules.json")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def recommend(self, project_description: str) -> StaffingRecommendation:
        """Build a staffing recommendation from presets.

        Outputs each role field in the 4-property pattern:
          user_input / ai_recommended / calculated / status

        The recommendation is stored as ``ai_recommended`` in the
        top-level ``staffing_plan``.

        Requirements: 7.1, 7.2, 7.5
        """
        ptype = self._detect_project_type(project_description)
        preset = self.staffing_presets.get(ptype, {})
        phase_pattern = self.phase_patterns.get(ptype, {})
        preset_roles = preset.get("roles", {})

        rec = StaffingRecommendation(project_type=ptype)

        for role_id, role_preset in preset_roles.items():
            catalog_entry = self.role_catalog.get(role_id, {})
            phases = phase_pattern.get("phases", {})
            reason = f"{ptype} preset 기반 추천"
            source = [f"preset_{ptype}"]

            # Clamp rate to rate_card bounds (Req 7.4)
            rate = role_preset.get("rate_per_hour", 0)
            card = self.rate_card.get(role_id)
            if card:
                rate = max(card["min"], min(rate, card["max"]))

            rec.roles[role_id] = {
                "role_id": role_id,
                "display_name": catalog_entry.get("display_name", role_id),
                "category": categorize_role(role_id),
                "count": {
                    "user_input": None,
                    "ai_recommended": role_preset.get("count", 1),
                    "calculated": None,
                    "status": "recommended",
                },
                "allocation_pct": {
                    "user_input": None,
                    "ai_recommended": role_preset.get("allocation_pct", 100),
                    "calculated": None,
                    "status": "recommended",
                },
                "rate_per_hour": {
                    "user_input": None,
                    "ai_recommended": rate,
                    "calculated": None,
                    "status": "recommended",
                },
                "phase_hours": {
                    phase: {
                        "user_input": None,
                        "ai_recommended": info.get("default_hours", 0),
                        "calculated": None,
                        "status": "recommended",
                    }
                    for phase, info in phases.items()
                },
                "reason": reason,
                "source_patterns": source,
                "confidence": 0.85,
            }

        rec.violations = self.validate_rates(rec)
        return rec

    def validate_rates(self, rec: StaffingRecommendation) -> list[RateViolation]:
        """Check all recommended rates against rate_card bounds.

        Requirements: 7.4
        """
        violations: list[RateViolation] = []
        for role_id, role_data in rec.roles.items():
            card = self.rate_card.get(role_id)
            if not card:
                continue
            # Extract rate from 4-property pattern or plain value
            rate_field = role_data.get("rate_per_hour", {})
            if isinstance(rate_field, dict):
                rate = rate_field.get("ai_recommended") or 0
            else:
                rate = rate_field
            if rate < card["min"] or rate > card["max"]:
                violations.append(RateViolation(
                    role_id=role_id, field="rate_per_hour",
                    value=rate, min_val=card["min"], max_val=card["max"],
                ))
        return violations

    # ------------------------------------------------------------------
    # Project type detection
    # ------------------------------------------------------------------

    def _detect_project_type(self, text: str) -> str:
        """Detect project type from description using keyword rules."""
        text_lower = text.lower()
        for rule in self.type_rules.get("rules", []):
            if any(kw in text_lower for kw in rule.get("keywords", [])):
                return rule["type"]
        return self.type_rules.get("default_type", "genai_multi_agent")
