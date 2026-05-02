# Doc Agent 인프라 구조

## 네트워크 흐름

```
브라우저 (https://dlstwg8d2t0h3.cloudfront.net)
  │
  ├─ 정적 파일 → CloudFront → S3 (doc-agent-frontend-*)
  │
  ├─ REST API → API Gateway HTTP API → Lambda (doc-agent-document-api)
  │                                       ├─ DynamoDB (doc-agent-documents)
  │                                       ├─ DynamoDB (doc-agent-conversation-history)
  │                                       ├─ AgentCore Runtime (doc_agent_runtime_demo)
  │                                       ├─ AppSync Events (publish)
  │                                       └─ Bedrock (LLM 호출)
  │
  └─ WebSocket → AppSync Events API (실시간 채팅/상태)
                   └─ Channel: /docs/{docId}/chat
```

## API Gateway HTTP API
- ID: 7wejbdujd6
- Endpoint: https://7wejbdujd6.execute-api.ap-northeast-2.amazonaws.com
- Protocol: HTTP
- Integration: AWS_PROXY → doc-agent-document-api Lambda
- **Timeout: 30초 (하드 리밋, 늘릴 수 없음)**
- Payload Format: 2.0
- Routes: `$default` (catch-all), `POST /invocations`
- CORS: Origins=*, Methods=[POST,PUT,OPTIONS,GET,DELETE], Headers=[authorization,x-user-id,content-type]

## Lambda (doc-agent-document-api)
- Runtime: Python 3.12
- Timeout: 120초
- Memory: 256MB
- Function URL: https://35y43tlkgrh6i23oepsnabvkiu0mwkfh.lambda-url.ap-northeast-2.on.aws/ (AuthType=NONE)
- 환경변수: DOCUMENTS_TABLE, CONVERSATION_HISTORY_TABLE, APPSYNC_HTTP_URL, AGENTCORE_MEMORY_ID, AGENTCORE_RUNTIME_NAME

## AppSync Events API
- API ID: kf4xutqq7jdwfmo6pus64ildia
- HTTP: https://4vn4ck5lfrdjlcvcqelhvpj5ea.appsync-api.ap-northeast-2.amazonaws.com
- WebSocket: wss://4vn4ck5lfrdjlcvcqelhvpj5ea.appsync-realtime-api.ap-northeast-2.amazonaws.com
- API Key: da2-ee7jg4kisjhyhg2wnymolkmxdy
- Channel Namespace: `docs`
- 인증: Subscribe=API_KEY, Publish=AWS_IAM
- CloudFormation 스택: doc-agent-appsync-events (CREATE_COMPLETE)

### WebSocket 연결 프로토콜
- URL: `wss://{realtime-domain}/event/realtime`
- Subprotocol: `header-{base64url({"host":"{http-domain}","x-api-key":"{key}"})}`, `aws-appsync-event-ws`
- connection_init → connection_ack → subscribe → subscribe_success → data events

## CloudFront
- Distribution ID: E3227YKM7GU8YP
- Domain: dlstwg8d2t0h3.cloudfront.net
- Origin: S3 (doc-agent-frontend-*)
- SPA: 403/404 → /index.html (200)

## Cognito
- User Pool ID: ap-northeast-2_lhnBbisuM
- Client ID: 6m9or28dr68m9rh2b3prsqhbhe
- Hosted UI Domain: doc-agent-626635430480.auth.ap-northeast-2.amazoncognito.com
- Pre Sign-up Lambda: doc-agent-pre-signup (도메인 제한: @mz.co.kr, @megazone.com)
- 인증 방식: SRP (커스텀 로그인 UI)

## AgentCore
- Runtime: doc_agent_runtime_demo-E10F4T83ci (READY)
- Endpoint: doc_agent_endpoint_demo
- Gateway: doc-agent-gateway-demo-pnzf76klki
- Memory: doc_agent_memory-o6QiOB8zCT (handler.py용), doc_agent_memory_demo-EAmE03Aa8g (CDK용)

## DynamoDB
- doc-agent-documents (PK: document_id, GSI: user_id-updated_at-index)
- doc-agent-conversation-history (PK: document_id, SK: session_id)
- doc-agent-patch-history (PK: document_id, SK: patch_id)

## S3
- doc-agent-artifacts-* (에이전트 코드, 다이어그램 등)
- doc-agent-frontend-* (프론트 빌드 파일)

## 주요 제약사항
- API Gateway HTTP API 타임아웃: **30초 하드 리밋** (변경 불가)
- Lambda 타임아웃: 120초 (API GW 경유 시 30초에 503)
- Lambda Function URL: 타임아웃 없음 (Lambda 타임아웃만 적용)
- AppSync Events publish: Lambda에서 SigV4 서명된 HTTP POST로 호출
- Bedrock 서울 리전: inference profile 필수 (직접 모델 ID 불가)
