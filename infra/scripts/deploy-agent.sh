#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_aws_env.sh"
export PYTHONWARNINGS="ignore:Unverified HTTPS request"


# agent/.venv의 Python을 우선 사용 (override 가능)
VENV_PYTHON="$ROOT_DIR/agent/.venv/bin/python"
PYTHON_BIN="${PYTHON_BIN:-$VENV_PYTHON}"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "ERROR: Python not found at $PYTHON_BIN"
  echo "       agent/.venv가 없으면 먼저 만드세요:"
  echo "       cd agent && python3.12 -m venv .venv && source .venv/bin/activate && pip install boto3"
  exit 1
fi

echo "=== AgentCore Runtime-only deploy ==="
echo "[env] python=$($PYTHON_BIN --version)"

# bedrock-agentcore-control 서비스 사용 가능 여부 사전 검증
if ! "$PYTHON_BIN" -c "import boto3,sys; sys.exit(0 if 'bedrock-agentcore-control' in boto3.session.Session().get_available_services() else 1)"; then
  echo "ERROR: boto3가 'bedrock-agentcore-control' 서비스를 모릅니다."
  echo "       업그레이드: $PYTHON_BIN -m pip install --upgrade boto3 botocore"
  exit 1
fi

"$PYTHON_BIN" "$ROOT_DIR/infra/cdk/deploy.py" --env "$ENV" --region "$REGION"
echo "Done."