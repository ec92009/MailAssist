# MailAssist Codex Review 2026-05-05

Generated: 2026-05-05 10:36:54 CEST

1/ General architecture

- MailAssist has the strongest package shape among the reviewed repos: `src/mailassist`, provider contracts, state modules, drafting modules, tests, packaging, and operational docs.
- The core risk is that `background_bot.py` centralizes prompt construction, watch state, provider interaction, classification fallback, activity logging, and draft creation. It is readable, but it is becoming the system's dependency hub.
- Provider boundaries are a good asset. Keep Gmail and Outlook behavior behind contracts and resist provider-specific branches in orchestration code.

2/ UI

- The product direction says the provider mail client remains the review surface, which reduces UI burden. The app UI should stay focused on setup, model health, provider connection state, logs, and "what will MailAssist do next?"
- Add a concise status view for last poll, last draft created, skipped count, provider health, Ollama health, and current watch filters.

3/ UX

- The no-send safety posture is clear and should remain prominent. The next UX issue is trust calibration: users need to understand why a draft was created or skipped.
- Store a human-readable reason and prompt/model summary with each activity item, without exposing sensitive mail in logs by default.

4/ Testing

- Existing tests cover many foundations. Broaden around idempotency: same latest message, user replied, provider draft already exists, and provider transient failure.
- Add provider contract tests that both Gmail and Outlook adapters must pass.

5/ Everything else

- `.env` exists locally; make sure secret handling remains ignored and documented.
- Packaging docs are thorough. Add a release checklist that ties tests, version bump, DMG build, and release upload together.

6/ My suggetions:

1. Split `background_bot.py` into watcher orchestration, draft decisioning, prompt preview, and activity logging modules.
2. Add idempotency and transient-failure tests for `run_watch_pass`.
3. Add a live status dashboard panel for provider/Ollama/watch health.
4. Define a shared provider contract test suite.
5. Add a one-page release checklist linking version, tests, build, and GitHub release.
