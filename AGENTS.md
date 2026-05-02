# AGENTS.md

Working preferences for `~/Dev/MailAssist`.

## Response Style

- In final status updates after implementation work, put the high-signal outcome first under `Result`, because the Codex app may append file cards and changed-file panels after the message.
- Keep `Result` short and concrete, such as version, completed scope, and test status.
- Put supporting details, changed files, and caveats below `Result`.
- Avoid clickable file links in final status updates unless the user specifically asks for them, because they create extra file cards that push the useful summary away from the top.

## Environment

- Full procedure lives in [docs/sops/ENVIRONMENT_SOP.md](~/Dev/MailAssist/docs/sops/ENVIRONMENT_SOP.md).
- Apply `docs/sops/ENVIRONMENT_SOP.md` for Python commands, tests, and package installs in this workspace.

## Versioning

- Full procedure lives in [docs/sops/VERSIONING_SOP.md](~/Dev/MailAssist/docs/sops/VERSIONING_SOP.md).
- Apply `docs/sops/VERSIONING_SOP.md` whenever MailAssist-visible version numbers or release badges change.

## "Show Me" SOP

- Full procedure lives in [docs/sops/SHOW_ME_SOP.md](~/Dev/MailAssist/docs/sops/SHOW_ME_SOP.md).
- Apply `docs/sops/SHOW_ME_SOP.md` whenever the user asks to see the local UI.

## Handoff SOP

- Trigger phrase: `prepare for handoff`.
- Full procedure lives in [docs/sops/HANDOFF_SOP.md](~/Dev/MailAssist/docs/sops/HANDOFF_SOP.md).
- When that phrase appears, execute `docs/sops/HANDOFF_SOP.md` exactly.

## Pick Up Where We Left Off SOP

- Trigger phrase: `pick up where we left off`.
- Full procedure lives in [docs/sops/PICKUP_WHERE_LEFT_OFF_SOP.md](~/Dev/MailAssist/docs/sops/PICKUP_WHERE_LEFT_OFF_SOP.md).
- When that phrase appears, execute `docs/sops/PICKUP_WHERE_LEFT_OFF_SOP.md` exactly.

## Claude Critiques

- Current consolidated critique lives in [2026.04.30_Claude_Critique_2.md](~/Dev/MailAssist/2026.04.30_Claude_Critique_2.md).
- Treat critique files as pointers, not marching orders.
- Apply critique suggestions only after checking them against current code, `TODO.md`, `RESULTS.md`, product safety, and provider-write constraints.
- Prefer small, useful process or safety improvements over large refactors unless the refactor is the highest-priority unblocked work.

## `rscp`

- `rscp` means: refresh docs, summarize the current conversation to `SUMMARY.md`, commit, and push.
- Apply `rscp` when the user asks for `rscp` explicitly.
- If pushing is blocked because the git remote or auth is not configured yet, complete the earlier steps and report the push blocker clearly.

## Product Context

- Consult [STRATEGY.md](~/Dev/MailAssist/STRATEGY.md) before changing the core drafting flow, provider boundaries, or review loop.
- Consult [REALISM.md](~/Dev/MailAssist/REALISM.md) before changing privacy, approval, or provider-write behavior.
- Consult [RESEARCH.md](~/Dev/MailAssist/RESEARCH.md) before adding Gmail sync, Outlook support, or revision/approval workflows.
- Consult [RESULTS.md](~/Dev/MailAssist/RESULTS.md) before changing implementation direction so new work starts from the latest known status.
- Consult [TODO.md](~/Dev/MailAssist/TODO.md) for the active follow-up list after finishing research or implementation work.
