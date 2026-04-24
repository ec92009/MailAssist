import argparse
import json
from pathlib import Path

from mailassist.bot_runtime import command_review_bot
from mailassist.config import write_env_file


def test_review_bot_ollama_check_requires_prompt(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_OLLAMA_URL": "http://localhost:11434",
            "MAILASSIST_OLLAMA_MODEL": "llama3.2:latest",
        },
    )
    args = argparse.Namespace(
        command="review-bot",
        action="ollama-check",
        thread_id=None,
        prompt="",
        base_url=None,
        selected_model=None,
    )

    exit_code = command_review_bot(args)

    assert exit_code == 1
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert lines[0]["type"] == "started"
    assert lines[0]["command"] == "review-bot"
    assert lines[0]["arguments"]["action"] == "ollama-check"
    assert lines[0]["arguments"]["base_url"] == "http://localhost:11434"
    assert lines[0]["arguments"]["selected_model"] == "llama3.2:latest"
    assert lines[1]["type"] == "log_file"
    assert Path(lines[1]["path"]).parent == tmp_path / "data" / "bot-logs"
    assert lines[-1]["type"] == "error"
    assert "--prompt is required for ollama-check" in lines[-1]["message"]


def test_review_bot_sync_review_state_uses_cli_model_arguments(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_OLLAMA_URL": "http://env-only:11434",
            "MAILASSIST_OLLAMA_MODEL": "env-model:latest",
        },
    )

    calls: list[tuple[str, str, str]] = []

    def fake_regenerate_thread_candidates(
        state: dict,
        thread_id: str,
        *,
        base_url: str,
        selected_model: str,
    ) -> dict:
        calls.append((thread_id, base_url, selected_model))
        thread_state = next(item for item in state["threads"] if item["thread_id"] == thread_id)
        thread_state["candidates"] = [{"candidate_id": "option-a", "body": "Ready"}]
        return thread_state

    monkeypatch.setattr(
        "mailassist.bot_runtime.regenerate_thread_candidates",
        fake_regenerate_thread_candidates,
    )

    args = argparse.Namespace(
        command="review-bot",
        action="sync-review-state",
        thread_id=None,
        prompt=None,
        base_url="http://cli-example:11434",
        selected_model="cli-model:latest",
    )

    exit_code = command_review_bot(args)

    assert exit_code == 0
    assert calls
    assert all(base_url == "http://cli-example:11434" for _, base_url, _ in calls)
    assert all(selected_model == "cli-model:latest" for _, _, selected_model in calls)

    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert lines[0]["type"] == "started"
    assert lines[0]["command"] == "review-bot"
    assert lines[0]["arguments"]["base_url"] == "http://cli-example:11434"
    assert lines[0]["arguments"]["selected_model"] == "cli-model:latest"
    assert lines[-1]["type"] == "completed"
    assert lines[-1]["generated_threads"] == len(calls)
