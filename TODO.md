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
- Keep live processing optimized for first-draft latency, usually one actionable email at a time.
- Use `--batch-size` for backlog catch-up, imports, or first-install processing, not as a reason to wait for more mail.
- Add per-batch timing events if batching remains useful for diagnostics.
- Keep post-generation safety checks for signature-only and promise-shaped replies.

## Gmail

- Keep Gmail OAuth credentials under ignored `secrets/`.
- Keep the mock-to-Gmail draft test available for regression checks.
- Keep the read-only latest-10 inbox preview available for Gmail ingestion checks.
- Add read-only classification for the latest Gmail inbox preview before any real-email drafting.
- Add Gmail inbox/thread polling.
- Preserve recipients, cc/bcc, subject, and reply threading metadata.
- Create drafts in the correct thread.
- Detect whether a user already replied manually.
- Avoid duplicate drafts for the same latest provider message.
- Keep real Gmail draft creation behind controlled tests until read-only classification looks trustworthy.

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
- Keep Gmail receipt/order lookups out of committed artifacts; they were used only to confirm local hardware performance context.
