# Magali Zoom Operator Script

Use this for the next Magali call. The goal is to validate Outlook/Microsoft
365 authorization and Ollama readiness without creating any drafts.

## Before Joining

- Confirm the MailAssist work/school Entra app registration exists.
- Have the Application (client) ID copied somewhere local.
- Keep these files open:
  - `docs/magali-outlook.env.example`
  - `docs/magali-windows-readiness-runbook.md`
  - `docs/outlook-m365-admin-consent.md`
- Do not ask Magali for passwords, security codes, or private message content.

## Opening

Suggested wording:

> Today I only want to check whether MailAssist can connect to your Microsoft
> 365 mailbox and whether your local model responds through MailAssist. We are
> not sending email, and the first Outlook check will not create drafts.

Ask her to share only the terminal/browser window involved in setup when
possible.

## Setup Sequence

1. Open PowerShell.
2. Paste the bootstrap command:

```powershell
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/ec92009/MailAssist/main/tools/magali-bootstrap.ps1" -OutFile "$env:USERPROFILE\Downloads\magali-bootstrap.ps1"; PowerShell -ExecutionPolicy Bypass -File "$env:USERPROFILE\Downloads\magali-bootstrap.ps1"
```

This downloads MailAssist into `Downloads\MailAssist-main`, installs `uv` if
missing, installs Python 3.12 through `uv`, syncs the project, and runs the safe
Outlook/Ollama readiness checks. It does not create drafts or send email.

Manual fallback:

1. Open the MailAssist folder on the Windows machine.
2. Copy the template:

```powershell
Copy-Item docs\magali-outlook.env.example .env
```

3. Run the helper with the Entra Application (client) ID:

```powershell
.\tools\magali-readiness.ps1 -ClientId <application-client-id>
```

Current verified client id:

```powershell
.\tools\magali-readiness.ps1 -ClientId 2b2639c3-605c-466d-ae89-63ef8ffff5c8
```

If PowerShell blocks scripts, run:

```powershell
PowerShell -ExecutionPolicy Bypass -File .\tools\magali-readiness.ps1 -ClientId <application-client-id>
```

The helper writes the client id into `.env`, keeps the tenant set to
`organizations`, syncs the environment, runs the read-only Outlook setup check,
and then runs the Ollama setup check.

If the Golden Years tenant id is known before the call, use:

```powershell
.\tools\magali-readiness.ps1 -ClientId <application-client-id> -TenantId <tenant-id>
```

Manual fallback: open `.env` and replace only:

```text
MAILASSIST_OUTLOOK_CLIENT_ID=<mailassist-entra-application-client-id>
```

4. Keep the tenant default unless the Golden Years tenant id is known:

```text
MAILASSIST_OUTLOOK_TENANT_ID=organizations
```

## Expected Prompts

For Outlook, Microsoft may show a device code and ask Magali to sign in in a
browser. She should sign in with:

```text
MagaliDomingue@goldenyearstaxstrategy.com
```

The requested permissions should be mailbox read/write for drafts and profile
sign-in. Stop if a prompt mentions sending mail.

For Ollama, the command should report that `qwen3:8b` is installed and then show
a short response time.

## Stop Conditions

Stop before continuing if:

- Microsoft asks for `Mail.Send` or says MailAssist can send mail.
- The signed-in mailbox is not
  `MagaliDomingue@goldenyearstaxstrategy.com`.
- Microsoft says admin approval is required.
- Ollama does not list `qwen3:8b`.
- The model response includes visible thinking text.
- Any command would create a draft before the read-only setup check succeeds.

## If Admin Consent Is Required

Do not improvise inside Microsoft admin screens. Capture the exact wording and
switch to `docs/outlook-m365-admin-consent.md`.

Useful note to Magali:

> This means Microsoft wants a tenant admin to approve the app's draft/mailbox
> access before it can connect. That is a normal Microsoft 365 policy gate.

## Only After Both Checks Pass

Do not create a draft unless Magali agrees and there is a harmless test thread.
The controlled command is:

```powershell
.\.venv\Scripts\mailassist.exe review-bot --action outlook-smoke-test --thread-id <conversation-id> --create-draft
```

It creates one unsent Outlook draft for the chosen thread. It does not send
email.
