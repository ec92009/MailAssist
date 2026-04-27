# Results

## Current Direction

MailAssist is a background draft creator.

The bot watches provider inboxes, uses a local Ollama model to classify new threads, creates one provider-native draft when a reply is needed, and otherwise stays quiet. Gmail/mock work today and remain useful as the sandbox. The north-star destination is Windows/Outlook for Magali, a CPA/business owner who uses Outlook Desktop for company email. The GUI configures and supervises the bot; it is not a second inbox or a draft editor.

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
- The old web review GUI and `serve-config` path have been removed.
- Settings are first-run friendly and collapse after completion.
- Settings include provider choice, Ollama model, preferred tone, signature, and advanced file/path fields.
- The model picker shows local model size and local modified/downloaded age when Ollama provides that metadata.
- The model picker preserves the user's selected model when the list refreshes after a small test prompt.
- The setup wizard now checks available RAM and recommends installed local models that fit the current memory budget, with a clear warning when none look small enough.
- RAM guidance now distinguishes currently free RAM from the effective model budget when Ollama already has a loaded model in memory.
- The settings schema now includes the first RTF-signature, watcher-filter, and attribution fields for the next GUI polish slice.
- Email threads now carry an `unread` flag, defaulting to true for existing mock and fixture paths.
- The logs view has a human-readable summary/timeline view and a raw JSONL fallback.
- The bot has JSONL stdout/log event reporting.
- The bot has `watch-once` and Gmail preview/test paths.
- The bot now has a polling `watch-loop` path that uses `MAILASSIST_BOT_POLL_SECONDS`.
- The bot has a simplified `watch-once` pass that classifies mock threads, skips non-response mail, and creates one provider draft per actionable thread.
- The provider layer now has a first Gmail inbox/thread polling contract that maps Gmail API threads into `EmailThread` objects for the live watcher.
- Live watcher state now lives in `data/live-state.json` with migration from the older `data/bot-state.json` path.
- Live watcher state now keeps provider-scoped thread records, a provider account-email map, and recent activity summaries in one file.
- The live watcher now persists a discovered provider account email when the provider exposes one and uses it for reply-recipient selection and quoted review context.
- The live watcher now marks threads as `user_replied` when the latest visible message is already from the user account, instead of drafting again.
- The bot can run controlled Gmail draft tests from sanitized mock input, and the desktop app now confirms before creating one live Gmail draft.
- `watch-once` supports `--batch-size`; batch 5 and batch 10 have both been tested with Gmail draft creation.
- Gmail draft records carry recipient headers so provider drafts can include `To`, `Cc`, and `Bcc`.
- Legacy review-state and local draft/log artifacts now live under `data/legacy/` instead of the main runtime path.
- Shared drafting/review-state helpers now live in `mailassist.review_state` instead of a web-server module.
- The dead legacy local draft pipeline (`draft-thread`, `list-drafts`, `list-logs`, `core/orchestrator.py`, `storage/filesystem.py`, `ExecutionLog`) has been removed.
- `review_state.py` no longer migrates files on every path lookup, saves atomically, and takes signatures explicitly in low-level generation helpers.
- The desktop app sizes from available screen space instead of a fixed large default.
- Generated runtime artifacts are ignored by git.
- Gmail setup PDFs exist under `docs/`.
- Mac/Gmail packaging exists under `packaging/macos/`.
- The release builder creates `MailAssist.app`, a release folder, and `MailAssist-vX.Y-mac-gmail.dmg`.
- The packaged app stores runtime data under `~/Library/Application Support/MailAssist/`.
- The README now points GitHub users to the `.dmg` through GitHub Releases.
- `NORTH_STAR.md` now captures the Magali/Windows/Outlook product compass.
- Magali's screenshots show her main Outlook Desktop business mailbox is Microsoft 365; an Outlook.com account is also present, but the business mailbox is the north-star account.

## Recent Verified Experiments

- `gemma4:31b` was downloaded and works locally.
- Before `think: false`, `gemma4:31b` timed out at 120 seconds in the MailAssist path and exposed thinking text in direct tests.
- After `think: false`, `gemma4:31b` created single Gmail drafts in roughly 14-20 seconds.
- Batch-size 5 processed 11 actionable mock emails plus 2 skipped automated emails in about 151 seconds end to end.
- Batch-size 10 processed the same 11 actionable mock emails plus 2 skipped automated emails in about 150 seconds end to end.
- The batching result is acceptable for backlog catch-up, but live mode should not wait for a batch because first-draft latency matters more than average throughput.
- The Apple order email confirms the local test machine is a 16-inch MacBook Pro with M1 Max, 10-core CPU, 24-core GPU, 32GB unified memory, and 2TB SSD.
- Full local test suite passed with 84 tests on April 27, 2026.
- Real Gmail read-only probing on April 27, 2026 succeeded after installing optional Gmail dependencies into the local virtualenv: latest-message preview worked, candidate-thread extraction returned 25 threads/25 messages with no missing ids/senders/dates/body text, and actionable-thread extraction returned 25 threads with no empty message bodies.
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
- Mac/Gmail `.app` and `.dmg` packaging as a sandbox artifact.
- Sanitized mock email data for testing.
- Versioning SOP and environment SOP.

## New Priority

- Treat Microsoft Graph as the first Outlook provider candidate because Magali's business mailbox is Microsoft 365.
- Confirm whether Magali can authorize the app herself or needs tenant-admin consent.
- Move Windows/Outlook research and implementation earlier than real-user Gmail OAuth verification or Mac notarization.
- Keep Gmail support useful for local testing and Dad's personal workflow, but do not let it define the whole product shape.
- Treat Mac/Gmail packaging as optional sandbox distribution unless it gets broader use.

## Pieces To Simplify Or Retire

- Two candidate drafts per email.
- GUI draft editor as a central workflow.
- `Use this` / `Ignore` as the main product loop.
- Large inbox review table as the default UI.
- Five-folder lifecycle as the primary architecture.
- Detailed local review state as the source of truth.

These were useful experiments, but the lighter product should not build on them as core assumptions.

## Latest Verified State

- Latest visible version: `v58.6`.
- Latest test run: 89 passing tests.
- Current visible GUI surface is the compact bot control panel and setup wizard.
- Gmail optional dependencies are installed in the local virtualenv.
- Local Gmail setup has been proven for draft creation and readonly inbox preview.
- Mac/Gmail DMG artifact was published as a GitHub release asset.
- The next implementation phase should clean up shared bot architecture while waiting for Magali's Outlook account-type details.
- The latest cleanup slices moved old review/runtime artifacts into a legacy subtree, removed the unused queue-phase lifecycle, deleted the old web review GUI path, removed the dead legacy local draft pipeline, and introduced a dedicated live-state store for watcher runtime data.
- The latest live-watcher slice added watcher filters, provider thread-listing hooks, Gmail thread polling helpers, and background-bot integration for real provider thread sources.
- Gmail actionable-thread listing now passes unread/time-window filters into Gmail search where available, while the watcher still uses broad candidate listing so it can emit `filtered_out` activity events.
- Magali Outlook discovery is now partially resolved: Microsoft 365 first, with tenant/admin consent as the remaining provider-path question.

## Conclusion

The product remains clear: the bot exists to hide local LLM latency. The GUI exists to configure and supervise the bot. The mail provider is where users review, edit, and send drafts. MailAssist creates drafts only; it does not send email.
