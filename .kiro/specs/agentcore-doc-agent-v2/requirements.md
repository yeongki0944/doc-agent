# Requirements Document

## Introduction

이 문서는 AgentCore 멀티에이전트 문서 생성 시스템 v2의 요구사항을 정의한다. v1은 Lambda + API Gateway + 직접 Bedrock 호출 기반으로 구현되었으며, v2는 이를 AgentCore Runtime/Memory/Gateway 통합으로 업그레이드한다.

v2의 핵심 변경 사항:
- **AgentCore Runtime**: Parent Orchestrator를 `bedrock-agentcore` SDK + `strands-agents` 프레임워크 기반 AgentCore Runtime으로 배포 (v1의 Lambda 직접 Bedrock 호출 대체)
- **AgentCore Memory**: 실제 `boto3 bedrock-agentcore` Memory API로 short-term/long-term 메모리 구현 (v1의 in-memory placeholder 대체)
- **AgentCore Gateway**: Lambda 함수를 MCP 도구로 등록하여 Parent Orchestrator가 Gateway 경유 호출 (v1의 stub Gateway client 대체)
- **Multi-Agent 구조 실체화**: v1의 단일 Lambda 내 인라인 Bedrock 호출을 7개 에이전트 구조로 분리
- **Canonical State 강화**: DynamoDB source of truth + optimistic locking + version 관리 실체화
- **프런트엔드 고도화**: bounded 대화 이력, 인라인 편집, AI 추천 시각 구분, completion score 표시

기존 v1 인프라(DynamoDB, S3, CloudFront, AppSync Events, API Gateway)는 유지하며, AgentCore 계층을 추가한다.

## Glossary

- **AgentCore_Runtime**: `bedrock-agentcore` SDK를 사용하여 에이전트 코드를 직접 배포하는 서버리스 실행 환경. `@app.entrypoint` 어노테이션 또는 `/invocations` POST 엔드포인트로 호출
- **Strands_Agents**: `strands-agents` Python 프레임워크. AgentCore Runtime 위에서 에이전트 로직을 구성하는 데 사용
- **AgentCore_Gateway**: Lambda 함수를 MCP 프로토콜 도구로 노출하는 AgentCore의 도구 게이트웨이. `boto3 bedrock-agentcore` 클라이언트로 target 등록
- **AgentCore_Memory**: `boto3 bedrock-agentcore` 클라이언트의 `batch_create_memory_records`, `retrieve_memory_records` 등 API를 사용하는 기억 계층
- **Parent_Orchestrator**: AgentCore Runtime 위에서 동작하는 최상위 에이전트. Opus 4.6 모델 사용. 사용자 의도 해석, 하위 에이전트 위임, patch 조율 수행
- **Discovery_Agent**: 프로젝트 정보 수집 및 구조화 에이전트. Sonnet 3.5 v2 모델 사용
- **Architecture_Agent**: 기존 아키텍처 분석 또는 신규 아키텍처 설계 초안 생성 에이전트. Sonnet 3.5 v2 모델 사용
- **Staffing_Agent**: preset 기반 역할/단가 추천 에이전트. Sonnet 3.5 v2 모델 사용
- **Cost_Agent**: 인건비 계산 및 AWS 서비스 비용 추정 에이전트. Sonnet 3.5 v2 모델 사용
- **Reviewer_Agent**: APN 템플릿 검증 및 불일치 탐지 에이전트. Sonnet 3.5 v2 모델 사용
- **Formatter_Agent**: DOCX export 및 문서 포맷 정리 에이전트. Sonnet 3.5 v2 모델 사용
- **Document_State**: DynamoDB에 저장되는 JSON canonical state. `sections`와 top-level `staffing_plan`, `version`, `created_at`, `updated_at`를 포함하며, 각 편집 가능 필드는 `user_input` / `ai_recommended` / `calculated` / `status` 4속성 패턴을 따른다
- **Staffing_Plan**: top-level 내부 상태 모델. Team UI 탭이 편집하는 실제 계산/추천 입력이며, 연락처/조직 정보 성격의 `stakeholders` 섹션과 구분된다
- **Patch**: AppSync Events를 통해 전달되는 문서 상태의 부분 변경 단위
- **Preset**: role_catalog.json, rate_card.json, staffing_presets.json 등 사전 분석된 정형 데이터 파일
- **Calculator_MCP**: aws-calculator-mcp 서버를 통해 calculator.aws shareable URL을 생성하는 MCP 도구
- **Fallback_Card**: Calculator MCP 링크 생성 실패 시 대체로 저장되는 비용 요약 카드
- **APN_Template**: APN PoC Project Plan의 고정 섹션 구조 (Cover, Overview, Team, Success Criteria, Assumptions, Scope, Architecture, Milestones, Cost, Acceptance, Resources & Cost Estimates)
- **Live_Document_Workspace**: 우측 패널에 표시되는 구조화 문서 렌더러 및 인라인 편집 UI
- **Chat_Workspace**: 좌측 패널에 표시되는 사용자-에이전트 대화 인터페이스. 최근 N턴의 bounded history를 API 호출에 포함하고, 전체 대화 이력은 문서/세션 기준으로 별도 저장 및 재로딩한다
- **Inference_Profile**: Bedrock 모델을 리전 간 라우팅하는 식별자. 직접 모델 ID 대신 사용 (예: `global.anthropic.claude-opus-4-6-v1`)

## Requirements

### Requirement 1: AgentCore Runtime 배포 — Parent Orchestrator

**User Story:** 개발자로서, Parent Orchestrator를 AgentCore Runtime에 직접 배포하여 서버리스 에이전트 실행 환경을 확보하고 싶다.

#### Acceptance Criteria

1. THE Parent_Orchestrator SHALL `bedrock-agentcore` SDK와 `strands-agents` 프레임워크를 사용하여 AgentCore Runtime에 배포된다.
2. THE Parent_Orchestrator SHALL `@app.entrypoint` 어노테이션 또는 `/invocations` POST 엔드포인트를 통해 호출 가능하다.
3. THE Parent_Orchestrator SHALL 에이전트 코드를 ZIP으로 패키징하여 AgentCore CLI 또는 `boto3 bedrock-agentcore` 클라이언트를 통해 배포한다.
4. THE Parent_Orchestrator SHALL Inference_Profile `global.anthropic.claude-opus-4-6-v1`을 모델로 사용한다.
5. WHEN Parent_Orchestrator가 하위 에이전트를 호출할 때, THE Parent_Orchestrator SHALL Inference_Profile `apac.anthropic.claude-3-5-sonnet-20241022-v2:0`을 하위 에이전트 모델로 지정한다.
6. THE AgentCore Runtime SHALL Python 3.12 런타임 환경을 사용한다.
7. IF the configured inference profile is temporarily unavailable, THEN THE system SHALL support a documented fallback inference profile or enter a degraded mode that returns a user-visible status message.

### Requirement 2: AgentCore Memory 통합

**User Story:** 세일즈 담당자로서, 이전 대화 맥락이 유지되고 고객 특성이 기억되어 반복 입력 없이 문서를 작성하고 싶다.

#### Acceptance Criteria

1. THE AgentCore_Memory SHALL `boto3 bedrock-agentcore` 클라이언트의 Memory API를 사용하여 short-term 메모리에 현재 세션의 대화 문맥을 저장한다.
2. WHEN 사용자가 고객 특성, 보안 요구, 리전 제약 등 장기 사실을 입력하면, THE AgentCore_Memory SHALL `batch_create_memory_records` API를 호출하여 long-term 메모리에 해당 정보를 저장한다.
3. WHEN 새로운 문서 생성 세션이 시작되면, THE Parent_Orchestrator SHALL `retrieve_memory_records` API를 호출하여 동일 고객명으로 범위를 제한한 long-term 메모리를 조회하고 초기 입력에 활용한다.
4. THE AgentCore_Memory SHALL v1의 in-memory placeholder(`agent/lib/memory/memory.py`)를 실제 AgentCore Memory API 호출로 대체한다.
5. IF AgentCore_Memory API calls fail temporarily, THEN THE system SHALL continue in a no-memory degraded mode using bounded session history and SHALL publish a warning status to the user.

### Requirement 3: AgentCore Gateway 도구 등록

**User Story:** 개발자로서, Lambda 함수를 AgentCore Gateway에 MCP 도구로 등록하여 Parent Orchestrator가 표준 프로토콜로 도구를 호출할 수 있게 하고 싶다.

#### Acceptance Criteria

1. THE AgentCore_Gateway SHALL 다음 6개 도구를 MCP 프로토콜로 노출한다: `validate_template_constraints`, `generate_architecture_diagram`, `estimate_cost`, `calculate_staffing_cost`, `export_docx`, `build_milestone_summary`.
2. WHEN 도구가 등록될 때, THE AgentCore_Gateway SHALL 각 도구를 대응하는 Lambda 함수(`doc-agent-validate-template`, `doc-agent-generate-diagram`, `doc-agent-estimate-cost`, `doc-agent-calc-staffing`, `doc-agent-export-docx`, `doc-agent-build-milestones`)에 연결한다.
3. WHEN Parent_Orchestrator가 도구 호출을 결정하면, THE AgentCore_Gateway SHALL 해당 Lambda 함수를 호출하고 결과를 Parent_Orchestrator에 반환한다.
4. IF AgentCore_Gateway 도구 호출이 실패하면, THEN THE Parent_Orchestrator SHALL 오류 내용을 `docs/{docId}/status` 채널로 발행하고 사용자에게 대안을 제시한다.
5. THE AgentCore_Gateway SHALL v1의 stub Gateway client(`agent/app/cost/gateway_client.py`)를 공통 Gateway 클라이언트(`agent/lib/gateway/agentcore_gateway.py`)로 대체한다.
6. IF a Gateway tool invocation fails, THEN THE system SHALL preserve the current Document_State, emit an error status, and avoid applying partial document mutations from the failed tool call.

### Requirement 4: Multi-Agent 아키텍처 실체화

**User Story:** 개발자로서, v1의 단일 Lambda 인라인 Bedrock 호출을 7개 에이전트 구조로 분리하여 각 에이전트가 전문 역할을 수행하게 하고 싶다.

#### Acceptance Criteria

1. THE Parent_Orchestrator SHALL 사용자 메시지를 수신하면 현재 Document_State를 조회하고 다음 작업 계획(task plan)을 수립한다.
2. WHEN task plan이 수립되면, THE Parent_Orchestrator SHALL 적절한 하위 에이전트(Discovery_Agent, Architecture_Agent, Staffing_Agent, Cost_Agent, Reviewer_Agent, Formatter_Agent)에 작업을 위임하고 결과를 Patch로 변환한다.
3. THE Parent_Orchestrator SHALL hub-and-spoke 패턴으로 동작하며, 하위 에이전트 간 직접 통신 없이 모든 조율을 Parent를 경유하여 수행한다.
4. THE initial v2 implementation SHALL realize sub-agents as logical agents within the Parent_Orchestrator runtime unless explicit separation into independent runtimes is required later.
5. WHEN 하위 에이전트의 작업이 완료되면, THE Parent_Orchestrator SHALL 다음 질문 또는 다음 단계 안내를 Chat_Workspace에 표시한다.
6. THE Parent_Orchestrator SHALL 사용자 메시지, 위임된 작업, 결과 patch 간의 추적 가능한 매핑을 유지한다.
7. THE system SHALL v1의 `agent/lambdas/document_api/handler.py` 내 인라인 Bedrock 호출을 AgentCore Runtime 기반 에이전트 호출로 대체한다.

### Requirement 5: 이중 진입 모드 분기

**User Story:** 세일즈 담당자로서, 기존 아키텍처가 있든 없든 프로젝트 상황에 맞는 문서 생성 흐름으로 진입하고 싶다.

#### Acceptance Criteria

1. WHEN 사용자가 `.drawio` 파일 또는 기타 아키텍처 자료를 업로드하면, THE Parent_Orchestrator SHALL Document_State의 mode를 `architecture_present`로 설정하고 Architecture_Agent에 분석 작업을 위임한다.
2. WHEN 사용자가 아키텍처 자료 없이 프로젝트 개요를 텍스트로 입력하면, THE Parent_Orchestrator SHALL Document_State의 mode를 `architecture_absent`로 설정하고 Discovery_Agent에 정보 수집 작업을 위임한다.
3. WHEN 두 모드 중 하나에서 아키텍처 섹션이 확정되면, THE Parent_Orchestrator SHALL 동일한 문서/비용/리뷰 파이프라인으로 후속 처리를 진행한다.

### Requirement 6: 프로젝트 정보 수집 및 구조화

**User Story:** 세일즈 담당자로서, 채팅으로 프로젝트 정보를 입력하면 시스템이 부족한 정보를 재질문하여 완전한 입력을 구조화해주길 원한다.

#### Acceptance Criteria

1. WHEN 사용자가 프로젝트 개요를 입력하면, THE Discovery_Agent SHALL 고객사명, 파트너명, 날짜, 프로젝트 목표, 범위, 아키텍처 유무, 대략적인 일정의 누락 여부를 판별한다.
2. WHEN draft 작성에 필요한 최소 입력 항목이 수집되면, THE Discovery_Agent SHALL 해당 입력값을 Document_State의 `user_input`으로 구조화하여 저장한다.
3. WHEN export 또는 final review에 필요한 항목(Sponsor, Stakeholder, Team, phase별 상세 일정, 비용/리소스 정보)이 누락된 경우, THE Discovery_Agent SHALL 누락된 항목을 명시하여 사용자에게 재질문을 생성한다.
4. THE Discovery_Agent SHALL draft-required inputs와 export-required inputs를 구분하여, export-required inputs만 누락된 경우 초기 draft 생성을 차단하지 않는다.

### Requirement 7: Preset 기반 Staffing 추천

**User Story:** 세일즈 담당자로서, 프로젝트 유형에 맞는 역할/인원/단가 조합을 자동으로 추천받고 필요 시 수정하고 싶다.

#### Acceptance Criteria

1. WHEN 아키텍처와 프로젝트 범위가 확정되면, THE Staffing_Agent SHALL `staffing_presets.json`과 `role_catalog.json`에서 프로젝트 유형에 가장 적합한 preset을 선택한다.
2. WHEN preset이 선택되면, THE Staffing_Agent SHALL 각 역할에 대해 count, allocation_pct, rate_per_hour, 추천 이유(reason), 출처 패턴(source_patterns)을 포함한 추천안을 `ai_recommended`로 top-level `staffing_plan`에 저장한다.
3. WHEN 사용자가 추천된 역할/인원/단가를 수정하면, THE Document_State SHALL 해당 항목의 `user_edited`를 `true`로, status를 `user_modified`로 갱신한다.
4. THE Staffing_Agent SHALL `rate_card.json`에 정의된 단가 범위를 벗어나는 값을 추천하지 않는다.
5. THE Staffing_Agent SHALL 기본 프로젝트 유형으로 GenAI 멀티에이전트 PoC를 사용하며, 6개 역할(PM, SA, ML Engineer, Backend Dev, Frontend Dev, QA)을 포함한다.
6. THE system SHALL treat the Team UI tab as a view over `staffing_plan`, not as a direct representation of stakeholder contact information.

### Requirement 8: 비용 계산 — 인건비 및 AWS 서비스 비용

**User Story:** 세일즈 담당자로서, 역할별 투입 시간과 단가 기반 인건비와 AWS 서비스 월간 비용이 자동 계산되길 원한다.

#### Acceptance Criteria

1. WHEN top-level `staffing_plan`에 역할별 count, allocation_pct, rate_per_hour, phase별 hours가 설정되면, THE Cost_Agent SHALL role별 total hours와 role별 total cost를 계산한다.
2. WHEN 모든 역할의 비용이 계산되면, THE Cost_Agent SHALL 전체 grand total cost를 계산하여 Document_State의 `cost_breakdown` 섹션에 `calculated`로 저장한다.
3. WHEN 사용자가 `staffing_plan`의 값을 수정하면, THE Cost_Agent SHALL 비용을 재계산하여 Document_State에 반영한다.
4. WHEN 아키텍처 섹션의 AWS 서비스 구성이 확정되면, THE Cost_Agent SHALL AgentCore_Gateway의 `estimate_cost` 도구를 호출하여 서비스별 월간 비용을 계산한다.
5. WHEN 비용 계산이 완료되면, THE Cost_Agent SHALL `calculator.aws` shareable URL, `monthly_cost_summary`, `service_breakdown`을 Document_State의 `cost_breakdown` 섹션에 저장한다.
6. IF Calculator_MCP 호출이 실패하면, THEN THE Cost_Agent SHALL 서비스별 비용 요약을 포함한 Fallback_Card를 생성하여 Document_State에 저장한다.
7. IF 특정 AWS 서비스가 Calculator_MCP 또는 Gateway cost 도구에서 지원되지 않으면, THEN THE Cost_Agent SHALL 해당 항목을 `manual_estimate_items`로 기록하고 `service_breakdown` 및 Fallback_Card에 반영한다.
8. THE Cost_Agent SHALL preserve a document-local cost summary even when an external calculator share URL is generated, so that the estimate remains readable if the external link expires or becomes unavailable.

### Requirement 9: 실시간 문서 동기화

**User Story:** 세일즈 담당자로서, 에이전트가 문서를 수정할 때 Live Document Workspace에 실시간으로 반영되는 것을 보고 싶다.

#### Acceptance Criteria

1. WHEN 에이전트가 Document_State를 변경하면, THE Parent_Orchestrator SHALL AppSync Events의 `docs/{docId}/patch` 채널로 Patch를 발행한다.
2. WHEN Patch가 발행되면, THE Live_Document_Workspace SHALL 해당 변경 사항을 실시간으로 화면에 반영한다.
3. WHEN Patch가 발행되기 전에, THE OnPublish Lambda SHALL Patch의 유효성을 검증하고 잘못된 Patch를 차단한다.
4. THE Parent_Orchestrator SHALL 에이전트 처리 상태를 `docs/{docId}/status` 채널로 발행하여 사용자에게 현재 진행 상황을 표시한다.
5. IF 실시간 patch 전달이 일시적으로 불가능하면, THEN THE system SHALL REST 기반 전체 Document_State 재조회로 fallback한다.

### Requirement 10: Canonical State 및 동시성 제어

**User Story:** 개발자로서, 실시간 patch와 사용자 편집이 충돌하더라도 문서 상태의 일관성을 유지하고 싶다.

#### Acceptance Criteria

1. THE Document_State SHALL use DynamoDB as the canonical source of truth for document content and metadata.
2. THE Document_State SHALL maintain `version`, `created_at`, and `updated_at` fields for every document.
3. WHEN a write API request or agent-generated patch updates the Document_State, THE system SHALL increment the document version and persist the updated state before broadcasting a patch.
4. THE system SHALL use optimistic locking based on the current document version when applying server-side updates.
5. WHEN a patch is received by OnPublish validation, THE system SHALL verify that the incoming patch version and target path are valid before allowing propagation.
6. IF version validation fails, THEN THE system SHALL reject the patch and publish an error status to `docs/{docId}/status`.

### Requirement 11: 프런트엔드 업그레이드

**User Story:** 세일즈 담당자로서, 채팅 이력이 유지되고 AI 추천이 시각적으로 구분되며 문서 완성도를 한눈에 파악하고 싶다.

#### Acceptance Criteria

1. THE Chat_Workspace SHALL send a bounded recent conversation history (최근 N턴) with each API call to preserve in-session continuity.
2. THE system SHALL persist document-level conversation history separately so that prior messages can be reloaded when the user reopens a document or session.
3. THE Parent_Orchestrator SHALL use AgentCore_Memory to supplement bounded chat history with relevant long-term context instead of requiring the full historical transcript on every request.
4. THE Live_Document_Workspace SHALL AI 추천 값을 노란색 배경과 `AI` 배지로 시각적으로 구분하여 표시한다.
5. THE Live_Document_Workspace SHALL 상단에 completion score 배지를 표시하여 문서 완성도를 실시간으로 확인할 수 있게 한다.
6. THE Live_Document_Workspace SHALL DOCX Export 버튼을 제공하며, blocking issue가 없을 때 활성화한다.
7. WHEN 사용자가 Team 섹션의 표에서 인라인 편집을 수행하면, THE Live_Document_Workspace SHALL 변경 사항을 top-level `staffing_plan`의 `user_input`으로 반영하고 비용 재계산을 트리거한다.
8. THE Live_Document_Workspace SHALL Architecture 섹션에서 `.drawio` 파일 업로드와 다이어그램 preview 표시를 지원한다.

### Requirement 12: 문서 상태 관리 — 4속성 패턴

**User Story:** 세일즈 담당자로서, AI 추천값과 내가 직접 입력한 값, 시스템 계산값이 명확히 구분되어 관리되길 원한다.

#### Acceptance Criteria

1. THE Document_State SHALL 각 편집 가능 필드를 `user_input`, `ai_recommended`, `calculated`, `status` 네 가지 속성으로 분리하여 저장한다.
2. WHEN 사용자가 `ai_recommended` 값을 수정하면, THE Document_State SHALL 해당 항목의 `user_edited`를 `true`로 설정하고 원래 `ai_recommended` 값을 보존한다.
3. WHEN `calculated` 값의 입력 데이터가 변경되면, THE Document_State SHALL 해당 `calculated` 값을 자동으로 재계산한다.
4. THE Document_State SHALL field-level metadata를 지원하며, 여기에는 최소한 `user_edited`, `reason`, `source_patterns`, `confidence`가 포함된다.
5. THE Document_State SHALL `agent/lib/schema/document_state.py`의 Pydantic v2 모델을 기준으로 직렬화/역직렬화한다.

### Requirement 13: 리뷰 및 DOCX Export

**User Story:** 세일즈 담당자로서, 문서가 APN 템플릿 규격에 맞는지 검증받고 완성된 문서를 DOCX로 다운로드하고 싶다.

#### Acceptance Criteria

1. WHEN 사용자가 문서 리뷰를 요청하면, THE Reviewer_Agent SHALL APN_Template의 필수 섹션 누락 여부, 섹션 순서 일치, 계산값과 본문 간 불일치를 검사한다.
2. WHEN 리뷰가 수행되면, THE Reviewer_Agent SHALL blocking issue와 non-blocking warning을 구분하여 보고한다.
3. WHEN 사용자가 DOCX export를 요청하면, THE Formatter_Agent SHALL Document_State를 APN_Template 섹션 순서에 맞게 정렬하고 AgentCore_Gateway의 `export_docx` 도구를 호출하여 DOCX 파일을 생성한다.
4. WHEN DOCX 파일이 생성되면, THE Formatter_Agent SHALL 파일을 S3에 저장하고 사용자에게 다운로드 링크를 제공한다.

### Requirement 14: Milestone 동기화

**User Story:** 세일즈 담당자로서, 인력 구성이나 일정이 변경되면 마일스톤이 자동으로 동기화되길 원한다.

#### Acceptance Criteria

1. WHEN top-level `staffing_plan` 또는 `scope_of_work` 섹션이 변경되면, THE Parent_Orchestrator SHALL AgentCore_Gateway의 `build_milestone_summary` 도구를 호출하여 milestones 섹션을 재생성한다.
2. WHEN milestones 섹션이 재생성되면, THE Document_State SHALL phase별 일정, deliverable, 담당 역할을 동기화하여 저장한다.
3. THE system SHALL not use stakeholder contact information as a direct input to milestone calculation unless it has been explicitly mapped into the staffing plan.

### Requirement 15: 배포 및 인프라

**User Story:** 개발자로서, Terraform과 Python CDK를 사용하여 전체 시스템을 ap-northeast-2 리전에 배포하고 싶다.

#### Acceptance Criteria

1. THE Terraform SHALL IAM, S3, DynamoDB, Lambda(OnPublish + Gateway target 6개), API Gateway, AppSync Events, CloudFront를 `ap-northeast-2` 리전에 생성한다.
2. THE Python CDK(`infra/cdk/deploy.py`) SHALL `boto3 bedrock-agentcore` 클라이언트를 사용하여 AgentCore Runtime, Endpoint, Gateway, Gateway target 등록, Memory를 생성하고 구성한다.
3. THE deployment workflow SHALL 최대 2개의 인프라 명령(Terraform apply + Python CDK deploy)으로 배포를 완료한다. 프런트엔드 배포는 별도 선택 사항이다.
4. THE deployment scripts SHALL `AWS_PROFILE=mzadmin`과 `ap-northeast-2`를 기본 실행 컨텍스트로 사용한다.
5. THE system SHALL `infra/scripts/deploy.sh`에서 Terraform apply → AgentCore deploy → Front build/deploy 순서를 실행하는 통합 배포 스크립트를 제공한다.
6. THE system SHALL `infra/scripts/destroy.sh`에서 Terraform 및 Python CDK 리소스를 정리하는 통합 삭제 스크립트를 제공한다.
7. IF Lambda Function URL이 SCP에 의해 차단되면, THEN THE system SHALL API Gateway를 기본 API 엔드포인트로 사용한다.

### Requirement 16: 아키텍처 에이전트 — 분석 및 설계 보조

**User Story:** 세일즈 담당자로서, 기존 아키텍처를 분석하거나 새로운 아키텍처 초안을 생성받고 싶다.

#### Acceptance Criteria

1. WHEN 사용자가 `.drawio` 파일을 업로드하면, THE Architecture_Agent SHALL 파일을 파싱하여 AWS 서비스 구성 목록을 추출하고 AWS 관점에서 해석 및 보완 사항을 `ai_recommended`로 저장한다.
2. WHEN 사용자가 기존 `.drawio` 파일을 업로드한 경우, THE Architecture_Agent SHALL 업로드된 원본을 S3에 저장하고, preview artifact를 생성하거나 재사용 가능한 preview가 있으면 이를 연결한다.
3. WHEN 아키텍처 자료 없이 프로젝트 요구사항이 구조화되면, THE Architecture_Agent SHALL 프로젝트 유형과 요구사항에 기반한 AWS 아키텍처 초안을 생성하고 `ai_recommended`로 저장한다.
4. WHEN 아키텍처가 확정되면, THE Architecture_Agent SHALL AgentCore_Gateway의 `generate_architecture_diagram` 도구를 호출하거나 equivalent normalization flow를 수행하여 `.drawio` 파일과 최소 1개의 preview artifact(`.png` 또는 `.svg`)를 S3에 저장한다.

### Requirement 17: Completion Score 및 Export 활성화

**User Story:** 세일즈 담당자로서, 문서의 완성도를 한눈에 파악하고 export 가능 여부를 알고 싶다.

#### Acceptance Criteria

1. WHEN Document_State가 변경되면, THE Reviewer_Agent SHALL 각 섹션의 필수 필드 채움 비율을 기반으로 completion score(0.0~1.0)를 계산한다.
2. THE Live_Document_Workspace SHALL completion score를 상단에 배지로 표시한다.
3. WHEN 모든 필수 섹션이 완료되고 blocking issue가 없으면, THE Live_Document_Workspace SHALL DOCX export 버튼을 활성화한다.
