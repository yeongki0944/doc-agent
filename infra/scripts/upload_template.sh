#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_aws_env.sh"

python3 "$ROOT_DIR/infra/scripts/upload_template.py" \
  --template "${TEMPLATE_PATH:-agent/templates/apn-poc-template.docx}" \
  --tf-dir "$TF_DIR" \
  --profile "$AWS_PROFILE" \
  --region "$REGION" \
  "$@"
