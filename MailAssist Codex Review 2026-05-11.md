# MailAssist Codex Review 2026-05-11

Review time: 2026-05-11 02:05 CEST.

1/ General architecture

- The current architecture is well-framed: a local background bot classifies mail, drafts provider-native replies, and leaves send/delete control to the user.
- Provider boundaries are the key asset. Gmail/mock/Outlook code should remain behind a small contract so the drafting loop does not learn provider-specific behavior.
- The north-star Windows/Outlook direction is documented clearly; avoid letting Mac/Gmail packaging decisions leak into the product center.

2/ UI

- The GUI's role should stay supervisory: connection status, bot state, last action, draft count, logs, and clear stop/start controls.
- Any provider-write state needs unambiguous labels. "Draft created" should be visibly different from "sent" or "ready to send."
- Setup screens should reflect the Windows/Outlook target even while the Mac/Gmail sandbox remains useful.

3/ UX

- The no-send safety posture is the core trust feature and should be repeated wherever users configure or review behavior.
- One-at-a-time first-draft latency is the right UX default; backlog catch-up should be explicit and bounded.
- First-run setup still depends on external OAuth/Entra/Ollama steps. The runbooks are good, but the app should surface readiness failures in plainer language.

4/ Testing

- This repo has a comparatively healthy test suite: config, provider contracts, runtime, CLI, models, Outlook/Gmail providers, and layout tests were detected.
- Next coverage should focus on cross-provider invariants: same input message, same draft-intent decision, provider-specific draft write adapter.
- Add tests for refusal/safety behavior around sensitive emails, missing recipients, broken OAuth, and provider rate/permission errors.

5/ Everything else

- Documentation is deep and current, but there are many planning files. README should stay the outsider entrypoint and link to deeper docs by task.
- Keep `.env` handling strict; no logs or test fixtures should expose real inbox data.
- Release artifact links in README should be checked as part of release work so stale DMG links do not become support traps.

6/ My suggetions:

1. Add provider-contract tests that run the same drafting scenario against mock Gmail and mock Outlook adapters.
2. Add app-visible readiness diagnostics for Ollama, OAuth/Entra credentials, model availability, and provider permissions.
3. Add safety regression tests proving MailAssist never sends email and only creates drafts.
4. Tighten README around the current "best path" for a new user: Mac/Gmail sandbox vs Windows/Outlook target.
5. Add a compact operations page showing recent classifications, skipped messages, drafts created, and last provider error.
