# Research

## Provider Watching

Open questions:

- Gmail: first validate one controlled draft write from mock input before adding real inbox polling.
- Gmail: polling interval vs push notifications.
- Gmail: which query best finds actionable new mail without reprocessing old threads.
- Gmail: how to preserve thread reply metadata when creating a draft.
- Gmail: how to detect whether the user already replied manually.
- Outlook: Microsoft Graph delta queries vs periodic polling.
- Outlook: required permissions for read + draft creation.
- Mock provider: how closely it should mimic provider IDs, thread updates, and duplicates.

Current Gmail research checkpoint:

- The first safe Gmail test keeps mock emails as input and creates one Gmail draft for `thread-008`.
- The test uses the Gmail compose scope and should create a draft only, not send mail.
- The next real-mail step uses Gmail readonly access for metadata/snippet preview before any drafting.
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

## GUI Scope

The GUI should be a control panel, not a review inbox.

Useful views to test:

- connection status
- bot running/paused
- last acquisition pass
- recent drafts created
- skipped counts by classification
- error list
- logs window
- settings modal

Avoid large empty descriptions; the app is an operational tool.

## Success Criteria

MailAssist is useful if:

- drafts are waiting in Gmail/Outlook before the user gets to the thread
- the drafts are usually grounded and editable
- the bot skips non-response mail quietly
- the user trusts that nothing is sent automatically
- the GUI makes status and failures easy to inspect
