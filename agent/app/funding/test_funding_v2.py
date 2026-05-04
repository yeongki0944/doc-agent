"""Funding validator v2 unit tests.

Tests FundingValidator against the v2 DocumentState schema paths.
No AWS calls, no hypothesis — pytest only.

Requirements: 7.1–7.9, 8.5
"""

import json

from agent.app.funding.funding_validator import FundingValidationResult, FundingValidator
from agent.lib.schema.document_state import (
    ArchitectureService,
    DocumentState,
    FieldValue,
    ServiceCategory,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _empty_doc() -> DocumentState:
    """Return a bare DocumentState with no services, no costs, no business case."""
    return DocumentState(document_id="test-funding-v2")


def _valid_doc() -> DocumentState:
    """Return a DocumentState that passes all funding validation checks."""
    doc = DocumentState(document_id="test-funding-v2-valid")

    # Architecture: include Bedrock
    doc.sections.architecture.services = [
        ArchitectureService(
            service_name=FieldValue(user_input="Amazon Bedrock"),
            category=ServiceCategory.genai_core,
            is_required_for_funding=True,
        )
    ]

    # Cost breakdown: calculator URL and ARR
    doc.sections.cost_breakdown.calculator_url = FieldValue(user_input="https://calculator.aws/#/estimate?id=abc")
    doc.sections.cost_breakdown.arr = FieldValue(user_input=120000)
    doc.sections.cost_breakdown.funding_calculation = {
        "yr1_arr": 500000,
        "sow_cost": 100000,
    }

    # Resources cost estimates: total_cost for SOW
    doc.sections.resources_cost_estimates.total_cost.total = "80000"

    # Business case
    bc = doc.sections.executive_summary.business_case
    bc.problem_definition = FieldValue(user_input="Manual support is expensive")
    bc.roi_calculation = FieldValue(user_input="Reduce support cost by 20%")
    bc.executive_sponsor = FieldValue(user_input="CTO")
    bc.production_commitment = FieldValue(user_input="Production launch planned")

    return doc


# ---------------------------------------------------------------------------
# 1. Missing Bedrock → blocking issue BEDROCK_MISSING
# ---------------------------------------------------------------------------

def test_missing_bedrock_creates_blocking_issue():
    doc = _empty_doc()
    # No services at all
    result = FundingValidator().validate(doc)

    codes = {issue.code for issue in result.blocking_issues}
    assert "BEDROCK_MISSING" in codes
    assert result.is_eligible is False


def test_bedrock_present_no_blocking_issue():
    doc = _valid_doc()
    result = FundingValidator().validate(doc)

    codes = {issue.code for issue in result.blocking_issues}
    assert "BEDROCK_MISSING" not in codes


# ---------------------------------------------------------------------------
# 2. Missing sponsor → blocking issue or warning
# ---------------------------------------------------------------------------

def test_missing_sponsor_creates_warning():
    doc = _valid_doc()
    doc.sections.executive_summary.business_case.executive_sponsor = FieldValue()

    result = FundingValidator().validate(doc)

    warning_codes = {w.code for w in result.warnings}
    blocking_codes = {b.code for b in result.blocking_issues}
    # Must appear as either a warning or blocking issue
    assert (
        "BUSINESS_CASE_EXECUTIVE_SPONSOR_MISSING" in warning_codes
        or "BUSINESS_CASE_EXECUTIVE_SPONSOR_MISSING" in blocking_codes
    )


# ---------------------------------------------------------------------------
# 3. Eligible amount formula: min(yr1_arr * 0.25, sow_cost, 125000)
# ---------------------------------------------------------------------------

def test_eligible_amount_25pct_arr_is_smallest():
    """yr1_arr * 0.25 = 25000 < sow_cost=80000 < cap=125000 → 25000."""
    doc = _valid_doc()
    doc.sections.cost_breakdown.funding_calculation = {
        "yr1_arr": 100000,
        "sow_cost": 80000,
    }

    calc = FundingValidator().calculate_funding(doc)

    assert calc["funding_25pct_arr"] == 25000.0
    assert calc["eligible_amount"] == 25000.0


def test_eligible_amount_sow_cost_is_smallest():
    """sow_cost=50000 < yr1_arr*0.25=250000 < cap=125000 → 50000."""
    doc = _valid_doc()
    doc.sections.cost_breakdown.funding_calculation = {
        "yr1_arr": 1000000,
        "sow_cost": 50000,
    }

    calc = FundingValidator().calculate_funding(doc)

    assert calc["funding_25pct_arr"] == 250000.0
    assert calc["eligible_amount"] == 50000.0


def test_eligible_amount_cap_is_smallest():
    """cap=125000 < yr1_arr*0.25=250000 and sow_cost=300000 → 125000."""
    doc = _valid_doc()
    doc.sections.cost_breakdown.funding_calculation = {
        "yr1_arr": 1000000,
        "sow_cost": 300000,
    }

    calc = FundingValidator().calculate_funding(doc)

    assert calc["funding_25pct_arr"] == 250000.0
    assert calc["eligible_amount"] == 125000.0


# ---------------------------------------------------------------------------
# 4. Eligible amount is 0.0 when yr1_arr or sow_cost is zero
# ---------------------------------------------------------------------------

def test_eligible_amount_zero_when_yr1_arr_is_zero():
    doc = _valid_doc()
    doc.sections.cost_breakdown.funding_calculation = {
        "yr1_arr": 0,
        "sow_cost": 100000,
    }
    # Also zero out the ARR FieldValue so _aws_annual_cost returns 0
    doc.sections.cost_breakdown.arr = FieldValue()

    calc = FundingValidator().calculate_funding(doc)

    assert calc["eligible_amount"] == 0.0


def test_eligible_amount_zero_when_sow_cost_is_zero():
    doc = _valid_doc()
    doc.sections.cost_breakdown.funding_calculation = {
        "yr1_arr": 500000,
        "sow_cost": 0,
    }
    # Also zero out the resources total so _sow_cost fallback returns 0
    doc.sections.resources_cost_estimates.total_cost.total = ""
    doc.sections.cost_breakdown.arr = FieldValue()

    calc = FundingValidator().calculate_funding(doc)

    assert calc["eligible_amount"] == 0.0


# ---------------------------------------------------------------------------
# 5. Low/missing ARR creates warnings (via funding validation flow)
# ---------------------------------------------------------------------------

def test_low_arr_missing_business_case_creates_warnings():
    """When business case fields are missing, warnings are generated."""
    doc = _empty_doc()
    # Add Bedrock so it doesn't block
    doc.sections.architecture.services = [
        ArchitectureService(
            service_name=FieldValue(user_input="Amazon Bedrock"),
            category=ServiceCategory.genai_core,
        )
    ]
    # Set calculator URL and SOW cost so those don't block either
    doc.sections.cost_breakdown.calculator_url = FieldValue(user_input="https://calc")
    doc.sections.resources_cost_estimates.total_cost.total = "50000"
    doc.sections.cost_breakdown.arr = FieldValue(user_input=1000)

    result = FundingValidator().validate(doc)

    warning_codes = {w.code for w in result.warnings}
    # Business case fields are missing → warnings
    assert "BUSINESS_CASE_PROBLEM_DEFINITION_MISSING" in warning_codes
    assert "BUSINESS_CASE_ROI_CALCULATION_MISSING" in warning_codes
    assert "BUSINESS_CASE_EXECUTIVE_SPONSOR_MISSING" in warning_codes
    assert "BUSINESS_CASE_PRODUCTION_COMMITMENT_MISSING" in warning_codes


# ---------------------------------------------------------------------------
# 6. FundingValidationResult is JSON-serializable
# ---------------------------------------------------------------------------

def test_funding_validation_result_json_serializable():
    doc = _valid_doc()
    result = FundingValidator().validate(doc)

    # Convert to dict
    result_dict = {
        "is_eligible": result.is_eligible,
        "blocking_issues": [
            {"code": b.code, "message": b.message, "section": b.section}
            for b in result.blocking_issues
        ],
        "warnings": [
            {"code": w.code, "message": w.message, "section": w.section}
            for w in result.warnings
        ],
        "checklist": result.checklist,
    }

    # Must not raise
    serialized = json.dumps(result_dict, ensure_ascii=False)
    assert isinstance(serialized, str)

    # Round-trip
    deserialized = json.loads(serialized)
    assert deserialized["is_eligible"] == result.is_eligible
    assert isinstance(deserialized["checklist"], dict)


def test_funding_validation_result_with_issues_json_serializable():
    doc = _empty_doc()
    result = FundingValidator().validate(doc)

    # Has blocking issues
    assert len(result.blocking_issues) > 0

    result_dict = {
        "is_eligible": result.is_eligible,
        "blocking_issues": [
            {"code": b.code, "message": b.message, "section": b.section}
            for b in result.blocking_issues
        ],
        "warnings": [
            {"code": w.code, "message": w.message, "section": w.section}
            for w in result.warnings
        ],
        "checklist": result.checklist,
    }

    serialized = json.dumps(result_dict, ensure_ascii=False)
    assert isinstance(serialized, str)


# ---------------------------------------------------------------------------
# 7. has_calculator_url reads from cost_breakdown.calculator_url
# ---------------------------------------------------------------------------

def test_has_calculator_url_reads_from_cost_breakdown():
    doc = _empty_doc()
    assert FundingValidator().has_calculator_url(doc) is False

    doc.sections.cost_breakdown.calculator_url = FieldValue(user_input="https://calc")
    assert FundingValidator().has_calculator_url(doc) is True


def test_has_calculator_url_ai_recommended():
    doc = _empty_doc()
    doc.sections.cost_breakdown.calculator_url = FieldValue(ai_recommended="https://calc-ai")
    assert FundingValidator().has_calculator_url(doc) is True


# ---------------------------------------------------------------------------
# 8. _sow_cost reads from resources_cost_estimates.total_cost
# ---------------------------------------------------------------------------

def test_sow_cost_reads_from_resources_total_cost():
    doc = _empty_doc()
    doc.sections.resources_cost_estimates.total_cost.total = "50000"

    validator = FundingValidator()
    sow = validator._sow_cost(doc)

    # _sow_cost = staffing_total + _aws_annual_cost
    # staffing_total = 50000, _aws_annual_cost = 0 (no arr set)
    assert sow == 50000.0


def test_sow_cost_includes_aws_annual_cost():
    doc = _empty_doc()
    doc.sections.resources_cost_estimates.total_cost.total = "30000"
    doc.sections.cost_breakdown.arr = FieldValue(user_input=20000)

    validator = FundingValidator()
    sow = validator._sow_cost(doc)

    # staffing_total=30000 + aws_annual_cost=20000 = 50000
    assert sow == 50000.0


def test_sow_cost_prefers_funding_calculation_sow_cost():
    doc = _empty_doc()
    doc.sections.cost_breakdown.funding_calculation = {"sow_cost": 75000}
    doc.sections.resources_cost_estimates.total_cost.total = "50000"

    validator = FundingValidator()
    sow = validator._sow_cost(doc)

    # funding_calculation.sow_cost takes precedence
    assert sow == 75000.0


# ---------------------------------------------------------------------------
# 9. _business_case_has reads from executive_summary.business_case (nested)
# ---------------------------------------------------------------------------

def test_business_case_has_problem_definition():
    doc = _empty_doc()
    assert FundingValidator()._business_case_has(doc, "problem_definition") is False

    doc.sections.executive_summary.business_case.problem_definition = FieldValue(
        ai_recommended="Problem statement here"
    )
    assert FundingValidator()._business_case_has(doc, "problem_definition") is True


def test_business_case_has_roi_calculation():
    doc = _empty_doc()
    assert FundingValidator()._business_case_has(doc, "roi_calculation") is False

    doc.sections.executive_summary.business_case.roi_calculation = FieldValue(
        user_input="20% cost reduction"
    )
    assert FundingValidator()._business_case_has(doc, "roi_calculation") is True


def test_business_case_has_executive_sponsor():
    doc = _empty_doc()
    assert FundingValidator()._business_case_has(doc, "executive_sponsor") is False

    doc.sections.executive_summary.business_case.executive_sponsor = FieldValue(
        user_input="VP Engineering"
    )
    assert FundingValidator()._business_case_has(doc, "executive_sponsor") is True


def test_business_case_has_production_commitment():
    doc = _empty_doc()
    assert FundingValidator()._business_case_has(doc, "production_commitment") is False

    doc.sections.executive_summary.business_case.production_commitment = FieldValue(
        user_input="Q3 2026 launch"
    )
    assert FundingValidator()._business_case_has(doc, "production_commitment") is True
