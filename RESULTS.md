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
- The current desktop app still contains some earlier review-table prototype code, but the visible direction is a compact control panel.
- The bot has JSONL stdout/log event reporting.
- The bot has a first queue experiment with `process-mock-inbox` and `queue-status`.
- The bot now has a simplified `watch-once` mock pass that classifies mock threads, skips non-response mail, and creates one mock provider draft per actionable thread.
- The bot can now run a narrow Gmail draft test using mock input: `watch-once --provider gmail --thread-id thread-008 --force`.
- Gmail draft records now carry recipient headers so provider drafts can include `To`, `Cc`, and `Bcc`.
- The desktop app includes a Gmail test-draft button for the controlled mock-to-Gmail path.
- The desktop app now opens as a compact bot control panel rather than a review table.
- Settings now include preferred tone and poll interval beside the user signature.
- Runtime queue folders exist with `.gitkeep` placeholders.
- Generated runtime artifacts are ignored by git.
- Gmail setup PDFs exist under `docs/`.

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

- Latest visible version: `v56.0`.
- Latest test run: 37 passing tests.
- Current code still contains legacy review helpers, but the visible GUI surface is now the compact bot control panel.
- Gmail optional dependencies are installed in the local virtualenv.
- Local Gmail setup still needs `secrets/gmail-client-secret.json` and the first browser OAuth run to create `secrets/gmail-token.json`.
- The next code phase should test one real Gmail draft, then remove or quarantine legacy review code once the control-panel path is stable.

## Conclusion

The product has become clearer: the bot exists to hide local LLM latency. The GUI exists to configure and supervise the bot. The mail provider is where users review, edit, and send drafts.
