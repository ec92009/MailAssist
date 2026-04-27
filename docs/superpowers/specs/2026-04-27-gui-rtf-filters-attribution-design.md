# GUI Polish — RTF Signatures, Live Watcher Filters, Attribution

Date: 2026-04-27
Status: Approved (pending user review of this written spec)
Owner: Codex

## Goal

Deliver three TODO.md GUI/draft polish items as one cohesive change to the Codex-managed
desktop control panel:

1. Offer RTF formatting for signatures (with Gmail HTML passthrough).
2. Let the user filter which emails the live watcher scans (unread-only and
   time window).
3. Offer to add an optional attribution line to drafts (MailAssist + Ollama +
   model name).

The work also lays a small contract that Codex's future real-provider polling
must honor for filtering, so the GUI side stays useful when Codex implements
real Gmail/Outlook polling later.

## Non-Goals

- Real Gmail/Outlook inbox polling. The watcher contract is defined here, but
  the actual provider polling implementation is Codex's P2 work.
- Outlook draft creation. Outlook provider is not yet wired.
- Editable attribution templates. The attribution line is fixed.
- Bullet lists, color, font size in the RTF signature editor — explicitly out
  of scope (minimal: bold, italic, link).

## Settings — New Env Vars

Five total. Persisted in `~/Library/Application Support/MailAssist/.env`
through the existing `read_env_file` / `write_env_file` helpers.

| Var | Type | Default |
|---|---|---|
| `MAILASSIST_USER_SIGNATURE_HTML` | sanitized HTML string | `""` |
| `MAILASSIST_WATCHER_UNREAD_ONLY` | bool (`true`/`false`) | `false` |
| `MAILASSIST_WATCHER_TIME_WINDOW` | enum: `all` \| `24h` \| `7d` \| `30d` | `all` |
| `MAILASSIST_DRAFT_ATTRIBUTION` | bool | `false` |

`Settings` (in `src/mailassist/config.py`) gains four matching fields:

```python
user_signature_html: str
watcher_unread_only: bool
watcher_time_window: str   # "all" | "24h" | "7d" | "30d"
draft_attribution: bool
```

`load_settings()` reads each via the existing `parse_bool` / direct env reads.
The plain `user_signature` remains canonical and unchanged.

## Section 1 — RTF Signatures + Gmail HTML Passthrough

### Storage

- `MAILASSIST_USER_SIGNATURE` (existing) stays the canonical plain-text form.
  Used in prompts, mock drafts, and as the fallback when no HTML form exists.
- `MAILASSIST_USER_SIGNATURE_HTML` (new) holds the optional sanitized HTML
  form. Empty string means "no rich form."
- The `\n` ⇄ literal-`\n` round-trip used by the existing plain signature
  field is preserved. The HTML form does not need it (HTML uses `<br>`).

### Editor

The wizard's Signature page replaces `QPlainTextEdit` with `QTextEdit` in
rich-text mode (`setAcceptRichText(True)`). A small horizontal toolbar above
the editor exposes:

- **Bold** (`Ctrl+B`) — `setFontWeight(Bold/Normal)` toggle.
- **Italic** (`Ctrl+I`) — `setFontItalic` toggle.
- **Insert Link** (`Ctrl+K`) — opens a small `QDialog` with two fields
  ("Visible text" prefilled from selection, "URL"). On accept, inserts an
  anchor over the selection.

Format toolbar is small (3 buttons), top-right of the editor area, matching
the existing button styling.

### Sanitizer

A new tiny module `src/mailassist/sanitize.py` exposes:

```python
ALLOWED_HTML_TAGS = ("b", "strong", "i", "em", "a", "br")

def sanitize_signature_html(html: str) -> str: ...
def signature_html_to_plain(html: str) -> str: ...
```

Implementation is regex-based, no new dependencies (mirrors the existing
`_gmail_signature_to_text` approach in `providers/gmail.py`). It:

- Strips every tag not in `ALLOWED_HTML_TAGS`.
- For `<a>`, keeps only `href`. URL must start with `http://`, `https://`, or
  `mailto:` — otherwise the tag is dropped (text retained).
- Strips event handlers (`on*`), `style`, `class`, `id`.
- Collapses whitespace runs but preserves `<br>` breaks.

`signature_html_to_plain` reuses the same regex unrolling used for Gmail's
HTML-to-text conversion, then trims.

### Save flow

`save_settings()` writes both:

```python
"MAILASSIST_USER_SIGNATURE": <plain text from editor>.replace("\n", "\\n"),
"MAILASSIST_USER_SIGNATURE_HTML": sanitize_signature_html(<editor toHtml()>),
```

Plain text is computed from `signature_input.toPlainText()` so the canonical
plain version always matches what the user sees. HTML is the sanitized form
of `signature_input.toHtml()`.

### Gmail import

`_import_gmail_signature` already retrieves the raw signature HTML through
the Gmail API. New behavior:

- Sanitize the HTML through `sanitize_signature_html`.
- Compute the plain form via `signature_html_to_plain` (replaces the current
  `_gmail_signature_to_text` call inside `providers/gmail.py` for the import
  path; the function moves to `sanitize.py` for reuse).
- Set both into the editor: `signature_input.setHtml(sanitized_html)`. The
  editor's `toPlainText()` then returns the plain form automatically.

Precedence stays "user edits win" (Question 7 option A): the auto-import on
first wizard visit only runs when the editor is empty; the explicit "Import
from Gmail" button always overwrites.

### Draft creation

`background_bot.py` already calls `append_signature_to_body` after the LLM
returns. New flow:

1. Compose plain body using existing `append_signature` (unchanged).
2. If `settings.user_signature_html` is non-empty, also compose an HTML body:
   - Convert plain LLM body to HTML (replace `\n` with `<br>`, escape `<>&`).
   - Append `<br><br>` + the sanitized HTML signature.
3. Pass both forms to the provider via a new `body_html: str | None` field
   on `DraftRecord` (defaults to `None`).

Gmail provider:

- If `draft.body_html` is `None` → current `MIMEText(body)` path (plain).
- If `draft.body_html` is set → build `MIMEMultipart('alternative')` with a
  `MIMEText(body, 'plain')` part and a `MIMEText(body_html, 'html')` part.
  Subject + recipients identical.

Mock provider keeps writing JSON files with the plain body only (HTML is
ignored — mock drafts have no rendering surface).

### Prompt

Unchanged. The LLM continues to receive only the plain signature in
`signature_prompt_block(signature)`. HTML is appended at draft-assembly time,
after the model's substantive body. The model never sees HTML.

## Section 2 — Live Watcher Filters

### Contract

New module `src/mailassist/live_filters.py`:

```python
from dataclasses import dataclass
from datetime import datetime
from mailassist.models import EmailThread

TIME_WINDOW_SECONDS = {
    "all": None,
    "24h": 24 * 3600,
    "7d": 7 * 24 * 3600,
    "30d": 30 * 24 * 3600,
}

@dataclass(frozen=True)
class WatcherFilter:
    unread_only: bool
    max_age_seconds: int | None  # None = no time limit

    @classmethod
    def from_settings(cls, settings) -> "WatcherFilter": ...

def thread_passes_filter(
    thread: EmailThread,
    filter: WatcherFilter,
    now: datetime,
) -> tuple[bool, str | None]: ...  # (passes, reason_if_skipped)
```

`thread_passes_filter` is a pure function. Reasons returned: `"unread"` (when
filter requires unread but thread isn't), `"time_window"` (when latest
message is older than the window), or `None` (passes).

Time check parses `thread.messages[-1].sent_at` via
`datetime.fromisoformat(value.replace("Z", "+00:00"))` and compares against
`now - timedelta(seconds=max_age_seconds)`. A malformed or empty `sent_at`
fails closed (treated as outside the window) and the skip reason is
`"time_window"`.

### EmailThread change

`models.EmailThread` gains an optional field:

```python
unread: bool = True
```

Default `True` so existing fixture/mock paths and tests keep their current
semantics under an unread-only filter. `from_dict` reads `payload.get("unread", True)`.

Real-provider polling (Codex's later work) sets `unread` from provider state.

### Watch pass

`run_mock_watch_pass` reads `WatcherFilter.from_settings(settings)` once at
the top. For each thread, before classification:

```python
passes, reason = thread_passes_filter(thread, watcher_filter, now=utcnow())
if not passes:
    events.append({
        "type": "filtered_out",
        "thread_id": thread.thread_id,
        "subject": thread.subject,
        "reason": reason,  # "unread" or "time_window"
    })
    continue
```

The `filtered_out` event is also surfaced in `bot_runtime.py` aggregations
(adds `filtered_out_count` to the `completed` event for `watch-once` and
`watch-loop`).

### Provider hook (future)

`DraftProvider` (in `providers/base.py`) gains an optional method:

```python
def list_actionable_threads(self, filter: WatcherFilter) -> list[EmailThread]:
    raise NotImplementedError
```

Mock provider implements it as `[t for t in build_mock_threads() if thread_passes_filter(t, filter, now)[0]]`. Gmail provider does not yet implement it (raises). Codex's later real-polling work fills this in by translating the filter to `q=is:unread newer_than:7d` for Gmail and the equivalent Microsoft Graph query for Outlook.

The current watch pass keeps using `build_mock_threads()` directly + filter,
because real polling isn't here yet. Once Codex lands `list_actionable_threads`
on real providers, the watch pass switches to that call.

### Wizard

The "Choose Email Provider" step (step 0) gets a new `Watch only` group below
the Gmail/Outlook checkboxes:

```
┌─ Watch only ─────────────────────────────┐
│  [✓] Unread emails only                  │
│  Time window:                            │
│    ◯ All  ◯ 24h  ●  7d  ◯ 30d            │
└──────────────────────────────────────────┘
```

Implemented as a `QCheckBox` and a `QButtonGroup` of four `QRadioButton`s.
Saved through the existing `save_settings()` flow (added to the `current.update({...})` block).

### Dashboard

The status grid in the Bot Control group gains one row:

```
Filter: Unread, last 7 days
```

Built by `_describe_filter(settings)`:

- `"All emails"` when filter is off.
- `"Unread"` / `"Last 24 hours"` / `"Unread, last 7 days"` etc. depending on
  what's set.

`refresh_dashboard()` calls it on each refresh.

## Section 3 — Attribution Toggle

### Setting

`MAILASSIST_DRAFT_ATTRIBUTION` (bool, default `false`).

### Wizard

A new `QCheckBox` on the Signature wizard page, below the editor:

```
[ ] Add a small "Drafted with MailAssist" line at the bottom of each draft.
    (Includes the local model name. Off by default.)
```

Persisted via `save_settings()`.

### Content

`Drafted with MailAssist using Ollama ({model}).` where `{model}` is the
configured Ollama model name (`settings.ollama_model`).

### Helpers

New module `src/mailassist/attribution.py`:

```python
def attribution_text(model: str) -> str:
    return f"Drafted with MailAssist using Ollama ({model})."

def attribution_html(model: str) -> str:
    return (
        '<p style="color:#888;font-style:italic;margin-top:12px">'
        f'Drafted with MailAssist using Ollama (<code>{model}</code>).'
        '</p>'
    )
```

Caller checks `settings.draft_attribution` before invoking.

### Insertion

Plain body: after `append_signature`, append `\n\n` + `attribution_text(model)`
when enabled.

HTML body: after the HTML signature block, append `attribution_html(model)`.

Mock provider writes the plain attribution into its JSON. Gmail provider's
multipart parts each get the matching form.

## Files Touched

| File | Change |
|---|---|
| `src/mailassist/config.py` | New env vars on `Settings`; `load_settings` updates |
| `src/mailassist/live_filters.py` *(new)* | `WatcherFilter`, `thread_passes_filter`, `TIME_WINDOW_SECONDS` |
| `src/mailassist/models.py` | `EmailThread.unread` field; `DraftRecord.body_html` field |
| `src/mailassist/sanitize.py` *(new)* | `sanitize_signature_html`, `signature_html_to_plain` |
| `src/mailassist/attribution.py` *(new)* | `attribution_text`, `attribution_html` |
| `src/mailassist/background_bot.py` | Filter check; HTML body assembly; attribution insertion; `filtered_out` event |
| `src/mailassist/bot_runtime.py` | Aggregate `filtered_out_count` for `watch-once` and `watch-loop` completion events |
| `src/mailassist/providers/base.py` | Optional `list_actionable_threads` |
| `src/mailassist/providers/mock.py` | Implements `list_actionable_threads`; ignores `body_html` |
| `src/mailassist/providers/gmail.py` | Multipart draft when `body_html` is set; sanitized HTML signature import |
| `src/mailassist/gui/desktop.py` | RTF editor + toolbar + link dialog; filter widgets on provider wizard page; attribution checkbox on signature page; dashboard filter row |
| `tests/` | New unit + integration tests (see Testing) |

## Testing

### Unit

- **`live_filters`** — every combination: filter off, unread-only, each time
  window. Boundary cases: thread exactly at window edge, malformed `sent_at`,
  empty thread.
- **`sanitize`** — allowlisted tags survive; `<script>`, `<img>`, inline
  `style`/`onclick`, non-http/mailto `href` are stripped; round-trip with
  Gmail-style nested HTML produces stable plain output.
- **`attribution`** — text vs HTML output; empty/disabled case.

### Integration

- **Gmail draft assembly** — confirms `MIMEMultipart('alternative')` is built
  with both parts when `body_html` is set; confirms plain `MIMEText` path
  unchanged when not. Uses a stub Gmail service.
- **Mock watch pass with filter** — a fixture thread older than 24h is
  skipped when window=`24h`; `filtered_out` event is emitted with reason
  `time_window`. An unread=False fixture is skipped when `unread_only=true`.
- **Settings round-trip** — saving a wizard state writes all four new env
  vars; reloading reconstitutes the same `Settings`.

### Manual / smoke (per CLAUDE.md)

- Launch desktop GUI from source.
- Walk wizard end-to-end with each new control.
- Run a mock pass; confirm filter row reflects current settings; confirm
  `filtered_out` events appear in Recent Activity when applicable.
- Toggle attribution on, run mock pass, confirm attribution appears in the
  written mock draft JSON.

## Risks

- **`QTextEdit` HTML output is verbose.** `toHtml()` returns a full HTML
  document with Qt-specific styles. The sanitizer strips everything outside
  the allowlist; expect very small output. Verified during implementation.
- **Mock fixture timestamps drift.** The mock fixtures use static `sent_at`
  values from 2026-04-24. As real time advances, the `24h` filter will start
  excluding everything in mock. Acceptable: this is realistic test material
  (and the `7d` / `30d` / `all` windows still work).
- **Email body HTML escaping.** When wrapping LLM plain-text in HTML, must
  escape `<`, `>`, `&` before adding `<br>`. Tested.

## Rollout

Single PR, all three features together. Visible version bumps once
(`v56.48`). Per CLAUDE.md: smoke test, refresh `README.md` and `SUMMARY.md`,
commit, push.
