# MailAssist Codex Review 2026-05-07

Reviewed at: 2026-05-07 00:00 Europe/Madrid

1/ General architecture:
- The provider/runtime/review-state split is a good direction, but `src/mailassist/gui/desktop.py` is carrying too much product behavior. Move non-visual state transitions into application services so Gmail, Outlook, and local review flows share one contract.
- Keep provider-write boundaries strict. Approval, draft generation, and provider mutation should remain separate layers with auditable handoffs.
- The runtime modules are testable, but the next architecture step is an explicit state machine for message intake, draft proposal, user approval, send/archive/defer, and error recovery.

2/ UI:
- The desktop UI needs progressive disclosure for operational complexity: inbox state, draft state, provider state, and approval state should be visually distinct.
- Add compact status chips for provider connection, sync freshness, pending approvals, and failed actions.
- Long review surfaces should favor scanability: sender, intent, proposed action, risk flag, and next button should be aligned consistently.

3/ UX:
- The product should make it impossible to confuse "drafted" with "sent". Keep a hard approval step and make provider-write outcomes explicit.
- Add recovery flows for stale provider tokens, deleted messages, provider rate limits, and send failures.
- Build a first-run/checkup workflow that validates credentials, mailbox read access, model availability, and write permissions before a user trusts automation.

4/ Testing:
- Existing test coverage is strong compared with most repos here. The gap is integration-style coverage for full review loops across providers with fake mailboxes.
- Add state-machine tests for edge cases: duplicate message ingestion, draft regeneration, provider errors after approval, and restart recovery.
- Add UI smoke tests for common review actions and layout snapshots for dense inbox states.

5/ Everything else:
- The strategy/realism/research docs are useful guardrails. Keep `TODO.md` pruned so implementation work starts from the current product decision, not old research.
- Review checked-in local artifacts such as `.env` and caches carefully; secrets and mailbox state should stay outside source history.
- Consider a lightweight audit log format that can be used both in tests and in real user troubleshooting.

6/ My suggetions:
1. Extract non-visual workflow state out of `src/mailassist/gui/desktop.py`.
2. Define and test an explicit review/approval state machine.
3. Add fake-provider integration tests for Gmail and Outlook loops.
4. Add provider/status chips and clearer failure recovery in the UI.
5. Create an audit-log contract for draft, approval, and provider-write events.
