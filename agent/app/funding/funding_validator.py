"""Deterministic GenAIIC PLD funding validation.

This module performs local schema inspection only. It makes no AWS calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from agent.lib.schema.document_state import (
    BlockingIssue,
    DocumentState,
    FieldValue,
    Warning,
)


@dataclass
class FundingValidationResult:
    is_eligible: bool = False
    blocking_issues: list[BlockingIssue] = field(default_factory=list)
    warnings: list[Warning] = field(default_factory=list)
    checklist: dict[str, bool] = field(default_factory=dict)


def _effective_value(value: Any) -> Any:
    if isinstance(value, FieldValue):
        for candidate in (value.user_input, value.ai_recommended, value.calculated):
            if candidate not in (None, ""):
                return candidate
        return None
    if isinstance(value, dict):
        for key in ("user_input", "ai_recommended", "calculated"):
            candidate = value.get(key)
            if candidate not in (None, ""):
                return candidate
        return None
    if hasattr(value, "calculated"):
        return getattr(value, "calculated")
    return value


def _to_float(value: Any) -> float:
    resolved = _effective_value(value)
    if resolved in (None, ""):
        return 0.0
    try:
        return float(resolved)
    except (TypeError, ValueError):
        return 0.0


def _has_value(value: Any) -> bool:
    resolved = _effective_value(value)
    return resolved not in (None, "", [], {})


class FundingValidator:
    """Validate APN PoC Project Plan readiness for GenAIIC PLD review."""

    def __init__(self, today: date | None = None) -> None:
        self.today = today or datetime.now(timezone.utc).date()

    def validate(self, doc_state: DocumentState) -> FundingValidationResult:
        result = FundingValidationResult()
        checklist = {
            "bedrock_included": self.has_bedrock(doc_state),
            "calculator_url_present": self.has_calculator_url(doc_state),
            "sow_cost_present": self.has_sow_cost(doc_state),
            "problem_definition_present": self._business_case_has(doc_state, "problem_definition"),
            "roi_calculation_present": self._business_case_has(doc_state, "roi_calculation"),
            "executive_sponsor_present": self._business_case_has(doc_state, "executive_sponsor"),
            "production_commitment_present": self._business_case_has(doc_state, "production_commitment"),
        }
        result.checklist = checklist

        if not checklist["bedrock_included"]:
            result.blocking_issues.append(BlockingIssue(
                code="BEDROCK_MISSING",
                message="Amazon Bedrock is required in architecture services for GenAIIC PLD funding review.",
                section="architecture",
            ))
        if not checklist["calculator_url_present"]:
            result.blocking_issues.append(BlockingIssue(
                code="CALCULATOR_URL_MISSING",
                message="AWS Calculator URL is required for funding review.",
                section="cost_breakdown",
            ))
        if not checklist["sow_cost_present"]:
            result.blocking_issues.append(BlockingIssue(
                code="SOW_COST_MISSING",
                message="SOW cost is required for funding review.",
                section="cost_breakdown",
            ))

        warning_specs = [
            ("problem_definition_present", "BUSINESS_CASE_PROBLEM_DEFINITION_MISSING", "Business case problem definition is missing."),
            ("roi_calculation_present", "BUSINESS_CASE_ROI_CALCULATION_MISSING", "Business case ROI calculation is missing."),
            ("executive_sponsor_present", "BUSINESS_CASE_EXECUTIVE_SPONSOR_MISSING", "Business case executive sponsor is missing."),
            ("production_commitment_present", "BUSINESS_CASE_PRODUCTION_COMMITMENT_MISSING", "Business case production commitment is missing."),
        ]
        for checklist_key, code, message in warning_specs:
            if not checklist[checklist_key]:
                result.warnings.append(Warning(code=code, message=message, section="executive_summary"))

        if self._poc_start_date_too_soon(doc_state):
            result.warnings.append(Warning(
                code="POC_START_DATE_TOO_SOON",
                message="POC start date is less than 14 days from today.",
                section="cover",
            ))

        result.is_eligible = not result.blocking_issues
        return result

    def calculate_funding(self, doc_state: DocumentState) -> dict[str, float]:
        cost = doc_state.sections.cost_breakdown
        funding = cost.funding_calculation

        annual_aws_arr = _to_float(funding.yr1_arr)
        if annual_aws_arr <= 0:
            annual_aws_arr = self._aws_annual_cost(doc_state)

        sow_cost = self._sow_cost(doc_state)
        funding_25pct_arr = round(annual_aws_arr * 0.25, 2)
        eligible_amount = round(min(funding_25pct_arr, sow_cost, funding.funding_cap), 2)
        if annual_aws_arr <= 0 or sow_cost <= 0:
            eligible_amount = 0.0

        return {
            "yr1_arr": annual_aws_arr,
            "sow_cost": sow_cost,
            "funding_25pct_arr": funding_25pct_arr,
            "eligible_amount": eligible_amount,
        }

    def has_bedrock(self, doc_state: DocumentState) -> bool:
        architecture = doc_state.sections.architecture
        for service in architecture.services:
            candidates = [
                _effective_value(service.service_name),
                getattr(service, "service_id", None),
            ]
            model_extra = getattr(service, "model_extra", None)
            if isinstance(model_extra, dict):
                candidates.append(model_extra.get("service_id"))
            if any("bedrock" in str(candidate).lower() for candidate in candidates if candidate):
                return True

        extra_services = getattr(architecture, "model_extra", {}).get("services")
        if isinstance(extra_services, list):
            for service in extra_services:
                if isinstance(service, dict):
                    candidates = [service.get("service_name"), service.get("service_id"), service.get("name")]
                    if any("bedrock" in str(candidate).lower() for candidate in candidates if candidate):
                        return True
        return False

    def has_calculator_url(self, doc_state: DocumentState) -> bool:
        return bool(doc_state.sections.cost_breakdown.aws_service_cost.calculator_share_url)

    def has_sow_cost(self, doc_state: DocumentState) -> bool:
        return self._sow_cost(doc_state) > 0

    def _business_case_has(self, doc_state: DocumentState, field_name: str) -> bool:
        business_case = doc_state.sections.executive_summary.business_case
        return _has_value(getattr(business_case, field_name))

    def _sow_cost(self, doc_state: DocumentState) -> float:
        cost = doc_state.sections.cost_breakdown
        configured_sow_cost = _to_float(cost.funding_calculation.sow_cost)
        if configured_sow_cost > 0:
            return configured_sow_cost

        staffing_total = _to_float(doc_state.staffing_plan.grand_total_cost)
        if staffing_total <= 0:
            staffing_total = _to_float(cost.staffing_cost.grand_total)
        return round(staffing_total + self._aws_annual_cost(doc_state), 2)

    def _aws_annual_cost(self, doc_state: DocumentState) -> float:
        monthly = _to_float(doc_state.sections.cost_breakdown.aws_service_cost.monthly_cost_summary)
        return round(monthly * 12, 2)

    def _poc_start_date_too_soon(self, doc_state: DocumentState) -> bool:
        raw = (
            self._cover_extra_value(doc_state, "start_date")
            or self._cover_extra_value(doc_state, "poc_start_date")
            or _effective_value(doc_state.meta.date)
        )
        if not raw:
            return False
        try:
            start_date = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
        except ValueError:
            return False
        return 0 <= (start_date - self.today).days < 14

    def _cover_extra_value(self, doc_state: DocumentState, key: str) -> Any:
        cover = doc_state.sections.cover
        extra = getattr(cover, "model_extra", {}) or {}
        return _effective_value(extra.get(key))
