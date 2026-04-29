# Magali Pre-Zoom Checklist

Use this before scheduling the next Magali setup call. Everything here can be
done without access to her private mailbox.

Current verified client id:

```text
MAILASSIST_OUTLOOK_CLIENT_ID=2b2639c3-605c-466d-ae89-63ef8ffff5c8
MAILASSIST_OUTLOOK_TENANT_ID=organizations
```

The source app registration lives in local tenant
`fff6075e-c052-4a48-b80b-fc2b03b9c4a0`, but Magali should use
`organizations` until her Golden Years tenant id is known.

## Entra App Registration

- Create or verify the MailAssist app registration in Microsoft Entra.
- Use `docs/mailassist-outlook-entra-portal-steps.md` for the portal path.
- Use `docs/mailassist-outlook-entra-app-manifest.json` as the manifest
  cross-check.
- Azure CLI is installed on the current Mac workspace; if using CLI, run
  `az login`, then `./tools/create-outlook-entra-app.sh`.
- If a client id already exists, run
  `./tools/verify-outlook-entra-app.sh <application-client-id>` before the call.
- Supported account type:
  - Preferred: Accounts in any organizational directory.
  - Acceptable: Accounts in any organizational directory and personal Microsoft
    accounts.
- Authentication:
  - Treat MailAssist as a public/native desktop client.
  - Allow public client flows.
- Microsoft Graph delegated permissions:
  - `offline_access`
  - `User.Read`
  - `Mail.ReadWrite`
- Do not add:
  - `Mail.Send`
  - Application permissions
  - Client secrets
- Copy the Application (client) ID.
- If available, copy the Golden Years tenant ID. If not available, use
  `organizations` during the first setup check.

## Local Repo Prep

- Confirm the repo is on `main`.
- Run:

```bash
git pull origin main
uv sync
./.venv/bin/pytest tests/test_cli_main.py
./tools/prezoom-check.sh
```

- Keep these files open:
  - `docs/magali-zoom-operator-script.md`
  - `docs/magali-windows-readiness-runbook.md`
  - `docs/outlook-m365-admin-consent.md`
  - `docs/mailassist-outlook-entra-portal-steps.md`

## Windows Command To Have Ready

If only the client ID is known:

```powershell
.\tools\magali-readiness.ps1 -ClientId <application-client-id>
```

If both the client ID and Golden Years tenant ID are known:

```powershell
.\tools\magali-readiness.ps1 -ClientId <application-client-id> -TenantId <tenant-id>
```

If PowerShell blocks scripts:

```powershell
PowerShell -ExecutionPolicy Bypass -File .\tools\magali-readiness.ps1 -ClientId <application-client-id>
```

## Call Goal

- Prove Microsoft signs in as
  `MagaliDomingue@goldenyearstaxstrategy.com`.
- Prove read-only inbox preview works without showing message bodies.
- Prove `qwen3:8b` responds through MailAssist's `think:false` Ollama path.
- Create no drafts during readiness checks.
- Send no email.

## Open Questions For The Call

- Does Microsoft allow user consent, or does it require admin approval?
- Does the consent wording mention only profile/sign-in and mailbox read/write?
- Does the machine already have `git`, `uv`, and Ollama available in PowerShell?
- Does `qwen3:8b` respond quickly enough through MailAssist?
