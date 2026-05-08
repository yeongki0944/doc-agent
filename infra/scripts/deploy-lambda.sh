#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_aws_env.sh"

# 사용법:
#   ./deploy-lambda.sh                    # 7개 전부
#   ./deploy-lambda.sh document_api       # 한 개만
#   ./deploy-lambda.sh validate_template  # gateway tool 한 개

TARGET="${1:-all}"

LAMBDA_KEYS=(document_api validate_template generate_diagram estimate_cost calc_staffing export_docx build_milestones create_calculator_link explain_aws_services)

lambda_info() {
  case "$1" in
    document_api)              echo "doc-agent-document-api:agent/lambdas/document_api/handler.py" ;;
    validate_template)         echo "doc-agent-validate-template:agent/lambdas/gateway_tools/validate_template.py" ;;
    generate_diagram)          echo "doc-agent-generate-diagram:agent/lambdas/gateway_tools/generate_diagram.py" ;;
    estimate_cost)             echo "doc-agent-estimate-cost:agent/lambdas/gateway_tools/estimate_cost.py" ;;
    calc_staffing)             echo "doc-agent-calc-staffing:agent/lambdas/gateway_tools/calc_staffing.py" ;;
    export_docx)               echo "doc-agent-export-docx:agent/lambdas/gateway_tools/export_docx.py" ;;
    build_milestones)          echo "doc-agent-build-milestones:agent/lambdas/gateway_tools/build_milestones.py" ;;
    create_calculator_link)    echo "doc-agent-create-calculator-link:agent/lambdas/gateway_tools/create_calculator_link.py" ;;
    explain_aws_services)      echo "doc-agent-explain-aws-services:agent/lambdas/gateway_tools/explain_aws_services.py" ;;
    *) echo "" ;;
  esac
}

update_one() {
  local key="$1"
  local entry; entry=$(lambda_info "$key")
  local fn_name="${entry%%:*}"
  local src_path="${entry##*:}"

  echo "  Updating $fn_name ..."
  zip -j "/tmp/${key}.zip" "$ROOT_DIR/$src_path" >/dev/null
  aws lambda update-function-code \
    --profile "$AWS_PROFILE" --region "$REGION" \
    --function-name "$fn_name" \
    --zip-file "fileb:///tmp/${key}.zip" \
    --query 'CodeSha256' --output text
}

echo "=== Lambda-only deploy (target=$TARGET) ==="

if [ "$TARGET" = "all" ]; then
  for key in "${LAMBDA_KEYS[@]}"; do update_one "$key"; done
else
  info=$(lambda_info "$TARGET")
  if [ -z "$info" ]; then
    echo "ERROR: unknown lambda '$TARGET'. Available: ${LAMBDA_KEYS[*]}"
    exit 1
  fi
  update_one "$TARGET"
fi

echo "Done."