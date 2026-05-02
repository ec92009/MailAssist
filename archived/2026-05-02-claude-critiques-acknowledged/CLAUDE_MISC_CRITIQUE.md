# Miscellaneous Critique — MailAssist

*Originally reviewed 2026-04-26. Refreshed 2026-04-30 against `main` at `146b8c9` (v61.10), 191 tests green.*

Issues that do not fit the architecture or GUI critiques.

---

## Resolved Since 2026-04-26

- **`bot_poll_seconds` configured but inert** — the `watch-loop` action now exists (`bot_runtime.py:91, 781–784`) and uses `args.poll_seconds or settings.bot_poll_seconds or 30`. The desktop's "Start Auto-Check" button is wired to it (`desktop.py:573–593`), and Recent Activity now distinguishes "pass completed" from "waiting for next interval". The poll-interval field in the settings wizard is no longer aspirational.
- **`ensure_review_state` blocking the main thread** — `desktop.py` no longer imports `review_state`; the synchronous-Ollama-call-during-`refresh_dashboard` path is gone with the rest of the review UI.
- **No tests for `desktop.py`** — `tests/test_desktop_layout.py` (1527 lines) covers wizard navigation, layout stability, status pill painting, and the action gating helpers. (Severity-of-coverage caveat in GUI critique #7.)

---

## 1. `append_signature_to_body` still implemented twice

`review_state.py:113` and `drafting.py:79` both define `append_signature_to_body`. `background_bot.py:649` defines `append_signature` as a thin wrapper around the `drafting.py` version. The active production path uses `drafting.py`'s implementation, but `review_state.py`'s copy is still imported by `tests/test_review_state.py` and is loaded into the package whenever `review_state.py` is imported.

If the duplicate had truly diverged it would already be a bug; the safer reading is that they happen to agree today and could silently diverge tomorrow. Resolution depends on Issue 1 of the architecture critique: if `review_state.py` is removed, this duplicate goes with it. Otherwise, `review_state.py` should `from mailassist.drafting import append_signature_to_body` rather than re-defining it.

---

## 2. `fallback_classification_for_thread` still uses unbounded substring matching

`review_state.py:350–381` (also re-exported from `drafting.py`) classifies threads by joining subject + participants + every message body, lowercasing, and testing `if any(token in haystack for token in (...))`. The original critique noted the false-positive risk — "no-reply" inside ordinary prose. Active triggers:

- `"unsubscribe"` flags any message that contains the literal substring (legitimate "you can unsubscribe at any time" copy in a *human-written* mail will misclassify as `automated`).
- `"digest"` matches "digestive issues" or anything else where that substring appears.
- `"urgent"`, `"asap"`, `"this afternoon"`, `"end of day"` are all matched anywhere in the body, including quoted history.

The fix is unchanged from Apr 26: scope the match to sender address and subject, and use `\b` word boundaries when scanning body text. Lower priority since this is a heuristic fallback — the LLM classifier is the primary path — but the heuristic is what gets used when Ollama is unreachable.

---

## 3. `parse_batch_candidate_response` still raises on any missing block

`background_bot.py:540–556` builds the per-thread block markers and raises `ValueError` as soon as one expected thread block is missing. The caller falls back to per-thread generation for the whole batch, so the granularity issue from Apr 26 still applies: a single missing block causes N–1 redundant retries.

The cleaner shape is to keep the parsed blocks for threads that were present and report missing ones to the caller, so the caller can retry only those threads. This is one localized change in `_parse_batch_block` / `parse_batch_candidate_response` plus a small contract change in the caller.

---

## 4. Active review state is still stored under `data/legacy/`

`review_state_path` (`review_state.py:322–323`) returns `root_dir / "data" / "legacy" / REVIEW_STATE_FILENAME`. `config.migrate_legacy_runtime_layout` even moves `data/review-inbox.json` → `data/legacy/review-inbox.json` on startup (`config.py:191`). This is fine *if* the review module is being deleted (architecture critique Issue 1). If it stays, the path is misleading: `data/legacy/` was created during an earlier migration to hold *deprecated* artifacts, and stashing the active file there reads like a mistake.

Either delete the review module entirely, or move `review-inbox.json` back to `data/review-inbox.json` and update the migration helper.

---

## 5. Mock-thread fixtures still hard-code `you@example.com`

`fixtures/mock_threads.py` uses `you@example.com` as the recipient and as a participant in 12 mock threads. This is fine for unit tests and for the mock provider (the provider explicitly accepts `account_email` and threads it through), but two surprises remain:

- The controlled Gmail test draft (`bot_runtime.py:680, 691`) constructs body text with `user_address="you@example.com"` even though the surrounding code resolves the real `account_email` via `provider.get_account_email()` two lines later. The two coexist because the controlled test path is intentionally synthetic, but the literal address still appears in the body that is sent to the Gmail draft API.
- Anyone running `mailassist outlook-smoke-test` against a fixture-shaped Outlook conversation would see the same placeholder leak through.

Pass `user_address=account_email or "you@example.com"` (or simply omit the kwarg now that defaults exist) and the placeholder stops being user-visible.

---

## 6. `MAILASSIST_USER_SIGNATURE_HTML` and the plain-text signature can drift

The wizard maintains both `user_signature` (plain text) and `user_signature_html` (rich text). Persistence and import paths now exist for both, but nothing reconciles them: a user who changes `user_signature` directly via `.env` after first-run will keep an out-of-date `user_signature_html`, and vice versa. Drafts then assemble using the HTML signature for the HTML part and the plain-text signature for the plain part, producing a draft where the two MIME parts disagree.

A single `derive_html_from_plain(text)` fallback (used when `user_signature_html` is empty *or* when the plain version was edited more recently) would close this. Lower priority because the wizard is the normal editing surface and keeps them in sync.

---

## 7. CLI surface and GUI surface have grown in parallel without sharing entry-point types

`bot_runtime.py` argparse declares each action's flags. `gui/desktop.py` `run_bot_action(action, **kwargs)` constructs the same flags by hand. There is no shared schema. Every new flag (e.g., `--days` for organizers, `--force`, `--dry-run`) has to be added in argparse *and* hand-spelled in the GUI dispatch, with no compile-time guarantee they agree. A small `BotActionSpec` dataclass per action — used by both surfaces — would prevent the silent-typo class of bug.

This is a tax that will scale with the number of actions; it has not yet caused a visible regression.

---

## Summary

| # | Issue | Severity | Δ vs. 2026-04-26 |
|---|---|---|---|
| 1 | `append_signature_to_body` duplicated in `review_state.py` and `drafting.py` | Medium | Carryover (was Issue 2) |
| 2 | `fallback_classification_for_thread` uses unbounded substring matching | Low–Medium | Carryover (was Issue 6) |
| 3 | `parse_batch_candidate_response` fails the whole batch on one missing block | Low | Carryover (was Issue 7) |
| 4 | Active review state still under `data/legacy/` | Low | Carryover (was Issue 8) |
| 5 | `you@example.com` placeholder leaks into controlled Gmail draft body | Low–Medium | New |
| 6 | Plain-text and HTML signatures can drift out of sync | Low | New |
| 7 | CLI argparse and GUI `run_bot_action` flags hand-spelled in two places | Low | New |
