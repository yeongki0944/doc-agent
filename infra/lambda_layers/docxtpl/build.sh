#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"
PYTHON_DIR="$SCRIPT_DIR/python"
LAYER_ZIP="$SCRIPT_DIR/layer.zip"
VENV_PYTHON="$ROOT_DIR/agent/.venv/bin/python"
PYTHON_BIN="${PYTHON_BIN:-$VENV_PYTHON}"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "ERROR: Python not found at $PYTHON_BIN"
  echo "       Set PYTHON_BIN or create agent/.venv with Python 3.12."
  exit 1
fi

rm -rf "$PYTHON_DIR" "$LAYER_ZIP"
mkdir -p "$PYTHON_DIR"

"$PYTHON_BIN" -m pip install \
  --requirement "$SCRIPT_DIR/requirements.txt" \
  --target "$PYTHON_DIR" \
  --platform manylinux2014_x86_64 \
  --implementation cp \
  --python-version 3.12 \
  --abi cp312 \
  --only-binary=:all: \
  --upgrade

cd "$SCRIPT_DIR"
zip -qr "$LAYER_ZIP" python

echo "Built $LAYER_ZIP"
