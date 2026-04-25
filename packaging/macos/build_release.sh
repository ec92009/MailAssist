#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h:h}"
PROJECT_PYTHON="$PROJECT_DIR/.venv/bin/python"

cd "$PROJECT_DIR"

if [[ ! -x "$PROJECT_PYTHON" ]]; then
  echo "Missing $PROJECT_PYTHON. Create the MailAssist virtualenv first." >&2
  exit 1
fi

if ! "$PROJECT_PYTHON" -c "import PyInstaller" >/dev/null 2>&1; then
  UV_BIN="${UV_BIN:-$(command -v uv || true)}"
  if [[ -z "$UV_BIN" ]]; then
    echo "PyInstaller is not installed and uv was not found." >&2
    exit 1
  fi
  "$UV_BIN" pip install --python "$PROJECT_PYTHON" pyinstaller
fi

exec "$PROJECT_PYTHON" packaging/macos/build_release.py
