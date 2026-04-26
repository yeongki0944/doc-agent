#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_aws_env.sh"

echo "=== Front-only deploy ==="

API_GW_URL=$(terraform -chdir="$TF_DIR" output -raw api_gateway_url)
FRONTEND_BUCKET=$(terraform -chdir="$TF_DIR" output -raw frontend_bucket)
CF_DIST_ID=$(terraform -chdir="$TF_DIR" output -raw cloudfront_distribution_id)
CF_DOMAIN=$(terraform -chdir="$TF_DIR" output -raw cloudfront_domain)

COGNITO_DOMAIN=$(terraform -chdir="$TF_DIR" output -raw cognito_hosted_ui_domain)
COGNITO_CLIENT_ID=$(terraform -chdir="$TF_DIR" output -raw cognito_user_pool_client_id)
COGNITO_USER_POOL_ID=$(terraform -chdir="$TF_DIR" output -raw cognito_user_pool_id)
APPSYNC_HTTP_URL=$(terraform -chdir="$TF_DIR" output -raw appsync_http_url)
APPSYNC_WS_URL=$(terraform -chdir="$TF_DIR" output -raw appsync_ws_url)
APPSYNC_API_KEY=$(terraform -chdir="$TF_DIR" output -raw appsync_api_key)

cd "$ROOT_DIR/front"
cat > .env.production <<EOF
VITE_API_URL=$API_GW_URL
VITE_COGNITO_DOMAIN=$COGNITO_DOMAIN
VITE_COGNITO_CLIENT_ID=$COGNITO_CLIENT_ID
VITE_COGNITO_USER_POOL_ID=$COGNITO_USER_POOL_ID
VITE_APPSYNC_HTTP_URL=$APPSYNC_HTTP_URL
VITE_APPSYNC_WS_URL=$APPSYNC_WS_URL
VITE_APPSYNC_API_KEY=$APPSYNC_API_KEY
EOF

[ -d node_modules ] || npm install --silent
npx vite build

aws s3 sync dist/ "s3://$FRONTEND_BUCKET/" \
  --profile "$AWS_PROFILE" --region "$REGION" --delete

aws cloudfront create-invalidation \
  --profile "$AWS_PROFILE" \
  --distribution-id "$CF_DIST_ID" \
  --paths "/*" \
  --query 'Invalidation.Id' --output text

echo ""
echo "Front deployed: https://$CF_DOMAIN/"