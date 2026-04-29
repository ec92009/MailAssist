# Magali Outlook Call Checklist

Use this when Magali offers a short Pacific-time window. The goal is to learn
which Microsoft account owns her business mailbox and whether MailAssist can be
authorized without turning the call into technical support.

## Ground Rules

- Do not ask Magali to share passwords, security codes, or private email
  content.
- Ask her to share a browser window or Outlook settings window, not her whole
  desktop, when possible.
- If Microsoft asks for an authenticator code or password, have her enter it
  privately while screen sharing is paused or while the sign-in window is not
  visible.
- Stop before approving any unfamiliar consent prompt if the wording is
  surprising or includes send-mail permission.
- MailAssist should request read/write mailbox access for drafts only. It
  should not request permission to send mail.

## What We Already Know

- Website host: Squarespace (`www.goldenyearstaxstrategy.com` points to
  Squarespace).
- Primary mail host: Microsoft 365 / Exchange Online
  (`goldenyearstaxstrategy-com.mail.protection.outlook.com`).
- Mailgun is also present in DNS, likely for website or transactional mail.
- Screen-share findings from April 28, 2026:
  - Microsoft account home organization is Golden Years Tax Strategy.
  - `admin.microsoft.com` opens for Magali, so she appears to have Microsoft
    365 admin access.
  - Her mailbox is licensed as Microsoft 365 Business Standard (no Teams).
  - Outlook on the web opens the Golden Years mailbox.
  - Classic Outlook Desktop shows the account type as Microsoft Exchange.
  - Ollama is installed on her Windows laptop with `qwen3:8b` (5.2 GB),
    modified 4 days before the call.
  - The direct terminal `ollama run qwen3:8b ...` path appeared slow and showed
    thinking behavior; MailAssist should use its own `think: false` Ollama path
    for the real setup test.

## Before The Call

- Have a MailAssist Outlook app registration client id ready that supports
  work/school Microsoft 365 accounts. A personal-Microsoft-account-only client
  id will not be enough for Magali's Golden Years mailbox.
- Start from `docs/magali-outlook.env.example` for the Windows machine `.env`.
  Replace only `MAILASSIST_OUTLOOK_CLIENT_ID` before the call; keep the token
  path under ignored `secrets/`.
- Have the local commands ready, but do not run provider-writing commands until
  consent/readiness is understood.
- Keep this file and `docs/outlook-m365-admin-consent.md` open.
- Keep `docs/magali-zoom-operator-script.md` open for the call-time script.
- Suggested screen-share tool: Zoom or Google Meet. Avoid remote control unless
  it is truly needed.

## Ask Her To Open These

1. Open Outlook on the web:
   `https://outlook.office.com/mail/`

   Ask her to sign in with her Golden Years email if prompted. Once mail opens,
   ask her to click her initials or photo in the top-right corner and share a
   screenshot of the account box.

   What this tells us:
   - Whether the Golden Years mailbox opens in Microsoft-hosted Outlook.
   - The signed-in account identity.

2. Open Microsoft account profile:
   `https://myaccount.microsoft.com/`

   Ask her to sign in with the same Golden Years email. Screenshot the first
   page or the error message.

   What this tells us:
   - Whether Microsoft sees the account as a work/school tenant account.
   - Organization or tenant hints, if shown.

3. Open Microsoft 365 admin center:
   `https://admin.microsoft.com/`

   Ask her to sign in with the same Golden Years email. Screenshot whatever
   appears. It is fine if she is blocked or sees a permissions message.

   What this tells us:
   - Whether she is likely the tenant admin.
   - Whether admin consent can be handled by her during the call or needs
     another account/person.

4. Open Outlook Desktop account settings, if easy:
   - Classic Outlook: File -> Account Settings -> Account Settings.
   - Screenshot only the row for the Golden Years email.
   - If there is no File menu or it is confusing, skip this step.

   What this tells us:
   - Whether Outlook Desktop calls the account Microsoft 365, Exchange, IMAP,
     or something else.

## If We Try MailAssist Authorization

Start with the one-command read-only setup check:

```bash
./.venv/bin/mailassist outlook-setup-check \
  --expected-email MagaliDomingue@goldenyearstaxstrategy.com
```

This authorizes Outlook, checks the signed-in account, previews a few inbox
thread subjects, and does not create drafts or send email.

Do not create provider drafts until the read-only setup check succeeds and the
account identity is clearly the Golden Years mailbox.

Then run MailAssist's own Ollama path instead of raw `ollama run`:

```bash
./.venv/bin/mailassist ollama-setup-check --model qwen3:8b
```

This uses the same local Ollama HTTP path as MailAssist drafts and sends
`think:false`, so it is the relevant model check for her installed model.

If the read-only smoke test succeeds, a controlled draft test is the next safe
write:

```bash
./.venv/bin/mailassist review-bot \
  --action outlook-smoke-test \
  --thread-id <conversation-id> \
  --create-draft
```

This creates one unsent reply draft for an explicit thread id. It does not send
email.

## Result Meanings

- Outlook web opens the Golden Years mailbox: Microsoft Graph is likely the
  right provider path.
- `myaccount.microsoft.com` opens normally: work/school identity is likely
  usable.
- `admin.microsoft.com` opens: she may be the Microsoft 365 admin.
- `admin.microsoft.com` blocks her: user consent may still work, but admin
  consent may require another admin account.
- Microsoft says approval is required: capture the exact wording and use
  `docs/outlook-m365-admin-consent.md`.
- Microsoft shows a send-mail permission: stop and inspect the app/scopes
  before continuing.

## Minimum Useful Outcome

Even if there is no time to run MailAssist, get these three screenshots:

1. Outlook web top-right account box.
2. `myaccount.microsoft.com` first page or error.
3. `admin.microsoft.com` first page or error.

Those are enough to decide the next technical step without another long call.

## Current Outcome

The minimum useful outcome is complete. Do not repeat the passive discovery
steps unless something changes. The next useful work is to prepare a
Magali-ready install flow and run `mailassist outlook-setup-check` plus
MailAssist's own model check on her machine rather than relying on raw
`ollama run`.
