from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

from mailassist.config import load_settings
from mailassist.gui.server import load_review_state, regenerate_thread_candidates, save_review_state
from mailassist.llm.ollama import OllamaClient
from mailassist.models import utc_now_iso


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
        choices=("sync-review-state", "regenerate-thread", "ollama-check"),
        help="Bot action to run.",
    )
    parser.add_argument("--thread-id", help="Thread ID for review-state actions.")
    parser.add_argument("--prompt", help="Prompt for Ollama check actions.")
    parser.add_argument("--base-url", help="Ollama base URL for bot actions.")
    parser.add_argument("--selected-model", help="Ollama model for bot actions.")


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
