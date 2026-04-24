from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

from mailassist.background_bot import run_mock_watch_pass
from mailassist.bot_queue import (
    build_bot_processed_item,
    ensure_queue_dirs,
    existing_phase_for_thread,
    list_phase_items,
    write_queue_item,
)
from mailassist.config import load_settings
from mailassist.gui.server import (
    build_mock_threads,
    load_review_state,
    regenerate_thread_candidates,
    save_review_state,
)
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
        help="Run a bot-side review action and emit JSONL events on stdout.",
    )
    parser.add_argument(
        "--action",
        required=True,
        choices=(
            "sync-review-state",
            "regenerate-thread",
            "ollama-check",
            "process-mock-inbox",
            "queue-status",
            "watch-once",
        ),
        help="Bot action to run.",
    )
    parser.add_argument("--thread-id", help="Thread ID for review-state actions.")
    parser.add_argument("--prompt", help="Prompt for Ollama check actions.")
    parser.add_argument("--base-url", help="Ollama base URL for bot actions.")
    parser.add_argument("--selected-model", help="Ollama model for bot actions.")
    parser.add_argument("--provider", default="mock", help="Provider to watch for watch-once.")
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
        },
    )
    reporter.emit("log_file", path=str(reporter.log_path))

    try:
        if args.action == "sync-review-state":
            state = load_review_state(settings.root_dir)
            pending = [item for item in state.get("threads", []) if not item.get("candidates")]
            reporter.emit(
                "info",
                message=f"Preparing draft options for {len(pending)} thread(s).",
            )
            for thread_state in pending:
                reporter.emit(
                    "info",
                    message=f"Generating draft options for {thread_state['thread_id']}.",
                    thread_id=thread_state["thread_id"],
                    subject=thread_state["subject"],
                )
                regenerate_thread_candidates(
                    state,
                    thread_state["thread_id"],
                    base_url=base_url,
                    selected_model=selected_model,
                )
            if pending:
                save_review_state(settings.root_dir, state)
            reporter.emit(
                "completed",
                message="Review state is ready.",
                generated_threads=len(pending),
                thread_count=len(state.get("threads", [])),
            )
            return 0

        if args.action == "regenerate-thread":
            if not args.thread_id:
                raise ValueError("--thread-id is required for regenerate-thread")
            reporter.emit("info", message=f"Regenerating draft options for {args.thread_id}.")
            state = load_review_state(settings.root_dir)
            regenerate_thread_candidates(
                state,
                args.thread_id,
                base_url=base_url,
                selected_model=selected_model,
            )
            save_review_state(settings.root_dir, state)
            reporter.emit(
                "completed",
                message="Draft options refreshed.",
                thread_id=args.thread_id,
                base_url=base_url,
                selected_model=selected_model,
            )
            return 0

        if args.action == "process-mock-inbox":
            queue_dirs = ensure_queue_dirs(settings.root_dir)
            reporter.emit(
                "queue_ready",
                phases={phase: str(path) for phase, path in queue_dirs.items()},
            )
            processed_count = 0
            skipped_count = 0
            for thread in build_mock_threads():
                if args.thread_id and thread.thread_id != args.thread_id:
                    continue
                existing_phase = existing_phase_for_thread(settings.root_dir, "mock", thread.thread_id)
                if existing_phase and not getattr(args, "force", False):
                    skipped_count += 1
                    reporter.emit(
                        "skipped_email",
                        message=f"{thread.thread_id} already exists in {existing_phase}.",
                        thread_id=thread.thread_id,
                        subject=thread.subject,
                        phase=existing_phase,
                    )
                    continue

                reporter.emit(
                    "info",
                    message=f"Processing mock email {thread.thread_id}.",
                    thread_id=thread.thread_id,
                    subject=thread.subject,
                )
                item = build_bot_processed_item(
                    thread=thread,
                    provider="mock",
                    source="mock",
                    base_url=base_url,
                    selected_model=selected_model,
                )
                path = write_queue_item(settings.root_dir, "bot_processed", item)
                processed_count += 1
                reporter.emit(
                    "processed_email",
                    message="Mock email processed for GUI acquisition.",
                    thread_id=thread.thread_id,
                    subject=thread.subject,
                    classification=item["classification"],
                    candidate_count=len(item.get("candidates", [])),
                    path=str(path),
                )
            reporter.emit(
                "completed",
                message="Mock inbox acquisition pass completed.",
                processed_count=processed_count,
                skipped_count=skipped_count,
            )
            return 0

        if args.action == "queue-status":
            ensure_queue_dirs(settings.root_dir)
            counts = {
                phase: len(list_phase_items(settings.root_dir, phase))
                for phase in (
                    "bot_processed",
                    "gui_acquired",
                    "user_reviewed",
                    "provider_drafted",
                    "user_replied",
                )
            }
            reporter.emit("queue_status", counts=counts)
            reporter.emit("completed", message="Queue status ready.", counts=counts)
            return 0

        if args.action == "watch-once":
            provider_name = getattr(args, "provider", "mock") or "mock"
            provider = get_provider_for_settings(settings, provider_name)
            reporter.emit(
                "info",
                message=f"Running one mock-input watch pass for {provider_name} drafts.",
                provider=provider_name,
            )
            events = run_mock_watch_pass(
                settings=settings,
                provider=provider,
                base_url=base_url,
                selected_model=selected_model,
                thread_id=args.thread_id or "",
                force=bool(getattr(args, "force", False)),
            )
            draft_count = 0
            skipped_count = 0
            already_handled_count = 0
            for event in events:
                event_type = str(event.pop("type"))
                if event_type == "draft_created":
                    draft_count += 1
                elif event_type == "skipped_email":
                    skipped_count += 1
                elif event_type == "already_handled":
                    already_handled_count += 1
                reporter.emit(event_type, **event)
            reporter.emit(
                "completed",
                message="Watch pass completed.",
                provider=provider_name,
                draft_count=draft_count,
                skipped_count=skipped_count,
                already_handled_count=already_handled_count,
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
