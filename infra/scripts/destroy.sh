#!/usr/bin/env bash
set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-mzadmin}"
REGION="ap-northeast-2"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV="${ENV:-demo}"

echo "============================================"
echo " Doc Agent — Full Destroy (env=$ENV)"
echo " Profile: $AWS_PROFILE  Region: $REGION"
echo "============================================"

# -----------------------------------------------
# Step 1: AgentCore CDK destroy (reverse order)
# -----------------------------------------------
echo ""
echo "=== Step 1: AgentCore CDK destroy ==="
python "$ROOT_DIR/infra/cdk/destroy.py" --env "$ENV" --region "$REGION" || {
  echo "WARNING: AgentCore CDK destroy had errors (continuing with Terraform destroy)"
}

# -----------------------------------------------
# Step 2: Empty S3 buckets
# -----------------------------------------------
echo ""
echo "=== Step 2: Empty S3 buckets ==="
FRONTEND_BUCKET=$(terraform -chdir="$ROOT_DIR/infra/terraform" output -raw frontend_bucket 2>/dev/null || echo "")
ARTIFACTS_BUCKET=$(terraform -chdir="$ROOT_DIR/infra/terraform" output -raw s3_bucket 2>/dev/null || echo "")

if [ -n "$FRONTEND_BUCKET" ]; then
  echo "Emptying $FRONTEND_BUCKET..."
  aws s3 rm "s3://$FRONTEND_BUCKET" --recursive --region "$REGION" || true
fi

if [ -n "$ARTIFACTS_BUCKET" ]; then
  echo "Emptying $ARTIFACTS_BUCKET..."
  aws s3 rm "s3://$ARTIFACTS_BUCKET" --recursive --region "$REGION" || true
fi

# -----------------------------------------------
# Step 3: Terraform destroy
# -----------------------------------------------
echo ""
echo "=== Step 3: Terraform destroy ==="
terraform -chdir="$ROOT_DIR/infra/terraform" destroy -auto-approve

echo ""
echo "============================================"
echo " Destroy complete!"
echo "============================================"
