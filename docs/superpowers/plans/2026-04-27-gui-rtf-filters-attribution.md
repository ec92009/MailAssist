# GUI Polish — RTF Signatures, Watcher Filters, Attribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver three Codex-owned GUI/draft polish tasks (RTF signatures with Gmail HTML passthrough, live-watcher unread/time-window filter contract, optional draft attribution) as one cohesive change.

**Architecture:** Five new env vars layered on the existing `.env`/`Settings` shape. Pure helpers in three new modules (`live_filters`, `sanitize`, `attribution`) feed into `background_bot.py` and the Gmail provider. `EmailThread` gains an `unread` flag; `DraftRecord` gains `body_html`. The wizard's "Choose Email Provider" page hosts filter controls; the Signature page becomes a `QTextEdit` rich editor with a tiny toolbar and an attribution checkbox; the dashboard surfaces the active filter.

**Tech Stack:** Python 3.9+, PySide6 6.10+, regex-based HTML sanitizer (no new deps), `email.mime.multipart` for Gmail HTML drafts, pytest.

**Spec:** `docs/superpowers/specs/2026-04-27-gui-rtf-filters-attribution-design.md`

---

## File Structure

| Path | Status | Responsibility |
|---|---|---|
| `src/mailassist/config.py` | modify | Add four new fields to `Settings`; load four new env vars |
| `src/mailassist/models.py` | modify | `EmailThread.unread: bool = True`; `DraftRecord.body_html: str \| None = None` |
| `src/mailassist/sanitize.py` | new | `sanitize_signature_html`, `signature_html_to_plain` (regex-based, no deps) |
| `src/mailassist/live_filters.py` | new | `WatcherFilter` dataclass, `TIME_WINDOW_SECONDS`, `thread_passes_filter` |
| `src/mailassist/attribution.py` | new | `attribution_text`, `attribution_html` |
| `src/mailassist/background_bot.py` | modify | Filter check + `filtered_out` event; HTML body assembly; attribution insertion |
| `src/mailassist/bot_runtime.py` | modify | Aggregate `filtered_out_count` for `watch-once` and `watch-loop` completion events |
| `src/mailassist/providers/base.py` | modify | Optional `list_actionable_threads(filter)` declaration |
| `src/mailassist/providers/mock.py` | modify | Implement `list_actionable_threads`; ignore `body_html` |
| `src/mailassist/providers/gmail.py` | modify | Multipart draft when `body_html` set; sanitize HTML signature on import |
| `src/mailassist/gui/desktop.py` | modify | RTF editor + toolbar + link dialog; filter widgets; attribution checkbox; dashboard filter row |
| `tests/test_sanitize.py` | new | Unit tests for the HTML allowlist sanitizer |
| `tests/test_live_filters.py` | new | Unit tests for `WatcherFilter` and `thread_passes_filter` |
| `tests/test_attribution.py` | new | Unit tests for attribution helpers |
| `tests/test_config.py` | modify | Round-trip tests for the four new env vars |
| `tests/test_background_bot.py` | modify | Filter integration + HTML body + attribution integration tests |
| `tests/test_gmail_provider.py` | modify | Multipart draft test |
| `pyproject.toml` | modify | Version bump to `56.48.0` |
| `data/version.txt` (or equivalent) | modify | Visible version bump |
| `README.md` | modify | Document new wizard controls |
| `SUMMARY.md` | modify | Project snapshot refresh |

---

## Task 1: Add four new fields to `Settings`

**Files:**
- Modify: `src/mailassist/config.py`
- Modify: `tests/test_config.py`

- [x] **Step 1.1: Write the failing test**

Append to `tests/test_config.py`:

```python
def test_load_settings_reads_new_gui_polish_env_vars(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_USER_SIGNATURE_HTML": "<b>Best,</b><br>Ethan",
            "MAILASSIST_WATCHER_UNREAD_ONLY": "true",
            "MAILASSIST_WATCHER_TIME_WINDOW": "7d",
            "MAILASSIST_DRAFT_ATTRIBUTION": "true",
        },
    )

    settings = load_settings()

    assert settings.user_signature_html == "<b>Best,</b><br>Ethan"
    assert settings.watcher_unread_only is True
    assert settings.watcher_time_window == "7d"
    assert settings.draft_attribution is True


def test_load_settings_defaults_for_new_gui_polish_env_vars(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)

    settings = load_settings()

    assert settings.user_signature_html == ""
    assert settings.watcher_unread_only is False
    assert settings.watcher_time_window == "all"
    assert settings.draft_attribution is False
```

- [x] **Step 1.2: Run tests to verify they fail**

Run: `./.venv/bin/pytest tests/test_config.py::test_load_settings_reads_new_gui_polish_env_vars tests/test_config.py::test_load_settings_defaults_for_new_gui_polish_env_vars -v`

Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'user_signature_html'`.

- [x] **Step 1.3: Add fields to `Settings` dataclass**

In `src/mailassist/config.py`, extend the `Settings` dataclass:

```python
@dataclass(frozen=True)
class Settings:
    root_dir: Path
    data_dir: Path
    legacy_data_dir: Path
    drafts_dir: Path
    logs_dir: Path
    bot_logs_dir: Path
    mock_provider_drafts_dir: Path
    ollama_url: str
    ollama_model: str
    user_signature: str
    user_signature_html: str
    user_tone: str
    bot_poll_seconds: int
    default_provider: str
    gmail_enabled: bool
    outlook_enabled: bool
    gmail_credentials_file: Path
    gmail_token_file: Path
    outlook_client_id: str
    outlook_tenant_id: str
    outlook_redirect_uri: str
    watcher_unread_only: bool
    watcher_time_window: str
    draft_attribution: bool
```

- [x] **Step 1.4: Populate the new fields in `load_settings`**

In the `return Settings(...)` block of `load_settings`, add:

```python
        user_signature_html=os.getenv("MAILASSIST_USER_SIGNATURE_HTML", ""),
```

(immediately after the existing `user_signature=` line) and at the end of the `Settings(...)` call (before the closing paren), add:

```python
        watcher_unread_only=parse_bool(os.getenv("MAILASSIST_WATCHER_UNREAD_ONLY"), default=False),
        watcher_time_window=os.getenv("MAILASSIST_WATCHER_TIME_WINDOW", "all"),
        draft_attribution=parse_bool(os.getenv("MAILASSIST_DRAFT_ATTRIBUTION"), default=False),
```

- [x] **Step 1.5: Run tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_config.py -v`

Expected: all tests in `test_config.py` PASS.

- [x] **Step 1.6: Commit**

```bash
git add src/mailassist/config.py tests/test_config.py
git commit -m "Add settings fields for RTF signatures, watcher filters, attribution"
git push
```

---

## Task 2: Add `unread` to `EmailThread`

**Files:**
- Modify: `src/mailassist/models.py`

- [x] **Step 2.1: Write the failing test**

Create `tests/test_models.py` (new file):

```python
from mailassist.models import EmailThread


def test_email_thread_default_unread_true() -> None:
    thread = EmailThread(
        thread_id="t1",
        subject="Hello",
        participants=["a@example.com"],
        messages=[],
    )
    assert thread.unread is True


def test_email_thread_from_dict_reads_unread() -> None:
    payload = {
        "thread_id": "t1",
        "subject": "Hello",
        "participants": [],
        "messages": [],
        "unread": False,
    }
    thread = EmailThread.from_dict(payload)
    assert thread.unread is False


def test_email_thread_from_dict_defaults_unread_true_when_missing() -> None:
    payload = {
        "thread_id": "t1",
        "subject": "Hello",
        "participants": [],
        "messages": [],
    }
    thread = EmailThread.from_dict(payload)
    assert thread.unread is True
```

- [x] **Step 2.2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_models.py -v`

Expected: FAIL with `TypeError` or attribute error.

- [x] **Step 2.3: Add the `unread` field**

In `src/mailassist/models.py`, modify `EmailThread`:

```python
@dataclass
class EmailThread:
    thread_id: str
    subject: str
    participants: List[str]
    messages: List[EmailMessage]
    unread: bool = True

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "EmailThread":
        return cls(
            thread_id=payload["thread_id"],
            subject=payload["subject"],
            participants=list(payload.get("participants", [])),
            messages=[EmailMessage.from_dict(item) for item in payload.get("messages", [])],
            unread=bool(payload.get("unread", True)),
        )
```

- [x] **Step 2.4: Run tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_models.py tests/test_background_bot.py -v`

Expected: all PASS. (Run `test_background_bot.py` too to make sure default `unread=True` doesn't break the existing mock pass.)

- [x] **Step 2.5: Commit**

```bash
git add src/mailassist/models.py tests/test_models.py
git commit -m "Add unread flag to EmailThread (defaults True)"
git push
```

---

## Task 3: Add `body_html` to `DraftRecord`

**Files:**
- Modify: `src/mailassist/models.py`
- Modify: `tests/test_models.py`

- [ ] **Step 3.1: Write the failing test**

Append to `tests/test_models.py`:

```python
from mailassist.models import DraftRecord


def test_draft_record_default_body_html_none() -> None:
    record = DraftRecord(
        draft_id="d1",
        thread_id="t1",
        provider="mock",
        subject="Re: Hello",
        body="Hi there.",
        model="mock-model",
    )
    assert record.body_html is None


def test_draft_record_to_dict_includes_body_html_when_set() -> None:
    record = DraftRecord(
        draft_id="d1",
        thread_id="t1",
        provider="gmail",
        subject="Re: Hello",
        body="Hi there.",
        model="mock-model",
        body_html="<p>Hi there.</p>",
    )
    payload = record.to_dict()
    assert payload["body_html"] == "<p>Hi there.</p>"


def test_draft_record_from_dict_handles_missing_body_html() -> None:
    payload = {
        "draft_id": "d1",
        "thread_id": "t1",
        "provider": "mock",
        "subject": "Re: Hello",
        "body": "Hi there.",
        "model": "mock-model",
    }
    record = DraftRecord.from_dict(payload)
    assert record.body_html is None
```

- [ ] **Step 3.2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_models.py -v`

Expected: FAIL with attribute error on `body_html`.

- [ ] **Step 3.3: Add `body_html` to `DraftRecord`**

In `src/mailassist/models.py`, modify `DraftRecord`:

```python
@dataclass
class DraftRecord:
    draft_id: str
    thread_id: str
    provider: str
    subject: str
    body: str
    model: str
    to: List[str] = field(default_factory=list)
    cc: List[str] = field(default_factory=list)
    bcc: List[str] = field(default_factory=list)
    body_html: Optional[str] = None
    status: str = "pending_review"
    created_at: str = field(default_factory=utc_now_iso)
    provider_submission_status: str = "not_submitted"
    provider_draft_id: Optional[str] = None
    provider_thread_id: Optional[str] = None
    provider_message_id: Optional[str] = None
    provider_synced_at: Optional[str] = None
    provider_error: Optional[str] = None
    revision_notes: Optional[str] = None
```

In `from_dict`, add `body_html=payload.get("body_html")` after the `bcc=` line.

- [ ] **Step 3.4: Run tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_models.py tests/test_background_bot.py tests/test_gmail_provider.py -v`

Expected: all PASS.

- [ ] **Step 3.5: Commit**

```bash
git add src/mailassist/models.py tests/test_models.py
git commit -m "Add optional body_html field to DraftRecord"
git push
```

---

## Task 4: HTML signature sanitizer module

**Files:**
- Create: `src/mailassist/sanitize.py`
- Create: `tests/test_sanitize.py`

- [ ] **Step 4.1: Write the failing tests**

Create `tests/test_sanitize.py`:

```python
from mailassist.sanitize import sanitize_signature_html, signature_html_to_plain


def test_sanitize_keeps_allowlisted_tags() -> None:
    html = "<b>Best,</b><br><i>Ethan</i>"
    assert sanitize_signature_html(html) == "<b>Best,</b><br><i>Ethan</i>"


def test_sanitize_strips_disallowed_tags() -> None:
    html = "<b>Best</b><script>alert(1)</script><img src=x>"
    assert sanitize_signature_html(html) == "<b>Best</b>"


def test_sanitize_strips_event_handlers_and_inline_styles() -> None:
    html = '<b style="color:red" onclick="hack()">Best</b>'
    assert sanitize_signature_html(html) == "<b>Best</b>"


def test_sanitize_keeps_http_anchor_with_only_href() -> None:
    html = '<a href="https://example.com" onclick="hack()" class="x">Site</a>'
    assert sanitize_signature_html(html) == '<a href="https://example.com">Site</a>'


def test_sanitize_drops_anchor_tag_for_unsafe_scheme_keeps_text() -> None:
    html = '<a href="javascript:alert(1)">Click</a>'
    assert sanitize_signature_html(html) == "Click"


def test_sanitize_keeps_mailto_anchor() -> None:
    html = '<a href="mailto:me@example.com">Email</a>'
    assert sanitize_signature_html(html) == '<a href="mailto:me@example.com">Email</a>'


def test_sanitize_returns_empty_for_empty_input() -> None:
    assert sanitize_signature_html("") == ""
    assert sanitize_signature_html("   ") == ""


def test_signature_html_to_plain_strips_tags_and_decodes_entities() -> None:
    html = "<b>Best,</b><br>Ethan&nbsp;Cohen"
    assert signature_html_to_plain(html) == "Best,\nEthan Cohen"


def test_signature_html_to_plain_collapses_paragraphs() -> None:
    html = "<p>Best,</p><p>Ethan</p>"
    assert signature_html_to_plain(html) == "Best,\nEthan"
```

- [ ] **Step 4.2: Run tests to verify they fail**

Run: `./.venv/bin/pytest tests/test_sanitize.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'mailassist.sanitize'`.

- [ ] **Step 4.3: Implement the sanitizer**

Create `src/mailassist/sanitize.py`:

```python
from __future__ import annotations

import html
import re

ALLOWED_TAGS = ("b", "strong", "i", "em", "br", "a")
SAFE_HREF_PREFIXES = ("http://", "https://", "mailto:")


def sanitize_signature_html(input_html: str) -> str:
    """Return a small allowlisted subset of HTML safe for an email signature.

    Allowed tags: b, strong, i, em, br, a (with only an http/https/mailto href).
    Everything else is stripped; unsafe anchors keep their inner text.
    """
    text = (input_html or "").strip()
    if not text:
        return ""

    def replace_tag(match: re.Match[str]) -> str:
        raw = match.group(0)
        is_close = bool(match.group(1))
        name = match.group(2).lower()
        attrs = match.group(3) or ""

        if name not in ALLOWED_TAGS:
            return ""

        if name == "br":
            return "<br>"

        if name == "a":
            if is_close:
                return "</a>"
            href_match = re.search(r'href\s*=\s*"([^"]*)"|href\s*=\s*\'([^\']*)\'', attrs, flags=re.IGNORECASE)
            if not href_match:
                return ""
            href = (href_match.group(1) or href_match.group(2) or "").strip()
            if not href.lower().startswith(SAFE_HREF_PREFIXES):
                return ""
            href_escaped = html.escape(href, quote=True)
            return f'<a href="{href_escaped}">'

        return f"</{name}>" if is_close else f"<{name}>"

    cleaned = re.sub(
        r"<\s*(/?)\s*([a-zA-Z][a-zA-Z0-9]*)\b([^>]*)>",
        replace_tag,
        text,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def signature_html_to_plain(input_html: str) -> str:
    """Convert HTML signature to plain text using the same conventions as Gmail import."""
    text = (input_html or "").strip()
    if not text:
        return ""
    text = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", text)
    text = re.sub(r"(?i)</\s*(p|div|li|tr|h[1-6])\s*>", "\n", text)
    text = re.sub(r"(?i)<\s*li[^>]*>", "- ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    collapsed: list[str] = []
    for line in lines:
        if line or (collapsed and collapsed[-1]):
            collapsed.append(line)
    return "\n".join(collapsed).strip()
```

- [ ] **Step 4.4: Run tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_sanitize.py -v`

Expected: all 9 tests PASS.

- [ ] **Step 4.5: Commit**

```bash
git add src/mailassist/sanitize.py tests/test_sanitize.py
git commit -m "Add HTML signature sanitizer with tiny allowlist"
git push
```

---

## Task 5: Live filter contract module

**Files:**
- Create: `src/mailassist/live_filters.py`
- Create: `tests/test_live_filters.py`

- [ ] **Step 5.1: Write the failing tests**

Create `tests/test_live_filters.py`:

```python
from datetime import datetime, timezone

from mailassist.config import load_settings
from mailassist.live_filters import (
    TIME_WINDOW_SECONDS,
    WatcherFilter,
    thread_passes_filter,
)
from mailassist.models import EmailMessage, EmailThread


def _thread(*, sent_at: str, unread: bool = True) -> EmailThread:
    return EmailThread(
        thread_id="t1",
        subject="Hello",
        participants=["sender@example.com"],
        messages=[
            EmailMessage(
                message_id="m1",
                sender="sender@example.com",
                to=["me@example.com"],
                sent_at=sent_at,
                text="hi",
            )
        ],
        unread=unread,
    )


NOW = datetime(2026, 4, 27, 12, 0, 0, tzinfo=timezone.utc)


def test_filter_off_passes_everything() -> None:
    filter = WatcherFilter(unread_only=False, max_age_seconds=None)
    passes, reason = thread_passes_filter(_thread(sent_at="2020-01-01T00:00:00Z", unread=False), filter, NOW)
    assert passes is True
    assert reason is None


def test_unread_only_blocks_read_thread() -> None:
    filter = WatcherFilter(unread_only=True, max_age_seconds=None)
    passes, reason = thread_passes_filter(_thread(sent_at="2026-04-27T11:59:00Z", unread=False), filter, NOW)
    assert passes is False
    assert reason == "unread"


def test_unread_only_passes_unread_thread() -> None:
    filter = WatcherFilter(unread_only=True, max_age_seconds=None)
    passes, reason = thread_passes_filter(_thread(sent_at="2026-04-27T11:59:00Z", unread=True), filter, NOW)
    assert passes is True
    assert reason is None


def test_time_window_blocks_old_thread() -> None:
    filter = WatcherFilter(unread_only=False, max_age_seconds=TIME_WINDOW_SECONDS["24h"])
    passes, reason = thread_passes_filter(_thread(sent_at="2026-04-26T11:00:00Z"), filter, NOW)
    assert passes is False
    assert reason == "time_window"


def test_time_window_passes_recent_thread() -> None:
    filter = WatcherFilter(unread_only=False, max_age_seconds=TIME_WINDOW_SECONDS["24h"])
    passes, reason = thread_passes_filter(_thread(sent_at="2026-04-27T01:00:00Z"), filter, NOW)
    assert passes is True
    assert reason is None


def test_time_window_passes_thread_at_exact_boundary() -> None:
    filter = WatcherFilter(unread_only=False, max_age_seconds=TIME_WINDOW_SECONDS["24h"])
    passes, reason = thread_passes_filter(_thread(sent_at="2026-04-26T12:00:00Z"), filter, NOW)
    assert passes is True
    assert reason is None


def test_malformed_sent_at_treated_as_outside_window() -> None:
    filter = WatcherFilter(unread_only=False, max_age_seconds=TIME_WINDOW_SECONDS["24h"])
    thread = _thread(sent_at="not-a-date")
    passes, reason = thread_passes_filter(thread, filter, NOW)
    assert passes is False
    assert reason == "time_window"


def test_thread_with_no_messages_treated_as_outside_window() -> None:
    filter = WatcherFilter(unread_only=False, max_age_seconds=TIME_WINDOW_SECONDS["24h"])
    thread = EmailThread(thread_id="t1", subject="x", participants=[], messages=[], unread=True)
    passes, reason = thread_passes_filter(thread, filter, NOW)
    assert passes is False
    assert reason == "time_window"


def test_unread_check_runs_before_time_check() -> None:
    filter = WatcherFilter(unread_only=True, max_age_seconds=TIME_WINDOW_SECONDS["24h"])
    passes, reason = thread_passes_filter(
        _thread(sent_at="2020-01-01T00:00:00Z", unread=False),
        filter,
        NOW,
    )
    assert passes is False
    assert reason == "unread"


def test_from_settings_reads_env_vars(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    from mailassist.config import write_env_file
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_WATCHER_UNREAD_ONLY": "true",
            "MAILASSIST_WATCHER_TIME_WINDOW": "7d",
        },
    )
    settings = load_settings()
    filter = WatcherFilter.from_settings(settings)
    assert filter.unread_only is True
    assert filter.max_age_seconds == TIME_WINDOW_SECONDS["7d"]


def test_from_settings_unknown_window_falls_back_to_all(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    from mailassist.config import write_env_file
    write_env_file(tmp_path / ".env", {"MAILASSIST_WATCHER_TIME_WINDOW": "garbage"})
    settings = load_settings()
    filter = WatcherFilter.from_settings(settings)
    assert filter.max_age_seconds is None
```

- [ ] **Step 5.2: Run tests to verify they fail**

Run: `./.venv/bin/pytest tests/test_live_filters.py -v`

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 5.3: Implement `live_filters.py`**

Create `src/mailassist/live_filters.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from mailassist.config import Settings
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
    max_age_seconds: Optional[int]

    @classmethod
    def from_settings(cls, settings: Settings) -> "WatcherFilter":
        window = settings.watcher_time_window
        max_age = TIME_WINDOW_SECONDS.get(window, None)
        return cls(
            unread_only=bool(settings.watcher_unread_only),
            max_age_seconds=max_age,
        )


def _parse_iso(value: str) -> Optional[datetime]:
    text = (value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def thread_passes_filter(
    thread: EmailThread,
    filter: WatcherFilter,
    now: datetime,
) -> Tuple[bool, Optional[str]]:
    """Return (passes, reason_if_skipped). Pure function. Unread is checked first."""
    if filter.unread_only and not thread.unread:
        return False, "unread"

    if filter.max_age_seconds is None:
        return True, None

    if not thread.messages:
        return False, "time_window"

    sent_at = _parse_iso(thread.messages[-1].sent_at)
    if sent_at is None:
        return False, "time_window"

    cutoff = now - timedelta(seconds=filter.max_age_seconds)
    if sent_at < cutoff:
        return False, "time_window"
    return True, None
```

- [ ] **Step 5.4: Run tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_live_filters.py -v`

Expected: all 11 tests PASS.

- [ ] **Step 5.5: Commit**

```bash
git add src/mailassist/live_filters.py tests/test_live_filters.py
git commit -m "Add WatcherFilter contract for live watcher filtering"
git push
```

---

## Task 6: Attribution helpers module

**Files:**
- Create: `src/mailassist/attribution.py`
- Create: `tests/test_attribution.py`

- [ ] **Step 6.1: Write the failing tests**

Create `tests/test_attribution.py`:

```python
from mailassist.attribution import attribution_html, attribution_text


def test_attribution_text_contains_model_name() -> None:
    assert attribution_text("gemma3:12b") == "Drafted with MailAssist using Ollama (gemma3:12b)."


def test_attribution_text_with_blank_model() -> None:
    assert attribution_text("") == "Drafted with MailAssist using Ollama."


def test_attribution_html_contains_styled_paragraph_with_model() -> None:
    html_line = attribution_html("gemma3:12b")
    assert html_line.startswith("<p")
    assert "gemma3:12b" in html_line
    assert "italic" in html_line
    assert "color:#888" in html_line


def test_attribution_html_with_blank_model_omits_parentheses() -> None:
    html_line = attribution_html("")
    assert "()" not in html_line
    assert "Drafted with MailAssist" in html_line
```

- [ ] **Step 6.2: Run tests to verify they fail**

Run: `./.venv/bin/pytest tests/test_attribution.py -v`

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 6.3: Implement `attribution.py`**

Create `src/mailassist/attribution.py`:

```python
from __future__ import annotations


def attribution_text(model: str) -> str:
    name = (model or "").strip()
    if name:
        return f"Drafted with MailAssist using Ollama ({name})."
    return "Drafted with MailAssist using Ollama."


def attribution_html(model: str) -> str:
    name = (model or "").strip()
    style = "color:#888;font-style:italic;margin-top:12px"
    if name:
        return (
            f'<p style="{style}">Drafted with MailAssist using Ollama '
            f'(<code>{name}</code>).</p>'
        )
    return f'<p style="{style}">Drafted with MailAssist using Ollama.</p>'
```

- [ ] **Step 6.4: Run tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_attribution.py -v`

Expected: 4 tests PASS.

- [ ] **Step 6.5: Commit**

```bash
git add src/mailassist/attribution.py tests/test_attribution.py
git commit -m "Add attribution helpers for plain and HTML draft footers"
git push
```

---

## Task 7: Filter integration in `run_mock_watch_pass`

**Files:**
- Modify: `src/mailassist/background_bot.py`
- Modify: `tests/test_background_bot.py`

- [ ] **Step 7.1: Write the failing test**

Append to `tests/test_background_bot.py`:

```python
from mailassist.live_filters import TIME_WINDOW_SECONDS
from mailassist.models import EmailMessage, EmailThread


def test_run_mock_watch_pass_emits_filtered_out_for_old_thread(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_USER_TONE": "brief_casual",
            "MAILASSIST_USER_SIGNATURE": "Best,\\nTest",
            "MAILASSIST_WATCHER_TIME_WINDOW": "24h",
        },
    )

    old_thread = EmailThread(
        thread_id="thread-old",
        subject="Ancient",
        participants=["sender@example.com"],
        messages=[
            EmailMessage(
                message_id="m1",
                sender="sender@example.com",
                to=["me@example.com"],
                sent_at="2020-01-01T00:00:00Z",
                text="hi",
            )
        ],
        unread=True,
    )
    monkeypatch.setattr(
        "mailassist.background_bot.build_mock_threads",
        lambda: [old_thread],
    )

    settings = load_settings()
    provider = MockProvider(settings.mock_provider_drafts_dir)

    events = run_mock_watch_pass(
        settings=settings,
        provider=provider,
        base_url="http://localhost:11434",
        selected_model="mock-model",
    )

    assert any(
        event["type"] == "filtered_out"
        and event["thread_id"] == "thread-old"
        and event["reason"] == "time_window"
        for event in events
    )


def test_run_mock_watch_pass_emits_filtered_out_for_read_thread(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_USER_TONE": "brief_casual",
            "MAILASSIST_USER_SIGNATURE": "Best,\\nTest",
            "MAILASSIST_WATCHER_UNREAD_ONLY": "true",
        },
    )

    read_thread = EmailThread(
        thread_id="thread-read",
        subject="Already opened",
        participants=["sender@example.com"],
        messages=[
            EmailMessage(
                message_id="m1",
                sender="sender@example.com",
                to=["me@example.com"],
                sent_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                text="hi",
            )
        ],
        unread=False,
    )
    monkeypatch.setattr(
        "mailassist.background_bot.build_mock_threads",
        lambda: [read_thread],
    )

    settings = load_settings()
    provider = MockProvider(settings.mock_provider_drafts_dir)

    events = run_mock_watch_pass(
        settings=settings,
        provider=provider,
        base_url="http://localhost:11434",
        selected_model="mock-model",
    )

    assert any(
        event["type"] == "filtered_out"
        and event["thread_id"] == "thread-read"
        and event["reason"] == "unread"
        for event in events
    )
```

- [ ] **Step 7.2: Run tests to verify they fail**

Run: `./.venv/bin/pytest tests/test_background_bot.py::test_run_mock_watch_pass_emits_filtered_out_for_old_thread tests/test_background_bot.py::test_run_mock_watch_pass_emits_filtered_out_for_read_thread -v`

Expected: FAIL — no `filtered_out` events.

- [ ] **Step 7.3: Wire filter into `run_mock_watch_pass`**

In `src/mailassist/background_bot.py`, near the top imports add:

```python
from datetime import datetime, timezone

from mailassist.live_filters import WatcherFilter, thread_passes_filter
```

Inside `run_mock_watch_pass`, immediately after the line `pending_threads: list[tuple[EmailThread, str]] = []`, insert:

```python
    watcher_filter = WatcherFilter.from_settings(settings)
    now = datetime.now(timezone.utc)
```

Inside the `for thread in build_mock_threads():` loop, **before** the existing `latest_message_id = _latest_message_id(thread)` line, insert:

```python
        passes, skip_reason = thread_passes_filter(thread, watcher_filter, now)
        if not passes:
            events.append(
                {
                    "type": "filtered_out",
                    "thread_id": thread.thread_id,
                    "subject": thread.subject,
                    "reason": skip_reason,
                }
            )
            _append_recent_activity(
                state,
                provider_name=provider.name,
                event=events[-1],
            )
            continue
```

- [ ] **Step 7.4: Run tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_background_bot.py -v`

Expected: all PASS, including the two new ones.

- [ ] **Step 7.5: Commit**

```bash
git add src/mailassist/background_bot.py tests/test_background_bot.py
git commit -m "Apply watcher filter in run_mock_watch_pass with filtered_out events"
git push
```

---

## Task 8: Aggregate `filtered_out_count` in bot runtime

**Files:**
- Modify: `src/mailassist/bot_runtime.py`
- Modify: `tests/test_bot_runtime.py`

- [ ] **Step 8.1: Write the failing test**

Append to `tests/test_bot_runtime.py` (use the existing fixtures style):

```python
def test_watch_once_completed_event_includes_filtered_out_count(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    from mailassist.config import write_env_file

    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_USER_TONE": "brief_casual",
            "MAILASSIST_WATCHER_TIME_WINDOW": "24h",
        },
    )

    monkeypatch.setattr(
        "mailassist.bot_runtime.run_mock_watch_pass",
        lambda **_kwargs: [
            {
                "type": "filtered_out",
                "thread_id": "thread-old",
                "subject": "Ancient",
                "reason": "time_window",
            }
        ],
    )

    args = argparse.Namespace(
        action="watch-once",
        thread_id="",
        prompt="",
        base_url="http://localhost:11434",
        selected_model="mock-model",
        provider="mock",
        force=False,
        poll_seconds=0,
        max_passes=0,
        batch_size=1,
        limit=10,
    )
    rc = command_review_bot(args)

    assert rc == 0
    output_lines = capsys.readouterr().out.splitlines()
    completed = next(json.loads(line) for line in output_lines if json.loads(line).get("type") == "completed")
    assert completed["filtered_out_count"] == 1
```

(Adjust imports at the top of the test file as needed: `import argparse`, `import json`, plus `from mailassist.bot_runtime import command_review_bot`.)

- [ ] **Step 8.2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_bot_runtime.py::test_watch_once_completed_event_includes_filtered_out_count -v`

Expected: FAIL — `KeyError: 'filtered_out_count'`.

- [ ] **Step 8.3: Add aggregation in `command_review_bot`**

In `src/mailassist/bot_runtime.py`, inside the `if args.action == "watch-once":` block, after the line `user_replied_count = 0`, add:

```python
            filtered_out_count = 0
```

In the per-event loop, after the `elif event_type == "user_replied":` branch, add:

```python
                elif event_type == "filtered_out":
                    filtered_out_count += 1
```

In the `reporter.emit("completed", ...)` call inside `watch-once`, add the kwarg:

```python
                filtered_out_count=filtered_out_count,
```

Repeat the same three changes inside the `watch-loop` block (declare `total_filtered_out_count = 0`; increment on `event_type == "filtered_out"`; add kwarg to the final `completed` event).

- [ ] **Step 8.4: Run tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_bot_runtime.py -v`

Expected: all PASS.

- [ ] **Step 8.5: Commit**

```bash
git add src/mailassist/bot_runtime.py tests/test_bot_runtime.py
git commit -m "Aggregate filtered_out_count in watch-once and watch-loop completion events"
git push
```

---

## Task 9: HTML body assembly in `run_mock_watch_pass`

**Files:**
- Modify: `src/mailassist/background_bot.py`
- Modify: `tests/test_background_bot.py`

- [ ] **Step 9.1: Write the failing test**

Append to `tests/test_background_bot.py`:

```python
def test_run_mock_watch_pass_attaches_html_body_when_html_signature_set(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_USER_TONE": "brief_casual",
            "MAILASSIST_USER_SIGNATURE": "Best,\\nTest",
            "MAILASSIST_USER_SIGNATURE_HTML": "<b>Best,</b><br>Test",
        },
    )

    monkeypatch.setattr(
        "mailassist.background_bot.build_mock_threads",
        lambda: [item for item in build_mock_threads() if item.thread_id == "thread-008"],
    )
    monkeypatch.setattr(
        "mailassist.background_bot.generate_candidate_for_tone",
        lambda *args, **kwargs: (
            {"candidate_id": "option-a", "body": "Approved.\n\nBest,\nTest", "generated_by": "mock"},
            "mock",
            None,
            "urgent",
        ),
    )

    settings = load_settings()
    captured: list = []

    class CapturingProvider(MockProvider):
        def create_draft(self, draft):
            captured.append(draft)
            return super().create_draft(draft)

    provider = CapturingProvider(settings.mock_provider_drafts_dir)

    run_mock_watch_pass(
        settings=settings,
        provider=provider,
        base_url="http://localhost:11434",
        selected_model="mock-model",
    )

    assert len(captured) == 1
    draft = captured[0]
    assert draft.body_html is not None
    assert "<b>Best,</b>" in draft.body_html
    assert "Approved." in draft.body_html
```

- [ ] **Step 9.2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_background_bot.py::test_run_mock_watch_pass_attaches_html_body_when_html_signature_set -v`

Expected: FAIL — `draft.body_html is None`.

- [ ] **Step 9.3: Build HTML body in the draft assembly path**

In `src/mailassist/background_bot.py`, at module top add:

```python
import html as html_module
```

Add a new helper near `append_signature`:

```python
def build_html_body(plain_body: str, *, signature_html: str) -> str:
    escaped = html_module.escape(plain_body or "", quote=False).replace("\n", "<br>")
    sig = (signature_html or "").strip()
    if not sig:
        return escaped
    return f"{escaped}<br><br>{sig}"
```

Inside `run_mock_watch_pass`, where `DraftRecord(...)` is constructed (the block that already builds the plain `body_with_review_context`), set `body_html` when the signature_html is configured:

```python
            plain_body = body_with_review_context(thread, body, user_address=user_address)
            html_body: str | None = None
            if settings.user_signature_html.strip():
                html_body = build_html_body(plain_body, signature_html=settings.user_signature_html)
            draft = DraftRecord(
                draft_id=str(uuid4()),
                thread_id=thread.thread_id,
                provider=provider.name,
                subject=f"Re: {thread.subject}",
                body=plain_body,
                body_html=html_body,
                model=str(generation_model or "fallback"),
                to=reply_recipients_for_thread(thread, user_address=user_address),
            )
```

(Replace the existing `body=body_with_review_context(...)` argument with the prepared `plain_body` variable used above.)

- [ ] **Step 9.4: Run tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_background_bot.py -v`

Expected: all PASS.

- [ ] **Step 9.5: Commit**

```bash
git add src/mailassist/background_bot.py tests/test_background_bot.py
git commit -m "Attach HTML body to drafts when user has an HTML signature"
git push
```

---

## Task 10: Attribution insertion in `run_mock_watch_pass`

**Files:**
- Modify: `src/mailassist/background_bot.py`
- Modify: `tests/test_background_bot.py`

- [ ] **Step 10.1: Write the failing test**

Append to `tests/test_background_bot.py`:

```python
def test_run_mock_watch_pass_appends_plain_attribution_when_enabled(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_USER_TONE": "brief_casual",
            "MAILASSIST_USER_SIGNATURE": "Best,\\nTest",
            "MAILASSIST_OLLAMA_MODEL": "gemma3:12b",
            "MAILASSIST_DRAFT_ATTRIBUTION": "true",
        },
    )

    monkeypatch.setattr(
        "mailassist.background_bot.build_mock_threads",
        lambda: [item for item in build_mock_threads() if item.thread_id == "thread-008"],
    )
    monkeypatch.setattr(
        "mailassist.background_bot.generate_candidate_for_tone",
        lambda *args, **kwargs: (
            {"candidate_id": "option-a", "body": "Approved.\n\nBest,\nTest", "generated_by": "mock"},
            "mock",
            None,
            "urgent",
        ),
    )

    settings = load_settings()
    captured: list = []

    class CapturingProvider(MockProvider):
        def create_draft(self, draft):
            captured.append(draft)
            return super().create_draft(draft)

    provider = CapturingProvider(settings.mock_provider_drafts_dir)

    run_mock_watch_pass(
        settings=settings,
        provider=provider,
        base_url="http://localhost:11434",
        selected_model="mock-model",
    )

    assert "Drafted with MailAssist using Ollama (gemma3:12b)." in captured[0].body


def test_run_mock_watch_pass_appends_html_attribution_when_enabled_and_html_set(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_USER_TONE": "brief_casual",
            "MAILASSIST_USER_SIGNATURE": "Best,\\nTest",
            "MAILASSIST_USER_SIGNATURE_HTML": "<b>Best,</b><br>Test",
            "MAILASSIST_OLLAMA_MODEL": "gemma3:12b",
            "MAILASSIST_DRAFT_ATTRIBUTION": "true",
        },
    )

    monkeypatch.setattr(
        "mailassist.background_bot.build_mock_threads",
        lambda: [item for item in build_mock_threads() if item.thread_id == "thread-008"],
    )
    monkeypatch.setattr(
        "mailassist.background_bot.generate_candidate_for_tone",
        lambda *args, **kwargs: (
            {"candidate_id": "option-a", "body": "Approved.\n\nBest,\nTest", "generated_by": "mock"},
            "mock",
            None,
            "urgent",
        ),
    )

    settings = load_settings()
    captured: list = []

    class CapturingProvider(MockProvider):
        def create_draft(self, draft):
            captured.append(draft)
            return super().create_draft(draft)

    provider = CapturingProvider(settings.mock_provider_drafts_dir)

    run_mock_watch_pass(
        settings=settings,
        provider=provider,
        base_url="http://localhost:11434",
        selected_model="mock-model",
    )

    assert "italic" in captured[0].body_html
    assert "gemma3:12b" in captured[0].body_html
```

- [ ] **Step 10.2: Run tests to verify they fail**

Run: `./.venv/bin/pytest tests/test_background_bot.py -v -k attribution`

Expected: FAIL — attribution sentence not present.

- [ ] **Step 10.3: Append attribution in the assembly path**

In `src/mailassist/background_bot.py`, add the import at top:

```python
from mailassist.attribution import attribution_html, attribution_text
```

In `run_mock_watch_pass`, after the `plain_body = body_with_review_context(...)` line and the optional `html_body` build, before constructing `DraftRecord`, append attribution:

```python
            if settings.draft_attribution:
                model_label = str(generation_model or selected_model or "")
                plain_body = f"{plain_body}\n\n{attribution_text(model_label)}"
                if html_body is not None:
                    html_body = f"{html_body}{attribution_html(model_label)}"
```

- [ ] **Step 10.4: Run tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_background_bot.py -v`

Expected: all PASS.

- [ ] **Step 10.5: Commit**

```bash
git add src/mailassist/background_bot.py tests/test_background_bot.py
git commit -m "Append optional MailAssist+Ollama attribution to drafts"
git push
```

---

## Task 11: Mock provider implements `list_actionable_threads`

**Files:**
- Modify: `src/mailassist/providers/base.py`
- Modify: `src/mailassist/providers/mock.py`
- Create: `tests/test_mock_provider.py`

- [ ] **Step 11.1: Write the failing test**

Create `tests/test_mock_provider.py`:

```python
from datetime import datetime, timezone
from pathlib import Path

from mailassist.fixtures.mock_threads import build_mock_threads
from mailassist.live_filters import WatcherFilter, TIME_WINDOW_SECONDS
from mailassist.providers.mock import MockProvider


def test_mock_provider_list_actionable_threads_with_no_filter_returns_all(tmp_path: Path) -> None:
    provider = MockProvider(tmp_path / "drafts")
    filter = WatcherFilter(unread_only=False, max_age_seconds=None)
    threads = provider.list_actionable_threads(filter)
    assert len(threads) == len(build_mock_threads())


def test_mock_provider_list_actionable_threads_filters_old_threads(tmp_path: Path) -> None:
    provider = MockProvider(tmp_path / "drafts")
    filter = WatcherFilter(unread_only=False, max_age_seconds=TIME_WINDOW_SECONDS["24h"])
    threads = provider.list_actionable_threads(filter, now=datetime(2050, 1, 1, tzinfo=timezone.utc))
    assert threads == []
```

- [ ] **Step 11.2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_mock_provider.py -v`

Expected: FAIL — method missing.

- [ ] **Step 11.3: Add base declaration**

In `src/mailassist/providers/base.py`:

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional

from mailassist.live_filters import WatcherFilter
from mailassist.models import DraftRecord, EmailThread, ProviderDraftReference


class DraftProvider(ABC):
    name: str

    def get_account_email(self) -> Optional[str]:
        return None

    @abstractmethod
    def create_draft(self, draft: DraftRecord) -> ProviderDraftReference:
        raise NotImplementedError

    def list_actionable_threads(
        self,
        filter: WatcherFilter,
        *,
        now: Optional[datetime] = None,
    ) -> List[EmailThread]:
        raise NotImplementedError(
            f"Provider {self.name!r} does not implement list_actionable_threads yet."
        )
```

- [ ] **Step 11.4: Implement on `MockProvider`**

In `src/mailassist/providers/mock.py`:

```python
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from mailassist.fixtures.mock_threads import build_mock_threads
from mailassist.live_filters import WatcherFilter, thread_passes_filter
from mailassist.models import DraftRecord, EmailThread, ProviderDraftReference
from mailassist.providers.base import DraftProvider


class MockProvider(DraftProvider):
    name = "mock"

    def __init__(self, drafts_dir: Path, account_email: Optional[str] = None) -> None:
        self.drafts_dir = drafts_dir
        self.account_email = (account_email or "").strip() or None

    def get_account_email(self) -> Optional[str]:
        return self.account_email

    def create_draft(self, draft: DraftRecord) -> ProviderDraftReference:
        self.drafts_dir.mkdir(parents=True, exist_ok=True)
        path = self.drafts_dir / f"{draft.thread_id}.json"
        path.write_text(json.dumps(draft.to_dict(), indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        return ProviderDraftReference(
            draft_id=f"mock-draft-{draft.thread_id}",
            thread_id=draft.thread_id,
            message_id=None,
        )

    def list_actionable_threads(
        self,
        filter: WatcherFilter,
        *,
        now: Optional[datetime] = None,
    ) -> List[EmailThread]:
        instant = now or datetime.now(timezone.utc)
        return [
            thread
            for thread in build_mock_threads()
            if thread_passes_filter(thread, filter, instant)[0]
        ]
```

- [ ] **Step 11.5: Run tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_mock_provider.py tests/test_background_bot.py -v`

Expected: all PASS.

- [ ] **Step 11.6: Commit**

```bash
git add src/mailassist/providers/base.py src/mailassist/providers/mock.py tests/test_mock_provider.py
git commit -m "Add list_actionable_threads contract; implement on MockProvider"
git push
```

---

## Task 12: Gmail provider creates multipart draft when `body_html` set

**Files:**
- Modify: `src/mailassist/providers/gmail.py`
- Modify: `tests/test_gmail_provider.py`

- [ ] **Step 12.1: Write the failing test**

Append to `tests/test_gmail_provider.py` (review existing patterns there for stub Gmail service shape):

```python
def test_gmail_create_draft_uses_multipart_when_body_html_present(monkeypatch, tmp_path: Path) -> None:
    from mailassist.providers.gmail import GmailProvider

    captured = {}

    class FakeDrafts:
        def create(self, *, userId, body):
            captured["raw"] = body["message"]["raw"]
            class _Exec:
                def execute(self_inner):
                    return {"id": "draft-123", "message": {"id": "msg-1", "threadId": "thr-1"}}
            return _Exec()

    class FakeUsers:
        def drafts(self):
            return FakeDrafts()

    class FakeService:
        def users(self):
            return FakeUsers()

    def fake_load_modules(self):
        return None, None, None, lambda *args, **kwargs: FakeService()

    def fake_credentials(self, allow_interactive_auth=True):
        return None

    monkeypatch.setattr(GmailProvider, "_load_google_modules", fake_load_modules)
    monkeypatch.setattr(GmailProvider, "_credentials", fake_credentials)

    provider = GmailProvider(tmp_path / "creds.json", tmp_path / "token.json")
    record = DraftRecord(
        draft_id="d1",
        thread_id="t1",
        provider="gmail",
        subject="Hello",
        body="Plain body",
        body_html="<p>Plain body</p>",
        model="mock",
        to=["alice@example.com"],
    )
    provider.create_draft(record)

    import base64
    raw = base64.urlsafe_b64decode(captured["raw"]).decode("utf-8", errors="replace")
    assert "multipart/alternative" in raw.lower()
    assert "Plain body" in raw
    assert "<p>Plain body</p>" in raw
```

(Add `from mailassist.models import DraftRecord` at the top of the test file if missing.)

- [ ] **Step 12.2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_gmail_provider.py::test_gmail_create_draft_uses_multipart_when_body_html_present -v`

Expected: FAIL — body lacks `multipart/alternative`.

- [ ] **Step 12.3: Update `GmailProvider.create_draft`**

In `src/mailassist/providers/gmail.py`, replace `create_draft`:

```python
    def create_draft(self, draft: DraftRecord) -> ProviderDraftReference:
        from email.mime.multipart import MIMEMultipart
        _, _, _, build = self._load_google_modules()
        creds = self._credentials()

        if draft.body_html:
            message = MIMEMultipart("alternative")
            message.attach(MIMEText(draft.body, "plain"))
            message.attach(MIMEText(draft.body_html, "html"))
        else:
            message = MIMEText(draft.body)

        message["subject"] = draft.subject
        if draft.to:
            message["to"] = ", ".join(draft.to)
        if draft.cc:
            message["cc"] = ", ".join(draft.cc)
        if draft.bcc:
            message["bcc"] = ", ".join(draft.bcc)
        encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

        service = build("gmail", "v1", credentials=creds)
        created = (
            service.users()
            .drafts()
            .create(userId="me", body={"message": {"raw": encoded}})
            .execute()
        )
        message_payload = created.get("message", {})
        return ProviderDraftReference(
            draft_id=created["id"],
            thread_id=message_payload.get("threadId"),
            message_id=message_payload.get("id"),
        )
```

- [ ] **Step 12.4: Run tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_gmail_provider.py -v`

Expected: all PASS.

- [ ] **Step 12.5: Commit**

```bash
git add src/mailassist/providers/gmail.py tests/test_gmail_provider.py
git commit -m "Build multipart/alternative Gmail drafts when HTML body is set"
git push
```

---

## Task 13: Gmail signature import sanitizes via shared sanitizer

**Files:**
- Modify: `src/mailassist/providers/gmail.py`
- Modify: `tests/test_gmail_provider.py`

- [ ] **Step 13.1: Write the failing test**

Append to `tests/test_gmail_provider.py`:

```python
def test_gmail_get_default_signature_returns_sanitized_html_and_plain(monkeypatch, tmp_path: Path) -> None:
    from mailassist.providers.gmail import GmailProvider, GmailSignature

    class FakeSendAs:
        def list(self, userId):
            class _Exec:
                def execute(self_inner):
                    return {
                        "sendAs": [
                            {
                                "isDefault": True,
                                "sendAsEmail": "me@example.com",
                                "signature": '<b>Best,</b><br>Ethan<script>alert(1)</script>',
                            }
                        ]
                    }
            return _Exec()

    class FakeSettings:
        def sendAs(self):
            return FakeSendAs()

    class FakeUsers:
        def settings(self):
            return FakeSettings()

    class FakeService:
        def users(self):
            return FakeUsers()

    monkeypatch.setattr(
        GmailProvider,
        "_load_google_modules",
        lambda self: (None, None, None, lambda *a, **k: FakeService()),
    )
    monkeypatch.setattr(GmailProvider, "_credentials", lambda self, allow_interactive_auth=False: None)

    provider = GmailProvider(tmp_path / "creds.json", tmp_path / "token.json")
    sig = provider.get_default_signature(allow_interactive_auth=False)

    assert sig is not None
    assert sig.signature == "Best,\nEthan"
    assert sig.signature_html == "<b>Best,</b><br>Ethan"
```

- [ ] **Step 13.2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_gmail_provider.py::test_gmail_get_default_signature_returns_sanitized_html_and_plain -v`

Expected: FAIL — `GmailSignature` has no `signature_html` field.

- [ ] **Step 13.3: Extend `GmailSignature` and use shared sanitizer**

In `src/mailassist/providers/gmail.py`:

```python
from mailassist.sanitize import sanitize_signature_html, signature_html_to_plain
```

Replace `_gmail_signature_to_text` usage and the `GmailSignature` dataclass:

```python
@dataclass(frozen=True)
class GmailSignature:
    signature: str
    signature_html: str
    send_as_email: str
```

Inside `get_default_signature`, replace the existing block that calls `_gmail_signature_to_text`:

```python
        raw_html = str(selected.get("signature", ""))
        sanitized_html = sanitize_signature_html(raw_html)
        plain = signature_html_to_plain(sanitized_html)
        if not plain and not sanitized_html:
            return None
        return GmailSignature(
            signature=plain,
            signature_html=sanitized_html,
            send_as_email=str(selected.get("sendAsEmail", "")).strip(),
        )
```

Remove the now-unused local `_gmail_signature_to_text` function (deduplicated into `sanitize.py`).

- [ ] **Step 13.4: Run tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_gmail_provider.py tests/test_sanitize.py -v`

Expected: all PASS.

- [ ] **Step 13.5: Commit**

```bash
git add src/mailassist/providers/gmail.py tests/test_gmail_provider.py
git commit -m "Sanitize Gmail signature HTML and expose both rich and plain forms"
git push
```

---

## Task 14: Replace signature editor with `QTextEdit` and tiny RTF toolbar

**Files:**
- Modify: `src/mailassist/gui/desktop.py`

- [ ] **Step 14.1: Update imports**

In `src/mailassist/gui/desktop.py`, add to the `from PySide6.QtWidgets import (...)` block:

```python
    QTextEdit,
    QToolButton,
    QInputDialog,
```

And add at the top imports:

```python
from mailassist.sanitize import sanitize_signature_html, signature_html_to_plain
```

- [ ] **Step 14.2: Replace the signature input widget**

Find `_build_wizard_signature_page` and modify the section that creates `self.signature_input`:

```python
        self.signature_input = QTextEdit()
        self.signature_input.setAcceptRichText(True)
        if self.settings.user_signature_html.strip():
            self.signature_input.setHtml(self.settings.user_signature_html)
        else:
            self.signature_input.setPlainText(self.settings.user_signature)
        self.signature_input.setPlaceholderText("Best regards,\nYour Name")
        self.signature_input.setMinimumHeight(140)
        self.signature_input.setMaximumHeight(200)
        self.signature_input.textChanged.connect(self._refresh_prompt_preview)

        toolbar = QHBoxLayout()
        bold_button = QToolButton()
        bold_button.setText("B")
        bold_button.setToolTip("Bold (Ctrl+B)")
        bold_button.setShortcut("Ctrl+B")
        bold_button.clicked.connect(self._toggle_signature_bold)

        italic_button = QToolButton()
        italic_button.setText("I")
        italic_button.setToolTip("Italic (Ctrl+I)")
        italic_button.setShortcut("Ctrl+I")
        italic_button.clicked.connect(self._toggle_signature_italic)

        link_button = QToolButton()
        link_button.setText("Link")
        link_button.setToolTip("Insert link (Ctrl+K)")
        link_button.setShortcut("Ctrl+K")
        link_button.clicked.connect(self._insert_signature_link)

        toolbar.addWidget(bold_button)
        toolbar.addWidget(italic_button)
        toolbar.addWidget(link_button)
        toolbar.addStretch(1)
        signature_layout.addLayout(toolbar)
        signature_layout.addWidget(self.signature_input)
```

- [ ] **Step 14.3: Add the RTF helper methods**

Append inside the `MailAssistDesktopWindow` class (next to the existing settings helpers):

```python
    def _toggle_signature_bold(self) -> None:
        cursor = self.signature_input.textCursor()
        char_format = cursor.charFormat()
        new_weight = QFont.Weight.Normal if char_format.fontWeight() > QFont.Weight.Normal else QFont.Weight.Bold
        char_format.setFontWeight(new_weight)
        cursor.mergeCharFormat(char_format)
        self.signature_input.mergeCurrentCharFormat(char_format)

    def _toggle_signature_italic(self) -> None:
        cursor = self.signature_input.textCursor()
        char_format = cursor.charFormat()
        char_format.setFontItalic(not char_format.fontItalic())
        cursor.mergeCharFormat(char_format)
        self.signature_input.mergeCurrentCharFormat(char_format)

    def _insert_signature_link(self) -> None:
        cursor = self.signature_input.textCursor()
        selected = cursor.selectedText() or ""
        url, ok = QInputDialog.getText(self, "Insert link", "URL:")
        if not ok or not url.strip():
            return
        href = url.strip()
        text = selected if selected else href
        cursor.insertHtml(f'<a href="{href}">{text}</a>')
```

(Add `from PySide6.QtGui import QFont` is already present — confirm and reuse.)

- [ ] **Step 14.4: Smoke test the editor**

Run: `./.venv/bin/mailassist desktop-gui`

Verify: the Signature wizard step shows a small toolbar with Bold/Italic/Link buttons; selecting text and clicking Bold visibly bolds it.

(No automated test for Qt rendering — manual confirmation is acceptable.)

- [ ] **Step 14.5: Commit**

```bash
git add src/mailassist/gui/desktop.py
git commit -m "Switch signature editor to QTextEdit with bold/italic/link toolbar"
git push
```

---

## Task 15: Persist HTML signature on save and round-trip

**Files:**
- Modify: `src/mailassist/gui/desktop.py`

- [ ] **Step 15.1: Update `save_settings`**

In `src/mailassist/gui/desktop.py`, find `save_settings` and modify the `current.update({...})` block. Replace the existing `MAILASSIST_USER_SIGNATURE` line with:

```python
                "MAILASSIST_USER_SIGNATURE": self.signature_input.toPlainText().strip().replace("\n", "\\n"),
                "MAILASSIST_USER_SIGNATURE_HTML": sanitize_signature_html(self.signature_input.toHtml()),
```

- [ ] **Step 15.2: Update `_import_gmail_signature`**

In `_import_gmail_signature`, after the successful import block, replace `self.signature_input.setPlainText(result.signature)` with:

```python
        sanitized_html = getattr(result, "signature_html", "") or ""
        if sanitized_html:
            self.signature_input.setHtml(sanitized_html)
        else:
            self.signature_input.setPlainText(result.signature)
```

- [ ] **Step 15.3: Smoke test**

Run: `./.venv/bin/mailassist desktop-gui`

Verify:
- Type a signature with bold text in the Signature step.
- Click Finish.
- Open `~/Library/Application Support/MailAssist/.env` (or `./.env` when running from source).
- Confirm `MAILASSIST_USER_SIGNATURE_HTML=<b>...` is present and `MAILASSIST_USER_SIGNATURE=...` holds the plain form.

- [ ] **Step 15.4: Commit**

```bash
git add src/mailassist/gui/desktop.py
git commit -m "Persist sanitized HTML signature alongside plain signature"
git push
```

---

## Task 16: Filter widgets on the Choose Email Provider wizard page

**Files:**
- Modify: `src/mailassist/gui/desktop.py`

- [ ] **Step 16.1: Add imports**

In `src/mailassist/gui/desktop.py`, extend the PySide6.QtWidgets import:

```python
    QButtonGroup,
    QRadioButton,
```

Add at the top imports:

```python
from mailassist.live_filters import TIME_WINDOW_SECONDS
```

- [ ] **Step 16.2: Add filter group to `_build_wizard_provider_page`**

Append below the existing `provider_group` widget (still inside `_build_wizard_provider_page`):

```python
        watch_group = QGroupBox("Watch only")
        watch_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        watch_layout = QVBoxLayout(watch_group)
        watch_layout.setSpacing(8)
        watch_layout.setContentsMargins(18, 16, 18, 16)

        self.watcher_unread_only = QCheckBox("Unread emails only")
        self.watcher_unread_only.setChecked(self.settings.watcher_unread_only)
        watch_layout.addWidget(self.watcher_unread_only)

        time_window_label = QLabel("Time window:")
        time_window_label.setStyleSheet("color: #5e6978; font-size: 13px;")
        watch_layout.addWidget(time_window_label)

        self.watcher_time_window_group = QButtonGroup(watch_group)
        self.watcher_time_window_buttons: dict[str, QRadioButton] = {}
        windows_row = QHBoxLayout()
        for value, label in (("all", "All"), ("24h", "24h"), ("7d", "7d"), ("30d", "30d")):
            button = QRadioButton(label)
            button.setProperty("window_value", value)
            self.watcher_time_window_group.addButton(button)
            self.watcher_time_window_buttons[value] = button
            windows_row.addWidget(button)
        windows_row.addStretch(1)
        watch_layout.addLayout(windows_row)
        current_window = self.settings.watcher_time_window if self.settings.watcher_time_window in TIME_WINDOW_SECONDS else "all"
        self.watcher_time_window_buttons[current_window].setChecked(True)

        layout.addWidget(watch_group, 0, Qt.AlignmentFlag.AlignTop)
```

- [ ] **Step 16.3: Smoke test**

Run: `./.venv/bin/mailassist desktop-gui`

Verify the "Watch only" group appears below the provider checkboxes with a checkbox and four radio buttons.

- [ ] **Step 16.4: Commit**

```bash
git add src/mailassist/gui/desktop.py
git commit -m "Add unread-only and time-window filter controls to provider wizard step"
git push
```

---

## Task 17: Persist filter values on save

**Files:**
- Modify: `src/mailassist/gui/desktop.py`

- [ ] **Step 17.1: Add a small helper**

Append in `MailAssistDesktopWindow`:

```python
    def _selected_time_window_value(self) -> str:
        for value, button in getattr(self, "watcher_time_window_buttons", {}).items():
            if button.isChecked():
                return value
        return "all"
```

- [ ] **Step 17.2: Wire into `save_settings`**

In `save_settings`'s `current.update({...})` block, add:

```python
                "MAILASSIST_WATCHER_UNREAD_ONLY": "true" if self.watcher_unread_only.isChecked() else "false",
                "MAILASSIST_WATCHER_TIME_WINDOW": self._selected_time_window_value(),
```

- [ ] **Step 17.3: Smoke test**

Run: `./.venv/bin/mailassist desktop-gui`

Verify after Finish that `.env` shows the two new vars matching the wizard selections.

- [ ] **Step 17.4: Commit**

```bash
git add src/mailassist/gui/desktop.py
git commit -m "Persist watcher unread-only and time-window selections"
git push
```

---

## Task 18: Attribution checkbox on the Signature wizard page

**Files:**
- Modify: `src/mailassist/gui/desktop.py`

- [ ] **Step 18.1: Add the checkbox**

In `_build_wizard_signature_page`, after the `signature_layout.addWidget(self.gmail_signature_status)` line:

```python
        self.attribution_checkbox = QCheckBox(
            'Add a small "Drafted with MailAssist" line at the bottom of each draft.'
        )
        self.attribution_checkbox.setToolTip(
            "Includes the local model name. Off by default."
        )
        self.attribution_checkbox.setChecked(self.settings.draft_attribution)
        signature_layout.addWidget(self.attribution_checkbox)
```

- [ ] **Step 18.2: Wire into `save_settings`**

Add to the `current.update({...})` block in `save_settings`:

```python
                "MAILASSIST_DRAFT_ATTRIBUTION": "true" if self.attribution_checkbox.isChecked() else "false",
```

- [ ] **Step 18.3: Smoke test**

Run: `./.venv/bin/mailassist desktop-gui`. Verify the checkbox appears under the signature editor and that toggling + Finish persists `MAILASSIST_DRAFT_ATTRIBUTION` in `.env`.

- [ ] **Step 18.4: Commit**

```bash
git add src/mailassist/gui/desktop.py
git commit -m "Add draft attribution checkbox to signature wizard step"
git push
```

---

## Task 19: Dashboard "Filter:" row

**Files:**
- Modify: `src/mailassist/gui/desktop.py`

- [ ] **Step 19.1: Add a description helper**

Append in `MailAssistDesktopWindow`:

```python
    def _describe_filter(self) -> str:
        unread = self.settings.watcher_unread_only
        window = self.settings.watcher_time_window
        window_label = {
            "all": "all time",
            "24h": "last 24 hours",
            "7d": "last 7 days",
            "30d": "last 30 days",
        }.get(window, "all time")
        if unread and window == "all":
            return "Unread only"
        if unread:
            return f"Unread, {window_label}"
        if window == "all":
            return "All emails"
        return f"All, {window_label}"
```

- [ ] **Step 19.2: Add the row to the status grid**

In `_build_ui`, find the `for label_text, widget, style in (...)` loop that builds the status grid, and add a new tuple before the trailing `):`:

```python
            ("Filter", self.filter_status_label, plain_style),
```

Just above that loop, add:

```python
        self.filter_status_label = QLabel(self._describe_filter())
```

- [ ] **Step 19.3: Refresh the row when settings change**

In `refresh_dashboard` (find the existing method), add:

```python
        if hasattr(self, "filter_status_label"):
            self.filter_status_label.setText(self._describe_filter())
```

- [ ] **Step 19.4: Smoke test**

Run: `./.venv/bin/mailassist desktop-gui`. Verify the dashboard shows a `Filter:` row that reflects the current selection, and updates after saving wizard changes.

- [ ] **Step 19.5: Commit**

```bash
git add src/mailassist/gui/desktop.py
git commit -m "Show active live-watcher filter on the dashboard"
git push
```

---

## Task 20: Surface `filtered_out` events in Recent Activity

**Files:**
- Modify: `src/mailassist/gui/desktop.py`

- [ ] **Step 20.1: Extend `_handle_bot_event`**

In `_handle_bot_event`, find the existing event-type branches and add a new `elif`:

```python
        elif event_type == "filtered_out":
            self._append_recent_activity(
                f"Filtered out: {event.get('subject', 'Unknown subject')} "
                f"({event.get('reason', 'unknown')})"
            )
```

- [ ] **Step 20.2: Smoke test**

Run: `./.venv/bin/mailassist desktop-gui`, set the filter to `24h`, run Mock Pass. Verify Recent Activity shows lines like `Filtered out: ... (time_window)` for old mock fixtures.

- [ ] **Step 20.3: Commit**

```bash
git add src/mailassist/gui/desktop.py
git commit -m "Surface filtered_out events in Recent Activity"
git push
```

---

## Task 21: End-to-end smoke + version bump + docs refresh

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/mailassist/review_state.py` (or whichever module exposes `load_visible_version`) — see `load_visible_version` source for the version file path.
- Modify: `README.md`
- Modify: `SUMMARY.md`

- [ ] **Step 21.1: Run the full test suite**

Run: `./.venv/bin/pytest -v`

Expected: all tests PASS (existing + new ~30 added across the plan).

- [ ] **Step 21.2: Smoke test the desktop app**

Run: `./.venv/bin/mailassist desktop-gui`

Walkthrough:
1. Wizard step "Choose Email Provider" — toggle Unread only, pick `7d`.
2. Step "Set Signature" — type a signature with bold text using Ctrl+B; tick the attribution checkbox.
3. Finish.
4. Dashboard shows `Filter: Unread, last 7 days` and `Signature: Configured`.
5. Click Run Mock Pass.
6. Recent Activity shows at least one `Filtered out: ...` line for the old mock fixtures and one `Draft created` for a recent thread.
7. Open `data/mock-provider-drafts/<thread>.json` and confirm:
   - `body` ends with `Drafted with MailAssist using Ollama (<model>).`
   - `body_html` is a non-empty string containing `<b>` and `<p style="color:#888...">`.

- [ ] **Step 21.3: Version bump**

Bump the project version per `VERSIONING_SOP.md`. In `pyproject.toml`:

```toml
version = "56.48.0"
```

Update the visible version source so `load_visible_version` returns `56.48`. (Inspect `src/mailassist/review_state.py` for the exact file/line — usually a `VERSION` constant or a small text file.)

- [ ] **Step 21.4: Update `README.md`**

Add a brief paragraph under "Run The Desktop App From Source" describing the new wizard controls (RTF signature editor, watch-only filter, attribution checkbox). Also update the "Current Verified Baseline" version line to `v56.48`.

- [ ] **Step 21.5: Update `SUMMARY.md`**

Refresh the project snapshot to mention the three new GUI features and the new env vars.

- [ ] **Step 21.6: Commit and push**

```bash
git add pyproject.toml src/mailassist/review_state.py README.md SUMMARY.md
git commit -m "Bump to v56.48 and refresh docs for GUI polish wave"
git push
```

---

## Self-Review Checklist (run before handing the plan to the executor)

- [ ] Spec coverage — every section in the spec maps to a task above. (Five env vars: Task 1. Sanitizer: Task 4. Live filter contract: Task 5. Attribution helpers: Task 6. EmailThread.unread: Task 2. DraftRecord.body_html: Task 3. Filter integration in watch pass: Task 7. filtered_out_count aggregation: Task 8. HTML body assembly: Task 9. Attribution insertion: Task 10. Mock provider list_actionable_threads: Task 11. Gmail multipart drafts: Task 12. Sanitized Gmail signature import: Task 13. RTF editor + toolbar: Task 14. HTML signature persistence: Task 15. Filter widgets on wizard: Task 16. Filter persistence: Task 17. Attribution checkbox: Task 18. Dashboard filter row: Task 19. Filtered_out in Recent Activity: Task 20. Smoke + version + docs: Task 21.)
- [ ] No placeholders — each step shows the exact code or command to run.
- [ ] Type consistency — `WatcherFilter.from_settings(settings)` (Task 5) is used the same way in Task 7. `body_html` field defined in Task 3 is read in Tasks 9, 11, 12.
- [ ] Test coverage — every behavioral change has a matching test.
