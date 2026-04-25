# Summary

MailAssist has now proven the local-LLM to Gmail-draft loop with `gemma4:31b`, including real Gmail draft creation from sanitized mock threads.

The product thesis is sharper: the bot exists to hide local LLM latency by preparing provider-native drafts in the background. The user still reviews, edits, sends, or deletes drafts in Gmail or Outlook. MailAssist must not send email.

## Current Product Shape

- The bot watches Gmail, Outlook, or mock input.
- The bot classifies new or changed messages.
- The bot skips mail that does not need a reply.
- The bot generates one draft using the user's configured tone and signature.
- The bot creates that draft in the source provider when appropriate.
- Gmail/Outlook remain the review and editing surfaces.
- The GUI configures and supervises the bot.

## Latest Gmail And LLM Findings

- Mock-to-Gmail draft creation works end to end.
- `gemma4:31b` is installed locally and works through MailAssist.
- Ollama calls now send `think: false`, which prevented visible thinking text and changed `gemma4:31b` from timing out to completing single-email drafts in roughly 14-20 seconds.
- The synchronous Ollama timeout is now 300 seconds so larger local models can complete.
- Batch-size 5 and 10 both created 11 Gmail drafts from sanitized mock mail in about 150 seconds end to end.
- Batch-size 10 is useful for backlog catch-up, but live watching should prefer batch size 1 so the first actionable email gets a draft as soon as possible.
- Gmail OAuth has both compose and readonly scopes.
- Real Gmail inbox preview has been tested without creating drafts or sending mail.

## Prompt And Safety State

- Generated provider drafts now include a short review context block quoting up to the last two incoming messages.
- Review context timestamps use local, readable wording such as `yesterday afternoon at 14:09`.
- The prompt forbids invented teams, reviewers, companies, calendars, approvals, availability, and internal processes.
- The prompt warns against promise-shaped language such as `I will call`, `I will check`, `I will follow up`, or `I'll let you know` unless the user already made that exact commitment.
- The bot now post-checks generated draft bodies and replaces signature-only or promise-shaped replies with a conservative acknowledgement: `Thanks for the note. I am reviewing this.`
- The open-house mock case no longer invents a team.
- The utility-company mock case no longer lets the model promise to make calls on the user's behalf.

## Current Code Reality

- `watch-once` can target a provider instead of being mock-only.
- `watch-once` accepts `--batch-size`, but the preferred live default remains one-at-a-time processing.
- The Gmail provider can create drafts with `To`, `Cc`, and `Bcc` headers from `DraftRecord`.
- `DraftRecord` carries recipient fields.
- The mock watch pass can filter to one thread and route generated drafts to either mock or Gmail providers.
- Gmail provider work includes a read-only inbox preview path for recent messages.
- The local virtualenv has Gmail optional dependencies installed.
- Additional sanitized mock emails now cover real-estate, title, travel, and decision/request cases.
- Runtime Gmail test drafts are created and deleted manually during experiments; they are not committed.

## Docs Added

- `docs/setting_up_gmail_connection_for_MailAssist.pdf`: beginner-oriented Gmail connection setup guide.
- `docs/gmail_oauth_advanced.pdf`: more detailed OAuth/Desktop-client setup reference.
- The guides include practical Google Cloud Console navigation hints such as top project picker, left-column menu, OAuth Overview, bottom Save/Continue buttons, and Credentials flow.

## Desired Next Code Direction

- Keep live Gmail mode focused on first-draft latency: process actionable arrivals immediately, usually batch size 1.
- Use batching only for backlog catch-up, import, first-install processing, or when multiple emails are already waiting at the same polling tick.
- Add read-only classification for real Gmail inbox previews before real-email draft creation.
- Add Gmail inbox/thread polling after the read-only preview and classification path looks trustworthy.
- Keep the GUI compact and focused on provider status, bot state, settings, recent activity, and logs.

## Current Version And Tests

- Latest visible version: `v56.10`.
- Latest verified suite: 51 passing tests.
- Confirmed local test machine from Apple order email: 16-inch MacBook Pro, M1 Max, 10-core CPU, 24-core GPU, 32GB unified memory, 2TB SSD.

Project workflow shorthand:

- `rscp` means: refresh docs, summarize the current conversation to `SUMMARY.md`, commit, and push.
