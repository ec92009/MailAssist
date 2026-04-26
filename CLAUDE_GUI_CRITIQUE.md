# GUI Critique — MailAssist Desktop App

*Reviewed 2026-04-26 against `src/mailassist/gui/desktop.py` (1768 lines).*

The web GUI (`gui/server.py`) was removed. The only GUI is the PySide6 desktop app. It is a bot control panel: it shows bot status, runs mock/live passes, and hosts the settings wizard. There is no review pane. This is the correct scoped direction per TODO P4.

---

## 1. Dead method: `_build_settings_dialog`

`_build_settings_dialog` (line 384–413) builds a tab-based QDialog with tabs for Ollama, Providers, Signature, and Prompt. This dialog is never shown. The wizard (`_build_settings_wizard`) replaced it. `open_settings_dialog` (line 479–483) references `self.settings_tabs` which does not exist and only falls through to show a banner.

Both `_build_settings_dialog` and `open_settings_dialog` are dead code. Remove them.

---

## 2. "Create Gmail Test Draft" has no confirmation

```python
# desktop.py:1495
def run_gmail_draft_test(self) -> None:
    self.run_bot_action("watch-once", provider="gmail", thread_id="thread-008", force=True)
```

Clicking this button immediately triggers a live Gmail draft on the user's connected account with no confirmation dialog. It sits next to "Run Mock Pass" in the Bot Control panel. An accidental click has no undo path. It should either require a confirmation dialog or be moved to a developer/debug section, as already identified in TODO P3.

---

## 3. Bot status label is visually undifferentiated

```python
# desktop.py:353
widget.setStyleSheet("color: #1d2430; font-size: 14px;")
```

"Running" and "Idle" are rendered with the same style. Bot state is not visually scannable — the user must read the label to know whether a process is active. Running should use a distinct color (e.g., amber or green). This is already in TODO P4.

---

## 4. Progress bar advances on a timer, not on actual progress

```python
# desktop.py:189–191
self.progress_timer = QTimer(self)
self.progress_timer.setInterval(180)
self.progress_timer.timeout.connect(self._advance_fake_progress)
```

The bar advances on a 180ms timer regardless of what Ollama is doing. For operations that take 1–2 minutes this is decorative. A pulsing indeterminate bar (`setRange(0, 0)`) with a label like "Waiting for Ollama..." would be more honest and eliminate the timer state. This is already in TODO P4.

---

## 5. Hard-coded 1120×680 initial window size

```python
# desktop.py:206
self.resize(1120, 680)
```

No minimum size is set against the screen. On a 13" laptop at non-retina scaling this can overflow. `QScreen.availableGeometry()` should constrain the initial size, or `showMaximized()` with a reasonable minimum should be used. This is already in TODO P4.

---

## 6. `QApplication.processEvents()` in `test_ollama`

```python
# desktop.py:1489
QApplication.processEvents()
self.run_bot_action("ollama-check", prompt=prompt)
```

`processEvents()` is called to force the UI to update before launching the bot subprocess. This is a pattern that typically indicates missing proper async or signal/slot wiring. It works here because `run_bot_action` immediately returns after starting `QProcess`, but the explicit `processEvents()` call suggests the UI update path is fragile. The banner update before it should be sufficient without forcing event processing.

---

## 7. No keyboard shortcuts

There are no `QShortcut` or `QAction` bindings. Common macOS conventions like ⌘, for Settings, ⌘R for Run Mock Pass, and Escape to dismiss the banner are missing. Lower priority than correctness issues, but expected by macOS users.

---

## 8. Settings wizard stable-height bookkeeping is complex

The wizard tracks `settings_group_stable_height` and `settings_wizard_stable_height`, calls `_sync_settings_stack_height()` and `_restore_geometry_after_layout()` in several places to prevent the window from resizing as wizard pages change. This machinery is fragile — any page that changes its preferred height unexpectedly can cause layout jumps. A `QScrollArea` wrapping the wizard content would make this unnecessary.

---

## Summary

| Issue | Severity |
|---|---|
| Dead `_build_settings_dialog` method and `open_settings_dialog` referencing non-existent widget | Medium |
| "Create Gmail Test Draft" triggers live account action with no confirmation | High |
| Bot status "Running"/"Idle" visually identical | Medium |
| Progress bar advances on timer, not actual progress | Medium |
| Hard-coded 1120×680 initial size with no screen constraint | Low |
| `QApplication.processEvents()` in `test_ollama` — fragile UI update pattern | Low |
| No keyboard shortcuts | Low |
| Wizard stable-height bookkeeping is fragile; a scroll area would be simpler | Low |
