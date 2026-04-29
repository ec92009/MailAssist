#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

app_id="${1:-}"
if [[ -z "$app_id" || "$app_id" == "-h" || "$app_id" == "--help" ]]; then
  cat <<'EOF'
Verify a MailAssist Outlook Microsoft Entra app registration.

Requires:
  az login
  permission to read app registrations in the signed-in tenant

Usage:
  ./tools/verify-outlook-entra-app.sh <application-client-id>

Checks:
  - signInAudience supports work/school accounts
  - public/native client fallback is enabled
  - delegated Graph permissions include offline_access, User.Read, Mail.ReadWrite
  - Mail.Send is not configured
  - no application permissions are configured
EOF
  exit 0
fi

if ! command -v az >/dev/null 2>&1; then
  echo "Azure CLI is not installed." >&2
  exit 1
fi

if ! az account show >/dev/null 2>&1; then
  echo "Azure CLI is not signed in. Run: az login" >&2
  exit 1
fi

app_json="$(az ad app show --id "$app_id" --output json)"

./.venv/bin/python - "$app_json" <<'PY'
import json
import sys

app = json.loads(sys.argv[1])

allowed_audiences = {"AzureADMultipleOrgs", "AzureADandPersonalMicrosoftAccount"}
graph_app_id = "00000003-0000-0000-c000-000000000000"
expected_scopes = {
    "7427e0e9-2fba-42fe-b0c0-848c9e6a8182": "offline_access",
    "e1fe6dd8-ba31-4d61-89e7-88639da4683d": "User.Read",
    "024d486e-b451-40bb-833d-3e66d98c5c73": "Mail.ReadWrite",
}
blocked_ids = {
    "e2a3a72e-5f79-4c64-b1b1-878b674786c9": "Mail.ReadWrite application permission",
    "e383f46e-2787-4529-855e-0e479a3ffac0": "Mail.Send delegated permission",
    "b633e1c5-b582-4048-a93e-9f11b44c7e96": "Mail.Send application permission",
}

status = 0

def ok(message: str) -> None:
    print(f"ok: {message}")

def fail(message: str) -> None:
    global status
    status = 1
    print(f"blocked: {message}")

audience = app.get("signInAudience") or ""
if audience in allowed_audiences:
    ok(f"signInAudience={audience}")
else:
    fail(f"signInAudience={audience or '(missing)'} does not support Magali's work/school mailbox")

if app.get("isFallbackPublicClient") is True:
    ok("isFallbackPublicClient=true")
else:
    fail("public/native client fallback is not enabled")

resources = app.get("requiredResourceAccess") or []
graph_resources = [item for item in resources if item.get("resourceAppId") == graph_app_id]
if not graph_resources:
    fail("Microsoft Graph permissions are missing")
    configured = []
else:
    configured = graph_resources[0].get("resourceAccess") or []

configured_scope_ids = {
    item.get("id")
    for item in configured
    if item.get("type") == "Scope"
}
configured_role_ids = {
    item.get("id")
    for item in configured
    if item.get("type") == "Role"
}

for scope_id, name in expected_scopes.items():
    if scope_id in configured_scope_ids:
        ok(f"delegated Graph scope present: {name}")
    else:
        fail(f"delegated Graph scope missing: {name}")

for blocked_id, name in blocked_ids.items():
    if blocked_id in configured_scope_ids or blocked_id in configured_role_ids:
        fail(f"forbidden permission configured: {name}")

if configured_role_ids:
    fail("application permissions are configured; MailAssist should use delegated permissions only")
else:
    ok("no Microsoft Graph application permissions configured")

if status == 0:
    print()
    print("Entra app registration looks ready for the Magali Outlook setup path.")
else:
    print()
    print("Entra app registration has blockers. Fix these before the Zoom call.")

raise SystemExit(status)
PY
