# Results

## Current Direction

MailAssist is being simplified into a background draft creator.

The bot should continuously watch Gmail, Outlook, or mock input; use the local LLM to classify new threads; create one provider-native draft when a reply is needed; and otherwise stay quiet. The GUI should configure the bot and show status/logs, not act as a second inbox or draft editor.

## Current Implementation

- Python package and CLI scaffold are in place.
- Ollama integration exists through a local HTTP client.
- Gmail draft creation exists as an optional provider path.
- Outlook remains a stub.
- A native `PySide6` desktop app exists.
- The current desktop app still contains the earlier review-table prototype.
- The bot has JSONL stdout/log event reporting.
- The bot has a first queue experiment with `process-mock-inbox` and `queue-status`.
- Runtime queue folders exist with `.gitkeep` placeholders.
- Generated runtime artifacts are ignored by git.

## Working Pieces To Keep

- Local-first execution.
- Explicit provider draft creation rather than send automation.
- Ollama model discovery.
- User signature setting.
- Bot stdout/log events.
- Separate logs window.
- Native desktop app entrypoint.
- Mock email data for testing.
- Versioning SOP and environment SOP.

## Pieces To Simplify Or Retire

- Two candidate drafts per email.
- GUI draft editor as a central workflow.
- `Use this` / `Ignore` as the main product loop.
- Large inbox review table as the default UI.
- Five-folder lifecycle as the primary architecture.
- Detailed local review state as the source of truth.

These were useful experiments, but the lighter product should not build on them as core assumptions.

## Latest Verified State

- Latest visible version before this planning reset: `v55.33`.
- Latest test run before this rewrite: 32 passing tests.
- Current code still includes the review prototype and the queue scaffold.
- The next code phase should intentionally reshape the app, not incrementally patch the old review workflow.

## Conclusion

The product has become clearer: the bot exists to hide local LLM latency. The GUI exists to configure and supervise the bot. The mail provider is where users review, edit, and send drafts.
