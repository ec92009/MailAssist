# MailAssist Codex Review 2026-05-09

Generated: 2026-05-09 00:00 Europe/Madrid

1/ General architecture

- MailAssist has the healthiest modular shape in this set: providers, runtime, config, drafting, GUI, and tests are separated. The main risk is behavior drift between Gmail, Outlook, and mock providers.
- Keep all provider writes behind explicit contracts. Draft creation, skips, retries, provider IDs, and user-visible state should be evented and auditable rather than incidental side effects.

2/ UI

- The desktop GUI should remain an operations console, not a full mail client. Prioritize provider health, model health, last scan, last decision, blocked draft, and next retry.
- Make recent activity easier to scan: what message was inspected, why it drafted or skipped, what provider action happened, and what needs human attention.

3/ UX

- The conservative draft-only product stance is correct. Trust now depends on explaining decisions quickly: "why this draft" and "why this skip" should be first-class.
- Setup friction, especially Outlook/Windows, remains a product risk. Keep converting docs into validation commands and exact remediation messages.

4/ Testing

- The test suite is strong compared with most sibling repos. Add provider contract tests that run the same scan/classify/draft/skip cases against mock, Gmail fake, and Outlook fake adapters.
- Add regressions for duplicate draft prevention, pagination, token refresh failure, retry/backoff, and provider-native ID persistence.

5/ Everything else

- Archived historical directions are extensive. Keep the active README focused on the current background drafting workflow so old queue terminology does not confuse setup.
- Treat prompts as product code: version them and keep before/after fixtures for representative decisions.

6/ My suggetions:

1. Add provider contract tests shared by mock, Gmail, and Outlook adapters.
2. Introduce an auditable event log for decisions, provider writes, retries, and status.
3. Improve GUI panels for last action, provider health, model health, and next retry.
4. Add prompt/version fixtures for draft, skip, uncertain, and provider-error examples.
5. Continue turning Outlook setup docs into validation scripts with exact fixes.
