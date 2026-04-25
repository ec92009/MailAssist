# Strategy

## Product Thesis

MailAssist exists because local LLMs are useful but slow.

The bot's job is to spend that minute before the user needs the answer. It should watch the inbox continuously, classify new mail, and pre-create provider-native draft replies for messages that need a response. The user's normal mail client remains the review and editing surface.

MailAssist should feel like a quiet local assistant that keeps Gmail or Outlook prepared, not like a second inbox the user has to manage.

## Core Workflow

1. The bot runs continuously on the user's machine.
2. It polls or watches connected providers: Gmail first, Outlook later, mock while developing.
3. It detects new or changed threads that have not already been handled.
4. It sends each candidate thread to the local LLM for classification.
5. If the thread does not need a response, the bot records that decision locally and does nothing else.
6. If the thread needs a response, the bot asks the local LLM for one draft in the user's selected tone.
7. The bot creates a draft in the source mail provider.
8. The user reviews, edits, sends, or deletes that draft in Gmail or Outlook.
9. The GUI shows configuration, bot health, recent activity, and logs.

Live watching should optimize for first-draft latency. If one actionable email arrives, draft it immediately instead of waiting for a batch. Batching is useful for backlog catch-up, import jobs, first-install processing, or an acquisition pass where several messages are already waiting at the same instant.

## What The Bot Owns

- Provider polling or watching.
- Deduplication of already-seen provider threads.
- Classification.
- Draft generation.
- Provider draft creation.
- Local logs and lightweight activity history.
- Retry/backoff for provider and Ollama failures.

The bot should be boring, persistent, and focused. It should not become a general workflow engine.

## What The GUI Owns

- Provider configuration and connection status.
- Ollama URL and local model selection.
- User signature.
- Preferred writing tone.
- Polling interval and run/pause controls.
- Bot logs, recent draft-created activity, and error visibility.

The GUI should not be a full email editor. Gmail and Outlook already do that well, and the user can edit drafts there before sending.

## Drafting Policy

- Generate one draft, not multiple options.
- Use the user's configured tone as the base style.
- Include the user's exact configured signature when appropriate.
- Stay grounded in the source thread.
- Never invent attachments, commitments, dates, approvals, prices, or prior context.
- Never invent teams, reviewers, vendors, calendars, internal processes, or availability.
- Do not promise the user will call, check, contact, confirm, update, or follow up unless the user already made that exact commitment in the thread.
- For requests that require a user decision, generate a safe holding reply and leave the final decision for the user to add.
- Do not draft for automated, spam, newsletter, digest, or no-response messages.
- Treat `urgent` as a priority signal, not as a separate user workflow.

## Tone Settings

The user should choose one default tone in settings. Initial tone options:

- `Direct and concise`
- `Warm and collaborative`
- `Formal and polished`
- `Brief and casual`

This replaces generating two candidate replies. If the draft is not quite right, the user edits it in the provider draft editor.

## Provider Boundary

MailAssist creates provider drafts. It does not send mail.

Provider writes should preserve:

- recipients
- cc/bcc when available
- thread/reply metadata
- subject
- provider draft ID
- provider thread/message IDs

Gmail is first. Outlook follows once the Gmail loop is stable.

## Local State

Keep local state small and explainable:

- provider cursor or last-seen IDs
- per-thread processing status
- classification result
- provider draft reference
- run logs
- recent activity summary for the GUI

Avoid a complex folder state machine unless real provider behavior forces it. A simple local state file plus logs is enough until proven otherwise.

## Model Posture

`gemma4:31b` is a promising quality model on the current M1 Max test machine. MailAssist should disable Ollama thinking output with `think: false`, allow enough timeout for slower local models, and expose model selection without allowing accidental model downloads from free-form names.

Single-email drafting latency around 14-20 seconds is acceptable for background watching. Batch sizes 5 and 10 are acceptable for throughput, but they should not become the default live behavior if they delay the first visible provider draft.

## Design Posture

- Optimize for low cognitive load.
- Prefer settings, status, and logs over a second inbox.
- Keep the UI dense and operational: little empty space, few subtitles, no decorative panels.
- Put generated drafts where the user already works: Gmail or Outlook.
- Make slow local LLM work visible but non-blocking.
