# MailAssist Repo Review — 2026-05-02 (v62.12)

Working directory: `~/Dev/MailAssist`. Branch reviewed: `claude/optimistic-leakey-08d156` (worktree, clean against `main`). Test baseline reported in `README.md`: 202 passing tests on 2026-05-01.

This is a quick, opinionated walk-through. Nothing here is blocking; the product direction is sound and the discipline around safety/handoff is unusually good.

---

## 1. Architecture

### Pros

- **Provider abstraction is clean.** `DraftProvider` (ABC) + `ProviderReadiness` dataclass in [providers/base.py](src/mailassist/providers/base.py) gives Gmail, Outlook, and Mock a tight uniform contract — `authenticate`, `get_account_email`, `list_actionable_threads`, `create_draft`, `readiness_check`. New providers slot in via [providers/factory.py](src/mailassist/providers/factory.py:1) without touching the bot loop.
- **Draft-only invariant is enforced at the boundary, not by convention.** No provider exposes a "send" method — the safety promise lives in the type system, not just in docs. This is the single most important architectural choice and it's done right.
- **Pure-stdlib Ollama + Graph clients.** [llm/ollama.py](src/mailassist/llm/ollama.py) and the Graph code in [providers/outlook.py](src/mailassist/providers/outlook.py) use `urllib` only — keeps the dep tree tiny and the packaged `.app` light. `think: false` is wired in for both streaming and non-streaming paths.
- **Bot/GUI separation matches STRATEGY.md.** The bot is a CLI subprocess (`review-bot --action watch-loop`) that emits JSONL events on stdout; the GUI launches it via `QProcess` and parses log lines. This means the bot keeps running even with the UI closed, and the UI never has to share Python state with a long-running watcher. Good unix-y choice.
- **Honest, auditable event stream.** `BotEventReporter` in [bot_runtime.py](src/mailassist/bot_runtime.py:59) writes one JSONL file per run, mirrored to stdout — easy to tail, easy to replay, easy to test.
- **Dataclasses over dicts.** [models.py](src/mailassist/models.py) uses `@dataclass` with explicit `from_dict`/`to_dict`. `DraftRecord` is rich enough to round-trip provider draft IDs, RFC message-ids, references, and submission status — that's what makes resumption across machines actually work.
- **Local-first state.** `data/live-state.json`, `data/bot-logs/*.jsonl`, `secrets/*.json` are all gitignored; runtime files relocate to `~/Library/Application Support/MailAssist` for the packaged app. The privacy posture in [REALISM.md](REALISM.md) is matched by what the code actually does.
- **Watcher filters are first-class.** [live_filters.py](src/mailassist/live_filters.py) gives both providers a shared `WatcherFilter` (unread-only, time window) so behavior is consistent across Gmail and Outlook.

### Cons

- **`gui/desktop.py` is a 3,809-line god object.** One `MailAssistDesktopWindow` with 152 methods owns theming, settings wizard, dashboard, bot lifecycle, log parsing, signature editor, prompt preview, organizer flow, confirmation dialogs, and elder-contacts editor. This is the largest maintenance liability in the repo. Splitting into `ThemeManager`, `BotProcessController`, `SettingsWizardDialog`, `DashboardWidget`, and `SignatureEditor` would shrink the public surface dramatically and make AI-agent edits far less fragile.
- **`review_state.py` is 1,048 lines of mostly legacy code.** It still defines `CLASSIFICATION_OPTIONS`, `COMMON_DRAFTING_RULES`, `CANDIDATE_BLUEPRINTS`, etc. — duplicates of what now lives in [drafting.py](src/mailassist/drafting.py). Production code no longer imports it; only `tests/test_review_state.py` and `tests/test_config.py` do. The risk is drift: the tests will keep the legacy classification logic alive even after the product moves on. Either delete the module and its tests, or move the still-useful pieces into `drafting.py` and retire the rest.
- **`bot_runtime.py` (1,153 lines) and `background_bot.py` (1,028 lines) carry too much.** `bot_runtime` is argparse + ten action handlers + Gmail/Outlook label plumbing in one file; `background_bot` mixes prompt construction, classification, draft assembly, attribution, signature handling, and platform/locale detection. A `mailassist/actions/` package (one file per `--action`) plus a `mailassist/prompts/` module would make the bot loop readable in a single screen.
- **Synchronous everywhere.** The bot loop is blocking; Ollama draft generation can take 14-20s per thread. This is fine for a background watcher, but a `cancel-current-draft` path doesn't really exist — the GUI's stop-after-timeout timer in `_stop_bot_after_timeout` is the only escape hatch.
- **Hand-rolled `.env` parser.** `read_env_file` / `write_env_file` in [config.py](src/mailassist/config.py:146) doesn't handle quoted values, `export` prefixes, or escaped newlines. Today's `.env` only has simple values, but a Windows path with spaces or an Outlook redirect URI with `?` query parts could surprise it.
- **No schema versioning on `live-state.json`.** Legacy `review-inbox.json` had a `REVIEW_STATE_SCHEMA_VERSION`; the live-state file used by the new bot does not. Once Magali is on it, future migrations will be harder.
- **Tests pin legacy.** `test_review_state.py` patches `mailassist.review_state.generate_candidate_for_tone` — a function that exists only because the legacy module shadows the real one. Cleaning this up should be part of the same change that retires `review_state.py`.

---

## 2. UI (PySide6 desktop)

### Pros

- **Native, not Electron.** PySide6 + a single window keeps the install footprint small and start-up fast. Window title shows `MailAssist v{visible_version}`, satisfying the global versioning rule on every screen.
- **Day / Night / System theming.** [`_theme_colors`](src/mailassist/gui/desktop.py:389) defines a full palette pair; `_resolved_appearance` follows the OS via `QApplication.styleHints().colorScheme()` and gracefully falls back to palette luminance. Status pills, success/warn/error banners, and combo popups all read from the palette.
- **Status as colored pills.** Bot, provider, and Ollama states render as glanceable pills, exactly the dense operational posture STRATEGY.md asks for. No decorative panels, no second inbox.
- **Settings flow is a wizard with a visible progress line.** `_build_settings_wizard` + `_settings_progress_stops` walk the user through provider → Ollama → writing style → signature → advanced → summary. The summary page reduces "did I configure this right?" anxiety.
- **Rich-text signature editor with attribution preview.** Bold / italic / underline / link controls, plus live HTML preview that respects the `Hide / Above / Below` attribution placement.
- **Honest progress UI for slow Ollama.** Heartbeat timer + countdown for the model check + status pills follow [REALISM.md](REALISM.md): no fake percentages, just "waiting / drafting / draft created / failed".
- **Keyboard shortcuts.** `Ctrl+,` settings, `Ctrl+L` logs, `Esc` dismiss banner.

### Cons

- **One file, one class, ~3.8k lines.** Already called out under architecture but it's a UI concern too: a designer (or Claude) cannot reason about the dashboard without scrolling through theming code, settings code, and bot-process plumbing in the same class.
- **Stylesheet rebuilt and re-walked on every theme change.** `_refresh_theme_dependent_widgets` calls `findChildren(QComboBox)` / `findChildren(QToolButton)` and re-applies inline stylesheets. Works, but it's why incremental UI tweaks tend to need cross-cutting edits.
- **README/code drift on shortcuts.** README advertises `⌘R` to "run a mock pass"; `_install_shortcuts` only registers `Ctrl+,`, `Ctrl+L`, and `Esc`. Either wire `Ctrl+R` up or remove it from README.
- **Tone is fixed at four options.** Good default, but no "custom tone" escape valve. Users who don't see themselves in `direct_concise / warm_collaborative / formal_polished / brief_casual` have to edit drafts in Gmail/Outlook every time.
- **Activity surface is "last only".** The dashboard summarizes the most recent pass and most recent failure; there is no rolling history view in the GUI itself (logs window aside). For a CPA who wants to trust the bot, a 7-day "drafts created / skipped / failed" mini-table would buy a lot of trust at low UI cost.
- **No first-run Ollama liveness check before the wizard.** If Ollama isn't running, the wizard still proceeds — the user discovers it later when the model list is empty. A pre-flight gate (or a one-button "Start Ollama") would be friendlier on Windows.

---

## 3. UX (end-to-end product feel)

### Pros

- **The product thesis is sharp and the docs match the code.** [STRATEGY.md](STRATEGY.md), [REALISM.md](REALISM.md), and [NORTH_STAR.md](NORTH_STAR.md) say the same thing the code does: pre-cook drafts in the background, never send, keep review in Gmail/Outlook. The bot is not pretending to be a mail client.
- **Magali-grade safety.** Drafting rules in [drafting.py](src/mailassist/drafting.py:44) explicitly forbid invented commitments, prices, calendars, follow-ups, and "I will call/check/confirm" promises. This is the right policy for a CPA reviewing real client mail.
- **`gmail-controlled-draft` is a smart safety primitive.** Self-addressed test draft from sanitized mock content — proves the write path without ever emailing a real recipient. Should be the model for the equivalent Outlook flow (which exists but is less prominent in the GUI).
- **`--dry-run` everywhere it matters.** `watch-once`, `watch-loop`, `gmail-label-cleanup`, `outlook-populate-categories` all preview before they write. This is what lets the project ship to a non-developer.
- **Doctor + setup-check commands.** `mailassist doctor`, `outlook-setup-check`, `ollama-setup-check` give a "does my install actually work?" answer without launching the GUI. Great for the Magali Zoom call.
- **Magali runbook is real.** [docs/magali-zoom-operator-script.md](docs/magali-zoom-operator-script.md), [docs/magali-windows-readiness-runbook.md](docs/magali-windows-readiness-runbook.md), and `tools/magali-bootstrap.ps1` reduce the call from "let's debug Python" to "paste this one command".

### Cons

- **Onboarding still requires hand-rolled OAuth.** Gmail needs a Desktop client JSON; Outlook needs an Entra app + tenant id. The PDFs are well-written but the user is still pasting paths into config. The North-Star ("Magali installs without developer help") is not yet met for either provider — a hosted/multitenant Outlook app is the closer of the two, and Gmail likely needs Google verification before it can be truly self-serve.
- **Versioning is opaque to outsiders.** `vX.Y` where X is days since 2026-02-28 is internally consistent but no end user can read `v62.12` and know what's in it. A short "What's new in v62" line in the GUI About panel (or README) would humanize it.
- **Repo-root markdown sprawl.** ~14 top-level `.md` files (README, STRATEGY, REALISM, RESEARCH, RESULTS, TODO, SUMMARY, NORTH_STAR, AGENTS, plus five SOPs). For a contributor or reviewer this is a lot to triage. Consider moving the SOPs into `docs/sops/` and keeping the root to README + a `docs/index.md`.
- **Slow LLM is visible but not interruptible.** A user who sees "drafting…" for 90s can stop the whole bot but cannot say "skip this thread, move on". Not urgent, but worth a backlog entry.
- **Activity history per provider is thin.** "Drafts created today: 3" / "Skipped: 12" / "Failed: 0" on the dashboard would shift the trust curve a lot, especially after the first week.
- **Mac DMG is ad-hoc signed, not notarized.** README walks the user through Gatekeeper override, which is fine for a sandbox build but is friction every install. A notarization pass once Magali is happy is worth the Apple Developer account fee.

---

## 4. Misc

### Pros

- **Test count is healthy and the suite is fast.** 202 tests, no network in the mock path, provider contract tests cover Gmail + Outlook + Mock uniformly via [tests/test_provider_contract.py](tests/test_provider_contract.py).
- **Strict and accurate `.gitignore`.** Every runtime drafts/logs/secrets path is excluded; only sanitized samples and placeholder folders ship.
- **Cross-platform packaging is thought through.** [packaging/macos/](packaging/macos) for DMG, `tools/magali-bootstrap.ps1` for Windows pickup, `docs/windows-packaging.md` for the VM rehearsal checklist.
- **SOPs make collaboration with Claude reproducible.** `prepare for handoff`, `pick up where we left off`, `rscp`, `Show Me` — these are real, specific, testable triggers. The codebase reads as if a process expert wrote it.
- **Archived work is actually archived.** [archived/2026-04-24-pre-background-bot/](archived/2026-04-24-pre-background-bot) and [archived/2026-05-02-claude-critiques-acknowledged/](archived/2026-05-02-claude-critiques-acknowledged) keep history without polluting the active root. Good muscle.
- **Outlook category writes mirror Gmail labels.** Symmetric `MailAssist - <Category>` / `MailAssist/<Category>` naming and a single shared "Categories" editor in the GUI is a small detail that pays off as the user moves between providers.

### Cons

- **No CI.** No `.github/workflows/`, no `pre-commit` hook, no pinned formatter. With 202 tests on local-only runs, regressions on a dirty machine are easy to ship. A simple "run pytest on push to main" GH Action would close the loop.
- **`uv.lock` weighs ~146k lines.** Expected, but worth pinning Python version (`requires-python = ">=3.9"` in `pyproject.toml` is broad — the packaged Mac app and Magali's Windows machine are both 3.12). Tightening to `>=3.11` would simplify support promises.
- **Several large markdown docs (TODO 174 lines, SUMMARY 153 lines, RESULTS 201 lines, README 339 lines) overlap.** They're each useful, but a contributor reading top-to-bottom will see the same Magali context restated four times.
- **No telemetry / opt-in usage stats.** Not asking for them — the local-first posture is correct — but if commercialization ever becomes the goal, a clearly-opt-in error reporter is the one thing that will be hard to retrofit.
- **`assets/brand/mailassist_icon.svg` is loaded but there's no PNG/ICO fallback path checked in for Windows packaging.** Worth confirming before the next Windows build.

---

## 5. Suggested next moves (small, high-leverage)

1. **Retire `review_state.py`.** Move the still-used helpers into `drafting.py`, delete the rest, drop `tests/test_review_state.py`. ~1k lines of legacy gone in one PR. (Already flagged in past Claude critiques per `archived/2026-05-02-claude-critiques-acknowledged/`.)
2. **Split `gui/desktop.py`.** First cut: `gui/theme.py`, `gui/bot_process.py`, `gui/settings_wizard.py`, `gui/dashboard.py`. Even without behavior changes, the navigability win is large.
3. **Split `bot_runtime.py` actions.** One module per `--action`, registered in a small dispatch table. `bot_runtime.py` becomes the argparse + dispatch shell.
4. **Add `.github/workflows/test.yml`.** `uv sync && uv run pytest` on Linux + macOS. Keeps the 202-test invariant honest.
5. **Add a 7-day activity strip to the dashboard.** `drafted / skipped / failed` per day, read straight from JSONL logs. Single bar chart, no new state.
6. **Pre-flight Ollama check in the wizard.** If `OllamaClient.list_models()` raises, show a single banner "Ollama isn't running — start it and click retry" before the model dropdown.
7. **Tighten `requires-python` to `>=3.11`.** Magali's machine and the packaged Mac are already there; clearer support promise.
8. **Move SOPs to `docs/sops/` and keep root markdown to ~6 files.** Mechanical change, big "first impression" win for new readers.

---

## TL;DR

MailAssist is a tightly-scoped product with an unusually disciplined safety posture and a bot/GUI split that fits its slow-LLM reality. The two pieces of obvious technical debt are a 3.8k-line god-object GUI class and a 1k-line legacy module that production code no longer imports. Neither is dangerous, both are worth a focused refactor before the Windows/Outlook destination becomes the daily driver. The product is closer to "Magali can use this" than the docs let on; the gap is mostly onboarding polish and a few UI affordances, not core architecture.
