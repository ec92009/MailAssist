# TODO

This backlog is ordered around the north-star user: Magali, a CPA in San Diego who runs her own business, uses Windows, and gets business email in Outlook Desktop.

Mac/Gmail remains the proving ground because it is already working locally and exercises the drafting loop. Windows/Outlook is the more important destination.

## P0: Understand Magali's Outlook Setup

- Find out what kind of account Magali's Outlook Desktop uses: Microsoft 365/Exchange, Outlook.com, IMAP/SMTP, Gmail/Google Workspace inside Outlook, or another provider.
- Confirm whether her company tenant allows third-party Microsoft Graph apps.
- Confirm whether she has admin rights or needs tenant-admin consent.
- Identify the least painful auth path for her actual account type.
- Decide whether Microsoft Graph, local Outlook automation, IMAP/SMTP, or another route is the right first Outlook provider.

## P1: Windows/Outlook First Useful Version

- Implement the chosen Outlook provider path.
- Keep MailAssist as a draft creator only; never add send automation.
- Create provider-native Outlook drafts that preserve recipients, subject, and reply/thread context.
- Derive the user's Outlook/account email before watching/drafting.
- Import or suggest the user's Outlook signature if the chosen provider path exposes it.
- Build a one-click `Connect Outlook` flow that avoids developer consoles or API credential handling for Magali.
- Package a Windows desktop build that Magali can install without developer tools.
- Keep setup, logs, and status readable enough for remote Dad-support.

## P2: Live Watcher Core

- Make the background bot independent of `gui.server`; shared bot/core modules should own classification, prompt building, and fixture access.
- Choose one durable live-bot state store for provider cursors, processed message IDs, classifications, draft IDs, and recent activity.
- Add provider inbox/thread polling.
- Track already-seen provider threads/messages.
- Classify new threads.
- Skip `automated`, `spam`, and `no_response`.
- Draft only for `urgent` and `reply_needed`.
- Avoid duplicate drafts for the same latest provider message.
- Detect whether a user already replied manually.
- Keep live processing optimized for first-draft latency, usually one actionable email at a time.
- Use `--batch-size` only for backlog catch-up, imports, or first-install processing.
- Emit JSONL activity events for skipped, drafted, failed, and retry states.
- Show skipped counts, recent drafts, latest acquisition pass, and failures in the GUI.

## P3: Product Safety And Trust

- Keep post-generation safety checks for signature-only and promise-shaped replies.
- Keep destructive or provider-writing actions explicit about what will happen.
- Put live provider test actions behind confirmation or a developer/debug section.
- Keep generated runtime artifacts, logs, drafts, queue files, and provider tokens ignored by git.
- Keep only sanitized samples in git.
- Avoid committing real email/order/account artifacts used during local testing.

## P4: GUI Polish For The Control Panel

- Make the desktop app copy honest about being a bot control panel, not an email review inbox.
- Show bot running/paused state.
- Give bot running/idle/error states visible color or status treatment, not plain text only.
- Show selected provider and connection status.
- Show Ollama model and health.
- Show preferred tone and signature status.
- Keep logs in a separate inspectable window.
- Keep the setup wizard compact, stable in window size, and first-run friendly.
- Keep bottom navigation controls in stable locations across wizard pages.
- Size the main window from available screen geometry instead of a hard-coded large default.
- Keep Ollama wait states honest and non-blocking; avoid fake exact progress when the model is only waiting or streaming text.
- Avoid explanatory subtitles and empty panels.

## P5: Mac/Gmail Sandbox

- Keep the mock-to-Gmail draft test available for regression checks.
- Keep the read-only latest-10 Gmail preview available for ingestion checks.
- Keep Gmail OAuth credentials under ignored local paths.
- Keep the development Gmail OAuth-client path available for local testing, but hide it behind advanced/developer settings.
- Add real-user Gmail OAuth verification only if it becomes necessary for broader testing or teaches something reusable.
- Keep Mac/Gmail `.dmg` builds as optional sandbox artifacts, not the main product goal.

## P6: Architecture Cleanup

- Relegate `review-inbox.json`, queue phase directories, and old draft storage away from the main product path.
- Retire the old two-candidate review flow from the main product path; provider drafts are now the review surface.
- Remove or quarantine legacy review-table helper code once the compact control panel is stable.
- Remove dead desktop review methods/widgets once the control-panel direction is fully confirmed.
- Decide whether to retire the web review GUI or keep it only as a developer/debug surface.
- Decide whether to keep `bot_queue.py` as a useful scaffold or replace it with a simpler state store.
- Consider an LLM client protocol only when adding a second backend beyond Ollama.

## P7: Packaging And Distribution

- Keep `dist/` ignored; do not commit generated app/package artifacts.
- Publish test builds through GitHub Releases when useful.
- Keep README download links synchronized with the current visible version.
- Add Windows signing/installer research before handing a build to Magali.
- Keep Mac signing/notarization as a later concern unless Mac/Gmail gets broader use.
