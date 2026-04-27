from datetime import datetime, timezone
from pathlib import Path

from mailassist.config import load_settings, write_env_file
from mailassist.live_filters import WatcherFilter, thread_passes_filter
from mailassist.models import EmailMessage, EmailThread


def _thread(*, unread: bool = True, sent_at: str = "2026-04-27T10:00:00Z") -> EmailThread:
    return EmailThread(
        thread_id="thread-1",
        subject="Subject",
        participants=["sender@example.com"],
        unread=unread,
        messages=[
            EmailMessage(
                message_id="msg-1",
                sender="sender@example.com",
                to=["you@example.com"],
                sent_at=sent_at,
                text="Hello there",
            )
        ],
    )


def test_watcher_filter_from_settings_reads_supported_window(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_WATCHER_UNREAD_ONLY": "true",
            "MAILASSIST_WATCHER_TIME_WINDOW": "7d",
        },
    )

    watcher_filter = WatcherFilter.from_settings(load_settings())

    assert watcher_filter.unread_only is True
    assert watcher_filter.max_age_seconds == 7 * 24 * 60 * 60


def test_thread_passes_filter_rejects_read_threads_when_unread_only() -> None:
    passes, reason = thread_passes_filter(
        _thread(unread=False),
        WatcherFilter(unread_only=True, max_age_seconds=None),
        now=datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc),
    )

    assert passes is False
    assert reason == "unread"


def test_thread_passes_filter_rejects_threads_outside_time_window() -> None:
    passes, reason = thread_passes_filter(
        _thread(sent_at="2026-04-20T09:00:00Z"),
        WatcherFilter(unread_only=False, max_age_seconds=24 * 60 * 60),
        now=datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc),
    )

    assert passes is False
    assert reason == "time_window"


def test_thread_passes_filter_accepts_recent_unread_threads() -> None:
    passes, reason = thread_passes_filter(
        _thread(),
        WatcherFilter(unread_only=True, max_age_seconds=7 * 24 * 60 * 60),
        now=datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc),
    )

    assert passes is True
    assert reason is None
