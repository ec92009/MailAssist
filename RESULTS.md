# Results

## Current Direction

MailAssist is a background draft creator.

The bot watches provider inboxes, uses a local Ollama model to classify new threads, creates one provider-native draft when a reply is needed, and otherwise stays quiet. Gmail/mock work today and remain useful as the sandbox. The north-star destination is Windows/Outlook for Magali, a CPA/business owner who uses Outlook Desktop for company email. The GUI configures and supervises the bot; it is not a second inbox or a draft editor.

## Current Implementation

- Python package and CLI scaffold are in place.
- Ollama integration exists through a local HTTP client.
- Ollama generation requests pass `think: false`.
- The Ollama generation timeout is 300 seconds for slower local models.
- Gmail draft creation exists as a provider path, and its Google client packages are installed by the default project dependency set.
- Gmail provider can preview recent inbox message metadata/snippets using read-only access.
- Gmail provider can retrieve the account send-as signature as a starting point for MailAssist settings.
- Outlook now has a mockable Microsoft Graph provider slice for account discovery, mailbox message parsing, readiness/admin-consent reporting, category updates, and reply-draft payload mapping. It also has a real Graph client with device-code OAuth, ignored local refresh-token storage, `/me`, inbox listing, message category updates, and reply-draft creation.
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
- Rich signatures now persist both plain text and sanitized HTML.
- The signature editor now has explicit bold, italic, underline, and link controls.
- Draft records can carry `body_html`, and Gmail creates multipart `text/plain` + `text/html` drafts when HTML is present.
- Optional draft attribution can be included in both plain and HTML bodies.
- Draft attribution placement is configurable as hidden, above the saved signature, or below the saved signature, with matching plain-text and HTML assembly.
- Settings shows a read-only `Signature + Attribution` preview so placement can be checked before live drafts are created.
- The Advanced Settings check-frequency spinner height now matches neighboring text fields without shrinking those fields.
- Email threads now carry an `unread` flag, defaulting to true for existing mock and fixture paths.
- The logs view has a human-readable summary/timeline view and a raw JSONL fallback.
- The bot has JSONL stdout/log event reporting.
- The bot has `watch-once` and Gmail preview/test paths.
- The bot has an Outlook smoke-test path that checks provider readiness and inbox preview without writing drafts by default.
- The CLI has an `outlook-setup-check` path for Magali-style setup: authorize Outlook, verify the signed-in mailbox, optionally enforce an expected email, preview inbox thread subjects only, and create no drafts.
- The CLI has an `ollama-setup-check` path for Magali-style setup: list installed Ollama models, verify the configured or requested model exists, run a small prompt through MailAssist's own `think:false` Ollama client, and report response time without touching mail.
- The desktop GUI has confirmation-gated `Stop Ollama` and headless `Start Ollama` controls in the Settings local-model tab beside the small test prompt.
- `Start Ollama` quietly refreshes the installed model list after startup without overwriting the current model-test result text.
- The desktop GUI can clear the visible Recent Activity window without deleting saved bot run logs; the clear control sits beside the scrolling text to preserve vertical log space.
- Longer desktop GUI tooltips render as constrained multiline rich text instead of one wide line.
- GUI draft previews now report provider-specific completion lines, and Outlook preview is capped to a small candidate set so it remains a quick dry-run check.
- Long-running GUI preview/watch actions emit heartbeat lines in Recent Activity so the user can see MailAssist is still working and no email is being sent.
- Gmail and Outlook preview actions now share the same warning/heartbeat behavior and auto-stop after 2 minutes if the preview has not finished.
- Outlook preview diagnostics now distinguish auth failure from model work: preview errors are visible in Recent Activity, `invalid_grant` tells the user to refresh Outlook sign-in, and dry-run preview model calls use a shorter Ollama timeout.
- Dry-run Gmail and Outlook draft previews run without confirmation modals; preview heartbeats stop immediately on completion or failure.
- Recent Activity heartbeat/final summaries include progress counts for previews, watch passes, and Gmail/Outlook organizer runs.
- Recent Activity now has a local `Report` button that opens the detailed run report/log window, wraps long lines inside the visible panel, and expands terse Outlook `invalid_grant` failures into re-auth guidance.
- Recent Activity is now horizontally shrinkable and uses shorter preview/heartbeat copy so long status text cannot push the desktop window beyond the screen edge.
- Gmail and Outlook organizer runs now emit setup and per-thread classification-start progress, so the UI can explain the first minute before any category result has finished.
- Outlook organizer readiness failures now show as connection failures and explain that organization stopped before mailbox reads, rather than reporting a misleading quick zero-email completion.
- Organizer failure messages now use the same structure across Gmail and Outlook, including pre-first-category and partial-progress failure cases.
- Recent Activity progress now avoids subject-level detail: previews/watch passes show scanned/draft counts, and organizer runs show scanned/category counts, with full subject detail left to reports/logs.
- Recent Activity no longer appends per-item `Progress:` rows; heartbeat lines are the single live progress signal while counters update silently between heartbeats.
- Auto-check loop activity now distinguishes active checking from waiting between polling passes.
- Live provider draft creation now creates replies to the triggering provider thread instead of standalone new-thread drafts. Gmail reply drafts carry Gmail thread/reply metadata, Outlook drafts pass the source message id into Graph `createReply`, and live provider drafts no longer include MailAssist-inserted review-context summaries.
- Outlook reply-draft creation now lets Microsoft Graph create the native reply shell first, then patches body/recipients afterward so Outlook controls the normal reply subject and conversation shape.
- Outlook unread state is preserved after reply-draft creation by restoring the source message to unread when it was unread before Graph created the reply shell.
- Outlook reply draft body updates now preserve the native quoted original message by inserting MailAssist text above Graph's generated reply content. When the triggering message was sent to an account alias, MailAssist attempts to keep that alias as the draft sender and falls back if Graph rejects it.
- Draft prompting now explicitly mirrors the sender's language and register, including informal French `tu` when the incoming thread uses informal French.
- The small local-model test shows a two-minute countdown while Ollama is running and reports `Test successful after <duration>` when the model responds.
- The bot has an Outlook category-population path that classifies recent Outlook threads into MailAssist categories, dry-runs by default, and only writes Graph message categories with `--apply-categories`.
- The bot has a Gmail category-labeling path that asks the selected local Ollama model to choose one configured MailAssist category, or `NA`, for each recent thread.
- Gmail category labels live under a top-level `MailAssist` label; configured category labels are created as needed and prior MailAssist category labels are replaced/removed during reclassification.
- Settings now stores `MAILASSIST_CATEGORIES`, with `Needs Reply` locked because it drives draft generation.
- The desktop control panel has `Organize Gmail` and `Organize Outlook` actions with bounded day horizons and confirmation copy that warns the run can take a few minutes while the user keeps working.
- The desktop control panel has a confirmation-gated `Preview Outlook Draft` action that runs Outlook draft classification in dry-run mode without creating provider drafts.
- Settings has one shared `MailAssist Categories` editor; Gmail uses those categories to create/update `MailAssist/<Category>` labels and Outlook uses them to create/update `MailAssist - <Category>` message categories.
- `watch-once` and `watch-loop` now support a dry-run mode that produces `draft_ready` events without creating provider drafts.
- The bot now has a polling `watch-loop` path that uses `MAILASSIST_BOT_POLL_SECONDS`.
- The bot has a simplified `watch-once` pass that classifies mock threads, skips non-response mail, and creates one provider draft per actionable thread.
- The provider layer now has a first Gmail inbox/thread polling contract that maps Gmail API threads into `EmailThread` objects for the live watcher.
- Live watcher state now lives in `data/live-state.json` with migration from the older `data/bot-state.json` path.
- Live watcher state now keeps provider-scoped thread records, a provider account-email map, and recent activity summaries in one file.
- The live watcher now persists a discovered provider account email when the provider exposes one and uses it for reply-recipient selection and quoted review context.
- The live watcher now marks threads as `user_replied` when the latest visible message is already from the user account, instead of drafting again.
- The bot can run controlled Gmail draft tests from sanitized mock input, and the desktop app now confirms before creating one live Gmail draft.
- The bot can run a controlled Outlook reply-draft smoke test only when an explicit thread id and `--create-draft` are supplied.
- The controlled Gmail draft test addresses the draft to the account owner and is intended for provider-write validation without emailing an external recipient.
- The desktop control panel now separates Gmail dry-run, controlled Gmail real-draft creation, watch-loop start, and stop actions.
- `watch-once` supports `--batch-size`; batch 5 and batch 10 have both been tested with Gmail draft creation.
- Gmail draft records carry recipient headers so provider drafts can include `To`, `Cc`, and `Bcc`.
- Legacy review-state and local draft/log artifacts now live under `data/legacy/` instead of the main runtime path.
- Live drafting/classification helpers now live in `mailassist.drafting`; `mailassist.review_state` remains as a legacy compatibility/support module for the old two-candidate review path.
- Visible-version loading now lives in `mailassist.version` so the desktop app no longer imports legacy review-state code.
- Live batch LLM output no longer asks for a separate `SHOULD_DRAFT` flag; classification and body content are enough for provider-draft control.
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
- Magali's screen-share confirmed her business mailbox is Microsoft 365 / Exchange Online: Microsoft account home organization is Golden Years Tax Strategy, `admin.microsoft.com` opens for her, the mailbox is licensed as Microsoft 365 Business Standard (no Teams), Outlook web opens the mailbox, and Classic Outlook Desktop reports Microsoft Exchange.
- Magali's Windows laptop is reported to be fairly recent with plenty of SSD storage and 32 GB of RAM. Ollama is installed there with `qwen3:8b` (5.2 GB), but a raw terminal `ollama run` check was slow and showed thinking behavior.

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
- Real Gmail dry-run watching on April 27, 2026 completed with zero provider drafts created; the latest inbox slice had no actionable draft-ready thread.
- Controlled real Gmail draft creation on April 27, 2026 succeeded from sanitized mock content. The corrected draft `r75464073844852680` was fetched back through Gmail and verified as multipart plain/HTML, addressed to `ec92009@gmail.com`, with the controlled subject, review context, attribution in both parts, and no script HTML.
- A real live Gmail `watch-once --provider gmail --force` provider-writing pass on April 28, 2026 created two unsent Gmail drafts for actionable inbox threads, `Nudge` and `Note to self`, after skipping automated/non-response mail. Gmail visual inspection showed review context, generated body text, and the saved signature rendered correctly.
- A live Gmail MailAssist-label reclassification on April 28, 2026 processed 342 recent threads using the local Ollama model `qwen3.6:35b`, the configured category set (`Needs Reply`, `Needs Action`, `Subscriptions`, `Licenses & Accounts`, `Receipts & Finance`, `Appointments`, `Marketing`, `Political`), and the `NA` escape hatch. Gmail labels were applied, replaced, or removed without sending email.
- Personal Outlook.com Microsoft Graph validation on April 28, 2026 succeeded for `ec92009@gmail.com`: device-code auth, `/me`, inbox preview, category writes, controlled reply-draft creation, and a targeted live watcher draft all worked without sending email.
- A live Outlook category pass on April 28, 2026 classified 5 recent Outlook messages and applied one `MailAssist - <Category>` category to each through Microsoft Graph.
- A real live Outlook `watch-once --provider outlook --thread-id ... --force` pass on April 28, 2026 created one unsent model-generated draft for `Test from PT` using `qwen3.6:35b`. A prior dry run produced one `draft_ready` event, and a follow-up pass did not create a duplicate draft.
- A no-write Gemma `gemma4:31b` generation pass on April 30, 2026 against the fresh Outlook `Coucou` thread replied informally in French, using `ton message` rather than formal `votre message`.
- `dist/MailAssist-v56.46-mac-gmail.dmg` was built locally at about 253 MB, well under GitHub Releases' 2 GiB per-asset limit.

## Draft Quality Findings

- The model initially invented commitments such as calling the utility company.
- The model also invented a generic `team` in an open-house decision draft.
- Prompts now explicitly ban invented teams, reviewers, internal processes, availability, and promise-shaped user commitments.
- Drafts now include recent incoming review context so Gmail recipients can see what the generated reply is responding to.
- Review context timestamps use local, readable wording such as `yesterday afternoon at 14:09`.
- The bot post-checks generated bodies and replaces signature-only or promise-shaped responses with a conservative acknowledgement.
- Automated sender safety now treats `noreply`, `do not reply`, `notificationmail`, `promomail`, and `emailnotify` as automated signals before drafting.

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
- Windows packaging notes now exist under `docs/windows-packaging.md`; the real build step needs Parallels or another Windows build machine.
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

- Latest visible version: `v61.6`.
- Latest test run: 183 passing tests on April 30, 2026.
- Current visible GUI surface is the compact bot control panel and setup wizard.
- Gmail provider dependencies are installed by plain `uv sync`.
- Local Gmail setup has been proven for draft creation and readonly inbox preview.
- Mac/Gmail DMG artifact was published as a GitHub release asset.
- The next implementation phase should run the Magali-ready Windows bootstrap during the Zoom call, validate read-only Outlook Graph readiness with `outlook-setup-check`, validate model readiness with `ollama-setup-check`, and only then consider an explicit controlled draft write.
- The latest cleanup slices moved old review/runtime artifacts into a legacy subtree, removed the unused queue-phase lifecycle, deleted the old web review GUI path, removed the dead legacy local draft pipeline, and introduced a dedicated live-state store for watcher runtime data.
- The latest live-watcher slice added watcher filters, provider thread-listing hooks, Gmail thread polling helpers, and background-bot integration for real provider thread sources.
- Gmail actionable-thread listing now passes unread/time-window filters into Gmail search where available, while the watcher still uses broad candidate listing so it can emit `filtered_out` activity events.
- Gmail dry-run and controlled-draft paths are now distinct: dry-run validates watcher flow without provider writes, while controlled draft creation proves Gmail write/rendering behavior with sanitized mock content.
- Personal Outlook.com Graph behavior is proven; Magali Outlook discovery is now resolved as Microsoft 365 / Exchange Online with admin center access.
- Magali's target hardware should be capable of running a medium local model; the unknowns are MailAssist-path model performance with `think: false` and the tenant authorization experience, not baseline RAM.

## Conclusion

The product remains clear: the bot exists to hide local LLM latency. The GUI exists to configure and supervise the bot. The mail provider is where users review, edit, and send drafts. MailAssist creates drafts only; it does not send email.
