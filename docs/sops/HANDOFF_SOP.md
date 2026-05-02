# Handoff SOP

Trigger phrase: `prepare for handoff`.

When asked to prepare for handoff, always do all of the following before replying:

1. Update `TODO.md` `Handoff` with:
   - the exact startup prompt:
     - `work in ~/Dev/MailAssist, synchronize with Github ec92009/MailAssist, catch up; open TODO.md and execute the handoff instructions`
   - current `main` commit
   - current visible version
   - current local app/dev entrypoint
   - active open issue(s) and immediate next implementation step
2. Apply backlog hygiene:
   - keep recently completed items in `TODO.md` under `Recently Completed`
   - make sure completed items state what changed and who owns follow-up work
   - keep blocked work marked with the concrete blocker, such as `Waiting on Magali`
3. Refresh `SUMMARY.md` with the current project state and resume point.
4. Commit and push the handoff/documentation updates to `main`.
5. Reply with `handoff ready` and include the commit hash.
