#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

display_name="MailAssist Outlook"
sign_in_audience="AzureADMultipleOrgs"
update_app_id=""
write_env=0

usage() {
  cat <<'EOF'
Create or update the MailAssist Outlook Microsoft Entra app registration.

Requires:
  az login
  permission to create or update app registrations in the signed-in tenant

Usage:
  ./tools/create-outlook-entra-app.sh [options]

Options:
  --display-name NAME    App display name. Default: MailAssist Outlook
  --audience VALUE       signInAudience. Default: AzureADMultipleOrgs
                         Allowed useful values:
                           AzureADMultipleOrgs
                           AzureADandPersonalMicrosoftAccount
  --update APP_ID        Update an existing app registration instead of creating one
  --write-env            Write MAILASSIST_OUTLOOK_CLIENT_ID and tenant to .env
  -h, --help             Show this help

This script configures only delegated Graph scopes:
  offline_access, User.Read, Mail.ReadWrite

It does not create a client secret and does not add Mail.Send.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --display-name)
      display_name="${2:-}"
      shift 2
      ;;
    --audience)
      sign_in_audience="${2:-}"
      shift 2
      ;;
    --update)
      update_app_id="${2:-}"
      shift 2
      ;;
    --write-env)
      write_env=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$sign_in_audience" != "AzureADMultipleOrgs" && "$sign_in_audience" != "AzureADandPersonalMicrosoftAccount" ]]; then
  echo "Unsupported audience for Magali setup: $sign_in_audience" >&2
  echo "Use AzureADMultipleOrgs or AzureADandPersonalMicrosoftAccount." >&2
  exit 2
fi

if ! command -v az >/dev/null 2>&1; then
  echo "Azure CLI is not installed. Install it first, then run az login." >&2
  exit 1
fi

if ! az account show >/dev/null 2>&1; then
  echo "Azure CLI is not signed in. Run: az login" >&2
  exit 1
fi

permissions_file="docs/mailassist-outlook-graph-permissions.json"
./.venv/bin/python -m json.tool "$permissions_file" >/dev/null

tenant_id="$(az account show --query tenantId -o tsv)"

if [[ -n "$update_app_id" ]]; then
  echo "Updating existing app registration: $update_app_id"
  az ad app update \
    --id "$update_app_id" \
    --display-name "$display_name" \
    --sign-in-audience "$sign_in_audience" \
    --is-fallback-public-client true \
    --required-resource-accesses @"$permissions_file" \
    --only-show-errors
  app_id="$(az ad app show --id "$update_app_id" --query appId -o tsv)"
else
  echo "Creating app registration: $display_name"
  app_id="$(az ad app create \
    --display-name "$display_name" \
    --sign-in-audience "$sign_in_audience" \
    --is-fallback-public-client true \
    --required-resource-accesses @"$permissions_file" \
    --query appId \
    -o tsv)"
fi

echo
echo "MailAssist Outlook app registration is ready."
echo "Application (client) ID: $app_id"
echo "Tenant ID from current az account: $tenant_id"
echo
echo "Use this for Magali unless the app is in a non-Golden-Years tenant:"
echo "MAILASSIST_OUTLOOK_CLIENT_ID=$app_id"
echo "MAILASSIST_OUTLOOK_TENANT_ID=organizations"
echo
echo "If this is the Golden Years tenant, prefer:"
echo "MAILASSIST_OUTLOOK_TENANT_ID=$tenant_id"

if [[ "$write_env" -eq 1 ]]; then
  if [[ ! -f .env ]]; then
    cp docs/magali-outlook.env.example .env
  fi
  ./.venv/bin/python - "$app_id" "$tenant_id" <<'PY'
from pathlib import Path
import sys

app_id = sys.argv[1]
tenant_id = sys.argv[2]
path = Path(".env")
lines = path.read_text(encoding="utf-8").splitlines()
values = {
    "MAILASSIST_OUTLOOK_CLIENT_ID": app_id,
    "MAILASSIST_OUTLOOK_TENANT_ID": tenant_id,
}
seen = set()
out = []
for line in lines:
    key = line.split("=", 1)[0].strip() if "=" in line else ""
    if key in values:
        out.append(f"{key}={values[key]}")
        seen.add(key)
    else:
        out.append(line)
for key, value in values.items():
    if key not in seen:
        out.append(f"{key}={value}")
path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
PY
  echo
  echo "Updated .env with the client id and current tenant id."
fi
