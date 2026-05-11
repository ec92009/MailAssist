# MailAssist Codex Review 2026-05-10

Timestamp: 2026-05-10 02:04 CEST

1/ General architecture:

- MailAssist has a healthy package layout and test suite, but `gui/desktop.py` is over 3,800 lines and should be split before more Outlook setup and supervision UI lands.
- Provider abstractions exist, but Outlook still has several intentionally unimplemented paths. The provider contract should make capability differences explicit instead of surfacing late `NotImplementedError` branches.

2/ UI:

- The desktop app needs stronger operations panels: provider health, model health, last acquisition pass, last draft decision, next retry, and latest provider write.
- Settings and supervision views should make "safe to start bot" versus "blocked by setup" visually unambiguous.

3/ UX:

- The north-star Windows/Outlook path is well documented. Turn more of that setup into `doctor` checks that say exactly what is missing and how to fix it.
- Draft decisions should remain auditable for non-technical users: why skipped, why drafted, model used, provider write id, and retry status.

4/ Testing:

- Tests are a strength here. Add shared provider contract fixtures that run against mock/Gmail/Outlook capabilities and assert each provider advertises unsupported operations clearly.
- Add prompt regression fixtures for skip, draft, uncertain, dangerous-content, and provider-error examples so model/prompt changes do not silently shift behavior.

5/ Everything else:

- Keep the archived critique documents historical, but fold accepted items into `TODO.md` so daily work starts from one list.
- The README release link is concrete; add a release verification checklist so package/version drift is caught before publishing.

6/ My suggetions:

1. Split `src/mailassist/gui/desktop.py` into settings, status, review, and setup modules.
2. Add provider capability metadata and shared contract tests for mock, Gmail, and Outlook.
3. Extend `mailassist doctor` for Outlook prerequisites and local Ollama/model readiness.
4. Add an append-only audit log for decisions, provider writes, retries, and errors.
5. Add prompt/version regression fixtures for the highest-risk drafting decisions.
