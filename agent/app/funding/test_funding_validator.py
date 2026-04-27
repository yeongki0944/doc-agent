from datetime import date
from types import SimpleNamespace

from agent.app.funding import FundingValidator
from agent.lib.schema.document_state import (
    ArchitectureService,
    CalculatedOnly,
    CostBreakdownSection,
    DocumentState,
    FieldValue,
    FundingCalculation,
    ServiceCategory,
    StaffingPlan,
)


def _valid_doc() -> DocumentState:
    doc = DocumentState(document_id="funding-valid")
    doc.sections.architecture.services = [
        ArchitectureService(
            service_name=FieldValue(user_input="Amazon Bedrock"),
            category=ServiceCategory.genai_core,
            is_required_for_funding=True,
        )
    ]
    doc.sections.cost_breakdown.aws_service_cost.calculator_share_url = "https://calculator.aws/#/estimate?id=abc"
    doc.staffing_plan = StaffingPlan(
        grand_total_cost=CalculatedOnly(calculated=100000),
    )
    doc.sections.cost_breakdown.funding_calculation = FundingCalculation(
        yr1_arr=FieldValue(user_input=1000000),
        sow_cost=FieldValue(user_input=100000),
    )
    business_case = doc.sections.executive_summary.business_case
    business_case.problem_definition = FieldValue(user_input="Manual support is expensive")
    business_case.roi_calculation = FieldValue(user_input="Reduce support cost by 20%")
    business_case.executive_sponsor = FieldValue(user_input="CTO")
    business_case.production_commitment = FieldValue(user_input="Production launch planned")
    return doc


def test_bedrock_missing_produces_blocking_issue():
    doc = _valid_doc()
    doc.sections.architecture.services = []

    result = FundingValidator().validate(doc)

    assert "BEDROCK_MISSING" in {issue.code for issue in result.blocking_issues}
    assert result.is_eligible is False


def test_calculator_url_missing_produces_blocking_issue():
    doc = _valid_doc()
    doc.sections.cost_breakdown.aws_service_cost.calculator_share_url = None

    result = FundingValidator().validate(doc)

    assert "CALCULATOR_URL_MISSING" in {issue.code for issue in result.blocking_issues}
    assert result.is_eligible is False


def test_sow_cost_missing_produces_blocking_issue():
    doc = _valid_doc()
    doc.staffing_plan.grand_total_cost = CalculatedOnly(calculated=None)
    doc.sections.cost_breakdown.funding_calculation.sow_cost = FieldValue()

    result = FundingValidator().validate(doc)

    assert "SOW_COST_MISSING" in {issue.code for issue in result.blocking_issues}
    assert result.is_eligible is False


def test_valid_document_is_eligible():
    result = FundingValidator(today=date(2026, 4, 27)).validate(_valid_doc())

    assert result.is_eligible is True
    assert result.blocking_issues == []
    assert result.checklist["bedrock_included"] is True
    assert result.checklist["calculator_url_present"] is True
    assert result.checklist["sow_cost_present"] is True


def test_bedrock_detection_checks_service_id():
    doc = _valid_doc()
    doc.sections.architecture.services = [
        SimpleNamespace(service_name=FieldValue(), service_id="amazon-bedrock")
    ]

    assert FundingValidator().has_bedrock(doc) is True


def test_poc_start_date_less_than_14_days_warns():
    doc = _valid_doc()
    doc.meta.date = FieldValue(user_input="2026-05-05")

    result = FundingValidator(today=date(2026, 4, 27)).validate(doc)

    assert "POC_START_DATE_TOO_SOON" in {warning.code for warning in result.warnings}


def test_funding_amount_arr_25pct_is_smallest():
    doc = _valid_doc()
    doc.sections.cost_breakdown.funding_calculation = FundingCalculation(
        yr1_arr=FieldValue(user_input=100000),
        sow_cost=FieldValue(user_input=80000),
    )

    calc = FundingValidator().calculate_funding(doc)

    assert calc["funding_25pct_arr"] == 25000
    assert calc["eligible_amount"] == 25000


def test_funding_amount_sow_cost_is_smallest():
    doc = _valid_doc()
    doc.sections.cost_breakdown.funding_calculation = FundingCalculation(
        yr1_arr=FieldValue(user_input=1000000),
        sow_cost=FieldValue(user_input=50000),
    )

    calc = FundingValidator().calculate_funding(doc)

    assert calc["funding_25pct_arr"] == 250000
    assert calc["eligible_amount"] == 50000


def test_funding_amount_cap_is_smallest():
    doc = _valid_doc()
    doc.sections.cost_breakdown.funding_calculation = FundingCalculation(
        yr1_arr=FieldValue(user_input=1000000),
        sow_cost=FieldValue(user_input=300000),
    )

    calc = FundingValidator().calculate_funding(doc)

    assert calc["funding_25pct_arr"] == 250000
    assert calc["eligible_amount"] == 125000


def test_funding_uses_staffing_and_annual_aws_cost_when_sow_missing():
    doc = _valid_doc()
    doc.sections.cost_breakdown = CostBreakdownSection(
        funding_calculation=FundingCalculation(
            yr1_arr=FieldValue(user_input=500000),
        )
    )
    doc.staffing_plan.grand_total_cost = CalculatedOnly(calculated=10000)
    doc.sections.cost_breakdown.aws_service_cost.monthly_cost_summary = CalculatedOnly(calculated=1000)

    calc = FundingValidator().calculate_funding(doc)

    assert calc["sow_cost"] == 22000
