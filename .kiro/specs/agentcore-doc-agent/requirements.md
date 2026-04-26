# Requirements Document

## Introduction

이 문서는 해커톤용 AgentCore 멀티에이전트 문서 생성 시스템의 요구사항을 정의한다. 이 시스템은 사용자가 채팅으로 요구사항을 입력하면, Parent Orchestrator가 총 7개 에이전트와 MCP 도구를 오케스트레이션하여 APN PoC Project Plan 문서를 실시간으로 생성·수정하고, 아키텍처 다이어그램과 비용 추정 링크까지 포함한 최종 DOCX를 생성하는 시스템이다.

핵심 설계 원칙은 다음과 같다:
- 이중 진입 구조: 기존 아키텍처 유무에 따라 분석 모드 또는 설계 보조 모드로 진입
- JSON canonical state가 문서의 source of truth
- 사용자 입력 / AI 추천 / 시스템 계산의 명확한 분리
- preset 기반 staffing/rate 추천으로 일관성 확보
- AppSync Events 기반 실시간 문서 동기화

## Glossary

- **Parent_Orchestrator**: AgentCore Runtime 위에서 동작하는 최상위 에이전트. 사용자 의도를 해석하고 하위 에이전트와 도구를 오케스트레이션하는 문서 상태 기계 겸 라우터
- **Discovery_Agent**: 프로젝트 overview를 수집하고 부족한 정보를 재질문하여 입력값을 구조화하는 에이전트
- **Architecture_Agent**: 기존 아키텍처를 분석하거나 신규 아키텍처 설계 초안을 생성하고 Diagram Service를 호출하는 에이전트
- **Staffing_Agent**: preset 기반으로 역할/단가를 추천하고 보정·설명하는 에이전트
- **Cost_Agent**: 인건비 계산, AWS 서비스 비용 계산, calculator link 및 fallback card를 생성하는 에이전트
- **Reviewer_Agent**: 필수 섹션 누락 체크, 템플릿 순서 검증, 불일치 탐지를 수행하는 에이전트
- **Formatter_Agent**: section order 유지, 표/블록 포맷 정리, DOCX export를 수행하는 에이전트
- **Document_State**: JSON canonical state로 관리되는 APN PoC Project Plan 문서의 전체 상태. 각 섹션은 user_input, ai_recommended, calculated, status 구조를 가짐
- **Patch**: AppSync Events를 통해 전달되는 문서 상태의 부분 변경 단위
- **Preset**: role_catalog.json, rate_card.json, staffing_presets.json 등 사전 분석된 정형 데이터 파일
- **Calculator_MCP**: aws-calculator-mcp 서버를 통해 calculator.aws shareable URL을 생성하는 MCP 도구
- **AgentCore_Gateway**: Lambda를 MCP 도구로 노출하는 AgentCore의 도구 게이트웨이
- **AgentCore_Memory**: 세션 문맥(short-term)과 고객 특성·리전 제약 등 장기 사실(long-term)을 저장하는 기억 계층
- **Live_Document_Workspace**: 우측 패널에 표시되는 구조화 문서 렌더러 및 인라인 편집 UI
- **Chat_Workspace**: 좌측 패널에 표시되는 사용자-에이전트 대화 인터페이스
- **Fallback_Card**: Calculator MCP 링크 생성 실패 시 대체로 저장되는 비용 요약 카드
- **APN_Template**: APN PoC Project Plan의 고정 섹션 구조 (Cover, Overview, Team, Success Criteria, Assumptions, Scope, Architecture, Milestones, Cost, Acceptance, Resources & Cost Estimates)

## Requirements

### Requirement 1: 이중 진입 모드 분기

**User Story:** 세일즈 담당자로서, 기존 아키텍처가 있든 없든 프로젝트 상황에 맞는 문서 생성 흐름으로 진입하고 싶다.

#### Acceptance Criteria

1. WHEN 사용자가 `.drawio` 파일 또는 기타 아키텍처 자료를 업로드하면, THE Parent_Orchestrator SHALL Document_State의 mode를 "architecture_present"로 설정하고 Architecture_Agent에 분석 작업을 위임한다.
2. WHEN 사용자가 아키텍처 자료 없이 프로젝트 개요를 텍스트로 입력하면, THE Parent_Orchestrator SHALL Document_State의 mode를 "architecture_absent"로 설정하고 Discovery_Agent에 정보 수집 작업을 위임한다.
3. WHEN 두 모드 중 하나에서 아키텍처 섹션이 확정되면, THE Parent_Orchestrator SHALL 동일한 문서/비용/리뷰 파이프라인으로 후속 처리를 진행한다.

### Requirement 2: 프로젝트 정보 수집 및 구조화

**User Story:** 세일즈 담당자로서, 채팅으로 프로젝트 정보를 입력하면 시스템이 부족한 정보를 재질문하여 완전한 입력을 구조화해주길 원한다.

#### Acceptance Criteria

1. WHEN 사용자가 프로젝트 개요를 입력하면, THE Discovery_Agent SHALL 고객사명, 파트너명, 날짜, 프로젝트 목표, 범위, 아키텍처 유무, 대략적인 일정의 누락 여부를 우선 판별한다.
2. WHEN draft 작성에 필요한 최소 입력 항목이 수집되면, THE Discovery_Agent SHALL 초기 문서 초안을 생성할 수 있도록 해당 입력값을 Document_State의 `user_input`으로 구조화하여 저장한다.
3. WHEN export 또는 final review에 필요한 항목(Sponsor, Stakeholder, Team, phase별 상세 일정, 비용/리소스 정보)이 누락된 경우, THE Discovery_Agent SHALL 누락된 항목을 명시하여 사용자에게 재질문을 생성한다.
4. THE Discovery_Agent SHALL distinguish between `draft-required inputs` and `export-required inputs`, and SHALL not block initial draft generation when only export-required inputs are missing.
5. WHEN 모든 export-required 입력이 수집되면, THE Discovery_Agent SHALL 해당 값을 Document_State의 관련 섹션에 `user_input`으로 반영한다.

### Requirement 3: 아키텍처 분석 모드

**User Story:** 세일즈 담당자로서, 기존 아키텍처 자료를 업로드하면 시스템이 AWS 관점으로 해석하고 보완해주길 원한다.

#### Acceptance Criteria

1. WHEN 사용자가 `.drawio` 파일을 업로드하면, THE Architecture_Agent SHALL 파일을 파싱하여 AWS 서비스 구성 목록을 추출한다.
2. WHEN AWS 서비스 구성 목록이 추출되면, THE Architecture_Agent SHALL AWS 관점에서 해석 및 보완 사항을 `ai_recommended`로 Document_State의 `architecture` 섹션에 저장한다.
3. WHEN 아키텍처 분석이 완료되면, THE Architecture_Agent SHALL Diagram Service를 호출하여 `.drawio` 파일과 최소 1개의 preview artifact(`.png` 또는 `.svg`)를 S3에 저장한다.
4. IF 사용자가 `.drawio` 이외의 이미지 또는 텍스트 기반 아키텍처 자료를 제공하면, THEN THE Architecture_Agent SHALL 이를 보조 입력으로 사용하고, 필요 시 draw.io 변환 또는 추가 설명을 사용자에게 요청한다.
5. IF 업로드된 아키텍처 자료만으로 AWS 서비스 구성을 충분히 식별할 수 없으면, THEN THE Architecture_Agent SHALL 부족한 조건을 사용자에게 재질문한 뒤 분석을 이어간다.

### Requirement 4: 아키텍처 설계 보조 모드

**User Story:** 세일즈 담당자로서, 아키텍처가 없는 상태에서 프로젝트 요구사항을 입력하면 시스템이 아키텍처 초안을 생성해주길 원한다.

#### Acceptance Criteria

1. WHEN Discovery_Agent가 프로젝트 개요와 조건을 구조화하면, THE Architecture_Agent SHALL 프로젝트 유형과 요구사항에 기반한 AWS 아키텍처 초안을 생성한다.
2. WHEN 아키텍처 초안이 생성되면, THE Architecture_Agent SHALL 초안을 ai_recommended로 Document_State의 architecture 섹션에 저장하고 사용자에게 검토를 요청한다.
3. WHEN 사용자가 아키텍처 초안을 승인하거나 수정하면, THE Architecture_Agent SHALL Diagram Service를 호출하여 `.drawio` 파일과 최소 1개의 preview artifact(`.png` 또는 `.svg`)를 S3에 저장한다.

### Requirement 5: Preset 기반 Staffing 추천

**User Story:** 세일즈 담당자로서, 프로젝트 유형에 맞는 역할/인원/단가 조합을 자동으로 추천받고 필요 시 수정하고 싶다.

#### Acceptance Criteria

1. WHEN 아키텍처와 프로젝트 범위가 확정되면, THE Staffing_Agent SHALL staffing_presets.json과 role_catalog.json에서 프로젝트 유형에 가장 적합한 preset을 선택한다.
2. WHEN preset이 선택되면, THE Staffing_Agent SHALL 각 역할에 대해 count, allocation_pct, rate_per_hour, 추천 이유(reason), 출처 패턴(source_patterns)을 포함한 추천안을 ai_recommended로 Document_State의 team 섹션에 저장한다.
3. WHEN 사용자가 추천된 역할/인원/단가를 수정하면, THE Document_State SHALL 해당 항목의 user_edited를 true로, status를 "user_modified"로 갱신한다.
4. THE Staffing_Agent SHALL rate_card.json에 정의된 단가 범위를 벗어나는 값을 추천하지 않는다.

### Requirement 6: 비용 계산 — 인건비

**User Story:** 세일즈 담당자로서, 역할별 투입 시간과 단가를 기반으로 인건비가 자동 계산되길 원한다.

#### Acceptance Criteria

1. WHEN Document_State의 team 섹션에 역할별 count, allocation_pct, rate_per_hour, phase별 hours가 설정되면, THE Cost_Agent SHALL role별 total hours와 role별 total cost를 계산한다.
2. WHEN 모든 역할의 비용이 계산되면, THE Cost_Agent SHALL 전체 grand total cost를 계산하여 Document_State의 cost_breakdown 섹션에 calculated로 저장한다.
3. WHEN 사용자가 team 섹션의 값을 수정하면, THE Cost_Agent SHALL 비용을 즉시 재계산하여 Document_State에 반영한다. 재계산은 일반 데모 조건에서 3초 이내 완료를 목표로 한다.

### Requirement 7: 비용 계산 — AWS 서비스 비용

**User Story:** 세일즈 담당자로서, 아키텍처에 포함된 AWS 서비스의 월간 비용 추정과 calculator.aws 공유 링크를 받고 싶다.

#### Acceptance Criteria

1. WHEN 아키텍처 섹션의 AWS 서비스 구성이 확정되면, THE Cost_Agent SHALL Calculator_MCP를 호출하여 서비스별 월간 비용을 계산한다.
2. WHEN Calculator_MCP가 비용 계산을 완료하면, THE Cost_Agent SHALL calculator.aws shareable URL을 생성하여 Document_State의 `cost_breakdown` 섹션에 `calculator_share_url`로 저장한다.
3. WHEN 비용 계산이 완료되면, THE Cost_Agent SHALL `monthly_cost_summary`와 `service_breakdown`을 Document_State의 `cost_breakdown` 섹션에 저장한다.
4. IF Calculator_MCP 호출이 실패하면, THEN THE Cost_Agent SHALL 서비스별 비용 요약을 포함한 `Fallback_Card`를 생성하여 Document_State의 `cost_breakdown` 섹션에 `fallback_card`로 저장한다.
5. IF a required AWS service is not supported by Calculator_MCP, THEN THE Cost_Agent SHALL mark it as a `manual_estimate` item and include it in the `service_breakdown` and `fallback_card`.
6. THE Cost_Agent SHALL preserve both the calculator share URL and a document-local cost summary so that the estimate remains readable even if the external link expires or becomes unavailable.

### Requirement 8: 실시간 문서 동기화

**User Story:** 세일즈 담당자로서, 에이전트가 문서를 수정할 때 Live Document Workspace에 빠르게 반영되는 것을 보고 싶다.

#### Acceptance Criteria

1. WHEN 에이전트가 Document_State를 변경하면, THE Parent_Orchestrator SHALL AppSync Events의 `docs/{docId}/patch` 채널로 Patch를 발행한다.
2. WHEN Patch가 발행되면, THE Live_Document_Workspace SHALL 해당 변경 사항을 실시간으로 화면에 반영한다.
3. WHEN Patch가 발행되기 전에, THE OnPublish Lambda SHALL Patch의 유효성을 검증하고 잘못된 Patch를 차단한다.
4. THE Parent_Orchestrator SHALL 에이전트 처리 상태를 `docs/{docId}/status` 채널로 발행하여 사용자에게 현재 진행 상황을 표시한다.
5. THE system SHOULD target patch propagation and UI reflection within 1 second under normal demo conditions.
6. THE system SHALL support fallback to REST-based refresh if real-time patch delivery is temporarily unavailable.

### Requirement 9: 프런트엔드 레이아웃

**User Story:** 세일즈 담당자로서, 좌측에서 채팅하면서 우측에서 문서가 실시간으로 완성되는 것을 확인하고 싶다.

#### Acceptance Criteria

1. THE Chat_Workspace SHALL 화면 좌측에 배치되어 사용자-에이전트 간 대화를 표시한다.
2. THE Live_Document_Workspace SHALL 화면 우측에 배치되어 구조화 문서 렌더러와 인라인 편집 UI를 제공한다.
3. THE Live_Document_Workspace SHALL 상단에 Cover, Overview, Team, Success Criteria, Assumptions, Scope, Architecture, Milestones, Cost, Acceptance 탭을 제공하여 섹션 간 전환을 지원한다. Resources & Cost Estimates는 Cost 탭 내 서브섹션으로 포함한다.
4. WHEN 사용자가 Live_Document_Workspace에서 인라인 편집을 수행하면, THE Live_Document_Workspace SHALL 변경 사항을 Document_State에 user_input으로 반영한다.

### Requirement 10: 문서 상태 관리

**User Story:** 세일즈 담당자로서, AI 추천값과 내가 직접 입력한 값, 시스템 계산값이 명확히 구분되어 관리되길 원한다.

#### Acceptance Criteria

1. THE Document_State SHALL 각 섹션의 데이터를 `user_input`, `ai_recommended`, `calculated`, `status` 네 가지 속성으로 분리하여 저장한다.
2. WHEN 사용자가 `ai_recommended` 값을 수정하면, THE Document_State SHALL 해당 항목의 `user_edited`를 `true`로 설정하고 원래 `ai_recommended` 값을 보존한다.
3. WHEN `calculated` 값의 입력 데이터가 변경되면, THE Document_State SHALL 해당 `calculated` 값을 자동으로 재계산한다.
4. THE Document_State SHALL DynamoDB에 문서 canonical state, section status, patch version을 저장한다.
5. THE Document_State SHALL field-level metadata를 지원하며, 여기에는 최소한 `user_edited`, `reason`, `source_patterns`, `confidence`가 포함되어야 한다.
6. THE Document_State SHALL preserve both AI recommendation values and user-confirmed values so that recommendation history can be traced.

### Requirement 11: 리뷰 및 검증

**User Story:** 세일즈 담당자로서, 문서가 APN 템플릿 규격에 맞는지 자동으로 검증받고 싶다.

#### Acceptance Criteria

1. WHEN 사용자가 문서 리뷰를 요청하면, THE Reviewer_Agent SHALL APN_Template의 필수 섹션(`Cover`, `Overview`, `Team`, `Success Criteria`, `Assumptions`, `Scope`, `Architecture`, `Milestones`, `Cost`, `Acceptance`, `Resources & Cost Estimates`) 누락 여부를 검사한다.
2. WHEN 리뷰가 수행되면, THE Reviewer_Agent SHALL 섹션 순서가 APN_Template 규격과 일치하는지 검증한다.
3. WHEN 리뷰가 수행되면, THE Reviewer_Agent SHALL 계산값과 본문 내용 간 불일치를 탐지하여 사용자에게 보고한다.
4. WHEN 리뷰가 수행되면, THE Reviewer_Agent SHALL team, milestones, cost_breakdown, resources_cost_estimates 간의 숫자 및 역할 불일치를 검증한다.
5. WHEN 누락 또는 불일치가 발견되면, THE Reviewer_Agent SHALL 각 항목에 대해 구체적인 수정 제안을 생성한다.
6. THE Reviewer_Agent SHALL distinguish between blocking issues and non-blocking warnings.

### Requirement 12: DOCX Export

**User Story:** 세일즈 담당자로서, 완성된 문서를 APN PoC Project Plan 형식의 DOCX 파일로 다운로드하고 싶다.

#### Acceptance Criteria

1. WHEN 사용자가 DOCX export를 요청하면, THE Formatter_Agent SHALL Document_State를 APN_Template 섹션 순서에 맞게 정렬한다.
2. WHEN 문서가 정렬되면, THE Formatter_Agent SHALL AgentCore_Gateway의 export_docx 도구를 호출하여 표, 블록, 다이어그램 이미지, 비용 링크를 포함한 DOCX 파일을 생성한다.
3. WHEN DOCX 파일이 생성되면, THE Formatter_Agent SHALL 파일을 S3에 저장하고 사용자에게 다운로드 링크를 제공한다.

### Requirement 13: AgentCore 기억 계층 활용

**User Story:** 세일즈 담당자로서, 이전 대화 맥락이 유지되고 고객 특성이 기억되어 반복 입력 없이 문서를 작성하고 싶다.

#### Acceptance Criteria

1. THE AgentCore_Memory SHALL 현재 세션의 대화 문맥을 short-term 메모리에 저장하여 세션 내 연속성을 유지한다.
2. WHEN 사용자가 고객 특성, 보안 요구, 리전 제약 등 장기 사실을 입력하면, THE AgentCore_Memory SHALL 해당 정보를 long-term 메모리에 저장한다.
3. WHEN 새로운 문서 생성 세션이 시작되면, THE Parent_Orchestrator SHALL AgentCore_Memory의 long-term 메모리에서 동일 고객명 또는 명시적으로 매칭된 프로젝트 컨텍스트로 범위를 제한하여 관련 정보를 조회하고 초기 입력에 활용한다.

### Requirement 14: AgentCore Gateway 도구 호출

**User Story:** 세일즈 담당자로서, 에이전트가 다양한 도구를 활용하여 문서의 각 섹션을 자동으로 채워주길 원한다.

#### Acceptance Criteria

1. THE AgentCore_Gateway SHALL validate_template_constraints, generate_architecture_diagram, estimate_cost, calculate_staffing_cost, export_docx, build_milestone_summary 도구를 MCP 프로토콜로 노출한다.
2. WHEN Parent_Orchestrator가 도구 호출을 결정하면, THE AgentCore_Gateway SHALL 해당 Lambda 함수를 호출하고 결과를 Parent_Orchestrator에 반환한다.
3. IF AgentCore_Gateway 도구 호출이 실패하면, THEN THE Parent_Orchestrator SHALL 오류 내용을 docs/{docId}/status 채널로 발행하고 사용자에게 대안을 제시한다.

### Requirement 15: Milestone 동기화

**User Story:** 세일즈 담당자로서, 팀 구성이나 일정이 변경되면 마일스톤이 자동으로 동기화되길 원한다.

#### Acceptance Criteria

1. WHEN Document_State의 team 또는 scope_of_work 섹션이 변경되면, THE Parent_Orchestrator SHALL build_milestone_summary 도구를 호출하여 milestones 섹션을 재생성한다.
2. WHEN milestones 섹션이 재생성되면, THE Document_State SHALL phase별 일정, deliverable, 담당 역할을 동기화하여 저장한다.
3. WHEN milestones와 team 간 불일치가 발생하면, THE Reviewer_Agent SHALL 불일치 항목을 사용자에게 보고한다.

### Requirement 16: 배포 및 인프라

**User Story:** 개발자로서, Terraform과 Python CDK를 사용하여 전체 시스템을 ap-northeast-2 리전에 배포하고 싶다.

#### Acceptance Criteria

1. THE Terraform SHALL IAM, S3, DynamoDB, Lambda, AppSync Events, CodeBuild 및 기타 기반 인프라 리소스를 `ap-northeast-2` 리전에 생성한다.
2. THE Python CDK SHALL AgentCore Runtime, Endpoint, Memory, Gateway 및 관련 연결 리소스를 생성하고 구성한다.
3. WHEN CodeBuild가 트리거되면, THE CodeBuild SHALL 에이전트 소스를 패키징하여 S3에 업로드한다.
4. WHEN Python CDK 배포가 실행되면, THE system SHALL S3에 업로드된 에이전트 artifact를 사용하여 AgentCore Runtime을 생성 또는 갱신한다.
5. THE deployment workflow SHALL support deployment with no more than two infrastructure commands (Terraform + Python CDK), excluding optional front-end deployment.
6. THE deployment scripts SHALL use `AWS_PROFILE=mzadmin` and `ap-northeast-2` as the default execution context.
7. THE system SHALL support corresponding destroy workflows for Terraform and Python CDK resources.

### Requirement 17: 문서 Completion Score

**User Story:** 세일즈 담당자로서, 문서의 완성도를 한눈에 파악하고 싶다.

#### Acceptance Criteria

1. WHEN Document_State가 변경되면, THE Reviewer_Agent SHALL 각 섹션의 필수 필드 채움 비율을 기반으로 completion score를 계산한다.
2. THE Live_Document_Workspace SHALL completion score를 상단에 표시하여 사용자가 문서 완성도를 확인할 수 있게 한다.
3. WHEN all required sections are complete and no blocking issues remain, THE Live_Document_Workspace SHALL DOCX export 버튼을 활성화한다. Completion score는 참고 지표로 표시하되, export 활성화의 유일한 조건으로 사용하지 않는다.

### Requirement 18: Parent Orchestrator 상태 기계

**User Story:** 세일즈 담당자로서, 문서 생성 과정이 체계적인 단계를 따라 진행되길 원한다.

#### Acceptance Criteria

1. THE Parent_Orchestrator SHALL 사용자 메시지를 수신하면 현재 Document_State를 조회하고 다음 작업 계획(task plan)을 수립한다.
2. WHEN task plan이 수립되면, THE Parent_Orchestrator SHALL 적절한 하위 에이전트 또는 도구에 작업을 위임하고 결과를 Patch로 변환한다.
3. WHEN 하위 에이전트의 작업이 완료되면, THE Parent_Orchestrator SHALL 다음 질문 또는 다음 단계 안내를 Chat_Workspace에 표시한다.
4. THE Parent_Orchestrator SHOULD support parallel delegation for independent tasks where feasible.
5. THE Parent_Orchestrator SHALL maintain an auditable mapping between user messages, delegated tasks, and resulting patches.
