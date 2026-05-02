# Doc Agent 디버깅 가이드

## Lambda 로그 확인

### 최근 로그 보기 (실시간)
```bash
# 최근 5분
aws logs tail /aws/lambda/doc-agent-document-api --profile mzadmin --region ap-northeast-2 --since 5m --format short

# 최근 30분
aws logs tail /aws/lambda/doc-agent-document-api --profile mzadmin --region ap-northeast-2 --since 30m --format short

# 실시간 follow (터미널에서 직접 실행)
aws logs tail /aws/lambda/doc-agent-document-api --profile mzadmin --region ap-northeast-2 --follow --format short
```

### 에러만 필터링
```bash
aws logs tail /aws/lambda/doc-agent-document-api --profile mzadmin --region ap-northeast-2 --since 30m --format short 2>&1 | grep -i "error\|exception\|failed\|traceback"
```

### 특정 키워드 필터링
```bash
# Bedrock 관련
aws logs tail /aws/lambda/doc-agent-document-api --profile mzadmin --region ap-northeast-2 --since 30m --format short 2>&1 | grep -i "bedrock"

# Memory 관련
aws logs tail /aws/lambda/doc-agent-document-api --profile mzadmin --region ap-northeast-2 --since 30m --format short 2>&1 | grep -i "memory"

# AppSync 관련
aws logs tail /aws/lambda/doc-agent-document-api --profile mzadmin --region ap-northeast-2 --since 30m --format short 2>&1 | grep -i "appsync\|publish"

# AgentCore Runtime 관련
aws logs tail /aws/lambda/doc-agent-document-api --profile mzadmin --region ap-northeast-2 --since 30m --format short 2>&1 | grep -i "runtime\|invoke"
```

### REPORT만 (실행 시간, 메모리 확인)
```bash
aws logs tail /aws/lambda/doc-agent-document-api --profile mzadmin --region ap-northeast-2 --since 30m --format short 2>&1 | grep "REPORT"
```

### 로그 없이 REPORT만 제외 (실제 출력만)
```bash
aws logs tail /aws/lambda/doc-agent-document-api --profile mzadmin --region ap-northeast-2 --since 30m --format short 2>&1 | grep -v "START\|END\|REPORT\|INIT_START"
```

## Lambda 설정 확인

### 현재 배포된 Lambda 정보
```bash
aws lambda get-function --function-name doc-agent-document-api --profile mzadmin --region ap-northeast-2 --query 'Configuration.{CodeSha256:CodeSha256,LastModified:LastModified,Timeout:Timeout,MemorySize:MemorySize}' --output table
```

### 환경변수 확인
```bash
aws lambda get-function --function-name doc-agent-document-api --profile mzadmin --region ap-northeast-2 --query 'Configuration.Environment.Variables' --output json
```

## AgentCore 확인

### AgentCore Runtime 목록
```bash
AWS_PROFILE=mzadmin agent/.venv/bin/python -c "
import boto3
session = boto3.Session(profile_name='mzadmin', region_name='ap-northeast-2')
c = session.client('bedrock-agentcore-control')
resp = c.list_agent_runtimes()
for r in resp.get('agentRuntimes', resp.get('agentRuntimeSummaries', [])):
    print(f\"  {r.get('agentRuntimeName')}: {r.get('status', 'unknown')} — {r.get('agentRuntimeArn', r.get('agentRuntimeId', ''))}\")
"
```

### AgentCore Memory 상태
```bash
AWS_PROFILE=mzadmin agent/.venv/bin/python -c "
import boto3
session = boto3.Session(profile_name='mzadmin', region_name='ap-northeast-2')
c = session.client('bedrock-agentcore-control')
resp = c.get_memory(memoryId='doc_agent_memory-o6QiOB8zCT')
print(f\"Status: {resp['memory']['status']}\")
print(f\"Name: {resp['memory']['name']}\")
"
```

## API Gateway 테스트

### 직접 API 호출 (인증 없이 — 401 예상)
```bash
curl -s https://7wejbdujd6.execute-api.ap-northeast-2.amazonaws.com/documents | python3 -m json.tool
```

## DynamoDB 확인

### 문서 목록 조회
```bash
aws dynamodb scan --table-name doc-agent-documents --profile mzadmin --region ap-northeast-2 --select COUNT
```

### 특정 문서 조회
```bash
aws dynamodb get-item --table-name doc-agent-documents --profile mzadmin --region ap-northeast-2 --key '{"document_id":{"S":"DOC_ID_HERE"}}' --output json
```

## 흔한 문제와 해결

### "처리 완료"만 나오고 내용이 없음
- AgentCore Runtime 응답에서 `result` 필드가 비어있음
- handler.py의 `_runtime_response`에서 `runtime_result.get("result", "")` → 빈 문자열 → 프론트에서 "처리 완료" fallback
- Lambda 로그에 print 출력이 없으면 에러가 조용히 처리된 것
- `_invoke_runtime`에서 `ModuleNotFoundError`만 catch하고 다른 에러는 상위 전파
- AgentCore Runtime 로그 그룹: `/aws/bedrock-agentcore/runtimes/doc_agent_runtime_demo-E10F4T83ci-*`

### "계획 수립 완료: N개 작업" 응답
- AgentCore Runtime의 task_planner가 응답한 것
- Runtime이 정상 호출되었지만 실제 작업 실행이 안 된 상태
- Runtime 내부 에이전트(orchestrator → discovery/staffing/cost 등)의 로직 확인 필요

### AppSync "실시간 연결 대기 중"
- WebSocket 연결 실패
- 브라우저 콘솔에서 WebSocket 에러 확인
- VITE_APPSYNC_WS_URL, VITE_APPSYNC_API_KEY 환경변수 확인

### CORS 에러
- API Gateway cors_configuration 확인 (infra/terraform/main.tf)
- Lambda _response 함수의 CORS 헤더 확인
- Authorization, X-User-Id 헤더가 allow_headers에 있는지

### Memory API 에러
- Lambda boto3 버전이 오래되면 일부 메서드 미지원
- `[memory]` 로그 검색으로 확인
- 에러가 나도 기본 기능은 정상 동작 (degraded mode)
