# MailAssist Codex Review 2026-05-06

Timestamp: 2026-05-06 02:02 CEST

## 1/ General architecture

- The provider-native draft boundary is the right architectural anchor: MailAssist should classify, draft, and supervise, but never send.
- Continue separating runtime activity, prompt construction, provider adapters, and GUI panels; recent file splits are moving in the right direction.
- Make the background bot state machine explicit: idle, polling, classifying, drafting, provider-write pending, provider-write complete, skipped, errored.
- Keep Outlook/Windows as a first-class target by avoiding macOS-only assumptions in core provider/runtime modules.

## 2/ UI

- The GUI should foreground bot health: provider connected, Ollama reachable, last poll, last draft, last error, and whether the bot is actively watching.
- Use clear status labels for "draft created in provider" vs. "no reply needed"; these are different kinds of success.
- Keep configuration surfaces compact and progressive; advanced OAuth/provider details should not crowd the normal supervision view.

## 3/ UX

- First-run setup needs a guided checklist for provider auth, Ollama install/model readiness, and a safe test message.
- Add an explainability panel for each draft decision: why it replied, why it skipped, which provider action occurred, and where the draft is now.
- Preserve the review loop in the user's mail client; avoid building a parallel inbox unless there is a very specific gap.

## 4/ Testing

- Expand contract tests across Gmail, mock, and Outlook adapters before adding more provider behavior.
- Add durable runtime tests for restart behavior, duplicate suppression, provider write failures, and Ollama unavailability.
- Keep GUI layout tests focused on visible health/config states rather than pixel-perfect snapshots.

## 5/ Everything else

- The docs are extensive; keep `RESULTS.md` and `TODO.md` as the active decision records and archive stale strategy branches quickly.
- Add a privacy/safety checklist near release packaging so "does not send email" remains visible in every user-facing build.
- Current uncommitted work is substantial; finish and push that cycle before layering more product changes.

## 6/ My suggetions:

1. Formalize the background bot state machine and expose it in the GUI.
2. Add provider contract tests for duplicate suppression, draft writes, auth errors, and no-send guarantees.
3. Build a first-run readiness checklist for Gmail/Outlook plus Ollama.
4. Add per-message decision explanations to logs and GUI activity.
5. Consolidate active docs around `RESULTS.md`, `TODO.md`, and the current Outlook readiness path.
