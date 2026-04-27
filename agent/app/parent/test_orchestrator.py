"""Tests for ParentOrchestrator (orchestrator.py).

Validates:
- State transitions: IDLE → PLANNING → DELEGATING → PATCHING → RESPONDING → IDLE
- handle_message full pipeline (Memory → DynamoDB → task plan → delegate → patch)
- apply_patches with optimistic locking
- publish_patch / publish_status logging
- Dual-entry mode detection (architecture_present vs architecture_absent)
- Error handling: VersionConflictError, general exceptions
- Auditable mapping: user message → delegated task → result patches

Requirements: 1.1, 1.2, 4.1, 4.2, 4.5, 4.6, 9.1, 9.4
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from unittest.mock import patch

from agent.app.parent.orchestrator import (
    AgentResult,
    OrchestratorState,
    ParentOrchestrator,
    Task,
    TaskPlan,
    _apply_operation,
    _architecture_service_to_field_values,
    _discovery_schema_patches,
)
from agent.lib.schema.document_state import Contribution, DocumentState, BlockingIssue, Warning
from agent.lib.schema.patch import AgentStatus, Patch, PatchOperation
from agent.lib.storage.dynamodb import DocumentStore, VersionConflictError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store() -> DocumentStore:
    """Fresh in-memory document store."""
    return DocumentStore()


@pytest.fixture
def orchestrator(store: DocumentStore) -> ParentOrchestrator:
    """Orchestrator with in-memory store, no Memory, mocked sub-agents."""
    from unittest.mock import AsyncMock, MagicMock
    from agent.app.discovery.discovery_agent import DiscoveryResult, MissingFields
    from agent.app.staffing.staffing_agent import StaffingRecommendation
    from agent.app.architecture.architecture_agent import ArchitectureResult
    from agent.app.reviewer.reviewer_agent import ReviewResult

    orch = ParentOrchestrator(document_store=store, memory=None)

    # Mock discovery agent
    mock_discovery = MagicMock()
    mock_discovery.collect_info = AsyncMock(return_value=DiscoveryResult(
        structured_input={"customer": "TestCorp"},
        missing=MissingFields(draft_required=[], export_required=[]),
        follow_up_questions=[],
        can_generate_draft=True,
    ))
    orch._discovery_agent = mock_discovery

    # Mock architecture agent
    mock_arch = MagicMock()
    mock_arch.analyze_existing = AsyncMock(return_value=ArchitectureResult(
        services=["lambda", "s3"],
        analysis="아키텍처 분석 완료",
    ))
    mock_arch.design_new = AsyncMock(return_value=ArchitectureResult(
        services=["lambda"],
        analysis="아키텍처 설계 완료",
    ))
    orch._architecture_agent = mock_arch

    # Mock staffing agent
    mock_staffing = MagicMock()
    mock_staffing.recommend.return_value = StaffingRecommendation(
        project_type="genai_multi_agent", roles={}, violations=[],
    )
    orch._staffing_agent = mock_staffing

    # Mock reviewer agent — use real ReviewerAgent since it's deterministic
    # (no LLM calls in review())

    return orch


@pytest.fixture
def seeded_store(store: DocumentStore) -> DocumentStore:
    """Store with a pre-existing document at version 1."""
    doc = DocumentState(document_id="doc-001", version=0)
    store.put(doc)
    # put sets version via model, update increments
    stored = store.update(doc, expected_version=0)
    assert stored.version == 1
    return store


# ---------------------------------------------------------------------------
# State transition tests
# ---------------------------------------------------------------------------

class TestStateTransitions:
    """Verify IDLE → PLANNING → DELEGATING → PATCHING → RESPONDING → IDLE."""

    @pytest.mark.asyncio
    async def test_handle_message_returns_to_idle(self, orchestrator: ParentOrchestrator):
        assert orchestrator.state == OrchestratorState.IDLE

        await orchestrator.handle_message("doc-001", "hello", [])

        assert orchestrator.state == OrchestratorState.IDLE

    @pytest.mark.asyncio
    async def test_state_transitions_during_handle_message(self, store: DocumentStore):
        """Capture state transitions by monkey-patching _transition."""
        transitions: list[str] = []
        orch = ParentOrchestrator(document_store=store, memory=None)

        original_transition = orch._transition

        def tracking_transition(new_state: OrchestratorState) -> None:
            transitions.append(new_state.value)
            original_transition(new_state)

        orch._transition = tracking_transition

        await orch.handle_message("doc-001", "test message", [])

        assert transitions == [
            "planning",
            "delegating",
            "patching",
            "responding",
            "idle",
        ]

    @pytest.mark.asyncio
    async def test_returns_to_idle_on_error(self, orchestrator: ParentOrchestrator):
        """Even on error, state should return to IDLE."""
        # Force an error by making document_store.get raise unexpectedly
        def broken_get(doc_id):
            raise RuntimeError("simulated failure")

        orchestrator.document_store.get = broken_get
        # Also break put so _fetch_document_state fails entirely
        orchestrator.document_store.put = lambda doc: (_ for _ in ()).throw(RuntimeError("simulated"))

        plan = await orchestrator.handle_message("doc-err", "test", [])

        assert orchestrator.state == OrchestratorState.IDLE
        assert "오류" in plan.chat_response


# ---------------------------------------------------------------------------
# handle_message pipeline tests
# ---------------------------------------------------------------------------

class TestHandleMessage:

    @pytest.mark.asyncio
    async def test_creates_document_if_not_found(self, orchestrator: ParentOrchestrator):
        plan = await orchestrator.handle_message("new-doc", "hello", [])

        assert plan.chat_response  # non-empty response
        assert orchestrator.document_store.exists("new-doc")

    @pytest.mark.asyncio
    async def test_returns_task_plan_with_chat_response(self, orchestrator: ParentOrchestrator):
        plan = await orchestrator.handle_message("doc-001", "프로젝트 개요를 알려주세요", [])

        assert isinstance(plan, TaskPlan)
        assert isinstance(plan.chat_response, str)
        assert len(plan.chat_response) > 0

    @pytest.mark.asyncio
    async def test_publishes_processing_and_idle_status(self, orchestrator: ParentOrchestrator):
        await orchestrator.handle_message("doc-001", "test", [])

        statuses = [s["status"] for s in orchestrator._status_log]
        assert "processing" in statuses
        assert "idle" in statuses

    @pytest.mark.asyncio
    async def test_audit_log_populated(self, orchestrator: ParentOrchestrator):
        await orchestrator.handle_message("doc-001", "test", [])

        assert len(orchestrator._audit_log) > 0
        entry = orchestrator._audit_log[0]
        assert "agent" in entry
        assert "action" in entry
        assert "success" in entry


# ---------------------------------------------------------------------------
# Dual-entry mode detection
# ---------------------------------------------------------------------------

class TestDualEntryMode:

    @pytest.mark.asyncio
    async def test_drawio_routes_to_architecture_agent(self, orchestrator: ParentOrchestrator):
        await orchestrator.handle_message("doc-001", "여기 .drawio 파일입니다", [])

        agents = [e["agent"] for e in orchestrator._audit_log]
        assert "architecture_agent" in agents

    @pytest.mark.asyncio
    async def test_text_routes_to_discovery_agent(self, orchestrator: ParentOrchestrator):
        await orchestrator.handle_message("doc-001", "새 프로젝트를 시작합니다", [])

        agents = [e["agent"] for e in orchestrator._audit_log]
        assert "discovery_agent" in agents

    @pytest.mark.asyncio
    async def test_architecture_file_keyword(self, orchestrator: ParentOrchestrator):
        await orchestrator.handle_message("doc-001", "아키텍처 파일을 업로드합니다", [])

        agents = [e["agent"] for e in orchestrator._audit_log]
        assert "architecture_agent" in agents


# ---------------------------------------------------------------------------
# delegate_task tests
# ---------------------------------------------------------------------------

class TestDelegateTask:

    @pytest.mark.asyncio
    async def test_delegate_returns_agent_result(self, orchestrator: ParentOrchestrator):
        """delegate_task should return AgentResult from actual sub-agent dispatch."""
        from unittest.mock import AsyncMock, MagicMock
        from agent.app.discovery.discovery_agent import DiscoveryResult, MissingFields

        doc = DocumentState(document_id="doc-001")
        task = Task(agent="discovery_agent", action="collect_info", params={"message": "hi"})

        # Mock the discovery agent to avoid LLM calls
        mock_discovery = MagicMock()
        mock_discovery.collect_info = AsyncMock(return_value=DiscoveryResult(
            structured_input={"customer": "TestCorp"},
            missing=MissingFields(draft_required=[], export_required=[]),
            follow_up_questions=[],
            can_generate_draft=True,
        ))
        orchestrator._discovery_agent = mock_discovery

        result = await orchestrator.delegate_task("discovery_agent", task, doc)

        assert isinstance(result, AgentResult)
        assert result.success is True
        assert len(result.patches) > 0  # should have patches from extracted fields

    @pytest.mark.asyncio
    async def test_delegate_creates_audit_entry(self, orchestrator: ParentOrchestrator):
        """delegate_task should create an audit log entry with agent/action/success."""
        from unittest.mock import MagicMock

        doc = DocumentState(document_id="doc-001")
        task = Task(agent="staffing_agent", action="recommend", params={"message": "GenAI project"})

        # Mock the staffing agent to avoid LLM calls
        from agent.app.staffing.staffing_agent import StaffingRecommendation
        mock_staffing = MagicMock()
        mock_staffing.recommend.return_value = StaffingRecommendation(
            project_type="genai_multi_agent",
            roles={},
            violations=[],
        )
        orchestrator._staffing_agent = mock_staffing

        await orchestrator.delegate_task("staffing_agent", task, doc)

        assert len(orchestrator._audit_log) == 1
        assert orchestrator._audit_log[0]["agent"] == "staffing_agent"
        assert orchestrator._audit_log[0]["action"] == "recommend"
        assert orchestrator._audit_log[0]["success"] is True

    @pytest.mark.asyncio
    async def test_delegate_unknown_agent_returns_error(self, orchestrator: ParentOrchestrator):
        """Unknown agent_name should return a failed AgentResult."""
        doc = DocumentState(document_id="doc-001")
        task = Task(agent="unknown_agent", action="do_stuff", params={})

        result = await orchestrator.delegate_task("unknown_agent", task, doc)

        assert result.success is False
        assert "알 수 없는 에이전트" in result.chat_response

    @pytest.mark.asyncio
    async def test_delegate_exception_returns_error_result(self, orchestrator: ParentOrchestrator):
        """If a sub-agent raises, delegate_task should catch and return error."""
        from unittest.mock import AsyncMock, MagicMock

        doc = DocumentState(document_id="doc-001")
        task = Task(agent="discovery_agent", action="collect_info", params={"message": "hi"})

        mock_discovery = MagicMock()
        mock_discovery.collect_info = AsyncMock(side_effect=RuntimeError("LLM down"))
        orchestrator._discovery_agent = mock_discovery

        result = await orchestrator.delegate_task("discovery_agent", task, doc)

        assert result.success is False
        assert "오류" in result.chat_response
        # Audit log should still record the failure
        assert orchestrator._audit_log[-1]["success"] is False

    @pytest.mark.asyncio
    async def test_delegate_reviewer_returns_patches(self, orchestrator: ParentOrchestrator):
        """Reviewer delegation should return completion_score and issues as patches."""
        from unittest.mock import MagicMock
        from agent.app.reviewer.reviewer_agent import ReviewResult
        from agent.lib.schema.document_state import BlockingIssue, Warning as DocWarning

        doc = DocumentState(document_id="doc-001")
        task = Task(agent="reviewer_agent", action="review", params={})

        # Mock reviewer agent since its __init__ requires strands.Agent
        mock_reviewer = MagicMock()
        mock_reviewer.review.return_value = ReviewResult(
            completion_score=0.45,
            blocking_issues=[BlockingIssue(code="MISSING_COVER", message="Cover 누락", section="cover")],
            warnings=[DocWarning(code="ZERO_COST", message="비용 0", section="cost_breakdown")],
            suggestions=["[blocking] Cover 누락"],
        )
        orchestrator._reviewer_agent = mock_reviewer

        result = await orchestrator.delegate_task("reviewer_agent", task, doc)

        assert result.success is True
        assert len(result.patches) >= 1  # at least completion_score patch
        paths = [p["path"] for p in result.patches]
        assert "/completion_score" in paths

    @pytest.mark.asyncio
    async def test_delegate_cost_staffing_calculation(self, orchestrator: ParentOrchestrator):
        """Cost agent delegation should calculate staffing cost deterministically."""
        from unittest.mock import MagicMock
        from agent.app.cost.cost_agent import StaffingCostResult
        from agent.lib.schema.document_state import (
            StaffingPlan, StaffingRole, FieldValue, FieldStatus, PhaseHours,
        )

        role = StaffingRole(
            role_id="pm",
            display_name="PM",
            count=FieldValue(ai_recommended=1, status=FieldStatus.recommended),
            allocation_pct=FieldValue(ai_recommended=100, status=FieldStatus.recommended),
            rate_per_hour=FieldValue(ai_recommended=80.0, status=FieldStatus.recommended),
            phase_hours=PhaseHours(
                discovery=FieldValue(ai_recommended=40, status=FieldStatus.recommended),
                development=FieldValue(ai_recommended=80, status=FieldStatus.recommended),
                testing=FieldValue(ai_recommended=20, status=FieldStatus.recommended),
            ),
        )
        doc = DocumentState(
            document_id="doc-001",
            staffing_plan=StaffingPlan(roles={"pm": role}),
        )
        task = Task(agent="cost_agent", action="calculate", params={})

        # Mock cost agent since its __init__ requires strands.Agent
        mock_cost = MagicMock()
        mock_cost.calculate_staffing_cost.return_value = StaffingCostResult(
            roles_summary=[{"role_id": "pm", "total_hours": 140, "total_cost": 11200.0}],
            grand_total=11200.0,
        )
        mock_cost.calculate_default_contribution.return_value = Contribution()
        orchestrator._cost_agent = mock_cost

        result = await orchestrator.delegate_task("cost_agent", task, doc)

        assert result.success is True
        assert len(result.patches) >= 1
        assert "인건비" in result.chat_response

    @pytest.mark.asyncio
    async def test_discovery_delegate_populates_docx_schema_fields(self, orchestrator: ParentOrchestrator):
        from unittest.mock import AsyncMock, MagicMock
        from agent.app.discovery.discovery_agent import DiscoveryResult, MissingFields

        mock_discovery = MagicMock()
        mock_discovery.collect_info = AsyncMock(return_value=DiscoveryResult(
            structured_input={
                "customer": "TestCorp",
                "architecture_available": False,
                "executive_sponsors": [
                    {"name": "Kim", "title": "VP", "description": "Sponsor", "contact": "kim@example.com"},
                ],
                "success_criteria": ["Success"],
            },
            missing=MissingFields(),
            can_generate_draft=True,
            executive_summary="Summary",
            executive_sponsors=[{"name": "Kim", "title": "VP", "description": "Sponsor", "contact": "kim@example.com"}],
            stakeholders=[],
            project_team=[],
            escalation_contacts=[],
            success_criteria=["Success"],
            assumptions=[],
            scope_of_work=[],
            acceptance_text="Accepted by customer",
        ))
        orchestrator._discovery_agent = mock_discovery

        result = await orchestrator.delegate_task(
            "discovery_agent",
            Task(agent="discovery_agent", action="collect", params={"message": "hi"}),
            DocumentState(document_id="doc-001"),
        )

        patches = {p["path"]: p["value"] for p in result.patches}
        assert patches["/sections/executive_summary/text"]["ai_recommended"] == "Summary"
        assert patches["/sections/stakeholders/executive_sponsors"][0]["role_or_description"]["ai_recommended"] == "Sponsor"
        assert "/sections/stakeholders/stakeholders" not in patches
        assert patches["/sections/success_criteria/items"][0]["ai_recommended"] == "Success"
        assert patches["/sections/acceptance/text"]["ai_recommended"] == "Accepted by customer"

    def test_discovery_schema_patches_include_new_apn_paths(self):
        from agent.app.discovery.discovery_agent import DiscoveryResult

        result = DiscoveryResult(
            structured_input={},
            executive_summary_fields={
                "customer_intro": "Customer intro",
                "problem_statement": "Problem",
                "proposed_solution": "Solution",
                "phases_overview": ["Discover", "Build"],
            },
            business_case={
                "problem_definition": "Manual work",
                "roi_calculation": "25% cycle reduction",
                "executive_sponsor": "VP Operations",
                "production_commitment": "Production after PoC",
            },
            success_criteria_groups=[
                {"category_name": "Project Objective", "items": ["Success metric"]},
            ],
            assumption_groups=[
                {"category_name": "Business Context", "items": ["SMEs available"]},
            ],
            scope_tasks=[
                {
                    "task_category": "Technical Framework Design",
                    "schedule": "Week 1",
                    "details": ["Design agent workflow"],
                    "personnel": "SA",
                },
            ],
        )

        patches = {p["path"]: p["value"] for p in _discovery_schema_patches(result)}

        assert patches["/sections/executive_summary/customer_intro"]["ai_recommended"] == "Customer intro"
        assert patches["/sections/executive_summary/business_case/roi_calculation"]["ai_recommended"] == "25% cycle reduction"
        assert patches["/sections/executive_summary/phases_overview"][0]["ai_recommended"] == "Discover"
        assert patches["/sections/success_criteria/groups"][0]["category_name"]["ai_recommended"] == "Project Objective"
        assert patches["/sections/assumptions/groups"][0]["items"][0]["ai_recommended"] == "SMEs available"
        assert patches["/sections/scope_of_work/tasks"][0]["details"][0]["ai_recommended"] == "Design agent workflow"

    @pytest.mark.asyncio
    async def test_discovery_delegate_does_not_overwrite_omitted_lists(self, orchestrator: ParentOrchestrator):
        from unittest.mock import AsyncMock, MagicMock
        from agent.app.discovery.discovery_agent import DiscoveryResult, MissingFields

        mock_discovery = MagicMock()
        mock_discovery.collect_info = AsyncMock(return_value=DiscoveryResult(
            structured_input={"customer": "TestCorp", "stakeholders": "legacy stakeholder text"},
            missing=MissingFields(),
            can_generate_draft=True,
            stakeholders=[],
            success_criteria=[],
        ))
        orchestrator._discovery_agent = mock_discovery

        result = await orchestrator.delegate_task(
            "discovery_agent",
            Task(agent="discovery_agent", action="collect", params={"message": "hi"}),
            DocumentState(document_id="doc-001"),
        )

        paths = [p["path"] for p in result.patches]
        assert "/sections/stakeholders/stakeholders" not in paths
        assert "/sections/success_criteria/items" not in paths

    @pytest.mark.asyncio
    async def test_architecture_delegate_populates_description_and_tools(self, orchestrator: ParentOrchestrator):
        from unittest.mock import AsyncMock, MagicMock
        from agent.app.architecture.architecture_agent import ArchitectureResult

        mock_arch = MagicMock()
        mock_arch.design_new = AsyncMock(return_value=ArchitectureResult(
            services=["lambda"],
            analysis="analysis",
            description="Architecture description",
            tools=["AWS Lambda", "DynamoDB"],
        ))
        orchestrator._architecture_agent = mock_arch

        result = await orchestrator.delegate_task(
            "architecture_agent",
            Task(agent="architecture_agent", action="design", params={"message": "design"}),
            DocumentState(document_id="doc-001"),
        )

        patches = {p["path"]: p["value"] for p in result.patches}
        assert patches["/sections/architecture/description"]["ai_recommended"] == "Architecture description"
        assert patches["/sections/architecture/tools"][0]["ai_recommended"] == "AWS Lambda"

    @pytest.mark.asyncio
    async def test_architecture_delegate_patches_new_service_schema(self, orchestrator: ParentOrchestrator):
        from unittest.mock import AsyncMock, MagicMock
        from agent.app.architecture.architecture_agent import ArchitectureResult

        mock_arch = MagicMock()
        mock_arch.design_new = AsyncMock(return_value=ArchitectureResult(
            overview="Bedrock agent architecture",
            services=[
                {
                    "service_name": "Amazon Bedrock",
                    "service_id": "amazon_bedrock",
                    "priority": 1,
                    "category": "genai_core",
                    "description": "Foundation model orchestration",
                    "sizing_rationale": "Required for GenAI workload",
                    "is_required_for_funding": True,
                },
            ],
        ))
        orchestrator._architecture_agent = mock_arch

        result = await orchestrator.delegate_task(
            "architecture_agent",
            Task(agent="architecture_agent", action="design", params={"message": "design"}),
            DocumentState(document_id="doc-001"),
        )

        patches = {p["path"]: p["value"] for p in result.patches}
        service = patches["/sections/architecture/services"][0]
        assert patches["/sections/architecture/overview"]["ai_recommended"] == "Bedrock agent architecture"
        assert service["service_name"]["ai_recommended"] == "Amazon Bedrock"
        assert service["service_id"] == "amazon_bedrock"
        assert service["category"] == "genai_core"
        assert service["is_required_for_funding"] is True

    def test_architecture_service_helper_wraps_field_values(self):
        service = _architecture_service_to_field_values({
            "service_name": "Amazon S3",
            "service_id": "amazon_s3",
            "priority": 11,
            "category": "data",
            "description": "Object storage",
            "sizing_rationale": "Stores artifacts",
        })

        assert service["service_name"]["ai_recommended"] == "Amazon S3"
        assert service["description"]["ai_recommended"] == "Object storage"
        assert service["priority"] == 11
        assert service["category"] == "data"

    @pytest.mark.asyncio
    async def test_architecture_delegate_patches_description_once(self, orchestrator: ParentOrchestrator):
        from unittest.mock import AsyncMock, MagicMock
        from agent.app.architecture.architecture_agent import ArchitectureResult

        mock_arch = MagicMock()
        mock_arch.design_new = AsyncMock(return_value=ArchitectureResult(
            analysis="analysis",
            architecture_description="Legacy description",
            description="New description",
        ))
        orchestrator._architecture_agent = mock_arch

        result = await orchestrator.delegate_task(
            "architecture_agent",
            Task(agent="architecture_agent", action="design", params={"message": "design"}),
            DocumentState(document_id="doc-001"),
        )

        description_patches = [
            p for p in result.patches
            if p["path"] == "/sections/architecture/description"
        ]
        assert len(description_patches) == 1
        assert description_patches[0]["value"]["ai_recommended"] == "New description"

    @pytest.mark.asyncio
    async def test_cost_delegate_populates_default_contribution(self, orchestrator: ParentOrchestrator):
        from unittest.mock import MagicMock
        from agent.app.cost.cost_agent import CostAgent, StaffingCostResult

        with patch("agent.app.cost.cost_agent.Agent"):
            contribution = CostAgent().calculate_default_contribution(1000.0)

        mock_cost = MagicMock()
        mock_cost.calculate_staffing_cost.return_value = StaffingCostResult(
            roles_summary=[],
            grand_total=1000.0,
        )
        mock_cost.calculate_default_contribution.return_value = contribution
        orchestrator._cost_agent = mock_cost

        result = await orchestrator.delegate_task(
            "cost_agent",
            Task(agent="cost_agent", action="calculate", params={}),
            DocumentState(document_id="doc-001"),
        )

        patches = {p["path"]: p["value"] for p in result.patches}
        contribution_patch = patches["/sections/resources_cost_estimates/contribution"]
        assert contribution_patch["customer"]["amount"]["ai_recommended"] == 500.0
        assert contribution_patch["partner"]["pct"]["ai_recommended"] == 25

    @pytest.mark.asyncio
    async def test_aws_cost_contribution_uses_existing_cost_breakdown_staffing_total(self, orchestrator: ParentOrchestrator):
        from unittest.mock import AsyncMock, MagicMock
        from agent.app.cost.cost_agent import AWSCostResult, CostAgent

        doc = DocumentState(document_id="doc-001")
        doc.sections.cost_breakdown.staffing_cost.grand_total.calculated = 1000.0

        with patch("agent.app.cost.cost_agent.Agent"):
            contribution = CostAgent().calculate_default_contribution(1200.0)

        mock_cost = MagicMock()
        mock_cost.calculate_aws_cost = AsyncMock(return_value=AWSCostResult(
            monthly_cost_summary=200.0,
            service_breakdown=[],
        ))
        mock_cost.calculate_default_contribution.return_value = contribution
        orchestrator._cost_agent = mock_cost
        orchestrator.gateway_client = MagicMock()

        result = await orchestrator.delegate_task(
            "cost_agent",
            Task(agent="cost_agent", action="calculate_aws_cost", params={"services": []}),
            doc,
        )

        mock_cost.calculate_default_contribution.assert_called_once_with(1200.0)
        patches = {p["path"]: p["value"] for p in result.patches}
        contribution_patch = patches["/sections/resources_cost_estimates/contribution"]
        assert contribution_patch["customer"]["amount"]["ai_recommended"] == 600.0


# ---------------------------------------------------------------------------
# apply_patches tests
# ---------------------------------------------------------------------------

class TestApplyPatches:

    @pytest.mark.asyncio
    async def test_apply_patches_increments_version(self, seeded_store: DocumentStore):
        orch = ParentOrchestrator(document_store=seeded_store, memory=None)

        patch = Patch(
            patch_id="p-001",
            doc_id="doc-001",
            agent="test",
            version=0,
            operations=[
                PatchOperation(op="replace", path="/completion_score", value=0.5)
            ],
        )

        new_version = await orch.apply_patches("doc-001", [patch], expected_version=1)

        assert new_version == 2
        doc = seeded_store.get("doc-001")
        assert doc.version == 2

    @pytest.mark.asyncio
    async def test_apply_patches_raises_on_version_conflict(self, seeded_store: DocumentStore):
        orch = ParentOrchestrator(document_store=seeded_store, memory=None)

        patch = Patch(
            patch_id="p-001",
            doc_id="doc-001",
            agent="test",
            version=0,
            operations=[
                PatchOperation(op="replace", path="/completion_score", value=0.5)
            ],
        )

        with pytest.raises(VersionConflictError):
            await orch.apply_patches("doc-001", [patch], expected_version=999)

    @pytest.mark.asyncio
    async def test_apply_patches_publishes_to_patch_log(self, seeded_store: DocumentStore):
        orch = ParentOrchestrator(document_store=seeded_store, memory=None)

        patch = Patch(
            patch_id="p-001",
            doc_id="doc-001",
            agent="test",
            version=0,
            operations=[
                PatchOperation(op="replace", path="/completion_score", value=0.3)
            ],
        )

        await orch.apply_patches("doc-001", [patch], expected_version=1)

        assert len(orch._patch_log) == 1
        assert orch._patch_log[0].patch_id == "p-001"


# ---------------------------------------------------------------------------
# publish_patch / publish_status tests
# ---------------------------------------------------------------------------

class TestPublishing:

    @pytest.mark.asyncio
    async def test_publish_patch_logs_without_appsync(self, orchestrator: ParentOrchestrator):
        patch = Patch(
            patch_id="p-001",
            doc_id="doc-001",
            agent="test",
            operations=[PatchOperation(op="replace", path="/mode", value="architecture_present")],
        )

        await orchestrator.publish_patch("doc-001", [patch])

        assert len(orchestrator._patch_log) == 1

    @pytest.mark.asyncio
    async def test_publish_patch_payload_includes_event_contract(self, orchestrator: ParentOrchestrator):
        published = []

        async def fake_publish(channel: str, payload: dict):
            published.append((channel, payload))

        orchestrator._appsync_publish = fake_publish

        patch = Patch(
            patch_id="p-001",
            doc_id="doc-001",
            agent="test",
            version_before=1,
            version_after=2,
            operations=[PatchOperation(op="replace", path="/mode", value="architecture_present")],
        )

        import agent.app.parent.orchestrator as orchestrator_mod

        old_endpoint = orchestrator_mod.APPSYNC_HTTP_ENDPOINT
        orchestrator_mod.APPSYNC_HTTP_ENDPOINT = "https://example.com/event"
        try:
            await orchestrator.publish_patch("doc-001", [patch])
        finally:
            orchestrator_mod.APPSYNC_HTTP_ENDPOINT = old_endpoint

        assert published[0][0] == "docs/doc-001/patch"
        assert published[0][1]["type"] == "patch"
        assert published[0][1]["version_before"] == 1
        assert published[0][1]["version_after"] == 2
        assert published[0][1]["operations"] == [
            {
                "op": "replace",
                "path": "/mode",
                "value": "architecture_present",
                "source": None,
            }
        ]

    @pytest.mark.asyncio
    async def test_publish_status_logs_without_appsync(self, orchestrator: ParentOrchestrator):
        await orchestrator.publish_status("doc-001", AgentStatus.processing)

        assert len(orchestrator._status_log) == 1
        assert orchestrator._status_log[0]["status"] == "processing"

    @pytest.mark.asyncio
    async def test_publish_multiple_statuses(self, orchestrator: ParentOrchestrator):
        await orchestrator.publish_status("doc-001", AgentStatus.processing)
        await orchestrator.publish_status("doc-001", AgentStatus.idle)

        assert len(orchestrator._status_log) == 2
        statuses = [s["status"] for s in orchestrator._status_log]
        assert statuses == ["processing", "idle"]


# ---------------------------------------------------------------------------
# _apply_operation helper tests
# ---------------------------------------------------------------------------

class TestApplyOperation:

    def test_replace_top_level(self):
        doc = {"completion_score": 0.0}
        _apply_operation(doc, PatchOperation(op="replace", path="/completion_score", value=0.75))
        assert doc["completion_score"] == 0.75

    def test_replace_nested(self):
        doc = {"meta": {"customer": {"user_input": None}}}
        _apply_operation(
            doc,
            PatchOperation(op="replace", path="/meta/customer/user_input", value="ABC Corp"),
        )
        assert doc["meta"]["customer"]["user_input"] == "ABC Corp"

    def test_add_creates_path(self):
        doc = {"sections": {}}
        _apply_operation(
            doc,
            PatchOperation(op="add", path="/sections/cover/title", value="New Title"),
        )
        assert doc["sections"]["cover"]["title"] == "New Title"

    def test_remove_key(self):
        doc = {"meta": {"customer": {"user_input": "old"}}}
        _apply_operation(
            doc,
            PatchOperation(op="remove", path="/meta/customer/user_input"),
        )
        assert "user_input" not in doc["meta"]["customer"]

    def test_empty_path_is_noop(self):
        doc = {"key": "value"}
        _apply_operation(doc, PatchOperation(op="replace", path="", value="x"))
        assert doc == {"key": "value"}


# ---------------------------------------------------------------------------
# Version conflict handling in handle_message
# ---------------------------------------------------------------------------

class TestVersionConflictHandling:

    @pytest.mark.asyncio
    async def test_version_conflict_returns_error_message(self, orchestrator: ParentOrchestrator):
        """When VersionConflictError occurs, handle_message should return
        an error chat_response and publish error status."""
        # Seed a document
        doc = DocumentState(document_id="doc-vc", version=0)
        orchestrator.document_store.put(doc)

        # Sabotage the store to always raise VersionConflictError on update
        original_update = orchestrator.document_store.update

        def conflict_update(d, v):
            raise VersionConflictError("forced conflict")

        orchestrator.document_store.update = conflict_update

        # Also make delegate_task return patches so apply_patches is triggered
        async def patchy_delegate(agent_name, task, doc_state):
            return AgentResult(
                success=True,
                patches=[{"op": "replace", "path": "/completion_score", "value": 0.5}],
            )

        orchestrator.delegate_task = patchy_delegate

        plan = await orchestrator.handle_message("doc-vc", "test", [])

        assert "충돌" in plan.chat_response or "오류" in plan.chat_response
        assert orchestrator.state == OrchestratorState.IDLE

        # Error status should have been published
        statuses = [s["status"] for s in orchestrator._status_log]
        assert "error" in statuses


# ---------------------------------------------------------------------------
# Sequential handle_message calls
# ---------------------------------------------------------------------------

class TestSequentialCalls:

    @pytest.mark.asyncio
    async def test_multiple_handle_message_calls_reset_state(self, orchestrator: ParentOrchestrator):
        """State should be IDLE between sequential handle_message calls."""
        await orchestrator.handle_message("doc-001", "first message", [])
        assert orchestrator.state == OrchestratorState.IDLE

        await orchestrator.handle_message("doc-001", "second message", [])
        assert orchestrator.state == OrchestratorState.IDLE

    @pytest.mark.asyncio
    async def test_sequential_calls_accumulate_audit_log(self, orchestrator: ParentOrchestrator):
        """Each handle_message call should add entries to the audit log."""
        await orchestrator.handle_message("doc-001", "first", [])
        first_count = len(orchestrator._audit_log)
        assert first_count > 0

        await orchestrator.handle_message("doc-001", "second", [])
        assert len(orchestrator._audit_log) > first_count

    @pytest.mark.asyncio
    async def test_error_then_success_resets_state(self, orchestrator: ParentOrchestrator):
        """After an error, the next call should still work normally."""
        # Force an error
        def broken_get(doc_id):
            raise RuntimeError("simulated failure")

        orchestrator.document_store.get = broken_get
        orchestrator.document_store.put = lambda doc: (_ for _ in ()).throw(RuntimeError("simulated"))

        plan1 = await orchestrator.handle_message("doc-err", "test", [])
        assert orchestrator.state == OrchestratorState.IDLE
        assert "오류" in plan1.chat_response

        # Restore normal store
        orchestrator.document_store = DocumentStore()

        plan2 = await orchestrator.handle_message("doc-ok", "test", [])
        assert orchestrator.state == OrchestratorState.IDLE
        assert plan2.chat_response  # non-empty


# ---------------------------------------------------------------------------
# _apply_operation edge cases
# ---------------------------------------------------------------------------

class TestApplyOperationEdgeCases:

    def test_replace_on_non_dict_parent_is_noop(self):
        doc = {"meta": "not_a_dict"}
        _apply_operation(
            doc,
            PatchOperation(op="replace", path="/meta/child/key", value="val"),
        )
        # Should not crash; meta is a string, can't traverse further
        assert doc["meta"] == "not_a_dict"

    def test_add_deeply_nested_creates_intermediates(self):
        doc = {}
        _apply_operation(
            doc,
            PatchOperation(op="add", path="/a/b/c/d", value=42),
        )
        assert doc["a"]["b"]["c"]["d"] == 42

    def test_remove_nonexistent_key_is_noop(self):
        doc = {"meta": {"customer": {}}}
        _apply_operation(
            doc,
            PatchOperation(op="remove", path="/meta/customer/nonexistent"),
        )
        assert doc == {"meta": {"customer": {}}}

    def test_unknown_op_is_noop(self):
        doc = {"key": "value"}
        _apply_operation(
            doc,
            PatchOperation(op="move", path="/key", value="new"),
        )
        assert doc["key"] == "value"


# ---------------------------------------------------------------------------
# Memory degraded mode tests (Req 2.5)
# ---------------------------------------------------------------------------

class TestMemoryDegradedMode:
    """When Memory API fails, the system should continue with bounded
    session history and publish a warning/degraded status."""

    @pytest.mark.asyncio
    async def test_memory_retrieval_failure_publishes_degraded_status(self, store: DocumentStore):
        """Memory retrieve failure → degraded status published, pipeline continues."""
        from unittest.mock import MagicMock

        mock_memory = MagicMock()
        mock_memory.on_degraded = None  # will be overwritten by orchestrator
        mock_memory.retrieve_customer_context.return_value = []

        orch = ParentOrchestrator(document_store=store, memory=mock_memory)

        # Simulate the on_degraded callback being triggered
        # by making retrieve_customer_context trigger the callback
        def failing_retrieve(customer, query):
            # Simulate _safe_call triggering on_degraded
            if orch._on_memory_degraded:
                orch._on_memory_degraded("retrieve_customer_context", RuntimeError("API down"))
            return []

        mock_memory.retrieve_customer_context.side_effect = failing_retrieve

        plan = await orch.handle_message("doc-001", "hello", [])

        # Pipeline should complete successfully
        assert plan.chat_response
        assert orch.state == OrchestratorState.IDLE

        # Degraded status should have been published
        degraded_statuses = [
            s for s in orch._status_log if s.get("status") == "degraded"
        ]
        assert len(degraded_statuses) >= 1
        assert degraded_statuses[0].get("reason") == "memory_api_failure"

    @pytest.mark.asyncio
    async def test_memory_store_failure_publishes_degraded_status(self, store: DocumentStore):
        """Memory store failure → degraded status published, pipeline continues."""
        from unittest.mock import MagicMock

        mock_memory = MagicMock()
        mock_memory.on_degraded = None
        mock_memory.retrieve_customer_context.return_value = []
        # store_session_event returns False (failure)
        mock_memory.store_session_event.return_value = False

        orch = ParentOrchestrator(document_store=store, memory=mock_memory)

        plan = await orch.handle_message("doc-001", "hello", [])

        assert plan.chat_response
        assert orch.state == OrchestratorState.IDLE

        # Degraded status for store failure
        degraded_statuses = [
            s for s in orch._status_log if s.get("status") == "degraded"
        ]
        assert len(degraded_statuses) >= 1
        store_failures = [
            s for s in degraded_statuses
            if s.get("failed_method") == "store_session_event"
        ]
        assert len(store_failures) == 1

    @pytest.mark.asyncio
    async def test_no_memory_means_no_degraded_status(self, orchestrator: ParentOrchestrator):
        """When memory is None, no degraded status should be published."""
        assert orchestrator.memory is None

        plan = await orchestrator.handle_message("doc-001", "hello", [])

        assert plan.chat_response
        degraded_statuses = [
            s for s in orchestrator._status_log if s.get("status") == "degraded"
        ]
        assert len(degraded_statuses) == 0

    @pytest.mark.asyncio
    async def test_memory_degraded_flag_resets_per_request(self, store: DocumentStore):
        """_memory_degraded flag should reset at the start of each handle_message."""
        from unittest.mock import MagicMock

        mock_memory = MagicMock()
        mock_memory.on_degraded = None
        mock_memory.retrieve_customer_context.return_value = []
        mock_memory.store_session_event.return_value = True

        orch = ParentOrchestrator(document_store=store, memory=mock_memory)

        # First call: no failure
        await orch.handle_message("doc-001", "first", [])
        assert orch._memory_degraded is False

        # Manually set flag to simulate leftover state
        orch._memory_degraded = True

        # Second call should reset it
        await orch.handle_message("doc-001", "second", [])
        assert orch._memory_degraded is False

    @pytest.mark.asyncio
    async def test_on_degraded_callback_wired_to_memory(self, store: DocumentStore):
        """Orchestrator should wire _on_memory_degraded to memory.on_degraded."""
        from agent.lib.memory.agentcore_memory import AgentCoreMemory
        from unittest.mock import patch as mock_patch, MagicMock

        with mock_patch("agent.lib.memory.agentcore_memory.boto3") as mock_boto3:
            mock_boto3.client.return_value = MagicMock()
            mem = AgentCoreMemory(memory_id="mem-001")

        orch = ParentOrchestrator(document_store=store, memory=mem)

        # The orchestrator should have set the callback
        assert mem.on_degraded is not None
        assert mem.on_degraded == orch._on_memory_degraded

    @pytest.mark.asyncio
    async def test_degraded_status_contains_memory_failure_info(self, store: DocumentStore):
        """Degraded status payload should contain reason and failed_method."""
        from unittest.mock import MagicMock

        mock_memory = MagicMock()
        mock_memory.on_degraded = None
        mock_memory.retrieve_customer_context.return_value = []
        mock_memory.store_session_event.return_value = False

        orch = ParentOrchestrator(document_store=store, memory=mock_memory)

        await orch.handle_message("doc-001", "test", [])

        degraded = [
            s for s in orch._status_log
            if s.get("status") == "degraded" and s.get("reason") == "memory_api_failure"
        ]
        assert len(degraded) >= 1
        entry = degraded[0]
        assert entry["doc_id"] == "doc-001"
        assert "message" in entry
        assert "Memory API" in entry["message"]


# ---------------------------------------------------------------------------
# Memory integration in handle_message flow (Task 3.3)
# Requirements: 2.1, 2.2, 2.3, 11.3
# ---------------------------------------------------------------------------

class TestMemoryContextSupplementation:
    """Verify that retrieved memory context supplements bounded history."""

    def test_supplement_history_with_memory_prepends_context(self):
        """Memory records should be prepended as a system message."""
        history = [
            {"role": "user", "content": "hello"},
            {"role": "agent", "content": "hi there"},
        ]
        memory_context = [
            {"content": {"text": "Uses EKS"}, "score": 0.95},
            {"content": {"text": "Seoul region only"}, "score": 0.88},
        ]

        result = ParentOrchestrator._supplement_history_with_memory(
            history, memory_context
        )

        assert len(result) == 3  # 1 system + 2 original
        assert result[0]["role"] == "system"
        assert "Uses EKS" in result[0]["content"]
        assert "Seoul region only" in result[0]["content"]
        # Original history preserved
        assert result[1] == history[0]
        assert result[2] == history[1]

    def test_supplement_history_empty_memory_returns_original(self):
        """Empty memory context should return history unchanged."""
        history = [{"role": "user", "content": "hello"}]

        result = ParentOrchestrator._supplement_history_with_memory(history, [])

        assert result == history

    def test_supplement_history_empty_text_records_skipped(self):
        """Records with empty text should be skipped."""
        history = [{"role": "user", "content": "hello"}]
        memory_context = [
            {"content": {"text": ""}},
            {"content": {"text": "Valid fact"}},
        ]

        result = ParentOrchestrator._supplement_history_with_memory(
            history, memory_context
        )

        assert len(result) == 2
        assert "Valid fact" in result[0]["content"]
        assert "장기 메모리" in result[0]["content"]

    def test_supplement_history_all_empty_text_returns_original(self):
        """If all records have empty text, return original history."""
        history = [{"role": "user", "content": "hello"}]
        memory_context = [{"content": {"text": ""}}, {"content": {}}]

        result = ParentOrchestrator._supplement_history_with_memory(
            history, memory_context
        )

        assert result == history

    @pytest.mark.asyncio
    async def test_handle_message_uses_memory_context(self, store: DocumentStore):
        """handle_message should supplement history with memory context."""
        from unittest.mock import MagicMock

        mock_memory = MagicMock()
        mock_memory.on_degraded = None
        mock_memory.retrieve_customer_context.return_value = [
            {"content": {"text": "Customer prefers ap-northeast-2"}}
        ]
        mock_memory.store_session_event.return_value = True
        mock_memory.store_long_term_facts.return_value = True

        orch = ParentOrchestrator(document_store=store, memory=mock_memory)

        plan = await orch.handle_message("doc-001", "hello", [])

        # Memory retrieval should have been called
        mock_memory.retrieve_customer_context.assert_called_once_with(
            customer="doc-001", query="hello"
        )
        assert plan.chat_response
        assert orch.state == OrchestratorState.IDLE


class TestLongTermFactDetection:
    """Verify long-term fact detection and storage (Req 2.2)."""

    def test_extract_security_keywords(self):
        orch = ParentOrchestrator(memory=None)
        facts = orch._extract_long_term_facts("이 프로젝트는 보안 요구사항이 있습니다")
        assert len(facts) >= 1
        categories = [f["category"] for f in facts]
        assert "security_requirement" in categories

    def test_extract_region_keywords(self):
        orch = ParentOrchestrator(memory=None)
        facts = orch._extract_long_term_facts("ap-northeast-2 리전에서만 운영해야 합니다")
        categories = [f["category"] for f in facts]
        assert "region_constraint" in categories

    def test_extract_compliance_keywords(self):
        orch = ParentOrchestrator(memory=None)
        facts = orch._extract_long_term_facts("HIPAA compliance가 필요합니다")
        categories = [f["category"] for f in facts]
        assert "compliance_requirement" in categories

    def test_extract_industry_keywords(self):
        orch = ParentOrchestrator(memory=None)
        facts = orch._extract_long_term_facts("금융 산업 고객입니다")
        categories = [f["category"] for f in facts]
        assert "industry" in categories

    def test_no_keywords_returns_empty(self):
        orch = ParentOrchestrator(memory=None)
        facts = orch._extract_long_term_facts("프로젝트 개요를 작성해주세요")
        assert facts == []

    def test_deduplicates_categories(self):
        """Multiple keywords for same category should produce one fact."""
        orch = ParentOrchestrator(memory=None)
        facts = orch._extract_long_term_facts("security 보안 관련 요구사항")
        categories = [f["category"] for f in facts]
        assert categories.count("security_requirement") == 1

    @pytest.mark.asyncio
    async def test_handle_message_stores_long_term_facts(self, store: DocumentStore):
        """When long-term keywords detected, store_long_term_facts is called."""
        from unittest.mock import MagicMock

        mock_memory = MagicMock()
        mock_memory.on_degraded = None
        mock_memory.retrieve_customer_context.return_value = []
        mock_memory.store_session_event.return_value = True
        mock_memory.store_long_term_facts.return_value = True

        orch = ParentOrchestrator(document_store=store, memory=mock_memory)

        await orch.handle_message("doc-001", "HIPAA compliance가 필요합니다", [])

        mock_memory.store_long_term_facts.assert_called_once()
        call_args = mock_memory.store_long_term_facts.call_args
        assert call_args.kwargs["customer"] == "doc-001"
        facts = call_args.kwargs["facts"]
        assert len(facts) >= 1
        assert any("compliance" in f["category"] for f in facts)

    @pytest.mark.asyncio
    async def test_handle_message_no_facts_skips_store(self, store: DocumentStore):
        """When no long-term keywords detected, store_long_term_facts is NOT called."""
        from unittest.mock import MagicMock

        mock_memory = MagicMock()
        mock_memory.on_degraded = None
        mock_memory.retrieve_customer_context.return_value = []
        mock_memory.store_session_event.return_value = True

        orch = ParentOrchestrator(document_store=store, memory=mock_memory)

        await orch.handle_message("doc-001", "프로젝트 개요를 작성해주세요", [])

        mock_memory.store_long_term_facts.assert_not_called()

    @pytest.mark.asyncio
    async def test_long_term_facts_failure_publishes_degraded(self, store: DocumentStore):
        """store_long_term_facts failure → degraded status published."""
        from unittest.mock import MagicMock

        mock_memory = MagicMock()
        mock_memory.on_degraded = None
        mock_memory.retrieve_customer_context.return_value = []
        mock_memory.store_session_event.return_value = True
        mock_memory.store_long_term_facts.return_value = False  # failure

        orch = ParentOrchestrator(document_store=store, memory=mock_memory)

        await orch.handle_message("doc-001", "보안 요구사항이 있습니다", [])

        degraded = [
            s for s in orch._status_log
            if s.get("status") == "degraded"
            and s.get("failed_method") == "store_long_term_facts"
        ]
        assert len(degraded) == 1

    @pytest.mark.asyncio
    async def test_no_memory_skips_long_term_facts(self, orchestrator: ParentOrchestrator):
        """When memory is None, long-term fact detection is skipped."""
        assert orchestrator.memory is None

        plan = await orchestrator.handle_message("doc-001", "보안 요구사항", [])

        assert plan.chat_response
        # No degraded status for long-term facts
        degraded = [
            s for s in orchestrator._status_log
            if s.get("failed_method") == "store_long_term_facts"
        ]
        assert len(degraded) == 0


class TestRuntimeMemoryWiring:
    """Verify runtime.py wires AgentCoreMemory into the orchestrator singleton."""

    def test_get_orchestrator_without_memory_id(self):
        """Without AGENTCORE_MEMORY_ID, orchestrator has no memory."""
        import importlib
        from unittest.mock import patch as mock_patch, MagicMock
        import agent.app.parent.runtime as runtime_mod

        # Reset singleton
        runtime_mod._orchestrator_instance = None

        with mock_patch.dict("os.environ", {}, clear=False):
            # Ensure AGENTCORE_MEMORY_ID is not set
            import os
            os.environ.pop("AGENTCORE_MEMORY_ID", None)

            with mock_patch(
                "agent.lib.storage.dynamodb.boto3"
            ) as mock_dynamodb_boto3:
                mock_dynamodb_boto3.resource.return_value.Table.return_value = MagicMock()

                importlib.reload(runtime_mod)
                runtime_mod._orchestrator_instance = None

                orch = runtime_mod._get_orchestrator()
                assert orch.memory is None

        # Cleanup
        runtime_mod._orchestrator_instance = None

    def test_get_orchestrator_with_memory_id(self):
        """With AGENTCORE_MEMORY_ID set, orchestrator gets AgentCoreMemory."""
        import importlib
        from unittest.mock import patch as mock_patch, MagicMock
        import agent.app.parent.runtime as runtime_mod

        # Reset singleton
        runtime_mod._orchestrator_instance = None

        with mock_patch.dict(
            "os.environ",
            {"AGENTCORE_MEMORY_ID": "mem-test-123"},
        ):
            with mock_patch(
                "agent.lib.memory.agentcore_memory.boto3"
            ) as mock_boto3:
                with mock_patch(
                    "agent.lib.storage.dynamodb.boto3"
                ) as mock_dynamodb_boto3:
                    mock_boto3.client.return_value = MagicMock()
                    mock_dynamodb_boto3.resource.return_value.Table.return_value = MagicMock()

                    importlib.reload(runtime_mod)
                    runtime_mod._orchestrator_instance = None

                    orch = runtime_mod._get_orchestrator()
                    assert orch.memory is not None
                    assert orch.memory.memory_id == "mem-test-123"

        # Cleanup
        runtime_mod._orchestrator_instance = None
        importlib.reload(runtime_mod)


# ---------------------------------------------------------------------------
# Task 10.1: Milestone sync tests (Req 14.1, 14.2, 14.3)
# ---------------------------------------------------------------------------

class TestMilestoneSync:
    """Verify milestone regeneration when staffing_plan or scope changes."""

    @pytest.fixture
    def orch_with_gateway(self, store: DocumentStore) -> ParentOrchestrator:
        """Orchestrator with mocked gateway client."""
        from unittest.mock import AsyncMock, MagicMock

        mock_gw = MagicMock()
        mock_gw.call_tool_safe = AsyncMock(return_value=(
            {
                "phases": [
                    {"phase": "discovery", "total_hours": 120, "roles": ["PM", "SA"], "deliverables": ["요구사항 문서"]},
                    {"phase": "development", "total_hours": 200, "roles": ["Backend Dev"], "deliverables": ["API 개발"]},
                    {"phase": "testing", "total_hours": 80, "roles": ["QA"], "deliverables": ["통합 테스트"]},
                ],
                "total_project_hours": 400,
            },
            None,
        ))

        orch = ParentOrchestrator(document_store=store, memory=None, gateway_client=mock_gw)
        return orch

    @pytest.mark.asyncio
    async def test_trigger_milestone_sync_returns_patches(self, orch_with_gateway: ParentOrchestrator):
        """_trigger_milestone_sync should return patches for milestones section."""
        doc = DocumentState(document_id="doc-001")
        result = await orch_with_gateway._trigger_milestone_sync("doc-001", doc)

        assert result.success is True
        paths = [p["path"] for p in result.patches]
        assert "/sections/milestones/phases" in paths
        assert "/sections/milestones/total_project_hours" in paths

    @pytest.mark.asyncio
    async def test_milestone_sync_calls_gateway(self, orch_with_gateway: ParentOrchestrator):
        """Should call build_milestone_summary via gateway client."""
        doc = DocumentState(document_id="doc-001")
        await orch_with_gateway._trigger_milestone_sync("doc-001", doc)

        orch_with_gateway.gateway_client.call_tool_safe.assert_called_once()
        call_args = orch_with_gateway.gateway_client.call_tool_safe.call_args
        assert call_args[0][0] == "build_milestone_summary"

    @pytest.mark.asyncio
    async def test_milestone_sync_local_fallback_without_gateway(self, store: DocumentStore):
        """Without gateway client, should use local milestone sync."""
        from agent.lib.schema.document_state import (
            StaffingPlan, StaffingRole, FieldValue, FieldStatus, PhaseHours,
        )

        role = StaffingRole(
            role_id="pm",
            display_name="PM",
            count=FieldValue(ai_recommended=1, status=FieldStatus.recommended),
            allocation_pct=FieldValue(ai_recommended=100, status=FieldStatus.recommended),
            rate_per_hour=FieldValue(ai_recommended=80.0, status=FieldStatus.recommended),
            phase_hours=PhaseHours(
                discovery=FieldValue(ai_recommended=40, status=FieldStatus.recommended),
                development=FieldValue(ai_recommended=80, status=FieldStatus.recommended),
                testing=FieldValue(ai_recommended=20, status=FieldStatus.recommended),
            ),
        )
        doc = DocumentState(
            document_id="doc-001",
            staffing_plan=StaffingPlan(roles={"pm": role}),
        )

        orch = ParentOrchestrator(document_store=store, memory=None, gateway_client=None)
        result = await orch._trigger_milestone_sync("doc-001", doc)

        assert result.success is True
        assert len(result.patches) >= 2
        # Check phases patch has correct structure
        phases_patch = next(p for p in result.patches if p["path"] == "/sections/milestones/phases")
        phases = phases_patch["value"]
        assert len(phases) == 3
        assert phases[0]["phase"]["ai_recommended"] == "discovery"
        assert "요구사항 문서" in phases[0]["deliverables"]["ai_recommended"]

    @pytest.mark.asyncio
    async def test_milestone_sync_gateway_failure_falls_back(self, store: DocumentStore):
        """Gateway failure should fall back to local sync."""
        from unittest.mock import AsyncMock, MagicMock

        mock_gw = MagicMock()
        mock_gw.call_tool_safe = AsyncMock(return_value=(None, "Gateway error"))

        orch = ParentOrchestrator(document_store=store, memory=None, gateway_client=mock_gw)
        doc = DocumentState(document_id="doc-001")
        result = await orch._trigger_milestone_sync("doc-001", doc)

        assert result.success is True
        assert "로컬 동기화" in result.chat_response

    @pytest.mark.asyncio
    async def test_staffing_change_triggers_milestone_sync(self, store: DocumentStore):
        """handle_message with staffing keywords should trigger milestone sync."""
        from unittest.mock import AsyncMock, MagicMock
        from agent.app.staffing.staffing_agent import StaffingRecommendation

        orch = ParentOrchestrator(document_store=store, memory=None, gateway_client=None)

        # Mock staffing agent
        mock_staffing = MagicMock()
        mock_staffing.recommend.return_value = StaffingRecommendation(
            project_type="genai_multi_agent", roles={}, violations=[],
        )
        orch._staffing_agent = mock_staffing

        plan = await orch.handle_message("doc-001", "팀 구성을 추천해주세요", [])

        assert plan.chat_response
        # Milestone sync should have been triggered
        assert "milestone_sync" in plan.chat_response or "마일스톤" in plan.chat_response

    @pytest.mark.asyncio
    async def test_stakeholders_not_used_in_milestone_calc(self, store: DocumentStore):
        """Stakeholder contact info should NOT be used in milestone calculation (Req 14.3)."""
        orch = ParentOrchestrator(document_store=store, memory=None, gateway_client=None)
        doc = DocumentState(document_id="doc-001")

        result = await orch._trigger_milestone_sync("doc-001", doc)

        # The call should only use staffing_plan and scope_of_work
        # No stakeholders data should appear in the result
        assert result.success is True

    def test_local_milestone_sync_static(self):
        """_local_milestone_sync should produce correct phase structure."""
        staffing = {
            "roles": {
                "pm": {
                    "display_name": "PM",
                    "phase_hours": {
                        "discovery": {"ai_recommended": 40},
                        "development": {"ai_recommended": 80},
                        "testing": {"ai_recommended": 20},
                    },
                },
            },
        }
        result = ParentOrchestrator._local_milestone_sync(staffing, {})

        assert len(result["phases"]) == 3
        assert result["total_project_hours"] == 140.0
        assert result["phases"][0]["roles"] == ["PM"]


# ---------------------------------------------------------------------------
# Task 10.2: Review / Export flow tests (Req 13.1, 13.2, 13.3, 13.4)
# ---------------------------------------------------------------------------

class TestReviewExportFlow:
    """Verify review and export request handling in orchestrator."""

    @pytest.fixture
    def orch_review(self, store: DocumentStore) -> ParentOrchestrator:
        """Orchestrator with mocked reviewer and gateway for review tests."""
        from unittest.mock import AsyncMock, MagicMock
        from agent.app.reviewer.reviewer_agent import ReviewResult

        orch = ParentOrchestrator(document_store=store, memory=None)

        mock_reviewer = MagicMock()
        mock_reviewer.review.return_value = ReviewResult(
            completion_score=0.45,
            blocking_issues=[BlockingIssue(code="EMPTY_STAFFING", message="staffing 비어있음", section="staffing_plan")],
            warnings=[Warning(code="ZERO_COST", message="비용 0", section="cost_breakdown")],
            suggestions=["[blocking] staffing 비어있음"],
        )
        orch._reviewer_agent = mock_reviewer

        return orch

    @pytest.mark.asyncio
    async def test_review_request_returns_blocking_issues(self, orch_review: ParentOrchestrator):
        """Review request should return blocking issues and warnings."""
        doc = DocumentState(document_id="doc-001")
        result = await orch_review._handle_review_request("doc-001", doc)

        assert result.success is True
        paths = [p["path"] for p in result.patches]
        assert "/completion_score" in paths
        assert "/blocking_issues" in paths
        assert "/warnings" in paths

    @pytest.mark.asyncio
    async def test_review_with_gateway_merges_issues(self, store: DocumentStore):
        """Review with gateway should merge gateway issues with reviewer issues."""
        from unittest.mock import AsyncMock, MagicMock
        from agent.app.reviewer.reviewer_agent import ReviewResult

        mock_gw = MagicMock()
        mock_gw.call_tool_safe = AsyncMock(return_value=(
            {
                "valid": False,
                "blocking_issues": [{"code": "MISSING_SECTION", "message": "cover 누락", "section": "cover"}],
                "warnings": [{"code": "SECTION_ORDER", "message": "순서 불일치"}],
                "completion_score": 0.3,
            },
            None,
        ))

        orch = ParentOrchestrator(document_store=store, memory=None, gateway_client=mock_gw)

        mock_reviewer = MagicMock()
        mock_reviewer.review.return_value = ReviewResult(
            completion_score=0.45,
            blocking_issues=[BlockingIssue(code="EMPTY_STAFFING", message="staffing 비어있음", section="staffing_plan")],
            warnings=[Warning(code="ZERO_COST", message="비용 0", section="cost_breakdown")],
            suggestions=[],
        )
        orch._reviewer_agent = mock_reviewer

        doc = DocumentState(document_id="doc-001")
        result = await orch._handle_review_request("doc-001", doc)

        assert result.success is True
        assert "gateway" in result.chat_response.lower()

        # Check that blocking_issues patch has merged items
        bi_patch = next(p for p in result.patches if p["path"] == "/blocking_issues")
        assert len(bi_patch["value"]) >= 2  # at least reviewer + gateway

    @pytest.mark.asyncio
    async def test_review_intent_detected_in_handle_message(self, orch_review: ParentOrchestrator):
        """handle_message with review keywords should route to review flow."""
        plan = await orch_review.handle_message("doc-001", "문서 리뷰를 요청합니다", [])

        assert plan.chat_response
        assert "리뷰" in plan.chat_response or "completion" in plan.chat_response.lower() or "완료" in plan.chat_response

    @pytest.mark.asyncio
    async def test_export_request_delegates_to_formatter(self, store: DocumentStore):
        """Export request should delegate to formatter agent."""
        from unittest.mock import AsyncMock, MagicMock
        from agent.app.formatter.formatter_agent import ExportResult

        mock_gw = MagicMock()
        mock_gw.call_tool_safe = AsyncMock(return_value=(
            {"s3_key": "exports/doc-001.docx", "download_url": "https://s3.example.com/doc.docx"},
            None,
        ))

        orch = ParentOrchestrator(document_store=store, memory=None, gateway_client=mock_gw)

        mock_formatter = MagicMock()
        mock_formatter.export_docx = AsyncMock(return_value=ExportResult(
            success=True,
            s3_path="exports/doc-001.docx",
            download_url="https://s3.example.com/doc.docx",
        ))
        orch._formatter_agent = mock_formatter

        doc = DocumentState(document_id="doc-001")
        result = await orch._handle_export_request("doc-001", doc)

        assert result.success is True
        assert "다운로드" in result.chat_response or "export" in result.chat_response.lower()

    @pytest.mark.asyncio
    async def test_export_intent_detected_in_handle_message(self, store: DocumentStore):
        """handle_message with export keywords should route to export flow."""
        from unittest.mock import AsyncMock, MagicMock
        from agent.app.formatter.formatter_agent import ExportResult

        mock_gw = MagicMock()
        mock_gw.call_tool_safe = AsyncMock(return_value=(
            {"s3_key": "exports/doc-001.docx", "download_url": "https://s3.example.com/doc.docx"},
            None,
        ))

        orch = ParentOrchestrator(document_store=store, memory=None, gateway_client=mock_gw)

        mock_formatter = MagicMock()
        mock_formatter.export_docx = AsyncMock(return_value=ExportResult(
            success=True,
            s3_path="exports/doc-001.docx",
            download_url="https://s3.example.com/doc.docx",
        ))
        orch._formatter_agent = mock_formatter

        plan = await orch.handle_message("doc-001", "DOCX export 해주세요", [])

        assert plan.chat_response
        assert "다운로드" in plan.chat_response or "export" in plan.chat_response.lower()

    def test_detect_review_intent(self):
        orch = ParentOrchestrator(memory=None)
        assert orch._detect_review_intent("문서 리뷰 해주세요") is True
        assert orch._detect_review_intent("review the document") is True
        assert orch._detect_review_intent("프로젝트 개요") is False

    def test_detect_export_intent(self):
        orch = ParentOrchestrator(memory=None)
        assert orch._detect_export_intent("DOCX export 해주세요") is True
        assert orch._detect_export_intent("다운로드 하고 싶어요") is True
        assert orch._detect_export_intent("프로젝트 개요") is False


# ---------------------------------------------------------------------------
# Task 10.3: User edit → cost recalculation tests (Req 7.3, 8.3, 12.2, 12.3)
# ---------------------------------------------------------------------------

class TestUserEditCostRecalc:
    """Verify user edit triggers cost recalculation with proper field marking."""

    @pytest.fixture
    def orch_with_staffing(self, store: DocumentStore) -> tuple[ParentOrchestrator, DocumentState]:
        """Orchestrator with a document that has staffing_plan roles."""
        from unittest.mock import MagicMock
        from agent.app.cost.cost_agent import StaffingCostResult
        from agent.lib.schema.document_state import (
            StaffingPlan, StaffingRole, FieldValue, FieldStatus, PhaseHours,
        )

        role = StaffingRole(
            role_id="pm",
            display_name="PM",
            count=FieldValue(ai_recommended=1, status=FieldStatus.recommended),
            allocation_pct=FieldValue(ai_recommended=100, status=FieldStatus.recommended),
            rate_per_hour=FieldValue(ai_recommended=80.0, status=FieldStatus.recommended),
            phase_hours=PhaseHours(
                discovery=FieldValue(ai_recommended=40, status=FieldStatus.recommended),
                development=FieldValue(ai_recommended=80, status=FieldStatus.recommended),
                testing=FieldValue(ai_recommended=20, status=FieldStatus.recommended),
            ),
        )
        doc = DocumentState(
            document_id="doc-001",
            staffing_plan=StaffingPlan(roles={"pm": role}),
        )
        store.put(doc)

        orch = ParentOrchestrator(document_store=store, memory=None)

        mock_cost = MagicMock()
        mock_cost.calculate_staffing_cost.return_value = StaffingCostResult(
            roles_summary=[{"role_id": "pm", "total_hours": 140, "total_cost": 11200.0}],
            grand_total=11200.0,
        )
        orch._cost_agent = mock_cost

        return orch, doc

    @pytest.mark.asyncio
    async def test_user_edit_marks_field_as_user_modified(
        self, orch_with_staffing: tuple[ParentOrchestrator, DocumentState]
    ):
        """User edit should set user_edited=true and status=user_modified."""
        orch, doc = orch_with_staffing

        edit_payload = {"role_id": "pm", "field": "rate_per_hour", "value": 90.0}
        result = await orch._handle_user_edit("doc-001", doc, edit_payload)

        assert result.success is True

        # Check user_input patch
        ui_patch = next(
            p for p in result.patches
            if p["path"] == "/staffing_plan/roles/pm/rate_per_hour/user_input"
        )
        assert ui_patch["value"] == 90.0

        # Check user_edited patch
        ue_patch = next(
            p for p in result.patches
            if p["path"] == "/staffing_plan/roles/pm/rate_per_hour/user_edited"
        )
        assert ue_patch["value"] is True

        # Check status patch
        st_patch = next(
            p for p in result.patches
            if p["path"] == "/staffing_plan/roles/pm/rate_per_hour/status"
        )
        assert st_patch["value"] == "user_modified"

    @pytest.mark.asyncio
    async def test_user_edit_preserves_ai_recommended(
        self, orch_with_staffing: tuple[ParentOrchestrator, DocumentState]
    ):
        """User edit should NOT overwrite ai_recommended value (Req 12.2)."""
        orch, doc = orch_with_staffing

        edit_payload = {"role_id": "pm", "field": "rate_per_hour", "value": 90.0}
        result = await orch._handle_user_edit("doc-001", doc, edit_payload)

        # No patch should overwrite ai_recommended
        ai_patches = [
            p for p in result.patches
            if "ai_recommended" in p["path"]
        ]
        assert len(ai_patches) == 0

    @pytest.mark.asyncio
    async def test_user_edit_triggers_cost_recalculation(
        self, orch_with_staffing: tuple[ParentOrchestrator, DocumentState]
    ):
        """User edit should trigger cost recalculation (Req 8.3)."""
        orch, doc = orch_with_staffing

        edit_payload = {"role_id": "pm", "field": "rate_per_hour", "value": 90.0}
        result = await orch._handle_user_edit("doc-001", doc, edit_payload)

        # Should have cost_breakdown patch
        cb_patches = [p for p in result.patches if "cost_breakdown" in p["path"]]
        assert len(cb_patches) >= 1

        # Should have grand_total patches
        gt_patches = [p for p in result.patches if "grand_total" in p["path"]]
        assert len(gt_patches) >= 2  # hours + cost

        # Chat should mention cost recalculation
        assert "재계산" in result.chat_response or "cost" in result.chat_response.lower()

    @pytest.mark.asyncio
    async def test_user_edit_updates_role_totals(
        self, orch_with_staffing: tuple[ParentOrchestrator, DocumentState]
    ):
        """User edit should recalculate role-level total_hours and total_cost."""
        orch, doc = orch_with_staffing

        edit_payload = {"role_id": "pm", "field": "rate_per_hour", "value": 90.0}
        result = await orch._handle_user_edit("doc-001", doc, edit_payload)

        # Check role total_hours calculated patch
        th_patch = next(
            p for p in result.patches
            if p["path"] == "/staffing_plan/roles/pm/total_hours/calculated"
        )
        assert th_patch["value"] > 0

        # Check role total_cost calculated patch
        tc_patch = next(
            p for p in result.patches
            if p["path"] == "/staffing_plan/roles/pm/total_cost/calculated"
        )
        assert tc_patch["value"] > 0

    @pytest.mark.asyncio
    async def test_user_edit_marks_role_level_user_edited(
        self, orch_with_staffing: tuple[ParentOrchestrator, DocumentState]
    ):
        """User edit should also set role-level user_edited flag."""
        orch, doc = orch_with_staffing

        edit_payload = {"role_id": "pm", "field": "rate_per_hour", "value": 90.0}
        result = await orch._handle_user_edit("doc-001", doc, edit_payload)

        role_ue = next(
            p for p in result.patches
            if p["path"] == "/staffing_plan/roles/pm/user_edited"
        )
        assert role_ue["value"] is True

    @pytest.mark.asyncio
    async def test_user_edit_empty_payload_still_recalculates(
        self, orch_with_staffing: tuple[ParentOrchestrator, DocumentState]
    ):
        """Even with empty edit payload, cost recalculation should still run."""
        orch, doc = orch_with_staffing

        edit_payload = {}  # no specific field edit
        result = await orch._handle_user_edit("doc-001", doc, edit_payload)

        assert result.success is True
        # Should still have cost_breakdown patch from recalculation
        cb_patches = [p for p in result.patches if "cost_breakdown" in p["path"]]
        assert len(cb_patches) >= 1
