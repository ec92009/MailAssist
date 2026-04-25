# MailAssist

MailAssist is a local background email drafting assistant. It watches connected inboxes, uses a local Ollama model to decide whether a message needs a reply, and creates a draft directly in Gmail when useful.

The user reviews, edits, sends, or deletes drafts in the normal mail client. MailAssist does not send email.

## Current Product Direction

- Bot runs continuously.
- Bot watches Gmail or mock input. Outlook is planned next.
- Bot classifies new mail.
- Bot skips mail that does not need a response.
- Bot creates one provider draft for mail that needs a response.
- GUI configures and supervises the bot.
- Gmail remains the review and editing surface for the first packaged build.
- Live watching favors one-at-a-time first-draft latency; batching is for backlog catch-up.

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

## Download And Run: Mac/Gmail Preview

The first downloadable target is:

```text
macOS + Gmail + local Ollama
```

Windows and Outlook are planned after this Mac/Gmail loop is stable.

### Download From GitHub

If you are reading this on GitHub, download the latest Mac/Gmail `.dmg`:

[Download MailAssist-v56.46-mac-gmail.dmg](https://github.com/ec92009/MailAssist/releases/download/v56.46/MailAssist-v56.46-mac-gmail.dmg)

If that direct link is not available yet, open the [MailAssist Releases page](https://github.com/ec92009/MailAssist/releases) and download the latest Mac/Gmail `.dmg`.

Look for a file named like:

```text
MailAssist-vX.Y-mac-gmail.dmg
```

Open the `.dmg`, then drag `MailAssist.app` into `Applications`.

### What The User Needs

- A Mac running macOS 12 or newer.
- [Ollama](https://ollama.com) installed and running.
- At least one local model installed in Ollama. Suggested starting points:

| Mac RAM | Suggested Ollama model |
|---:|---|
| 16 GB | [`gemma3:12b`](https://ollama.com/library/gemma3) |
| 24 GB | [`gemma3:27b`](https://ollama.com/library/gemma3) |
| 32 GB | [`qwen3:30b`](https://ollama.com/library/qwen3) |
| 64 GB | [`llama3.3:70b`](https://ollama.com/library/llama3.3) |
| 128 GB | [`gpt-oss:120b`](https://ollama.com/library/gpt-oss:120b) |

These are MailAssist-oriented recommendations, not hard limits. They favor the strongest current Ollama model that still leaves practical headroom for macOS, MailAssist, and Ollama. If the Mac feels slow or starts swapping, use the model from the previous row. If you want the safest first install, start with:

```bash
ollama pull gemma3:12b
```

Sources checked: [Gemma 3 on Ollama](https://ollama.com/library/gemma3), [Qwen 3 on Ollama](https://ollama.com/library/qwen3), [Llama 3.3 on Ollama](https://ollama.com/library/llama3.3), and [gpt-oss on Ollama](https://ollama.com/library/gpt-oss:120b).

- A Gmail OAuth Desktop client JSON file. The first-time guide is:

```text
docs/setting_up_gmail_connection_for_MailAssist.pdf
```

### Install From The DMG

1. Open the MailAssist DMG.
2. Drag `MailAssist.app` to `Applications`.
3. Open `MailAssist.app`.
4. If macOS blocks the preview build because it is not notarized yet, try opening it once, then use Apple menu > `System Settings` > `Privacy & Security`. In the `Security` section, choose `Open` or `Open Anyway` for MailAssist, confirm again, and enter your Mac login password if prompted. Apple says this override is available for about an hour after the blocked open attempt.
5. Follow the setup wizard.
6. Place the Gmail client secret JSON at the path shown in settings, or use the default:

```text
~/Library/Application Support/MailAssist/secrets/gmail-client-secret.json
```

MailAssist stores local settings, Gmail tokens, logs, and runtime files under:

```text
~/Library/Application Support/MailAssist/
```

MailAssist creates Gmail drafts only. It never sends email.

### Build The Mac/Gmail Release Artifact

From the repo:

```bash
./packaging/macos/build_release.sh
```

The script produces:

```text
dist/MailAssist-vX.Y-mac-gmail.dmg
dist/MailAssist-vX.Y-mac-gmail/
```

The release folder includes:

- `MailAssist.app`
- `README_FIRST.txt`
- `setting_up_gmail_connection_for_MailAssist.pdf`
- `gmail_oauth_advanced.pdf`

This preview DMG is ad-hoc signed but not Apple-notarized yet, so macOS may require the Privacy & Security override above the first time.

Apple references:

- [Safely open apps on your Mac](https://support.apple.com/en-gw/102445)
- [Open an app by overriding security settings](https://support.apple.com/en-afri/guide/mac-help/mh40617/mac)

## Developer Setup

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

Developer Gmail setup requires a local OAuth Desktop client JSON at:

```text
secrets/gmail-client-secret.json
```

Use the first-time setup PDF in `docs/` before running the Gmail test.

MailAssist currently requests Gmail permissions for:

- reading message metadata/snippets for triage
- creating Gmail drafts for replies

It still does not send email.

## Run The Desktop App From Source

```bash
./.venv/bin/mailassist desktop-gui
```

The desktop app is now a compact bot control panel with settings, bot controls, readable logs, and recent activity.

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

Process a mock backlog in larger Ollama batches:

```bash
./.venv/bin/mailassist review-bot \
  --action watch-once \
  --provider gmail \
  --force \
  --batch-size 10 \
  --selected-model gemma4:31b
```

Use batching for backlogs or controlled tests. For live watching, prefer immediate one-at-a-time drafting so the first provider draft appears as soon as possible.

Preview the latest 10 Gmail inbox messages without creating drafts:

```bash
./.venv/bin/mailassist review-bot --action gmail-inbox-preview --limit 10
```

Older local draft command, still useful for testing:

```bash
./.venv/bin/mailassist draft-thread --thread-file data/threads/sample-thread.json
```

## Runtime Data

When running from source, runtime files live under `data/` and should generally stay out of git:

- `data/logs/`
- `data/bot-logs/`
- `data/drafts/`
- `data/bot_processed/`
- `data/gui_acquired/`
- `data/user_reviewed/`
- `data/provider_drafted/`
- `data/user_replied/`

Only sanitized examples and empty placeholders should be committed.

When running the packaged Mac app, the same runtime data lives under:

```text
~/Library/Application Support/MailAssist/data/
```

## Current Verified Baseline

- Visible version: `v56.46`.
- Test suite: 61 passing tests.
- `gemma4:31b` works locally after MailAssist sends `think: false` to Ollama.
- Controlled mock-to-Gmail draft creation has been tested with batch sizes 1, 5, and 10.
- MailAssist creates drafts only; it does not send email.

## Project Shorthand

`rscp` means: refresh docs, summarize the current conversation to `SUMMARY.md`, commit, and push.
