#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_aws_env.sh"

# 사용법:
#   ./deploy-tf.sh           # apply
#   ./deploy-tf.sh plan      # plan만 (변경 미리보기)
#   ./deploy-tf.sh init      # init만

ACTION="${1:-apply}"

echo "=== Terraform-only deploy (action=$ACTION) ==="

case "$ACTION" in
  init)
    terraform -chdir="$TF_DIR" init -input=false
    ;;
  plan)
    terraform -chdir="$TF_DIR" init -input=false
    terraform -chdir="$TF_DIR" plan
    ;;
  apply)
    terraform -chdir="$TF_DIR" init -input=false
    terraform -chdir="$TF_DIR" apply -auto-approve

    echo ""
    echo "=== Outputs ==="
    echo "  API Gateway: $(terraform -chdir="$TF_DIR" output -raw api_gateway_url)"
    echo "  Frontend:    $(terraform -chdir="$TF_DIR" output -raw frontend_bucket)"
    echo "  CloudFront:  https://$(terraform -chdir="$TF_DIR" output -raw cloudfront_domain)/"
    ;;
  *)
    echo "ERROR: unknown action '$ACTION'. Use: init | plan | apply"
    exit 1
    ;;
esac

echo "Done."