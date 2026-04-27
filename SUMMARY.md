# Summary

MailAssist remains a local background draft creator. It watches connected mail, classifies threads with a local Ollama model, creates provider-native drafts when useful, and never sends email. Gmail and mock remain the working sandbox. Windows and Outlook remain the north-star destination for Magali.

## This Conversation

- Checked how far the RTF-signature, watcher-filter, and attribution assignment had progressed.
- Confirmed the first two plan tasks were complete on `feature/gui-rtf-filters-attribution`: new settings fields and `EmailThread.unread`.
- Confirmed the rest of that GUI-polish plan is still pending, starting with `DraftRecord.body_html`.
- Prepared to merge the branch back to `main` and ran `rscp`.
- Reassigned active TODO ownership to Codex and reprioritized unblocked live-watcher work ahead of blocked Outlook implementation.

## Work Being Landed

- Added `Settings.user_signature_html`, `watcher_unread_only`, `watcher_time_window`, and `draft_attribution`, loaded from env vars.
- Added `EmailThread.unread`, defaulting to `True`, with dict loading coverage.
- Added onboarding RAM checks and installed-model recommendations in the desktop wizard.
- Moved model-size formatting and memory recommendation helpers into `src/mailassist/system_resources.py`.
- Updated docs to reflect the `v58.0` visible version and 69-test baseline.

## Current Verified State

- Visible version: `v58.0`.
- Full test suite: 69 passing tests on April 27, 2026.
- Compact desktop control panel remains the visible UI direction.
- Gmail draft creation, Gmail inbox preview, and Gmail signature import remain the working sandbox capabilities.
- The RTF/filter/attribution plan exists under `docs/superpowers/`; tasks 1 and 2 are complete, task 3 onward remains open and Codex-owned.

## Still Pending

- Finish `DraftRecord.body_html`, sanitizer, live watcher filter contract, attribution helpers, bot integration, Gmail multipart drafts, and the actual GUI controls for RTF signatures, filters, and attribution.
- Outlook provider choice remains blocked on Magali's actual Outlook account type and tenant constraints.
- Windows/Outlook connect flow, native Outlook drafts, and Windows packaging still depend on that answer.

## Project Shorthand

- `rscp` means: refresh docs, summarize the current conversation to `SUMMARY.md`, commit, and push.
