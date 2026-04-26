# Architecture Critique — MailAssist

*Reviewed 2026-04-26 against the full `src/mailassist/` tree.*

---

## 1. Dead pipeline: `core/orchestrator.py` + `storage/filesystem.py`

`DraftOrchestrator`, `FileStorage`, and `ExecutionLog` are a complete, parallel draft pipeline that is never exercised by the normal bot or review flow. The active path is `run_mock_watch_pass` → `generate_candidate_for_tone` → `provider.create_draft` → `bot-state.json`. The legacy path uses `FileStorage.save_draft` → `data/legacy/drafts/` and `FileStorage.save_log` → `data/legacy/logs/`.

The CLI commands `mailassist draft-thread`, `list-drafts`, and `list-logs` are the only callers of the legacy path. They write to directories that are never read by the GUI or the bot. These three modules (`orchestrator.py`, `filesystem.py`, and the related CLI commands) should be deleted. `ExecutionLog` in `models.py` can also go with them.

---

## 2. Two disconnected state stores

**`data/bot-state.json`** (`background_bot.py`) records which threads the bot has seen and what it did (skipped, draft_created), keyed by provider and thread ID.

**`data/legacy/review-inbox.json`** (`review_state.py`) stores threads, their classification, generated candidates, and review status.

These stores do not reference each other. When the bot creates a draft during a live Gmail pass, it writes to `bot-state.json` only. The review inbox is never updated. The GUI's "Recent Activity" log shows live bot events, but the review table (if one ever exists) would not know about them. For the mock flow this is hidden by the fact that both systems seed from the same fixtures, but for a real Gmail integration it is a real data gap.

The active product direction (TODO P2, P6) plans to replace both with a single durable live-bot state store. Until then, the gap should at least be documented in code comments.

---

## 3. Hardcoded user email in two functions

```python
# background_bot.py:470
def reply_recipients_for_thread(thread: EmailThread, user_address: str = "you@example.com") -> list[str]:

# background_bot.py:563
def review_context_messages(thread, *, user_address: str = "you@example.com", ...):
```

No caller ever passes a real address — both use the default. `Settings` has no `user_email` field. In a live Gmail flow, the bot would generate drafts addressed to `you@example.com` and omit the real sender from quoted context. This must be resolved before a live watch pass is meaningful.

---

## 4. Two incompatible tone systems

`background_bot.py` defines `TONE_OPTIONS` — a dict of **4 tones** used when the bot generates a single draft per thread.

`review_state.py` defines `CANDIDATE_BLUEPRINTS` — a list of **2 hardcoded tones** used when the review UI generates two candidates per thread.

These systems have no shared source of truth. The user-configured tone in Settings only affects bot-path drafting. The review candidate generation always uses the same two hardcoded tones regardless of what the user chose. If the review path is retired (TODO P6), this issue goes away with it. Until then it is a confusing inconsistency.

---

## 5. Duplicate prompt ruleset in four places

The drafting rules block (classification rules, no-promise rules, grounding rules, word limit, signature rules) is copy-pasted nearly verbatim into:

- `build_batch_candidate_prompt` (`background_bot.py`)
- `build_review_candidates_prompt` (`review_state.py`)
- `build_single_review_candidate_prompt` (`review_state.py`)
- `build_single_review_candidate_body_prompt` (`review_state.py`)

Any rule change requires four synchronized edits. One shared `_draft_rules_block(...)` helper would eliminate the drift risk.

---

## 6. `review_state.py` is a 1000-line god module

`review_state.py` currently combines: state persistence, schema migration, LLM orchestration, prompt building, response parsing, candidate fallback logic, filtering and sorting helpers, and status constants. It imports from `config`, `fixtures`, `llm`, and `models`. This file is hard to navigate and test in isolation. A future split into `review_store.py` (persistence + schema) and keeping prompt/generation logic in `background_bot.py` would match the direction already suggested in TODO P6.

---

## 7. `migrate_legacy_runtime_layout` runs on every state read/write

```python
# review_state.py:332
def review_state_path(root_dir: Path) -> Path:
    migrate_legacy_runtime_layout(root_dir)   # ← runs every call
    return root_dir / "data" / "legacy" / REVIEW_STATE_FILENAME
```

`review_state_path` is called by `load_review_state` and `save_review_state`. Migration logic runs on every read and write — including autosave. Migration should run once at startup (it already does in `load_settings`), and `review_state_path` should be a pure path resolver.

---

## 8. `save_review_state` has no atomic write

`save_bot_state` uses a tmp-file + rename pattern to avoid a partial write corrupting state. `save_review_state` writes directly:

```python
# review_state.py:768
path.write_text(json.dumps(state, indent=2), encoding="utf-8")
```

A crash mid-write would corrupt `review-inbox.json`. The same tmp+rename pattern from `save_bot_state` should be applied here.

---

## 9. `generate_candidates_for_thread` calls `load_settings()` at call time

```python
# review_state.py:559
def generate_candidates_for_thread(thread, base_url, selected_model):
    signature = load_settings().user_signature   # re-reads .env every call
```

`load_settings()` re-reads `.env` from `Path.cwd()` each call. If the caller is in a subprocess that started in a different directory, it silently gets the wrong settings. The signature (and other relevant settings) should be passed as parameters, not re-derived inside a generation function.

---

## 10. `load_settings()` falls back to `cwd` without warning

```python
# config.py:87
return Path.cwd()   # dev fallback
```

The frozen-app path is correct. The dev fallback is `Path.cwd()`. There is no log or warning when `.env` is missing. Any component that calls `load_settings()` outside the GUI's `QProcess` (which explicitly sets `--working-directory`) will silently use a wrong root. The minimal fix is a `warnings.warn` when `.env` is not found at the resolved root. The right fix is for `MAILASSIST_ROOT_DIR` to be required in all non-frozen invocations.

---

## Summary

| Issue | Severity |
|---|---|
| Dead pipeline: `orchestrator.py`, `filesystem.py`, related CLI commands | High |
| Two disconnected state stores; bot and review UI have no shared channel | High |
| User email hardcoded as `you@example.com`; no `user_email` in Settings | High |
| Two incompatible tone systems; user tone preference ignored in review path | Medium |
| Duplicate prompt ruleset copy-pasted across four prompt builders | Medium |
| `review_state.py` is a 1000-line god module combining unrelated concerns | Medium |
| `migrate_legacy_runtime_layout` called on every state read/write | Low–Medium |
| `save_review_state` has no atomic write | Low–Medium |
| `generate_candidates_for_thread` re-derives settings from cwd at call time | Low–Medium |
| `load_settings()` silently falls back to cwd with no warning | Low |
