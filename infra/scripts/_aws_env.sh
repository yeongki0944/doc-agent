#!/usr/bin/env bash
# 모든 deploy-*.sh 스크립트가 source 해서 공유하는 환경 셋업.

unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
unset AWS_REGION AWS_DEFAULT_REGION

export AWS_PROFILE="${AWS_PROFILE:-mzadmin}"
export REGION="ap-northeast-2"
export EXPECTED_ACCOUNT="626635430480"
export ENV="${ENV:-demo}"

# bash이면 BASH_SOURCE, zsh이면 %x 사용
if [ -n "${BASH_SOURCE[0]:-}" ]; then
  _SOURCE="${BASH_SOURCE[0]}"
elif [ -n "${(%):-%x}" ] 2>/dev/null; then
  _SOURCE="${(%):-%x}"
else
  _SOURCE="$0"
fi

_THIS_DIR="$(cd "$(dirname "$_SOURCE")" && pwd)"
export ROOT_DIR="$(cd "$_THIS_DIR/../.." && pwd)"
export TF_DIR="$ROOT_DIR/infra/terraform"

CALLER_JSON=$(aws sts get-caller-identity --profile "$AWS_PROFILE" --output json)
CALLER_ACCOUNT=$(echo "$CALLER_JSON" | python3 -c "import sys,json;print(json.load(sys.stdin)['Account'])")
if [ "$CALLER_ACCOUNT" != "$EXPECTED_ACCOUNT" ]; then
  echo "ERROR: 잘못된 AWS 계정. expected=$EXPECTED_ACCOUNT, actual=$CALLER_ACCOUNT"
  return 1 2>/dev/null || exit 1
fi
echo "[env] account=$CALLER_ACCOUNT profile=$AWS_PROFILE region=$REGION env=$ENV root=$ROOT_DIR"