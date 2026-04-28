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
- Picked up from the handoff SOP on `main` at `5935e1c`, synced the repo, refreshed the local package environment, and resumed the Outlook/Microsoft Graph path.
- Created a personal Microsoft-account Azure app registration for MailAssist after Microsoft Developer Program tenant signup proved gated. The app is configured for personal Microsoft accounts, public client/native auth, delegated `User.Read`, `Mail.ReadWrite`, and `offline_access`, with local `.env` using tenant `consumers` and token storage under ignored `secrets/outlook-token.json`.
- Authorized `ec92009@gmail.com` through Microsoft device-code auth and proved real Graph readiness/read access: `/me` returned the account email, inbox preview returned 25 Outlook threads, and `outlook-smoke-test` reported `can_authenticate`, `can_read`, and `can_create_drafts` all true with no admin consent required.
- Added Outlook category support as the Outlook counterpart to Gmail labels: Graph message `categories` reads/writes, provider `replace_thread_categories`, `outlook-populate-categories` dry-run/apply action, and `MailAssist - <Category>` rendering for Outlook.
- Ran live Outlook category classification against the dormant Outlook mailbox. A dry run previewed 5 threads, then an apply pass wrote one MailAssist category to each of 5 Outlook messages without sending email.
- Added GUI support for Outlook organization: `Organize Gmail` and `Organize Outlook` sit side-by-side in bot controls, both use a `days` unit, and one shared `MailAssist Categories` editor explains that categories create/update Gmail labels and/or Outlook categories.
- Created one controlled unsent Outlook reply draft for the `Test outlook` thread through Graph smoke-test tooling.
- Sent a fresh Outlook test email (`Test from PT`), ran `watch-once --provider outlook --dry-run --force`, confirmed one `draft_ready` event, then ran a targeted real Outlook watcher pass that created one model-generated unsent Outlook draft with `qwen3.6:35b`. No email was sent.
- Tightened automated-mail safety so `noreply`, `do not reply`, `notificationmail`, `promomail`, and `emailnotify` are treated as automated signals before drafting, and guarded MailAssist `Needs Reply` category assignment for automated/newsletter-like messages.
- Bumped the visible version through `v59.12` and ran the full test suite after the Outlook category/drafting/UI work: 135 passing tests on April 28, 2026.
- Picked up from the handoff on `main` at `e39fa7f`, synced with origin, refreshed the environment with `uv sync`, and confirmed the Microsoft 365 tenant validation step remains blocked on a developer tenant or Magali tenant authorization.
- Added a safe desktop `Preview Outlook Draft` action that confirms first, saves current settings, then runs Outlook `watch-once` with `--dry-run --force`; it reads/classifies recent Outlook threads but does not create provider drafts or send email.
- Bumped the visible version to `v59.13` and ran the full local test suite after the Outlook preview GUI work: 137 passing tests on April 28, 2026.
- Confirmed the Golden Years Tax Strategy website is hosted by Squarespace while the domain's primary mail MX points to Microsoft 365 / Exchange Online, then added `docs/magali-outlook-call-checklist.md` so the eventual screen-share can quickly capture account/admin state without exposing passwords or private mail.
- Recorded updated target-machine context for Magali: recent Windows laptop, 32 GB RAM, ample SSD storage, Ollama already installed, and local model `qwen3:8b` installed.
- During the Magali screen-share, confirmed her Microsoft account home organization is Golden Years Tax Strategy, `admin.microsoft.com` opens for her, her mailbox license is Microsoft 365 Business Standard (no Teams), Outlook web opens the Golden Years mailbox, and Classic Outlook Desktop reports the account type as Microsoft Exchange.
- A direct terminal `ollama run qwen3:8b ...` check was slow and showed thinking behavior; the real setup check should use MailAssist's own Ollama path with `think: false`.
- Added `mailassist outlook-setup-check`, a read-only one-command Outlook setup path that runs Graph authorization, verifies readiness, checks an optional expected mailbox email, previews inbox thread subjects only, and explicitly avoids draft creation/sending. Bumped visible version to `v59.14` and ran the full local test suite: 140 passing tests on April 28, 2026.

## Current Verified State

- Visible version: `v59.14`.
- Full test suite: 140 passing tests on April 28, 2026.
- Native desktop app is the active GUI surface; it has no localhost or LAN URL.
- Latest synchronized commit before the handoff commit: `5935e1c`.
- Installed app path: `/Applications/MailAssist.app`.
- Gmail optional dependencies are installed in the local virtualenv.
- Gmail read-only probing, Gmail dry-run watching, controlled Gmail provider-write draft creation, and Gmail multipart draft validation have all been exercised locally.
- The corrected controlled Gmail draft validation proves recipient, subject, review context, attribution, HTML/plain multipart fallback, and HTML sanitizing through the actual Gmail provider path.
- Attribution placement is now persisted with `MAILASSIST_DRAFT_ATTRIBUTION_PLACEMENT`; legacy `MAILASSIST_DRAFT_ATTRIBUTION=true` maps to `below_signature`.
- The first real live Gmail provider-writing pass with actionable inbox mail succeeded on April 28, 2026 and created two real Gmail drafts without sending email.
- Outlook/Microsoft Graph now has a mockable provider slice plus real personal-Outlook validation: in-memory fixtures cover `/me`, mailbox messages, conversation/thread parsing, category updates, reply draft creation payloads, and admin-consent auth blockers; the real client handles device-code OAuth, refresh-token reuse, `/me`, inbox listing, category writes, and reply-draft creation. The bot has safe Outlook smoke-test, category-population, and targeted watcher-draft paths.
- The compact desktop control panel remains the visible UI direction.
- The compact desktop control panel now includes user-centered bot actions, including `Organize Gmail` and `Organize Outlook` with bounded days spinners for forced recent organization.
- MailAssist categories are now shared across providers: Gmail renders them as `MailAssist/<Category>` labels, Outlook renders them as `MailAssist - <Category>` categories, and Ollama chooses one configured category or `NA`.
- Visible version loading now lives in `mailassist.version`; `review_state.py` is compatibility-only support for the old two-candidate review path.
- Live batch LLM output no longer asks for a separate `SHOULD_DRAFT` report flag.
- Live watcher state lives in `data/live-state.json` with provider-scoped slots, account email discovery, recent activity, and migration from the older `data/bot-state.json`.
- Magali's Outlook account discovery is resolved enough to proceed: her main business mailbox is Microsoft 365 / Exchange Online, she can access the Microsoft 365 admin center, and Outlook Desktop uses Microsoft Exchange.

## Remaining Backlog

- Verify or create a MailAssist Microsoft Entra app registration that supports work/school accounts, then package or stage a Magali-ready Windows run that can execute `mailassist outlook-setup-check --expected-email MagaliDomingue@goldenyearstaxstrategy.com`; run any controlled draft write only after read-only readiness succeeds.
- Run MailAssist's own small local model check on her `qwen3:8b` setup; hardware RAM is likely sufficient, but raw terminal Ollama thinking was slow.
- Use `docs/outlook-m365-admin-consent.md` as the packaged tenant/admin-consent guidance before attempting Magali's Microsoft 365 account.
- Decide the next Outlook GUI exposure for drafting. Current GUI exposes `Organize Outlook`; targeted Outlook draft creation remains available through explicit CLI/smoke-test commands.
- Continue product safety and trust hardening around explicit provider writes and ignored runtime artifacts.
- Maintain the Mac/Gmail sandbox.
- Continue Windows packaging once Parallels or another Windows build machine is available.

## Project Shorthand

- `rscp` means: refresh docs, summarize the current conversation to `SUMMARY.md`, commit, and push.
