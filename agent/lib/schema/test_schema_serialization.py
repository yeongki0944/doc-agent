"""Tests for schema serialization/deserialization — tasks 14.1, 14.2, 14.3.

Covers:
- FieldValue 4-property pattern round-trip
- DocumentState full serialization (v2 fields including timestamps, cost breakdown, conversation history)
- Patch model version tracking fields
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from agent.lib.schema.document_state import (
    AWSServiceCost,
    CalculatedOnly,
    ConversationHistory,
    ConversationMessage,
    CostBreakdownSection,
    DocumentLocalSummary,
    DocumentMode,
    DocumentState,
    FieldStatus,
    FieldValue,
    PhaseHours,
    RoleCostSummary,
    Sections,
    ServiceBreakdownItem,
    StaffingCost,
    StaffingPlan,
    StaffingRole,
)
from agent.lib.schema.patch import AgentStatus, Patch, PatchOperation


# ---------------------------------------------------------------------------
# FieldValue 4-property pattern round-trip
# ---------------------------------------------------------------------------

class TestFieldValueRoundTrip:
    """FieldValue serialization preserves all 4 properties + metadata."""

    def test_default_field_value_round_trip(self):
        fv = FieldValue()
        data = fv.model_dump()
        restored = FieldValue.model_validate(data)
        assert restored.user_input is None
        assert restored.ai_recommended is None
        assert restored.calculated is None
        assert restored.status == FieldStatus.empty
        assert restored.user_edited is False
        assert restored.reason is None
        assert restored.source_patterns == []
        assert restored.confidence is None

    def test_full_field_value_round_trip(self):
        fv = FieldValue(
            user_input="ABC Corp",
            ai_recommended="ABC Corporation",
            calculated=None,
            status=FieldStatus.user_modified,
            user_edited=True,
            reason="User corrected company name",
            source_patterns=["preset_genai_multi_agent_v2"],
            confidence=0.85,
        )
        data = fv.model_dump()
        restored = FieldValue.model_validate(data)
        assert restored.user_input == "ABC Corp"
        assert restored.ai_recommended == "ABC Corporation"
        assert restored.status == FieldStatus.user_modified
        assert restored.user_edited is True
        assert restored.reason == "User corrected company name"
        assert restored.source_patterns == ["preset_genai_multi_agent_v2"]
        assert restored.confidence == 0.85

    def test_field_value_json_round_trip(self):
        """Serialize to JSON string and back."""
        fv = FieldValue(
            user_input=50,
            ai_recommended=40,
            status=FieldStatus.recommended,
            reason="Based on project scope",
            source_patterns=["preset_genai_multi_agent_v2", "rate_card_v1"],
            confidence=0.92,
        )
        json_str = fv.model_dump_json()
        restored = FieldValue.model_validate_json(json_str)
        assert restored.user_input == 50
        assert restored.ai_recommended == 40
        assert restored.confidence == 0.92
        assert len(restored.source_patterns) == 2

    def test_field_value_status_transitions(self):
        """All FieldStatus enum values serialize correctly."""
        for status in FieldStatus:
            fv = FieldValue(status=status)
            data = fv.model_dump()
            restored = FieldValue.model_validate(data)
            assert restored.status == status
            assert data["status"] == status.value

    def test_calculated_only_round_trip(self):
        co = CalculatedOnly(calculated=45796.80)
        data = co.model_dump()
        restored = CalculatedOnly.model_validate(data)
        assert restored.calculated == 45796.80


# ---------------------------------------------------------------------------
# CostBreakdownSection detailed schema
# ---------------------------------------------------------------------------

class TestCostBreakdownSection:
    """CostBreakdownSection v2 detailed schema serialization."""

    def test_empty_cost_breakdown_round_trip(self):
        section = CostBreakdownSection()
        data = section.model_dump()
        restored = CostBreakdownSection.model_validate(data)
        assert restored.staffing_cost.roles_summary == []
        assert restored.aws_service_cost.calculator_share_url is None
        assert restored.document_local_summary.total_project_cost == 0.0

    def test_full_cost_breakdown_round_trip(self):
        section = CostBreakdownSection(
            staffing_cost=StaffingCost(
                roles_summary=[
                    RoleCostSummary(
                        role_id="project_manager",
                        display_name="Project Manager",
                        total_hours=140,
                        rate_per_hour=81.78,
                        total_cost=11449.20,
                    ),
                    RoleCostSummary(
                        role_id="backend_dev",
                        display_name="Backend Developer",
                        total_hours=200,
                        rate_per_hour=75.0,
                        total_cost=15000.0,
                    ),
                ],
                grand_total=CalculatedOnly(calculated=26449.20),
            ),
            aws_service_cost=AWSServiceCost(
                monthly_cost_summary=CalculatedOnly(calculated=1113.68),
                service_breakdown=[
                    ServiceBreakdownItem(
                        service_name="AWS Lambda",
                        service_code="aWSLambda",
                        monthly_cost=244.13,
                        supported_by_calculator=True,
                    ),
                ],
                calculator_share_url="https://calculator.aws/#/estimate?id=abc123",
                manual_estimate_items=[],
            ),
            document_local_summary=DocumentLocalSummary(
                total_staffing_cost=26449.20,
                total_aws_monthly_cost=1113.68,
                total_project_cost=27562.88,
                generated_at=datetime(2025, 7, 1, 10, 30, 0, tzinfo=timezone.utc),
            ),
        )
        data = section.model_dump()
        restored = CostBreakdownSection.model_validate(data)

        assert len(restored.staffing_cost.roles_summary) == 2
        assert restored.staffing_cost.roles_summary[0].role_id == "project_manager"
        assert restored.staffing_cost.grand_total.calculated == 26449.20
        assert restored.aws_service_cost.monthly_cost_summary.calculated == 1113.68
        assert len(restored.aws_service_cost.service_breakdown) == 1
        assert restored.aws_service_cost.calculator_share_url == "https://calculator.aws/#/estimate?id=abc123"
        assert restored.document_local_summary.total_project_cost == 27562.88

    def test_cost_breakdown_json_round_trip(self):
        section = CostBreakdownSection(
            staffing_cost=StaffingCost(
                roles_summary=[
                    RoleCostSummary(role_id="pm", total_cost=10000.0),
                ],
                grand_total=CalculatedOnly(calculated=10000.0),
            ),
            document_local_summary=DocumentLocalSummary(
                total_staffing_cost=10000.0,
                generated_at=datetime(2025, 7, 1, tzinfo=timezone.utc),
            ),
        )
        json_str = section.model_dump_json()
        restored = CostBreakdownSection.model_validate_json(json_str)
        assert restored.staffing_cost.grand_total.calculated == 10000.0

    def test_fallback_card_preserved(self):
        section = CostBreakdownSection(
            aws_service_cost=AWSServiceCost(
                fallback_card={"reason": "Calculator MCP unavailable", "services": ["Lambda", "S3"]},
                manual_estimate_items=[{"service": "Custom ML", "note": "Manual estimate needed"}],
            ),
        )
        data = section.model_dump()
        restored = CostBreakdownSection.model_validate(data)
        assert restored.aws_service_cost.fallback_card["reason"] == "Calculator MCP unavailable"
        assert len(restored.aws_service_cost.manual_estimate_items) == 1


# ---------------------------------------------------------------------------
# ConversationHistory model
# ---------------------------------------------------------------------------

class TestConversationHistory:
    """ConversationHistory Pydantic model serialization."""

    def test_empty_conversation_history(self):
        ch = ConversationHistory(document_id="doc-001", session_id="sess-001")
        data = ch.model_dump()
        assert data["document_id"] == "doc-001"
        assert data["session_id"] == "sess-001"
        assert data["messages"] == []
        assert data["bounded_window"] == 20
        assert data["total_count"] == 0

    def test_full_conversation_history_round_trip(self):
        ch = ConversationHistory(
            document_id="doc-001",
            session_id="sess-20250701-001",
            messages=[
                ConversationMessage(
                    id="msg-001",
                    role="user",
                    content="Create a PoC plan for GenAI multi-agent system",
                    timestamp="2025-07-01T09:00:00Z",
                ),
                ConversationMessage(
                    id="msg-002",
                    role="agent",
                    content="I'll help you create that plan. What's the customer name?",
                    timestamp="2025-07-01T09:00:05Z",
                    agent="parent",
                ),
            ],
            bounded_window=20,
            total_count=45,
        )
        json_str = ch.model_dump_json()
        restored = ConversationHistory.model_validate_json(json_str)
        assert restored.document_id == "doc-001"
        assert restored.session_id == "sess-20250701-001"
        assert len(restored.messages) == 2
        assert restored.messages[0].role == "user"
        assert restored.messages[1].agent == "parent"
        assert restored.bounded_window == 20
        assert restored.total_count == 45


# ---------------------------------------------------------------------------
# DocumentState full serialization (v2 fields)
# ---------------------------------------------------------------------------

class TestDocumentStateSerialization:
    """DocumentState full round-trip including v2 timestamp and cost fields."""

    def test_default_document_state_round_trip(self):
        doc = DocumentState(document_id="doc-001")
        data = doc.model_dump()
        restored = DocumentState.model_validate(data)
        assert restored.document_id == "doc-001"
        assert restored.template == "apn_poc_project_plan"
        assert restored.mode == DocumentMode.architecture_absent
        assert restored.version == 0
        assert restored.completion_score == 0.0

    def test_timestamps_serialize_as_iso_strings(self):
        ts = datetime(2025, 7, 1, 9, 0, 0, tzinfo=timezone.utc)
        doc = DocumentState(
            document_id="doc-001",
            created_at=ts,
            updated_at=ts,
        )
        data = doc.model_dump()
        assert isinstance(data["created_at"], str)
        assert isinstance(data["updated_at"], str)
        assert "2025-07-01" in data["created_at"]
        assert "2025-07-01" in data["updated_at"]

    def test_timestamps_deserialize_from_iso_strings(self):
        data = {
            "document_id": "doc-001",
            "created_at": "2025-07-01T09:00:00+00:00",
            "updated_at": "2025-07-01T10:30:00+00:00",
        }
        doc = DocumentState.model_validate(data)
        assert doc.created_at.year == 2025
        assert doc.created_at.month == 7
        assert doc.updated_at.hour == 10

    def test_full_document_state_json_round_trip(self):
        ts = datetime(2025, 7, 1, 9, 0, 0, tzinfo=timezone.utc)
        doc = DocumentState(
            document_id="doc-001",
            template="apn_poc_project_plan",
            mode=DocumentMode.architecture_present,
            version=42,
            created_at=ts,
            updated_at=ts,
            completion_score=0.65,
        )
        # Add a staffing role
        doc.staffing_plan.roles["project_manager"] = StaffingRole(
            role_id="project_manager",
            display_name="Project Manager",
            count=FieldValue(ai_recommended=1, status=FieldStatus.recommended),
            rate_per_hour=FieldValue(ai_recommended=81.78, status=FieldStatus.recommended),
            total_hours=CalculatedOnly(calculated=140),
            total_cost=CalculatedOnly(calculated=11449.20),
            reason="6개 서비스 연동, 4주 일정 관리 필요",
            source_patterns=["preset_genai_multi_agent_v2"],
        )
        doc.staffing_plan.grand_total_hours = CalculatedOnly(calculated=560)
        doc.staffing_plan.grand_total_cost = CalculatedOnly(calculated=45796.80)

        json_str = doc.model_dump_json()
        restored = DocumentState.model_validate_json(json_str)

        assert restored.document_id == "doc-001"
        assert restored.version == 42
        assert restored.mode == DocumentMode.architecture_present
        assert restored.completion_score == 0.65
        pm = restored.staffing_plan.roles["project_manager"]
        assert pm.count.ai_recommended == 1
        assert pm.total_cost.calculated == 11449.20
        assert pm.reason == "6개 서비스 연동, 4주 일정 관리 필요"
        assert restored.staffing_plan.grand_total_cost.calculated == 45796.80

    def test_document_state_with_cost_breakdown(self):
        """Full document with detailed cost_breakdown section."""
        doc = DocumentState(document_id="doc-002", version=10)
        doc.sections.cost_breakdown = CostBreakdownSection(
            staffing_cost=StaffingCost(
                roles_summary=[
                    RoleCostSummary(role_id="pm", display_name="PM", total_hours=100, rate_per_hour=80, total_cost=8000),
                ],
                grand_total=CalculatedOnly(calculated=8000),
            ),
            aws_service_cost=AWSServiceCost(
                monthly_cost_summary=CalculatedOnly(calculated=500),
                service_breakdown=[
                    ServiceBreakdownItem(service_name="Lambda", service_code="aWSLambda", monthly_cost=500),
                ],
            ),
            document_local_summary=DocumentLocalSummary(
                total_staffing_cost=8000,
                total_aws_monthly_cost=500,
                total_project_cost=8500,
                generated_at=datetime(2025, 7, 1, 10, 0, 0, tzinfo=timezone.utc),
            ),
        )
        json_str = doc.model_dump_json()
        restored = DocumentState.model_validate_json(json_str)
        cb = restored.sections.cost_breakdown
        assert cb.staffing_cost.grand_total.calculated == 8000
        assert cb.aws_service_cost.monthly_cost_summary.calculated == 500
        assert cb.document_local_summary.total_project_cost == 8500

    def test_document_state_with_blocking_issues_and_warnings(self):
        from agent.lib.schema.document_state import BlockingIssue, Warning
        doc = DocumentState(
            document_id="doc-003",
            blocking_issues=[BlockingIssue(code="MISSING_SECTION", message="Cover page missing", section="cover")],
            warnings=[Warning(code="LOW_CONFIDENCE", message="Cost estimate confidence low", section="cost_breakdown")],
        )
        data = doc.model_dump()
        restored = DocumentState.model_validate(data)
        assert len(restored.blocking_issues) == 1
        assert restored.blocking_issues[0].code == "MISSING_SECTION"
        assert len(restored.warnings) == 1
        assert restored.warnings[0].section == "cost_breakdown"


# ---------------------------------------------------------------------------
# Patch model version tracking
# ---------------------------------------------------------------------------

class TestPatchSerialization:
    """Patch model serialization including version_before/version_after."""

    def test_patch_default_round_trip(self):
        p = Patch(patch_id="p-001", doc_id="doc-001", agent="staffing_agent")
        data = p.model_dump()
        restored = Patch.model_validate(data)
        assert restored.patch_id == "p-001"
        assert restored.version_before is None
        assert restored.version_after is None

    def test_patch_with_version_tracking(self):
        p = Patch(
            patch_id="p-20250701-001",
            doc_id="doc-001",
            agent="staffing_agent",
            timestamp=datetime(2025, 7, 1, 10, 30, 0, tzinfo=timezone.utc),
            operations=[
                PatchOperation(
                    op="replace",
                    path="/staffing_plan/roles/project_manager/count/ai_recommended",
                    value=1,
                    source="ai_recommended",
                ),
            ],
            version=42,
            version_before=41,
            version_after=42,
        )
        json_str = p.model_dump_json()
        restored = Patch.model_validate_json(json_str)
        assert restored.version_before == 41
        assert restored.version_after == 42
        assert restored.version == 42
        assert len(restored.operations) == 1
        assert restored.operations[0].source == "ai_recommended"

    def test_patch_timestamp_serializes_as_iso(self):
        ts = datetime(2025, 7, 1, 10, 30, 0, tzinfo=timezone.utc)
        p = Patch(patch_id="p-001", timestamp=ts)
        data = p.model_dump()
        assert isinstance(data["timestamp"], str)
        assert "2025-07-01" in data["timestamp"]

    def test_agent_status_enum_values(self):
        """All AgentStatus values are valid strings."""
        assert AgentStatus.processing.value == "processing"
        assert AgentStatus.idle.value == "idle"
        assert AgentStatus.error.value == "error"
        assert AgentStatus.degraded.value == "degraded"

    def test_patch_operation_sources(self):
        """PatchOperation source field accepts expected values."""
        for source in ["user_input", "ai_recommended", "calculated"]:
            op = PatchOperation(op="replace", path="/meta/customer", value="test", source=source)
            data = op.model_dump()
            restored = PatchOperation.model_validate(data)
            assert restored.source == source

    def test_patch_multiple_operations_round_trip(self):
        p = Patch(
            patch_id="p-multi",
            doc_id="doc-001",
            agent="cost_agent",
            operations=[
                PatchOperation(op="replace", path="/sections/cost_breakdown/staffing_cost", value=100, source="calculated"),
                PatchOperation(op="add", path="/staffing_plan/roles/qa", value={"role_id": "qa"}, source="ai_recommended"),
                PatchOperation(op="remove", path="/warnings/0", value=None),
            ],
            version=5,
            version_before=4,
            version_after=5,
        )
        json_str = p.model_dump_json()
        restored = Patch.model_validate_json(json_str)
        assert len(restored.operations) == 3
        assert restored.operations[0].op == "replace"
        assert restored.operations[1].op == "add"
        assert restored.operations[2].op == "remove"
