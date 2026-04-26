#!/usr/bin/env bash
set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-mzadmin}"
REGION="ap-northeast-2"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV="${ENV:-demo}"

echo "============================================"
echo " Doc Agent — Full Deploy (env=$ENV)"
echo " Profile: $AWS_PROFILE  Region: $REGION"
echo "============================================"

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

  # Write API URL into .env for build
  echo "VITE_API_URL=$API_GW_URL" > .env.production

  npm install --silent
  npx vite build

  aws s3 sync dist/ "s3://$FRONTEND_BUCKET/" --delete --region "$REGION"
  aws cloudfront create-invalidation \
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
