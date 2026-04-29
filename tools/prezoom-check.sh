#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "MailAssist pre-Zoom local check"
echo

status=0

check_file() {
  local path="$1"
  if [[ -f "$path" ]]; then
    echo "ok: $path"
  else
    echo "missing: $path"
    status=1
  fi
}

check_file docs/magali-pre-zoom-checklist.md
check_file docs/magali-zoom-operator-script.md
check_file docs/magali-windows-readiness-runbook.md
check_file docs/magali-outlook.env.example
check_file docs/outlook-m365-admin-consent.md
check_file docs/mailassist-outlook-entra-app-manifest.json
check_file docs/mailassist-outlook-graph-permissions.json
check_file docs/mailassist-outlook-entra-portal-steps.md
check_file tools/magali-bootstrap.ps1
check_file tools/magali-readiness.ps1
check_file tools/create-outlook-entra-app.sh
check_file tools/verify-outlook-entra-app.sh

echo
if command -v jq >/dev/null 2>&1; then
  jq -e '.signInAudience == "AzureADMultipleOrgs"' docs/mailassist-outlook-entra-app-manifest.json >/dev/null
  jq -e '.isFallbackPublicClient == true' docs/mailassist-outlook-entra-app-manifest.json >/dev/null
  echo "ok: Entra manifest JSON shape"
else
  ./.venv/bin/python -m json.tool docs/mailassist-outlook-entra-app-manifest.json >/dev/null
  ./.venv/bin/python -m json.tool docs/mailassist-outlook-graph-permissions.json >/dev/null
  echo "ok: Entra manifest JSON parses"
fi

if rg -n "Mail.Send|consumers|common" docs/magali-pre-zoom-checklist.md docs/magali-zoom-operator-script.md docs/magali-windows-readiness-runbook.md >/tmp/mailassist-prezoom-rg.txt; then
  echo "note: found explicit stop-condition references:"
  cat /tmp/mailassist-prezoom-rg.txt
else
  echo "warning: expected stop-condition text not found"
  status=1
fi

echo
if [[ -f .env ]]; then
  if rg -q '^MAILASSIST_OUTLOOK_CLIENT_ID=<mailassist-entra-application-client-id>' .env; then
    echo "blocked: .env still has the Outlook client-id placeholder"
    status=1
  elif rg -q '^MAILASSIST_OUTLOOK_CLIENT_ID=' .env; then
    echo "ok: .env has an Outlook client-id value"
  else
    echo "blocked: .env has no MAILASSIST_OUTLOOK_CLIENT_ID"
    status=1
  fi
  if rg -q '^MAILASSIST_OUTLOOK_TENANT_ID=(consumers|common)\s*$' .env; then
    echo "blocked: .env uses a personal/common Outlook tenant. Use organizations or the Golden Years tenant id."
    status=1
  elif rg -q '^MAILASSIST_OUTLOOK_TENANT_ID=' .env; then
    echo "ok: .env has a work/school-oriented Outlook tenant value"
  else
    echo "blocked: .env has no MAILASSIST_OUTLOOK_TENANT_ID"
    status=1
  fi
else
  echo "note: no local .env; this is fine until the Entra client id exists"
fi

echo
if command -v az >/dev/null 2>&1; then
  echo "ok: Azure CLI is installed"
  if az account show >/dev/null 2>&1; then
    echo "ok: Azure CLI is signed in"
  else
    echo "note: Azure CLI is installed but not signed in"
  fi
else
  echo "blocked for app creation: Azure CLI is not installed on this machine"
fi

echo
uv sync
./.venv/bin/pytest tests/test_cli_main.py

echo
if [[ "$status" -eq 0 ]]; then
  echo "Pre-Zoom local check passed. Remaining blocker may still be Entra access/client id."
else
  echo "Pre-Zoom local check found blockers above."
fi
exit "$status"
