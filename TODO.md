# TODO

This backlog is ordered around the north-star user: Magali, a CPA in San Diego who runs her own business, uses Windows, and gets business email in Outlook Desktop.

Mac/Gmail remains the proving ground because it is already working locally and exercises the drafting loop. Windows/Outlook is the more important destination. Magali's screenshots show her business mailbox in Outlook Desktop is a Microsoft 365 account, so the first Outlook provider decision should now focus on Microsoft Graph feasibility and tenant/admin consent instead of broad account-type discovery.

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
  - Last synchronized commit before this handoff update: `59cf4ae`
  - Current visible version: `v59.1`
  - Local app/dev entrypoint: `./.venv/bin/mailassist desktop-gui`
  - Packaged app path: `/Applications/MailAssist.app`
- Known open issue to continue:
  - Highest unblocked implementation work is now Outlook/Microsoft 365 progress without a real Outlook subscription: build Graph mock fixtures on top of the new provider readiness/auth contract.
  - Immediate next implementation step: add synthetic Microsoft Graph fixtures for `/me`, mailbox messages, conversation/thread parsing, draft creation, and admin-consent/auth failures.
  - Small GUI polish tasks are also ready: add a `Signature + Attribution` preview with `Hide`/`Above Signature`/`Below Signature`, and increase the check-frequency spinner height to match neighboring fields without shrinking those fields.
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

## Remaining Backlog

1. Validate the corrected controlled Gmail draft visually in Gmail's draft editor if browser/manual inspection is desired; API validation is complete and shows multipart plain/HTML content, attribution, review context, recipient, subject, and sanitizing are correct. (Managed by Codex)

2. Show a `Signature + Attribution` preview in Settings. Replace the attribution checkbox with a choice: `Hide`, `Above Signature`, or `Below Signature`, and make draft assembly honor that placement in both plain and HTML bodies. (Managed by Codex)

3. Harmonize Advanced Settings field heights by increasing the check-frequency spinner height to match the neighboring text fields; do not reduce the other field heights. (Managed by Codex)

4. Exercise one real live-watch provider-writing pass when a genuinely actionable Gmail inbox thread is available; the controlled provider-write path is proven, but the latest real inbox slice had no actionable candidate. (Managed by Codex)

5. Build the Outlook/Microsoft 365 provider path for Magali on the new provider contract. Next steps are Graph mock fixtures, auth/readiness checks, account email discovery, inbox/thread parsing, and provider-native draft payloads. (Managed by Codex) (Waiting on Magali/admin where noted)

6. Continue product safety and trust hardening. Send automation stays out of scope, provider-writing actions stay explicit, live provider tests stay behind confirmation/developer UI, and real tokens/logs/drafts/queues/email artifacts stay out of git. (Managed by Codex)

7. Continue architecture cleanup. Move any remaining live-only prompt helpers out of legacy paths, then quarantine remaining two-candidate review helpers as legacy-only test/support code. (Managed by Codex)

8. Maintain the Mac/Gmail sandbox. Keep mock-to-Gmail draft tests, read-only Gmail preview, ignored OAuth credential paths, hidden developer OAuth settings, and optional Mac/Gmail `.dmg` artifacts available for regression and learning. (Managed by Codex)

9. Prepare packaging and distribution. Keep `dist/` ignored, publish test builds through GitHub Releases when useful, keep README download links in sync with the visible version, research Windows signing/installer needs before handing a build to Magali, and defer Mac signing/notarization until broader Mac use requires it. (Managed by Codex)
