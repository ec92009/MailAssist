# Realism

## The Real Problem

Local models can take about a minute to draft a useful email. That is too slow for an on-click workflow, but acceptable for a background workflow.

MailAssist should therefore do slow work ahead of time. The bot earns its keep by making drafts available before the user opens the thread.

## Non-Negotiables

- The bot may create provider drafts.
- The bot must not send email.
- The user remains in Gmail or Outlook for final review, edits, and sending.
- The model must stay grounded in the provider thread.
- Generated drafts and logs may contain sensitive content and must stay out of git.
- Provider credentials and tokens must stay under ignored local paths.

## What We Should Not Build Yet

- A second inbox.
- A multi-stage review queue.
- Multiple draft candidates per message.
- A GUI email editor.
- A large file-moving workflow engine.
- A send automation path.

Each of those adds weight before the core value is proven.

## Provider Reality

Gmail and Outlook drafts are the correct user-facing artifact because:

- they preserve the user's normal review habit
- they allow rich editing without us rebuilding an editor
- they keep final send authority in the provider
- they make MailAssist useful even when the GUI is closed

The hard provider work is not the visual review loop. The hard provider work is reliable ingestion, deduplication, reply metadata, draft creation, auth refresh, and error handling.

## LLM Reality

Model behavior will vary by local machine and model. Some models may not stream partial output promptly, even when the HTTP API is technically streaming.

The UI should avoid pretending progress is exact. Use honest statuses:

- waiting for Ollama
- drafting
- draft created
- skipped because no reply is needed
- failed with retryable/non-retryable error

Some newer local models can expose thinking text unless explicitly disabled. MailAssist should send `think: false` to Ollama generation requests and should keep generation timeouts long enough for larger local models.

Prompting alone is not enough. If a generated draft is only a signature, or if it promises that the user will call, check, contact, confirm, update, or follow up without an existing user commitment, the bot should fall back to a conservative acknowledgement instead of writing that promise into Gmail.

Batching improves average throughput for backlogs, but it can hurt the user-visible moment that matters most: when the first draft appears. Live provider watching should usually draft one actionable email immediately and reserve batching for already-waiting backlogs.

## Privacy Reality

Local state will contain email content. Default posture:

- keep generated artifacts under `data/`
- ignore runtime JSON/log/draft files
- commit only sanitized samples and empty folder placeholders
- show logs locally, not through public hosting

## Audit Reality

The user does not need a heavy review queue, but they do need to understand what the bot did.

Keep a small activity trail:

- source provider
- subject/sender
- classification
- whether a draft was created
- provider draft ID
- model used
- error if any
- timestamps

That is enough to debug and trust the bot without turning the product into a case-management system.
