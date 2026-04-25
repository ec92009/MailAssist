# MailAssist

MailAssist is a local background email drafting assistant. It watches connected inboxes, uses a local Ollama model to decide whether a message needs a reply, and creates a draft directly in Gmail or Outlook when useful.

The user reviews, edits, sends, or deletes drafts in the normal mail client. MailAssist does not send email.

## Current Product Direction

- Bot runs continuously.
- Bot watches Gmail, Outlook, or mock input.
- Bot classifies new mail.
- Bot skips mail that does not need a response.
- Bot creates one provider draft for mail that needs a response.
- GUI configures and supervises the bot.
- Gmail/Outlook remain the review and editing surfaces.

## Current Docs

- [STRATEGY.md](~/Dev/MailAssist/STRATEGY.md): product direction and architecture
- [REALISM.md](~/Dev/MailAssist/REALISM.md): constraints and safety posture
- [RESEARCH.md](~/Dev/MailAssist/RESEARCH.md): provider, prompt, and GUI questions
- [RESULTS.md](~/Dev/MailAssist/RESULTS.md): current implementation status
- [TODO.md](~/Dev/MailAssist/TODO.md): active implementation list
- [SUMMARY.md](~/Dev/MailAssist/SUMMARY.md): latest project snapshot
- [docs/setting_up_gmail_connection_for_MailAssist.pdf](~/Dev/MailAssist/docs/setting_up_gmail_connection_for_MailAssist.pdf): first-time Gmail setup guide
- [docs/gmail_oauth_advanced.pdf](~/Dev/MailAssist/docs/gmail_oauth_advanced.pdf): detailed Gmail OAuth setup reference
- [ENVIRONMENT_SOP.md](~/Dev/MailAssist/ENVIRONMENT_SOP.md): local Python workflow
- [VERSIONING_SOP.md](~/Dev/MailAssist/VERSIONING_SOP.md): visible version rules
- [SHOW_ME_SOP.md](~/Dev/MailAssist/SHOW_ME_SOP.md): local UI launch workflow

Historical docs from the heavier review-queue direction are archived under:

```text
archived/2026-04-24-pre-background-bot/
```

## Setup

```bash
cd ~/Dev/MailAssist
uv venv .venv
source .venv/bin/activate
uv pip install --python .venv/bin/python -e .
```

For Gmail support:

```bash
uv pip install --python .venv/bin/python -e ".[gmail]"
```

Gmail setup requires a local OAuth Desktop client JSON at:

```text
secrets/gmail-client-secret.json
```

Use the first-time setup PDF in `docs/` before running the Gmail test.

MailAssist currently requests Gmail permissions for:

- reading message metadata/snippets for triage
- creating Gmail drafts for replies

It still does not send email.

## Run The Desktop App

```bash
./.venv/bin/mailassist desktop-gui
```

The desktop app is being redesigned as a compact bot control panel. The current code still includes the earlier review prototype while the simplified direction is implemented.

## Bot Commands

Check local queue status:

```bash
./.venv/bin/mailassist review-bot --action queue-status
```

Process mock input into a draft-processing artifact:

```bash
./.venv/bin/mailassist review-bot --action process-mock-inbox --thread-id thread-008
```

Create one Gmail draft from one mock email after Gmail setup is complete:

```bash
./.venv/bin/mailassist review-bot \
  --action watch-once \
  --provider gmail \
  --thread-id thread-008 \
  --force
```

This command is intentionally narrow: it keeps mock input emails, creates one provider draft in Gmail, and should not send mail. Re-running with `--force` can create duplicate drafts.

Preview the latest 10 Gmail inbox messages without creating drafts:

```bash
./.venv/bin/mailassist review-bot --action gmail-inbox-preview --limit 10
```

Older local draft command, still useful for testing:

```bash
./.venv/bin/mailassist draft-thread --thread-file data/threads/sample-thread.json
```

## Runtime Data

Runtime files live under `data/` and should generally stay out of git:

- `data/logs/`
- `data/bot-logs/`
- `data/drafts/`
- `data/bot_processed/`
- `data/gui_acquired/`
- `data/user_reviewed/`
- `data/provider_drafted/`
- `data/user_replied/`

Only sanitized examples and empty placeholders should be committed.

## Project Shorthand

`rscp` means: refresh docs, summarize the current conversation to `SUMMARY.md`, commit, and push.
