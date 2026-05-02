# DynamoDB 스키마 정리

## doc-agent-documents (메인 문서 테이블)
- PK: `document_id` (S)
- GSI: `user_id-updated_at-index` (user_id=HASH, updated_at=RANGE)

### 필드
| 필드 | 타입 | 설명 |
|------|------|------|
| document_id | S | PK. `doc-{uuid12}` 형식 |
| user_id | S | Cognito sub. GSI HASH key |
| title | S | 사이드바 표시명. 자동 생성: `[고객사] 프로젝트명` |
| template | S | `apn_poc_project_plan` (고정) |
| mode | S | `architecture_present` / `architecture_absent` |
| version | N | 낙관적 잠금용. 매 업데이트마다 +1 |
| created_at | S | ISO 8601 |
| updated_at | S | ISO 8601 |
| meta | M | `{customer, partner, date}` — 각각 FieldValue 패턴 |
| sections | M | 섹션별 데이터. key=섹션명, value=섹션 내용 |
| sections_en | M | 영어 번역 버전 (번역 서브에이전트가 생성) |
| staffing_plan | M | `{roles, grand_total_hours, grand_total_cost}` |
| completion_score | N | 0.0~1.0 |
| blocking_issues | L | `[{code, message, section}]` |
| warnings | L | `[{code, message, section}]` |
| agent_status | S | `idle` / `processing` / `error` / `degraded` |
| agent_active | S | 현재 실행 중인 에이전트명 (예: `discovery_agent`) |
| agent_message | S | 상태 메시지 (예: `📋 정보 수집 중...`) |

### FieldValue 패턴 (4-property)
```json
{
  "user_input": "사용자 입력값",
  "ai_recommended": "AI 추천값",
  "calculated": "계산값",
  "status": "empty|recommended|user_modified|confirmed|calculated",
  "user_edited": false,
  "reason": "변경 사유",
  "source_patterns": ["preset_name"],
  "confidence": 0.85
}
```

### sections 키 목록
| 키 | 설명 |
|---|---|
| cover | 표지 (프로젝트명, 목표, 기간, 예산, AWS 서비스, 버전) |
| executive_summary | Executive Summary |
| stakeholders | 이해관계자 (sponsors, team, escalation) |
| success_criteria | 성공 기준 / KPIs |
| assumptions | 가정 사항 & 리스크 |
| scope_of_work | 작업 범위 |
| architecture | 아키텍처 (description, tools, diagram URLs) |
| milestones | 마일스톤 & 산출물 |
| cost_breakdown | 비용 분석 (staffing_cost, aws_service_cost, document_local_summary) |
| acceptance | 인수 기준 |
| resources_cost_estimates | 리소스 비용 추정 (contribution: customer/partner/aws) |

---

## doc-agent-conversation-history (대화 히스토리)
- PK: `document_id` (S)
- SK: `session_id` (S) — 기본값 `default`

### 필드
| 필드 | 타입 | 설명 |
|------|------|------|
| document_id | S | PK |
| session_id | S | SK. 기본 `default` |
| user_id | S | 소유자 |
| messages | L | `[{id, role, content, timestamp}]` |
| bounded_window | N | 최근 N개만 API에 전달 (기본 20) |
| total_count | N | 전체 메시지 수 |
| updated_at | S | ISO 8601 |

### message 형식
```json
{
  "id": "msg-xxx 또는 agent-xxx",
  "role": "user" | "agent",
  "content": "메시지 내용",
  "timestamp": "2026-05-02T03:00:00Z"
}
```

---

## doc-agent-patch-history (패치 이력)
- PK: `document_id` (S)
- SK: `patch_id` (S)

### 필드
| 필드 | 타입 | 설명 |
|------|------|------|
| document_id | S | PK |
| patch_id | S | SK. `patch-{uuid12}` |
| agent | S | 패치 생성 에이전트 |
| timestamp | S | ISO 8601 |
| operations | L | JSON Patch 연산 `[{op, path, value}]` |
| version | N | 패치 적용 후 버전 |
| version_before | N | 패치 적용 전 버전 |
| version_after | N | 패치 적용 후 버전 |

---

## 상태 관리 원칙
- **DynamoDB = source of truth** — 문서 상태, 대화 히스토리, agent_status 모두 DynamoDB에 저장
- **AppSync = 실시간 보너스** — 현재 보고 있는 문서의 변경을 즉시 반영
- **문서 전환 시** — DynamoDB에서 최신 상태 fetch → store에 반영 → 이후 AppSync로 실시간 업데이트
- **agent_status** — 문서별로 DynamoDB에 저장. 문서 로드 시 fetch, 실행 중 AppSync로 실시간 업데이트
