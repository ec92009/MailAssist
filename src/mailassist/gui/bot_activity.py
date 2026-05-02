from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def humanize(token: str) -> str:
    return token.replace("_", " ").title()


def user_facing_failure_message(message: str) -> str:
    if message.strip() == "invalid_grant":
        return (
            "Outlook sign-in expired or was revoked (invalid_grant). "
            "Run Outlook setup/auth again before previewing Outlook drafts."
        )
    return message


def is_organizer_action(action: str) -> bool:
    return action in {"gmail-populate-labels", "outlook-populate-categories"}


def organizer_stop_message(provider_label: str, reason: str, *, categorized: int, stage: str = "") -> str:
    if categorized > 0:
        return f"{provider_label} organize stopped after {categorized} emails categorized: {reason}"
    if stage:
        return f"{provider_label} organize stopped {stage}: {reason}"
    return f"{provider_label} organize stopped before the first category: {reason}"


def parse_event_timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone()


def event_time_label(value: object) -> str:
    parsed = parse_event_timestamp(value)
    if parsed is None:
        return "--:--"
    return parsed.strftime("%H:%M:%S")


def event_day_time_label(value: object) -> str:
    parsed = parse_event_timestamp(value)
    if parsed is None:
        return "Unknown time"
    today = datetime.now(parsed.tzinfo).date()
    if parsed.date() == today:
        prefix = "Today"
    elif (today - parsed.date()).days == 1:
        prefix = "Yesterday"
    else:
        prefix = parsed.strftime("%b %-d")
    return f"{prefix} {parsed.strftime('%H:%M')}"


def short_duration_label(seconds: float) -> str:
    whole_seconds = max(0, int(round(seconds)))
    if whole_seconds < 60:
        return f"{whole_seconds} second{'s' if whole_seconds != 1 else ''}"
    minutes, remainder = divmod(whole_seconds, 60)
    if remainder:
        return f"{minutes} min {remainder} sec"
    return f"{minutes} min"


def log_action_label(action: str) -> str:
    labels = {
        "gmail-controlled-draft": "Controlled Gmail draft",
        "gmail-inbox-preview": "Gmail inbox preview",
        "ollama-check": "Ollama check",
        "watch-once": "Watch pass",
        "watch-loop": "Watch loop",
    }
    return labels.get(action, humanize(action))


def parse_bot_log_events(raw_text: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            events.append(parsed)
    return events


def read_bot_log_events(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return parse_bot_log_events(path.read_text(encoding="utf-8"))


def format_bot_log_for_humans(path: Path, raw_text: str) -> str:
    events = parse_bot_log_events(raw_text)
    if not events:
        return f"No readable events were found in {path.name}."

    first = events[0]
    completed = next((event for event in reversed(events) if event.get("type") == "completed"), None)
    errors = [event for event in events if event.get("type") == "error" or event.get("generation_error")]
    action = str(first.get("action") or "")
    title = log_action_label(action)
    started_at = first.get("timestamp")
    finished_at = completed.get("timestamp") if completed else None
    duration = log_duration_label(started_at, finished_at)

    lines = [
        f"{event_day_time_label(started_at)} - {title}",
        "",
        "Summary",
        f"Started: {event_time_label(started_at)}",
    ]
    if completed:
        lines.append(f"Finished: {event_time_label(finished_at)}{f' ({duration})' if duration else ''}")
    else:
        lines.append("Finished: not yet")
    lines.extend(bot_log_summary_lines(action, events, completed, errors))
    if errors:
        lines.extend(["", "Needs Attention"])
        lines.extend(f"- {event_human_message(event)}" for event in errors)
    lines.extend(["", "Timeline"])
    for event in events:
        if event.get("type") == "log_file":
            continue
        lines.append(f"{event_time_label(event.get('timestamp'))}  {event_human_message(event)}")
    lines.extend(["", f"Raw log file: {path}"])
    return "\n".join(lines)


def log_duration_label(started_at: object, finished_at: object) -> str:
    start = parse_event_timestamp(started_at)
    finish = parse_event_timestamp(finished_at)
    if start is None or finish is None:
        return ""
    seconds = max(0, int((finish - start).total_seconds()))
    if seconds < 60:
        return f"{seconds} seconds"
    minutes, remainder = divmod(seconds, 60)
    return f"{minutes} min {remainder} sec" if remainder else f"{minutes} min"


def bot_log_summary_lines(
    action: str,
    events: list[dict[str, object]],
    completed: dict[str, object] | None,
    errors: list[dict[str, object]],
) -> list[str]:
    lines: list[str] = []
    started = events[0]
    arguments = started.get("arguments") if isinstance(started.get("arguments"), dict) else {}
    provider = (completed or {}).get("provider") or arguments.get("provider")
    model = (completed or {}).get("selected_model") or arguments.get("selected_model")
    if provider and action != "ollama-check":
        lines.append(f"Provider: {str(provider).title()}")
    if model:
        lines.append(f"Model: {model}")
    if completed:
        for key, label in (
            ("draft_count", "Drafts created"),
            ("skipped_count", "Skipped"),
            ("already_handled_count", "Already handled"),
            ("filtered_out_count", "Filtered out"),
            ("message_count", "Messages read"),
        ):
            if key in completed:
                lines.append(f"{label}: {completed.get(key)}")
    lines.append(f"Result: {'Error' if errors else 'OK'}")
    return lines


def event_human_message(event: dict[str, object]) -> str:
    event_type = str(event.get("type") or "")
    message = str(event.get("message") or "").strip()
    subject = str(event.get("subject") or "").strip()
    classification = str(event.get("classification") or "").strip()
    if event_type == "started":
        return f"Started {log_action_label(str(event.get('action') or 'bot action'))}."
    if event_type == "log_file":
        return "Opened the run log file."
    if event_type == "info":
        return message or "Information event."
    if event_type == "draft_created":
        detail = f'Created draft for "{subject}".' if subject else "Created draft."
        if classification:
            detail += f" Classification: {humanize(classification)}."
        provider_draft_id = event.get("provider_draft_id")
        if provider_draft_id:
            detail += f" Draft ID: {provider_draft_id}."
        return detail
    if event_type == "already_handled":
        return f'Already handled "{subject}".' if subject else "Already handled an email."
    if event_type == "skipped_email":
        return message or (f'Skipped "{subject}".' if subject else "Skipped an email.")
    if event_type == "filtered_out":
        reason = str(event.get("reason") or "filter")
        return f'Filtered out "{subject}" by {reason}.' if subject else f"Filtered out an email by {reason}."
    if event_type == "gmail_message_preview":
        sender = event.get("sender") or event.get("from") or "unknown sender"
        return f'Previewed Gmail message "{subject or event.get("snippet", "")}" from {sender}.'
    if event_type == "ollama_result":
        result = str(event.get("result") or "").strip()
        return f"Ollama replied: {result}" if result else "Ollama returned an empty reply."
    if event_type == "completed":
        return message or "Completed."
    if event_type == "error":
        return message or "Error."
    if event.get("generation_error"):
        return f"Draft generation error: {event.get('generation_error')}"
    return message or humanize(event_type)
