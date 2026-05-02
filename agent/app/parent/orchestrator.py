"""Parent Orchestrator — document state machine & router.

Receives user messages, queries Document_State, builds a task plan,
delegates to child agents/tools, and publishes patches via AppSync Events.

State transitions: IDLE → PLANNING → DELEGATING → PATCHING → RESPONDING → IDLE

Integrates with:
- AgentCore Memory (long-term context retrieval + session event storage)
- DynamoDB (Document_State fetch + optimistic lock updates)
- AppSync Events (patch / status / chat publishing)
- Sub-agents (task delegation via hub-and-spoke pattern)

Requirements: 1.1, 1.2, 4.1, 4.2, 4.5, 4.6, 9.1, 9.4
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import boto3

from agent.lib.schema.document_state import (
    DocumentState, DocumentMode, FieldStatus, FieldValue,
)
from agent.lib.schema.patch import AgentStatus, Patch, PatchOperation
from agent.lib.storage.dynamodb import DocumentStore, VersionConflictError, DocumentNotFoundError
from agent.lib.calculation.recalculate import recalculate_costs
from agent.app.parent.inference_fallback import (
    InferenceProfileFallback,
    InferenceProfileUnavailableError,
    FallbackResult,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AppSync Events configuration
# ---------------------------------------------------------------------------

APPSYNC_HTTP_ENDPOINT: str = os.environ.get("APPSYNC_HTTP_ENDPOINT", "")
APPSYNC_API_KEY: str = os.environ.get("APPSYNC_API_KEY", "")
AWS_REGION: str = os.environ.get("AWS_REGION", "ap-northeast-2")


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

class OrchestratorState(str, Enum):
    IDLE = "idle"
    PLANNING = "planning"
    DELEGATING = "delegating"
    PATCHING = "patching"
    RESPONDING = "responding"


# ---------------------------------------------------------------------------
# Data classes for task planning and agent results
# ---------------------------------------------------------------------------

@dataclass
class Task:
    agent: str = ""
    action: str = ""
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    success: bool = True
    patches: list[dict] = field(default_factory=list)
    chat_response: str = ""
    error: Optional[str] = None


@dataclass
class TaskPlan:
    tasks: list[Task] = field(default_factory=list)
    patch_proposals: list[Patch] = field(default_factory=list)
    chat_response: str = ""
    status_updates: list[AgentStatus] = field(default_factory=list)
    new_version: int = 0



class ParentOrchestrator:
    """Top-level orchestrator for the document generation system.

    Coordinates Memory retrieval, DynamoDB state management,
    task planning, sub-agent delegation, and AppSync Events publishing.
    """

    def __init__(
        self,
        document_store: DocumentStore | None = None,
        memory: Any | None = None,
        gateway_client: Any | None = None,
    ) -> None:
        self.state = OrchestratorState.IDLE
        self.document_store = document_store or DocumentStore()
        self.memory = memory  # AgentCoreMemory instance (task 3.x)
        self.gateway_client = gateway_client  # AgentCoreGatewayClient (optional)
        self._memory_degraded = False  # tracks whether Memory is in degraded mode

        # Wire up degraded callback if memory supports it (Req 2.5)
        if self.memory is not None and hasattr(self.memory, "on_degraded"):
            self.memory.on_degraded = self._on_memory_degraded

        # Inference profile fallback helpers (Req 1.7)
        from agent.app.parent.runtime import (
            PARENT_MODEL,
            PARENT_MODEL_FALLBACK,
            CHILD_MODEL,
            CHILD_MODEL_FALLBACK,
        )
        self.parent_fallback = InferenceProfileFallback(
            primary=PARENT_MODEL,
            fallback=PARENT_MODEL_FALLBACK,
            role="parent",
        )
        self.child_fallback = InferenceProfileFallback(
            primary=CHILD_MODEL,
            fallback=CHILD_MODEL_FALLBACK,
            role="child",
        )

        # Lazy sub-agent instances (Req 4.4 — logical agents within Parent)
        self._discovery_agent: Any | None = None
        self._architecture_agent: Any | None = None
        self._staffing_agent: Any | None = None
        self._cost_agent: Any | None = None
        self._reviewer_agent: Any | None = None
        self._formatter_agent: Any | None = None

        # Logs for observability and auditing
        self._patch_log: list[Patch] = []
        self._status_log: list[dict] = []
        self._audit_log: list[dict] = []

    # ------------------------------------------------------------------
    # Lazy sub-agent accessors (Req 4.4)
    # ------------------------------------------------------------------

    @property
    def discovery_agent(self):
        if self._discovery_agent is None:
            from agent.app.discovery.discovery_agent import DiscoveryAgent
            self._discovery_agent = DiscoveryAgent()
        return self._discovery_agent

    @property
    def architecture_agent(self):
        if self._architecture_agent is None:
            from agent.app.architecture.architecture_agent import ArchitectureAgent
            self._architecture_agent = ArchitectureAgent()
        return self._architecture_agent

    @property
    def staffing_agent(self):
        if self._staffing_agent is None:
            from agent.app.staffing.staffing_agent import StaffingAgent
            self._staffing_agent = StaffingAgent()
        return self._staffing_agent

    @property
    def cost_agent(self):
        if self._cost_agent is None:
            from agent.app.cost.cost_agent import CostAgent
            self._cost_agent = CostAgent()
        return self._cost_agent

    @property
    def reviewer_agent(self):
        if self._reviewer_agent is None:
            from agent.app.reviewer.reviewer_agent import ReviewerAgent
            self._reviewer_agent = ReviewerAgent()
        return self._reviewer_agent

    @property
    def formatter_agent(self):
        if self._formatter_agent is None:
            from agent.app.formatter.formatter_agent import FormatterAgent
            self._formatter_agent = FormatterAgent()
        return self._formatter_agent

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def handle_message(
        self,
        doc_id: str,
        user_message: str,
        history: list[dict],
    ) -> TaskPlan:
        """Process user message through the full orchestration pipeline.

        Steps:
            1. PLANNING  — Memory context retrieval + DynamoDB state fetch + task plan
            2. DELEGATING — Sub-agent delegation
            3. PATCHING  — Patch generation + DynamoDB optimistic lock update
            4. RESPONDING — AppSync publish + Memory session event storage

        Returns a TaskPlan with chat_response and new_version for the caller.
        """
        from agent.app.parent.task_planner import build_task_plan

        plan = TaskPlan()

        try:
            # --- IDLE → PLANNING ---
            self._transition(OrchestratorState.PLANNING)
            await self.publish_status(doc_id, AgentStatus.processing)

            # Reset memory degraded flag for this request
            self._memory_degraded = False

            # Step 1: Retrieve long-term context from AgentCore Memory
            memory_context = await self._retrieve_memory_context(doc_id, user_message)

            # Supplement bounded history with long-term context (Req 2.3, 11.3)
            if memory_context:
                history = self._supplement_history_with_memory(history, memory_context)

            # Step 2: Fetch Document_State + version from DynamoDB
            doc_state, current_version = await self._fetch_document_state(doc_id)

            # Step 3: Build task plan (intent classification)
            plan = build_task_plan(user_message)
            logger.info("Task plan: %d tasks — %s", len(plan.tasks), [(t.agent, t.action) for t in plan.tasks])

            # --- PLANNING → DELEGATING ---
            self._transition(OrchestratorState.DELEGATING)

            # Step 4: Delegate tasks to sub-agents and collect results
            # All routing is handled by LLM-based task_planner — no keyword overrides
            all_patches: list[Patch] = []
            chat_parts: list[str] = [plan.chat_response] if plan.chat_response else []

            for task in plan.tasks:
                logger.info("Executing task: agent=%s action=%s", task.agent, task.action)
                result = await self.delegate_task(task.agent, task, doc_state)
                if result.chat_response:
                    chat_parts.append(result.chat_response)
                if result.patches:
                    from agent.app.parent.patch_builder import build_patch
                    patch = build_patch(
                        doc_id=doc_id,
                        agent=task.agent,
                        version=current_version,
                        operations=result.patches,
                    )
                    all_patches.append(patch)

            # Milestone sync trigger (Task 10.1 — Req 14.1)
            # After staffing/scope changes, rebuild milestones
            if self._detect_staffing_or_scope_change(plan.tasks):
                ms_result = await self._trigger_milestone_sync(doc_id, doc_state)
                if ms_result.chat_response:
                    chat_parts.append(ms_result.chat_response)
                if ms_result.patches:
                    from agent.app.parent.patch_builder import build_patch
                    ms_patch = build_patch(
                        doc_id=doc_id,
                        agent="milestone_sync",
                        version=current_version,
                        operations=ms_result.patches,
                    )
                    all_patches.append(ms_patch)

            # --- DELEGATING → PATCHING ---
            self._transition(OrchestratorState.PATCHING)

            # Step 5: Apply patches with optimistic lock
            new_version = current_version
            if all_patches:
                new_version = await self.apply_patches(
                    doc_id, all_patches, current_version
                )

            plan.patch_proposals = all_patches
            plan.new_version = new_version
            plan.chat_response = "\n\n".join(chat_parts) if chat_parts else plan.chat_response

            # --- PATCHING → RESPONDING ---
            self._transition(OrchestratorState.RESPONDING)

            # Step 6: Store session events in AgentCore Memory
            await self._store_session_event(doc_id, user_message, plan.chat_response)

            # Step 7: Detect and store long-term facts (Req 2.2)
            await self._detect_and_store_long_term_facts(doc_id, user_message, doc_state)

            await self.publish_status(doc_id, AgentStatus.idle)

        except VersionConflictError as exc:
            logger.warning("Version conflict for doc_id=%s: %s", doc_id, exc)
            await self.publish_status(doc_id, AgentStatus.error)
            plan.chat_response = (
                "문서 버전 충돌이 발생했습니다. 페이지를 새로고침한 후 다시 시도해주세요."
            )
        except InferenceProfileUnavailableError as exc:
            logger.warning("Inference profile unavailable for doc_id=%s: %s", doc_id, exc)
            await self._publish_degraded_status(doc_id, exc)
            plan.chat_response = (
                "현재 AI 모델 inference profile이 일시적으로 사용 불가합니다. "
                "잠시 후 다시 시도해주세요."
            )
        except Exception as exc:
            logger.exception("handle_message failed for doc_id=%s", doc_id)
            await self.publish_status(doc_id, AgentStatus.error)
            plan.chat_response = f"처리 중 오류가 발생했습니다: {exc}"
        finally:
            # --- → IDLE ---
            self._transition(OrchestratorState.IDLE)

        return plan

    # ------------------------------------------------------------------
    # Sub-agent delegation
    # ------------------------------------------------------------------

    async def delegate_task(
        self,
        agent_name: str,
        task: Task,
        doc_state: DocumentState,
    ) -> AgentResult:
        """Delegate a task to a child agent (hub-and-spoke pattern).

        All coordination goes through Parent; sub-agents never
        communicate directly with each other.

        Routes to the correct sub-agent based on agent_name:
          - discovery_agent → DiscoveryAgent.collect_info()
          - architecture_agent → ArchitectureAgent.analyze_existing() / design_new()
          - staffing_agent → StaffingAgent.recommend()
          - cost_agent → CostAgent.calculate_staffing_cost() / calculate_aws_cost()
          - reviewer_agent → ReviewerAgent.review()
          - formatter_agent → FormatterAgent.export_docx()

        Maintains auditable mapping: user message → delegated task → patches.

        Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6
        """
        result = AgentResult(success=True)

        # Publish progress via ProgressPublisher
        from agent.lib.progress import ProgressPublisher
        progress = ProgressPublisher(doc_id=doc_state.document_id, table=self.document_store._table)

        agent_labels = {
            "discovery_agent": "📋 정보 수집",
            "section_writer_agent": "✏️ 섹션 작성",
            "staffing_agent": "👥 팀 구성 추천",
            "cost_agent": "💰 비용 산정",
            "architecture_agent": "🏗️ 아키텍처 분석",
            "reviewer_agent": "🔎 문서 리뷰",
            "formatter_agent": "📄 DOCX 생성",
            "conversation_agent": "💬 대화 처리",
        }
        label = agent_labels.get(agent_name, agent_name)
        progress.publish(agent_name, f"{label} 시작...", step="start")

        try:
            logger.info("delegate_task: agent=%s action=%s params=%s", agent_name, task.action, {k: v for k, v in task.params.items() if k != "message"})
            if agent_name == "discovery_agent":
                result = await self._delegate_discovery(task, doc_state)
            elif agent_name == "conversation_agent":
                result = self._delegate_conversation(task)
            elif agent_name == "section_writer_agent":
                result = await self._delegate_section_writer(task, doc_state)
            elif agent_name == "architecture_agent":
                result = await self._delegate_architecture(task, doc_state)
            elif agent_name == "staffing_agent":
                result = await self._delegate_staffing(task, doc_state)
            elif agent_name == "cost_agent":
                result = await self._delegate_cost(task, doc_state)
            elif agent_name == "reviewer_agent":
                result = await self._delegate_reviewer(task, doc_state)
            elif agent_name == "formatter_agent":
                result = await self._delegate_formatter(task, doc_state)
            else:
                result = AgentResult(
                    success=False,
                    chat_response=f"알 수 없는 에이전트: {agent_name}",
                    error=f"Unknown agent: {agent_name}",
                )
        except Exception as exc:
            logger.exception("delegate_task failed for agent=%s", agent_name)
            result = AgentResult(
                success=False,
                chat_response=f"[{agent_name}] 작업 처리 중 오류가 발생했습니다: {exc}",
                error=str(exc),
            )

        # Auditable mapping entry (Req 4.6)
        self._audit_log.append({
            "agent": agent_name,
            "action": task.action,
            "params": task.params,
            "success": result.success,
            "patches_count": len(result.patches),
        })

        # Publish completion progress
        if result.success:
            summary = result.chat_response[:100] if result.chat_response else "완료"
            progress.complete(agent_name, f"✅ {label} 완료 — {summary}")
        else:
            progress.publish(agent_name, f"⚠️ {label} 실패", step="error")

        return result

    # ------------------------------------------------------------------
    # Per-agent delegation helpers
    # ------------------------------------------------------------------

    def _delegate_conversation(self, task: Task) -> AgentResult:
        """Handle simple non-document chat without mutating Document_State."""
        message = task.params.get("message", "").strip()
        if message.isdigit():
            response = (
                "입력하신 내용만으로는 프로젝트 정보를 판단하기 어렵습니다. "
                "예: '고객사는 visang이고 GenAI 문서 자동화 PoC를 진행합니다'처럼 알려주세요."
            )
        else:
            response = (
                "가능합니다. 다만 이 채팅은 APN PoC Project Plan 작성을 돕는 용도라, "
                "문서에 반영할 내용이면 고객사, 목표, 범위, 일정, 팀 구성처럼 알려주시면 바로 반영하겠습니다."
            )
        return AgentResult(success=True, chat_response=response)

    async def _delegate_discovery(
        self, task: Task, doc_state: DocumentState
    ) -> AgentResult:
        """Delegate to DiscoveryAgent.collect_info().

        Requirements: 6.1, 6.2, 6.3, 6.4
        """
        user_input = task.params.get("message", "")
        discovery_result = await self.discovery_agent.collect_info(user_input, doc_state)

        patches: list[dict] = []
        chat_parts: list[str] = []

        # Apply extracted fields as patches
        for field_name, value in discovery_result.structured_input.items():
            if value is not None:
                if field_name == "customer":
                    patches.append({
                        "op": "replace",
                        "path": "/meta/customer/user_input",
                        "value": value,
                        "source": "user_input",
                    })
                elif field_name == "project_goal":
                    patches.append({
                        "op": "replace",
                        "path": "/meta/project_goal",
                        "value": value,
                        "source": "user_input",
                    })
                elif field_name == "scope_summary":
                    patches.append({
                        "op": "replace",
                        "path": "/sections/scope_of_work/summary",
                        "value": value,
                        "source": "user_input",
                    })

        # Set mode based on architecture availability
        if discovery_result.structured_input.get("architecture_available"):
            patches.append({
                "op": "replace",
                "path": "/mode",
                "value": DocumentMode.architecture_present.value,
                "source": "ai_recommended",
            })
        else:
            patches.append({
                "op": "replace",
                "path": "/mode",
                "value": DocumentMode.architecture_absent.value,
                "source": "ai_recommended",
            })

        patches.extend(_discovery_schema_patches(discovery_result))

        # Build chat response
        if discovery_result.can_generate_draft:
            chat_parts.append("프로젝트 정보 수집이 완료되었습니다. 초안 생성을 진행합니다.")
        elif discovery_result.follow_up_questions:
            chat_parts.append("추가 정보가 필요합니다:")
            for q in discovery_result.follow_up_questions:
                chat_parts.append(f"  • {q}")
        else:
            chat_parts.append("[discovery_agent] 정보 수집을 처리했습니다.")

        return AgentResult(
            success=True,
            patches=patches,
            chat_response="\n".join(chat_parts),
        )

    async def _delegate_section_writer(
        self, task: Task, doc_state: DocumentState
    ) -> AgentResult:
        """Generate or update a document section using Bedrock LLM.

        The section_writer_agent handles requests like "Assumptions 작성해줘",
        "Scope 작성해줘", etc. It uses the current document context to generate
        appropriate section content.
        """
        import json as _json
        section_name = task.params.get("section", "")
        message = task.params.get("message", "")

        if not section_name:
            # Try to infer section from message
            section_map = {
                "overview": "executive_summary", "summary": "executive_summary",
                "executive": "executive_summary", "요약": "executive_summary",
                "scope": "scope_of_work", "범위": "scope_of_work",
                "success": "success_criteria", "kpi": "success_criteria",
                "성공": "success_criteria",
                "assumptions": "assumptions", "가정": "assumptions",
                "리스크": "assumptions", "risk": "assumptions",
                "milestones": "milestones", "마일스톤": "milestones",
                "일정": "milestones",
                "acceptance": "acceptance", "인수": "acceptance",
                "수락": "acceptance",
            }
            msg_lower = message.lower()
            for keyword, sec in section_map.items():
                if keyword in msg_lower:
                    section_name = sec
                    break

        if not section_name:
            return AgentResult(
                success=False,
                chat_response="어떤 섹션을 작성할지 지정해주세요. (예: Overview, Scope, Assumptions, Success Criteria, Milestones, Acceptance)",
            )

        logger.info("section_writer: generating section=%s", section_name)

        # Build context from current document state
        meta = doc_state.meta
        context_parts = []
        if meta.customer.user_input:
            context_parts.append(f"고객사: {meta.customer.user_input}")
        if meta.partner.user_input:
            context_parts.append(f"파트너: {meta.partner.user_input}")
        cover = doc_state.sections.cover
        if hasattr(cover, 'model_extra') and cover.model_extra:
            for k, v in cover.model_extra.items():
                if v:
                    context_parts.append(f"{k}: {v}")

        doc_context = "\n".join(context_parts) if context_parts else "프로젝트 정보가 아직 부족합니다."

        section_display_names = {
            "executive_summary": "Executive Summary",
            "scope_of_work": "Scope of Work",
            "success_criteria": "Success Criteria / KPIs",
            "assumptions": "Assumptions & Risks",
            "milestones": "Milestones & Deliverables",
            "acceptance": "Acceptance Criteria",
        }
        display_name = section_display_names.get(section_name, section_name)

        system_prompt = f"""당신은 APN PoC Project Plan 문서의 '{display_name}' 섹션을 작성하는 전문가입니다.
현재까지 수집된 프로젝트 정보를 바탕으로 해당 섹션의 내용을 한국어로 작성하세요.

프로젝트 정보:
{doc_context}

규칙:
- 반드시 한국어로 작성하세요
- 정보가 부족하더라도 합리적인 초안을 작성하세요
- 구체적이고 전문적인 내용으로 작성하세요
- JSON 형식으로 응답하세요: {{"items": {{"key1": "내용1", "key2": "내용2", ...}}}}
- key는 항목의 제목 (예: "가정사항_1", "리스크_1", "KPI_1" 등)
- 3~5개 항목을 작성하세요"""

        try:
            fallback = self.child_fallback
            model_id = fallback.primary or "apac.anthropic.claude-3-5-sonnet-20241022-v2:0"

            bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)
            resp = bedrock.invoke_model(
                modelId=model_id,
                contentType="application/json",
                accept="application/json",
                body=_json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 2000,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": message}],
                }),
            )
            raw = _json.loads(resp["body"].read())["content"][0]["text"]
            logger.info("section_writer raw response length=%d", len(raw))

            # Parse JSON from response
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                parsed = _json.loads(raw[start:end])
                items = parsed.get("items", parsed)
            else:
                items = {"content": raw}

            # Build patches for the section
            patches = []
            for key, value in items.items():
                patches.append({
                    "op": "add",
                    "path": f"/sections/{section_name}/{key}",
                    "value": value,
                })

            chat_response = f"{display_name} 섹션을 작성했습니다.\n\n"
            for key, value in items.items():
                chat_response += f"**{key}**: {value}\n\n"

            return AgentResult(
                success=True,
                patches=patches,
                chat_response=chat_response,
            )
        except Exception as exc:
            logger.exception("section_writer failed for section=%s", section_name)
            return AgentResult(
                success=False,
                chat_response=f"{display_name} 섹션 작성 중 오류가 발생했습니다: {exc}",
                error=str(exc),
            )

    async def _delegate_architecture(
        self, task: Task, doc_state: DocumentState
    ) -> AgentResult:
        """Delegate to ArchitectureAgent.analyze_existing() or design_new().

        Dual-entry mode:
          - .drawio content → analyze_existing (architecture_present)
          - text description → design_new (architecture_absent)

        Requirements: 5.1, 5.2, 5.3
        """
        action = task.action
        message = task.params.get("message", "")
        patches: list[dict] = []

        if action == "analyze_existing":
            # architecture_present mode
            arch_result = await self.architecture_agent.analyze_existing(
                message, doc_state
            )
            patches.append({
                "op": "replace",
                "path": "/mode",
                "value": DocumentMode.architecture_present.value,
                "source": "ai_recommended",
            })
        else:
            # architecture_absent → design_new
            from agent.app.architecture.architecture_agent import ProjectContext
            ctx = ProjectContext(
                project_goal=message,
                scope_summary=task.params.get("scope", ""),
            )
            arch_result = await self.architecture_agent.design_new(ctx, doc_state)

        # Store architecture results as patches
        if arch_result.services:
            patches.append({
                "op": "replace",
                "path": "/sections/architecture/services",
                "value": [_architecture_service_to_field_values(s) for s in arch_result.services],
                "source": "ai_recommended",
            })
        overview = getattr(arch_result, "overview", "")
        if overview:
            patches.append({
                "op": "replace",
                "path": "/sections/architecture/overview",
                "value": _ai_field_value(overview),
                "source": "ai_recommended",
            })
        if arch_result.analysis:
            patches.append({
                "op": "replace",
                "path": "/sections/architecture/analysis",
                "value": arch_result.analysis,
                "source": "ai_recommended",
            })
        if arch_result.recommendations:
            patches.append({
                "op": "replace",
                "path": "/sections/architecture/recommendations",
                "value": arch_result.recommendations,
                "source": "ai_recommended",
            })
        architecture_description = arch_result.description or arch_result.architecture_description
        if architecture_description:
            patches.append({
                "op": "replace",
                "path": "/sections/architecture/description",
                "value": _ai_field_value(architecture_description),
                "source": "ai_recommended",
            })
        if arch_result.tools:
            patches.append({
                "op": "replace",
                "path": "/sections/architecture/tools",
                "value": [_ai_field_value(tool) for tool in arch_result.tools],
                "source": "ai_recommended",
            })

        chat_response = arch_result.analysis or "[architecture_agent] 아키텍처 분석을 완료했습니다."

        return AgentResult(
            success=True,
            patches=patches,
            chat_response=chat_response,
        )

    async def _delegate_staffing(
        self, task: Task, doc_state: DocumentState
    ) -> AgentResult:
        """Delegate to StaffingAgent.recommend().

        Requirements: 7.1, 7.2, 7.4, 7.5, 7.6
        """
        message = task.params.get("message", "")
        rec = self.staffing_agent.recommend(message)

        # Convert recommendation to patches via apply_recommendation logic
        patches: list[dict] = []
        for role_id, role_data in rec.roles.items():
            patches.append({
                "op": "replace",
                "path": f"/staffing_plan/roles/{role_id}",
                "value": role_data,
                "source": "ai_recommended",
            })

        chat_parts = [f"[staffing_agent] {rec.project_type} 유형 기반 팀 구성을 추천했습니다."]
        if rec.violations:
            chat_parts.append(f"⚠️ {len(rec.violations)}건의 단가 범위 위반이 감지되었습니다.")

        return AgentResult(
            success=True,
            patches=patches,
            chat_response="\n".join(chat_parts),
        )

    async def _delegate_cost(
        self, task: Task, doc_state: DocumentState
    ) -> AgentResult:
        """Delegate to CostAgent.calculate_staffing_cost() or calculate_aws_cost().

        Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8
        """
        action = task.action
        patches: list[dict] = []
        chat_parts: list[str] = []

        if action == "calculate_aws_cost" and self.gateway_client:
            services = task.params.get("services", [])
            aws_result = await self.cost_agent.calculate_aws_cost(
                services, self.gateway_client
            )
            patches.append({
                "op": "replace",
                "path": "/sections/cost_breakdown/aws_service_cost",
                "value": {
                    "monthly_cost_summary": {"calculated": aws_result.monthly_cost_summary},
                    "service_breakdown": aws_result.service_breakdown,
                    "calculator_share_url": aws_result.calculator_share_url,
                    "manual_estimate_items": aws_result.manual_estimate_items,
                },
                "source": "calculated",
            })
            total_project_cost = _current_staffing_total(doc_state) + aws_result.monthly_cost_summary
            patches.append({
                "op": "replace",
                "path": "/sections/resources_cost_estimates/contribution",
                "value": self.cost_agent.calculate_default_contribution(
                    total_project_cost
                ).model_dump(mode="json"),
                "source": "calculated",
            })
            chat_parts.append(f"[cost_agent] AWS 서비스 비용: 월 ${aws_result.monthly_cost_summary:,.2f}")
        else:
            # Default: calculate staffing cost
            staffing_result = self.cost_agent.calculate_staffing_cost(
                doc_state.staffing_plan
            )
            patches.append({
                "op": "replace",
                "path": "/sections/cost_breakdown/staffing_cost",
                "value": {
                    "roles_summary": staffing_result.roles_summary,
                    "grand_total": {"calculated": staffing_result.grand_total},
                },
                "source": "calculated",
            })
            total_project_cost = staffing_result.grand_total + _current_aws_monthly_total(doc_state)
            patches.append({
                "op": "replace",
                "path": "/sections/resources_cost_estimates/contribution",
                "value": self.cost_agent.calculate_default_contribution(
                    total_project_cost
                ).model_dump(mode="json"),
                "source": "calculated",
            })
            chat_parts.append(
                f"[cost_agent] 인건비 계산 완료: 총 ${staffing_result.grand_total:,.2f}"
            )

        return AgentResult(
            success=True,
            patches=patches,
            chat_response="\n".join(chat_parts),
        )

    async def _delegate_reviewer(
        self, task: Task, doc_state: DocumentState
    ) -> AgentResult:
        """Delegate to ReviewerAgent.review().

        Requirements: 13.1, 13.2, 17.1
        """
        review_result = self.reviewer_agent.review(doc_state)

        patches: list[dict] = [
            {
                "op": "replace",
                "path": "/completion_score",
                "value": review_result.completion_score,
                "source": "calculated",
            },
            {
                "op": "replace",
                "path": "/blocking_issues",
                "value": [i.model_dump() for i in review_result.blocking_issues],
                "source": "calculated",
            },
            {
                "op": "replace",
                "path": "/warnings",
                "value": [w.model_dump() for w in review_result.warnings],
                "source": "calculated",
            },
        ]

        chat_parts = [
            f"[reviewer_agent] 문서 리뷰 완료 — 완성도: {review_result.completion_score:.0%}"
        ]
        if review_result.blocking_issues:
            chat_parts.append(
                f"🚫 Blocking issues: {len(review_result.blocking_issues)}건"
            )
        if review_result.warnings:
            chat_parts.append(
                f"⚠️ Warnings: {len(review_result.warnings)}건"
            )
        if review_result.suggestions:
            for s in review_result.suggestions[:3]:
                chat_parts.append(f"  • {s}")

        return AgentResult(
            success=True,
            patches=patches,
            chat_response="\n".join(chat_parts),
        )

    async def _delegate_formatter(
        self, task: Task, doc_state: DocumentState
    ) -> AgentResult:
        """Delegate to FormatterAgent.export_docx().

        Requirements: 13.3, 13.4
        """
        if not self.gateway_client:
            return AgentResult(
                success=False,
                chat_response="[formatter_agent] Gateway 클라이언트가 설정되지 않아 DOCX export를 수행할 수 없습니다.",
                error="No gateway_client configured",
            )

        export_result = await self.formatter_agent.export_docx(
            doc_state, self.gateway_client
        )

        if not export_result.success:
            return AgentResult(
                success=False,
                chat_response=f"[formatter_agent] DOCX export 실패: {export_result.error}",
                error=export_result.error,
            )

        patches: list[dict] = []
        if export_result.s3_path:
            patches.append({
                "op": "replace",
                "path": "/sections/resources_cost_estimates/export_s3_path",
                "value": export_result.s3_path,
                "source": "calculated",
            })

        chat_response = "[formatter_agent] DOCX export 완료"
        if export_result.download_url:
            chat_response += f"\n📥 다운로드: {export_result.download_url}"

        return AgentResult(
            success=True,
            patches=patches,
            chat_response=chat_response,
        )

    # ------------------------------------------------------------------
    # Milestone sync (Task 10.1 — Req 14.1, 14.2, 14.3)
    # ------------------------------------------------------------------

    async def _trigger_milestone_sync(
        self,
        doc_id: str,
        doc_state: DocumentState,
    ) -> AgentResult:
        """Rebuild milestones when staffing_plan or scope_of_work changes.

        Calls Gateway ``build_milestone_summary`` tool with the current
        staffing_plan and scope_of_work, then returns patches to update
        ``sections.milestones``.

        stakeholders contact info is NOT used as direct input (Req 14.3).

        Requirements: 14.1, 14.2, 14.3
        """
        staffing_dict = doc_state.staffing_plan.model_dump(mode="json")
        scope_dict = doc_state.sections.scope_of_work.model_dump(mode="json")

        params = {
            "staffing_plan": staffing_dict,
            "scope_of_work": scope_dict,
        }

        patches: list[dict] = []
        chat_parts: list[str] = []

        if self.gateway_client:
            result, error = await self.gateway_client.call_tool_safe(
                "build_milestone_summary", params
            )
            if error or result is None:
                logger.warning("build_milestone_summary failed: %s", error)
                chat_parts.append(
                    "[milestone_sync] Gateway 호출 실패 — 로컬 동기화로 대체합니다."
                )
                # Fallback to local sync
                result = self._local_milestone_sync(staffing_dict, scope_dict)
        else:
            # No gateway client — use local sync
            result = self._local_milestone_sync(staffing_dict, scope_dict)

        if result:
            phases = result.get("phases", [])
            phase_values = [_milestone_phase_to_field_values(p) for p in phases]
            patches.append({
                "op": "replace",
                "path": "/sections/milestones/phases",
                "value": phase_values,
                "source": "calculated",
            })
            total_hours = result.get("total_project_hours", 0)
            patches.append({
                "op": "replace",
                "path": "/sections/milestones/total_project_hours",
                "value": total_hours,
                "source": "calculated",
            })
            chat_parts.append(
                f"[milestone_sync] 마일스톤 동기화 완료 — {len(phases)}개 phase, "
                f"총 {total_hours}시간"
            )

        return AgentResult(
            success=True,
            patches=patches,
            chat_response="\n".join(chat_parts) if chat_parts else "",
        )

    @staticmethod
    def _local_milestone_sync(
        staffing_plan: dict, scope_of_work: dict
    ) -> dict:
        """Local fallback milestone generation without Gateway call."""
        phases_list = ("discovery", "development", "testing")
        default_deliverables = {
            "discovery": ["요구사항 문서", "아키텍처 설계서", "프로젝트 계획서"],
            "development": ["에이전트 구현", "API 개발", "UI 구현", "통합"],
            "testing": ["통합 테스트", "UAT", "버그 수정", "최종 문서"],
        }
        roles = staffing_plan.get("roles", {})
        phases: list[dict] = []
        for phase in phases_list:
            total_hours = 0.0
            assigned: list[str] = []
            for role_id, role in roles.items():
                ph = role.get("phase_hours", {})
                fv = ph.get(phase, {})
                val = fv.get("user_input") or fv.get("ai_recommended") or fv.get("calculated")
                hours = float(val) if val else 0.0
                if hours > 0:
                    total_hours += hours
                    name = role.get("display_name", role_id)
                    if name not in assigned:
                        assigned.append(name)
            deliverables = scope_of_work.get(
                f"{phase}_deliverables",
                default_deliverables.get(phase, []),
            )
            if not isinstance(deliverables, list):
                deliverables = default_deliverables.get(phase, [])
            phases.append({
                "phase": phase,
                "total_hours": round(total_hours, 2),
                "roles": assigned,
                "deliverables": deliverables,
            })
        return {
            "phases": phases,
            "total_project_hours": round(sum(p["total_hours"] for p in phases), 2),
        }

    # ------------------------------------------------------------------
    # Review / Export flow (Task 10.2 — Req 13.1, 13.2, 13.3, 13.4)
    # ------------------------------------------------------------------

    async def _handle_review_request(
        self,
        doc_id: str,
        doc_state: DocumentState,
    ) -> AgentResult:
        """Handle review request: Reviewer Agent + Gateway validation.

        1. Delegate to ReviewerAgent for local review
        2. Call Gateway ``validate_template_constraints`` for template validation
        3. Merge blocking issues + warnings from both sources

        Requirements: 13.1, 13.2
        """
        # Step 1: Local reviewer agent review
        review_task = Task(agent="reviewer_agent", action="review", params={})
        reviewer_result = await self.delegate_task("reviewer_agent", review_task, doc_state)

        # Step 2: Gateway template validation
        gateway_issues: list[dict] = []
        gateway_warnings: list[dict] = []

        if self.gateway_client:
            params = {
                "sections": doc_state.sections.model_dump(mode="json"),
                "staffing_plan": doc_state.staffing_plan.model_dump(mode="json"),
                "completion_score": doc_state.completion_score,
            }
            gw_result, error = await self.gateway_client.call_tool_safe(
                "validate_template_constraints", params
            )
            if gw_result and not error:
                gateway_issues = gw_result.get("blocking_issues", [])
                gateway_warnings = gw_result.get("warnings", [])

        # Merge gateway results into reviewer patches
        patches = list(reviewer_result.patches)
        chat_parts = [reviewer_result.chat_response] if reviewer_result.chat_response else []

        if gateway_issues:
            # Append gateway blocking issues to the existing blocking_issues patch
            for p in patches:
                if p.get("path") == "/blocking_issues":
                    existing = p.get("value", [])
                    p["value"] = existing + gateway_issues
                    break

            chat_parts.append(
                f"[gateway] 추가 blocking issues: {len(gateway_issues)}건"
            )

        if gateway_warnings:
            for p in patches:
                if p.get("path") == "/warnings":
                    existing = p.get("value", [])
                    p["value"] = existing + gateway_warnings
                    break

            chat_parts.append(
                f"[gateway] 추가 warnings: {len(gateway_warnings)}건"
            )

        return AgentResult(
            success=True,
            patches=patches,
            chat_response="\n".join(chat_parts),
        )

    async def _handle_export_request(
        self,
        doc_id: str,
        doc_state: DocumentState,
    ) -> AgentResult:
        """Handle export request: Formatter Agent → Gateway export_docx → S3 link.

        Requirements: 13.3, 13.4
        """
        export_task = Task(agent="formatter_agent", action="export", params={})
        return await self.delegate_task("formatter_agent", export_task, doc_state)

    # ------------------------------------------------------------------
    # User edit → cost recalculation (Task 10.3 — Req 7.3, 8.3, 12.2, 12.3)
    # ------------------------------------------------------------------

    async def _handle_user_edit(
        self,
        doc_id: str,
        doc_state: DocumentState,
        edit_payload: dict,
    ) -> AgentResult:
        """Handle user edit on staffing_plan: mark as user_modified, recalculate costs.

        Steps:
          1. Apply user edits to staffing_plan fields with user_edited=true,
             status=user_modified, preserving original ai_recommended
          2. Trigger Cost Agent recalculation
          3. Update cost_breakdown section

        Requirements: 7.3, 8.3, 12.2, 12.3
        """
        patches: list[dict] = []
        chat_parts: list[str] = []

        role_id = edit_payload.get("role_id", "")
        field_name = edit_payload.get("field", "")
        new_value = edit_payload.get("value")

        if role_id and field_name and new_value is not None:
            # Mark the field as user_modified, preserve ai_recommended
            base_path = f"/staffing_plan/roles/{role_id}/{field_name}"
            patches.append({
                "op": "replace",
                "path": f"{base_path}/user_input",
                "value": new_value,
                "source": "user_input",
            })
            patches.append({
                "op": "replace",
                "path": f"{base_path}/user_edited",
                "value": True,
                "source": "user_input",
            })
            patches.append({
                "op": "replace",
                "path": f"{base_path}/status",
                "value": FieldStatus.user_modified.value,
                "source": "user_input",
            })

            # Also mark the role-level user_edited flag
            patches.append({
                "op": "replace",
                "path": f"/staffing_plan/roles/{role_id}/user_edited",
                "value": True,
                "source": "user_input",
            })

            chat_parts.append(
                f"[user_edit] {role_id}.{field_name} = {new_value} (user_modified)"
            )

        # Recalculate costs using the updated staffing_plan
        # Build an updated staffing_plan dict with the user edit applied
        sp_dict = doc_state.staffing_plan.model_dump(mode="json")
        if role_id and field_name and new_value is not None:
            role_data = sp_dict.get("roles", {}).get(role_id, {})
            field_data = role_data.get(field_name, {})
            if isinstance(field_data, dict):
                field_data["user_input"] = new_value
                field_data["user_edited"] = True
                field_data["status"] = FieldStatus.user_modified.value

        calc = recalculate_costs(sp_dict)

        # Update calculated totals for each role
        for rid, vals in calc["roles"].items():
            patches.append({
                "op": "replace",
                "path": f"/staffing_plan/roles/{rid}/total_hours/calculated",
                "value": vals["total_hours"],
                "source": "calculated",
            })
            patches.append({
                "op": "replace",
                "path": f"/staffing_plan/roles/{rid}/total_cost/calculated",
                "value": vals["total_cost"],
                "source": "calculated",
            })

        # Update grand totals
        patches.append({
            "op": "replace",
            "path": "/staffing_plan/grand_total_hours/calculated",
            "value": calc["grand_total_hours"],
            "source": "calculated",
        })
        patches.append({
            "op": "replace",
            "path": "/staffing_plan/grand_total_cost/calculated",
            "value": calc["grand_total_cost"],
            "source": "calculated",
        })

        # Update cost_breakdown section
        cost_result = self.cost_agent.calculate_staffing_cost(doc_state.staffing_plan)
        patches.append({
            "op": "replace",
            "path": "/sections/cost_breakdown/staffing_cost",
            "value": {
                "roles_summary": cost_result.roles_summary,
                "grand_total": {"calculated": cost_result.grand_total},
            },
            "source": "calculated",
        })

        chat_parts.append(
            f"[cost_recalc] 비용 재계산 완료 — 총 ${calc['grand_total_cost']:,.2f}"
        )

        return AgentResult(
            success=True,
            patches=patches,
            chat_response="\n".join(chat_parts),
        )

    # ------------------------------------------------------------------
    # Intent-based routing helpers for handle_message integration
    # ------------------------------------------------------------------

    def _detect_staffing_or_scope_change(self, tasks: list[Task]) -> bool:
        """Check if any task modifies staffing_plan or scope_of_work."""
        for task in tasks:
            if task.agent in ("staffing_agent", "cost_agent"):
                return True
            if task.action in ("recommend", "calculate"):
                return True
        return False

    def _detect_review_intent(self, user_message: str) -> bool:
        """Check if user message requests a review."""
        msg_lower = user_message.lower()
        return any(kw in msg_lower for kw in ["리뷰", "review", "검증", "검사"])

    def _detect_export_intent(self, user_message: str) -> bool:
        """Check if user message requests an export."""
        msg_lower = user_message.lower()
        return any(kw in msg_lower for kw in ["export", "docx", "다운로드", "내보내기"])

    def _detect_user_edit_intent(self, user_message: str) -> bool:
        """Check if user message is a staffing plan edit."""
        msg_lower = user_message.lower()
        return any(kw in msg_lower for kw in [
            "수정", "변경", "edit", "modify", "update",
            "인원", "단가", "시간", "rate", "hours", "count",
        ])

    # ------------------------------------------------------------------
    # Patch application with optimistic locking
    # ------------------------------------------------------------------

    async def apply_patches(
        self,
        doc_id: str,
        patches: list[Patch],
        expected_version: int,
    ) -> int:
        """Apply patches to DynamoDB with optimistic locking, then publish.

        1. Fetch current document state
        2. Apply patch operations to the in-memory state
        3. Write back with ConditionExpression on version (optimistic lock)
        4. Publish patches to AppSync Events

        Returns the new document version after successful update.

        Raises:
            VersionConflictError: if the expected version doesn't match.
        """
        doc_state = self.document_store.get(doc_id)

        # Apply all patch operations to the document state dict
        doc_dict = doc_state.model_dump(mode="json")
        for patch in patches:
            for op in patch.operations:
                _apply_operation(doc_dict, op)

        # Reconstruct and persist with optimistic lock
        updated_state = DocumentState.model_validate(doc_dict)
        saved = self.document_store.update(updated_state, expected_version)
        new_version = saved.version

        # Update patch versions and publish to AppSync
        for patch in patches:
            patch.version = new_version
            patch.version_before = expected_version
            patch.version_after = new_version
        await self.publish_patch(doc_id, patches)

        return new_version

    # ------------------------------------------------------------------
    # AppSync Events publishing
    # ------------------------------------------------------------------

    async def publish_patch(self, doc_id: str, patches: list[Patch]) -> None:
        """Publish patches to AppSync Events ``docs/{docId}/patch`` channel.

        Uses AppSync Events HTTP API when configured, otherwise logs
        for development visibility.
        """
        channel = f"docs/{doc_id}/patch"

        for patch in patches:
            payload = {
                **patch.model_dump(mode="json"),
                "type": "patch",
            }
            self._patch_log.append(patch)

            if APPSYNC_HTTP_ENDPOINT:
                await self._appsync_publish(channel, payload)
            else:
                logger.info(
                    "publish_patch [dev] channel=%s patch_id=%s ops=%d",
                    channel,
                    patch.patch_id,
                    len(patch.operations),
                )

    async def publish_status(self, doc_id: str, status: AgentStatus) -> None:
        """Publish agent status to AppSync Events ``docs/{docId}/status`` channel."""
        channel = f"docs/{doc_id}/status"
        payload = {"doc_id": doc_id, "status": status.value}

        self._status_log.append(payload)

        if APPSYNC_HTTP_ENDPOINT:
            await self._appsync_publish(channel, payload)
        else:
            logger.info(
                "publish_status [dev] channel=%s status=%s",
                channel,
                status.value,
            )

    async def publish_chat(self, doc_id: str, message: str) -> None:
        """Publish chat response to AppSync Events ``docs/{docId}/chat`` channel."""
        channel = f"docs/{doc_id}/chat"
        payload = {"doc_id": doc_id, "message": message}

        if APPSYNC_HTTP_ENDPOINT:
            await self._appsync_publish(channel, payload)
        else:
            logger.info("publish_chat [dev] channel=%s len=%d", channel, len(message))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _transition(self, new_state: OrchestratorState) -> None:
        """Transition the orchestrator state machine."""
        logger.debug("state transition: %s → %s", self.state.value, new_state.value)
        self.state = new_state

    async def _retrieve_memory_context(
        self, doc_id: str, user_message: str
    ) -> list[dict]:
        """Retrieve long-term context from AgentCore Memory.

        Falls back to empty list if Memory is unavailable (degraded mode).
        When the Memory API call fails, a warning/degraded status is
        published to ``docs/{docId}/status`` (Req 2.5).
        """
        if self.memory is None:
            return []

        result = self.memory.retrieve_customer_context(
            customer=doc_id, query=user_message
        )

        # retrieve_customer_context returns [] on failure via _safe_call;
        # check the degraded flag set by the on_degraded callback.
        if self._memory_degraded:
            await self._publish_memory_degraded_status(
                doc_id, "retrieve_customer_context"
            )
        return result

    async def _fetch_document_state(
        self, doc_id: str
    ) -> tuple[DocumentState, int]:
        """Fetch Document_State + version from DynamoDB.

        Creates a new empty document if not found.
        """
        try:
            doc = self.document_store.get(doc_id)
            return doc, doc.version
        except DocumentNotFoundError:
            doc = DocumentState(document_id=doc_id, version=0)
            self.document_store.put(doc)
            return doc, 0

    async def _store_session_event(
        self, doc_id: str, user_message: str, agent_response: str
    ) -> None:
        """Store session events in AgentCore Memory.

        Silently degrades if Memory is unavailable and publishes a
        warning/degraded status to ``docs/{docId}/status`` (Req 2.5).
        """
        if self.memory is None:
            return

        success = self.memory.store_session_event(
            session_id=doc_id,
            actor_id="parent_orchestrator",
            content=f"user: {user_message}\nagent: {agent_response}",
        )
        if not success:
            await self._publish_memory_degraded_status(
                doc_id, "store_session_event"
            )

    # ------------------------------------------------------------------
    # Memory context supplementation (Req 2.3, 11.3)
    # ------------------------------------------------------------------

    @staticmethod
    def _supplement_history_with_memory(
        history: list[dict],
        memory_context: list[dict],
    ) -> list[dict]:
        """Prepend long-term memory context to bounded history.

        Inserts a system-level context message at the beginning of the
        history so the LLM can leverage customer-specific facts
        retrieved from AgentCore Memory without requiring the full
        historical transcript.
        """
        context_texts = []
        for record in memory_context:
            content = record.get("content", {})
            text = content.get("text", "") if isinstance(content, dict) else str(content)
            if text:
                context_texts.append(text)

        if not context_texts:
            return history

        context_message = {
            "role": "system",
            "content": (
                "[장기 메모리 컨텍스트]\n"
                + "\n".join(f"- {t}" for t in context_texts)
            ),
        }
        return [context_message] + list(history)

    # ------------------------------------------------------------------
    # Long-term fact detection and storage (Req 2.2)
    # ------------------------------------------------------------------

    # Keywords that indicate long-term customer characteristics
    _LONG_TERM_KEYWORDS: list[tuple[str, str]] = [
        ("보안", "security_requirement"),
        ("security", "security_requirement"),
        ("compliance", "compliance_requirement"),
        ("컴플라이언스", "compliance_requirement"),
        ("hipaa", "compliance_requirement"),
        ("pci", "compliance_requirement"),
        ("리전", "region_constraint"),
        ("region", "region_constraint"),
        ("ap-northeast", "region_constraint"),
        ("us-east", "region_constraint"),
        ("eu-west", "region_constraint"),
        ("산업", "industry"),
        ("industry", "industry"),
        ("금융", "industry"),
        ("헬스케어", "industry"),
        ("healthcare", "industry"),
    ]

    def _extract_long_term_facts(self, user_message: str) -> list[dict]:
        """Detect long-term customer facts from user message.

        Scans for keywords indicating security requirements, region
        constraints, compliance needs, or industry characteristics.
        Returns a list of ``{"value": ..., "category": ...}`` dicts.
        """
        msg_lower = user_message.lower()
        detected: list[dict] = []
        seen_categories: set[str] = set()

        for keyword, category in self._LONG_TERM_KEYWORDS:
            if keyword in msg_lower and category not in seen_categories:
                seen_categories.add(category)
                detected.append({
                    "value": f"[{category}] {user_message}",
                    "category": category,
                })

        return detected

    async def _detect_and_store_long_term_facts(
        self,
        doc_id: str,
        user_message: str,
        doc_state: DocumentState,
    ) -> None:
        """Detect long-term facts in user message and store them.

        Extracts customer characteristics (security requirements,
        region constraints, etc.) and persists them via
        ``store_long_term_facts()`` for future session retrieval.

        Falls back silently if Memory is unavailable (Req 2.5).
        """
        if self.memory is None:
            return

        facts = self._extract_long_term_facts(user_message)
        if not facts:
            return

        # Determine customer scope from doc_state or doc_id
        customer = doc_id
        meta = getattr(doc_state, "meta", None)
        if meta and isinstance(meta, dict):
            customer_field = meta.get("customer", {})
            if isinstance(customer_field, dict):
                customer = customer_field.get("user_input") or doc_id
            elif hasattr(customer_field, "user_input") and customer_field.user_input:
                customer = customer_field.user_input

        success = self.memory.store_long_term_facts(
            customer=customer,
            facts=facts,
        )
        if not success:
            await self._publish_memory_degraded_status(
                doc_id, "store_long_term_facts"
            )

    async def _publish_degraded_status(
        self,
        doc_id: str,
        exc: InferenceProfileUnavailableError | None = None,
    ) -> None:
        """Publish degraded status to ``docs/{docId}/status`` channel.

        Called when an inference profile is unavailable and the system
        enters degraded mode (Req 1.7).
        """
        channel = f"docs/{doc_id}/status"
        payload: dict[str, Any] = {
            "doc_id": doc_id,
            "status": AgentStatus.degraded.value,
            "message": (
                "AI 모델 inference profile이 일시적으로 사용 불가합니다. "
                "일부 기능이 제한될 수 있습니다."
            ),
        }
        if exc is not None:
            payload["primary"] = exc.primary
            payload["fallback"] = exc.fallback

        self._status_log.append(payload)

        if APPSYNC_HTTP_ENDPOINT:
            await self._appsync_publish(channel, payload)
        else:
            logger.info(
                "publish_status [dev] channel=%s status=degraded",
                channel,
            )

    async def _publish_memory_degraded_status(
        self,
        doc_id: str,
        method_name: str,
    ) -> None:
        """Publish warning/degraded status when Memory API fails (Req 2.5).

        Informs the user that the system is operating in no-memory
        degraded mode using bounded session history only.
        """
        channel = f"docs/{doc_id}/status"
        payload: dict[str, Any] = {
            "doc_id": doc_id,
            "status": AgentStatus.degraded.value,
            "reason": "memory_api_failure",
            "failed_method": method_name,
            "message": (
                "Memory API가 일시적으로 사용 불가합니다. "
                "현재 세션 이력만으로 동작합니다."
            ),
        }

        self._status_log.append(payload)

        if APPSYNC_HTTP_ENDPOINT:
            await self._appsync_publish(channel, payload)
        else:
            logger.info(
                "publish_status [dev] channel=%s status=degraded reason=memory_api_failure method=%s",
                channel,
                method_name,
            )

    def _on_memory_degraded(self, method_name: str, exc: Exception) -> None:
        """Callback passed to AgentCoreMemory.on_degraded.

        Sets the ``_memory_degraded`` flag so the orchestrator can
        publish a warning status after the call returns.
        """
        self._memory_degraded = True
        logger.warning(
            "Memory degraded callback: method=%s error=%s", method_name, exc
        )

    async def _appsync_publish(self, channel: str, payload: dict) -> None:
        """Publish a message to an AppSync Events channel via HTTP POST.

        Uses the AppSync Events HTTP API with API key authentication.
        """
        try:
            import urllib.request
            import urllib.error

            url = f"{APPSYNC_HTTP_ENDPOINT}/event"
            data = json.dumps({
                "channel": channel,
                "events": [json.dumps(payload)],
            }).encode("utf-8")

            req = urllib.request.Request(
                url,
                data=data,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": APPSYNC_API_KEY,
                },
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                logger.debug(
                    "AppSync publish OK channel=%s status=%d",
                    channel,
                    resp.status,
                )
        except Exception as exc:
            logger.error(
                "AppSync publish failed channel=%s: %s", channel, exc
            )


# ---------------------------------------------------------------------------
# Patch operation helpers
# ---------------------------------------------------------------------------

def _ai_field_value(value: Any) -> dict[str, Any]:
    return {
        "user_input": None,
        "ai_recommended": value or "",
        "calculated": None,
        "status": FieldStatus.recommended.value,
        "user_edited": False,
    }


def _contact_to_field_value(c: dict) -> dict:
    role_value = c.get("description") or c.get("stakeholder_for") or c.get("role") or ""

    def fv(value):
        return _ai_field_value(value)

    return {
        "name": fv(c.get("name", "")),
        "title": fv(c.get("title", "")),
        "role_or_description": fv(role_value),
        "contact": fv(c.get("contact", "")),
    }


def _field_value_list(items: list[Any]) -> list[dict[str, Any]]:
    return [_ai_field_value(item) for item in items]


def _category_group_to_field_values(group: dict[str, Any]) -> dict[str, Any]:
    return {
        "category_name": _ai_field_value(group.get("category_name", "")),
        "items": _field_value_list(group.get("items", [])),
    }


def _scope_task_to_field_values(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_category": _ai_field_value(task.get("task_category", "")),
        "schedule": _ai_field_value(task.get("schedule", "")),
        "details": _field_value_list(task.get("details", [])),
        "personnel": _ai_field_value(task.get("personnel", "")),
    }


def _architecture_service_to_field_values(service: Any) -> dict[str, Any]:
    if not isinstance(service, dict):
        service = {"service_name": str(service), "service_id": str(service)}
    return {
        "service_name": _ai_field_value(service.get("service_name", "")),
        "service_id": service.get("service_id", ""),
        "priority": service.get("priority", 99),
        "category": service.get("category", "compute"),
        "description": _ai_field_value(service.get("description", "")),
        "sizing_rationale": _ai_field_value(service.get("sizing_rationale", "")),
        "is_required_for_funding": bool(service.get("is_required_for_funding", False)),
    }


def _discovery_schema_patches(discovery_result: Any) -> list[dict]:
    patches: list[dict] = []
    structured_input = getattr(discovery_result, "structured_input", {}) or {}
    summary_fields = getattr(discovery_result, "executive_summary_fields", {}) or {}
    business_case = getattr(discovery_result, "business_case", {}) or {}

    for path, value in [
        ("/sections/executive_summary/text", discovery_result.executive_summary),
        ("/sections/acceptance/text", discovery_result.acceptance_text),
        ("/sections/executive_summary/customer_intro", summary_fields.get("customer_intro", "")),
        ("/sections/executive_summary/problem_statement", summary_fields.get("problem_statement", "")),
        ("/sections/executive_summary/proposed_solution", summary_fields.get("proposed_solution", "")),
        ("/sections/executive_summary/business_case/problem_definition", business_case.get("problem_definition", "")),
        ("/sections/executive_summary/business_case/roi_calculation", business_case.get("roi_calculation", "")),
        ("/sections/executive_summary/business_case/executive_sponsor", business_case.get("executive_sponsor", "")),
        ("/sections/executive_summary/business_case/production_commitment", business_case.get("production_commitment", "")),
    ]:
        if value != "":
            patches.append({
                "op": "replace",
                "path": path,
                "value": _ai_field_value(value),
                "source": "ai_recommended",
            })
    phases_overview = summary_fields.get("phases_overview", [])
    if phases_overview:
        patches.append({
            "op": "replace",
            "path": "/sections/executive_summary/phases_overview",
            "value": _field_value_list(phases_overview),
            "source": "ai_recommended",
        })

    for path, contacts in [
        ("/sections/stakeholders/executive_sponsors", discovery_result.executive_sponsors),
        ("/sections/stakeholders/stakeholders", discovery_result.stakeholders),
        ("/sections/stakeholders/project_team", discovery_result.project_team),
        ("/sections/stakeholders/escalation_contacts", discovery_result.escalation_contacts),
    ]:
        field_name = path.rsplit("/", 1)[-1]
        if not isinstance(structured_input.get(field_name), list) or not contacts:
            continue
        patches.append({
            "op": "replace",
            "path": path,
            "value": [_contact_to_field_value(c) for c in contacts],
            "source": "ai_recommended",
        })

    for path, items in [
        ("/sections/success_criteria/items", discovery_result.success_criteria),
        ("/sections/assumptions/items", discovery_result.assumptions),
        ("/sections/scope_of_work/items", discovery_result.scope_of_work),
    ]:
        field_name = path.split("/")[-2]
        if not isinstance(structured_input.get(field_name), list) or not items:
            continue
        patches.append({
            "op": "replace",
            "path": path,
            "value": _field_value_list(items),
            "source": "ai_recommended",
        })
    for path, groups in [
        ("/sections/success_criteria/groups", getattr(discovery_result, "success_criteria_groups", [])),
        ("/sections/assumptions/groups", getattr(discovery_result, "assumption_groups", [])),
    ]:
        if groups:
            patches.append({
                "op": "replace",
                "path": path,
                "value": [_category_group_to_field_values(group) for group in groups],
                "source": "ai_recommended",
            })
    scope_tasks = getattr(discovery_result, "scope_tasks", [])
    if scope_tasks:
        patches.append({
            "op": "replace",
            "path": "/sections/scope_of_work/tasks",
            "value": [_scope_task_to_field_values(task) for task in scope_tasks],
            "source": "ai_recommended",
        })
    return patches


def _milestone_phase_to_field_values(phase: dict[str, Any]) -> dict[str, Any]:
    deliverables = phase.get("deliverables", "")
    if isinstance(deliverables, list):
        deliverables = "\n".join(str(d) for d in deliverables if d)
    completion_date = phase.get("completion_date") or phase.get("date") or phase.get("end_date") or ""
    return {
        "phase": _ai_field_value(phase.get("phase", "")),
        "completion_date": _ai_field_value(completion_date),
        "deliverables": _ai_field_value(deliverables),
    }


def _current_staffing_total(doc_state: DocumentState) -> float:
    value = getattr(doc_state.staffing_plan.grand_total_cost, "calculated", 0) or 0
    if value:
        return float(value)
    staffing_cost = doc_state.sections.cost_breakdown.staffing_cost
    section_value = getattr(staffing_cost.grand_total, "calculated", 0) or 0
    return float(section_value)


def _current_aws_monthly_total(doc_state: DocumentState) -> float:
    summary = doc_state.sections.cost_breakdown.aws_service_cost.monthly_cost_summary
    value = getattr(summary, "calculated", 0) or 0
    return float(value)


def _apply_operation(doc_dict: dict, op: PatchOperation) -> None:
    """Apply a single JSON-Patch-style operation to a document dict."""
    parts = [p for p in op.path.strip("/").split("/") if p]
    if not parts:
        return

    current = doc_dict
    for part in parts[:-1]:
        if isinstance(current, dict):
            current = current.setdefault(part, {})
        else:
            return

    target_key = parts[-1]

    if op.op == "replace" or op.op == "add":
        if isinstance(current, dict):
            current[target_key] = op.value
    elif op.op == "remove":
        if isinstance(current, dict):
            current.pop(target_key, None)
