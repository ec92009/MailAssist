# Results

## Current Direction

MailAssist is a background draft creator.

The bot should continuously watch Gmail, Outlook, or mock input; use the local LLM to classify new threads; create one provider-native draft when a reply is needed; and otherwise stay quiet. The GUI should configure the bot and show status/logs, not act as a second inbox or draft editor.

## Current Implementation

- Python package and CLI scaffold are in place.
- Ollama integration exists through a local HTTP client.
- Ollama generation requests now pass `think: false`.
- The Ollama generation timeout is 300 seconds for slower local models.
- Gmail draft creation exists as an optional provider path.
- Outlook remains a stub.
- A native `PySide6` desktop app exists.
- The current desktop app still contains some earlier review-table prototype code, but the visible direction is a compact control panel.
- The bot has JSONL stdout/log event reporting.
- The bot has a first queue experiment with `process-mock-inbox` and `queue-status`.
- The bot has a simplified `watch-once` pass that classifies mock threads, skips non-response mail, and creates one provider draft per actionable thread.
- The bot can run controlled Gmail draft tests from sanitized mock input.
- `watch-once` supports `--batch-size`; batch 5 and batch 10 have both been tested with Gmail draft creation.
- Gmail draft records carry recipient headers so provider drafts can include `To`, `Cc`, and `Bcc`.
- Gmail provider can preview recent inbox message metadata/snippets using read-only access.
- Settings include preferred tone and poll interval beside the user signature.
- Runtime queue folders exist with `.gitkeep` placeholders.
- Generated runtime artifacts are ignored by git.
- Gmail setup PDFs exist under `docs/`.

## Recent Verified Experiments

- `gemma4:31b` was downloaded and works locally.
- Before `think: false`, `gemma4:31b` timed out at 120 seconds in the MailAssist path and exposed thinking text in direct tests.
- After `think: false`, `gemma4:31b` created single Gmail drafts in roughly 14-20 seconds.
- Batch-size 5 processed 11 actionable mock emails plus 2 skipped automated emails in about 151 seconds end to end.
- Batch-size 10 processed the same 11 actionable mock emails plus 2 skipped automated emails in about 150 seconds end to end.
- The batching result is acceptable for backlog catch-up, but live mode should not wait for a batch because first-draft latency matters more than average throughput.
- The Apple order email confirms the local test machine is a 16-inch MacBook Pro with M1 Max, 10-core CPU, 24-core GPU, 32GB unified memory, and 2TB SSD.

## Draft Quality Findings

- The model initially invented commitments such as calling the utility company.
- The model also invented a generic `team` in an open-house decision draft.
- Prompts now explicitly ban invented teams, reviewers, internal processes, availability, and promise-shaped user commitments.
- Drafts now include recent incoming review context so Gmail recipients can see what the generated reply is responding to.
- The bot post-checks generated bodies and replaces signature-only or promise-shaped responses with a conservative acknowledgement.

## Working Pieces To Keep

- Local-first execution.
- Explicit provider draft creation rather than send automation.
- Ollama model discovery.
- User signature setting.
- Bot stdout/log events.
- Separate logs window.
- Native desktop app entrypoint.
- Sanitized mock email data for testing.
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

- Latest visible version: `v56.10`.
- Latest test run: 51 passing tests.
- Current code still contains legacy review helpers, but the visible GUI surface is now the compact bot control panel.
- Gmail optional dependencies are installed in the local virtualenv.
- Local Gmail setup has been proven for draft creation and readonly inbox preview.
- The next code phase should add read-only classification for real Gmail previews, then add real Gmail polling/drafting only after classification output looks trustworthy.

## Conclusion

The product remains clear: the bot exists to hide local LLM latency. The GUI exists to configure and supervise the bot. The mail provider is where users review, edit, and send drafts.
