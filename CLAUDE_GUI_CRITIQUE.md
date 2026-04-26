# GUI Critique — MailAssist

Two GUIs exist: a **PySide6 desktop app** (`gui/desktop.py`) and a **web-based config/review GUI** (`gui/server.py`). Each has distinct issues.

---

## Desktop GUI (`gui/desktop.py`)

### CRITICAL: Review pane is missing entirely

`_build_ui` only builds the hero, status overlay, Bot Control group, and Recent Activity log. It never constructs `self.thread_table`, `self.detail_panel`, `self.candidate_tabs`, `self.thread_title`, `self.thread_body`, `self.classification_filter`, `self.status_filter`, `self.show_archived`, or any of the candidate action buttons (`use_candidate_button`, `ignore_thread_button`, etc.).

All of those are referenced in `refresh_queue`, `render_current_thread`, `current_context`, and `_refresh_candidate_action_state` — but they don't exist. Any bot action that completes and calls `self.refresh_queue()` will crash with `AttributeError`. The desktop GUI cannot review emails at all in its current form.

**Fix needed:** Either build the review pane inside `_build_ui` (thread table + splitter + detail panel + candidate tabs + action buttons), or remove the dead review-related methods and rename the desktop app to a "bot control monitor" with no pretense of review.

---

### Bot Control is the only visible section

The sole thing a user sees is: bot status labels, three action buttons (Run Mock Pass, Create Gmail Test Draft, Queue Status), and a large read-only activity log. There is no way to open an email, read a thread, or act on a draft from the desktop app.

This is either a design gap or an intentional constraint. Either way, it should be reflected in the window title and help text — "MailAssist Desktop Review" is misleading if no review is possible.

---

### Settings dialog mixes concerns across tabs

The **Signature** tab (`_build_signature_settings_panel`) contains three unrelated things: the signature block, the default tone, and the bot poll interval. Tone and poll interval belong in a "Bot behavior" or "General" tab, not under "Signature."

---

### Fake progress bar with `time.sleep` in the worker thread

`CandidateRegenerationWorker._emit_partial_chunk` calls `time.sleep(0.01)` to "give the main thread a chance to paint." This is fragile: it blocks the worker thread unnecessarily and is not a reliable cross-thread coordination mechanism. The progress bar is also set to indeterminate (`setRange(0, 0)`) and then uses `setFormat` to fake a char-count display that isn't really progress. A pulsing indeterminate bar with a clear label ("Streaming from Ollama — 382 chars") would be cleaner and honest.

---

### Hard-coded 1440×980 initial window size

`self.resize(1440, 980)` will overflow or look bad on a 1280×800 or 13" laptop. No minimum size is set. Use a percentage of the screen or `showMaximized()` with a sensible minimum.

---

### No keyboard shortcuts

Common review actions (select next thread, accept draft, ignore, close) have no keyboard bindings. For a review tool that processes multiple emails daily, keyboard-first navigation is essential.

---

### Bot status label has no visual differentiation

"Running" and "Idle" are rendered identically in plain text. Running should at minimum be a different color (green or amber) so the bot state is visible at a glance without reading the label.

---

### "Create Gmail Test Draft" in the main Bot Control panel

`gmail_draft_test_button` creates a draft in a live Gmail account. This is a destructive test action. It should be behind a confirmation dialog or moved to a developer/debug section, not placed next to "Run Mock Pass."

---

## Web GUI (`gui/server.py`)

### Filters require an explicit "Apply" button

Changing a filter dropdown does not apply the filter immediately — the user must click "Apply queue view." On a review tool used repeatedly, this is friction. Filters should auto-submit on change (a small `onchange="this.form.submit()"` on each select), or at minimum, the button should be positioned directly below the filters and labeled "Filter" not "Apply queue view."

---

### Synchronous Ollama calls block the browser

`/regenerate-thread` and `/test-ollama` call Ollama synchronously inside the request handler thread. Ollama can take 1–3 minutes. The browser will appear completely frozen with no feedback — no spinner, no loading state, nothing. For a local tool this is survivable, but there is zero indication to the user that work is happening. At minimum, the form buttons should be disabled via JS on submit and replaced with "Working…"

---

### Hero description is developer changelog copy

The hero `<p>` reads: *"The operator flow is now centered on green lights and red lights, with queue triage up front. Use Ollama's classification signal to separate urgent mail from automated or spammy threads before anyone spends time editing a response."*

This is a developer changelog note, not UI copy. A real user doesn't need to know how the flow was redesigned. Replace it with a one-sentence description of what the tool does and what the user should do next.

---

### ISO timestamps in email message cards

Message cards display raw ISO 8601 timestamps (`2026-04-24T08:30:00Z`) in the summary line. These should be formatted as relative or human-readable dates ("Apr 24, 8:30 AM" or "2 hours ago").

---

### "Green light" / "Red light" terminology is unexplained

The primary actions are "Green light this draft" and "Red light this draft." These are not standard email client terms. There is no tooltip, no legend, and no explanation anywhere on the page. First-time users will be confused about what "green light" actually does (it marks the draft as selected and sets the thread to `use_draft`). Rename to "Select this draft" and "Dismiss this draft" — or keep the branding but add a tooltip.

---

### Internal metadata shown in candidate cards

Every candidate card header displays: the raw `tone` string (e.g., `direct and executive`), the model name (e.g., `qwen3:8b-instruct` or `fallback`), and a classification pill inside the card itself. This is implementation metadata. Users acting on a draft don't need to know which model generated it or see the classification repeated inside each card (it's already shown at the thread level). Hide these behind a disclosure or remove them from the card header.

---

### Thread status labels not normalized to user-friendly strings

Thread list cards show `pending_review` as "pending review" and `use_draft` as "use draft" — just via `.replace('_', ' ')`. "use draft" is not a meaningful status phrase for a user. Use the same human labels already defined elsewhere (`_status_label` in `desktop.py`): "Needs review," "Draft selected," "Ignored," "User replied."

---

### No confirmation before red-light or ignore

"Red light this draft" is an immediate POST form submit. Clicking it by accident has no undo. At minimum, add a `onclick="return confirm('Mark this draft as red-lit?')"` to destructive actions, or introduce an undo banner ("Draft red-lit. [Undo]") that reverses the action within a few seconds.

---

### Settings buried in collapsible at page bottom

"Operator settings" (Ollama URL, model selection, provider config) is in a `<details>` element at the very bottom of the page, collapsed by default. On first run, the user must scroll past the hero, the inbox, the thread body, and the candidate cards before reaching Ollama configuration. If Ollama isn't configured, no drafts will generate. Settings should surface on an empty-state screen or at minimum be linked from a visible "Settings" button near the top.

---

### Inbox panel has no explicit overflow scroll

The inbox panel is `position: sticky; top: 18px`. If there are many threads, the `.thread-list` container grows taller than the viewport with no scroll container. Add `max-height: calc(100vh - 60px); overflow-y: auto;` to the inbox panel's thread list.

---

## Shared Issues (Both GUIs)

| Issue | Desktop | Web |
|---|---|---|
| No keyboard shortcuts for review actions | Yes | Yes |
| No confirmation for destructive actions | Yes | Yes |
| No empty state when candidate list is empty | Yes | Yes |
| Ollama model name ("fallback") exposed to user | Yes | Yes |
| Tone options ("direct and executive") shown verbatim | Yes | Yes |

---

*Critique generated 2026-04-26 from code review of `src/mailassist/gui/desktop.py` and `src/mailassist/gui/server.py`.*
