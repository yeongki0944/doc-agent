"""Apply review results to Document_State."""

from agent.lib.schema.document_state import DocumentState
from agent.app.reviewer.reviewer_agent import ReviewerAgent, ReviewResult


def apply_review(doc: DocumentState) -> tuple[DocumentState, ReviewResult]:
    """Run review and update doc's completion_score, blocking_issues, warnings."""
    reviewer = ReviewerAgent()
    result = reviewer.review(doc)

    doc.completion_score = result.completion_score
    doc.blocking_issues = result.blocking_issues
    doc.warnings = result.warnings

    return doc, result
