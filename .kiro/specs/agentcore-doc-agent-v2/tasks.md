# Implementation Plan: AgentCore 멀티에이전트 문서 생성 시스템 v2

## Overview

v1의 단일 Lambda + 직접 Bedrock 호출 아키텍처를 AgentCore Runtime/Memory/Gateway 기반 멀티에이전트 시스템으로 업그레이드한다. 기존 인프라(DynamoDB, S3, CloudFront, AppSync Events, API Gateway)는 유지하면서 AgentCore 계층을 추가한다.

테스트 전략: unit/contract/component 테스트는 Kiro가 작성·실행하고, 사용자는 AWS 통합 검증에 집중한다.

## Tasks

- [x] 1. AgentCore Runtime 설정 및 Parent Orchestrator 배포
  - [x] 1.1 `bedrock-agentcore` SDK 및 `strands-agents` 의존성 설치
    - `agent/` 프로젝트에 `bedrock-agentcore`, `strands-agents` 추가 (pyproject.toml 또는 requirements.txt)
    - Python 3.12 호환성 검증
    - _Requirements: 1.1, 1.6_

  - [x] 1.2 AgentCore Runtime 진입점 모듈 생성
    - `agent/app/parent/runtime.py` 생성: `BedrockAgentCoreApp` + `@app.entrypoint` decorator
    - `invoke(payload)` 함수: `doc_id`, `prompt`, `history` (bounded N턴) 수신
    - 응답 형식: `{"result": chat_response, "version": new_version, "status": "ok"}` — 문서 상태 변경은 AppSync patch 채널로만 전달
    - `PARENT_MODEL`, `CHILD_MODEL`을 환경변수로 override 가능하게 구성
    - _Requirements: 1.1, 1.2, 1.4, 1.5_

  - [x] 1.3 `orchestrator.py` AgentCore Runtime 통합 리팩토링
    - `handle_message(doc_id, user_message, history)`: Memory 조회 → DynamoDB state fetch → task plan → sub-agent 위임 → patch 생성
    - `apply_patches(doc_id, patches, expected_version)`: DynamoDB optimistic lock 적용 후 AppSync patch 발행
    - `publish_patch()`, `publish_status()`: 실제 AppSync Events HTTP publish
    - 상태 전이: `IDLE → PLANNING → DELEGATING → PATCHING → RESPONDING → IDLE`
    - _Requirements: 1.1, 1.2, 4.1, 4.2, 4.5, 4.6, 9.1, 9.4_

  - [x] 1.4 Inference profile fallback 메커니즘 구현
    - Primary profile 사용 실패 시 degraded mode 진입 + 사용자 상태 메시지 발행
    - `docs/{docId}/status` 채널로 degraded 상태 발행
    - _Requirements: 1.7_

  - [x] 1.5 Runtime 진입점 및 orchestrator 리팩토링 테스트
    - `invoke()` payload 파싱 및 응답 형식 테스트
    - 상태 전이 (IDLE → ... → IDLE) 테스트
    - Inference profile fallback 동작 테스트
    - _Requirements: 1.1, 1.2, 1.7_

- [x] 2. Checkpoint — AgentCore Runtime 부팅 및 응답 확인
  - Ensure all Kiro-generated tests pass, then validate AWS integration behavior manually if needed.

- [x] 3. AgentCore Memory 통합
  - [x] 3.1 `AgentCoreMemory` wrapper 클래스 구현 (v1 in-memory placeholder 대체)
    - `agent/lib/memory/agentcore_memory.py` 생성: `boto3 bedrock-agentcore` 클라이언트
    - `store_session_event()`: `create_memory_event` API (short-term)
    - `store_long_term_facts()`: `batch_create_memory_records` API (long-term — 고객 특성, 보안 요구, 리전 제약)
    - `retrieve_customer_context()`: `retrieve_memory_records` API (customer-scoped namespace `/customers/{customer}/`)
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 3.2 Memory API 실패 시 degraded mode 구현
    - 모든 Memory API 호출을 try/except로 감싸기; 실패 시 bounded session history만으로 동작
    - `docs/{docId}/status` 채널로 warning 상태 발행
    - _Requirements: 2.5_

  - [x] 3.3 Memory를 Parent Orchestrator 흐름에 연결
    - `handle_message()` 시작 시: `retrieve_customer_context()` 호출하여 bounded history에 long-term context 보충
    - 처리 완료 후: `store_session_event()` 호출하여 세션 이벤트 저장
    - 장기 사실 감지 시: `store_long_term_facts()` 호출
    - _Requirements: 2.1, 2.2, 2.3, 11.3_

  - [x] 3.4 Memory wrapper mocked boto3 테스트
    - `store_session_event()`, `store_long_term_facts()`, `retrieve_customer_context()` mocked boto3 테스트
    - Degraded mode 동작 테스트 (API 실패 시)
    - _Requirements: 2.1, 2.2, 2.3, 2.5_

- [x] 4. AgentCore Gateway 공통 클라이언트 + Lambda tool targets
  - [x] 4.1 공통 Gateway 클라이언트 생성 (`agent/lib/gateway/agentcore_gateway.py`)
    - v1의 `agent/app/cost/gateway_client.py` stub을 공통 레이어로 승격
    - `AgentCoreGatewayClient` 클래스: `call_tool(tool_name, params)`, `call_tool_safe(tool_name, params)`
    - Cost/Architecture/Formatter/Parent 모두 이 공통 클라이언트 사용
    - 실패 시: 현재 Document_State 보존, error status 발행, partial mutation 방지
    - _Requirements: 3.1, 3.3, 3.4, 3.5, 3.6_

  - [x] 4.2 6개 Gateway target Lambda handler 생성
    - `agent/lambdas/gateway_tools/validate_template.py` — APN 템플릿 섹션/순서 검증
    - `agent/lambdas/gateway_tools/generate_diagram.py` — .drawio + preview 생성
    - `agent/lambdas/gateway_tools/estimate_cost.py` — Calculator MCP wrapper
    - `agent/lambdas/gateway_tools/calc_staffing.py` — deterministic 인건비 계산
    - `agent/lambdas/gateway_tools/export_docx.py` — DOCX 생성 + S3 저장
    - `agent/lambdas/gateway_tools/build_milestones.py` — phase/deliverable/역할 동기화
    - _Requirements: 3.1, 3.2_

  - [x] 4.3 Gateway 클라이언트 mocked 호출 테스트
    - `call_tool()` mocked boto3 응답 테스트
    - 실패 시 상태 보존 + error status 발행 테스트
    - 각 Lambda handler sample input/output 테스트
    - _Requirements: 3.1, 3.3, 3.4, 3.6_

- [x] 5. Checkpoint — Gateway 도구 호출 가능 확인
  - Ensure all Kiro-generated tests pass, then validate AWS integration behavior manually if needed.

- [x] 6. Multi-agent 구조 (Parent Runtime 내부 logical agents)
  - [x] 6.1 Discovery Agent를 `strands.Agent()` logical agent로 리팩토링
    - `agent/app/discovery/discovery_agent.py`: `Agent(model_id=CHILD_MODEL, system_prompt=DISCOVERY_PROMPT)`
    - `collect_info()`: 입력 분석 → 누락 항목 판별 → 구조화 또는 재질문
    - `classify_missing_fields()`: draft-required vs export-required 분류
    - draft-required만 누락 시 초안 생성 차단하지 않음
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

  - [x] 6.2 Architecture Agent를 `strands.Agent()` logical agent로 리팩토링
    - `agent/app/architecture/architecture_agent.py`: `Agent(model_id=CHILD_MODEL, system_prompt=ARCHITECTURE_PROMPT)`
    - `analyze_existing()`: .drawio 파싱 → AWS 서비스 추출 → 해석/보완 → 원본 S3 저장 + preview 생성/재사용
    - `design_new()`: 프로젝트 요구사항 → AWS 아키텍처 초안 생성
    - `generate_diagram()`: 공통 Gateway 클라이언트로 `generate_architecture_diagram` 호출
    - _Requirements: 5.1, 5.2, 5.3, 16.1, 16.2, 16.3, 16.4_

  - [x] 6.3 Staffing Agent를 `strands.Agent()` logical agent로 리팩토링
    - `agent/app/staffing/staffing_agent.py`: `Agent(model_id=CHILD_MODEL, system_prompt=STAFFING_PROMPT)`
    - `recommend()`: preset 선택 → 역할별 추천안 → `ai_recommended`로 top-level `staffing_plan`에 저장
    - `validate_rates()`: `rate_card.json` 범위 검증
    - Team UI 탭은 `staffing_plan`의 뷰이며, `stakeholders`는 연락처/조직 정보 전용
    - _Requirements: 7.1, 7.2, 7.4, 7.5, 7.6_

  - [x] 6.4 Cost Agent를 `strands.Agent()` logical agent로 리팩토링
    - `agent/app/cost/cost_agent.py`: `Agent(model_id=CHILD_MODEL, system_prompt=COST_PROMPT)`
    - `calculate_staffing_cost()`: deterministic 계산 (`staffing_plan` 전용, `stakeholders` 미사용)
    - `calculate_aws_cost()`: 공통 Gateway 클라이언트로 `estimate_cost` 호출
    - `generate_fallback_card()`: 실패/미지원 서비스 → `manual_estimate_items` + FallbackCard
    - `document_local_summary` 항상 보존 (외부 링크 만료 대비)
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8_

  - [x] 6.5 Reviewer Agent를 `strands.Agent()` logical agent로 리팩토링
    - `agent/app/reviewer/reviewer_agent.py`: `Agent(model_id=CHILD_MODEL, system_prompt=REVIEWER_PROMPT)`
    - `review()`: 필수 섹션 누락 + 순서 검증 + 숫자 불일치
    - `classify_issues()`: blocking vs non-blocking 분류
    - `calculate_completion_score()`: 0.0~1.0
    - _Requirements: 13.1, 13.2, 17.1_

  - [x] 6.6 Formatter Agent를 `strands.Agent()` logical agent로 리팩토링
    - `agent/app/formatter/formatter_agent.py`: `Agent(model_id=CHILD_MODEL, system_prompt=FORMATTER_PROMPT)`
    - `export_docx()`: APN 템플릿 순서 정렬 → 공통 Gateway 클라이언트로 `export_docx` 호출 → S3 저장 → 다운로드 링크
    - _Requirements: 13.3, 13.4_

  - [x] 6.7 Parent Orchestrator에 모든 sub-agent 위임 연결
    - `delegate_task()`: 실제 sub-agent 인스턴스로 dispatch (Runtime 내부 함수 호출)
    - Hub-and-spoke 패턴: 모든 조율 Parent 경유, sub-agent 간 직접 통신 없음
    - 이중 진입 모드 분기: `.drawio` → `architecture_present` → Architecture Agent; 텍스트 → `architecture_absent` → Discovery Agent
    - Auditable mapping: user message → delegated task → result patches
    - v1 `handler.py` 인라인 `_invoke_bedrock()` 호출을 AgentCore Runtime 기반으로 대체
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 5.1, 5.2, 5.3_

  - [x] 6.8 Sub-agent 위임 및 이중 진입 모드 테스트
    - Discovery Agent `collect_info()` 다양한 입력 완성도 테스트
    - Architecture Agent 이중 진입 모드 (analyze_existing vs design_new) 테스트
    - Staffing Agent preset 선택 및 rate 검증 테스트
    - Cost Agent deterministic 계산 및 fallback card 생성 테스트
    - Reviewer Agent completion score 계산 테스트
    - Parent 위임 라우팅 및 hub-and-spoke 패턴 테스트
    - _Requirements: 4.1, 4.2, 4.3, 5.1, 5.2, 6.1, 7.1, 8.1, 13.1, 17.1_

- [x] 7. Checkpoint — Multi-agent 위임 end-to-end 동작 확인
  - Ensure all Kiro-generated tests pass, then validate AWS integration behavior manually if needed.

- [x] 8. DynamoDB optimistic locking 구현
  - [x] 8.1 `agent/lib/storage/dynamodb.py` in-memory → 실제 DynamoDB 전환
    - `boto3.resource("dynamodb")` 실제 호출로 교체
    - `get()`: `table.get_item(Key={"document_id": doc_id})`
    - `update()`: `ConditionExpression` 기반 optimistic locking (`Attr("version").eq(expected_version)`)
    - `version` 자동 증가 + `updated_at` 갱신
    - `VersionConflictError` 실제 발생
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

  - [x] 8.2 OnPublish Lambda v2 patch validation 업그레이드
    - `agent/lambdas/on_publish/handler.py`: patch `version` vs DynamoDB 현재 version 검증
    - `operations[].path` 유효성 검증, `source` 허용값 검증
    - 실패 시: patch 차단 + `docs/{docId}/status`로 error 발행 + version conflict 정보
    - OnPublish는 version validation 역할. 실제 optimistic locking은 Parent DynamoDB update 시점
    - _Requirements: 10.5, 10.6, 9.3_

  - [x] 8.3 Patch history persistence 구현
    - `doc-agent-patch-history` 테이블에 patch write 구현
    - user message → delegated task → resulting patches 추적 저장
    - `version_before`, `version_after` 기록
    - _Requirements: 10.3, 4.6_

  - [x] 8.4 Optimistic locking 및 OnPublish validation 테스트
    - Version conflict 감지 및 `VersionConflictError` 발생 테스트
    - OnPublish Lambda patch validation (유효/무효 path, version mismatch, 무효 source) 테스트
    - 동시 업데이트 시나리오 테스트
    - Patch history 저장 및 조회 테스트
    - _Requirements: 10.4, 10.5, 10.6_

- [x] 9. Checkpoint — Optimistic locking 충돌 방지 확인
  - Ensure all Kiro-generated tests pass, then validate AWS integration behavior manually if needed.

- [x] 10. Milestone 동기화 및 리뷰 연결
  - [x] 10.1 Milestone 동기화를 Parent Orchestrator에 연결
    - `staffing_plan` 또는 `scope_of_work` 변경 시 공통 Gateway 클라이언트로 `build_milestone_summary` 호출
    - `sections.milestones` 재생성 (phase 일정, deliverable, 담당 역할)
    - `stakeholders` 연락처 정보는 milestone 계산의 직접 입력으로 사용하지 않음
    - _Requirements: 14.1, 14.2, 14.3_

  - [x] 10.2 리뷰/export 흐름을 Parent Orchestrator에 연결
    - 리뷰 요청: Reviewer Agent 위임 → Gateway `validate_template_constraints` → blocking issues + warnings
    - Export 요청: Formatter Agent 위임 → Gateway `export_docx` → S3 다운로드 링크
    - _Requirements: 13.1, 13.2, 13.3, 13.4_

  - [x] 10.3 사용자 편집 → 비용 재계산 트리거 구현
    - `staffing_plan` 값 수정 시: `user_edited: true`, `status: user_modified`, 원래 `ai_recommended` 보존
    - Cost Agent `calculate_staffing_cost()` 재계산 트리거
    - `cost_breakdown` 섹션 갱신
    - _Requirements: 7.3, 8.3, 12.2, 12.3_

  - [x] 10.4 Milestone 동기화 및 리뷰 연결 테스트
    - staffing_plan 변경 시 milestone 재생성 테스트
    - 리뷰 흐름 blocking issues + warnings 반환 테스트
    - 사용자 편집 → 비용 재계산 트리거 테스트
    - _Requirements: 14.1, 13.1, 8.3_

- [x] 11. Conversation history 저장소 구현
  - [x] 11.1 서버 측 conversation history 저장/조회 API 구현
    - `POST /documents/{docId}/history` — 대화 이력 저장 (canonical store)
    - `GET /documents/{docId}/history` — 대화 이력 조회 (document reopen 시 서버 reload)
    - DynamoDB 또는 별도 테이블에 `document_id`, `session_id`, `messages`, `bounded_window`, `total_count` 저장
    - _Requirements: 11.2_

  - [x] 11.2 프런트엔드 conversation history 관리 구현
    - `ChatPanel`: bounded N턴 (기본 20) history만 API 호출에 포함
    - 문서 재오픈 시: 서버에서 history reload → `localStorage`에 캐시
    - `localStorage`는 빠른 복원용 클라이언트 캐시로만 사용, canonical store는 서버
    - _Requirements: 11.1, 11.2_

  - [x] 11.3 Conversation history 저장/조회 테스트
    - 서버 API 저장/조회 round-trip 테스트
    - Bounded window 제한 테스트
    - _Requirements: 11.1, 11.2_

- [x] 12. 프런트엔드 업그레이드
  - [x] 12.1 Zustand store를 AppSync-authoritative patch 경로로 업데이트
    - `documentStore.ts`: 문서 상태 변경은 AppSync `patch` 채널 수신으로만 적용
    - `/invocations` HTTP 응답은 채팅 메시지 + 상태 메타데이터만 반영, 문서 상태 직접 적용하지 않음
    - AppSync `patch` 채널 구독 handler: JSON Patch operations → 로컬 상태 적용
    - REST fallback: AppSync 연결 끊김 시 `GET /documents/{docId}`로 전체 상태 재조회
    - _Requirements: 9.1, 9.2, 9.5_

  - [x] 12.2 AI 추천 시각 배지 및 completion score 구현
    - 모든 섹션 렌더러에서 `ai_recommended` 값: 노란색 배경 + `AI` 배지
    - `CompletionBadge` 컴포넌트: 0.0~1.0 score 상단 표시
    - `ExportButton` 컴포넌트: `blocking_issues` 비어있을 때만 활성화
    - _Requirements: 11.4, 11.5, 11.6, 17.2, 17.3_

  - [x] 12.3 TeamSection inline editing 강화 — staffing_plan 바인딩
    - 인라인 편집 대상: `staffing_plan.roles[roleId].{field}.user_input`에만 기록
    - Team 탭은 UI 이름, 실제 데이터는 top-level `staffing_plan`
    - `stakeholders`는 연락처/조직 정보 전용, 편집 대상 아님
    - 편집 시: `recalculateAll()` 로컬 실행 → REST API `/documents/{docId}/user-input` 전송
    - _Requirements: 11.7, 7.3, 7.6_

  - [x] 12.4 ArchitectureSection .drawio 업로드 및 preview 구현
    - `.drawio` 파일 업로드 input
    - `.png`/`.svg` preview S3 artifact URL 표시
    - _Requirements: 11.8_

  - [x] 12.5 StatusBar 에이전트 상태 표시 구현
    - ChatPanel 내 StatusBar: processing, idle, error, degraded 상태 표시
    - AppSync `docs/{docId}/status` 채널 구독
    - Degraded mode 경고 표시 (Memory API 실패, inference profile 불가)
    - _Requirements: 9.4, 1.7, 2.5_

  - [x] 12.6 프런트엔드 핵심 테스트
    - TeamSection inline edit → `staffing_plan.roles[roleId].{field}.user_input` 기록 흐름 테스트
    - Zustand store AppSync patch 적용 테스트
    - ExportButton enable/disable 로직 테스트
    - CompletionBadge 다양한 score 렌더링 테스트
    - _Requirements: 11.4, 11.5, 11.6, 11.7_

- [x] 13. Checkpoint — 프런트엔드 patch 및 배지 정상 렌더링 확인
  - Ensure all Kiro-generated tests pass, then validate AWS integration behavior manually if needed.

- [x] 14. Document_State 스키마 업그레이드
  - [x] 14.1 Pydantic v2 모델 v2 필드 확장
    - `document_state.py`: `created_at`, `updated_at` 타임스탬프 직렬화 처리
    - `FieldValue`에 `user_edited`, `reason`, `source_patterns`, `confidence` 메타데이터 확인
    - `CostBreakdownSection` 상세 스키마: `staffing_cost`, `aws_service_cost`, `document_local_summary`
    - `ConversationHistory` 모델: `document_id`, `session_id`, `messages`, `bounded_window`, `total_count`
    - _Requirements: 10.2, 12.1, 12.4, 12.5_

  - [x] 14.2 `patch.py` v2 patch validation 확장
    - `AgentStatus.degraded` enum 값 추가
    - Patch 모델에 `version_before`, `version_after` 필드 추가 (patch history 추적용)
    - _Requirements: 9.4, 10.5_

  - [x] 14.3 스키마 직렬화/역직렬화 테스트
    - FieldValue 4속성 패턴 round-trip 테스트
    - DocumentState 전체 직렬화 (v2 필드 포함) 테스트
    - Patch 모델 version tracking 필드 테스트
    - _Requirements: 12.1, 12.5_

- [x] 15. 배포 스크립트 업데이트 (Terraform + Python CDK)
  - [x] 15.1 Terraform에 6개 Gateway target Lambda 리소스 추가
    - `aws_lambda_function` 6개: validate-template, generate-diagram, estimate-cost, calc-staffing, export-docx, build-milestones
    - 각 Lambda IAM 권한 (DynamoDB, S3, Bedrock)
    - AgentCore Gateway 호출용 `aws_lambda_permission`
    - Conversation history DynamoDB 테이블 (필요 시)
    - _Requirements: 15.1, 3.2_

  - [x] 15.2 실제 AgentCore CDK deploy 스크립트 구현
    - `infra/cdk/deploy.py`: `boto3 bedrock-agentcore` 클라이언트 실제 호출
    - AgentCore Runtime 생성 (agent/ 코드 ZIP 패키징)
    - AgentCore Endpoint 생성
    - AgentCore Gateway 생성 + 6개 Lambda target MCP 도구 스키마 등록
    - AgentCore Memory 인스턴스 생성
    - _Requirements: 15.2_

  - [x] 15.3 CDK destroy 스크립트 구현
    - `infra/cdk/destroy.py`: AgentCore Runtime, Endpoint, Gateway, Memory 리소스 정리
    - _Requirements: 15.6_

  - [x] 15.4 통합 deploy/destroy 스크립트 업데이트
    - `deploy.sh`: Terraform apply → AgentCore CDK deploy → (선택) Front build/deploy
    - `destroy.sh`: AgentCore CDK destroy → Terraform destroy
    - `AWS_PROFILE=mzadmin`, `ap-northeast-2` 기본 실행 컨텍스트
    - API Gateway를 기본 API 엔드포인트로 사용 (Lambda Function URL은 SCP 차단 시 fallback)
    - _Requirements: 15.3, 15.4, 15.5, 15.6, 15.7_

  - [x] 15.5 API Gateway에 `/invocations` 라우트 추가
    - `POST /invocations` → AgentCore Runtime invoke로 프록시
    - 기존 라우트 (`/documents/{docId}/*`) 유지
    - _Requirements: 15.1, 15.7_

  - [x] 15.6 배포 스크립트 통합 테스트
    - Terraform plan dry-run으로 예상 리소스 확인
    - CDK deploy 스크립트 mocked boto3 호출 테스트
    - _Requirements: 15.1, 15.2_

- [x] 16. Checkpoint — 배포 스크립트 에러 없이 실행 확인
  - Ensure all Kiro-generated tests pass, then validate AWS integration behavior manually if needed.

- [x] 17. 통합 연결 및 end-to-end 흐름
  - [x] 17.1 전체 채팅 흐름 연결: Frontend → API Gateway → AgentCore Runtime → sub-agents → DynamoDB → AppSync → Frontend
    - `handler.py`의 `/invocations` POST를 AgentCore Runtime invoke로 라우팅 (v1 인라인 `_invoke_bedrock()` 대체)
    - `/documents/{docId}/chat` POST는 backward-compatible alias로 유지
    - AppSync patch 채널이 문서 업데이트를 프런트엔드에 전달하는지 검증
    - _Requirements: 4.7, 9.1, 9.2_

  - [x] 17.2 4속성 패턴 full stack 연결
    - Sub-agent 출력이 올바른 `ai_recommended` / `calculated` 필드에 기록되는지 확인
    - 사용자 편집이 `user_input` + `user_edited: true` + `status: user_modified`로 기록되는지 확인
    - `calculated` 값이 입력 데이터 변경 시 자동 재계산되는지 확인
    - 값 해석 우선순위: `user_input > ai_recommended > calculated`
    - _Requirements: 12.1, 12.2, 12.3, 12.4_

  - [x] 17.3 실시간 상태 발행 연결
    - 모든 에이전트 상태 전이가 `docs/{docId}/status`로 발행되는지 확인
    - Gateway tool 실패 시 error status 발행 확인
    - Degraded mode (Memory 실패, inference profile 불가) warning status 발행 확인
    - _Requirements: 9.4, 3.4, 1.7, 2.5_

  - [x] 17.4 End-to-end 통합 테스트
    - 채팅 메시지 → agent 위임 → patch 생성 → DynamoDB 갱신 → AppSync 발행 테스트
    - 사용자 편집 → 비용 재계산 → patch broadcast 테스트
    - 에러 시나리오: Gateway 실패, Memory 실패, version conflict 테스트
    - _Requirements: 4.1, 9.1, 10.4, 3.6_

- [x] 18. Final checkpoint — 전체 시스템 검증
  - Ensure all Kiro-generated tests pass, then validate AWS integration behavior manually if needed.

## Notes

- 핵심 테스트 (1.5, 3.4, 4.3, 6.8, 8.4, 12.6)는 required — Kiro가 작성·실행
- `*` 표시 테스트 (10.4, 11.3, 14.3, 15.6, 17.4)는 optional — 시간에 따라 조정
- Checkpoint 문구: "Ensure all Kiro-generated tests pass, then validate AWS integration behavior manually if needed."
- Gateway 클라이언트는 `agent/lib/gateway/agentcore_gateway.py` 공통 레이어 — Cost/Architecture/Formatter/Parent 공유
- Conversation history canonical store는 server-side durable store, `localStorage`는 client cache only
- Patch history는 `doc-agent-patch-history` 테이블에 user message → task → patches 추적 저장
- 프런트 기본 HTTP 진입점은 API Gateway, `POST /invocations`는 내부적으로 AgentCore Runtime invoke로 라우팅
- OnPublish Lambda는 patch validation + version validation 역할 (optimistic locking은 Parent DynamoDB update 시점)
- Memory API: short-term은 `create_memory_event`, long-term은 `batch_create_memory_records`, 조회는 `retrieve_memory_records`
- `/invocations` 응답은 `chat_response + version + status` 메타데이터만, 문서 상태 반영은 AppSync patch 채널만 authoritative
- Team 탭은 UI 이름, 실제 편집 대상은 top-level `staffing_plan`, `stakeholders`는 연락처/조직 정보 전용
- Sub-agents는 Parent Runtime 내부 logical agents (독립 Runtime 분리는 필요 시 후속)
- Python 3.12 (agent/), TypeScript (front/)
- AWS Profile: mzadmin, Region: ap-northeast-2
