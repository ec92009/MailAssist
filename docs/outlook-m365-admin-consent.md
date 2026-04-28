# Outlook / Microsoft 365 Graph Setup Notes

MailAssist's Outlook path uses Microsoft Graph delegated permissions. It reads the signed-in user's mailbox and creates provider-native drafts, but it does not send mail.

## App Registration

Create or use a Microsoft Entra app registration for the tenant that owns the mailbox.

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

## First Authorization

Run:

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
