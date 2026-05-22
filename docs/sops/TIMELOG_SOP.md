# Active Collaboration Timelog SOP

This SOP defines how to track a user's active collaboration time with Codex on client or project work.

The purpose is to measure only the time the user spends exchanging project information, making decisions, reviewing options, or directing the work. It is not a wall-clock timer for Codex background work.

## Core Rule

Count only active user collaboration time.

Active collaboration time is the estimated time the user is present in the thread for project work, including:

- Giving requirements, corrections, approvals, or decisions.
- Answering Codex questions.
- Reviewing options, drafts, previews, or implementation results.
- Discussing priorities, scope, budget, risks, or tradeoffs.
- Asking project-related questions that affect the work.

Do not count:

- Codex background research, crawling, coding, testing, committing, deploying, or waiting on external systems.
- Idle gaps between user replies.
- Tool execution time unless the user is actively participating during it.
- Personal, administrative, or off-budget conversation after the user pauses the clock.
- Repeated status updates from Codex that do not require user attention.

## Clock State

The clock has an explicit state:

- `running`: project-related user collaboration is currently countable.
- `paused`: project-related or personal conversation is not countable until resumed.

User instructions control the state:

- "Start the clock", "resume", or equivalent starts counting again.
- "Stop the clock", "pause", "off budget", or equivalent pauses counting immediately.
- If the user switches to a clearly personal or unrelated topic, pause by default unless they explicitly say to keep counting.
- If the user returns to project direction after a pause, ask or infer based on context. When uncertain, do not count until the user clearly resumes project work.

## Estimation Method

Codex does not have reliable presence telemetry. Use a conservative message-based estimate:

- Count the active exchange window around project messages, not the full elapsed wall-clock gap.
- If the user sends several project messages in a short burst, count the realistic review/typing/decision time for that burst.
- If a gap between user messages is more than a few minutes and Codex was working independently, treat the gap as idle unless the conversation clearly shows the user was actively reviewing during that period.
- If the user gives an exact duration, use the user's duration.
- Log in one-minute increments.
- For a very small but meaningful project decision, log one minute.
- Do not add time for simple acknowledgments such as "thanks" unless they include a decision, correction, or new instruction.

When estimates are uncertain, err low and note the reason briefly.

## Timelog File Format

Use a project-local timelog file, usually named `SEO_TIMELOG.md`, `TIMELOG.md`, or another name specified by the repo.

Recommended structure:

```markdown
# Project Time Log

Budget: H:MM active collaboration time

Tracking rule: See `docs/sops/TIMELOG_SOP.md`.

Started tracking: YYYY-MM-DD HH:MM timezone

Clock state: running|paused

## Sessions

| Date | Start | End | Duration | Notes |
| --- | ---: | ---: | ---: | --- |
| YYYY-MM-DD | HH:MM TZ | HH:MM TZ | 0:03 | Brief project-specific note. |

## Totals

Active collaboration time used: H:MM
Remaining budget: H:MM
```

## Session Notes

Keep notes concise and client-safe:

- Describe the project activity, not private client details.
- Do not include passwords, admin credentials, personal notes, private strategy, or sensitive contact data unless the repo is explicitly private and the detail is necessary.
- Prefer "reviewed preview direction" over long narrative notes.

## Update Timing

Update the timelog when:

- The user starts, pauses, resumes, or stops the clock.
- A meaningful project exchange ends.
- The user asks for time remaining.
- A docs refresh, handoff, or commit is requested and time changed.

Do not force a timelog edit for unrelated repo-only documentation changes when the clock is paused and no project time should be counted.

## Budget Reporting

When reporting time:

- State active time used.
- State remaining budget if there is a fixed budget.
- Mention that background implementation time was excluded when relevant.
- If the clock is paused, state that clearly.

Example:

```text
Clock is paused. Active collaboration time remains 0:22 used, 5:38 remaining.
```

## Definition Of Done

Timelog tracking is current when:

- The clock state reflects the latest user instruction.
- All countable active project exchanges have a session entry.
- Totals match the session table.
- Off-budget or paused conversation has not been charged.
