# Outlook / Microsoft 365 Graph Setup Notes

MailAssist's Outlook path uses Microsoft Graph delegated permissions. It reads the signed-in user's mailbox and creates provider-native drafts, but it does not send mail.

## App Registration

Create or use a Microsoft Entra app registration for the tenant that owns the mailbox.

For Magali's Microsoft 365 mailbox, the app registration must support work or
school accounts. Use one of these supported account type choices:

- Accounts in any organizational directory, if MailAssist is only testing
  Microsoft 365 business/school mailboxes.
- Accounts in any organizational directory and personal Microsoft accounts, if
  the same app registration should continue supporting both Magali's Microsoft
  365 mailbox and personal Outlook.com smoke tests.

Do not use a personal-Microsoft-account-only app registration for Magali's
Golden Years mailbox.

## Developer Tenant Options

As of April 2026, Microsoft's free Microsoft 365 E5 developer sandbox is limited to
qualifying Microsoft 365 Developer Program members. The most reliable path is a
Visual Studio Professional or Enterprise subscription benefit; other qualifying
programs may also be eligible from the Developer Program dashboard.

For MailAssist testing, use one of these tenant paths:

1. Microsoft 365 Developer Program E5 sandbox, if the account qualifies.
2. A paid or trial Microsoft 365 Business/E5 tenant dedicated to testing.
3. Magali's real Microsoft 365 tenant, after app registration and consent are
   approved by the tenant owner/admin.
4. A personal Outlook.com/Microsoft account for a limited Graph smoke test.

Prefer an instant sandbox when available because it includes Outlook, sample
mail/calendar data, test users, and an admin account. Use a configurable sandbox
only when a custom tenant domain is useful enough to justify slower provisioning.

Personal Outlook.com accounts are useful for validating delegated Graph mail
read/write and draft creation, but they do not validate Microsoft 365 business
tenant setup, Exchange Online admin policy, or tenant-admin consent.

Recommended delegated Microsoft Graph scopes for the current implementation:

- `offline_access`
- `User.Read`
- `Mail.ReadWrite`

`Mail.ReadWrite` is intentionally used instead of `Mail.Send` because MailAssist creates drafts only. Microsoft Graph's permission reference describes delegated `Mail.ReadWrite` as allowing read/write access to the signed-in user's mailbox and not including send permission.

Set these local environment values in `.env`:

```text
MAILASSIST_OUTLOOK_ENABLED=true
MAILASSIST_DEFAULT_PROVIDER=outlook
MAILASSIST_OUTLOOK_CLIENT_ID=<application-client-id>
MAILASSIST_OUTLOOK_TENANT_ID=<tenant-id-or-organizations>
MAILASSIST_OUTLOOK_TOKEN_FILE=secrets/outlook-token.json
```

The token file path stays under `secrets/`, which is ignored by git.

For Magali's setup, prefer her tenant id if known. Otherwise use
`MAILASSIST_OUTLOOK_TENANT_ID=organizations` so the device-code flow targets
work/school accounts instead of personal Microsoft accounts.

## First Authorization

For a read-only setup check that authorizes Outlook, verifies the signed-in
mailbox, previews a few inbox thread subjects, and creates no drafts, run:

```bash
./.venv/bin/mailassist outlook-setup-check --expected-email <mailbox-email>
```

For authorization only, run:

```bash
./.venv/bin/mailassist outlook-auth
```

MailAssist uses the Microsoft identity device-code flow. The command prints Microsoft's sign-in instructions, stores the returned token locally, then checks `/me`.

## Smoke Test

Read-only smoke test:

```bash
./.venv/bin/mailassist review-bot --action outlook-smoke-test --limit 5
```

Controlled draft smoke test:

```bash
./.venv/bin/mailassist review-bot \
  --action outlook-smoke-test \
  --thread-id <conversation-id> \
  --create-draft
```

The draft command requires an explicit thread id so it does not write to an arbitrary mailbox thread.

## Admin Consent

Some tenants block user consent for third-party apps. If authorization reports admin consent is required, ask the tenant admin to approve the app registration's delegated Graph permissions.

Microsoft's v2 admin-consent endpoint format is:

```text
https://login.microsoftonline.com/{tenant}/v2.0/adminconsent?client_id={client_id}&scope=https://graph.microsoft.com/.default&redirect_uri={redirect_uri}&state=mailassist
```

Use the tenant id when possible. The redirect URI must match the app registration.

Primary Microsoft references:

- https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-device-code
- https://learn.microsoft.com/en-us/entra/identity-platform/v2-admin-consent
- https://learn.microsoft.com/en-us/graph/permissions-reference
- https://learn.microsoft.com/en-us/graph/api/message-createreply?view=graph-rest-1.0
