# Miscellaneous Critique — MailAssist

*Reviewed 2026-04-26. Issues that do not fit the architecture or GUI critiques.*

---

## 1. `MAILASSIST_BOT_POLL_SECONDS` is configured but never used

`Settings.bot_poll_seconds` is parsed from the environment and saved by the settings wizard. The app has no polling loop. The bot only runs when the user clicks "Run Mock Pass" or "Create Gmail Test Draft". The setting is inert. Either the polling loop needs to be built (TODO P2), or the setting should be removed from the wizard and settings model to avoid implying a capability that does not exist.

---

## 2. `append_signature_to_body` is implemented twice

`review_state.py` defines `append_signature_to_body` which strips a trailing signature before appending.

`background_bot.py` defines `append_signature` and `strip_configured_signature` which do the same thing with a slightly different implementation.

These are functionally identical but live in separate modules and are not shared. Any subtle divergence in behavior (e.g., case-sensitivity of the strip) would produce different output depending on which path generated the draft. One implementation in a shared module should replace both.

---

## 3. `ensure_review_state` can block the main thread

```python
# review_state.py:946
def ensure_review_state(root_dir, *, base_url, selected_model):
    state = load_review_state(root_dir)
    for thread_state in state.get("threads", []):
        if not thread_state.get("candidates"):
            regenerate_thread_candidates(...)   # ← synchronous Ollama call
```

`ensure_review_state` is called from `refresh_dashboard` in the desktop GUI. If `review-inbox.json` exists but has threads with no candidates, `ensure_review_state` calls Ollama synchronously in the main thread for each such thread. The GUI freezes until Ollama responds. This should run in a QThread or worker process, the same way `run_bot_action` does.

---

## 4. `bot_poll_seconds` setting conflicts with the manual-only bot

Related to issue 1: the settings wizard Advanced page includes a "Poll interval" field. Showing this to users implies the bot auto-polls. The real behavior is manual-only. Displaying a setting that does nothing erodes trust in the setup flow. Hide or remove it until the polling loop is implemented.

---

## 5. No test coverage for `desktop.py`

There are unit tests for `background_bot.py`, `bot_runtime.py`, `config.py`, and `review_state.py`. There are no tests for `desktop.py`. At minimum, the helper functions (`_format_model_size`, `_format_model_age`, `_event_time_label`, `_log_action_label`, `_humanize`) are pure functions that can and should be tested without a display.

---

## 6. `fallback_classification_for_thread` uses fragile keyword matching

```python
# review_state.py:361
if any(token in haystack for token in ("unsubscribe", "no-reply", ...)):
    return "automated"
```

The heuristic scans raw email text for literal substrings without word boundaries, case folding applied to the haystack only. "no-reply" would match inside "I'm not going to reply today". The patterns should use `re.search` with `\b` word boundaries, or at minimum be applied only to sender addresses and subject lines rather than the entire message body.

---

## 7. `parse_batch_candidate_response` raises on any missing block

```python
# background_bot.py:423
if start < 0 or end < 0:
    raise ValueError(f"Missing packed response block for {thread_id}.")
```

If the LLM omits one thread block from the batch response, the entire batch fails and the caller falls back to individual per-thread generation for all threads. The fallback is correct but the granularity is wrong: a single missing block should fail only that thread, not the entire batch. The caller (`run_mock_watch_pass`) would then retry just the missing thread.

---

## 8. `review-inbox.json` lives under `data/legacy/`

The active review state file is stored at `data/legacy/review-inbox.json`. The "legacy" path segment was intended for the queue phase directories that were removed. Keeping the active review file at a path explicitly labelled "legacy" is confusing for anyone reading the data directory. If the review flow is being retired (TODO P6), this is a non-issue. If it is kept, the file should move to `data/review-inbox.json` and the migration helper should move it there.

---

## Summary

| Issue | Severity |
|---|---|
| `bot_poll_seconds` configured in wizard but polling loop does not exist | Medium |
| `append_signature_to_body` duplicated with divergent implementations | Medium |
| `ensure_review_state` can freeze the main thread with synchronous Ollama calls | Medium |
| Poll interval field in settings wizard implies a capability that does not exist | Medium |
| No tests for `desktop.py` helper functions | Low |
| `fallback_classification_for_thread` uses unbounded substring matching | Low |
| Batch parse fails the entire batch when one thread block is missing | Low |
| Active review state stored under `data/legacy/` | Low |
