#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------
# AWS credentials sanity — must come BEFORE any aws/terraform call
# -----------------------------------------------
# 다른 계정의 임시 자격증명이 export되어 있으면 AWS_PROFILE을 덮어쓰므로 제거
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
unset AWS_REGION AWS_DEFAULT_REGION

export AWS_PROFILE="${AWS_PROFILE:-mzadmin}"
REGION="ap-northeast-2"
EXPECTED_ACCOUNT="626635430480"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV="${ENV:-demo}"

echo "============================================"
echo " Doc Agent — Full Deploy (env=$ENV)"
echo " Profile: $AWS_PROFILE  Region: $REGION"
echo "============================================"

# 어떤 계정으로 동작하는지 확인 후, 의도한 계정과 다르면 즉시 중단
echo ""
echo "=== Step 0: Verify AWS identity ==="
CALLER_JSON=$(aws sts get-caller-identity --profile "$AWS_PROFILE" --output json)
CALLER_ACCOUNT=$(echo "$CALLER_JSON" | python3 -c "import sys,json;print(json.load(sys.stdin)['Account'])")
CALLER_ARN=$(echo "$CALLER_JSON" | python3 -c "import sys,json;print(json.load(sys.stdin)['Arn'])")
echo "  Account: $CALLER_ACCOUNT"
echo "  ARN:     $CALLER_ARN"

if [ "$CALLER_ACCOUNT" != "$EXPECTED_ACCOUNT" ]; then
  echo ""
  echo "ERROR: 잘못된 AWS 계정입니다. expected=$EXPECTED_ACCOUNT, actual=$CALLER_ACCOUNT"
  echo "       env | grep AWS 로 다른 자격증명이 export되어 있지 않은지 확인하세요."
  exit 1
fi

# -----------------------------------------------
# Step 1: Terraform apply (base infrastructure)
# -----------------------------------------------
echo ""
echo "=== Step 1: Terraform apply ==="
terraform -chdir="$ROOT_DIR/infra/terraform" init -input=false
terraform -chdir="$ROOT_DIR/infra/terraform" apply -auto-approve

# Capture outputs
API_GW_URL=$(terraform -chdir="$ROOT_DIR/infra/terraform" output -raw api_gateway_url)
FRONTEND_BUCKET=$(terraform -chdir="$ROOT_DIR/infra/terraform" output -raw frontend_bucket)
CF_DIST_ID=$(terraform -chdir="$ROOT_DIR/infra/terraform" output -raw cloudfront_distribution_id)
CF_DOMAIN=$(terraform -chdir="$ROOT_DIR/infra/terraform" output -raw cloudfront_domain)

echo "Terraform outputs:"
echo "  API Gateway: $API_GW_URL"
echo "  Frontend:    $FRONTEND_BUCKET"

# -----------------------------------------------
# Step 2: Update Lambda code (document_api)
# -----------------------------------------------
echo ""
echo "=== Step 2: Update Lambda code (document_api) ==="
cd "$ROOT_DIR"
zip -j /tmp/document_api.zip agent/lambdas/document_api/handler.py
aws lambda update-function-code \
  --profile "$AWS_PROFILE" \
  --region "$REGION" \
  --function-name doc-agent-document-api \
  --zip-file fileb:///tmp/document_api.zip \
  --query 'CodeSha256' --output text
echo "Lambda code updated"

# -----------------------------------------------
# Step 3: Update Gateway Lambda code (6 targets)
# -----------------------------------------------
echo ""
echo "=== Step 3: Update Gateway Lambda code ==="
GATEWAY_LAMBDAS=(
  "validate_template:doc-agent-validate-template"
  "generate_diagram:doc-agent-generate-diagram"
  "estimate_cost:doc-agent-estimate-cost"
  "calc_staffing:doc-agent-calc-staffing"
  "export_docx:doc-agent-export-docx"
  "build_milestones:doc-agent-build-milestones"
)

for entry in "${GATEWAY_LAMBDAS[@]}"; do
  FILE="${entry%%:*}"
  FN_NAME="${entry##*:}"
  echo "  Updating $FN_NAME..."
  zip -j "/tmp/${FILE}.zip" "agent/lambdas/gateway_tools/${FILE}.py"
  aws lambda update-function-code \
    --profile "$AWS_PROFILE" \
    --region "$REGION" \
    --function-name "$FN_NAME" \
    --zip-file "fileb:///tmp/${FILE}.zip" \
    --query 'CodeSha256' --output text
done
echo "All Gateway Lambda code updated"

# -----------------------------------------------
# Step 4: AgentCore CDK deploy
# -----------------------------------------------
echo ""
echo "=== Step 4: AgentCore CDK deploy ==="
python "$ROOT_DIR/infra/cdk/deploy.py" --env "$ENV" --region "$REGION"

# -----------------------------------------------
# Step 5: Build & deploy frontend (optional)
# -----------------------------------------------
if [ "${SKIP_FRONTEND:-}" != "true" ]; then
  echo ""
  echo "=== Step 5: Build & deploy frontend ==="
  cd "$ROOT_DIR/front"

  echo "VITE_API_URL=$API_GW_URL" > .env.production

  npm install --silent
  npx vite build

  aws s3 sync dist/ "s3://$FRONTEND_BUCKET/" \
    --profile "$AWS_PROFILE" \
    --region "$REGION" \
    --delete
  aws cloudfront create-invalidation \
    --profile "$AWS_PROFILE" \
    --distribution-id "$CF_DIST_ID" \
    --paths "/*" \
    --query 'Invalidation.Id' --output text
  echo "Frontend deployed"
else
  echo ""
  echo "=== Step 5: Frontend deploy SKIPPED (SKIP_FRONTEND=true) ==="
fi

echo ""
echo "============================================"
echo " Deploy complete!"
echo " API:   $API_GW_URL"
echo " Front: https://$CF_DOMAIN/"
echo "============================================"