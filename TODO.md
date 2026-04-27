# TODO

This backlog is ordered around the north-star user: Magali, a CPA in San Diego who runs her own business, uses Windows, and gets business email in Outlook Desktop.

Mac/Gmail remains the proving ground because it is already working locally and exercises the drafting loop. Windows/Outlook is the more important destination, but Outlook provider choices are blocked until Magali's account details are known.

## Handoff

- Quick start for next operator or machine:
  ```bash
  work in ~/Dev/MailAssist, synchronize with Github ec92009/MailAssist, catch up; open TODO.md and execute the handoff instructions
  ```
- Operator checklist for a new machine:
  - Repository: `/Users/ecohen/Dev/MailAssist`
  - Origin: `git@github.com:ec92009/MailAssist.git`
  - Branch policy: work on `main` unless explicitly told otherwise.
  - Sync steps:
    - `cd /Users/ecohen/Dev/MailAssist`
    - `git checkout main`
    - `git pull origin main`
    - `uv sync`
    - `sed -n '1,220p' TODO.md`
    - `sed -n '1,180p' SUMMARY.md`
- Current baseline at handoff:
  - Last synchronized commit: latest pushed `origin/main` commit containing this handoff block.
  - Current visible version: `v58.0`
  - Local app/dev entrypoint: `./.venv/bin/mailassist desktop`
  - Packaged app path: no current packaged app handoff; Mac/Gmail DMG remains a sandbox artifact.
- Known open issue to continue:
  - Highest unblocked implementation work is P1 live watcher MVP, starting with Gmail provider inbox/thread polling on top of the existing provider-scoped live-state store.
  - Immediate next implementation step: read `RESEARCH.md`, `RESULTS.md`, `src/mailassist/background_bot.py`, `src/mailassist/providers/gmail.py`, and `src/mailassist/live_state.py`; then add the first Gmail thread polling contract and tests.
- Handoff protocol for this repo:
  - Run `prepare for handoff` before switching machines or ending a work block that should resume elsewhere.
  - Keep `SUMMARY.md` and this `Handoff` block current.
  - Commit and push to `main` before reporting handoff ready.

## Recently Completed

- Added a dedicated live watcher state store at `data/live-state.json` with migration from the older `data/bot-state.json` path. (Managed by Codex)
- Persisted provider account email discovery for the live watcher and used it for reply recipients and quoted review context. (Managed by Codex)
- Added manual `user_replied` detection when the latest visible message is already from the user account. (Managed by Codex)
- Added a polling `watch-loop` bot action that uses `MAILASSIST_BOT_POLL_SECONDS` and emits failed/retry JSONL events. (Managed by Codex)
- Consolidated provider thread runtime state under provider-scoped slots with room for future provider cursors. (Managed by Codex)
- Added onboarding RAM checks and installed-model recommendations, including a clear warning when no installed model looks small enough. (Managed by Codex)
- Added initial RTF/filter/attribution settings fields and `EmailThread.unread` for the GUI polish slice. (Managed by Codex)

## P0: Magali Outlook Discovery (Waiting on Magali) (Managed by Codex)

- Find out what kind of account Magali's Outlook Desktop uses: Microsoft 365/Exchange, Outlook.com, IMAP/SMTP, Gmail/Google Workspace inside Outlook, or another provider. (Managed by Codex) (Waiting on Magali)
- Confirm whether her company tenant allows third-party Microsoft Graph apps. (Managed by Codex) (Waiting on Magali)
- Confirm whether she has admin rights or needs tenant-admin consent. (Managed by Codex) (Waiting on Magali)
- Identify the least painful auth path for her actual account type. (Managed by Codex) (Waiting on Magali)
- Decide whether Microsoft Graph, local Outlook automation, IMAP/SMTP, or another route is the right first Outlook provider. (Managed by Codex) (Waiting on Magali)

## P1: Unblocked Live Watcher MVP (Managed by Codex)

- Add provider inbox/thread polling, starting with Gmail because it is already connected locally. (Managed by Codex)
- Track already-seen provider threads/messages using the provider-scoped live-state slots. (Managed by Codex)
- Classify new threads. (Managed by Codex)
- Skip `automated`, `spam`, and `no_response`. (Managed by Codex)
- Draft only for `urgent` and `reply_needed`. (Managed by Codex)
- Avoid duplicate drafts for the same latest provider message. (Managed by Codex)
- Detect whether a user already replied manually. (Managed by Codex)
- Keep live processing optimized for first-draft latency, usually one actionable email at a time. (Managed by Codex)
- Use `--batch-size` only for backlog catch-up, imports, or first-install processing. (Managed by Codex)
- Emit JSONL activity events for skipped, drafted, failed, retry, and filtered-out states. (Managed by Codex)
- Show skipped counts, recent drafts, latest acquisition pass, and failures in the GUI. (Managed by Codex)
- Decide whether real continuous polling should become the default or remain an explicit user-started bot action. (Managed by Codex)

## P2: Current GUI And Draft Polish Slice (Managed by Codex)

- Finish `DraftRecord.body_html` so providers can receive both plain and HTML draft bodies. (Managed by Codex)
- Add signature HTML sanitizing and plain-text extraction helpers. (Managed by Codex)
- Wire Gmail signature import through the shared sanitizer. (Managed by Codex)
- Create Gmail multipart drafts when `body_html` is present. (Managed by Codex)
- Add watcher filters for unread-only and time window, then honor them before classification. (Managed by Codex)
- Persist watcher filter controls in the setup wizard. (Managed by Codex)
- Show the active watcher filter on the dashboard. (Managed by Codex)
- Offer RTF formatting for signatures. (Managed by Codex)
- Offer optional draft attribution such as MailAssist, Ollama, and model name. (Managed by Codex)
- Show preferred tone and signature status. (Managed by Codex)

## P3: Product Safety And Trust (Managed by Codex)

- Keep post-generation safety checks for signature-only and promise-shaped replies. (Managed by Codex)
- Keep destructive or provider-writing actions explicit about what will happen. (Managed by Codex)
- Put live provider test actions behind confirmation or a developer/debug section. (Managed by Codex)
- Keep generated runtime artifacts, logs, drafts, queue files, and provider tokens ignored by git. (Managed by Codex)
- Keep only sanitized samples in git. (Managed by Codex)
- Avoid committing real email/order/account artifacts used during local testing. (Managed by Codex)

## P4: Windows/Outlook First Useful Version (Waiting on Magali) (Managed by Codex)

- Implement the chosen Outlook provider path. (Managed by Codex) (Waiting on Magali)
- Keep MailAssist as a draft creator only; never add send automation. (Managed by Codex)
- Create provider-native Outlook drafts that preserve recipients, subject, and reply/thread context. (Managed by Codex) (Waiting on Magali)
- Derive the user's Outlook/account email before watching/drafting. (Managed by Codex) (Waiting on Magali)
- Import or suggest the user's Outlook signature if the chosen provider path exposes it. (Managed by Codex) (Waiting on Magali)
- Build a one-click `Connect Outlook` flow that avoids developer consoles or API credential handling for Magali. (Managed by Codex) (Waiting on Magali)
- Package a Windows desktop build that Magali can install without developer tools. (Managed by Codex) (Waiting on Magali)
- Keep setup, logs, and status readable enough for remote Dad-support. (Managed by Codex)

## P5: Control Panel Cleanup (Managed by Codex)

- Make the desktop app copy honest about being a bot control panel, not an email review inbox. (Managed by Codex)
- Show bot running/paused state. (Managed by Codex)
- Give bot running/idle/error states visible color or status treatment, not plain text only. (Managed by Codex)
- Show selected provider and connection status. (Managed by Codex)
- Show Ollama model and health. (Managed by Codex)
- Keep logs in a separate inspectable window. (Managed by Codex)
- Keep the setup wizard compact, stable in window size, and first-run friendly. (Managed by Codex)
- Keep bottom navigation controls in stable locations across wizard pages. (Managed by Codex)
- Keep Ollama wait states honest and non-blocking; avoid fake exact progress when the model is only waiting or streaming text. (Managed by Codex)
- Avoid explanatory subtitles and empty panels. (Managed by Codex)

## P6: Mac/Gmail Sandbox (Managed by Codex)

- Keep the mock-to-Gmail draft test available for regression checks. (Managed by Codex)
- Keep the read-only latest-10 Gmail preview available for ingestion checks. (Managed by Codex)
- Keep Gmail OAuth credentials under ignored local paths. (Managed by Codex)
- Keep the development Gmail OAuth-client path available for local testing, but hide it behind advanced/developer settings. (Managed by Codex)
- Add real-user Gmail OAuth verification only if it becomes necessary for broader testing or teaches something reusable. (Managed by Codex)
- Keep Mac/Gmail `.dmg` builds as optional sandbox artifacts, not the main product goal. (Managed by Codex)

## P7: Architecture Cleanup (Managed by Codex)

- Relegate `review-inbox.json`, queue phase directories, and old draft storage away from the main product path. (Managed by Codex)
- Retire the old two-candidate review flow from the main product path; provider drafts are now the review surface. (Managed by Codex)
- Collapse the remaining split between `bot-state.json` and `review-inbox.json` into one durable live-bot state store. (Managed by Codex)
- Remove or quarantine legacy review-table helper code once the compact control panel is stable. (Managed by Codex)
- Remove dead desktop review methods/widgets once the control-panel direction is fully confirmed. (Managed by Codex)
- Split or shrink `review_state.py`; move persistence/schema concerns away from prompt-generation helpers. (Managed by Codex)
- Decide whether `review_state.py` should become a small legacy-only module or be merged into the single live-bot state store. (Managed by Codex)
- Remove the last placeholder `you@example.com` assumptions from review-context and reply-recipient helpers once the account-email source exists. (Managed by Codex)
- Consider an LLM client protocol only when adding a second backend beyond Ollama. (Managed by Codex)

## P8: Packaging And Distribution (Managed by Codex)

- Keep `dist/` ignored; do not commit generated app/package artifacts. (Managed by Codex)
- Publish test builds through GitHub Releases when useful. (Managed by Codex)
- Keep README download links synchronized with the current visible version. (Managed by Codex)
- Add Windows signing/installer research before handing a build to Magali. (Managed by Codex)
- Keep Mac signing/notarization as a later concern unless Mac/Gmail gets broader use. (Managed by Codex)
