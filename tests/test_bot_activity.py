from datetime import datetime

from mailassist.gui import bot_activity


def _local_timestamp_at(hour: int, minute: int, second: int = 0) -> str:
    return (
        datetime.now()
        .astimezone()
        .replace(hour=hour, minute=minute, second=second, microsecond=0)
        .isoformat()
    )


def test_event_labels_use_12_hour_system_time(monkeypatch) -> None:
    monkeypatch.setattr(bot_activity, "_system_uses_24_hour_clock", lambda: False)
    timestamp = _local_timestamp_at(22, 42)

    assert bot_activity.event_day_time_label(timestamp).endswith("10:42 PM")
    assert bot_activity.event_time_label(timestamp) == "10:42:00 PM"


def test_event_labels_use_24_hour_system_time(monkeypatch) -> None:
    monkeypatch.setattr(bot_activity, "_system_uses_24_hour_clock", lambda: True)
    timestamp = _local_timestamp_at(22, 42)

    assert bot_activity.event_day_time_label(timestamp).endswith("22:42")
    assert bot_activity.event_time_label(timestamp) == "22:42:00"


def test_scan_lock_busy_event_has_clear_message() -> None:
    assert (
        bot_activity.event_human_message(
            {
                "type": "scan_lock_busy",
                "message": "Another MailAssist scan is already running; this pass skipped without drafting.",
            }
        )
        == "Another MailAssist scan is already running; this pass skipped without drafting."
    )


def test_scan_lock_waiting_event_has_clear_message() -> None:
    assert (
        bot_activity.event_human_message(
            {
                "type": "scan_lock_waiting",
                "message": "Another MailAssist scan is already running; waiting for it to finish.",
            }
        )
        == "Another MailAssist scan is already running; waiting for it to finish."
    )
