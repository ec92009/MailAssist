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

## Current Verified State

- Visible version: `v59.3`.
- Full test suite: 107 passing tests on April 28, 2026.
- Native desktop app is the active GUI surface; it has no localhost or LAN URL.
- Latest pushed commit before this handoff update: `f5009aa`.
- Installed app path: `/Applications/MailAssist.app`.
- Gmail optional dependencies are installed in the local virtualenv.
- Gmail read-only probing, Gmail dry-run watching, controlled Gmail provider-write draft creation, and Gmail multipart draft validation have all been exercised locally.
- The corrected controlled Gmail draft validation proves recipient, subject, review context, attribution, HTML/plain multipart fallback, and HTML sanitizing through the actual Gmail provider path.
- Attribution placement is now persisted with `MAILASSIST_DRAFT_ATTRIBUTION_PLACEMENT`; legacy `MAILASSIST_DRAFT_ATTRIBUTION=true` maps to `below_signature`.
- The first real live Gmail provider-writing pass with actionable inbox mail succeeded on April 28, 2026 and created two real Gmail drafts without sending email.
- Outlook/Microsoft 365 now has a mockable Graph provider slice: in-memory Graph fixtures cover `/me`, mailbox messages, conversation/thread parsing, reply draft creation payloads, and admin-consent auth blockers.
- The compact desktop control panel remains the visible UI direction.
- Live watcher state lives in `data/live-state.json` with provider-scoped slots, account email discovery, recent activity, and migration from the older `data/bot-state.json`.
- Magali's Outlook account discovery remains partially resolved: her main business mailbox is Microsoft 365, so the first Outlook implementation path should focus on Microsoft Graph feasibility and tenant/admin consent.

## Remaining Backlog

- Continue the Outlook/Microsoft 365 provider path for Magali by adding real Microsoft Graph OAuth/token storage and developer-tenant smoke tests when available.
- Package tenant/admin-consent guidance for Magali before attempting her Microsoft 365 account.
- Continue product safety and trust hardening around explicit provider writes and ignored runtime artifacts.
- Continue architecture cleanup by quarantining remaining two-candidate review helpers as legacy-only support.
- Maintain the Mac/Gmail sandbox and prepare packaging/distribution work, especially Windows signing/installer research.

## Project Shorthand

- `rscp` means: refresh docs, summarize the current conversation to `SUMMARY.md`, commit, and push.
