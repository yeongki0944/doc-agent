# Doc Agent 배포 가이드

## 환경 정보
- AWS 계정: 626635430480
- 프로필: mzadmin
- 리전: ap-northeast-2
- 프론트 URL: https://dlstwg8d2t0h3.cloudfront.net/
- API Gateway: https://7wejbdujd6.execute-api.ap-northeast-2.amazonaws.com/
- AgentCore Memory ID: doc_agent_memory-o6QiOB8zCT
- AgentCore Runtime: doc_agent_runtime_demo (ARN: arn:aws:bedrock-agentcore:ap-northeast-2:626635430480:runtime/doc_agent_runtime_demo-E10F4T83ci)

## 아키텍처 흐름
프론트 → API Gateway → Lambda (handler.py) → AgentCore Runtime → Orchestrator → Bedrock
- handler.py의 `_handle_chat`은 모든 채팅을 AgentCore Runtime으로 위임
- Runtime 내부에서 orchestrator → discovery/staffing/cost 등 서브에이전트 호출
- 직접 Bedrock 호출 코드는 handler.py에 없음 (Runtime이 처리)

## 배포 스크립트 위치
모든 스크립트는 `infra/scripts/` 에 있음.

## 전체 배포 (순서대로)

```bash
# 1. Terraform (인프라: API Gateway, Lambda, DynamoDB, Cognito, AppSync, S3, CloudFront)
./infra/scripts/deploy-tf.sh

# 2. Lambda 전체 (document_api + gateway tools 7개)
./infra/scripts/deploy-lambda.sh

# 3. 프론트엔드 (빌드 + S3 업로드 + CloudFront 무효화)
./infra/scripts/deploy-front.sh
```

## 부분 배포

### Lambda만 (백엔드 코드 변경 시)
```bash
# 전체 Lambda
./infra/scripts/deploy-lambda.sh

# 특정 Lambda만
./infra/scripts/deploy-lambda.sh document_api
./infra/scripts/deploy-lambda.sh validate_template
./infra/scripts/deploy-lambda.sh generate_diagram
./infra/scripts/deploy-lambda.sh estimate_cost
./infra/scripts/deploy-lambda.sh calc_staffing
./infra/scripts/deploy-lambda.sh export_docx
./infra/scripts/deploy-lambda.sh build_milestones
```

### 프론트만 (UI 변경 시)
```bash
./infra/scripts/deploy-front.sh
```

### Terraform만 (인프라 변경 시)
```bash
./infra/scripts/deploy-tf.sh          # apply
./infra/scripts/deploy-tf.sh plan     # 변경 미리보기만
```

## 프로젝트 구조
```
agent/                    # 백엔드 (Python)
  lambdas/
    document_api/         # 메인 API Lambda (채팅, CRUD, Bedrock)
    gateway_tools/        # AgentCore Gateway 도구 Lambda 6개
    on_publish/           # DynamoDB 스트림 핸들러
    pre_signup/           # Cognito 가입 도메인 제한 Lambda
  app/                    # 에이전트 로직 (orchestrator, discovery, cost 등)
  lib/                    # 공통 라이브러리 (schema, memory, storage, gateway)
front/                    # 프론트엔드 (React + Vite + TypeScript)
  src/auth/               # Cognito SRP 인증 (cognito.ts, AuthContext, api.ts)
  src/components/         # UI 컴포넌트
  src/store/              # Zustand 상태 관리
  src/styles/             # 디자인 토큰 (tokens.ts, components.ts)
infra/
  terraform/              # Terraform (API GW, Lambda, DynamoDB, Cognito, AppSync, CloudFront)
  scripts/                # 배포 스크립트
  cdk/                    # AgentCore CDK (deploy.py)
```

## 주요 환경변수 (deploy-front.sh가 자동 생성)
- VITE_API_URL — API Gateway URL
- VITE_COGNITO_CLIENT_ID — Cognito App Client ID
- VITE_COGNITO_USER_POOL_ID — Cognito User Pool ID
- VITE_APPSYNC_HTTP_URL — AppSync Events HTTP endpoint
- VITE_APPSYNC_WS_URL — AppSync Events WebSocket endpoint
- VITE_APPSYNC_API_KEY — AppSync API Key

## 주의사항
- Terraform provider는 aws ~> 5.0 (AppSync Events는 CloudFormation으로 생성)
- Lambda 런타임: Python 3.12
- 프론트 빌드: `npx vite build` (front/ 디렉토리)
- Cognito 가입 제한: @mz.co.kr, @megazone.com 도메인만 허용
