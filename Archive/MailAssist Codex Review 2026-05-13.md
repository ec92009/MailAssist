# MailAssist Codex Review 2026-05-13

Reviewed: 2026-05-13

1/ General architecture

- MailAssist has a relatively strong package structure under `src/mailassist`, with provider, runtime, drafting, config, GUI, model, and review-state boundaries.
- The product direction is clear: provider-native drafts, no automatic sending, Gmail/Mac proving ground, Outlook/Windows north star.
- `bot_runtime.py`, `background_bot.py`, `review_state.py`, and provider implementations are the core contracts; keep them strict so Outlook does not become a Gmail fork.
- The docs are broad. The next architecture aid should be a concise system diagram plus a provider contract document.

2/ UI

- The desktop UI should remain focused on setup, supervision, readiness, and logs rather than duplicating Gmail or Outlook.
- The GUI is already treated as important through desktop layout tests, which is a healthy sign.
- Key status should stay visible: provider readiness, model readiness, last checked message, last draft result, and pause/resume state.
- Setup errors should be framed as actionable checks, not raw stack traces or buried logs.

3/ UX

- The trust posture is strong because MailAssist drafts but does not send.
- First-run setup is still the largest UX burden: OAuth, provider permissions, Ollama, model selection, and safe test-draft creation.
- Users need clear reasoning for skipped messages and created drafts so the bot feels reviewable rather than mysterious.
- A successful first run should mean provider connected, model reachable, dry-run passed, and one safe test draft created or explicitly skipped.

4/ Testing

- The suite is stronger than most repos here, covering runtime, providers, config, contacts, desktop layout, model client, and review state.
- The next gap is end-to-end dry-run coverage using fake provider messages and fake model responses.
- Provider contract tests should remain mandatory for Gmail, Outlook, and mock providers.
- Windows/Outlook smoke coverage should be added once that path becomes active.

5/ Everything else

- Keep `.env` and credentials out of Git; `.env.example` and readiness docs should track required values.
- README/release/version consistency should be automated because the project has visible release expectations.
- Convert repeated manual setup guidance into in-app readiness checks wherever possible.

6/ My suggetions:

1. Add an in-app readiness checklist for provider auth, Ollama, model selection, permissions, and safe test draft.
2. Add an end-to-end dry-run test with fake provider messages and fake model output to prove idempotent draft creation.
3. Keep expanding provider contract tests so Gmail, Outlook, and mock providers share behavior.
4. Add a README/release/package version consistency check.
5. Create a concise architecture diagram covering runtime loop, provider boundary, model boundary, and draft safety.
6. Keep UI scope focused on setup, status, supervision, and logs.
