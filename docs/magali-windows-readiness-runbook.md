# Magali Windows Readiness Runbook

Use this after the MailAssist Microsoft Entra app registration exists. The goal
is to validate Magali's Outlook/Microsoft 365 access and local Ollama model
without creating drafts first.

## Current Blocker

Create or verify a MailAssist Microsoft Entra app registration that supports
work/school accounts, then copy its Application (client) ID into the Windows
machine `.env`.

The app must:

- Support work/school accounts.
- Allow public-client/native device-code auth.
- Request delegated Graph scopes only: `offline_access`, `User.Read`, and
  `Mail.ReadWrite`.
- Not request `Mail.Send`.

Use `docs/outlook-m365-admin-consent.md` for the exact Entra checklist and
admin-consent fallback.
Use `docs/magali-zoom-operator-script.md` as the call-time talk track.

## Prepare `.env`

Use the verified work/school client id:

```text
MAILASSIST_OUTLOOK_CLIENT_ID=2b2639c3-605c-466d-ae89-63ef8ffff5c8
MAILASSIST_OUTLOOK_TENANT_ID=organizations
```

Start from:

```powershell
Copy-Item docs\magali-outlook.env.example .env
```

Edit only the placeholder client id at first:

```text
MAILASSIST_OUTLOOK_CLIENT_ID=<application-client-id>
```

Keep these defaults unless the Golden Years tenant id is known:

```text
MAILASSIST_OUTLOOK_TENANT_ID=organizations
MAILASSIST_OUTLOOK_TOKEN_FILE=secrets/outlook-token.json
MAILASSIST_OLLAMA_MODEL=qwen3:8b
```

Do not commit `.env` or anything under `secrets/`.

## Sync And Install

From the MailAssist checkout on Windows:

```powershell
git checkout main
git pull origin main
uv sync
```

Use the Windows virtualenv executable:

```powershell
.\.venv\Scripts\mailassist.exe --help
```

## Safe Readiness Checks

The simplest call-time path is to pass the Entra Application (client) ID into
the helper so it updates `.env` for you:

```powershell
.\tools\magali-readiness.ps1 -ClientId <application-client-id>
```

For the current app registration:

```powershell
.\tools\magali-readiness.ps1 -ClientId 2b2639c3-605c-466d-ae89-63ef8ffff5c8
```

If PowerShell blocks scripts, run:

```powershell
PowerShell -ExecutionPolicy Bypass -File .\tools\magali-readiness.ps1 -ClientId <application-client-id>
```

If the Golden Years tenant id is known, add it explicitly:

```powershell
.\tools\magali-readiness.ps1 -ClientId <application-client-id> -TenantId <tenant-id>
```

The script verifies that `.env` no longer contains the client-id placeholder,
rejects personal-account/common tenant settings for this Magali path, then runs
the two checks below.

Run Outlook first. This opens Microsoft's device-code sign-in flow, verifies the
signed-in mailbox, previews inbox thread subjects only, and creates no drafts.

```powershell
.\.venv\Scripts\mailassist.exe outlook-setup-check --expected-email MagaliDomingue@goldenyearstaxstrategy.com
```

Stop if the signed-in mailbox is not the Golden Years mailbox, if Microsoft
requests an unexpected permission, or if Microsoft reports admin approval is
required.

Then test Ollama through MailAssist's own `think:false` path:

```powershell
.\.venv\Scripts\mailassist.exe ollama-setup-check --model qwen3:8b
```

This is the relevant model check. Do not use raw `ollama run` as the readiness
signal because raw runs may expose thinking output that MailAssist disables.

## Controlled Draft Write

Only after both safe checks pass, choose an explicit harmless Outlook thread id
from a known test message. Then create one unsent reply draft:

```powershell
.\.venv\Scripts\mailassist.exe review-bot --action outlook-smoke-test --thread-id <conversation-id> --create-draft
```

This creates one provider-native Outlook draft. It does not send email.

## Success Criteria

- Outlook setup check signs in as
  `MagaliDomingue@goldenyearstaxstrategy.com`.
- Inbox preview works without showing message bodies.
- No draft is created during setup checks.
- Ollama reports `qwen3:8b` is installed and returns a non-thinking response.
- Any later draft write is explicit, one-thread-only, and unsent.
