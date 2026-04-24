# TODO

## Product Simplification

- Remove or quarantine legacy review-table helper code once the compact control panel is stable.
- Keep refining the control panel around bot status, recent activity, settings, and logs.
- Keep one preferred tone setting near the user signature.
- Keep one generated draft per actionable email.

## Bot

- Define the bot as a continuous watcher/drafter.
- Turn the current mock `watch-once` pass into a continuous mock watch loop for development.
- Add polling interval configuration.
- Track already-seen mock/provider threads.
- Classify new threads.
- Skip `automated`, `spam`, and `no_response`.
- Draft only for `urgent` and `reply_needed`.
- Create provider-native drafts for drafted items.
- Emit JSONL activity events for skipped, drafted, failed, and retry states.

## Gmail

- Use `docs/setting_up_gmail_connection_for_MailAssist.pdf` to create the OAuth Desktop client JSON.
- Place the downloaded JSON at `secrets/gmail-client-secret.json`.
- Enable Gmail in settings or `.env`.
- Run the first narrow mock-to-Gmail draft test:
  `./.venv/bin/mailassist review-bot --action watch-once --provider gmail --thread-id thread-008 --force`.
- Confirm the first OAuth browser approval creates `secrets/gmail-token.json`.
- Confirm exactly one Gmail draft appears in Drafts and is not sent.
- Validate recipient, subject, body, and whether Gmail preserves the expected reply/thread behavior.
- Add Gmail inbox/thread polling.
- Preserve recipients, cc/bcc, subject, and reply threading metadata.
- Create drafts in the correct thread.
- Detect whether a user already replied manually.
- Avoid duplicate drafts for the same latest provider message.

## Outlook

- Implement Microsoft Graph provider support after Gmail stabilizes.
- Confirm required read and draft permissions.
- Mirror the Gmail watcher/drafter contract.

## GUI

- Show bot running/paused state.
- Show selected provider and connection status.
- Show Ollama model and health.
- Show preferred tone and signature status.
- Show latest acquisition pass.
- Show recent drafts created in provider.
- Show skipped counts by classification.
- Keep logs in a separate inspectable window.
- Avoid explanatory subtitles and empty panels.

## Cleanup

- Decide whether to remove or quarantine the old review-table prototype code.
- Decide whether to keep `bot_queue.py` as a useful scaffold or replace it with a simpler state store.
- Keep runtime logs, drafts, queue files, and provider artifacts ignored.
- Keep only sanitized samples in git.
