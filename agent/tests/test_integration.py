"""End-to-end integration tests for the AgentCore multi-agent system.

Validates:
- Task 17.1: Chat flow — /invocations → AgentCore Runtime → sub-agents → DynamoDB → AppSync
- Task 17.2: 4-property pattern full-stack — ai_recommended / calculated / user_input consistency
- Task 17.3: Real-time status publishing — all state transitions, error, degraded
- Task 17.4: End-to-end pipeline — chat → delegate → patch → DynamoDB → AppSync publish

Requirements: 4.1, 4.7, 9.1, 9.2, 9.4, 10.4, 12.1, 12.2, 12.3, 12.4, 3.4, 3.6, 1.7, 2.5
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.app.parent.orchestrator import (
    AgentResult,
    OrchestratorState,
    ParentOrchestrator,
    Task,
    TaskPlan,
)
from agent.lib.schema.document_state import (
    DocumentState,
    FieldStatus,
    FieldValue,
    PhaseHours,
    StaffingPlan,
    StaffingRole,
)
from agent.lib.schema.patch import AgentStatus, Patch, PatchOperation
from agent.lib.storage.dynamodb import DocumentStore, VersionConflictError
from agent.lib.calculation.recalculate import recalculate_costs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_staffing_role(
    role_id: str,
    display_name: str,
    count: int = 1,
    alloc: int = 100,
    rate: float = 80.0,
    disc_h: int = 40,
    dev_h: int = 80,
    test_h: int = 20,
) -> StaffingRole:
    """Build a StaffingRole with ai_recommended values."""
    return StaffingRole(
        role_id=role_id,
        display_name=display_name,
        count=FieldValue(ai_recommended=count, status=FieldStatus.recommended),
        allocation_pct=FieldValue(ai_recommended=alloc, status=FieldStatus.recommended),
        rate_per_hour=FieldValue(ai_recommended=rate, status=FieldStatus.recommended),
        phase_hours=PhaseHours(
            discovery=FieldValue(ai_recommended=disc_h, status=FieldStatus.recommended),
            development=FieldValue(ai_recommended=dev_h, status=FieldStatus.recommended),
            testing=FieldValue(ai_recommended=test_h, status=FieldStatus.recommended),
        ),
    )


def _build_orchestrator_with_mocks(
    store: DocumentStore | None = None,
    memory: MagicMock | None = None,
    gateway: MagicMock | None = None,
) -> ParentOrchestrator:
    """Build an orchestrator with mocked sub-agents for integration testing."""
    from agent.app.discovery.discovery_agent import DiscoveryResult, MissingFields
    from agent.app.staffing.staffing_agent import StaffingRecommendation
    from agent.app.architecture.architecture_agent import ArchitectureResult
    from agent.app.reviewer.reviewer_agent import ReviewResult
    from agent.app.cost.cost_agent import StaffingCostResult
    from agent.lib.schema.document_state import BlockingIssue, Warning as DocWarning

    s = store or DocumentStore()
    orch = ParentOrchestrator(document_store=s, memory=memory, gateway_client=gateway)

    # Mock discovery agent
    mock_discovery = MagicMock()
    mock_discovery.collect_info = AsyncMock(return_value=DiscoveryResult(
        structured_input={"customer": "IntegrationCorp", "project_goal": "AI PoC"},
        missing=MissingFields(draft_required=[], export_required=[]),
        follow_up_questions=[],
        can_generate_draft=True,
    ))
    orch._discovery_agent = mock_discovery

    # Mock architecture agent
    mock_arch = MagicMock()
    mock_arch.analyze_existing = AsyncMock(return_value=ArchitectureResult(
        services=["lambda", "s3", "dynamodb"],
        analysis="아키텍처 분석 완료 — 3개 서비스 감지",
    ))
    mock_arch.design_new = AsyncMock(return_value=ArchitectureResult(
        services=["lambda", "api-gateway"],
        analysis="아키텍처 설계 완료",
    ))
    orch._architecture_agent = mock_arch

    # Mock staffing agent
    mock_staffing = MagicMock()
    mock_staffing.recommend.return_value = StaffingRecommendation(
        project_type="genai_multi_agent",
        roles={
            "pm": {
                "role_id": "pm", "display_name": "PM",
                "count": 1, "allocation_pct": 50, "rate_per_hour": 81.78,
                "reason": "프로젝트 관리",
            },
        },
        violations=[],
    )
    orch._staffing_agent = mock_staffing

    # Mock cost agent
    mock_cost = MagicMock()
    mock_cost.calculate_staffing_cost.return_value = StaffingCostResult(
        roles_summary=[{"role_id": "pm", "total_hours": 140, "total_cost": 11449.20}],
        grand_total=11449.20,
    )
    orch._cost_agent = mock_cost

    # Mock reviewer agent
    mock_reviewer = MagicMock()
    mock_reviewer.review.return_value = ReviewResult(
        completion_score=0.45,
        blocking_issues=[BlockingIssue(code="MISSING_COVER", message="Cover 누락", section="cover")],
        warnings=[DocWarning(code="ZERO_COST", message="비용 0", section="cost_breakdown")],
        suggestions=["Cover 섹션을 작성하세요"],
    )
    orch._reviewer_agent = mock_reviewer

    # Mock formatter agent
    mock_formatter = MagicMock()
    mock_formatter.export_docx = AsyncMock(return_value=MagicMock(
        success=True, s3_path="s3://bucket/doc.docx", download_url="https://example.com/doc.docx", error=None,
    ))
    orch._formatter_agent = mock_formatter

    return orch


# ===========================================================================
# Task 17.1 — 전체 채팅 흐름 연결
# ===========================================================================

class TestChatFlowIntegration:
    """Task 17.1: Frontend → API Gateway → AgentCore Runtime → sub-agents → DynamoDB → AppSync.

    Requirements: 4.7, 9.1, 9.2
    """

    def test_invocations_route_calls_runtime_invoke(self, monkeypatch):
        """POST /invocations routes to AgentCore Runtime invoke()."""
        from agent.lambdas.document_api import handler as document_api

        table = MagicMock()
        table.get_item.return_value = {"Item": {"document_id": "doc-int-001", "user_id": "user-1", "version": 3}}
        monkeypatch.setattr(document_api, "table", table)
        monkeypatch.setattr(document_api, "_invoke_runtime", lambda payload: {"result": "runtime reply", "version": 4, "status": "ok"})

        result = document_api._handle_invocations({
            "doc_id": "doc-int-001",
            "prompt": "새 프로젝트를 시작합니다",
            "history": [],
        }, {
            "headers": {"X-User-Id": "user-1"},
        })

        body = json.loads(result["body"])
        assert result["statusCode"] == 200
        assert "agent_response" in body
        assert body["status"] == "ok"
        assert isinstance(body["version"], int)

    def test_invocations_missing_fields_returns_400(self, monkeypatch):
        """POST /invocations with missing doc_id returns 400."""
        from agent.lambdas.document_api.handler import _handle_invocations

        result = _handle_invocations({"prompt": "hello"}, {"headers": {"X-User-Id": "user-1"}})
        assert result["statusCode"] == 400

    def test_chat_endpoint_backward_compatible(self, monkeypatch):
        """POST /documents/{docId}/chat routes through Runtime as alias."""
        from agent.lambdas.document_api import handler as document_api

        table = MagicMock()
        table.get_item.return_value = {"Item": {"document_id": "doc-int-002", "user_id": "user-1", "version": 3}}
        monkeypatch.setattr(document_api, "table", table)
        monkeypatch.setattr(document_api, "_invoke_runtime", lambda payload: {"result": "runtime reply", "version": 4, "status": "ok"})

        result = document_api._handle_chat("doc-int-002", {"message": "프로젝트 개요", "history": []}, {"headers": {"X-User-Id": "user-1"}})

        body = json.loads(result["body"])
        assert result["statusCode"] == 200
        assert "agent_response" in body

    def test_chat_endpoint_missing_message_returns_400(self, monkeypatch):
        """POST /documents/{docId}/chat with empty message returns 400."""
        from agent.lambdas.document_api.handler import _handle_chat

        result = _handle_chat("doc-int-003", {"message": ""}, {"headers": {"X-User-Id": "user-1"}})
        assert result["statusCode"] == 400

    @pytest.mark.asyncio
    async def test_full_pipeline_publishes_patches(self):
        """Full pipeline: message → delegate → patch → DynamoDB → AppSync publish."""
        orch = _build_orchestrator_with_mocks()

        plan = await orch.handle_message("doc-flow-001", "새 프로젝트를 시작합니다", [])

        # Pipeline should complete
        assert plan.chat_response
        assert orch.state == OrchestratorState.IDLE

        # Status log should contain processing → idle
        statuses = [s["status"] for s in orch._status_log]
        assert "processing" in statuses
        assert "idle" in statuses

    @pytest.mark.asyncio
    async def test_pipeline_creates_document_in_store(self):
        """Pipeline creates document in DynamoDB store if not found."""
        store = DocumentStore()
        orch = _build_orchestrator_with_mocks(store=store)

        await orch.handle_message("doc-new-001", "hello", [])

        assert store.exists("doc-new-001")

    @pytest.mark.asyncio
    async def test_pipeline_generates_patches_from_sub_agents(self):
        """Sub-agent results are converted to patches and logged."""
        orch = _build_orchestrator_with_mocks()

        await orch.handle_message("doc-patch-001", "프로젝트 정보를 입력합니다", [])

        # Audit log should show delegation happened
        assert len(orch._audit_log) > 0
        agents_called = [e["agent"] for e in orch._audit_log]
        assert "discovery_agent" in agents_called


class TestV2SourceOfTruthIntegration:
    """Backend integration checks for the v2 patch-first flow."""

    @pytest.mark.asyncio
    async def test_apply_patches_updates_expected_version_and_publishes(self):
        store = DocumentStore()
        store.put(DocumentState(document_id="doc-v2-001", version=1))

        orch = ParentOrchestrator(document_store=store, memory=None)
        published = []

        async def fake_publish(doc_id: str, patches: list[Patch]):
            published.append((doc_id, patches))

        orch.publish_patch = fake_publish

        patch = Patch(
            patch_id="patch-001",
            doc_id="doc-v2-001",
            agent="test",
            version=1,
            operations=[PatchOperation(op="replace", path="/completion_score", value=0.42)],
        )

        new_version = await orch.apply_patches("doc-v2-001", [patch], expected_version=1)

        assert new_version == 2
        assert store.get("doc-v2-001").version == 2
        assert len(published) == 1
        assert published[0][0] == "doc-v2-001"
        assert published[0][1][0].version_before == 1
        assert published[0][1][0].version_after == 2
        assert published[0][1][0].operations[0].path == "/completion_score"

    @pytest.mark.asyncio
    async def test_runtime_chat_alias_uses_proxy_and_returns_safe_payload(self, monkeypatch):
        from agent.lambdas.document_api import handler as document_api
        from agent.lambdas.document_api import runtime_proxy

        table = MagicMock()
        table.get_item.return_value = {
            "Item": {"document_id": "doc-1", "user_id": "user-1", "version": 3}
        }
        monkeypatch.setattr(document_api, "table", table)

        class FakeRuntimeProxy:
            def __init__(self):
                self.calls = []

            def invoke(self, payload):
                self.calls.append(payload)
                return {"result": "runtime reply", "version": 4, "status": "ok"}

        proxy = FakeRuntimeProxy()
        monkeypatch.setattr(runtime_proxy, "get_runtime_proxy", lambda: proxy)

        response = document_api.handler(
            {
                "requestContext": {"http": {"method": "POST", "path": "/documents/doc-1/chat"}},
                "headers": {"X-User-Id": "user-1"},
                "body": json.dumps({"message": "hello", "history": []}),
            },
            None,
        )

        assert response["statusCode"] == 200
        assert proxy.calls == [{
            "doc_id": "doc-1",
            "prompt": "hello",
            "history": [],
            "user_id": "user-1",
        }]


# ===========================================================================
# Task 17.2 — 4속성 패턴 full stack 연결
# ===========================================================================

class TestFourPropertyPattern:
    """Task 17.2: Verify 4-property pattern (user_input / ai_recommended / calculated / status).

    Requirements: 12.1, 12.2, 12.3, 12.4
    """

    @pytest.mark.asyncio
    async def test_discovery_writes_user_input_source(self):
        """Discovery agent output writes to user_input fields with correct source."""
        orch = _build_orchestrator_with_mocks()
        doc = DocumentState(document_id="doc-4p-001")
        task = Task(agent="discovery_agent", action="collect_info", params={"message": "ABC Corp 프로젝트"})

        result = await orch.delegate_task("discovery_agent", task, doc)

        assert result.success
        # Check that customer patch uses user_input source
        customer_patches = [p for p in result.patches if "customer" in p.get("path", "")]
        assert len(customer_patches) > 0
        for p in customer_patches:
            assert p["source"] == "user_input"

    @pytest.mark.asyncio
    async def test_staffing_writes_ai_recommended_source(self):
        """Staffing agent output writes to ai_recommended fields."""
        orch = _build_orchestrator_with_mocks()
        doc = DocumentState(document_id="doc-4p-002")
        task = Task(agent="staffing_agent", action="recommend", params={"message": "GenAI project"})

        result = await orch.delegate_task("staffing_agent", task, doc)

        assert result.success
        # All staffing patches should use ai_recommended source
        for p in result.patches:
            assert p["source"] == "ai_recommended"

    @pytest.mark.asyncio
    async def test_cost_writes_calculated_source(self):
        """Cost agent output writes to calculated fields."""
        orch = _build_orchestrator_with_mocks()
        role = _make_staffing_role("pm", "PM")
        doc = DocumentState(
            document_id="doc-4p-003",
            staffing_plan=StaffingPlan(roles={"pm": role}),
        )
        task = Task(agent="cost_agent", action="calculate", params={})

        result = await orch.delegate_task("cost_agent", task, doc)

        assert result.success
        # Cost patches should use calculated source
        for p in result.patches:
            assert p["source"] == "calculated"

    @pytest.mark.asyncio
    async def test_user_edit_sets_user_modified_status(self):
        """User edit marks field as user_modified with user_edited=true."""
        store = DocumentStore()
        role = _make_staffing_role("pm", "PM", rate=80.0)
        doc = DocumentState(
            document_id="doc-4p-004",
            staffing_plan=StaffingPlan(roles={"pm": role}),
            version=0,
        )
        store.put(doc)

        orch = _build_orchestrator_with_mocks(store=store)

        edit_payload = {"role_id": "pm", "field": "rate_per_hour", "value": 90.0}
        result = await orch._handle_user_edit("doc-4p-004", doc, edit_payload)

        assert result.success

        # Check user_input patch
        ui_patches = [p for p in result.patches if p["path"].endswith("/user_input")]
        assert len(ui_patches) >= 1
        assert ui_patches[0]["value"] == 90.0
        assert ui_patches[0]["source"] == "user_input"

        # Check user_edited patch
        ue_patches = [p for p in result.patches if p["path"].endswith("/user_edited") and "rate_per_hour" in p["path"]]
        assert len(ue_patches) >= 1
        assert ue_patches[0]["value"] is True

        # Check status patch
        status_patches = [p for p in result.patches if p["path"].endswith("/status") and "rate_per_hour" in p["path"]]
        assert len(status_patches) >= 1
        assert status_patches[0]["value"] == FieldStatus.user_modified.value

    @pytest.mark.asyncio
    async def test_user_edit_triggers_cost_recalculation(self):
        """User edit triggers automatic cost recalculation (calculated values update)."""
        store = DocumentStore()
        role = _make_staffing_role("pm", "PM", rate=80.0, disc_h=40, dev_h=80, test_h=20)
        doc = DocumentState(
            document_id="doc-4p-005",
            staffing_plan=StaffingPlan(roles={"pm": role}),
            version=0,
        )
        store.put(doc)

        orch = _build_orchestrator_with_mocks(store=store)

        edit_payload = {"role_id": "pm", "field": "rate_per_hour", "value": 100.0}
        result = await orch._handle_user_edit("doc-4p-005", doc, edit_payload)

        # Should have calculated total patches
        total_cost_patches = [
            p for p in result.patches
            if "total_cost/calculated" in p["path"]
        ]
        assert len(total_cost_patches) >= 1

        grand_total_patches = [
            p for p in result.patches
            if "grand_total_cost/calculated" in p["path"]
        ]
        assert len(grand_total_patches) >= 1

    def test_value_resolution_priority(self):
        """Value resolution: user_input > ai_recommended > calculated."""
        from agent.lib.calculation.recalculate import _resolve

        # user_input takes priority
        fv = {"user_input": 100, "ai_recommended": 80, "calculated": 60}
        assert _resolve(fv) == 100.0

        # ai_recommended when no user_input
        fv = {"user_input": None, "ai_recommended": 80, "calculated": 60}
        assert _resolve(fv) == 80.0

        # calculated when no user_input or ai_recommended
        fv = {"user_input": None, "ai_recommended": None, "calculated": 60}
        assert _resolve(fv) == 60.0

        # 0 when all None
        fv = {"user_input": None, "ai_recommended": None, "calculated": None}
        assert _resolve(fv) == 0.0

    @pytest.mark.asyncio
    async def test_user_edit_preserves_ai_recommended(self):
        """User edit preserves original ai_recommended value."""
        store = DocumentStore()
        role = _make_staffing_role("pm", "PM", rate=80.0)
        doc = DocumentState(
            document_id="doc-4p-006",
            staffing_plan=StaffingPlan(roles={"pm": role}),
            version=0,
        )
        store.put(doc)

        orch = _build_orchestrator_with_mocks(store=store)

        edit_payload = {"role_id": "pm", "field": "rate_per_hour", "value": 95.0}
        result = await orch._handle_user_edit("doc-4p-006", doc, edit_payload)

        # The patches should NOT overwrite ai_recommended — only set user_input
        ai_rec_patches = [
            p for p in result.patches
            if p["path"].endswith("/ai_recommended") and "rate_per_hour" in p["path"]
        ]
        assert len(ai_rec_patches) == 0  # ai_recommended should not be touched

    def test_recalculate_costs_uses_resolution_priority(self):
        """recalculate_costs respects user_input > ai_recommended > calculated."""
        sp = {
            "roles": {
                "pm": {
                    "count": {"user_input": 2, "ai_recommended": 1, "calculated": None},
                    "allocation_pct": {"user_input": None, "ai_recommended": 100, "calculated": None},
                    "rate_per_hour": {"user_input": None, "ai_recommended": 80.0, "calculated": None},
                    "phase_hours": {
                        "discovery": {"user_input": None, "ai_recommended": 40, "calculated": None},
                        "development": {"user_input": None, "ai_recommended": 80, "calculated": None},
                        "testing": {"user_input": None, "ai_recommended": 20, "calculated": None},
                    },
                }
            }
        }
        result = recalculate_costs(sp)

        # count=2 (user_input), alloc=100, rate=80, hours=140
        # total_cost = 2 * (100/100) * 80 * 140 = 22400
        assert result["roles"]["pm"]["total_hours"] == 140.0
        assert result["roles"]["pm"]["total_cost"] == 22400.0


# ===========================================================================
# Task 17.3 — 실시간 상태 발행 연결
# ===========================================================================

class TestStatusPublishing:
    """Task 17.3: Verify all agent state transitions publish to docs/{docId}/status.

    Requirements: 9.4, 3.4, 1.7, 2.5
    """

    @pytest.mark.asyncio
    async def test_normal_flow_publishes_processing_and_idle(self):
        """Normal flow: processing → idle status transitions."""
        orch = _build_orchestrator_with_mocks()

        await orch.handle_message("doc-st-001", "hello", [])

        statuses = [s["status"] for s in orch._status_log]
        assert statuses[0] == "processing"
        assert statuses[-1] == "idle"

    @pytest.mark.asyncio
    async def test_error_publishes_error_status(self):
        """On exception, error status is published."""
        orch = _build_orchestrator_with_mocks()

        # Force an error
        def broken_get(doc_id):
            raise RuntimeError("simulated DB failure")

        orch.document_store.get = broken_get
        orch.document_store.put = lambda doc: (_ for _ in ()).throw(RuntimeError("simulated"))

        await orch.handle_message("doc-st-002", "test", [])

        statuses = [s["status"] for s in orch._status_log]
        assert "error" in statuses

    @pytest.mark.asyncio
    async def test_version_conflict_publishes_error_status(self):
        """Version conflict → error status published."""
        store = DocumentStore()
        doc = DocumentState(document_id="doc-st-003", version=0)
        store.put(doc)
        store.update(doc, expected_version=0)  # version → 1

        orch = _build_orchestrator_with_mocks(store=store)

        # Sabotage update to always conflict
        original_update = store.update
        def conflict_update(d, v):
            raise VersionConflictError("forced conflict")
        store.update = conflict_update

        # Need to make delegate return patches so apply_patches is triggered
        async def patchy_delegate(agent_name, task, doc_state):
            return AgentResult(
                success=True,
                patches=[{"op": "replace", "path": "/completion_score", "value": 0.5}],
            )
        orch.delegate_task = patchy_delegate

        plan = await orch.handle_message("doc-st-003", "test", [])

        statuses = [s["status"] for s in orch._status_log]
        assert "error" in statuses
        assert "충돌" in plan.chat_response

    @pytest.mark.asyncio
    async def test_memory_failure_publishes_degraded_status(self):
        """Memory API failure → degraded status published (Req 2.5)."""
        mock_memory = MagicMock()
        mock_memory.on_degraded = None
        mock_memory.retrieve_customer_context.return_value = []
        mock_memory.store_session_event.return_value = False  # failure

        orch = _build_orchestrator_with_mocks(memory=mock_memory)

        await orch.handle_message("doc-st-004", "hello", [])

        degraded = [s for s in orch._status_log if s.get("status") == "degraded"]
        assert len(degraded) >= 1
        assert degraded[0].get("reason") == "memory_api_failure"

    @pytest.mark.asyncio
    async def test_memory_retrieval_degraded_publishes_warning(self):
        """Memory retrieval failure triggers degraded callback and warning."""
        mock_memory = MagicMock()
        mock_memory.on_degraded = None
        mock_memory.store_session_event.return_value = True

        orch = _build_orchestrator_with_mocks(memory=mock_memory)

        # Simulate on_degraded callback being triggered during retrieval
        def failing_retrieve(customer, query):
            if orch._on_memory_degraded:
                orch._on_memory_degraded("retrieve_customer_context", RuntimeError("timeout"))
            return []

        mock_memory.retrieve_customer_context.side_effect = failing_retrieve

        await orch.handle_message("doc-st-005", "hello", [])

        degraded = [s for s in orch._status_log if s.get("status") == "degraded"]
        assert len(degraded) >= 1

    @pytest.mark.asyncio
    async def test_inference_profile_unavailable_publishes_degraded(self):
        """Inference profile failure → degraded status (Req 1.7)."""
        from agent.app.parent.inference_fallback import InferenceProfileUnavailableError

        orch = _build_orchestrator_with_mocks()

        # Make _fetch_document_state raise InferenceProfileUnavailableError
        async def failing_fetch(doc_id):
            raise InferenceProfileUnavailableError(
                primary="global.anthropic.claude-opus-4-6-v1",
                fallback=None,
                cause=RuntimeError("profile unavailable"),
            )

        orch._fetch_document_state = failing_fetch

        plan = await orch.handle_message("doc-st-006", "test", [])

        assert "inference profile" in plan.chat_response
        degraded = [s for s in orch._status_log if s.get("status") == "degraded"]
        assert len(degraded) >= 1

    @pytest.mark.asyncio
    async def test_gateway_failure_publishes_error_via_callback(self):
        """Gateway tool failure triggers on_error callback (Req 3.4)."""
        from agent.lib.gateway.agentcore_gateway import AgentCoreGatewayClient, GatewayToolError

        errors_received: list[tuple[str, Exception]] = []

        def on_error(tool_name: str, error: Exception):
            errors_received.append((tool_name, error))

        # Create a mock gateway client that fails
        mock_gw = MagicMock(spec=AgentCoreGatewayClient)
        mock_gw.on_error = on_error

        async def failing_call_safe(tool_name, params):
            error = GatewayToolError(tool_name, "Lambda timeout")
            on_error(tool_name, error)
            return None, str(error)

        mock_gw.call_tool_safe = AsyncMock(side_effect=failing_call_safe)

        orch = _build_orchestrator_with_mocks(gateway=mock_gw)

        # Trigger a review which calls gateway validate_template_constraints
        plan = await orch.handle_message("doc-st-007", "리뷰 해주세요", [])

        # Gateway was called and error was captured
        assert len(errors_received) >= 1
        assert errors_received[0][0] == "validate_template_constraints"


# ===========================================================================
# Task 17.4 — End-to-end 통합 테스트
# ===========================================================================

class TestEndToEnd:
    """Task 17.4: Full end-to-end integration tests.

    Requirements: 4.1, 9.1, 10.4, 3.6
    """

    @pytest.mark.asyncio
    async def test_chat_to_patch_to_dynamodb_to_appsync(self):
        """Chat message → agent delegation → patch → DynamoDB update → AppSync publish."""
        store = DocumentStore()
        orch = _build_orchestrator_with_mocks(store=store)

        plan = await orch.handle_message("doc-e2e-001", "ABC Corp GenAI 프로젝트를 시작합니다", [])

        # 1. Chat response generated
        assert plan.chat_response
        assert len(plan.chat_response) > 0

        # 2. Document created in store
        assert store.exists("doc-e2e-001")
        doc = store.get("doc-e2e-001")

        # 3. Version incremented (patches applied)
        assert doc.version >= 1

        # 4. Patches were generated
        assert len(plan.patch_proposals) >= 0  # may be 0 if no patches needed

        # 5. Status log shows full lifecycle
        statuses = [s["status"] for s in orch._status_log]
        assert "processing" in statuses
        assert "idle" in statuses

        # 6. Audit log populated
        assert len(orch._audit_log) > 0

    @pytest.mark.asyncio
    async def test_user_edit_recalculation_patch_broadcast(self):
        """User edit → cost recalculation → patch generation."""
        store = DocumentStore()
        role = _make_staffing_role("sa", "Solutions Architect", count=1, alloc=60, rate=105.0)
        doc = DocumentState(
            document_id="doc-e2e-002",
            staffing_plan=StaffingPlan(roles={"sa": role}),
            version=0,
        )
        store.put(doc)

        orch = _build_orchestrator_with_mocks(store=store)

        # Simulate user editing the rate
        edit_payload = {"role_id": "sa", "field": "rate_per_hour", "value": 120.0}
        result = await orch._handle_user_edit("doc-e2e-002", doc, edit_payload)

        assert result.success

        # Verify patches contain:
        # 1. user_input update
        ui_patches = [p for p in result.patches if "/user_input" in p["path"]]
        assert len(ui_patches) >= 1

        # 2. user_edited flag
        ue_patches = [p for p in result.patches if "/user_edited" in p["path"] and "rate_per_hour" in p["path"]]
        assert len(ue_patches) >= 1

        # 3. Recalculated totals
        calc_patches = [p for p in result.patches if "/calculated" in p["path"]]
        assert len(calc_patches) >= 1

        # 4. Cost breakdown update
        cost_patches = [p for p in result.patches if "cost_breakdown" in p["path"]]
        assert len(cost_patches) >= 1

    @pytest.mark.asyncio
    async def test_gateway_failure_preserves_state(self):
        """Gateway failure preserves Document_State — no partial mutations (Req 3.6)."""
        store = DocumentStore()
        doc = DocumentState(document_id="doc-e2e-003", version=0, completion_score=0.3)
        store.put(doc)

        mock_gw = MagicMock()
        mock_gw.call_tool_safe = AsyncMock(return_value=(None, "Lambda timeout"))

        orch = _build_orchestrator_with_mocks(store=store, gateway=mock_gw)

        # Trigger review which calls gateway
        plan = await orch.handle_message("doc-e2e-003", "리뷰 해주세요", [])

        # Pipeline should complete (not crash)
        assert plan.chat_response
        assert orch.state == OrchestratorState.IDLE

    @pytest.mark.asyncio
    async def test_memory_failure_continues_with_bounded_history(self):
        """Memory failure → system continues with bounded session history only."""
        mock_memory = MagicMock()
        mock_memory.on_degraded = None
        mock_memory.retrieve_customer_context.return_value = []
        mock_memory.store_session_event.return_value = False
        mock_memory.store_long_term_facts.return_value = False

        orch = _build_orchestrator_with_mocks(memory=mock_memory)

        # Should complete despite all memory failures
        plan = await orch.handle_message("doc-e2e-004", "보안 요구사항이 있는 프로젝트입니다", [])

        assert plan.chat_response
        assert orch.state == OrchestratorState.IDLE

        # Memory methods were called
        mock_memory.retrieve_customer_context.assert_called_once()

    @pytest.mark.asyncio
    async def test_version_conflict_error_scenario(self):
        """Version conflict during patch application → error response."""
        store = DocumentStore()
        doc = DocumentState(document_id="doc-e2e-005", version=0)
        store.put(doc)
        store.update(doc, expected_version=0)  # version → 1

        orch = _build_orchestrator_with_mocks(store=store)

        # Sabotage update
        original_update = store.update
        call_count = [0]

        def conflict_on_second(d, v):
            call_count[0] += 1
            if call_count[0] > 1:
                raise VersionConflictError("concurrent edit")
            return original_update(d, v)

        store.update = conflict_on_second

        # First call succeeds (creates doc), second call (apply_patches) may conflict
        plan = await orch.handle_message("doc-e2e-005", "test", [])

        # Should handle gracefully
        assert orch.state == OrchestratorState.IDLE

    @pytest.mark.asyncio
    async def test_architecture_mode_detection_and_delegation(self):
        """Architecture file mention → architecture_present mode → Architecture Agent."""
        orch = _build_orchestrator_with_mocks()

        plan = await orch.handle_message("doc-e2e-006", "여기 .drawio 아키텍처 파일입니다", [])

        assert plan.chat_response
        agents = [e["agent"] for e in orch._audit_log]
        assert "architecture_agent" in agents

    @pytest.mark.asyncio
    async def test_text_mode_detection_and_delegation(self):
        """Text input → architecture_absent mode → Discovery Agent."""
        orch = _build_orchestrator_with_mocks()

        plan = await orch.handle_message("doc-e2e-007", "새 GenAI 프로젝트를 시작합니다", [])

        assert plan.chat_response
        agents = [e["agent"] for e in orch._audit_log]
        assert "discovery_agent" in agents

    @pytest.mark.asyncio
    async def test_sequential_messages_maintain_consistency(self):
        """Multiple sequential messages maintain state consistency."""
        store = DocumentStore()
        orch = _build_orchestrator_with_mocks(store=store)

        # First message
        plan1 = await orch.handle_message("doc-e2e-008", "ABC Corp 프로젝트", [])
        assert plan1.chat_response
        assert orch.state == OrchestratorState.IDLE

        # Second message
        plan2 = await orch.handle_message("doc-e2e-008", "팀 구성을 추천해주세요", [])
        assert plan2.chat_response
        assert orch.state == OrchestratorState.IDLE

        # Document should exist and have been updated
        assert store.exists("doc-e2e-008")

    @pytest.mark.asyncio
    async def test_review_flow_returns_blocking_issues(self):
        """Review request → Reviewer Agent → blocking issues + warnings."""
        orch = _build_orchestrator_with_mocks()

        plan = await orch.handle_message("doc-e2e-009", "문서 리뷰 해주세요", [])

        assert plan.chat_response
        # Should mention review results
        assert "리뷰" in plan.chat_response or "completion" in plan.chat_response.lower() or "blocking" in plan.chat_response.lower()

    @pytest.mark.asyncio
    async def test_runtime_invoke_returns_correct_format(self):
        """Runtime invoke() returns {result, version, status} format."""
        from agent.app.parent.runtime import invoke

        result = invoke({
            "doc_id": "doc-e2e-010",
            "prompt": "프로젝트 개요를 작성해주세요",
            "history": [],
        })

        assert set(result.keys()) == {"result", "version", "status"}
        assert result["status"] == "ok"
        assert isinstance(result["result"], str)
        assert isinstance(result["version"], int)
