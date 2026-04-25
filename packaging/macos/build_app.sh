#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h:h}"
PROJECT_PYTHON="$PROJECT_DIR/.venv/bin/python"

cd "$PROJECT_DIR"

if [[ -x "$PROJECT_PYTHON" ]]; then
  exec "$PROJECT_PYTHON" packaging/macos/build_app.py
fi

UV_BIN="${UV_BIN:-$(command -v uv || true)}"
if [[ -z "$UV_BIN" ]]; then
  echo "Neither $PROJECT_PYTHON nor uv was found." >&2
  exit 1
fi

exec "$UV_BIN" run --project "$PROJECT_DIR" python packaging/macos/build_app.py
