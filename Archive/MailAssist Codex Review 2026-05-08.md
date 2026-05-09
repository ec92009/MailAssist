# MailAssist Codex Review 2026-05-08

Generated: 2026-05-08 00:00 Europe/Madrid

1/ General architecture

- MailAssist has the strongest modular shape of the reviewed repos: provider interfaces, GUI, runtime, config, drafting, and tests are already separated. The main architecture risk is provider behavior drift between Gmail, Outlook, and mock implementations.
- Keep all provider writes behind explicit contracts and state transitions. Draft creation, skip decisions, retry logic, and provider-native IDs should be modeled as auditable events, not incidental side effects.

2/ UI

- The desktop supervision GUI should stay operational rather than becoming a mail client. Its job is to show connection health, model health, last actions, blocked drafts, and safe controls.
- Add clearer "what happened recently" surfaces: latest scanned message, decision, draft result, provider error, and next retry time.

3/ UX

- The product direction is appropriately conservative: draft only, never send. The remaining UX challenge is trust calibration. Users need quick answers to "why did it draft this?" and "why did it skip that?"
- Setup remains a major friction point, especially Outlook/Windows. Keep reducing setup to checklists, validation buttons, and actionable error text.

4/ Testing

- The test suite is comparatively healthy. The next layer should be contract tests that run the same cases against mock, Gmail adapter fakes, and Outlook adapter fakes.
- Add regression tests for duplicate draft prevention, provider pagination, token refresh failures, and retry/backoff behavior.

5/ Everything else

- Docs are extensive. Keep pruning archived paths from the active README so new users do not confuse historical review-queue direction with the current background drafting direction.
- Treat local LLM prompts as product code: version prompt templates and keep before/after decision fixtures.

6/ My suggetions:

1. Add provider contract tests that exercise identical scan, classify, draft, and skip flows across adapters.
2. Add an auditable event log model for decisions, provider writes, retries, and user-visible status.
3. Improve GUI status panels around last action, provider health, model health, and next retry.
4. Add prompt/version fixtures for "needs reply", "skip", and "uncertain" examples.
5. Continue simplifying Outlook setup with validation commands and exact remediation messages.
