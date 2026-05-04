"""Document_State v2 JSON canonical state schema.

Defines the Pydantic v2 models for the APN PoC Project Plan document state
stored in DynamoDB (table: doc-agent-documents, PK: document_id).

Aligned with apn-poc-template_v2.docx placeholders.

Each editable field follows the simplified 4-property pattern:
  user_input / ai_recommended / calculated / status (empty|draft|confirmed)

Breaking change from v1:
- FieldValue: removed reason, source_patterns, confidence
- FieldStatus: reduced to empty|draft|confirmed
- CalculatedOnly: removed (use FieldValue everywhere)
- Top-level staffing_plan: removed (merged into resources_cost_estimates)
- client_signatures section: removed (merged into resources_cost_estimates)
- Legacy section fields removed: executive_summary.text/summary,
  architecture.description/tools, acceptance.text
- CategoryGroup uses bullets (not items)
- Section models use extra="forbid" except CoverSection (extra="allow")
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
    """Status lifecycle for the 4-property pattern (v2: simplified)."""
    empty = "empty"
    draft = "draft"
    confirmed = "confirmed"


class ServiceCategory(str, Enum):
    """AWS service grouping for APN PoC architecture and funding review."""
    genai_core = "genai_core"
    data = "data"
    compute = "compute"
    network = "network"
    security = "security"
    monitoring = "monitoring"


# ---------------------------------------------------------------------------
# 4-property pattern base type (v2: simplified)
# ---------------------------------------------------------------------------

class FieldValue(BaseModel):
    """Simplified 4-property field. No metadata (reason/source_patterns/confidence)."""
    user_input: Any = None
    ai_recommended: Any = None
    calculated: Any = None
    status: FieldStatus = FieldStatus.empty
    user_edited: bool = False

    def resolve(self) -> Any:
        """Return first non-empty value: user_input > ai_recommended > calculated > ''."""
        for v in (self.user_input, self.ai_recommended, self.calculated):
            if v is not None and v != "":
                return v
        return ""


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------

class DocumentMeta(BaseModel):
    """Top-level meta: customer, partner, date."""
    customer: FieldValue = Field(default_factory=FieldValue)
    partner: FieldValue = Field(default_factory=FieldValue)
    date: FieldValue = Field(default_factory=FieldValue)


# ---------------------------------------------------------------------------
# Sub-models for DOCX export
# ---------------------------------------------------------------------------

class ContactEntry(BaseModel):
    """Stakeholders table row. Template uses description/stakeholder_for/role
    depending on the stakeholder list type."""
    name: FieldValue = Field(default_factory=FieldValue)
    title: FieldValue = Field(default_factory=FieldValue)
    description: FieldValue = Field(default_factory=FieldValue)
    stakeholder_for: FieldValue = Field(default_factory=FieldValue)
    role: FieldValue = Field(default_factory=FieldValue)
    contact: FieldValue = Field(default_factory=FieldValue)


class Phase(BaseModel):
    """Milestones table row."""
    phase: FieldValue = Field(default_factory=FieldValue)
    completion_date: FieldValue = Field(default_factory=FieldValue)
    deliverables: FieldValue = Field(default_factory=FieldValue)


class BusinessCase(BaseModel):
    """Executive business case for GenAIIC PLD/funding review.
    Nested under ExecutiveSummarySection. Export context flattens to
    business_case_problem, business_case_roi, etc."""
    problem_definition: FieldValue = Field(default_factory=FieldValue)
    roi_calculation: FieldValue = Field(default_factory=FieldValue)
    executive_sponsor: FieldValue = Field(default_factory=FieldValue)
    production_commitment: FieldValue = Field(default_factory=FieldValue)


class CategoryGroup(BaseModel):
    """Grouped success criteria / assumptions. Template iterates group.bullets."""
    category_name: FieldValue = Field(default_factory=FieldValue)
    bullets: list[FieldValue] = Field(default_factory=list)


class ScopeTask(BaseModel):
    """Scope of work task row. All fields remain FieldValue for agent patching."""
    task_category: FieldValue = Field(default_factory=FieldValue)
    schedule: FieldValue = Field(default_factory=FieldValue)
    details: FieldValue = Field(default_factory=FieldValue)
    personnel: FieldValue = Field(default_factory=FieldValue)


class ArchitectureService(BaseModel):
    """AWS service entry with ordering, category, and funding relevance."""
    service_name: FieldValue = Field(default_factory=FieldValue)
    priority: int = 99
    category: ServiceCategory = ServiceCategory.compute
    description: FieldValue = Field(default_factory=FieldValue)
    sizing_rationale: FieldValue = Field(default_factory=FieldValue)
    is_required_for_funding: bool = False


class AcceptanceStep(BaseModel):
    """Single acceptance criteria step with heading, content, and bullets."""
    heading: FieldValue = Field(default_factory=FieldValue)
    content: FieldValue = Field(default_factory=FieldValue)
    bullets: list[FieldValue] = Field(default_factory=list)


class CostBreakdownRow(BaseModel):
    """Single AWS cost breakdown table row."""
    category: FieldValue = Field(default_factory=FieldValue)
    mrr: FieldValue = Field(default_factory=FieldValue)
    arr: FieldValue = Field(default_factory=FieldValue)
    note: FieldValue = Field(default_factory=FieldValue)


class ContributionEntry(BaseModel):
    """Cost contribution table row for a single party."""
    amount: FieldValue = Field(default_factory=FieldValue)
    pct: FieldValue = Field(default_factory=FieldValue)


class Contribution(BaseModel):
    """Customer/Partner/AWS cost contribution."""
    customer: ContributionEntry = Field(default_factory=ContributionEntry)
    partner: ContributionEntry = Field(default_factory=ContributionEntry)
    aws: ContributionEntry = Field(default_factory=ContributionEntry)


class TeamMember(BaseModel):
    """Partner technical team member. Template loops member.role, member.name."""
    role: FieldValue = Field(default_factory=FieldValue)
    name: FieldValue = Field(default_factory=FieldValue)


class PhaseHours(BaseModel):
    """Phase hours table row with SA/Eng/Other breakdown."""
    phase: FieldValue = Field(default_factory=FieldValue)
    sa_hours: int = 0
    eng_hours: int = 0
    other_hours: int = 0
    total: int = 0


class TotalsRow(BaseModel):
    """Totals row for hours or cost. Template accesses .sa, .eng, .other, .total."""
    sa: str = ""
    eng: str = ""
    other: str = ""
    total: str = ""


# ---------------------------------------------------------------------------
# Section models
# All use extra="forbid" except CoverSection (extra="allow" for dynamic metadata)
# ---------------------------------------------------------------------------

class CoverSection(BaseModel):
    """Cover page section. extra="allow" because agents write dynamic metadata."""
    model_config = {"extra": "allow"}


class ExecutiveSummarySection(BaseModel):
    """Executive summary section (v2)."""
    model_config = {"extra": "forbid"}

    customer_intro: FieldValue = Field(default_factory=FieldValue)
    problem_statement: FieldValue = Field(default_factory=FieldValue)
    proposed_solution: FieldValue = Field(default_factory=FieldValue)
    phases_overview: list[FieldValue] = Field(default_factory=list)
    current_pain_points: list[FieldValue] = Field(default_factory=list)
    poc_objectives: list[FieldValue] = Field(default_factory=list)
    business_case: BusinessCase = Field(default_factory=BusinessCase)
    custom_blocks: list[dict] = Field(default_factory=list)


class StakeholdersSection(BaseModel):
    """Sponsor / Stakeholder / Team contact & org info."""
    model_config = {"extra": "forbid"}

    executive_sponsors: list[ContactEntry] = Field(default_factory=list)
    stakeholders: list[ContactEntry] = Field(default_factory=list)
    project_team: list[ContactEntry] = Field(default_factory=list)
    escalation_contacts: list[ContactEntry] = Field(default_factory=list)


class SuccessCriteriaSection(BaseModel):
    """Success criteria / KPIs section."""
    model_config = {"extra": "forbid"}

    groups: list[CategoryGroup] = Field(default_factory=list)
    items: list[FieldValue] = Field(default_factory=list)


class AssumptionsSection(BaseModel):
    """Assumptions & risks section."""
    model_config = {"extra": "forbid"}

    groups: list[CategoryGroup] = Field(default_factory=list)
    items: list[FieldValue] = Field(default_factory=list)


class ScopeOfWorkSection(BaseModel):
    """Scope of work section."""
    model_config = {"extra": "forbid"}

    tasks: list[ScopeTask] = Field(default_factory=list)
    out_of_scope: list[FieldValue] = Field(default_factory=list)
    items: list[FieldValue] = Field(default_factory=list)


class ArchitectureSection(BaseModel):
    """Architecture section — overview, diagram, services, tools."""
    model_config = {"extra": "forbid"}

    overview: FieldValue = Field(default_factory=FieldValue)
    diagram_image_s3_key: FieldValue = Field(default_factory=FieldValue)
    services: list[ArchitectureService] = Field(default_factory=list)
    tools_list: list[FieldValue] = Field(default_factory=list)


class MilestonesSection(BaseModel):
    """Milestones & deliverables section."""
    model_config = {"extra": "forbid"}

    phases: list[Phase] = Field(default_factory=list)


class CostBreakdownSection(BaseModel):
    """Cost breakdown section (v2: flat, clean schema names).
    Export context maps: calculator_url→aws_calculator_url, mrr→aws_mrr,
    arr→aws_arr, breakdown_table→aws_cost_breakdown_table,
    bedrock_extra→aws_bedrock_extra."""
    model_config = {"extra": "forbid"}

    calculator_url: FieldValue = Field(default_factory=FieldValue)
    mrr: FieldValue = Field(default_factory=FieldValue)
    arr: FieldValue = Field(default_factory=FieldValue)
    breakdown_table: list[CostBreakdownRow] = Field(default_factory=list)
    bedrock_extra: FieldValue = Field(default_factory=FieldValue)
    funding_calculation: dict = Field(default_factory=dict)


class AcceptanceSection(BaseModel):
    """Acceptance criteria section (v2: structured steps).
    Export context key: acceptance_steps (mapped from steps)."""
    model_config = {"extra": "forbid"}

    steps: list[AcceptanceStep] = Field(default_factory=list)


class ResourcesCostEstimatesSection(BaseModel):
    """Resources & cost estimates (v2: includes staffing + signatures).
    Replaces top-level staffing_plan and client_signatures section."""
    model_config = {"extra": "forbid"}

    partner_technical_team: list[TeamMember] = Field(default_factory=list)
    rate_solution_architect: FieldValue = Field(default_factory=FieldValue)
    rate_engineer: FieldValue = Field(default_factory=FieldValue)
    rate_other: FieldValue = Field(default_factory=FieldValue)
    phase_hours_table: list[PhaseHours] = Field(default_factory=list)
    total_hours: TotalsRow = Field(default_factory=TotalsRow)
    total_cost: TotalsRow = Field(default_factory=TotalsRow)
    contribution: Contribution = Field(default_factory=Contribution)
    client_signature_customer_name: FieldValue = Field(default_factory=FieldValue)
    client_signature_person_name: FieldValue = Field(default_factory=FieldValue)
    client_signature_designation: FieldValue = Field(default_factory=FieldValue)
    client_signature_date: FieldValue = Field(default_factory=FieldValue)


# ---------------------------------------------------------------------------
# Sections container
# ---------------------------------------------------------------------------

class Sections(BaseModel):
    """All APN template v2 sections keyed in snake_case."""
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
# Document_State v2 — root model
# ---------------------------------------------------------------------------

class DocumentState(BaseModel):
    """JSON canonical state for an APN PoC Project Plan document (v2).

    Stored in DynamoDB table `doc-agent-documents` with PK `document_id`.
    No top-level staffing_plan — staffing data is in resources_cost_estimates.
    """

    document_id: str = ""
    user_id: str = ""
    title: str = ""
    template: str = "apn_poc_project_plan"
    mode: DocumentMode = DocumentMode.architecture_absent
    version: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    meta: DocumentMeta = Field(default_factory=DocumentMeta)
    sections: Sections = Field(default_factory=Sections)

    completion_score: float = 0.0
    blocking_issues: list[BlockingIssue] = Field(default_factory=list)
    warnings: list[Warning] = Field(default_factory=list)

    # Agent execution status (per-document, persisted in DynamoDB)
    agent_status: str = "idle"       # idle / processing / error / degraded
    agent_active: str = ""           # currently running agent name
    agent_message: str = ""          # status message for UI

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
    """Conversation history for a document/session."""
    document_id: str = ""
    session_id: str = ""
    messages: list[ConversationMessage] = Field(default_factory=list)
    bounded_window: int = 20
    total_count: int = 0
