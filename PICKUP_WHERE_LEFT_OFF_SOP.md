# Pick Up Where We Left Off SOP

Trigger phrase: `pick up where we left off`.

When asked to pick up where we left off, always execute this sequence:

1. Sync local state:
   - `cd /Users/ecohen/Dev/MailAssist`
   - `git checkout main`
   - `git pull origin main`
   - `uv sync`
2. Rebuild project context from source-of-truth files:
   - read `TODO.md` fully, especially `Handoff` and the highest-priority open section
   - read `SUMMARY.md`
   - read `RESULTS.md`
   - read `STRATEGY.md` and `REALISM.md` before changing the core drafting flow, provider boundaries, privacy, approval, or provider-write behavior
   - read `RESEARCH.md` before adding Gmail sync, Outlook support, or revision/approval workflows
3. Reconstruct current execution status:
   - identify the single highest-priority unblocked item
   - identify the exact next implementation step already recorded
   - confirm blockers, environment gaps, and whether local credentials or tokens are intentionally absent on the current machine
4. Resume execution immediately:
   - start with the recorded next step
   - do not re-plan from scratch unless repo state or blockers changed
   - keep edits small and checkpoint progress in `TODO.md` and `SUMMARY.md` before handoff
5. Report back in one concise status update:
   - current baseline commit/version
   - task in progress
   - next concrete action
