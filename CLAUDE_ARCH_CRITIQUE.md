# Architecture Critique — MailAssist

*Originally reviewed 2026-04-26. Refreshed 2026-04-30 against `main` at `146b8c9` (v61.10), 191 tests green.*

---

## Resolved Since 2026-04-26

- **Dead `core/orchestrator.py` + `storage/filesystem.py` pipeline** — source files have been deleted. `DraftOrchestrator`, `FileStorage`, `ExecutionLog`, and the `draft-thread` / `list-drafts` / `list-logs` CLI commands no longer exist in the source tree. (Stale `__pycache__` directories remain at `src/mailassist/core/` and `src/mailassist/storage/` — harmless but worth `git clean -fdX`.)
- **Two disconnected state stores** — `bot-state.json` is gone. `live_state.py` consolidates everything under `data/live-state.json` with provider-scoped slots, account email, recent activity, and an automatic migration from the legacy filename. `review-inbox.json` is now untouched by any production path (see Issue 1 below).
- **Hardcoded `you@example.com` in production paths** — providers now expose `get_account_email()`; `bot_runtime.py` and `background_bot.py` resolve the real address through `_resolve_account_email` and pass it to `reply_recipients_for_thread` / `review_context_messages`. The `you@example.com` defaults remain as fallback parameters and in the synthetic controlled-Gmail-test-draft path (`bot_runtime.py:682,691`), but no live watcher pass uses them.
- **`save_review_state` non-atomic write** — `review_state.py:758–763` now writes to a `.tmp` sibling and atomically renames.
- **`generate_candidates_for_thread` re-deriving settings from cwd** — signature is now passed as a parameter (`review_state.py:543–549`).
- **`migrate_legacy_runtime_layout` on every state read/write** — `review_state_path` (line 322) is now a pure path resolver; migration runs once inside `load_review_state` (line 723), not on save.
- **Two incompatible tone systems** — the review path is no longer a production code path (see Issue 1), so `CANDIDATE_BLUEPRINTS` vs. `TONE_OPTIONS` is no longer a user-visible inconsistency.

---

## 1. `review_state.py` is dead-ish weight: 1048 lines, no production caller

`review_state.py` is no longer imported by any source file outside of tests. `grep -rn "from mailassist.review_state" src/` returns nothing. The only importers are `tests/test_review_state.py` and `tests/test_config.py`. Yet the module is still 1048 lines, still defines `CANDIDATE_BLUEPRINTS`, `build_review_candidates_prompt`, `build_single_review_candidate_prompt`, `build_single_review_candidate_body_prompt`, `generate_candidates_for_thread`, `ensure_review_state`, `regenerate_thread_candidates`, `load_review_state`, `save_review_state`, and the schema migration code.

The TODO backlog (item 4) explicitly calls this "legacy-only compatibility/test support". That status is fine as a transitional state, but the module is now decaying — its prompt builders have drifted from `drafting.py` (see Issue 2), and any maintenance change has to be verified against tests that exercise behavior the product no longer ships. Either:

- Delete `review_state.py` and the two test files entirely, or
- Reduce it to the small surface those tests actually exercise (probably classification helpers and schema migration), and remove everything else.

Keeping the full module around as "support" for tests that test the support is circular.

---

## 2. Drafting prompt rules now duplicated across `drafting.py` and `background_bot.py`

The Apr 26 critique called out the rules block being copy-pasted across four prompt builders inside `review_state.py` and `background_bot.py`. The duplication was reduced — the production path now uses one builder (`background_bot.py:470 build_batch_candidate_prompt`) — but the *other three builders* were copied verbatim from `review_state.py` into `drafting.py` (`build_review_candidates_prompt`, `build_single_review_candidate_prompt`, `build_single_review_candidate_body_prompt` at lines 307, 362, 419). `CANDIDATE_BLUEPRINTS` is also defined in both modules.

So the duplication was halved (4 → 2 modules), but it is still drift-prone. Because `drafting.py`'s copies are unused in production, they will silently fall behind any rule change made in `background_bot.py`. If `review_state.py` is removed (Issue 1), `drafting.py`'s copies should be removed with it; otherwise they should be folded into a single `_draft_rules_block(...)` helper.

---

## 3. `desktop.py` is a 3085-line single-class file

`MailAssistDesktopWindow` is the entire desktop GUI, with ~145 methods, defined as one class in `gui/desktop.py`. The file grew from 1768 lines (Apr 26) to 3085 (+74%) as Outlook controls, organizers, Recent Activity heartbeats, settings tabs, and Tone-page editors were added. Dev/CLAUDE.md states the project preference is "files under 300 lines where practical; refactor beyond that"; this class is 10× over.

Concrete pain points already visible:

- Test file `test_desktop_layout.py` is 1527 lines because every behavioral property has to be exercised through the same mega-window.
- The settings wizard, bot control panel, Tone editor, Categories editor, and Recent Activity panel are functionally separate but cross-reference each other through `self.` attributes on the same object — refactoring any one section requires reading the full file.
- New panels (e.g., the Elders editor) have to read the same `self.settings` and emit through the same `_set_banner` / `_append_recent_activity` choke points, making each addition expand the class.

The right next step is splitting the GUI into per-panel widgets that the main window composes. Settings tab pages and the Recent Activity panel are the most obvious extractions because each already has its own internal state.

---

## 4. `bot_runtime.py` and `background_bot.py` are both >1000 lines and overlap

`bot_runtime.py` (1153 lines) is the CLI/argparse entry point that dispatches every bot action, while `background_bot.py` (1028 lines) holds the watcher pipeline, drafting helpers, account-email resolution, recipient/quoted-context logic, and the live-state slot writes. The functional boundary between them is unclear:

- Both modules reach into `live_state` to read and write provider slots.
- Both define helpers to construct draft bodies; for example `body_with_review_context` is called from `bot_runtime.py:680` for the controlled Gmail test draft, but is defined inside `background_bot.py`.
- Reply/recipient helpers (`reply_recipients_for_thread`, `reply_metadata_for_thread`, `_safe_reply_recipient`) live in both modules.

The result: a casual reader cannot answer "where does an Outlook live watcher pass create the draft?" without reading both files end-to-end. A natural split would be: `bot_runtime.py` = argparse + per-action dispatch only; `background_bot.py` (or a new `live_pipeline.py`) = the watcher pass, slot writes, and reply construction; reply/recipient helpers move to a tiny `replies.py` shared by both. The slow accretion of "one more action" inside `bot_runtime.py` is the symptom that motivated the cleanup.

---

## 5. Provider modules are large and divergent

`providers/gmail.py` (750 lines) and `providers/outlook.py` (709 lines) implement the same `DraftProvider` contract but have grown side by side without a shared base for the cross-cutting concerns:

- Account-email caching, `from_address` selection, `to`-list de-duplication, "automated sender" classification, and reply-metadata wiring are implemented twice.
- `_safe_reply_recipient` lives in `bot_runtime.py` rather than `providers/base.py`, yet is purely a provider-shape concern.
- `providers/base.py` is only 63 lines and exposes the contract but no shared helpers, so each new provider re-implements the same edge-case handling.

This will become more painful when a third provider lands (the TODO mentions "future provider cursors" in `live_state.py`). The fix is to push the shared shape (account-email memoization, to/from de-dup, reply metadata) into `providers/base.py` so each concrete provider only handles its API differences.

---

## 6. `load_settings()` still falls back to `Path.cwd()` without warning

`config.py:160` returns `Path.cwd()` as the dev fallback when neither `MAILASSIST_ROOT_DIR` nor `sys.frozen` is set. There is still no `warnings.warn` when `.env` is missing at the resolved root. This was Issue 10 in the original critique and is unchanged.

The frozen-app path is correct. The risk surface is anything that calls `load_settings()` outside the GUI's `QProcess` (which sets `--working-directory`). Adding a single `warnings.warn` when `.env` is not found at the resolved root would make the silent-misconfiguration class of bug self-reporting; making `MAILASSIST_ROOT_DIR` mandatory in non-frozen invocations would eliminate it.

---

## 7. Stale `__pycache__` directories from deleted modules

`src/mailassist/core/__pycache__/orchestrator.cpython-313.pyc` and `src/mailassist/storage/__pycache__/filesystem.cpython-313.pyc` still exist on disk even though their source files were removed in the Apr 26→30 cleanup. `find src -path "*/core*" -o -path "*/storage*"` finds these directories. They cannot be imported (no source) and would normally be regenerated only if the source files came back, but they confuse `find` / IDE indexers and grep-based audits.

A `git clean -fdX src/` (interactive, dry-run first) plus a `.gitignore` already covering `__pycache__` is enough.

---

## Summary

| # | Issue | Severity | Δ vs. 2026-04-26 |
|---|---|---|---|
| 1 | `review_state.py` is 1048 lines, used only by tests | High | New (was god-module; now also dead) |
| 2 | Prompt rules duplicated across `drafting.py` and `background_bot.py` | Medium | Reduced from 4 modules to 2 |
| 3 | `desktop.py` is a 3085-line single class | High | Worsened (was 1768 lines) |
| 4 | `bot_runtime.py` + `background_bot.py` overlap; both >1000 lines | Medium | New |
| 5 | Provider modules duplicate shape; `providers/base.py` is thin | Medium | New |
| 6 | `load_settings()` falls back to cwd without warning | Low | Unchanged |
| 7 | Stale `__pycache__` from deleted `core/` and `storage/` | Low | New (cleanup miss) |
