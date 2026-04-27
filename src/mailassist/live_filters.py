from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from mailassist.config import Settings
from mailassist.models import EmailThread

TIME_WINDOW_SECONDS = {
    "all": None,
    "24h": 24 * 60 * 60,
    "7d": 7 * 24 * 60 * 60,
    "30d": 30 * 24 * 60 * 60,
}


@dataclass(frozen=True)
class WatcherFilter:
    unread_only: bool
    max_age_seconds: int | None

    @classmethod
    def from_settings(cls, settings: Settings) -> "WatcherFilter":
        window = settings.watcher_time_window if settings.watcher_time_window in TIME_WINDOW_SECONDS else "all"
        return cls(
            unread_only=bool(settings.watcher_unread_only),
            max_age_seconds=TIME_WINDOW_SECONDS[window],
        )


def thread_passes_filter(
    thread: EmailThread,
    watcher_filter: WatcherFilter,
    *,
    now: datetime,
) -> tuple[bool, str | None]:
    if watcher_filter.unread_only and not thread.unread:
        return False, "unread"

    if watcher_filter.max_age_seconds is None:
        return True, None

    if not thread.messages:
        return False, "time_window"

    latest_sent_at = _parse_sent_at(thread.messages[-1].sent_at)
    if latest_sent_at is None:
        return False, "time_window"

    anchor = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    cutoff = anchor - timedelta(seconds=watcher_filter.max_age_seconds)
    if latest_sent_at < cutoff:
        return False, "time_window"
    return True, None


def _parse_sent_at(value: str) -> datetime | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    if cleaned.endswith("Z"):
        cleaned = f"{cleaned[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
