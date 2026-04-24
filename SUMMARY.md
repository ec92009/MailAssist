# Summary

MailAssist is now a native desktop review app with a bot queue beginning to take shape behind it. The current product direction is local-first: the bot acquires and annotates email-like work items, the GUI lets the user review and decide, and provider writes stay explicit and draft-oriented.

## Product Shape

- The native `PySide6` desktop app is the primary review surface.
- The old browser-served UI is no longer the main path.
- The user-facing review actions are literal: `Use this`, `Ignore`, and `Close`.
- `Close` means come back later; it does not change workflow state.
- The long-term lifecycle is folder based:
  `bot_processed` -> `gui_acquired` -> `user_reviewed` -> `provider_drafted` -> `user_replied`.
- The desktop GUI still reads `data/review-inbox.json` today, but the bot can now create and populate the first queue phase.

## Desktop GUI Progress

- The inbox is now an Excel-style sortable table with checkbox, subject, classification, received date, and sender columns.
- Row density was tightened: rows are now 30px tall and the app opens with about six visible inbox rows.
- Low-value helper text was removed from the hero area, thread header, and candidate editor to free vertical space.
- The inbox/detail split is draggable, and the initial split favors the review pane once six inbox rows are visible.
- Candidate controls live in a right-side action rail outside the `Candidate Replies` frame.
- During regeneration, the running state is specific to the email/candidate being regenerated. Other emails return to normal controls while Ollama keeps working.
- Regeneration status now clearly tells the user that Ollama can take a couple of minutes and that they can click another email and keep working.
- Settings are in a modal dialog, with separate tabs for Ollama, providers, and signature.
- Bot logs are in a separate logs window.

## Prompting And Ollama

- Main draft generation asks the local model for both tones in one prompt.
- Candidate labels now use tone names: `Direct and executive` and `Warm and collaborative`.
- GUI-side alternate regeneration talks directly to Ollama and asks only for a replacement body.
- The app has streaming plumbing, but the current local model may still flush in a single late chunk. The UI now reflects this honestly as a waiting/streaming state.
- User signature is captured in settings and injected into prompts as an exact block, avoiding placeholders like `[Your Name]`.

## Bot Queue Work

- Added `src/mailassist/bot_queue.py`.
- Added lifecycle folders with `.gitkeep` placeholders:
  `data/bot_processed`, `data/gui_acquired`, `data/user_reviewed`, `data/provider_drafted`, `data/user_replied`.
- Generated queue JSON files are ignored so runtime email artifacts are not committed.
- Added `review-bot --action queue-status`.
- Added `review-bot --action process-mock-inbox`.
- `process-mock-inbox` can process all mock threads or a single `--thread-id`.
- It writes one annotated JSON file per thread into `data/bot_processed/`, emits JSONL stdout events, and skips threads already present in any lifecycle phase unless `--force` is used.
- A smoke run created `data/bot_processed/mock__thread-008.json` locally using fallback drafts.

## Tests And Version

- Added `tests/test_bot_queue.py`.
- Expanded config tests for fallback urgent classification on action-needed/deadline messages.
- Latest verified suite: 32 passing tests.
- Latest visible version is `v55.33`.

## Next Work

- Move the desktop GUI from `data/review-inbox.json` to claiming files from `data/bot_processed/` into `data/gui_acquired/`.
- Write reviewed GUI decisions into `data/user_reviewed/`.
- Add bot processing from `user_reviewed` to provider draft creation and `provider_drafted/`.
- Preserve richer provider metadata for Gmail draft creation.
- Validate Gmail OAuth and draft threading with real credentials.

Project workflow shorthand:

- `rscp` means: refresh docs, summarize the current conversation to `SUMMARY.md`, commit, and push.
