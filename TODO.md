# TODO

This backlog is ordered around the north-star user: Magali, a CPA in San Diego who runs her own business, uses Windows, and gets business email in Outlook Desktop.

Mac/Gmail remains the proving ground because it is already working locally and exercises the drafting loop. Windows/Outlook is the more important destination. Magali's screen-share confirmed her business mailbox is Microsoft 365 / Exchange Online, she can access the Microsoft 365 admin center, and Microsoft Graph is the right Outlook provider path.

## Handoff

- Quick start for next operator or machine:
  ```bash
  work in ~/Dev/MailAssist, synchronize with Github ec92009/MailAssist, catch up; open TODO.md and execute the handoff instructions
  ```
- Operator checklist for a new machine:
  - Repository: `/Users/ecohen/Dev/MailAssist`
  - Origin: `git@github.com:ec92009/MailAssist.git`
  - Branch policy: work on `main` unless explicitly told otherwise.
  - Sync steps:
    - `cd /Users/ecohen/Dev/MailAssist`
    - `git checkout main`
    - `git pull origin main`
    - `uv sync`
    - `sed -n '1,220p' TODO.md`
    - `sed -n '1,180p' SUMMARY.md`
- Current baseline at handoff:
  - Last synchronized commit before this handoff commit: `0d1ddb3`
  - Handoff commit: reported in the final assistant response after commit/push
  - Current visible version: `v60.1`
  - Local app/dev entrypoint: `./.venv/bin/mailassist desktop-gui`
  - Packaged app path: `/Applications/MailAssist.app`
- Known open issue to continue:
  - Personal Outlook.com Microsoft Graph is now proven end to end: auth, inbox reads, category writes, controlled draft creation, and live watcher-created model draft creation all succeeded without sending email.
  - Magali's Windows laptop is fairly recent with plenty of SSD storage and 32 GB RAM. Ollama is already installed with `qwen3:8b` (5.2 GB). Raw `ollama run` was slow/thinking; use MailAssist's own `think: false` model check during setup.
  - Magali's Microsoft 365 state is now confirmed: home organization Golden Years Tax Strategy, admin center access works, mailbox license is Microsoft 365 Business Standard (no Teams), Outlook web opens the mailbox, and Classic Outlook Desktop account type is Microsoft Exchange.
  - Immediate next implementation step: create the MailAssist Microsoft Entra app registration that supports work/school accounts, paste its client id into the Magali `.env` template, then stage a Magali-ready Windows run that can execute `mailassist outlook-setup-check --expected-email MagaliDomingue@goldenyearstaxstrategy.com` and `mailassist ollama-setup-check --model qwen3:8b` before any controlled draft write.
  - Keep Outlook provider writes explicit. Current safe commands are `review-bot --action outlook-smoke-test --thread-id <id> --create-draft`, `review-bot --action watch-once --provider outlook --thread-id <id> --force`, and `review-bot --action outlook-populate-categories --days <n> --apply-categories`.
- Handoff protocol for this repo:
  - Run `prepare for handoff` before switching machines or ending a work block that should resume elsewhere.
  - Keep `SUMMARY.md` and this `Handoff` block current.
  - Commit and push to `main` before reporting handoff ready.
  - The final handoff commit hash is reported in the assistant response because the commit cannot contain its own hash.

## Recently Completed

- Added a dedicated live watcher state store at `data/live-state.json` with migration from the older `data/bot-state.json` path. (Managed by Codex)
- Persisted provider account email discovery for the live watcher and used it for reply recipients and quoted review context. (Managed by Codex)
- Added manual `user_replied` detection when the latest visible message is already from the user account. (Managed by Codex)
- Added a polling `watch-loop` bot action that uses `MAILASSIST_BOT_POLL_SECONDS` and emits failed/retry JSONL events. (Managed by Codex)
- Consolidated provider thread runtime state under provider-scoped slots with room for future provider cursors. (Managed by Codex)
- Added onboarding RAM checks and installed-model recommendations, including a clear warning when no installed model looks small enough. (Managed by Codex)
- Added initial RTF/filter/attribution settings fields and `EmailThread.unread` for the GUI polish slice. (Managed by Codex)
- Added the first Gmail thread polling contract: watcher filters, provider thread-listing hooks, Gmail thread-to-`EmailThread` mapping, and background-bot integration with test coverage. (Managed by Codex)
- Reviewed Magali's Outlook screenshots and confirmed her main business address appears as a Microsoft 365 account in Outlook Desktop; she also has an Outlook.com account visible in the account list. (Managed by Codex)
- Exercised real Gmail read-only paths with local credentials: inbox preview, full candidate-thread extraction, and actionable-thread extraction all returned body text without missing ids, senders, or dates. (Managed by Codex)
- Wired Gmail actionable-thread listing to use provider-side Gmail search queries for unread/time-window filters while keeping watcher candidate listing broad enough to emit `filtered_out` activity. (Managed by Codex)
- Bumped visible version to `v58.6`, rebuilt/opened the installed Mac app, and polished the setup/control-panel layout: expanding Review and Recent Activity fields, provider-specific Gmail/Outlook watcher filter panels, check-frequency copy, model-selection stability, and clearer RAM guidance. (Managed by Codex)
- Added safe Gmail/watch dry-run support, exercised it against real Gmail credentials with zero provider drafts created, added rich signature/HTML draft body plumbing, Gmail multipart drafts, optional draft attribution, and renamed the live watch-pass entry point away from the old mock-specific name. (Managed by Codex)
- Created controlled real Gmail test drafts from sanitized mock content and fetched the corrected draft back through the Gmail API to validate recipient, subject, multipart plain/HTML content, review context, attribution, and HTML sanitizing. (Managed by Codex)
- Added explicit rich signature editor controls for bold, italic, underline, and links. (Managed by Codex)
- Added live watcher control-panel polish: clear Gmail dry-run vs controlled real-draft actions, start/stop watch-loop controls, and visible watch-loop pass/failure activity events. (Managed by Codex)
- Moved live drafting/classification helpers into `mailassist.drafting` so the background bot no longer depends on legacy `review_state.py`; the old review module remains as compatibility/legacy support. (Managed by Codex)
- Bumped visible version to `v59.1` for the controlled Gmail draft, rich signature, watch-loop control, and architecture cleanup release. (Managed by Codex)
- Defined the shared provider readiness/auth contract that Outlook/Microsoft Graph must satisfy: authenticate, discover account email, list candidate threads, create drafts, and report readiness/admin-consent blockers. (Managed by Codex)
- Added a Settings `Signature + Attribution` preview, replaced the attribution checkbox with `Hide`/`Above Signature`/`Below Signature`, made plain and HTML draft assembly honor that placement, and kept the controlled Gmail validation command attribution-enabled for multipart safety checks. (Managed by Codex)
- Increased the Advanced Settings check-frequency spinner height to match neighboring text fields without reducing those fields. (Managed by Codex)
- Bumped visible version to `v59.2` for the signature attribution placement and Advanced Settings height polish release. (Managed by Codex)
- Visually inspected a fresh controlled Gmail draft in Gmail's draft editor after fixing rich-signature persistence/fallback behavior. The draft rendered recipient, quoted context, body, saved signature, and attribution correctly with no duplicate signature or broken HTML. (Managed by Codex)
- Exercised a real live Gmail provider-writing pass against actionable inbox threads. The pass created two real Gmail drafts (`Nudge` and `Note to self`) with review context, generated body text, and saved signature rendered in Gmail; no email was sent. (Managed by Codex)
- Added the first Microsoft Graph mock-fixture slice for Outlook/Microsoft 365: `/me` account email discovery, synthetic mailbox messages, conversation/thread parsing, watcher filter support, reply-draft payload mapping, and admin-consent auth failure reporting through the provider readiness contract. (Managed by Codex)
- Bumped visible version to `v59.3` for the Outlook/Microsoft 365 Graph fixture and provider-contract progress. (Managed by Codex)
- Added real Microsoft Graph device-code OAuth, refresh-token storage under the ignored Outlook token path, a real Graph client for `/me`, inbox listing, and reply-draft creation, and an `outlook-auth` CLI command for first authorization. (Managed by Codex)
- Bumped visible version to `v59.4` for the Outlook OAuth/token-storage provider progress. (Managed by Codex)
- Added a safe Outlook smoke-test bot action for readiness, `/me`, inbox preview, and explicit controlled reply-draft validation by thread id; added Microsoft 365 app-registration/admin-consent notes under `docs/outlook-m365-admin-consent.md`. (Managed by Codex)
- Bumped visible version to `v59.5` for the Outlook smoke-test and tenant-consent readiness slice. (Managed by Codex)
- Moved visible-version loading out of legacy `review_state.py` into `mailassist.version`, leaving `review_state.py` as compatibility-only support for the old two-candidate review path. (Managed by Codex)
- Simplified the live batch LLM output shape by removing the redundant `SHOULD_DRAFT` flag; draft/no-draft is now inferred from classification and body content. (Managed by Codex)
- Added Windows packaging notes and a Parallels/VM checklist under `docs/windows-packaging.md`. (Managed by Codex)
- Added a dry-run-first Gmail label cleanup command that finds old messages under user labels and can explicitly remove those labels from matching old messages without deleting labels or emails. (Managed by Codex)
- Excluded archive labels from Gmail old-message label cleanup because old archived mail can remain archived. (Managed by Codex)
- Added MailAssist Gmail category labels under a top-level `MailAssist` label. Categories are user-configurable, `Needs Reply` is locked because it drives draft generation, and Ollama now chooses exactly one configured category or `NA` for no obvious category. (Managed by Codex)
- Added the desktop `Organize Gmail` control with a limited day horizon, confirmation copy that discloses the run can take a few minutes while the user keeps working, and compact user-centered bot-control labels. (Managed by Codex)
- Ran a live Gmail reclassification for the last 7 days with the updated category set including `Marketing` and `Political`; it processed 342 threads and applied/replaced/removed MailAssist labels through Gmail without sending email. (Managed by Codex)
- Bumped visible version to `v59.8` for the Gmail category-labeling and control-panel polish release. (Managed by Codex)
- Registered a personal Microsoft-account Azure app for MailAssist, enabled public client flows, added delegated `User.Read`, `Mail.ReadWrite`, and `offline_access`, authorized `ec92009@gmail.com`, and saved the ignored Outlook token under `secrets/outlook-token.json`. (Managed by Codex)
- Proved real personal Outlook Graph readiness and read access with `outlook-smoke-test`: `/me`, inbox preview, and provider readiness all returned ready without admin consent. (Managed by Codex)
- Added Outlook MailAssist category support: Graph message `categories` updates, `outlook-populate-categories` dry-run/apply action, guarded `Needs Reply` category behavior, and a live apply pass over 5 Outlook messages. (Managed by Codex)
- Added the desktop `Organize Outlook` control beside `Organize Gmail`, then standardized both organizer controls on a `days` horizon and kept one shared `MailAssist Categories` editor for Gmail labels and/or Outlook categories. (Managed by Codex)
- Created one controlled unsent Outlook reply draft for the `Test outlook` thread through Graph, then created one real model-generated unsent Outlook watcher draft for the fresh `Test from PT` thread. No email was sent. (Managed by Codex)
- Tightened automated-mail safety by treating `noreply`, `do not reply`, `notificationmail`, `promomail`, and `emailnotify` as automated signals before drafting. (Managed by Codex)
- Bumped visible version through `v59.12` for the Outlook category/drafting and organizer UI work; latest full local test suite passed with 135 tests on April 28, 2026. (Managed by Codex)
- After handoff, updated the TODO handoff block to record the pushed handoff commit explicitly. (Managed by Codex)
- Added a confirmation-gated desktop `Preview Outlook Draft` action that runs Outlook `watch-once` in dry-run mode only, so the GUI can exercise Outlook draft classification without creating provider drafts. Bumped visible version to `v59.13`; full local test suite passed with 137 tests on April 28, 2026. (Managed by Codex)
- Added `pytest` to uv's default dev dependency group and updated the environment SOP so plain `uv sync` keeps the test runner installed for normal pickup/test workflows. (Managed by Codex)
- Added `docs/magali-outlook-call-checklist.md` with a nontechnical screen-share script, safety ground rules, public DNS findings, Microsoft account/admin checks, and safe Outlook authorization/readiness commands. (Managed by Codex)
- Recorded Magali's target machine context: recent Windows laptop, 32 GB RAM, ample SSD storage, Ollama already installed, exact local model still unknown. (Managed by Codex)
- Completed the Magali discovery call: confirmed Microsoft 365 / Exchange Online mailbox, Golden Years Tax Strategy home organization, admin center access, Microsoft 365 Business Standard license, Outlook web access, Classic Outlook Desktop Microsoft Exchange account type, and installed Ollama model `qwen3:8b`. (Managed by Codex)
- Added `mailassist outlook-setup-check`, a one-command read-only Outlook setup path that authorizes Graph, verifies the signed-in mailbox, enforces an optional expected email, previews inbox thread subjects without bodies, and confirms no drafts were created or sent. Bumped visible version to `v59.14`; full local test suite passed with 140 tests on April 28, 2026. (Managed by Codex)
- Added a Magali-ready Outlook `.env` template, refreshed Microsoft 365 app-registration/admin-consent docs for work/school account support, and added `mailassist ollama-setup-check` so her `qwen3:8b` model can be tested through MailAssist's own `think:false` Ollama path. Bumped visible version to `v59.15`; full local test suite passed with 142 tests on April 28, 2026. (Managed by Codex)
- Moved Gmail provider packages into the default project dependencies so plain `uv sync` keeps Gmail usable for the desktop watcher; updated stale setup/error guidance away from the removed `.[gmail]` extra. Bumped visible version to `v59.16`; full local test suite passed with 142 tests on April 28, 2026. (Managed by Codex)
- Simplified the desktop bot action row by removing demo/test-draft controls from the main strip, added detailed tooltips to the remaining everyday actions, and made slow actions announce expected wait time in Recent Activity before running. Bumped visible version to `v59.17`; full local test suite passed with 143 tests on April 28, 2026. (Managed by Codex)
- Added a desktop `Stop Ollama` control that confirms first, stops any active MailAssist bot action, tries `ollama stop <model>`, and force-quits the local Ollama process when needed so stuck local model work can be interrupted. Bumped visible version to `v60.1`; full local test suite passed with 147 tests on April 29, 2026. (Managed by Codex)
- Added a Magali pre-Zoom checklist, Zoom operator script, Windows readiness runbook, Entra app portal steps, Entra manifest/permissions JSON, Azure CLI create/verify helpers, and `tools/magali-readiness.ps1` so the next call can pass the work/school Entra client id directly to the helper, run the read-only Outlook setup check, and run the MailAssist-path `qwen3:8b` Ollama check without improvising. Installed Azure CLI locally, created the work/school multitenant `MailAssist Outlook` app registration, enabled public client flows, added delegated `offline_access`, `User.Read`, and `Mail.ReadWrite` only, verified it with Azure CLI, and updated ignored local `.env` to use `MAILASSIST_OUTLOOK_CLIENT_ID=2b2639c3-605c-466d-ae89-63ef8ffff5c8` plus `MAILASSIST_OUTLOOK_TENANT_ID=organizations`. (Managed by Codex)

## Remaining Backlog

1. Run the Magali-ready Outlook authorization/install flow during the Zoom call. Personal Outlook.com auth/read/category/write/draft paths are validated, Magali's Microsoft 365 / Exchange account/admin state is confirmed, and the work/school multitenant `MailAssist Outlook` app registration is ready. Use client id `2b2639c3-605c-466d-ae89-63ef8ffff5c8` with tenant `organizations`, then run `tools/magali-readiness.ps1` on Windows before any controlled draft write. (Managed by Codex)

2. Decide the next Outlook GUI exposure after Microsoft 365 tenant validation. The GUI now exposes dry-run-only Outlook draft preview and `Organize Outlook`; real Outlook draft creation remains limited to explicit CLI/smoke-test paths until business-tenant behavior is proven. Keep provider-writing actions explicit and confirmation-gated. (Managed by Codex)

3. Continue product safety and trust hardening. Send automation stays out of scope, provider-writing actions stay explicit, live provider tests stay behind confirmation/developer UI, and real tokens/logs/drafts/queues/email artifacts stay out of git. (Managed by Codex)

4. Continue architecture cleanup. Remaining two-candidate review helpers are now legacy-only compatibility/test support; future cleanup should delete them only after no archived tests or support paths need them. (Managed by Codex)

5. Maintain the Mac/Gmail sandbox. Keep mock-to-Gmail draft tests, read-only Gmail preview, ignored OAuth credential paths, hidden developer OAuth settings, and optional Mac/Gmail `.dmg` artifacts available for regression and learning. (Managed by Codex)

6. Prepare packaging and distribution. Windows packaging notes now exist; the next real packaging step requires a Parallels VM or another Windows build machine. Keep `dist/` ignored, publish test builds through GitHub Releases when useful, keep README download links in sync with the visible version, and defer Mac signing/notarization until broader Mac use requires it. (Managed by Codex) (Blocked on Windows VM for Windows build)
