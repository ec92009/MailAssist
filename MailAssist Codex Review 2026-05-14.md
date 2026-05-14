# MailAssist Codex Review 2026-05-14

Review timestamp: 2026-05-14, Europe/Madrid.

1/ General architecture

- The provider abstraction is now the project backbone, with Gmail, Outlook, mock providers, live watcher state, drafting, contacts, and GUI supervision separated reasonably well.
- The north-star Windows/Outlook direction is clear, while Mac/Gmail remains a practical proving ground.
- The legacy `review_state.py` path is still present for compatibility; keep preventing it from becoming the place new live-drafting logic lands.

2/ UI

- The desktop GUI appears to cover setup, provider status, watch controls, activity, and category management; that is the right surface for a non-technical user.
- Auth-expired and readiness states need to be impossible to miss, especially for Outlook/Graph.
- Confirmation dialogs for provider-writing actions are essential and should stay explicit about draft creation versus sending.

3/ UX

- The product promise is safe because MailAssist drafts but does not send; every workflow should reinforce that boundary.
- Windows bootstrap and Magali setup docs are strong, but the first-run path should stay as one guided checklist instead of scattered commands.
- Model readiness should continue to report RAM/model mismatch in user terms, not just subprocess failures.

4/ Testing

- The test suite is strong relative to other repos: provider contracts, Gmail, Outlook, bot runtime, CLI, contacts, and desktop layout are covered.
- Add more end-to-end dry-run/provider-writing boundary tests so "no send" remains enforced across future providers.
- Keep mock Graph and Gmail fixtures close to real provider payloads to catch schema drift.

5/ Everything else

- The release README references downloadable DMGs and model recommendations; those are time-sensitive and should be checked before each public release.
- Secrets/token paths are documented as ignored; keep periodic repo audits for accidental provider credentials.
- The project has many SOPs; a short operator index is more useful than expanding each file indefinitely.

6/ My suggetions:

1. Build a single first-run Windows/Outlook checklist that links to detailed SOPs only when needed.
2. Add a regression test that provider actions can create drafts but never send mail.
3. Keep new live-drafting logic out of legacy `review_state.py` and mark the replacement path in code comments/docs.
4. Add provider-token and secrets leak checks to the repo audit.
5. Add GUI tests for expired auth, missing model, provider not ready, and draft-created confirmation states.
6. Refresh release links/model recommendations before each public DMG update.
