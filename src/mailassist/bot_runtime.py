from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from uuid import uuid4

from mailassist.background_bot import run_mock_watch_pass
from mailassist.config import load_settings
from mailassist.llm.ollama import OllamaClient
from mailassist.models import utc_now_iso
from mailassist.providers.factory import get_provider_for_settings


class BotEventReporter:
    def __init__(self, logs_dir: Path, action: str) -> None:
        self.run_id = str(uuid4())
        self.action = action
        self.log_path = logs_dir / f"bot-{action}-{self.run_id}.jsonl"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event_type: str, **payload: object) -> None:
        event = {
            "type": event_type,
            "action": self.action,
            "run_id": self.run_id,
            "timestamp": utc_now_iso(),
            **payload,
        }
        line = json.dumps(event, ensure_ascii=True)
        print(line, flush=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def build_review_bot_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "review-bot",
        help="Run a bot/debug action and emit JSONL events on stdout.",
    )
    parser.add_argument(
        "--action",
        required=True,
        choices=(
            "ollama-check",
            "watch-once",
            "watch-loop",
            "gmail-inbox-preview",
        ),
        help="Bot action to run.",
    )
    parser.add_argument("--thread-id", help="Optional thread ID for targeted watch passes.")
    parser.add_argument("--prompt", help="Prompt for Ollama check actions.")
    parser.add_argument("--base-url", help="Ollama base URL for bot actions.")
    parser.add_argument("--selected-model", help="Ollama model for bot actions.")
    parser.add_argument("--provider", default="mock", help="Provider to watch for watch-once.")
    parser.add_argument("--limit", type=int, default=10, help="Maximum Gmail messages for preview actions.")
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=0,
        help="Seconds to wait between watch-loop polling passes. Defaults to MAILASSIST_BOT_POLL_SECONDS.",
    )
    parser.add_argument(
        "--max-passes",
        type=int,
        default=0,
        help="Maximum passes for watch-loop. Use 0 to keep polling until stopped.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1,
        help="Number of actionable mock emails to submit to Ollama per prompt during watch-once.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reprocess mock inbox items even if they already exist in a queue phase.",
    )


def command_review_bot(args: argparse.Namespace) -> int:
    settings = load_settings()
    base_url = (getattr(args, "base_url", None) or settings.ollama_url).strip()
    selected_model = (getattr(args, "selected_model", None) or settings.ollama_model).strip()
    reporter = BotEventReporter(settings.bot_logs_dir, args.action)
    reporter.emit(
        "started",
        command="review-bot",
        arguments={
            "action": args.action,
            "thread_id": args.thread_id,
            "prompt": args.prompt,
            "base_url": base_url,
            "selected_model": selected_model,
            "force": bool(getattr(args, "force", False)),
            "provider": getattr(args, "provider", "mock"),
            "poll_seconds": int(getattr(args, "poll_seconds", 0) or 0),
            "max_passes": int(getattr(args, "max_passes", 0) or 0),
            "batch_size": max(1, int(getattr(args, "batch_size", 1) or 1)),
        },
    )
    reporter.emit("log_file", path=str(reporter.log_path))

    try:
        if args.action == "gmail-inbox-preview":
            provider = get_provider_for_settings(settings, "gmail")
            reader = getattr(provider, "list_recent_inbox_messages", None)
            if not callable(reader):
                raise RuntimeError("The configured Gmail provider cannot list inbox messages.")
            limit = max(1, int(getattr(args, "limit", 10) or 10))
            reporter.emit(
                "info",
                message=f"Reading metadata for the latest {limit} Gmail inbox message(s).",
                provider="gmail",
                limit=limit,
            )
            messages = reader(limit=limit)
            for message in messages:
                reporter.emit("gmail_message_preview", **message)
            reporter.emit(
                "completed",
                message="Gmail inbox preview completed.",
                provider="gmail",
                message_count=len(messages),
            )
            return 0

        if args.action == "watch-once":
            provider_name = getattr(args, "provider", "mock") or "mock"
            provider = get_provider_for_settings(settings, provider_name)
            reporter.emit(
                "info",
                message=f"Running one watch pass for {provider_name}.",
                provider=provider_name,
            )
            events = run_mock_watch_pass(
                settings=settings,
                provider=provider,
                base_url=base_url,
                selected_model=selected_model,
                thread_id=args.thread_id or "",
                force=bool(getattr(args, "force", False)),
                batch_size=max(1, int(getattr(args, "batch_size", 1) or 1)),
            )
            draft_count = 0
            skipped_count = 0
            already_handled_count = 0
            user_replied_count = 0
            filtered_out_count = 0
            for event in events:
                event_type = str(event.pop("type"))
                if event_type == "draft_created":
                    draft_count += 1
                elif event_type == "skipped_email":
                    skipped_count += 1
                elif event_type == "already_handled":
                    already_handled_count += 1
                elif event_type == "user_replied":
                    user_replied_count += 1
                elif event_type == "filtered_out":
                    filtered_out_count += 1
                reporter.emit(event_type, **event)
            reporter.emit(
                "completed",
                message="Watch pass completed.",
                provider=provider_name,
                draft_count=draft_count,
                skipped_count=skipped_count,
                already_handled_count=already_handled_count,
                user_replied_count=user_replied_count,
                filtered_out_count=filtered_out_count,
            )
            return 0

        if args.action == "watch-loop":
            provider_name = getattr(args, "provider", "mock") or "mock"
            provider = get_provider_for_settings(settings, provider_name)
            poll_seconds = max(1, int(getattr(args, "poll_seconds", 0) or settings.bot_poll_seconds or 30))
            max_passes = max(0, int(getattr(args, "max_passes", 0) or 0))
            completed_passes = 0
            total_draft_count = 0
            total_skipped_count = 0
            total_already_handled_count = 0
            total_user_replied_count = 0
            total_filtered_out_count = 0
            failed_pass_count = 0
            retry_count = 0
            reporter.emit(
                "info",
                message=f"Starting polling watch loop for {provider_name}.",
                provider=provider_name,
                poll_seconds=poll_seconds,
                max_passes=max_passes,
            )

            while True:
                completed_passes += 1
                pass_failed = False
                reporter.emit(
                    "watch_pass_started",
                    provider=provider_name,
                    pass_number=completed_passes,
                )
                try:
                    events = run_mock_watch_pass(
                        settings=settings,
                        provider=provider,
                        base_url=base_url,
                        selected_model=selected_model,
                        thread_id=args.thread_id or "",
                        force=bool(getattr(args, "force", False)),
                        batch_size=max(1, int(getattr(args, "batch_size", 1) or 1)),
                    )
                    for event in events:
                        event_type = str(event.pop("type"))
                        if event_type == "draft_created":
                            total_draft_count += 1
                        elif event_type == "skipped_email":
                            total_skipped_count += 1
                        elif event_type == "already_handled":
                            total_already_handled_count += 1
                        elif event_type == "user_replied":
                            total_user_replied_count += 1
                        elif event_type == "filtered_out":
                            total_filtered_out_count += 1
                        reporter.emit(event_type, **event)
                    reporter.emit(
                        "watch_pass_completed",
                        provider=provider_name,
                        pass_number=completed_passes,
                    )
                except Exception as exc:
                    pass_failed = True
                    failed_pass_count += 1
                    reporter.emit(
                        "failed_pass",
                        provider=provider_name,
                        pass_number=completed_passes,
                        message=str(exc),
                    )
                if max_passes and completed_passes >= max_passes:
                    break
                if pass_failed:
                    retry_count += 1
                    reporter.emit(
                        "retry_scheduled",
                        provider=provider_name,
                        pass_number=completed_passes + 1,
                        poll_seconds=poll_seconds,
                    )
                reporter.emit(
                    "sleeping",
                    provider=provider_name,
                    poll_seconds=poll_seconds,
                )
                time.sleep(poll_seconds)

            reporter.emit(
                "completed",
                message="Watch loop completed.",
                provider=provider_name,
                completed_passes=completed_passes,
                draft_count=total_draft_count,
                skipped_count=total_skipped_count,
                already_handled_count=total_already_handled_count,
                user_replied_count=total_user_replied_count,
                filtered_out_count=total_filtered_out_count,
                failed_pass_count=failed_pass_count,
                retry_count=retry_count,
            )
            return 0

        if args.action == "ollama-check":
            prompt = (args.prompt or "").strip()
            if not prompt:
                raise ValueError("--prompt is required for ollama-check")
            reporter.emit("info", message="Running Ollama check.")
            result = OllamaClient(base_url, selected_model).compose_reply(prompt)
            reporter.emit("ollama_result", prompt=prompt, result=result or "")
            reporter.emit(
                "completed",
                message="Ollama check completed.",
                base_url=base_url,
                selected_model=selected_model,
            )
            return 0

        raise ValueError(f"Unsupported bot action: {args.action}")
    except Exception as exc:
        reporter.emit("error", message=str(exc))
        return 1
