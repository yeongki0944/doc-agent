# Bedrock 모델 사용 가이드 (서울 리전)

## 서울 리전 (ap-northeast-2) 사용 가능 모델

### 직접 모델 ID (on-demand 불가 — inference profile 필수)
서울 리전에서는 직접 모델 ID로 호출하면 에러 발생:
```
ValidationException: Invocation of model ID anthropic.claude-3-5-sonnet-20241022-v2:0
with on-demand throughput isn't supported.
```

### Inference Profile (반드시 이것을 사용)

| Profile ID | 모델 | 용도 |
|---|---|---|
| `apac.anthropic.claude-3-5-sonnet-20241022-v2:0` | Claude 3.5 Sonnet v2 | 서브에이전트, 라우터, 번역 |
| `apac.anthropic.claude-sonnet-4-20250514-v1:0` | Claude Sonnet 4 | 서브에이전트 (최신) |
| `global.anthropic.claude-opus-4-6-v1` | Claude Opus 4.6 | Parent Orchestrator |
| `global.anthropic.claude-opus-4-7` | Claude Opus 4.7 | Parent (최신) |
| `global.anthropic.claude-sonnet-4-6` | Claude Sonnet 4.6 | 범용 |
| `global.anthropic.claude-haiku-4-5-20251001-v1:0` | Claude Haiku 4.5 | 빠른 분류/라우팅 |

### 프로젝트에서 사용 중인 모델
- Parent Orchestrator: `global.anthropic.claude-opus-4-6-v1`
- Child/Sub-agents: `apac.anthropic.claude-3-5-sonnet-20241022-v2:0`
- Router (task_planner): `apac.anthropic.claude-3-5-sonnet-20241022-v2:0`
- 번역: `apac.anthropic.claude-3-5-sonnet-20241022-v2:0`

## 로컬 테스트 방법

### 주의: BedrockAgentCoreApp 포트 충돌
`agent/app/__init__.py`에서 `runtime.py`를 import하면 `BedrockAgentCoreApp`이 포트 8080을 바인딩하려고 함.
→ `agent.app.parent.*`를 import하면 블로킹됨.

### 해결: 직접 Bedrock 호출로 테스트
```python
import boto3, json

session = boto3.Session(profile_name='mzadmin', region_name='ap-northeast-2')
c = session.client('bedrock-runtime')

resp = c.invoke_model(
    modelId='apac.anthropic.claude-3-5-sonnet-20241022-v2:0',
    contentType='application/json',
    accept='application/json',
    body=json.dumps({
        'anthropic_version': 'bedrock-2023-05-31',
        'max_tokens': 300,
        'system': 'You are a helpful assistant.',
        'messages': [{'role': 'user', 'content': '안녕하세요'}],
    }),
)
print(json.loads(resp['body'].read())['content'][0]['text'])
```

### task_planner 라우팅 테스트 (직접 호출)
```python
import boto3, json

session = boto3.Session(profile_name='mzadmin', region_name='ap-northeast-2')
c = session.client('bedrock-runtime')

registry = json.loads(open('agent/data/presets/agent_registry.json').read())
system = '사용자 메시지를 분석하여 에이전트를 선택하세요.\n\n에이전트:\n' + json.dumps(registry['agents'], ensure_ascii=False)

resp = c.invoke_model(
    modelId='apac.anthropic.claude-3-5-sonnet-20241022-v2:0',
    contentType='application/json',
    accept='application/json',
    body=json.dumps({
        'anthropic_version': 'bedrock-2023-05-31',
        'max_tokens': 300,
        'system': system,
        'messages': [{'role': 'user', 'content': 'Assumptions 작성해줘'}],
    }),
)
print(json.loads(resp['body'].read())['content'][0]['text'])
```

### 모델 목록 확인
```bash
# Foundation models
aws bedrock list-foundation-models --profile mzadmin --region ap-northeast-2 \
  --query 'modelSummaries[?contains(modelId, `anthropic`)].modelId' --output table

# Inference profiles
aws bedrock list-inference-profiles --profile mzadmin --region ap-northeast-2 \
  --query 'inferenceProfileSummaries[?contains(inferenceProfileId, `anthropic`)].{id:inferenceProfileId, status:status}' --output table
```

### 포트 8080 충돌 해결
```bash
lsof -ti:8080 | xargs kill -9
```
