#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="${0:A:h}"
cd "$SCRIPT_DIR"

UV_BIN="${UV_BIN:-$(command -v uv || true)}"
if [[ -z "$UV_BIN" ]]; then
  echo "uv was not found on PATH." >&2
  exit 1
fi

exec "$UV_BIN" run python src/mailassist/build_macos_app.py
