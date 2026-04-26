# Implementation Plan: AgentCore 멀티에이전트 문서 생성 시스템

## Overview

해커톤용 AgentCore 멀티에이전트 문서 생성 시스템을 4단계로 구현한다. 사용자가 확정한 개발 순서(agent 뼈대 → 사용자 입력/계산 → 실시간/에이전트 연결 → 외부 기능 연결)를 따르며, 각 단계가 이전 단계 위에 점진적으로 쌓이는 구조이다. 프로젝트 구조는 `infra/`, `agent/`, `front/` 3개 디렉토리로 고정한다.

## Tasks

- [x] 1. 1단계 — agent 뼈대: Document_State 스키마 및 타입 정의
  - [x] 1.1 `agent/lib/schema/` 에 Document_State JSON 스키마 정의
    - `document_state.py` 파일에 전체 Document_State의 Python dataclass 또는 Pydantic 모델 정의
    - `meta`, `sections` (cover, executive_summary, stakeholders, success_criteria, assumptions, scope_of_work, architecture, milestones, cost_breakdown, acceptance, resources_cost_estimates), top-level `staffing_plan`, `completion_score`, `blocking_issues`, `warnings` 포함
    - `version`, `created_at`, `updated_at`, `mode` (architecture_present | architecture_absent) 필드 포함
    - _Requirements: 10.1, 10.4_

  - [x] 1.2 4속성 패턴 타입 정의
    - `field_types.py` 파일에 `FieldValue` 타입 정의: `user_input`, `ai_recommended`, `calculated`, `status` + field-level metadata (`user_edited`, `reason`, `source_patterns`, `confidence`)
    - `status` enum 정의: `empty`, `recommended`, `user_modified`, `confirmed`, `calculated`
    - 축약형 `CalculatedOnly` 타입 정의 (read-only derived field용)
    - _Requirements: 10.1, 10.2, 10.5_

  - [x] 1.3 Staffing Plan 상세 스키마 정의
    - `staffing_plan.py` 파일에 역할별 `count`, `allocation_pct`, `rate_per_hour`, `phase_hours`, `total_hours`, `total_cost` 구조 정의
    - `grand_total_hours`, `grand_total_cost` 축약형 필드 포함
    - _Requirements: 5.2, 6.1_

  - [x] 1.4 Patch 및 AppSync 메시지 타입 정의
    - `patch.py` 파일에 `Patch`, `PatchOperation` 타입 정의
    - `patch_id`, `doc_id`, `agent`, `timestamp`, `operations`, `version` 필드 포함
    - `AgentStatus` 타입 정의 (processing, idle, error)
    - _Requirements: 8.1, 8.3_

  - [ ]* 1.5 스키마 유닛 테스트 작성
    - Document_State 생성, 4속성 패턴 status 전이, 축약형 필드 검증 테스트
    - _Requirements: 10.1, 10.2, 10.5_

- [x] 2. 1단계 — agent 뼈대: 시간/비용 계산 모듈
  - [x] 2.1 `agent/lib/calculation/` 에 인건비 계산 순수 함수 구현
    - `staffing_cost.py` 파일에 `calculate_role_total_hours()`, `calculate_role_total_cost()`, `calculate_grand_total()` 함수 구현
    - 입력: role별 count, allocation_pct, rate_per_hour, phase별 hours
    - 출력: total_hours, role_total_cost, grand_total_cost
    - 모든 함수는 순수 함수로 구현 (외부 상태 의존 없음)
    - _Requirements: 6.1, 6.2_

  - [x] 2.2 비용 재계산 트리거 함수 구현
    - `recalculate.py` 파일에 `recalculate_costs()` 함수 구현
    - staffing_plan 변경 시 관련 calculated 필드 일괄 재계산
    - _Requirements: 6.3, 10.3_

  - [ ]* 2.3 계산 모듈 유닛 테스트 작성
    - 역할별 비용 계산, grand total 계산, 재계산 트리거 검증
    - _Requirements: 6.1, 6.2, 6.3_

- [x] 3. 1단계 — agent 뼈대: Preset 데이터 파일 생성
  - [x] 3.1 `agent/data/presets/` 에 role_catalog.json 생성
    - GenAI 멀티에이전트 PoC 기준 역할 정의: Project Manager, Solutions Architect, ML Engineer, Backend Developer, Frontend Developer, QA Engineer
    - 각 역할의 display_name, description, default skills 포함
    - _Requirements: 5.1_

  - [x] 3.2 rate_card.json 생성
    - 역할별 단가 범위 (min, default, max) 정의
    - _Requirements: 5.4_

  - [x] 3.3 staffing_presets.json 생성
    - `genai_multi_agent` 프로젝트 유형 기준 역할 조합 템플릿
    - 역할별 기본 count, allocation_pct, rate_per_hour 포함
    - _Requirements: 5.1, 5.2_

  - [x] 3.4 phase_hour_patterns.json 생성
    - `genai_multi_agent` 유형의 phase별 시간 배분 패턴 (discovery, development, testing)
    - _Requirements: 5.1_

  - [x] 3.5 project_type_rules.json 생성
    - 프로젝트 유형 판별 규칙 (keywords, conditions → type 매핑)
    - _Requirements: 5.1_

- [x] 4. 1단계 — agent 뼈대: Parent Orchestrator skeleton
  - [x] 4.1 `agent/app/parent/` 에 Parent Orchestrator 기본 구조 구현
    - `orchestrator.py` 파일에 `ParentOrchestrator` 클래스 구현
    - `handle_message(doc_id: str, user_message: str)` → 반환: `TaskPlan` (task_plan, patch_proposals, chat_response, status_updates)
    - `delegate_task(agent_name: str, task: Task, doc_state: DocumentState)` → 반환: `AgentResult` (stub)
    - 상태 전이: IDLE → PLANNING → DELEGATING → PATCHING → RESPONDING → IDLE
    - 실제 Bedrock 호출 없이 task plan과 patch proposal만 반환
    - _Requirements: 18.1, 18.2, 18.3_

  - [x] 4.2 Task Plan 및 Patch Proposal 생성 로직 구현
    - `task_planner.py` 파일에 사용자 메시지 분석 → 작업 계획 생성 로직
    - `patch_builder.py` 파일에 작업 결과 → Patch 변환 로직
    - _Requirements: 18.2, 18.5_

  - [x] 4.3 DynamoDB Document_State CRUD 헬퍼 구현
    - `agent/lib/storage/dynamodb.py` 파일에 Document_State 조회/저장/버전 관리 함수
    - optimistic locking (version 기반) 구현
    - 초기에는 in-memory 또는 placeholder 구현을 허용하고, 2단계 API 연동 시 DynamoDB 실연결로 전환
    - _Requirements: 10.4, 8.3_

- [x] 5. Checkpoint — agent 뼈대 검증
  - 스키마 정의, 계산 모듈, preset 데이터, Parent Orchestrator skeleton이 정상 동작하는지 수동 확인
  - 필요 시 간단한 Python 검증 스크립트(`agent/scripts/manual_check.py`)로 확인
  - 구현 중 애매한 점이 있으면 사용자에게 질문

- [x] 6. 1단계 — front 기본 화면 구현 + infra/API skeleton
  - [x] 6.1 `infra/` 폴더 skeleton 생성
    - `infra/terraform/` 에 `provider.tf` placeholder (region only, profile은 실행 컨텍스트에서 주입), `main.tf` placeholder 생성
    - `infra/cdk/` 에 `deploy.py`, `destroy.py` placeholder 생성
    - `infra/scripts/deploy.sh`, `infra/scripts/destroy.sh` placeholder 생성
    - _Requirements: 16.5, 16.6_

  - [x] 6.2 `front/` 프로젝트 초기화 및 SplitLayout 구현
    - React + Vite + TypeScript 프로젝트 셋업
    - `SplitLayout` 컴포넌트: 좌측 ChatPanel, 우측 DocumentPanel 분할 레이아웃
    - 리사이즈 가능한 분할 구현
    - _Requirements: 9.1, 9.2_

  - [x] 6.3 ChatPanel 기본 구현
    - `ChatPanel`, `MessageList`, `ChatInput`, `StatusBar` 컴포넌트
    - 더미 메시지 렌더링 (API 연결 없음)
    - _Requirements: 9.1_

  - [x] 6.4 DocumentPanel 및 TabBar 구현
    - `DocumentPanel`, `TabBar` 컴포넌트
    - 10개 탭: Cover, Overview, Team, Success Criteria, Assumptions, Scope, Architecture, Milestones, Cost, Acceptance
    - Resources & Cost Estimates는 Cost 탭 내 서브섹션
    - `CompletionBadge`, `ExportButton` 컴포넌트
    - _Requirements: 9.3, 17.2_

  - [x] 6.5 섹션 렌더러 기본 구현
    - 각 탭에 대응하는 섹션 컴포넌트 (CoverSection, OverviewSection, TeamSection, SuccessCriteriaSection, AssumptionsSection, ScopeSection, ArchitectureSection, MilestonesSection, CostSection, AcceptanceSection)
    - 더미 Document_State 데이터로 렌더링
    - _Requirements: 9.2, 9.3_

  - [x] 6.6 클라이언트 상태 관리 셋업
    - Zustand 또는 React state로 Document_State 클라이언트 사본 관리
    - 더미 초기 상태 정의
    - _Requirements: 10.1_

- [x] 7. Checkpoint — 1단계 전체 검증
  - agent 뼈대 + front 기본 화면이 독립적으로 동작하는지 수동 확인
  - front에서 탭 전환, 더미 데이터 렌더링이 정상인지 확인
  - 필요 시 간단한 Python 검증 스크립트로 확인. 구현 중 애매한 점이 있으면 사용자에게 질문

- [x] 8. 2단계 — 팀/일정/리소스 표 UI (편집 가능)
  - [x] 8.1 TeamSection에 편집 가능한 표 구현 (staffing_plan 편집 UI)
    - staffing_plan의 역할별 count, allocation_pct, rate_per_hour, phase별 hours 편집 가능 표
    - 인라인 편집 시 로컬 상태 즉시 갱신 (optimistic local update)
    - 수정 시 `user_input`으로 staffing_plan 갱신
    - 이 단계에서는 AppSync 없이 write API + 로컬 즉시 갱신으로 동작
    - _Requirements: 9.4, 5.3, 10.2_

  - [x] 8.2 CostSection에 인건비 표 + AWS 비용 breakdown 표시
    - 역할별 비용 요약 표, grand total 표시
    - AWS 서비스별 비용 breakdown 영역 (초기에는 빈 상태)
    - calculator.aws 링크 영역, fallback card 영역
    - _Requirements: 6.2, 7.2, 7.3_

  - [x] 8.3 MilestonesSection에 phase/deliverable/역할 표시
    - phase별 일정, deliverable, 담당 역할 표 렌더링
    - 초기에는 scope/staffing_plan 입력 기반 placeholder 렌더링 (실제 milestone 생성 로직은 18.2에서 구현)
    - _Requirements: 15.2_

- [x] 9. 2단계 — 계산값 실시간 반영 + Write API 구현
  - [x] 9.1 `agent/app/api/` 에 Document Write/Read API 구현
    - `document_api.py` 파일에 REST API 엔드포인트 구현 (Parent Runtime에 붙는 간단한 HTTP layer로 구현)
    - `POST /documents/{docId}/user-input`: 사용자 편집값을 staffing_plan 또는 sections에 user_input으로 저장 → DynamoDB 갱신
    - `GET /documents/{docId}`: Document_State 전체 조회 (fallback용)
    - `POST /documents/{docId}/review`: 리뷰 요청 → Reviewer Agent 호출
    - `POST /documents/{docId}/export`: DOCX export 요청 → Formatter Agent 호출
    - _Requirements: 9.4, 8.6, 11.1, 12.1_

  - [x] 9.2 프런트엔드에서 staffing_plan 수정 시 비용 재계산 연동
    - TeamSection 편집 → calculation 모듈 호출 → CostSection 즉시 갱신
    - 재계산은 우선 프런트 로컬 상태에서 즉시 수행하고, write API 저장은 별도로 수행한다
    - `calculate_role_total_hours()`, `calculate_role_total_cost()`, `calculate_grand_total()` 프런트엔드 포팅 또는 API 호출
    - _Requirements: 6.3, 10.3_

  - [x] 9.3 프런트엔드 Write API 연동 구현
    - `POST /documents/{docId}/user-input` 호출로 서버에 user_input 변경 전송
    - `GET /documents/{docId}` 로 Document_State 전체 조회 (fallback용)
    - 흐름: front edit → optimistic local update → write API → DDB 저장 (AppSync patch는 3단계에서 추가)
    - _Requirements: 9.4, 8.6_

  - [ ]* 9.4 계산 연동 통합 테스트 작성
    - 팀 표 수정 → 비용 재계산 → UI 반영 흐름 검증
    - _Requirements: 6.3_

- [x] 10. 2단계 — preset 추천 로직 연결
  - [x] 10.1 `agent/app/staffing/` 에 Staffing Agent 구현
    - `staffing_agent.py` 파일에 `StaffingAgent` 클래스 구현
    - `recommend()`: project_type_rules.json으로 유형 판별 → staffing_presets.json에서 preset 선택 → role_catalog.json + rate_card.json 기반 추천안 생성
    - `validate_rates()`: rate_card.json 범위 검증
    - _Requirements: 5.1, 5.2, 5.4_

  - [x] 10.2 preset 추천 결과를 Document_State의 staffing_plan에 ai_recommended로 저장
    - 각 역할의 count, allocation_pct, rate_per_hour, reason, source_patterns, confidence 포함
    - _Requirements: 5.2, 10.1_

  - [x] 10.3 프런트엔드에서 AI 추천값 표시 및 사용자 수정 흐름 구현
    - TeamSection에서 ai_recommended 값 표시 (시각적 구분)
    - 사용자 수정 시 user_edited=true, status="user_modified" 갱신
    - _Requirements: 5.3, 10.2, 10.6_

- [x] 11. Checkpoint — 2단계 검증
  - 팀 표 편집, 비용 재계산, preset 추천이 정상 동작하는지 수동 확인
  - hours 변경 시 cost가 즉시 갱신되는지 확인
  - write API → DDB 저장 → front 반영 흐름이 동작하는지 확인
  - 필요 시 간단한 Python 검증 스크립트로 확인. 구현 중 애매한 점이 있으면 사용자에게 질문

- [x] 12. 3단계 — AppSync Events patch 반영
  - [x] 12.1 AppSync Events 채널 구독 구현 (프런트엔드)
    - `docs/{docId}/patch` 채널 구독 → JSON Patch 적용으로 로컬 상태 갱신
    - `docs/{docId}/status` 채널 구독 → StatusBar에 에이전트 상태 표시
    - `docs/{docId}/chat` 채널 구독 → ChatPanel에 에이전트 응답 표시
    - _Requirements: 8.1, 8.2, 8.4_

  - [x] 12.2 OnPublish Lambda 구현
    - Lambda 배포 정의는 `infra/terraform/`, 함수 소스는 `agent/lambdas/on_publish/` 에 작성
    - path 유효성 검증, version optimistic locking, source 검증
    - 검증 실패 시 patch 차단 + status 채널로 오류 발행
    - _Requirements: 8.3_

  - [x] 12.3 REST polling fallback 구현
    - AppSync 연결 끊김 감지 → `GET /documents/{docId}` 로 전체 상태 재조회
    - _Requirements: 8.6_

  - [x] 12.4 Parent Orchestrator에서 patch 발행 로직 구현
    - `publish_patch()`: DynamoDB 갱신 후 AppSync Events로 patch 발행
    - `publish_status()`: 에이전트 처리 상태 발행
    - _Requirements: 8.1, 8.4_

- [x] 13. 3단계 — Parent Orchestrator에서 patch plan 반환
  - [x] 13.1 Discovery Agent 구현
    - `agent/app/discovery/discovery_agent.py` 에 `DiscoveryAgent` 클래스 구현
    - `collect_info()`: 입력 분석 → 누락 항목 판별 → 구조화 또는 재질문 생성
    - `classify_missing_fields()`: draft-required vs export-required 분류
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 13.2 이중 진입 모드 분기 구현
    - Parent Orchestrator에서 아키텍처 자료 유무에 따라 mode 설정
    - architecture_present → Architecture Agent 분석 위임
    - architecture_absent → Discovery Agent 정보 수집 위임
    - _Requirements: 1.1, 1.2, 1.3_

  - [x] 13.3 Parent Orchestrator 위임 흐름 완성
    - task plan 수립 → 하위 에이전트 위임 → 결과 수집 → patch 변환 → 발행
    - auditable mapping (user message → delegated tasks → resulting patches) 구현
    - _Requirements: 18.1, 18.2, 18.3, 18.5_

  - [x] 13.4 AgentCore Memory 연동
    - short-term: 세션 대화 문맥 저장/조회
    - long-term: 고객 특성, 리전 제약 저장/조회
    - 새 세션 시작 시 동일 고객명 기준 long-term 메모리 조회
    - _Requirements: 13.1, 13.2, 13.3_

- [x] 14. 3단계 — Reviewer 기본 검증
  - [x] 14.1 `agent/app/reviewer/` 에 Reviewer Agent 구현
    - `reviewer_agent.py` 파일에 `ReviewerAgent` 클래스 구현
    - `review()`: 필수 섹션 누락 검사 + 섹션 순서 검증 + 숫자 불일치 탐지
    - `calculate_completion_score()`: 섹션별 필수 필드 채움 비율 → 0.0~1.0
    - `classify_issues()`: blocking vs non-blocking 분류
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.6_

  - [x] 14.2 리뷰 결과를 Document_State에 반영
    - completion_score, blocking_issues, warnings 갱신
    - 구체적 수정 제안 생성
    - _Requirements: 11.5, 17.1_

  - [x] 14.3 프런트엔드 CompletionBadge 및 ExportButton 연동
    - completion_score 실시간 표시
    - blocking issue 없을 때 ExportButton 활성화
    - `POST /documents/{docId}/review` API 연동
    - _Requirements: 17.2, 17.3_

  - [ ]* 14.4 Reviewer 유닛 테스트 작성
    - 필수 섹션 누락 검출, completion score 계산, blocking/non-blocking 분류 검증
    - _Requirements: 11.1, 11.6, 17.1_

- [x] 15. Checkpoint — 3단계 검증
  - AppSync patch가 실시간 반영되는지 수동 확인
  - Parent Orchestrator가 위임 → patch 발행 흐름이 동작하는지 확인
  - Reviewer가 누락/불일치를 정상 탐지하는지 확인
  - 필요 시 간단한 Python 검증 스크립트로 확인. 구현 중 애매한 점이 있으면 사용자에게 질문

- [x] 16. 4단계 — Calculator MCP 확장 (Gateway 경유)
  - [x] 16.1 Cost Agent 구현
    - `agent/app/cost/cost_agent.py` 파일에 `CostAgent` 클래스 구현
    - `calculate_staffing_cost(staffing_plan: StaffingPlan)`: 인건비 deterministic 계산 (calculation 모듈 활용). stakeholders 섹션 데이터는 사용하지 않음
    - `calculate_aws_cost(services, gateway_client: GatewayClient)`: Gateway의 `estimate_cost` 도구 호출 → 서비스별 비용 + shareable URL
    - `generate_fallback_card()`: 실패 또는 unsupported service 시 요약 카드 생성
    - _Requirements: 6.1, 6.2, 7.1, 7.2, 7.4_

  - [x] 16.2 AgentCore Gateway 도구 호출 연동
    - Gateway 클라이언트 구현: `estimate_cost`, `calculate_staffing_cost` MCP 도구 호출
    - 실패 시 오류 처리 및 status 채널 발행
    - _Requirements: 14.1, 14.2, 14.3_

  - [x] 16.3 Calculator MCP 결과를 Document_State에 반영
    - `monthly_cost_summary`, `service_breakdown`, `calculator_share_url` 저장
    - unsupported service는 `manual_estimate_items`에 포함
    - document-local cost summary 보존 (외부 링크 만료 대비)
    - _Requirements: 7.2, 7.3, 7.5, 7.6_

  - [x] 16.4 프런트엔드 CostSection에 AWS 비용 표시 연동
    - 서비스별 비용 breakdown 표시
    - calculator.aws 링크 표시
    - fallback card 표시 (실패 시)
    - _Requirements: 7.2, 7.3, 7.4_

- [x] 17. 4단계 — Diagram Service 연결 (조건부)
  - [x] 17.1 Architecture Agent 기본 구현 — 기존 아키텍처 분석 모드 (present mode)
    - `agent/app/architecture/architecture_agent.py` 파일에 `ArchitectureAgent` 클래스 구현
    - `analyze_existing()`: .drawio 파싱 → AWS 서비스 추출 → 해석/보완
    - 업로드된 .drawio를 S3에 저장하고, 최소 1개의 preview artifact(.png 또는 .svg)를 생성하여 S3 경로 반환
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

  - [x] 17.2 프런트엔드 ArchitectureSection에 업로드/표시 연동
    - .drawio 파일 업로드 UI
    - .png/.svg preview 표시 + .drawio 원본 다운로드 링크
    - _Requirements: 3.3_

  - [ ]* 17.3 Architecture Agent 확장 — 신규 아키텍처 설계 보조 모드 (absent mode)
    - `design_new()`: 프로젝트 요구사항 → AWS 아키텍처 초안 생성
    - `generate_diagram()`: Gateway의 `generate_architecture_diagram` 도구 호출 → .drawio + .png/.svg → S3 저장
    - _Requirements: 4.1, 4.2, 4.3_

- [x] 18. 4단계 — DOCX export 최소 버전
  - [x] 18.1 Formatter Agent 구현
    - `agent/app/formatter/formatter_agent.py` 파일에 `FormatterAgent` 클래스 구현
    - `export_docx()`: Document_State → APN 템플릿 순서 정렬 → Gateway의 `export_docx` 도구 호출 → DOCX 생성 → S3 저장
    - _Requirements: 12.1, 12.2, 12.3_

  - [x] 18.2 Milestone 동기화 구현
    - staffing_plan 또는 scope_of_work 변경 시 `build_milestone_summary` 도구 호출
    - milestones 섹션 재생성 및 동기화
    - _Requirements: 15.1, 15.2, 15.3_

  - [x] 18.3 프런트엔드 ExportButton → DOCX 다운로드 연동
    - `POST /documents/{docId}/export` API 호출
    - S3 presigned URL로 다운로드 링크 제공
    - _Requirements: 12.3, 17.3_

- [x] 19. 4단계 — 배포 인프라 구성
  - [x] 19.1 Terraform 기반 인프라 코드 작성
    - `infra/terraform/` 에 IAM, S3, DynamoDB, Lambda (OnPublish, Gateway targets), AppSync Events, CodeBuild 리소스 정의
    - default execution context: `AWS_PROFILE=mzadmin`, `ap-northeast-2` (provider 코드에 하드코딩하지 않고 실행 스크립트/환경변수로 주입)
    - _Requirements: 16.1, 16.5, 16.6_

  - [x] 19.2 Python CDK AgentCore 계층 코드 작성
    - `infra/cdk/` 에 AgentCore Runtime, Endpoint, Gateway, Gateway target 등록, Memory 리소스 정의
    - agent zip 업로드 연결
    - _Requirements: 16.2, 16.4_

  - [x] 19.3 배포/삭제 스크립트 작성
    - `infra/scripts/deploy.sh`: Terraform apply → CDK deploy 순서
    - `infra/scripts/destroy.sh`: CDK destroy → Terraform destroy 순서
    - _Requirements: 16.5, 16.6, 16.7_

- [x] 20. Final Checkpoint — 전체 시스템 검증
  - 전체 흐름 수동 확인: 채팅 입력 → 에이전트 위임 → patch 발행 → UI 반영 → 리뷰 → DOCX export
  - 배포 스크립트가 정상 동작하는지 확인
  - 필요 시 간단한 Python 검증 스크립트로 확인. 구현 중 애매한 점이 있으면 사용자에게 질문

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- 사용자가 확정한 개발 순서(1단계~4단계)를 엄격히 따름
- 1단계: agent 뼈대 (스키마, 계산, preset, Parent skeleton, front 기본 화면)
- 2단계: 사용자 입력과 계산 (편집 표, 실시간 재계산, preset 추천)
- 3단계: 실시간과 에이전트 연결 (AppSync, Parent 위임, Reviewer)
- 4단계: 외부 기능 연결 (Calculator MCP, Diagram, DOCX export, 배포)
- 바이브 모드 개발: 작은 단위로 생성 → 직접 확인 → 수정 → 다음 단계
- Python (agent/) + TypeScript/React+Vite (front/) 이중 언어 구성
- 배포는 최대 3회: Terraform + Python CDK + front (선택)
- team vs staffing_plan 구분: UI 탭 이름은 Team 유지, 내부 상태/계산 입력은 전부 staffing_plan 사용. stakeholders는 연락처/조직 정보만 담당
- Stage 2에서는 AppSync 없이 write API + optimistic local update로 동작. real-time patch는 Stage 3에서 추가
