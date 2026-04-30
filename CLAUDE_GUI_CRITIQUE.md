# GUI Critique — MailAssist Desktop App

*Originally reviewed 2026-04-26 against `gui/desktop.py` (1768 lines). Refreshed 2026-04-30 against `main` at `146b8c9` (v61.10) — `gui/desktop.py` is now 3085 lines, 191 tests green.*

The desktop app remains the only GUI surface; the web GUI is gone. This is still the right scoped direction.

---

## Resolved Since 2026-04-26

- **Dead `_build_settings_dialog` / `open_settings_dialog`** — `_build_settings_dialog` is now the live constructor of the wizard's hosting `QDialog` (`desktop.py:730`); `open_settings_wizard` (`desktop.py:720`) builds, shows, and raises it. The old non-existent `self.settings_tabs` reference is gone.
- **"Create Gmail Test Draft" with no confirmation** — the button now triggers a dry-run-only Gmail preview (`run_gmail_draft_test` at `desktop.py:2522`, `dry_run=True`). Real provider-write actions (`run_controlled_gmail_draft`, organizer runs, controlled Outlook smoke tests) are kept behind explicit `QMessageBox.question` confirmations.
- **Bot status pill visually undifferentiated** — `_PILL_STYLES` (`desktop.py:1838`) provides distinct styling for `ok`, `running`, `idle`, `warning`, `error` levels; `_paint_status_pill` paints the bot/provider/Ollama labels accordingly.
- **Progress bar advancing on a fake 180 ms timer** — replaced with `_start_indeterminate_progress` / `_finish_indeterminate_progress` (`desktop.py:1822–1834`) which use `setRange(0, 0)` for the standard pulsing indeterminate bar with a label.
- **Hard-coded 1120×680 initial size** — the window now uses `self._initial_window_size()` and constrains itself against the available screen geometry.
- **`QApplication.processEvents()` in `test_ollama`** — removed; the model-test path is now driven through the same `run_bot_action` plumbing as the rest.
- **No keyboard shortcuts** — `QShortcut` / `QKeySequence` are imported and registered (`desktop.py:363`).
- **Fragile settings-stack stable-height bookkeeping** — the `settings_group_stable_height` / `settings_wizard_stable_height` machinery has been removed; the wizard now leans on Qt's normal size-policy handling.

---

## 1. `MailAssistDesktopWindow` is a 3085-line single class

The whole desktop GUI lives in one class with ~145 methods and 1058 `self.` references inside one file. The file grew 74% (1768 → 3085) in four days as Outlook controls, organizers, the Tone-page Elders editor, the Categories editor, Recent Activity heartbeats, and Settings tabs accreted. Every new feature has to land on the same object, and `test_desktop_layout.py` is now 1527 lines because there is no smaller seam to test against.

This is now the dominant GUI risk — the original critique's specific defects (status pill, fake progress, dead dialog) have been fixed, but the megaclass has roughly doubled in size at the same time. The top-level fix is to extract the major panels into their own `QWidget` subclasses that the main window composes:

- Settings wizard pages (Ollama, Providers, Signature/Tone, Advanced) → one widget per page in `gui/settings/`
- Bot Control panel (action buttons, banner, progress bar) → `gui/bot_control.py`
- Recent Activity panel (list, Report button, Clear button, heartbeat hooks) → `gui/recent_activity.py`
- Tone-page Elders editor and MailAssist Categories editor → small dialog widgets

Each extraction lets `test_desktop_layout.py` shrink and lets future panels (e.g., a draft preview pane) land without piling on the same class.

---

## 2. Confirmation copy is repeated verbatim across actions

Six call sites use the `QMessageBox.question(self, title, text, Yes|No, No)` pattern with the same default-No, same Yes|No buttons, and very similar copy patterns ("This will…", "Run anyway?"). They live in: `run_controlled_gmail_draft` (1032), Elders remove (1708), model-test confirm (2419), and the three organizer/draft actions (2540, 2578, +). A small `_confirm_action(title, body)` helper would remove ~6 copies of the same six-line block and make it harder to forget the default-No safety the user has already chosen as the standard.

This is a small-but-persistent maintenance leak rather than a behavioral bug.

---

## 3. Dialog modality is inconsistent

Two long-lived dialogs are explicitly created `setModal(False)` — the settings dialog (`desktop.py:732`) and the bot logs dialog (`desktop.py:658`). Most short-lived dialogs (confirmations, Add Elder) use `QMessageBox` and are modal by default. This is fine in principle, but two issues follow from the non-modal settings dialog:

- A user can start a bot action while the Settings wizard is still open. The bot action then re-reads `Settings` from `.env`, which Settings has *already* mutated in memory but not yet persisted. The window the wizard uses to "save" is partly tied to the `Save` step button. Result: actions launched from the main window during an open Settings session can pick up partially edited settings.
- The settings dialog tracks `self.settings_open` and uses `_refresh_setup_visibility` to guard related UI, but there is no guard against starting a bot action while the dialog is open.

Either make the settings dialog modal, or disable the bot action row while `self.settings_open` is true (analogous to the `_bot_action_already_running` gating that already exists).

---

## 4. `run_bot_action` runs each action as a fresh `QProcess`

Every bot action — `run-mock`, `watch-once`, `watch-loop`, `outlook-smoke-test`, `gmail-populate-labels`, etc. — is launched as a brand-new Python subprocess via `QProcess` (`desktop.py:2666–2669`). Each subprocess re-parses argv, re-imports `mailassist`, re-runs `migrate_legacy_runtime_layout`, re-loads `.env`, re-instantiates the provider, and re-discovers the account email. For a `watch-once` preview that takes 90 seconds, the per-launch cost is small. For a loop of `watch-once` invocations during development, or for the Recent Activity heartbeat scheduling, it is significant overhead.

This was a deliberate isolation choice (a stuck Ollama call cannot freeze the GUI) and the choice itself is sound. But two consequences are worth either documenting or addressing:

- Provider auth state has to be re-discovered every action. The Outlook OAuth refresh-token round-trip alone is multiple hundred ms per launch.
- Heartbeat plumbing relies on parsing JSONL stdout from the subprocess, which means the GUI's progress signaling is *always* at least one full subprocess startup behind the actual work.

A cooperative `QThread`-based bot worker — same isolation against Ollama hangs, but a single long-lived Python interpreter — would remove the per-action startup tax. This is a larger refactor and only worth doing if the per-action cost shows up in the Magali deployment.

---

## 5. Three explicit `QTimer`s coordinate the bot/Ollama UX

`bot_heartbeat_timer`, `bot_timeout_timer`, and `ollama_test_countdown_timer` (`desktop.py:332–340`) plus two `QTimer.singleShot` calls (`desktop.py:1396, 2454`) coordinate heartbeat lines, watchdog timeouts, and a delayed model-list refresh. Each is set up in `__init__` and torn down in different code paths. The original critique flagged the `progress_timer` for advancing fake progress; that is gone, but the GUI now has more timers, not fewer.

The risk is timer leakage between actions: the bot heartbeat timer is started when an action begins and stopped on completion, but if a completion event is missed (e.g., `QProcess` errored before stdout was parsed), the heartbeat keeps emitting. There is no centralized "active timers belonging to action X" tracking. A small `BotActionTimers` helper that owns the trio and is started/stopped as a unit would make leak debugging tractable.

---

## 6. Status overlay logic is split between banner, pill, and progress bar

User-visible state is communicated through three independent surfaces:

- The banner (`_set_banner`) at the top of the window
- The pill labels in the status row (`_paint_status_pill`)
- The progress bar (`_start_indeterminate_progress` / `_finish_indeterminate_progress`)

Each is updated by a different method, and `_refresh_status_overlay_visibility` reconciles them. A bot action can leave the banner reading "Idle" while the pill still says "running" if a code path forgets to call one of them. The reconciliation method exists but it depends on the action paths calling the right setters in the right order. A single `set_app_state(level, message, progress=None)` entry point would collapse this into one place.

This is preventive — no specific bug is currently visible — but the surface area has grown enough that this kind of consolidation is overdue.

---

## 7. `test_desktop_layout.py` exercises the full window per test

The new test file (1527 lines) uses an offscreen Qt platform and constructs `MailAssistDesktopWindow()` per test. Tests are slow because each one boots the full GUI tree; they are also brittle because a layout change in one panel can break a test asserting button geometry in another. Per-panel tests against extracted widgets (Issue 1) would address this.

---

## Summary

| # | Issue | Severity | Δ vs. 2026-04-26 |
|---|---|---|---|
| 1 | `MailAssistDesktopWindow` is a 3085-line single class | High | New (was 1768 lines) |
| 2 | Confirmation copy duplicated across six call sites | Low | New |
| 3 | Settings dialog non-modal; bot can start with unsaved settings | Medium | New |
| 4 | Each bot action is a fresh `QProcess` with full startup tax | Medium | New |
| 5 | Three separate `QTimer`s coordinate bot UX with no central owner | Low–Medium | New |
| 6 | Banner / pill / progress bar are three independent surfaces | Low | New |
| 7 | `test_desktop_layout.py` slow and brittle because it exercises the full window | Low | New (no tests existed Apr 26) |
