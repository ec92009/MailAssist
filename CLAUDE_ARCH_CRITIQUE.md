# Architecture Critique — MailAssist

---

## 1. `gui/server.py` is a god module (most urgent)

At 2,240 lines, `gui/server.py` owns: HTTP routing, inline HTML+CSS rendering, all review-state persistence (`load_review_state`, `save_review_state`, `find_thread_state`, `update_candidate`, `update_thread_status`), all LLM prompt building (`build_review_candidates_prompt`, `build_single_review_candidate_prompt`), candidate generation (`generate_candidates_for_thread`, `generate_candidate_for_tone`, `stream_candidate_for_tone`), classification logic (`normalize_classification`, `fallback_classification_for_thread`, `merge_classification`), and all mock fixture data (`build_mock_threads`).

Because of this, every other module in the codebase imports from `gui.server` to get business logic:

| Importer | What it pulls from `gui.server` |
|---|---|
| `background_bot.py` | `build_mock_threads`, `fallback_classification_for_thread`, `generate_candidate_for_tone` |
| `bot_queue.py` | `generate_candidates_for_thread`, `thread_to_payload` |
| `bot_runtime.py` | `build_mock_threads`, `load_review_state`, `regenerate_thread_candidates`, `save_review_state` |
| `gui/desktop.py` | ~15 symbols including all state management and generation functions |

**The bot cannot run without importing the GUI server.** This makes it impossible to split bot and GUI into separate processes cleanly, test the bot without the HTTP stack being importable, or refactor the web layer without risking breakage everywhere.

**Fix:** Extract three modules from `server.py`:
- `core/review_state.py` — state persistence and mutation (`load_review_state`, `save_review_state`, `find_thread_state`, `update_candidate`, `update_thread_status`)
- `core/candidates.py` — classification, prompt building, and candidate generation
- `fixtures/mock_threads.py` — the hardcoded mock inbox data

`server.py` should only contain HTTP routing and HTML rendering, importing from those modules.

---

## 2. Two parallel, disconnected state systems

There are three separate persistence mechanisms that are not integrated:

**System A — `bot-state.json`** (`background_bot.py`)  
Tracks which threads the bot has seen and what action it took per provider. Written by `run_mock_watch_pass`. Never read by the GUI.

**System B — `review-inbox.json`** (`gui/server.py`)  
The primary review queue. Contains threads, candidates, classification, and review status. Written and read by both `server.py` and `desktop.py`. Pre-populated from hardcoded mock data via `default_review_state()`. Never written by `background_bot.py`.

**System C — Queue phase directories** (`bot_queue.py`)  
Five filesystem directories: `bot_processed`, `gui_acquired`, `user_reviewed`, `provider_drafted`, `user_replied`. Written by `process-mock-inbox`. **Never read by the GUI review flow.** The review workflow reads `review-inbox.json` directly and never touches these directories.

The result is that `bot-state.json` and the queue phases are write-only from the user's perspective: the GUI never reads them, so they accumulate data that drives nothing. The queue pipeline was clearly designed as a handoff between bot and GUI, but the connection was never built.

---

## 3. `core/orchestrator.py` and `storage/filesystem.py` are effectively dead code

`DraftOrchestrator.draft_thread` is the original draft generation path, called only by `mailassist draft-thread`. It produces `DraftRecord` objects stored in `data/drafts/` and `ExecutionLog` objects in `data/logs/`. Neither of these are used by the bot/review workflow, which uses `generate_candidates_for_thread` and stores everything in `review-inbox.json`.

`mailassist list-drafts` and `mailassist list-logs` list files that will always be empty in the normal bot/review workflow. `FileStorage`, `ExecutionLog`, and the `DraftOrchestrator` class exist alongside a completely separate candidate pipeline. These two paths have incompatible prompt builders, data structures, and storage strategies. One of them should be removed.

---

## 4. `load_settings()` depends on `Path.cwd()`

```python
def load_settings() -> Settings:
    root_dir = Path.cwd()
    load_dotenv(root_dir / ".env")
```

Settings assume the process is started from the project root. `bot_runtime.py` works around this by setting `QProcess.setWorkingDirectory(str(self.settings.root_dir))` before launching the bot subprocess — but `self.settings.root_dir` was already resolved from the GUI's `cwd`, creating circular dependency on the launch directory. If the user launches `mailassist desktop-gui` from any other directory, no `.env` is found and all settings fall back to defaults silently.

`load_settings()` should accept an explicit `root_dir: Path` parameter (defaulting to `Path.cwd()` for backwards compatibility) so callers can be explicit.

---

## 5. TONE_OPTIONS is defined in two incompatible places

`background_bot.py` defines `TONE_OPTIONS` as a dict of **4 tones** (direct_concise, warm_collaborative, formal_polished, brief_casual) used for single-draft bot generation.

`gui/server.py` defines `CANDIDATE_BLUEPRINTS` as a list of **2 tone blueprints** (direct and executive, warm and collaborative) used to generate review candidates.

These are two separate tone systems. The bot generates one draft per thread in the user's configured tone. The review GUI always generates two candidates in two hardcoded tones, ignoring the user's tone preference. There is no shared source of truth. The settings panel lets users set a "default tone" that only affects the bot pass — never the review candidate generation.

---

## 6. Mock data lives in production code

`build_mock_threads()` in `server.py` (lines 105–301) is 196 lines of hardcoded test thread data used in three separate contexts: seeding `review-inbox.json` on first run, running mock bot passes, and running the `process-mock-inbox` action. This data is part of the production import graph — importing `mailassist.gui.server` always loads 8 mock email threads into memory.

It belongs in `tests/fixtures/mock_threads.py` or a `mailassist/fixtures.py`, not in the HTTP server module.

---

## 7. No LLM abstraction layer

`OllamaClient` is imported and instantiated directly in `core/orchestrator.py`, `gui/server.py`, and `bot_runtime.py`. There is a `DraftProvider` ABC for email providers, but no equivalent `LLMClient` protocol. Adding a second LLM backend (Claude, OpenAI, a local llama.cpp endpoint) would require touching every module that constructs an `OllamaClient`.

The `providers/base.py` pattern (`DraftProvider` ABC with `create_draft`) is well-designed; the same pattern should exist for LLM clients.

---

## 8. `reply_recipients_for_thread` hardcodes the user's email address

```python
def reply_recipients_for_thread(thread: EmailThread, user_address: str = "you@example.com") -> list[str]:
```

The default is a mock address. No caller passes a real address — they all rely on the default. `Settings` has no `user_email` field. In a live Gmail flow, the bot would generate drafts addressed to `you@example.com` because no real user email is available.

---

## 9. All review state stored in a single file

`review-inbox.json` is read in full and written in full on every operation — every autosave, every status update, every candidate edit. As the inbox grows (imagine months of threads), this becomes a full read-write cycle on each keystroke in the draft editor (autosave fires 450ms after typing stops).

Consider per-thread JSON files in a directory, or at minimum a dirty-flag pattern that batches writes.

---

## 10. State mutation is inconsistent

Some functions return a modified dict that was also mutated in-place (e.g., `update_thread_status`, `update_candidate`). Callers sometimes use the return value, sometimes don't. There is no clear ownership — any code holding a reference to `thread_state` sees mutations from any other code touching the same object, since they all reference the same dict inside `review_state["threads"]`. This makes it hard to reason about when state is "dirty" and when it's been persisted.

---

## Summary

| Issue | Severity |
|---|---|
| `gui/server.py` is a god module; business logic lives in the HTTP layer | High |
| Three disconnected state systems; queue phases are unused by the GUI | High |
| `core/orchestrator.py` and `FileStorage` are dead code alongside a separate candidate pipeline | Medium |
| `load_settings()` depends on `cwd`; fragile for multi-process / multi-machine use | Medium |
| Two incompatible tone systems; user tone preference ignored during review candidate generation | Medium |
| Mock fixtures hardcoded in production HTTP module | Medium |
| No LLM abstraction; Ollama is hardwired throughout | Medium |
| User email hardcoded as `you@example.com` in bot reply logic | Medium |
| Single-file state store rewritten on every edit | Low (for now) |
| In-place state mutation with no ownership model | Low |

---

*Critique generated 2026-04-26 from code review of `src/mailassist/` — all Python modules.*
