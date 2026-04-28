# Summary

MailAssist remains a local background draft creator. It watches connected mail, classifies threads with a local Ollama model, creates provider-native drafts when useful, and never sends email. Gmail and mock are the working sandbox. Windows and Outlook remain the north-star destination for Magali.

## This Conversation

- Continued from the MailAssist handoff context with the active backlog focused on Gmail watcher safety, rich signatures/HTML drafts, attribution, control-panel polish, and cleanup of legacy review-state architecture.
- Cleaned `TODO.md` from stale P0/P8 buckets into a concise remaining-backlog list, then worked through the requested items.
- Added safe `--dry-run` support for `watch-once` and `watch-loop`; dry runs produce `draft_ready` events and do not call provider draft creation.
- Ran a real Gmail `watch-once --provider gmail --dry-run` pass. It completed safely with `dry_run: true`, created zero Gmail drafts, and found no actionable draft-ready thread in the latest inbox slice.
- Added `DraftRecord.body_html`, shared rich-text helpers, sanitized HTML/plain-text conversion, optional attribution helpers, and Gmail multipart draft creation for HTML bodies.
- Replaced the signature field with a rich `QTextEdit`, added persistence for `MAILASSIST_USER_SIGNATURE_HTML`, and added explicit bold, italic, underline, and link controls.
- Added an attribution checkbox and draft assembly support so enabled drafts can include MailAssist/Ollama/model attribution in both plain and HTML parts.
- Added a controlled Gmail provider-write action from sanitized mock content. It creates one real Gmail draft addressed to the account owner, behind confirmation in the GUI.
- Created and fetched back a corrected controlled Gmail draft, `r75464073844852680`, through the Gmail API. The fetched MIME was multipart `text/plain` + `text/html`, addressed to `ec92009@gmail.com`, had the controlled subject, contained review context and attribution in both parts, and had no script HTML.
- Polished the control panel with separate `Run Gmail Dry Run`, `Create Gmail Test Draft`, `Start Watch Loop`, and `Stop` controls, plus clearer watch-loop activity/failure events.
- Moved live drafting/classification helpers into `mailassist.drafting` so the background bot no longer imports them from legacy `review_state.py`. The old review module remains as compatibility/legacy support.
- Bumped the visible version to `v59.1` for this user-visible build.
- Refreshed docs, committed and pushed release commit `68d4b07` to `origin/main`, built `/Applications/MailAssist.app`, refreshed the Dock entry, and opened the native GUI.
- Started today's Outlook/Microsoft 365 work by defining the provider readiness/auth contract. Providers now expose `authenticate`, `get_account_email`, `list_candidate_threads`, `create_draft`, and `readiness_check`; Outlook reports missing Graph client-id and admin-consent/Graph implementation blockers without requiring a real Outlook subscription.
- Added two GUI polish TODOs requested by the user: show a `Signature + Attribution` preview with attribution placement options (`Hide`, `Above Signature`, `Below Signature`), and harmonize Advanced Settings field heights by increasing the check-frequency spinner height rather than shrinking neighboring text fields.
- Resumed from the handoff and completed the GUI polish TODOs: Settings now previews `Signature + Attribution`, attribution placement is `Hide`/`Above Signature`/`Below Signature`, watcher drafts honor placement in plain and HTML bodies, and Advanced Settings gives the check-frequency spinner the neighboring field height.
- Bumped the visible version to `v59.2` and ran the full test suite after the polish work: 101 passing tests on April 28, 2026.
- Fixed rich-signature persistence/fallback behavior discovered during Gmail visual inspection, then verified a controlled Gmail draft and a real live Gmail provider-writing pass in Gmail's draft editor. The live pass created two real unsent drafts, `Nudge` and `Note to self`, with review context, body text, and the saved signature visible.
- Added the first Outlook/Microsoft 365 Graph mock-provider slice: `/me` account email discovery, synthetic mailbox messages, conversation/thread parsing, watcher filtering, reply-draft payload mapping, and admin-consent auth failure reporting through the provider readiness contract.
- Bumped the visible version to `v59.3` and ran the full test suite after the Outlook slice: 107 passing tests on April 28, 2026.
- Picked up from the project SOP, synced `main`, refreshed the virtualenv, and resumed the recorded Outlook/Microsoft 365 next step.
- Added real Microsoft Graph device-code OAuth, ignored local refresh-token storage, a concrete Graph client for `/me`, inbox listing, and reply-draft creation, plus a `mailassist outlook-auth` command for first authorization.
- Bumped the visible version to `v59.4` and ran the full test suite after the OAuth slice: 110 passing tests on April 28, 2026.
- Added a safe `outlook-smoke-test` bot action that reports Outlook readiness and thread previews, and only creates a controlled reply draft when `--create-draft` and an explicit `--thread-id` are both provided.
- Added `docs/outlook-m365-admin-consent.md` with Microsoft 365 app-registration, delegated Graph scope, token-path, device-code auth, smoke-test, and admin-consent notes.
- Bumped the visible version to `v59.5`; the next Outlook step now needs an actual Microsoft 365 developer tenant or Magali tenant authorization.
- Continued through the next unblocked backlog items: moved visible-version loading out of legacy review-state code, simplified batch LLM output by removing the redundant `SHOULD_DRAFT` flag, and added `docs/windows-packaging.md` with a Parallels/VM checklist.
- Added Gmail old-message label cleanup: a dry-run-first bot action reports user labels that are attached to messages older than a configurable number of years, and `--remove-labels` removes those labels from the matching old messages without deleting labels or emails.
- Updated Gmail old-message label cleanup to exclude archive labels after the user clarified old archived mail can remain archived.
- Ran the full test suite after the smoke-test and cleanup slices: 116 passing tests on April 28, 2026.
- Cleaned up Gmail labels: removed stale labels from old non-archived mail, preserved archived mail after clarification, deleted unused user labels, and created a top-level `MailAssist` label tree.
- Added configurable MailAssist Gmail categories. `Needs Reply` is locked because it drives draft generation; users can add/remove other categories, and MailAssist creates matching Gmail labels as needed.
- Replaced the heuristic multi-label Gmail pass with a separate local Ollama categorization prompt: the selected model gets the configured category list, must choose one category, and may return `NA`/`No obvious category` to remove/skip MailAssist labels.
- Added the desktop `Organize Gmail` control with a limited day horizon, confirmation copy that discloses the run may take a few minutes while the user keeps working, user-centered bot-control labels, and compact aligned controls.
- Ran a live 7-day Gmail reclassification with `qwen3.6:35b` and categories `Needs Reply`, `Needs Action`, `Subscriptions`, `Licenses & Accounts`, `Receipts & Finance`, `Appointments`, `Marketing`, and `Political`; it completed 342 threads with Gmail labels applied/replaced/removed and no email sent.
- Bumped the visible version through `v59.8` and ran the full test suite after the UI/category work: 128 passing tests on April 28, 2026.

## Current Verified State

- Visible version: `v59.8`.
- Full test suite: 128 passing tests on April 28, 2026.
- Native desktop app is the active GUI surface; it has no localhost or LAN URL.
- Latest synchronized commit before this pickup: `6b65687`.
- Installed app path: `/Applications/MailAssist.app`.
- Gmail optional dependencies are installed in the local virtualenv.
- Gmail read-only probing, Gmail dry-run watching, controlled Gmail provider-write draft creation, and Gmail multipart draft validation have all been exercised locally.
- The corrected controlled Gmail draft validation proves recipient, subject, review context, attribution, HTML/plain multipart fallback, and HTML sanitizing through the actual Gmail provider path.
- Attribution placement is now persisted with `MAILASSIST_DRAFT_ATTRIBUTION_PLACEMENT`; legacy `MAILASSIST_DRAFT_ATTRIBUTION=true` maps to `below_signature`.
- The first real live Gmail provider-writing pass with actionable inbox mail succeeded on April 28, 2026 and created two real Gmail drafts without sending email.
- Outlook/Microsoft 365 now has a mockable Graph provider slice plus a real Graph client: in-memory fixtures cover `/me`, mailbox messages, conversation/thread parsing, reply draft creation payloads, and admin-consent auth blockers; the real client handles device-code OAuth, refresh-token reuse, `/me`, inbox listing, and reply-draft creation. The bot has a safe Outlook smoke-test action for readiness/read validation and explicit controlled draft creation by thread id.
- The compact desktop control panel remains the visible UI direction.
- The compact desktop control panel now includes user-centered bot actions, including `Organize Gmail` with a bounded days spinner for forced recent reclassification.
- Gmail MailAssist labels are now category-driven: one configured category per thread at most, or no label when Ollama returns `NA`.
- Visible version loading now lives in `mailassist.version`; `review_state.py` is compatibility-only support for the old two-candidate review path.
- Live batch LLM output no longer asks for a separate `SHOULD_DRAFT` report flag.
- Live watcher state lives in `data/live-state.json` with provider-scoped slots, account email discovery, recent activity, and migration from the older `data/bot-state.json`.
- Magali's Outlook account discovery remains partially resolved: her main business mailbox is Microsoft 365, so the first Outlook implementation path should focus on Microsoft Graph feasibility and tenant/admin consent.

## Remaining Backlog

- Continue the Outlook/Microsoft 365 provider path once a developer tenant or Magali tenant app authorization is available.
- Use `docs/outlook-m365-admin-consent.md` as the packaged tenant/admin-consent guidance before attempting Magali's Microsoft 365 account.
- Continue product safety and trust hardening around explicit provider writes and ignored runtime artifacts.
- Maintain the Mac/Gmail sandbox.
- Continue Windows packaging once Parallels or another Windows build machine is available.

## Project Shorthand

- `rscp` means: refresh docs, summarize the current conversation to `SUMMARY.md`, commit, and push.
