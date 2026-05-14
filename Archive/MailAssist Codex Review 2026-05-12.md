# MailAssist Codex Review 2026-05-12

Reviewed: 2026-05-12

1/ General architecture

- MailAssist has a solid package structure under `src/mailassist`, with providers, runtime, drafting, config, models, and review state separated better than most early desktop tools.
- The product direction is clear: provider-native drafts, no automatic sending, Mac/Gmail proving ground, Windows/Outlook north-star.
- `bot_runtime.py`, `background_bot.py`, and `review_state.py` are the architectural core. Keep provider boundaries strict so Outlook does not become a fork of Gmail behavior.
- The docs are extensive. The next architecture improvement is a concise system diagram and provider contract document for onboarding.

2/ UI

- The GUI is positioned as supervision/configuration rather than the mail review surface, which is the right scope.
- Desktop layout tests already exist, suggesting UI behavior is being treated as product-critical.
- The UI should continue to surface model/provider readiness, last processed message, last draft result, and safe pause/resume controls.
- Avoid adding inbox-review features that duplicate Gmail or Outlook unless they directly reduce setup/support friction.

3/ UX

- The product’s trust posture is strong: it creates drafts only and leaves send control to the user.
- Setup remains the largest UX burden. OAuth, Ollama, provider permissions, and Windows/Outlook readiness need one guided checklist in the app, not only docs.
- Users need unambiguous skip/draft reasoning so they can understand why a message did or did not get a reply.
- First-run success should be measured as "connected provider, model reachable, test draft created safely."

4/ Testing

- This repo has a relatively strong test suite covering runtime, providers, config, contacts, desktop layout, models, and review state.
- The next gap is end-to-end dry-run coverage that exercises provider polling, classification, draft generation, duplicate prevention, and logging with fake providers.
- Add contract tests that every provider must pass, especially around idempotency and native draft creation.
- Add Windows/Outlook-specific smoke tests once the north-star path is active.

5/ Everything else

- `.env` exists locally; make sure no secrets are tracked and `.env.example` stays current.
- The README still points to a release version that may drift from current `pyproject.toml`; automate that consistency check.
- The project has strong SOP coverage. Convert repeated manual setup steps into app checks where possible.

6/ My suggetions:

1. Add an in-app readiness checklist for provider auth, Ollama availability, model selection, and safe test-draft creation.
2. Create a provider contract test suite that Gmail, Outlook, and mock providers must all pass.
3. Add an end-to-end dry-run test using fake provider messages and a fake model response to prove idempotent draft creation.
4. Add a README/release consistency check so visible version, release links, and package version cannot drift silently.
5. Write a concise architecture diagram covering runtime loop, provider boundary, model boundary, and draft safety rules.
6. Keep UI scope focused on setup, status, supervision, and logs rather than building a competing inbox.
