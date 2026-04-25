# Summary

MailAssist has moved from a local review-inbox experiment to a compact Mac/Gmail background drafting app.

The product thesis is stable: local LLMs can be slow, so MailAssist should do the slow work before the user asks for it. The bot watches mail, classifies new threads, creates provider-native drafts only when a reply is useful, and never sends email. Gmail remains the first review/edit/send surface; Outlook comes later.

## Current Product Shape

- The bot watches Gmail or mock input.
- The bot classifies new or changed messages.
- The bot skips mail that does not need a reply.
- The bot generates one draft using the user's configured tone.
- The bot appends or uses the configured signature outside the model response.
- The bot creates that draft in Gmail when appropriate.
- Gmail remains the review and editing surface.
- The GUI configures and supervises the bot.
- The GUI is a compact control panel, not a second inbox.

## Gmail And LLM Findings

- Mock-to-Gmail draft creation works end to end.
- Gmail read-only inbox preview works.
- Gmail send-as settings can provide a candidate signature for MailAssist settings.
- `gemma4:31b` is installed locally and works through MailAssist.
- Ollama calls send `think: false`, which prevents visible thinking text and lets larger local models complete cleanly.
- The synchronous Ollama timeout is 300 seconds so larger local models can complete.
- Batch-size 5 and 10 both created 11 Gmail drafts from sanitized mock mail in about 150 seconds end to end.
- Batch-size 10 is useful for backlog catch-up, but live watching should prefer one-at-a-time drafting so the first actionable email gets a draft as soon as possible.
- Current README model suggestions are RAM-based and linked to Ollama model pages.

## Prompt And Safety State

- Generated provider drafts include a short review context block quoting recent incoming text.
- Review context timestamps use local, readable wording such as `yesterday afternoon at 14:09`.
- The prompt forbids invented teams, reviewers, companies, calendars, approvals, availability, and internal processes.
- The prompt warns against promise-shaped language such as `I will call`, `I will check`, `I will follow up`, or `I'll let you know` unless the user already made that exact commitment.
- The bot post-checks generated draft bodies and replaces signature-only or promise-shaped replies with a conservative acknowledgement.
- MailAssist creates drafts only; it does not send email.

## GUI State

- The native `PySide6` app is now centered on setup, bot controls, recent activity, and logs.
- Settings open on first run and collapse after completion.
- The setup wizard saves at each step.
- The wizard covers provider, model, tone, signature, optional advanced settings, and final review.
- The model page can refresh Ollama models, show local model size and local modified/downloaded age, and send a small visible test prompt.
- The signature page can start from Gmail's send-as signature when available.
- Logs are human-readable by default, with a timeline/summary view and raw JSONL fallback.
- The main window should stay stable in size and avoid unnecessary scroll/rake-garden behavior.

## Packaging State

- Mac/Gmail is the first downloadable target.
- `packaging/macos/` contains release build scripts.
- The release build creates `MailAssist.app`, a release folder, and `MailAssist-vX.Y-mac-gmail.dmg`.
- The packaged app stores settings, tokens, logs, and runtime files under `~/Library/Application Support/MailAssist/`.
- `dist/` remains ignored; generated `.app` and `.dmg` files should not be committed.
- The current local DMG is `dist/MailAssist-v56.46-mac-gmail.dmg`, about 253 MB.
- The README now links to the GitHub Releases asset URL for the DMG and keeps a Releases-page fallback.
- The preview app is ad-hoc signed but not notarized yet, so README instructions explain the current macOS Privacy & Security override.

## Docs State

- `README.md` now has GitHub download guidance, DMG install notes, RAM/model recommendations, and Apple unsigned-app links.
- `docs/setting_up_gmail_connection_for_MailAssist.pdf` is the beginner Gmail connection guide.
- `docs/gmail_oauth_advanced.pdf` is the detailed OAuth/Desktop-client setup reference.
- `STRATEGY.md`, `REALISM.md`, `RESEARCH.md`, `RESULTS.md`, and `TODO.md` reflect the lighter background-bot direction.
- Historical docs from the heavier review-queue direction are archived under `archived/2026-04-24-pre-background-bot/`.

## Current Version And Tests

- Latest visible version: `v56.46`.
- Latest verified suite: 61 passing tests on April 25, 2026.
- Confirmed local test machine from Apple order email: 16-inch MacBook Pro, M1 Max, 10-core CPU, 24-core GPU, 32GB unified memory, 2TB SSD.

## Next Moves

- Commit and push the refreshed docs and implementation.
- Create the GitHub `v56.46` release and upload `dist/MailAssist-v56.46-mac-gmail.dmg` so the README direct download link works.
- Continue toward real Gmail polling/drafting with deduplication and conservative safety checks.
- Research notarization/signing before wider Mac distribution.
- Add Windows packaging and Outlook support after Mac/Gmail is stable.

Project workflow shorthand:

- `rscp` means: refresh docs, summarize the current conversation to `SUMMARY.md`, commit, and push.
