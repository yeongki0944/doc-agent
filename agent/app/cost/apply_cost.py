"""Apply cost calculation results to Document_State."""

from __future__ import annotations

from agent.lib.schema.document_state import DocumentState
from agent.app.cost.cost_agent import (
    AWSCostResult,
    DocumentLocalSummary,
    FallbackCard,
)


def apply_aws_cost_to_state(
    doc: DocumentState,
    aws_result: AWSCostResult,
    fallback: FallbackCard | None = None,
) -> DocumentState:
    """Store AWS cost results in Document_State's cost_breakdown section."""
    # Using extra fields on the section (model_config allows extra)
    section = doc.sections.cost_breakdown

    section.monthly_cost_summary = aws_result.monthly_cost_summary  # type: ignore
    section.service_breakdown = aws_result.service_breakdown  # type: ignore
    section.calculator_share_url = aws_result.calculator_share_url  # type: ignore
    section.manual_estimate_items = aws_result.manual_estimate_items  # type: ignore

    if fallback:
        section.fallback_card = {  # type: ignore
            "services": fallback.services,
            "total_estimate": fallback.total_estimate,
            "reason": fallback.reason,
        }

    return doc


def apply_document_local_summary(
    doc: DocumentState,
    summary: DocumentLocalSummary,
) -> DocumentState:
    """Store document-local cost summary in Document_State.

    Always preserved so the estimate remains readable even when the
    external calculator share URL expires (Req 8.8).
    """
    section = doc.sections.cost_breakdown
    section.document_local_summary = {  # type: ignore
        "total_staffing_cost": summary.total_staffing_cost,
        "total_aws_monthly_cost": summary.total_aws_monthly_cost,
        "total_project_cost": summary.total_project_cost,
        "generated_at": summary.generated_at,
    }
    return doc
