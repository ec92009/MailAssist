# Results

## Current Direction

MailAssist is a background draft creator.

The bot watches Gmail or mock input, uses a local Ollama model to classify new threads, creates one provider-native Gmail draft when a reply is needed, and otherwise stays quiet. Outlook is planned after the Mac/Gmail loop is stable. The GUI configures and supervises the bot; it is not a second inbox or a draft editor.

## Current Implementation

- Python package and CLI scaffold are in place.
- Ollama integration exists through a local HTTP client.
- Ollama generation requests pass `think: false`.
- The Ollama generation timeout is 300 seconds for slower local models.
- Gmail draft creation exists as an optional provider path.
- Gmail provider can preview recent inbox message metadata/snippets using read-only access.
- Gmail provider can retrieve the account send-as signature as a starting point for MailAssist settings.
- Outlook remains a stub.
- A native `PySide6` desktop app exists.
- The visible desktop app is now a compact control panel with a setup wizard, bot controls, readable logs, and recent activity.
- Settings are first-run friendly and collapse after completion.
- Settings include provider choice, Ollama model, preferred tone, signature, advanced paths, and poll interval.
- The model picker shows local model size and local modified/downloaded age when Ollama provides that metadata.
- The logs view has a human-readable summary/timeline view and a raw JSONL fallback.
- The bot has JSONL stdout/log event reporting.
- The bot has `process-mock-inbox`, `queue-status`, `watch-once`, and Gmail preview/test paths.
- The bot has a simplified `watch-once` pass that classifies mock threads, skips non-response mail, and creates one provider draft per actionable thread.
- The bot can run controlled Gmail draft tests from sanitized mock input.
- `watch-once` supports `--batch-size`; batch 5 and batch 10 have both been tested with Gmail draft creation.
- Gmail draft records carry recipient headers so provider drafts can include `To`, `Cc`, and `Bcc`.
- Runtime queue folders exist with `.gitkeep` placeholders.
- Generated runtime artifacts are ignored by git.
- Gmail setup PDFs exist under `docs/`.
- Mac/Gmail packaging exists under `packaging/macos/`.
- The release builder creates `MailAssist.app`, a release folder, and `MailAssist-vX.Y-mac-gmail.dmg`.
- The packaged app stores runtime data under `~/Library/Application Support/MailAssist/`.
- The README now points GitHub users to the `.dmg` through GitHub Releases.

## Recent Verified Experiments

- `gemma4:31b` was downloaded and works locally.
- Before `think: false`, `gemma4:31b` timed out at 120 seconds in the MailAssist path and exposed thinking text in direct tests.
- After `think: false`, `gemma4:31b` created single Gmail drafts in roughly 14-20 seconds.
- Batch-size 5 processed 11 actionable mock emails plus 2 skipped automated emails in about 151 seconds end to end.
- Batch-size 10 processed the same 11 actionable mock emails plus 2 skipped automated emails in about 150 seconds end to end.
- The batching result is acceptable for backlog catch-up, but live mode should not wait for a batch because first-draft latency matters more than average throughput.
- The Apple order email confirms the local test machine is a 16-inch MacBook Pro with M1 Max, 10-core CPU, 24-core GPU, 32GB unified memory, and 2TB SSD.
- Full local test suite passed with 61 tests on April 25, 2026.
- `dist/MailAssist-v56.46-mac-gmail.dmg` was built locally at about 253 MB, well under GitHub Releases' 2 GiB per-asset limit.

## Draft Quality Findings

- The model initially invented commitments such as calling the utility company.
- The model also invented a generic `team` in an open-house decision draft.
- Prompts now explicitly ban invented teams, reviewers, internal processes, availability, and promise-shaped user commitments.
- Drafts now include recent incoming review context so Gmail recipients can see what the generated reply is responding to.
- Review context timestamps use local, readable wording such as `yesterday afternoon at 14:09`.
- The bot post-checks generated bodies and replaces signature-only or promise-shaped responses with a conservative acknowledgement.

## Working Pieces To Keep

- Local-first execution.
- Explicit provider draft creation rather than send automation.
- Ollama model discovery.
- User signature setting, with Gmail signature import as a starting point.
- Bot stdout/log events.
- Human-readable logs window.
- Native desktop app entrypoint.
- Mac/Gmail `.app` and `.dmg` packaging.
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

- Latest visible version: `v56.46`.
- Latest test run: 61 passing tests.
- Current visible GUI surface is the compact bot control panel and setup wizard.
- Gmail optional dependencies are installed in the local virtualenv.
- Local Gmail setup has been proven for draft creation and readonly inbox preview.
- Mac/Gmail DMG artifact exists locally and is ready to upload as a GitHub release asset.
- The next implementation phase should add real Gmail polling/drafting behind the same conservative guardrails.

## Conclusion

The product remains clear: the bot exists to hide local LLM latency. The GUI exists to configure and supervise the bot. Gmail is where users review, edit, and send drafts. MailAssist creates drafts only; it does not send email.
