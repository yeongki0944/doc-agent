# 알려진 이슈 및 예외 케이스

## AgentCore Runtime 로깅 불가 (2026-05 확인)
- **증상:** Runtime 내부의 `print()`, `logger` 출력이 CloudWatch에 안 나옴
- **로그 그룹:** `/aws/bedrock-agentcore/runtimes/{runtime_id}-{endpoint}` — `lastEvent: None`
- **원인:** AgentCore Runtime의 알려진 제한사항. 첫 세션 이후 로그가 누락됨
- **참고:** https://repost.aws/questions/QU-yMU1uWMSWepfK_z5brnMw
- **영향:** Runtime 내부 디버깅 불가, ProgressPublisher의 AppSync publish 성공 여부 확인 불가
- **우회:** handler.py (Lambda 환경)에서 로깅 및 AppSync publish 수행. Runtime은 블랙박스로 취급.
- **결론:** Runtime 내부에서 AppSync publish를 시도하되, 확실한 메시지는 handler.py에서 보냄

## AgentCore Runtime 로컬 테스트 불가
- **증상:** `agent.app.parent.*` import 시 `BedrockAgentCoreApp`이 포트 8080 바인딩 → 블로킹
- **원인:** `agent/app/__init__.py`에서 `runtime.py`를 import → `app = BedrockAgentCoreApp()` 실행
- **우회:** 로컬에서는 개별 함수 단위 테스트만 가능. 전체 흐름은 배포 후 테스트.
- **규칙:** AgentCore 관련 코드는 로컬 테스트 금지, 배포 후 API 호출 + CloudWatch 로그로 테스트

## API Gateway HTTP API 타임아웃 30초 하드 리밋
- **증상:** Runtime 호출이 30초 넘으면 503 Service Unavailable
- **원인:** API Gateway HTTP API의 integration timeout 최대값이 30초 (변경 불가)
- **해결:** 비동기 Lambda self-invoke + AppSync로 결과 전달 (현재 구현됨)

## Bedrock 서울 리전 — 직접 모델 ID 호출 불가
- **증상:** `ValidationException: Invocation of model ID ... with on-demand throughput isn't supported`
- **원인:** ap-northeast-2에서는 inference profile 필수
- **해결:** `apac.*` 또는 `global.*` prefix 사용 (예: `apac.anthropic.claude-3-5-sonnet-20241022-v2:0`)

## AppSync Events — data.event가 배열이 아닌 단일 문자열
- **증상:** 프론트에서 `data.event`를 배열로 순회하면 글자 단위로 파싱 시도 → 에러
- **원인:** AppSync Events API가 `event`를 단일 JSON 문자열로 전달 (배열 아님)
- **해결:** `Array.isArray(raw) ? raw : typeof raw === 'string' ? [raw] : []` 패턴 사용

## Lambda boto3 버전 — AgentCore Memory API 일부 미지원
- **증상:** `batch_create_memory_records` 등 일부 메서드가 Lambda 환경에서 없음
- **원인:** Lambda 런타임의 boto3 버전이 로컬보다 오래됨
- **영향:** Memory 저장 실패하지만 기본 기능은 정상 동작 (degraded mode)

## DocumentState에 user_id 필드 누락 시 문서 목록 안 나옴
- **증상:** 새로고침 후 문서 목록이 사라짐
- **원인:** GSI `user_id-updated_at-index`로 쿼리하는데 user_id가 None이면 인덱스에 안 나옴
- **해결:** DocumentState에 user_id/title 필드 추가 (2026-05-02 수정됨)

## Terraform provider aws ~> 5.0 — AppSync Events API 미지원
- **증상:** `aws_appsync_api` 리소스 타입 없음
- **원인:** AppSync Events API는 aws provider v6.x에서 추가됨
- **해결:** `aws_cloudformation_stack`으로 CloudFormation 경유 생성


## Lambda handler.py에서 agent 패키지 import 불가
- **증상:** `No module named 'agent'` 에러
- **원인:** Lambda는 `handler.py` 단일 파일로 배포됨. `agent/` 디렉토리는 AgentCore Runtime에만 존재.
- **규칙:** handler.py에서 `from agent.*` import 절대 금지. agent 패키지의 기능이 필요하면 handler.py에 인라인으로 구현하거나, Runtime을 통해 호출.
