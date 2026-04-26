"""Document_State JSON canonical state schema.

Defines the Pydantic v2 models for the APN PoC Project Plan document state
stored in DynamoDB (table: doc-agent-documents, PK: document_id).

Each editable field follows the 4-property pattern:
  user_input / ai_recommended / calculated / status
with field-level metadata: user_edited, reason, source_patterns, confidence.

Read-only derived fields use the CalculatedOnly abbreviated form.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_serializer


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class DocumentMode(str, Enum):
    """Entry mode: existing architecture vs. new design assistance."""
    architecture_present = "architecture_present"
    architecture_absent = "architecture_absent"


class FieldStatus(str, Enum):
    """Status lifecycle for the 4-property pattern."""
    empty = "empty"
    recommended = "recommended"
    user_modified = "user_modified"
    confirmed = "confirmed"
    calculated = "calculated"


# ---------------------------------------------------------------------------
# 4-property pattern base types
# ---------------------------------------------------------------------------

class FieldValue(BaseModel):
    """Full 4-property field with metadata."""
    user_input: Any = None
    ai_recommended: Any = None
    calculated: Any = None
    status: FieldStatus = FieldStatus.empty
    # field-level metadata
    user_edited: bool = False
    reason: Optional[str] = None
    source_patterns: list[str] = Field(default_factory=list)
    confidence: Optional[float] = None


class CalculatedOnly(BaseModel):
    """Abbreviated form for read-only derived fields (e.g. totals)."""
    calculated: Any = None


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------

class DocumentMeta(BaseModel):
    """Top-level meta: customer, partner, date."""
    customer: FieldValue = Field(default_factory=FieldValue)
    partner: FieldValue = Field(default_factory=FieldValue)
    date: FieldValue = Field(default_factory=FieldValue)


# ---------------------------------------------------------------------------
# Section models — each section is a generic container for now.
# Specific section schemas can be refined per-section as needed.
# ---------------------------------------------------------------------------

class Section(BaseModel):
    """Generic section container. Sections hold arbitrary field values."""
    model_config = {"extra": "allow"}


class CoverSection(Section):
    """Cover page section."""
    pass


class ExecutiveSummarySection(Section):
    """Executive summary section."""
    pass


class StakeholdersSection(Section):
    """Sponsor / Stakeholder / Team contact & org info."""
    pass


class SuccessCriteriaSection(Section):
    """Success criteria / KPIs section."""
    pass


class AssumptionsSection(Section):
    """Assumptions & risks section."""
    pass


class ScopeOfWorkSection(Section):
    """Scope of work section."""
    pass


class ArchitectureSection(Section):
    """Architecture section — diagrams, service list, analysis."""
    pass


class MilestonesSection(Section):
    """Milestones & deliverables section."""
    pass


class RoleCostSummary(BaseModel):
    """Single role cost summary within staffing cost breakdown."""
    role_id: str = ""
    display_name: str = ""
    total_hours: float = 0.0
    rate_per_hour: float = 0.0
    total_cost: float = 0.0


class StaffingCost(BaseModel):
    """Staffing cost breakdown — role summaries + grand total."""
    roles_summary: list[RoleCostSummary] = Field(default_factory=list)
    grand_total: CalculatedOnly = Field(default_factory=CalculatedOnly)


class ServiceBreakdownItem(BaseModel):
    """Single AWS service cost entry."""
    service_name: str = ""
    service_code: str = ""
    monthly_cost: float = 0.0
    supported_by_calculator: bool = True


class AWSServiceCost(BaseModel):
    """AWS service cost breakdown — monthly summary + per-service detail."""
    monthly_cost_summary: CalculatedOnly = Field(default_factory=CalculatedOnly)
    service_breakdown: list[ServiceBreakdownItem] = Field(default_factory=list)
    calculator_share_url: Optional[str] = None
    fallback_card: Optional[dict[str, Any]] = None
    manual_estimate_items: list[dict[str, Any]] = Field(default_factory=list)


class DocumentLocalSummary(BaseModel):
    """Document-local cost summary preserved even when external URLs expire."""
    total_staffing_cost: float = 0.0
    total_aws_monthly_cost: float = 0.0
    total_project_cost: float = 0.0
    generated_at: Optional[datetime] = None

    @field_serializer("generated_at")
    def _serialize_generated_at(self, v: datetime | None, _info: Any) -> str | None:
        if v is None:
            return None
        return v.isoformat()


class CostBreakdownSection(Section):
    """Cost breakdown section — staffing cost + AWS service cost + local summary."""
    staffing_cost: StaffingCost = Field(default_factory=StaffingCost)
    aws_service_cost: AWSServiceCost = Field(default_factory=AWSServiceCost)
    document_local_summary: DocumentLocalSummary = Field(default_factory=DocumentLocalSummary)


class AcceptanceSection(Section):
    """Acceptance criteria section."""
    pass


class ResourcesCostEstimatesSection(Section):
    """Resources & cost estimates — sub-section of Cost tab."""
    pass


# ---------------------------------------------------------------------------
# Sections container
# ---------------------------------------------------------------------------

class Sections(BaseModel):
    """All APN template sections keyed in snake_case."""
    cover: CoverSection = Field(default_factory=CoverSection)
    executive_summary: ExecutiveSummarySection = Field(default_factory=ExecutiveSummarySection)
    stakeholders: StakeholdersSection = Field(default_factory=StakeholdersSection)
    success_criteria: SuccessCriteriaSection = Field(default_factory=SuccessCriteriaSection)
    assumptions: AssumptionsSection = Field(default_factory=AssumptionsSection)
    scope_of_work: ScopeOfWorkSection = Field(default_factory=ScopeOfWorkSection)
    architecture: ArchitectureSection = Field(default_factory=ArchitectureSection)
    milestones: MilestonesSection = Field(default_factory=MilestonesSection)
    cost_breakdown: CostBreakdownSection = Field(default_factory=CostBreakdownSection)
    acceptance: AcceptanceSection = Field(default_factory=AcceptanceSection)
    resources_cost_estimates: ResourcesCostEstimatesSection = Field(
        default_factory=ResourcesCostEstimatesSection
    )


# ---------------------------------------------------------------------------
# Staffing Plan (top-level, outside sections)
# ---------------------------------------------------------------------------

class PhaseHours(BaseModel):
    """Per-phase hour allocations."""
    discovery: FieldValue = Field(default_factory=FieldValue)
    development: FieldValue = Field(default_factory=FieldValue)
    testing: FieldValue = Field(default_factory=FieldValue)


class StaffingRole(BaseModel):
    """Single role entry in the staffing plan."""
    role_id: str
    display_name: str = ""
    count: FieldValue = Field(default_factory=FieldValue)
    allocation_pct: FieldValue = Field(default_factory=FieldValue)
    rate_per_hour: FieldValue = Field(default_factory=FieldValue)
    phase_hours: PhaseHours = Field(default_factory=PhaseHours)
    total_hours: CalculatedOnly = Field(default_factory=CalculatedOnly)
    total_cost: CalculatedOnly = Field(default_factory=CalculatedOnly)
    reason: Optional[str] = None
    source_patterns: list[str] = Field(default_factory=list)
    user_edited: bool = False


class StaffingPlan(BaseModel):
    """Top-level staffing plan with roles and grand totals."""
    roles: dict[str, StaffingRole] = Field(default_factory=dict)
    grand_total_hours: CalculatedOnly = Field(default_factory=CalculatedOnly)
    grand_total_cost: CalculatedOnly = Field(default_factory=CalculatedOnly)


# ---------------------------------------------------------------------------
# Blocking issues & warnings
# ---------------------------------------------------------------------------

class BlockingIssue(BaseModel):
    """A blocking issue that prevents export."""
    code: str = ""
    message: str = ""
    section: Optional[str] = None


class Warning(BaseModel):
    """A non-blocking warning."""
    code: str = ""
    message: str = ""
    section: Optional[str] = None


# ---------------------------------------------------------------------------
# Document_State — root model
# ---------------------------------------------------------------------------

class DocumentState(BaseModel):
    """JSON canonical state for an APN PoC Project Plan document.

    Stored in DynamoDB table `doc-agent-documents` with PK `document_id`.
    """

    document_id: str = ""
    template: str = "apn_poc_project_plan"
    mode: DocumentMode = DocumentMode.architecture_absent
    version: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    meta: DocumentMeta = Field(default_factory=DocumentMeta)
    sections: Sections = Field(default_factory=Sections)
    staffing_plan: StaffingPlan = Field(default_factory=StaffingPlan)

    completion_score: float = 0.0
    blocking_issues: list[BlockingIssue] = Field(default_factory=list)
    warnings: list[Warning] = Field(default_factory=list)

    @field_serializer("created_at", "updated_at")
    def _serialize_timestamps(self, v: datetime, _info: Any) -> str:
        return v.isoformat()


# ---------------------------------------------------------------------------
# Conversation History — Pydantic model for serialization
# ---------------------------------------------------------------------------

class ConversationMessage(BaseModel):
    """Single message in a conversation history."""
    id: str = ""
    role: str = ""  # "user" | "agent"
    content: str = ""
    timestamp: Optional[str] = None
    agent: Optional[str] = None  # e.g. "parent", "discovery_agent"


class ConversationHistory(BaseModel):
    """Conversation history for a document/session.

    The server is the canonical store; the frontend uses localStorage as cache.
    API calls include only the most recent ``bounded_window`` messages.
    """
    document_id: str = ""
    session_id: str = ""
    messages: list[ConversationMessage] = Field(default_factory=list)
    bounded_window: int = 20
    total_count: int = 0
