from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QMessageBox

from mailassist.config import load_settings
from mailassist.gui.bot_activity import (
    event_day_time_label,
    format_bot_log_for_humans,
    humanize,
    is_organizer_action,
    log_action_label,
    organizer_stop_message,
    read_bot_log_events,
    short_duration_label,
    user_facing_failure_message,
)
from mailassist.gui.bot_process import (
    BotActionRequest,
    build_bot_action_args,
    build_bot_process_environment,
)
from mailassist.gui.recent_activity import EMPTY_ACTIVITY_TEXT, RecentActivityPanel
from mailassist.live_state import load_live_state


def _classification_bucket(classification: object) -> str:
    cleaned = str(classification or "").strip().lower().replace("-", "_").replace(" ", "_")
    if cleaned in {"urgent", "reply_needed", "needs_reply"}:
        return "need_reply"
    if cleaned in {"no_response", "ignore", "skip"}:
        return "no_reply"
    if cleaned in {"automated", "auto", "auto_generated", "newsletter"}:
        return "automated"
    if cleaned == "spam":
        return "spam"
    return "unclassified"


def _empty_activity_counts() -> dict[str, int]:
    return {
        "scanned": 0,
        "need_reply": 0,
        "no_reply": 0,
        "automated": 0,
        "spam": 0,
        "unclassified": 0,
        "drafts": 0,
        "draft_previews": 0,
        "already_handled": 0,
        "filtered": 0,
        "failed": 0,
    }


def _activity_summary(counts: dict[str, int]) -> str:
    scanned = counts.get("scanned", 0)
    pieces = [
        f"{scanned} scanned",
        f"{counts.get('need_reply', 0)} need reply",
        f"{counts.get('no_reply', 0)} no reply",
        f"{counts.get('automated', 0)} automated",
    ]
    if counts.get("spam", 0):
        pieces.append(f"{counts.get('spam', 0)} spam")
    if counts.get("unclassified", 0):
        pieces.append(f"{counts.get('unclassified', 0)} unclassified")
    drafts = counts.get("drafts", 0)
    pieces.append(f"{drafts} reply drafted" if drafts == 1 else f"{drafts} replies drafted")
    if counts.get("draft_previews", 0):
        pieces.append(f"{counts.get('draft_previews', 0)} previews")
    if counts.get("already_handled", 0):
        pieces.append(f"{counts.get('already_handled', 0)} already handled")
    if counts.get("filtered", 0):
        pieces.append(f"{counts.get('filtered', 0)} filtered")
    if counts.get("failed", 0):
        pieces.append(f"{counts.get('failed', 0)} failed")
    return " / ".join(pieces)


def _event_int(event: dict[str, Any], key: str) -> int:
    try:
        return int(event.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _event_has_activity_counts(event: dict[str, Any]) -> bool:
    return any(
        key in event
        for key in (
            "scanned_count",
            "need_reply_count",
            "no_reply_count",
            "automated_count",
            "spam_count",
            "unclassified_count",
            "draft_count",
            "draft_ready_count",
            "already_handled_count",
            "user_replied_count",
            "filtered_out_count",
            "generation_failed_count",
            "failed_pass_count",
        )
    )


def _activity_counts_from_event_payload(event: dict[str, Any]) -> dict[str, int]:
    counts = _empty_activity_counts()
    counts["scanned"] = _event_int(event, "scanned_count")
    counts["need_reply"] = _event_int(event, "need_reply_count")
    counts["no_reply"] = _event_int(event, "no_reply_count") + _event_int(event, "skipped_count")
    counts["automated"] = _event_int(event, "automated_count")
    counts["spam"] = _event_int(event, "spam_count")
    counts["unclassified"] = _event_int(event, "unclassified_count")
    counts["drafts"] = _event_int(event, "draft_count")
    counts["draft_previews"] = _event_int(event, "draft_ready_count")
    counts["already_handled"] = _event_int(event, "already_handled_count") + _event_int(
        event,
        "user_replied_count",
    )
    counts["filtered"] = _event_int(event, "filtered_out_count")
    counts["failed"] = _event_int(event, "failed_pass_count") + _event_int(
        event,
        "generation_failed_count",
    )
    if not counts["scanned"]:
        counts["scanned"] = counts["drafts"] + counts["draft_previews"] + counts["no_reply"]
    return counts


def _add_classification_count(counts: dict[str, int], classification: object) -> None:
    counts["scanned"] += 1
    counts[_classification_bucket(classification)] += 1


def _add_outcome_count(
    counts: dict[str, int],
    event: dict[str, Any],
    *,
    count_scan: bool,
) -> None:
    event_type = str(event.get("type") or "")
    if count_scan and event_type in {"draft_created", "draft_ready", "skipped_email"}:
        counts["scanned"] += 1
        counts[_classification_bucket(event.get("classification"))] += 1
    elif event_type == "filtered_out":
        counts["filtered"] += 1
    elif event_type in {"already_handled", "user_replied"}:
        counts["already_handled"] += 1
    elif event_type == "generation_failed":
        counts["failed"] += 1
    if event_type == "draft_created":
        counts["drafts"] += 1
    elif event_type == "draft_ready":
        counts["draft_previews"] += 1
    elif event_type in {"error", "failed_pass"}:
        counts["failed"] += 1


def _activity_counts_from_events(
    events: list[dict[str, Any]],
    *,
    cutoff: datetime | None,
) -> dict[str, int]:
    counts = _empty_activity_counts()
    scoped_events = []
    for event in events:
        timestamp = _event_timestamp(event)
        if cutoff is not None and (timestamp is None or timestamp < cutoff):
            continue
        scoped_events.append(event)
    has_classification_events = any(
        event.get("type") == "email_classified" for event in scoped_events
    )
    has_outcome_events = any(
        event.get("type")
        in {
            "draft_created",
            "draft_ready",
            "skipped_email",
            "already_handled",
            "user_replied",
            "filtered_out",
        }
        for event in scoped_events
    )
    for event in scoped_events:
        if event.get("type") == "email_classified":
            _add_classification_count(counts, event.get("classification"))
        else:
            _add_outcome_count(
                counts,
                event,
                count_scan=not has_classification_events,
            )
    if not has_classification_events and not has_outcome_events:
        for event in scoped_events:
            if event.get("type") != "completed" or "draft_count" not in event:
                continue
            drafts = int(event.get("draft_count") or 0)
            previews = int(event.get("draft_ready_count") or 0)
            skipped = int(event.get("skipped_count") or 0)
            already = int(event.get("already_handled_count") or 0)
            filtered = int(event.get("filtered_out_count") or 0)
            failed = int(event.get("failed_pass_count") or 0)
            counts["drafts"] += drafts
            counts["draft_previews"] += previews
            counts["no_reply"] += skipped
            counts["already_handled"] += already
            counts["filtered"] += filtered
            counts["failed"] += failed
            counts["scanned"] += drafts + previews + skipped
    return counts


def _watch_pass_counts_from_events(
    events: list[dict[str, Any]],
    completed_event: dict[str, Any],
) -> dict[str, int]:
    if _event_has_activity_counts(completed_event):
        return _activity_counts_from_event_payload(completed_event)
    completed_index = None
    for index in range(len(events) - 1, -1, -1):
        if events[index] is completed_event:
            completed_index = index
            break
    if completed_index is None:
        completed_index = len(events)
    pass_number = completed_event.get("pass_number")
    start_index = 0
    for index in range(completed_index - 1, -1, -1):
        event = events[index]
        event_type = event.get("type")
        if event_type == "watch_pass_started" and (
            pass_number is None or event.get("pass_number") == pass_number
        ):
            start_index = index + 1
            break
        if event_type == "watch_pass_completed":
            start_index = index + 1
            break
    return _activity_counts_from_events(events[start_index:completed_index], cutoff=None)


def _watch_pass_summary(
    event: dict[str, Any],
    events: list[dict[str, Any]] | None = None,
) -> str:
    if events is not None:
        return _activity_summary(_watch_pass_counts_from_events(events, event))
    if _event_has_activity_counts(event):
        return _activity_summary(_activity_counts_from_event_payload(event))
    return ""


def _merge_activity_counts(target: dict[str, int], source: dict[str, int]) -> None:
    for key, value in source.items():
        target[key] = target.get(key, 0) + value


def _has_activity_counts(counts: dict[str, int]) -> bool:
    return any(int(value or 0) for value in counts.values())


def _activity_counts_from_live_state(root_dir: Path, *, cutoff: datetime | None) -> dict[str, int]:
    counts = _empty_activity_counts()
    try:
        state = load_live_state(root_dir)
    except Exception:
        return counts
    providers = state.get("providers", {})
    if not isinstance(providers, dict):
        return counts
    for provider_slot in providers.values():
        if not isinstance(provider_slot, dict):
            continue
        threads = provider_slot.get("threads", {})
        if not isinstance(threads, dict):
            continue
        for record in threads.values():
            if not isinstance(record, dict):
                continue
            updated_at = _parse_datetime_value(record.get("updated_at"))
            if cutoff is not None and (updated_at is None or updated_at < cutoff):
                continue
            action = str(record.get("action") or "").strip()
            classification = str(record.get("classification") or "unclassified")
            if action in {"draft_created", "draft_ready", "skipped"}:
                counts["scanned"] += 1
                counts[_classification_bucket(classification)] += 1
                if action == "draft_created":
                    counts["drafts"] += 1
                elif action == "draft_ready":
                    counts["draft_previews"] += 1
            elif action in {"already_handled", "user_replied"}:
                counts["already_handled"] += 1
            elif action == "filtered_out":
                counts["filtered"] += 1
    return counts


def _latest_event(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    latest_timestamp: datetime | None = None
    for event in events:
        timestamp = _event_timestamp(event)
        if timestamp is None:
            continue
        if latest_timestamp is None or timestamp >= latest_timestamp:
            latest = event
            latest_timestamp = timestamp
    return latest


def _service_recent_event_key(event: dict[str, Any]) -> str:
    return "|".join(
        str(event.get(key) or "")
        for key in (
            "timestamp",
            "type",
            "provider",
            "pass_number",
            "classification",
            "message_timestamp",
            "scan_source",
        )
    )


def _scan_source_label(event: dict[str, Any], fallback: str = "service") -> str:
    source = str(event.get("scan_source") or "").strip().lower()
    if source == "manual":
        return "manual"
    if source == "service":
        return "service"
    return fallback


def _message_outcome_label(event: dict[str, Any]) -> str:
    event_type = str(event.get("type") or "")
    classification = str(event.get("classification") or "").strip()
    classification_label = humanize(classification) if classification else ""
    if event_type == "draft_created":
        return f"{classification_label}; reply drafted" if classification_label else "reply drafted"
    if event_type == "draft_ready":
        return f"{classification_label}; reply previewed" if classification_label else "reply previewed"
    if event_type == "skipped_email":
        return classification_label or "no reply needed"
    if event_type == "already_handled":
        return "already handled"
    if event_type == "user_replied":
        return "already answered by user"
    if event_type == "filtered_out":
        reason = str(event.get("reason") or "").strip()
        return f"filtered out ({humanize(reason)})" if reason else "filtered out"
    if event_type == "generation_failed":
        return "generation failed"
    return classification_label or "checked"


def _message_outcome_message(
    event: dict[str, Any],
    *,
    source_label: str,
) -> str:
    when = event_day_time_label(event.get("timestamp"))
    raw_message_time = str(event.get("message_timestamp") or "").strip()
    if raw_message_time:
        message_time = event_day_time_label(raw_message_time)
        return (
            f"{when}: {source_label} agent scanned email dated {message_time}, "
            f"outcome: {_message_outcome_label(event)}."
        )
    return f"{when}: {source_label} agent scanned email, outcome: {_message_outcome_label(event)}."


def _caught_up_detail(event: dict[str, Any]) -> str:
    raw_caught_up = str(event.get("caught_up_message_timestamp") or "").strip()
    if not raw_caught_up:
        return ""
    caught_up = event_day_time_label(raw_caught_up)
    return f"All caught up through {caught_up}."


def _dashboard_event_message(
    event: dict[str, Any],
    *,
    pass_summary: str = "",
    source_label: str = "",
) -> str:
    event_type = str(event.get("type") or "")
    source_label = source_label or _scan_source_label(event)
    provider = str(event.get("provider") or "").strip().title() or "MailAssist"
    subject = f"{source_label}: {provider}"
    classification = str(event.get("classification") or "").strip()
    classification_detail = f" as {humanize(classification)}" if classification else ""
    when = event_day_time_label(event.get("timestamp"))
    if event_type == "watch_pass_started":
        return f"{when}: {source_label} agent started."
    if event_type == "watch_pass_completed":
        summary = pass_summary or _watch_pass_summary(event)
        caught_up = _caught_up_detail(event)
        if summary:
            suffix = f" {caught_up}" if caught_up else ""
            return f"{when}: {source_label} agent finished: {summary}.{suffix}"
        return f"{when}: {source_label} agent finished."
    if event_type == "sleeping":
        poll_seconds = event.get("poll_seconds")
        if poll_seconds:
            return f"{subject} waiting {poll_seconds} seconds after {when}."
        return f"{subject} waiting after {when}."
    if event_type == "email_work_started":
        return f"{subject} working on message dated {event_day_time_label(event.get('message_timestamp'))}."
    if event_type == "email_classified":
        return f"{subject} classified an email{classification_detail} at {when}."
    if event_type in {
        "draft_created",
        "draft_ready",
        "already_handled",
        "user_replied",
        "skipped_email",
        "filtered_out",
        "generation_failed",
    }:
        return _message_outcome_message(event, source_label=source_label)
    if event_type == "error":
        return f"{subject} needs attention at {when}."
    if event_type == "started":
        return f"{when}: {source_label} agent started."
    if event_type == "info":
        return f"{subject} reported status at {when}."
    return f"{subject} activity at {when}."


def _event_timestamp(event: dict[str, Any]) -> datetime | None:
    return _parse_datetime_value(event.get("timestamp"))


def _parse_datetime_value(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def system_boot_time_utc() -> datetime | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        uptime_ms = int(ctypes.windll.kernel32.GetTickCount64())
    except Exception:
        return None
    return datetime.now(timezone.utc) - timedelta(milliseconds=uptime_ms)


class BotControllerMixin:
    def _append_recent_activity(self, message: str) -> None:
        if not hasattr(self, "recent_activity"):
            return
        if isinstance(self.activity_group, RecentActivityPanel):
            self.activity_group.append_message(message)
        else:
            if self.recent_activity.toPlainText().strip() == EMPTY_ACTIVITY_TEXT:
                self.recent_activity.clear()
            self.recent_activity.appendPlainText(message)
        self.last_activity_summary = message
        self.refresh_dashboard()

    def clear_recent_activity(self) -> None:
        if isinstance(self.activity_group, RecentActivityPanel):
            self.activity_group.clear_messages()
        else:
            self.recent_activity.setPlainText(EMPTY_ACTIVITY_TEXT)
        self.last_activity_summary = "Idle"
        self.refresh_dashboard()
        self._set_banner("Recent Activity cleared.", level="info")

    def _announce_long_action(self, message: str) -> None:
        self._append_recent_activity(message)
        self._set_banner(message, level="info")

    def _reset_bot_progress(self) -> None:
        self.bot_progress = {
            "total": 0,
            "categorized": 0,
            "checked": 0,
            "drafts": 0,
            "draft_previews": 0,
            "skipped": 0,
            "already_handled": 0,
            "filtered": 0,
            "updated_messages": 0,
            "current_index": 0,
            "need_reply": 0,
            "no_reply": 0,
            "automated": 0,
            "spam": 0,
            "unclassified": 0,
        }
        self.bot_progress["current_detail"] = ""

    def _bot_progress_summary(self) -> str:
        total = self.bot_progress.get("total", 0)
        categorized = self.bot_progress.get("categorized", 0)
        checked = self.bot_progress.get("checked", 0)
        drafts = self.bot_progress.get("drafts", 0)
        draft_previews = self.bot_progress.get("draft_previews", 0)
        skipped = self.bot_progress.get("skipped", 0)
        already_handled = self.bot_progress.get("already_handled", 0)
        filtered = self.bot_progress.get("filtered", 0)
        if self.current_bot_action in {"gmail-populate-labels", "outlook-populate-categories"}:
            current_index = int(self.bot_progress.get("current_index") or categorized or 0)
            if total:
                return f"{current_index}/{total} scanned · {categorized} categorized"
            return f"{categorized} scanned · {categorized} categorized"
        need_reply = self.bot_progress.get("need_reply", 0)
        no_reply = self.bot_progress.get("no_reply", 0)
        automated = self.bot_progress.get("automated", 0)
        spam = self.bot_progress.get("spam", 0)
        unclassified = self.bot_progress.get("unclassified", 0)
        classified_total = need_reply + no_reply + automated + spam + unclassified
        fresh_scanned = max(
            0,
            int(checked or 0) - int(already_handled or 0) - int(filtered or 0),
        )
        fresh_scanned = max(fresh_scanned, int(classified_total or 0))
        counts = {
            "scanned": fresh_scanned,
            "need_reply": int(need_reply or 0),
            "no_reply": int(no_reply or 0),
            "automated": int(automated or 0),
            "spam": int(spam or 0),
            "unclassified": int(unclassified or 0),
            "drafts": int(drafts or 0),
            "draft_previews": int(draft_previews or 0),
            "already_handled": int(already_handled or 0),
            "filtered": int(filtered or 0),
            "failed": 0,
        }
        if not classified_total and skipped:
            counts["no_reply"] = int(skipped or 0)
        summary = _activity_summary(counts)
        current_detail = str(self.bot_progress.get("current_detail") or "").strip()
        if current_detail:
            summary = f"{summary}; working on message dated {current_detail}"
        return summary

    def _start_bot_heartbeat(self, action: str, provider: str, *, dry_run: bool = False) -> None:
        self.bot_action_started_at = time.monotonic()
        self.current_bot_provider = provider
        self.current_bot_dry_run = dry_run
        self.current_bot_phase = "running"
        self.last_live_progress_summary = ""
        self._reset_bot_progress()
        if action == "watch-loop":
            self.watch_loop_stop_requested = False
            self.watch_loop_pass_completed = False
            self.watch_loop_stop_guard_until = time.monotonic() + 3.0
            if hasattr(self, "_set_manual_scan_refresh_active"):
                self._set_manual_scan_refresh_active(True)
        if action in {"watch-once", "watch-loop", "gmail-populate-labels", "outlook-populate-categories"}:
            self._append_bot_heartbeat()
            self.bot_heartbeat_timer.start()
            if action == "watch-once" and dry_run:
                self.bot_timeout_timer.start(120000)

    def _stop_bot_heartbeat(self) -> None:
        self.bot_heartbeat_timer.stop()
        self.bot_timeout_timer.stop()
        self.bot_action_started_at = None
        if hasattr(self, "_set_manual_scan_refresh_active"):
            self._set_manual_scan_refresh_active(False)

    def _append_bot_heartbeat(self) -> None:
        if self.bot_process is None or self.bot_action_started_at is None:
            self._stop_bot_heartbeat()
            return
        elapsed = short_duration_label(time.monotonic() - self.bot_action_started_at)
        provider = self.current_bot_provider.title() if self.current_bot_provider else "MailAssist"
        if self.current_bot_action == "watch-once":
            message = (
                f"{provider} preview still running after {elapsed}. "
                f"{self._bot_progress_summary()}. "
                "No email will be sent; auto-stops after 2 minutes."
            )
        elif self.current_bot_action == "watch-loop":
            if self.current_bot_phase == "waiting":
                summary = self.last_live_progress_summary or self._bot_progress_summary()
                message = f"Manual scan: {provider} waiting after {elapsed}. Last pass: {summary}."
                self._set_banner(message, level="info")
                return
            else:
                message = f"Manual scan: {provider} checking after {elapsed}. {self._bot_progress_summary()}."
        else:
            message = f"{provider} action still running after {elapsed}. {self._bot_progress_summary()}."
        self._append_recent_activity(message)
        self._set_banner(message, level="info")

    def _stop_bot_after_timeout(self) -> None:
        if self.bot_process is None:
            self._stop_bot_heartbeat()
            return
        provider = self.current_bot_provider.title() if self.current_bot_provider else "MailAssist"
        self._append_recent_activity(
            f"{provider} preview stopped after 2 minutes. No email was sent."
        )
        self._set_banner(f"{provider} preview stopped after 2 minutes.", level="error")
        self.stop_bot_action()

    def refresh_bot_logs(self) -> None:
        self.bot_log_selector.blockSignals(True)
        self.bot_log_selector.clear()
        log_paths = sorted(
            self.settings.bot_logs_dir.glob("*.jsonl"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in log_paths:
            self.bot_log_selector.addItem(self._bot_log_selector_label(path), str(path))
        self.bot_log_selector.blockSignals(False)
        self._refresh_summary_from_logs(log_paths)

        if self.latest_bot_log_path is not None:
            index = self.bot_log_selector.findData(str(self.latest_bot_log_path))
            if index >= 0:
                self.bot_log_selector.setCurrentIndex(index)
                self.load_selected_bot_log()
                return
        if self.bot_log_selector.count():
            self.bot_log_selector.setCurrentIndex(0)
            self.load_selected_bot_log()
        else:
            self.bot_log_viewer.clear()

    def refresh_service_activity_summary(self) -> None:
        log_paths = sorted(
            self.settings.bot_logs_dir.glob("*.jsonl"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        self._refresh_summary_from_logs(log_paths)
        self.refresh_dashboard()

    def _refresh_summary_from_logs(self, log_paths: list[Path]) -> None:
        latest_pass = ""
        latest_failure = ""
        latest_dashboard_event: dict[str, Any] | None = None
        latest_dashboard_timestamp: datetime | None = None
        latest_completed_watch_pass: dict[str, Any] | None = None
        latest_completed_watch_pass_summary = ""
        latest_completed_watch_timestamp: datetime | None = None
        boot_cutoff = system_boot_time_utc()
        session_counts = _empty_activity_counts()
        suppress_recent_log_append = (
            getattr(self, "bot_process", None) is not None
            and getattr(self, "current_bot_action", "") == "watch-loop"
        )
        for path in log_paths:
            events = read_bot_log_events(path)
            scoped_events = []
            for event in events:
                timestamp = _event_timestamp(event)
                if boot_cutoff is not None and (timestamp is None or timestamp < boot_cutoff):
                    continue
                scoped_events.append(event)
            candidate = _latest_event(
                [event for event in scoped_events if event.get("type") != "log_file"]
            )
            if candidate is not None:
                candidate_timestamp = _event_timestamp(candidate)
                if (
                    candidate_timestamp is not None
                    and (
                        latest_dashboard_timestamp is None
                        or candidate_timestamp >= latest_dashboard_timestamp
                    )
                ):
                    latest_dashboard_event = candidate
                    latest_dashboard_timestamp = candidate_timestamp
            latest_watch_pass = next(
                (
                    event
                    for event in reversed(scoped_events)
                    if event.get("type") == "watch_pass_completed"
                ),
                None,
            )
            if latest_watch_pass is not None:
                watch_timestamp = _event_timestamp(latest_watch_pass)
                if (
                    watch_timestamp is not None
                    and (
                        latest_completed_watch_timestamp is None
                        or watch_timestamp >= latest_completed_watch_timestamp
                    )
                ):
                    latest_completed_watch_pass = latest_watch_pass
                    latest_completed_watch_pass_summary = _watch_pass_summary(
                        latest_watch_pass,
                        scoped_events,
                    )
                    latest_completed_watch_timestamp = watch_timestamp
            _merge_activity_counts(
                session_counts,
                _activity_counts_from_events(events, cutoff=boot_cutoff),
            )
            completed = next(
                (event for event in reversed(events) if event.get("type") == "completed"),
                None,
            )
            error = next(
                (event for event in reversed(events) if event.get("type") == "error"),
                None,
            )
            if not latest_pass:
                latest_completed_pass = (
                    completed if completed and "draft_count" in completed else None
                )
                if latest_completed_pass:
                    when = event_day_time_label(completed.get("timestamp"))
                    latest_pass = (
                        f"{when} · {completed.get('draft_count', 0)} drafts · "
                        f"{completed.get('skipped_count', 0)} skipped · "
                        f"{completed.get('already_handled_count', 0)} already handled"
                    )
            if not latest_pass:
                if latest_watch_pass:
                    when = event_day_time_label(latest_watch_pass.get("timestamp"))
                    provider = str(latest_watch_pass.get("provider") or "").title()
                    pass_number = latest_watch_pass.get("pass_number")
                    pass_text = f"pass {pass_number}" if pass_number else "watch pass"
                    summary = _watch_pass_summary(latest_watch_pass, scoped_events)
                    caught_up = _caught_up_detail(latest_watch_pass)
                    prefix = (
                        f"{caught_up} {provider} {pass_text} completed at {when}"
                        if caught_up
                        else f"{when} - {provider} {pass_text} completed"
                    )
                    if summary:
                        latest_pass = f"{prefix}: {summary}"
                    else:
                        latest_pass = prefix
            if not latest_failure:
                err = next(
                    (event for event in reversed(events) if event.get("type") == "error"),
                    None,
                )
                if err:
                    when = event_day_time_label(err.get("timestamp"))
                    message = user_facing_failure_message(str(err.get("message") or "Bot error.").strip())
                    latest_failure = f"{when} · {message}"
        if latest_pass:
            self.last_pass_summary = latest_pass
        if latest_failure:
            self.last_failure_summary = latest_failure
        live_state_counts = _activity_counts_from_live_state(self.settings.root_dir, cutoff=boot_cutoff)
        if _has_activity_counts(live_state_counts):
            live_state_counts["failed"] += session_counts.get("failed", 0)
            self.activity_history_summary = _activity_summary(live_state_counts)
        else:
            self.activity_history_summary = _activity_summary(session_counts)
        if latest_dashboard_event is not None:
            dashboard_pass_summary = ""
            if latest_dashboard_event is latest_completed_watch_pass:
                dashboard_pass_summary = latest_completed_watch_pass_summary
            message = _dashboard_event_message(
                latest_dashboard_event,
                pass_summary=dashboard_pass_summary,
            )
            self.last_activity_summary = message
            self.background_scan_last_seen_at = latest_dashboard_timestamp
            recent_event = latest_dashboard_event
            recent_message = message
            if latest_completed_watch_pass is not None and (
                latest_dashboard_event.get("type") in {"sleeping", "watch_pass_completed", "completed"}
                or latest_dashboard_timestamp is None
                or (
                    latest_completed_watch_timestamp is not None
                    and latest_completed_watch_timestamp >= latest_dashboard_timestamp
                )
            ):
                recent_event = latest_completed_watch_pass
                recent_message = _dashboard_event_message(
                    latest_completed_watch_pass,
                    pass_summary=latest_completed_watch_pass_summary,
                )
                self.last_activity_summary = recent_message
            event_key = _service_recent_event_key(recent_event)
            if (
                hasattr(self, "recent_activity")
                and event_key
                and event_key != getattr(self, "service_activity_recent_event_key", "")
                and not suppress_recent_log_append
            ):
                self.service_activity_recent_event_key = event_key
                self._append_recent_activity(recent_message)
        else:
            self.background_scan_last_seen_at = None

    def _bot_log_selector_label(self, path: Path) -> str:
        events = read_bot_log_events(path)
        if not events:
            return path.name
        first = events[0]
        completed = next((event for event in reversed(events) if event.get("type") == "completed"), {})
        action = str(first.get("action") or path.name.removeprefix("bot-").split("-", 1)[0])
        pieces = [event_day_time_label(first.get("timestamp")), log_action_label(action)]
        provider = completed.get("provider")
        if provider:
            pieces.append(str(provider).title())
        if action == "watch-once" and completed:
            draft_count = int(completed.get("draft_count") or 0)
            skipped_count = int(completed.get("skipped_count") or 0)
            already_count = int(completed.get("already_handled_count") or 0)
            pieces.append(f"{draft_count} draft{'s' if draft_count != 1 else ''}")
            draft_ready_count = int(completed.get("draft_ready_count") or 0)
            if draft_ready_count:
                pieces.append(f"{draft_ready_count} dry run{'s' if draft_ready_count != 1 else ''}")
            if skipped_count:
                pieces.append(f"{skipped_count} skipped")
            if already_count:
                pieces.append(f"{already_count} already handled")
        elif action == "ollama-check":
            pieces.append("success" if completed else "running")
        elif completed and "message_count" in completed:
            pieces.append(f"{completed.get('message_count')} messages")
        elif completed and "processed_count" in completed:
            pieces.append(f"{completed.get('processed_count')} processed")
        if any(event.get("type") == "error" for event in events):
            pieces.append("error")
        return " - ".join(pieces)

    def run_gmail_draft_test(self) -> None:
        if self._main_bot_action_unavailable():
            return
        self._announce_long_action(
            "Previewing Gmail draft. Dry run only; no Gmail draft will be created. "
            "Heartbeat updates will appear here and the preview auto-stops after 2 minutes."
        )
        self.run_bot_action(
            "watch-once",
            provider="gmail",
            thread_id="thread-008",
            force=True,
            dry_run=True,
        )

    def run_controlled_gmail_draft(self) -> None:
        if self._main_bot_action_unavailable():
            return
        confirmation = self._confirm_action(
            "Create Controlled Gmail Draft",
            (
                "MailAssist will create one real Gmail draft addressed to your own Gmail account "
                "using sanitized mock content. Nothing will be sent. Continue?"
            ),
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            self._set_banner("Controlled Gmail draft canceled.", level="info")
            return
        self._announce_long_action(
            "Creating one controlled Gmail test draft. This may take a minute; nothing will be sent."
        )
        self.run_bot_action("gmail-controlled-draft", provider="gmail", thread_id="thread-008")

    def run_outlook_draft_preview(self) -> None:
        if self._main_bot_action_unavailable():
            return
        self.save_settings(announce=False)
        self._announce_long_action(
            "Previewing Outlook draft. Dry run only; no Outlook draft will be created. "
            "Heartbeat updates will appear here and the preview auto-stops after 2 minutes."
        )
        self.run_bot_action(
            "watch-once",
            provider="outlook",
            force=True,
            dry_run=True,
            limit=1,
        )

    def run_gmail_label_rescan(self) -> None:
        if self._main_bot_action_unavailable():
            return
        days = int(self.gmail_label_days_input.value()) if hasattr(self, "gmail_label_days_input") else 7
        confirmation = self._confirm_action(
            "Organize Gmail",
            (
                f"MailAssist will reclassify Gmail threads from the last {days} day"
                f"{'' if days == 1 else 's'} using the current category list. "
                "It may add, replace, or remove MailAssist labels.\n\n"
                "This can take a few minutes, but you can keep working while it runs. "
                "Continue?"
            ),
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            self._set_banner("Gmail label rescan canceled.", level="info")
            return
        self.save_settings(announce=False)
        self._announce_long_action(
            f"Organizing Gmail for the last {days} day{'' if days == 1 else 's'}. "
            "This can take a few minutes while the local model classifies messages."
        )
        self.run_bot_action(
            "gmail-populate-labels",
            provider="gmail",
            days=days,
            limit=500,
            apply_labels=True,
        )

    def run_outlook_category_rescan(self) -> None:
        if self._main_bot_action_unavailable():
            return
        days = (
            int(self.outlook_category_days_input.value())
            if hasattr(self, "outlook_category_days_input")
            else 25
        )
        confirmation = self._confirm_action(
            "Organize Outlook",
            (
                f"MailAssist will classify Outlook messages from the last {days} day"
                f"{'' if days == 1 else 's'} using the current category list. "
                "It may add, replace, or remove MailAssist Outlook categories.\n\n"
                "This can take a few minutes, but you can keep working while it runs. "
                "Continue?"
            ),
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            self._set_banner("Outlook category rescan canceled.", level="info")
            return
        self.save_settings(announce=False)
        self._announce_long_action(
            f"Organizing Outlook for the last {days} day{'' if days == 1 else 's'}. "
            "This can take a few minutes while the local model classifies messages."
        )
        self.run_bot_action(
            "outlook-populate-categories",
            provider="outlook",
            days=days,
            apply_categories=True,
        )

    def run_bot_action(
        self,
        action: str,
        *,
        thread_id: str = "",
        prompt: str = "",
        provider: str = "",
        force: bool = False,
        dry_run: bool = False,
        days: int | None = None,
        limit: int | None = None,
        max_passes: int | None = None,
        apply_labels: bool = False,
        apply_categories: bool = False,
    ) -> None:
        if self._bot_action_already_running():
            return
        if action != "ollama-check" and self._bot_action_blocked_by_settings():
            return

        base_url, selected_model = self._current_bot_ollama_settings()
        self.bot_stdout_buffer = ""
        self.current_bot_action = action
        self.current_bot_provider = provider
        self.current_bot_dry_run = dry_run
        self._reset_bot_progress()
        request = BotActionRequest(
            action=action,
            base_url=base_url,
            selected_model=selected_model,
            thread_id=thread_id,
            prompt=prompt,
            provider=provider,
            force=force,
            dry_run=dry_run,
            apply_labels=apply_labels,
            apply_categories=apply_categories,
            days=days,
            limit=limit,
            max_passes=max_passes,
        )
        args = build_bot_action_args(request)

        self.bot_process = QProcess(self)
        self.bot_process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.bot_process.setWorkingDirectory(str(self.settings.root_dir))
        self.bot_process.setProcessEnvironment(build_bot_process_environment(request))
        self.bot_process.readyReadStandardOutput.connect(self._handle_bot_stdout)
        self.bot_process.finished.connect(self._handle_bot_finished)

        python_executable = (
            self._bot_python_executable()
            if hasattr(self, "_bot_python_executable")
            else sys.executable
        )
        self._append_bot_console(f"$ {python_executable} {' '.join(args)}")
        self._set_banner(
            f"Starting bot action: {action}. Ollama work can take 1-2 minutes.",
            level="info",
        )
        self._set_bot_state("running")
        self._refresh_bot_action_controls()
        self._start_bot_heartbeat(action, provider, dry_run=dry_run)
        self.bot_process.start(python_executable, args)

    def _handle_bot_stdout(self) -> None:
        if self.bot_process is None:
            return
        chunk = bytes(self.bot_process.readAllStandardOutput()).decode("utf-8", errors="replace")
        self.bot_stdout_buffer += chunk
        while "\n" in self.bot_stdout_buffer:
            line, self.bot_stdout_buffer = self.bot_stdout_buffer.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            self._append_bot_console(line)
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._handle_bot_event(event)

    def _handle_bot_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        if event_type == "log_file":
            self.latest_bot_log_path = Path(str(event.get("path")))
            self.refresh_bot_logs()
        elif event_type == "ollama_result":
            prompt = str(event.get("prompt", "")).strip()
            result = str(event.get("result", "")).strip()
            success = f"Test successful after {self._ollama_test_elapsed_label()}."
            self._stop_ollama_test_countdown()
            self.ollama_result_label.setText(success)
            if prompt:
                self._set_ollama_result_text(f"{success}\n\nPrompt: {prompt}\n\nResponse: {result}")
            else:
                self._set_ollama_result_text(f"{success}\n\nResponse: {result}")
            self._set_banner(success, level="info")
        elif event_type == "draft_created":
            self.bot_progress["checked"] = self.bot_progress.get("checked", 0) + 1
            self.bot_progress["drafts"] = self.bot_progress.get("drafts", 0) + 1
            if self.current_bot_action == "watch-loop":
                self._append_recent_activity(_dashboard_event_message(event, source_label="manual"))
        elif event_type == "draft_ready":
            self.bot_progress["checked"] = self.bot_progress.get("checked", 0) + 1
            self.bot_progress["draft_previews"] = self.bot_progress.get("draft_previews", 0) + 1
            if self.current_bot_action == "watch-loop":
                self._append_recent_activity(_dashboard_event_message(event, source_label="manual"))
        elif event_type == "skipped_email":
            self.bot_progress["checked"] = self.bot_progress.get("checked", 0) + 1
            self.bot_progress["skipped"] = self.bot_progress.get("skipped", 0) + 1
            if self.current_bot_action == "watch-loop":
                self._append_recent_activity(_dashboard_event_message(event, source_label="manual"))
        elif event_type == "already_handled":
            self.bot_progress["checked"] = self.bot_progress.get("checked", 0) + 1
            self.bot_progress["already_handled"] = self.bot_progress.get("already_handled", 0) + 1
            if self.current_bot_action == "watch-loop":
                self._append_recent_activity(_dashboard_event_message(event, source_label="manual"))
        elif event_type == "user_replied":
            self.bot_progress["checked"] = self.bot_progress.get("checked", 0) + 1
            self.bot_progress["already_handled"] = self.bot_progress.get("already_handled", 0) + 1
            if self.current_bot_action == "watch-loop":
                self._append_recent_activity(_dashboard_event_message(event, source_label="manual"))
        elif event_type == "filtered_out":
            self.bot_progress["checked"] = self.bot_progress.get("checked", 0) + 1
            self.bot_progress["filtered"] = self.bot_progress.get("filtered", 0) + 1
            if self.current_bot_action == "watch-loop":
                self._append_recent_activity(_dashboard_event_message(event, source_label="manual"))
        elif event_type == "generation_failed":
            self.bot_progress["failed"] = self.bot_progress.get("failed", 0) + 1
            if self.current_bot_action == "watch-loop":
                self._append_recent_activity(_dashboard_event_message(event, source_label="manual"))
        elif event_type == "scan_lock_waiting":
            message = str(event.get("message") or "").strip()
            if not message:
                message = "Manual scan waiting for the active background scan to finish."
            self.current_bot_phase = "running"
            self.bot_progress["current_detail"] = "waiting for active scan"
            self._append_recent_activity(f"Manual scan: {message}")
            self._set_banner(message, level="info")
        elif event_type == "scan_lock_busy":
            message = str(event.get("message") or "").strip()
            if not message:
                message = "Manual scan could not start because another scan is still running."
            self.bot_progress["failed"] = self.bot_progress.get("failed", 0) + 1
            self.last_failure_summary = message
            self._append_recent_activity(f"Manual scan: {message}")
            self._set_banner(message, level="error")
        elif event_type == "email_work_started":
            message_time = event_day_time_label(event.get("message_timestamp"))
            self.bot_progress["current_detail"] = message_time
            provider = str(event.get("provider") or self.current_bot_provider or "provider").title()
            if self.current_bot_action == "watch-loop":
                self._append_recent_activity(
                    f"Manual scan: {provider} working on message dated {message_time}."
                )
            else:
                self._append_recent_activity(f"{provider} preview working on message dated {message_time}.")
        elif event_type == "email_classified":
            bucket = _classification_bucket(event.get("classification"))
            self.bot_progress[bucket] = self.bot_progress.get(bucket, 0) + 1
        elif event_type in {
            "gmail_thread_labeled",
            "gmail_thread_label_preview",
            "outlook_thread_categorized",
            "outlook_thread_category_preview",
        }:
            self.bot_progress["categorized"] = self.bot_progress.get("categorized", 0) + 1
            self.bot_progress["updated_messages"] = (
                self.bot_progress.get("updated_messages", 0) + int(event.get("updated_message_count") or 0)
            )
        elif event_type in {
            "organize_phase",
            "gmail_thread_classification_started",
            "outlook_thread_classification_started",
        }:
            if "thread_count" in event:
                self.bot_progress["total"] = int(event.get("thread_count") or 0)
            if "current_index" in event:
                self.bot_progress["current_index"] = int(event.get("current_index") or 0)
            message = str(event.get("message") or "").strip()
            if event_type == "organize_phase":
                detail = message or "Preparing organizer run."
                self.bot_progress["current_detail"] = detail
                self._append_recent_activity(detail)
        elif event_type == "watch_pass_started":
            self.current_bot_phase = "running"
            self._reset_bot_progress()
            self._append_recent_activity(_dashboard_event_message(event, source_label="manual"))
        elif event_type == "watch_pass_completed":
            self.current_bot_phase = "waiting"
            self.watch_loop_pass_completed = True
            if _event_has_activity_counts(event):
                self.last_live_progress_summary = _activity_summary(
                    _activity_counts_from_event_payload(event)
                )
            else:
                self.last_live_progress_summary = self._bot_progress_summary()
            self._append_recent_activity(
                _dashboard_event_message(
                    event,
                    pass_summary=self.last_live_progress_summary,
                    source_label="manual",
                )
            )
        elif event_type == "failed_pass":
            self._append_recent_activity(f"Watch pass failed: {event.get('message', 'Unknown error')}")
        elif event_type == "sleeping":
            self.current_bot_phase = "waiting"
        elif event_type == "outlook_readiness":
            ready = bool(event.get("ready"))
            self.current_provider_ready = ready
            self.current_provider_readiness_message = str(event.get("message") or "").strip()
            if not ready:
                message = self.current_provider_readiness_message or "Outlook connection is not ready."
                self._append_recent_activity(f"Outlook connection failed: {message}")
                self.last_failure_summary = message
                self._set_banner(message, level="error")
        elif event_type == "completed":
            self._stop_bot_heartbeat()
            if event.get("action") != "ollama-check":
                self._set_banner(str(event.get("message", "Bot action completed.")), level="info")
            self.settings = load_settings()
            self.refresh_models()
            self.refresh_bot_logs()
            if "draft_count" in event:
                draft_count = event.get("draft_count", 0)
                draft_ready_count = event.get("draft_ready_count", 0)
                skipped_count = event.get("skipped_count", 0)
                already_count = event.get("already_handled_count", 0)
                filtered_count = event.get("filtered_out_count", 0)
                self.last_pass_summary = (
                    f"{draft_count} drafts · {draft_ready_count} dry runs · {skipped_count} skipped · "
                    f"{already_count} already handled · {filtered_count} filtered"
                )
                provider = str(event.get("provider") or "").strip()
                provider_label = provider.title() if provider else "Provider"
                prefix = (
                    f"{provider_label} preview completed"
                    if event.get("dry_run")
                    else f"{provider_label} watch pass completed"
                )
                self._append_recent_activity(f"{prefix}: {self.last_pass_summary}.")
            elif "thread_count" in event:
                provider = str(event.get("provider") or "").strip()
                provider_label = provider.title() if provider else "Provider"
                thread_count = int(event.get("thread_count") or 0)
                applied_count = int(event.get("applied_count") or 0)
                updated_messages = int(event.get("message_update_count") or 0)
                if event.get("ready") is False:
                    reason = str(self.current_provider_readiness_message or event.get("message") or "").strip()
                    if reason:
                        detail = organizer_stop_message(
                            provider_label,
                            reason,
                            categorized=0,
                            stage="before reading mail",
                        )
                    else:
                        detail = f"{provider_label} organize stopped before reading mail because the provider is not connected."
                    self.last_failure_summary = reason or "Provider is not connected."
                elif updated_messages:
                    detail = (
                        f"{provider_label} organize completed: {thread_count} emails categorized · "
                        f"{applied_count} category writes · {updated_messages} messages updated."
                    )
                else:
                    detail = (
                        f"{provider_label} organize completed: {thread_count} emails categorized · "
                        f"{applied_count} updates applied."
                    )
                self._append_recent_activity(detail)
            self.refresh_dashboard()
        elif event_type == "error":
            self._stop_bot_heartbeat()
            failure = user_facing_failure_message(str(event.get("message", "Bot action failed.")))
            provider = str(event.get("provider") or self.current_bot_provider or "").strip()
            provider_label = provider.title() if provider else "MailAssist"
            if self.current_bot_action == "watch-once" and self.current_bot_dry_run:
                self._append_recent_activity(f"{provider_label} preview failed: {failure}")
            elif is_organizer_action(str(event.get("action") or self.current_bot_action or "")):
                categorized = int(self.bot_progress.get("categorized", 0) or 0)
                self._append_recent_activity(
                    organizer_stop_message(provider_label, failure, categorized=categorized)
                )
            else:
                self._append_recent_activity(f"{provider_label} action failed: {failure}")
            if event.get("action") == "ollama-check":
                self._stop_ollama_test_countdown()
                self.ollama_result_label.setText(
                    f"Model test failed after {self._ollama_test_elapsed_label()}."
                )
            self.last_failure_summary = failure
            self._set_banner(failure, level="error")
            self._set_bot_state("error", self._short_bot_error_label(failure, provider=provider))
        elif event_type == "info":
            if "thread_count" in event:
                self.bot_progress["total"] = int(event.get("thread_count") or 0)
            self._set_banner(str(event.get("message", "")), level="info")

    def _handle_bot_finished(self, exit_code: int, _exit_status) -> None:
        if self.bot_stdout_buffer.strip():
            self._append_bot_console(self.bot_stdout_buffer.strip())
            self.bot_stdout_buffer = ""
        self._stop_bot_heartbeat()
        finished_action = self.current_bot_action
        stopped_by_user = bool(getattr(self, "watch_loop_stop_requested", False))
        pass_completed = bool(getattr(self, "watch_loop_pass_completed", False))
        self.bot_process = None
        if finished_action == "watch-loop" and stopped_by_user:
            self._append_recent_activity(
                f"{event_day_time_label(datetime.now(timezone.utc))}: manual agent suspended."
            )
        elif finished_action == "watch-loop" and exit_code == 0 and not pass_completed:
            self._append_recent_activity(
                f"{event_day_time_label(datetime.now(timezone.utc))}: "
                "manual agent finished before completing a pass."
            )
        if finished_action == "watch-loop" and hasattr(self, "_resume_background_scan_after_gui_test"):
            self._resume_background_scan_after_gui_test()
        if hasattr(self, "stop_bot_button"):
            self.stop_bot_button.setEnabled(False)
        if exit_code != 0 and not stopped_by_user:
            if finished_action == "ollama-check":
                self._stop_ollama_test_countdown()
                self.ollama_result_label.setText(
                    f"Model test failed after {self._ollama_test_elapsed_label()}."
                )
            failure = f"Bot exited with code {exit_code}."
            self.last_failure_summary = failure
            self._set_banner(failure, level="error")
            self._set_bot_state("error")
        elif self.last_bot_state != "error":
            if finished_action == "ollama-check":
                self._stop_ollama_test_countdown()
            self._set_bot_state("idle")
        self.current_bot_action = ""
        self.current_bot_provider = ""
        self.current_bot_dry_run = False
        self.current_bot_phase = ""
        self.last_live_progress_summary = ""
        self.current_provider_ready = True
        self.current_provider_readiness_message = ""
        self.watch_loop_stop_guard_until = 0.0
        self.watch_loop_stop_requested = False
        self.watch_loop_pass_completed = False
        self.refresh_dashboard()
        self.refresh_bot_logs()

    def load_selected_bot_log(self, *_args: object) -> None:
        log_path_value = self.bot_log_selector.currentData()
        if not log_path_value:
            self.bot_log_viewer.clear()
            return
        log_path = Path(str(log_path_value))
        if not log_path.exists():
            self.bot_log_viewer.clear()
            self._set_banner("The selected bot log no longer exists.", level="error")
            return
        raw_text = log_path.read_text(encoding="utf-8")
        if self.show_raw_log_checkbox.isChecked():
            self.bot_log_viewer.setPlainText(raw_text)
            return
        self.bot_log_viewer.setPlainText(format_bot_log_for_humans(log_path, raw_text))

    def _format_bot_log_for_humans(self, path: Path, raw_text: str) -> str:
        return format_bot_log_for_humans(path, raw_text)
