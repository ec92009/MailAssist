# Summary

This conversation turned MailAssist into a much more concrete native desktop review product. The repo still keeps its local-first bot/orchestrator shape, but the center of gravity is now the `PySide6` GUI rather than the earlier browser-served workflow.

## Product and workflow decisions

- The user wants the bot and GUI to communicate cleanly: the GUI starts the bot with CLI arguments, the bot emits stdout events and writes JSONL logs the GUI can inspect.
- The long-term email lifecycle is now framed as a folder handoff model:
  `bot_processed` -> `gui_acquired` -> `user_reviewed` -> `provider_drafted` -> `user_replied`.
- That lifecycle is not implemented yet; today the app still uses `data/review-inbox.json` as the shared review-state file.
- “Green lit” / “red lit” language was intentionally retired in favor of more literal UI actions and states.
- The detail workflow settled on explicit `Use this`, `Ignore`, and `Close` actions.
- “Come back later” means simply closing the detail view without changing workflow state.
- Ignored and user-replied items should be efficient to archive, but items that still need action should not be auto-checked.
- `user_replied` became the preferred name over plain `replied`.

## Desktop GUI changes made in this conversation

- The native Python GUI is now the real review surface; the old local server path was intentionally deprioritized.
- The inbox became a scrollable, Excel-style table with checkbox, subject, classification, received date, and sender columns.
- The queue gained clearer row striping, denser spacing, larger checkboxes, sortable columns, and more mock messages for testing.
- The detail area now uses a movable splitter so the inbox and review pane can be resized.
- Automated / no-response / spam threads no longer show reply controls that do not apply.
- Candidate labels now reflect their actual tones instead of `Option A` / `Option B`.
  Current tones are `Direct and executive` and `Warm and collaborative`.
- Candidate actions were repeatedly refined:
  first grouped below the editor,
  then moved into a vertical stack,
  then moved outside the candidate frame into a shared action rail with minimum button sizes.
- Settings moved into a modal dialog opened by a gear button.
- Bot logs moved out of the main window into a dedicated logs window.
- Signature capture moved into its own settings tab.
- Ollama model choice was simplified to a dropdown-only picker backed by detected local models.
- When the user clicks `Use this`, the corresponding inbox row now becomes checked.

## Prompting and LLM behavior changes

- Prompting was changed so the local model can produce both draft tones in one prompt for the main generation path.
- Separator parsing was standardized for consistent candidate splitting.
- The GUI “regenerate alternate” path was changed to call Ollama directly, without routing through the bot subprocess.
- The regenerate prompt was simplified to request only a replacement body, which is better suited to live streaming into the editor.
- The exact user signature is now injected into the prompts so placeholders like `[Your Name]` are discouraged.

## Streaming and responsiveness work

- The GUI-side Ollama regenerate flow was moved onto a background worker to avoid beachballing the whole app.
- The app now warns the user that a regenerate may take 1-2 minutes.
- A banner and progress bar were added, then overlaid into a shared strip to save vertical space.
- Streaming was improved in several iterations:
  Ollama streaming support in the client,
  body-only prompt output,
  smaller HTTP reads,
  worker-side partial emissions,
  and finally editor-side append-by-delta updates rather than full-text replacement.
- The latest live-streaming change is version `v55.19`.

## Mock data and current examples

- The mock inbox was expanded beyond the original three threads.
- Added examples include:
  `Contract redlines before tomorrow`,
  `Team lunch headcount`,
  `Security awareness training reminder`,
  `Customer quote follow-up`,
  and `Action needed: approve vendor access`.
- The user asked to see original mock messages beside classifications and candidate replies, and to inspect the exact prompt used for a sample thread; that prompt is now easy to trace in the repo.

## Versioning and release cadence

- The user repeatedly asked that visible version bumps follow the repo SOP.
- Versioning was advanced across many user-visible GUI refinements during this conversation.
- The latest visible build at the end of this summary is `v55.19`.

## Current codebase status

- Shared settings now include a user signature.
- The desktop GUI, review-state helpers, prompt builders, and Ollama client were all updated substantially.
- `tests/test_review_state.py` was added.
- The targeted test suite passes.

## What still remains after this conversation

- Implement the folder-based lifecycle instead of the single shared `review-inbox.json` file.
- Validate Gmail end-to-end with real credentials.
- Preserve richer provider metadata when creating upstream drafts.
- Confirm live chunk-by-chunk streaming behavior across the actual Ollama models the user will use most.

Project workflow shorthand:

- `rscp` means: refresh docs, summarize the current conversation to `SUMMARY.md`, commit, and push.
