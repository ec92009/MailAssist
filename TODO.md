# TODO

## Product Simplification

- Redesign the desktop GUI as a compact control panel.
- Remove the review-inbox-first layout from the primary screen.
- Keep settings, bot status, recent activity, and logs.
- Add one preferred tone setting near the user signature.
- Stop generating two candidate drafts by default.

## Bot

- Define the bot as a continuous watcher/drafter.
- Add a mock watch loop for development.
- Add polling interval configuration.
- Track already-seen mock/provider threads.
- Classify new threads.
- Skip `automated`, `spam`, and `no_response`.
- Draft only for `urgent` and `reply_needed`.
- Create provider-native drafts for drafted items.
- Emit JSONL activity events for skipped, drafted, failed, and retry states.

## Gmail

- Validate OAuth with real credentials.
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
