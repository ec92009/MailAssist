# Summary

MailAssist is being simplified into a background draft creator.

The reason for the bot is latency: the local LLM can take around a minute to draft a useful reply. That work should happen before the user needs it. The bot should watch inboxes continuously, classify new mail, and create provider-native draft replies only for messages that need a response.

## Current Product Shape

- The bot watches Gmail, Outlook, or mock input.
- The bot classifies new messages or changed threads.
- The bot skips mail that does not need a reply.
- The bot generates one draft using the user's configured tone and signature.
- The bot creates that draft in Gmail or Outlook.
- The user edits, sends, or deletes the draft in the mail client.
- The GUI configures the bot and shows status, activity, and logs.

## What Changed In Thinking

The earlier review-inbox direction was too heavy. It created a second place to inspect, edit, approve, ignore, and archive mail. That is not the core value.

The lighter model is:

- MailAssist does slow LLM work in the background.
- Gmail/Outlook remain the review UI.
- The GUI becomes a compact control panel.
- The bot should do one thing well: keep useful drafts ready.

## Current Code Reality

- The repo still contains the earlier desktop review prototype.
- The repo has a first bot queue scaffold in `src/mailassist/bot_queue.py`.
- The bot can run `queue-status`.
- The bot can run `process-mock-inbox`.
- The bot can now run `watch-once --provider mock`, which skips automated/no-response mock mail and creates one mock provider draft per actionable thread.
- The visible desktop app has been reshaped into a compact bot control panel.
- Settings now include preferred tone and polling interval near the user signature.
- Runtime lifecycle folders exist, but they are not the intended long-term center unless they prove necessary.
- Docs from the heavier direction are archived under `archived/2026-04-24-pre-background-bot/`.

## Desired Next Code Direction

- Continue simplifying the GUI around bot health, settings, recent activity, and logs.
- Move draft review/editing out of MailAssist and into Gmail/Outlook.
- Turn the one-pass mock watcher into a continuous loop with pause/resume.
- Bring Gmail into the same watch/classify/draft contract.
- Keep logs and recent activity visible.

## Current Version And Tests

- Latest version after the first simplified redesign pass: `v55.34`.
- Latest verified suite after the first simplified redesign pass: 34 passing tests.

Project workflow shorthand:

- `rscp` means: refresh docs, summarize the current conversation to `SUMMARY.md`, commit, and push.
