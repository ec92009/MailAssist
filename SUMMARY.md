# Summary

MailAssist has a clearer north star now: build something useful for Magali.

Magali is a CPA in San Diego, runs her own business, prefers Windows, and gets business email in Outlook Desktop. The first useful version does not need to be commercial-grade software. It needs to create safe, useful drafts in the mail client she already uses, without forcing her through developer consoles or confusing setup.

## Current Product Shape

- MailAssist is a local background drafting assistant.
- The bot watches mail, classifies new threads, creates provider-native drafts only when a reply is useful, and never sends email.
- The user reviews, edits, sends, or deletes drafts in the normal mail client.
- Gmail/mock work today and are useful for local testing.
- Mac/Gmail is the proving ground, not the destination.
- Windows/Outlook is the more important product target.
- The GUI is a compact control panel for setup, bot status, logs, and recent activity, not a second inbox.

## North-Star Implications

- Do not over-invest in Google OAuth verification unless it teaches something reusable or becomes necessary for broader testing.
- Do not treat Mac/Gmail packaging as the main distribution goal.
- Move Windows/Outlook research and implementation earlier.
- The immediate Outlook blocker is learning Magali's actual account type.
- Possible Outlook account paths include Microsoft 365/Exchange, Outlook.com, IMAP/SMTP, Gmail/Google Workspace inside Outlook, or another provider.
- If her account is Microsoft-hosted, Microsoft Graph is likely the preferred API.
- If her account is IMAP/SMTP, we need to evaluate direct IMAP/SMTP drafting versus Outlook local automation.

## Magali Research Request

We drafted instructions for Magali to screenshot Outlook account settings:

- Classic Outlook: `File` > `Account Settings` > `Account Settings...` > `Email` tab.
- New Outlook: gear icon > `Accounts` > `Email accounts` > `Manage` next to the business account.
- The key field is account `Type`: for example `Microsoft Exchange`, `Microsoft 365`, `IMAP/SMTP`, `POP/SMTP`, or similar.
- A second screenshot of the Outlook left sidebar showing distinct mailboxes/accounts would help.
- She should blur passwords, security codes, private content, and anything sensitive.

## Gmail And LLM Findings

- Mock-to-Gmail draft creation works end to end.
- Gmail read-only inbox preview works.
- Gmail send-as settings can provide a candidate signature for MailAssist settings.
- `gemma4:31b` is installed locally and works through MailAssist.
- Ollama calls send `think: false`, which prevents visible thinking text and lets larger local models complete cleanly.
- The synchronous Ollama timeout is 300 seconds so larger local models can complete.
- Batch-size 5 and 10 both created 11 Gmail drafts from sanitized mock mail in about 150 seconds end to end.
- Batch-size 10 is useful for backlog catch-up, but live watching should prefer one-at-a-time drafting so the first actionable email gets a draft as soon as possible.
- Ollama remains a useful dependency because it handles model download, storage, runtime, Metal/GPU use, model switching, and local API plumbing.

## Prompt And Safety State

- Generated provider drafts include a short review context block quoting recent incoming text.
- Review context timestamps use local, readable wording such as `yesterday afternoon at 14:09`.
- The prompt forbids invented teams, reviewers, companies, calendars, approvals, availability, and internal processes.
- The prompt warns against promise-shaped language such as `I will call`, `I will check`, `I will follow up`, or `I'll let you know` unless the user already made that exact commitment.
- The bot post-checks generated draft bodies and replaces signature-only or promise-shaped replies with a conservative acknowledgement.
- MailAssist creates drafts only; it does not send email.

## GUI State

- The native `PySide6` app is centered on setup, bot controls, recent activity, and logs.
- Settings open on first run and collapse after completion.
- The setup wizard saves at each step.
- The wizard covers provider, model, tone, signature, optional advanced settings, and final review.
- The model page can refresh Ollama models, show local model size and local modified/downloaded age, and send a small visible test prompt.
- The signature page can start from Gmail's send-as signature when available.
- Logs are human-readable by default, with a timeline/summary view and raw JSONL fallback.
- The app copy should stay honest: this is a bot control panel, not an email review inbox.

## Packaging State

- `packaging/macos/` contains the Mac/Gmail release build scripts.
- The release build creates `MailAssist.app`, a release folder, and `MailAssist-vX.Y-mac-gmail.dmg`.
- `dist/` remains ignored; generated app/package files should not be committed.
- `dist/MailAssist-v56.46-mac-gmail.dmg` was uploaded as a GitHub release asset.
- The README links to the GitHub release asset and explains the macOS unsigned-app override.
- Windows packaging/signing now matters more than Mac notarization for the north-star path.

## Docs State

- `NORTH_STAR.md` captures the Magali-centered product compass.
- `TODO.md` is now prioritized around Windows/Outlook first, Mac/Gmail as sandbox.
- `STRATEGY.md` reflects Outlook/Windows as the destination and Gmail/Mac as the current proving ground.
- `README.md` describes the Mac/Gmail build as the current sandbox preview.
- `RESEARCH.md` tracks the Outlook account-type question as the immediate provider research blocker.
- `RESULTS.md` reflects the current verified Mac/Gmail state and the new priority shift.

## Current Version And Tests

- Latest visible version: `v56.46`.
- Latest verified suite: 61 passing tests on April 25, 2026.
- Confirmed local test machine from Apple order email: 16-inch MacBook Pro, M1 Max, 10-core CPU, 24-core GPU, 32GB unified memory, 2TB SSD.

## Next Moves

- Commit and push the refreshed north-star docs.
- While waiting for Magali's Outlook account-type screenshot, clean up architecture that benefits both Gmail and Outlook.
- First cleanup target: move mock thread fixtures out of `gui.server` into a dedicated fixtures module and update imports without changing behavior.
- After Magali replies, choose the Outlook provider strategy and start Windows/Outlook implementation.

Project workflow shorthand:

- `rscp` means: refresh docs, summarize the current conversation to `SUMMARY.md`, commit, and push.
