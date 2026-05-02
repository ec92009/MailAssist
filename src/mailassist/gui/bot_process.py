from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QProcessEnvironment


@dataclass(frozen=True)
class BotActionRequest:
    action: str
    base_url: str
    selected_model: str
    thread_id: str = ""
    prompt: str = ""
    provider: str = ""
    force: bool = False
    dry_run: bool = False
    apply_labels: bool = False
    apply_categories: bool = False
    days: int | None = None
    limit: int | None = None


def build_bot_action_args(request: BotActionRequest) -> list[str]:
    args = [
        "-u",
        "-m",
        "mailassist.cli.main",
        "review-bot",
        "--action",
        request.action,
        "--base-url",
        request.base_url,
        "--selected-model",
        request.selected_model,
    ]
    if request.thread_id:
        args.extend(["--thread-id", request.thread_id])
    if request.prompt:
        args.extend(["--prompt", request.prompt])
    if request.provider:
        args.extend(["--provider", request.provider])
    if request.force:
        args.append("--force")
    if request.dry_run:
        args.append("--dry-run")
    if request.days is not None:
        args.extend(["--days", str(max(1, int(request.days)))])
    if request.limit is not None:
        args.extend(["--limit", str(max(1, int(request.limit)))])
    if request.apply_labels:
        args.append("--apply-labels")
    if request.apply_categories:
        args.append("--apply-categories")
    return args


def build_bot_process_environment(request: BotActionRequest) -> QProcessEnvironment:
    process_env = QProcessEnvironment.systemEnvironment()
    if request.action == "watch-once" and request.dry_run:
        process_env.insert("MAILASSIST_OLLAMA_GENERATE_TIMEOUT_SECONDS", "110")
    return process_env
