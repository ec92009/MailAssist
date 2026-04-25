# Research

## Provider Watching

Open questions:

- Gmail: polling interval vs push notifications.
- Gmail: which query best finds actionable new mail without reprocessing old threads.
- Gmail: how to detect whether the user already replied manually.
- Gmail: how aggressively to import the Gmail send-as signature into MailAssist settings.
- Outlook: Microsoft Graph delta queries vs periodic polling.
- Outlook: required permissions for read + draft creation.
- Mock provider: how closely it should mimic provider IDs, thread updates, and duplicates.

Current Gmail research checkpoint:

- Safe Gmail tests keep sanitized mock emails as input and create Gmail drafts only, never sends.
- Controlled mock-to-Gmail draft creation has been validated.
- Gmail read-only inbox preview has been validated.
- Gmail send-as settings can be queried to obtain a signature candidate for the local signature setting.
- Batch-size 5 and 10 have been tested against Gmail draft creation with `gemma4:31b`.
- The next real-mail step is a conservative Gmail watcher that deduplicates, classifies, and drafts only when the thread clearly needs a reply.
- The project now has two setup PDFs for the Google Cloud/OAuth steps because the Google Console is dense enough to need explicit navigation cues.

## Deduplication

The bot needs a small durable record of provider work already handled.

Research decisions:

- Use provider thread ID as the primary key where possible.
- Include latest message ID or history ID so changed threads can be reconsidered.
- Store draft-created provider IDs to avoid duplicate drafts.
- Detect user-sent replies so future versions can mark items complete without watching our own GUI state.

## Classification

The classification only needs to answer product questions:

- Should MailAssist draft a reply?
- Is it urgent enough to process first?
- Should it be ignored as automated, spam, newsletter, digest, or no-response?

Candidate labels:

- `urgent`
- `reply_needed`
- `no_response`
- `automated`
- `spam`

Only `urgent` and `reply_needed` create drafts.

## Draft Generation

Research should compare one-draft prompts across the configured tone options:

- `Direct and concise`
- `Warm and collaborative`
- `Formal and polished`
- `Brief and casual`

Questions to answer:

- Should classification and drafting happen in one prompt or two?
- Is one prompt cheaper and reliable enough?
- Does the model produce better drafts if tone, signature, and provider context are separated into clear sections?
- How often does the model invent facts under each tone?

Latest findings:

- `gemma4:31b` is higher quality than the earlier small-model tests once Ollama thinking output is disabled.
- `think: false` is required for clean MailAssist output with this model.
- The model can still invent soft process details like `team` or promise-shaped user actions, so prompt rules need a post-generation guard.
- Batch-size 10 is not materially faster end to end than batch-size 5 for the current 11-email mock set; both are around 150 seconds including Gmail draft creation.
- Live watching should not delay draft creation while waiting for a batch. Batching is a backlog/catch-up tool.

## GUI Scope

The GUI should be a control panel, not a review inbox.

Useful views to keep:

- connection status
- bot running/paused
- last acquisition pass
- recent drafts created
- skipped counts by classification
- error list
- human-readable logs window with raw JSONL fallback
- first-run setup wizard
- compact settings reopen path after setup

Avoid large empty descriptions; the app is an operational tool.

## Packaging

Mac/Gmail is the first packaging target.

Research decisions:

- Build a native `.app` with PyInstaller.
- Wrap the app and setup PDFs in a `.dmg`.
- Do not commit the `.dmg` to git; `dist/` stays ignored.
- Upload the `.dmg` as a GitHub Releases asset. GitHub release assets support files under 2 GiB, which is enough for the current roughly 253 MB DMG.
- The README should link to `releases/latest/download/MailAssist-vX.Y-mac-gmail.dmg` and explain the Releases-page fallback.
- The preview app is ad-hoc signed but not notarized yet, so README instructions include the current macOS Privacy & Security override path for unsigned apps.

## Success Criteria

MailAssist is useful if:

- drafts are waiting in Gmail/Outlook before the user gets to the thread
- the drafts are usually grounded and editable
- the bot skips non-response mail quietly
- the user trusts that nothing is sent automatically
- the GUI makes status and failures easy to inspect
