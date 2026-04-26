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

def test_review_bot_gmail_inbox_preview_emits_message_metadata(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_GMAIL_ENABLED": "true",
        },
    )

    class FakeProvider:
        def list_recent_inbox_messages(self, limit: int = 10):
            assert limit == 2
            return [
                {
                    "id": "msg-1",
                    "thread_id": "thread-1",
                    "from": "sender@example.com",
                    "to": "you@example.com",
                    "date": "Sat, 25 Apr 2026 08:00:00 +0200",
                    "subject": "Hello",
                    "snippet": "Short preview",
                }
            ]

    monkeypatch.setattr(
        "mailassist.bot_runtime.get_provider_for_settings",
        lambda settings, provider_name: FakeProvider(),
    )

    args = argparse.Namespace(
        command="review-bot",
        action="gmail-inbox-preview",
        thread_id=None,
        prompt=None,
        base_url=None,
        selected_model=None,
        provider="gmail",
        batch_size=1,
        limit=2,
        force=False,
    )

    exit_code = command_review_bot(args)

    assert exit_code == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert any(line["type"] == "gmail_message_preview" for line in lines)
    assert lines[-1]["type"] == "completed"
    assert lines[-1]["message_count"] == 1


def test_review_bot_watch_loop_uses_polling_settings_and_counts_events(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_BOT_POLL_SECONDS": "15",
        },
    )

    class FakeProvider:
        name = "mock"

    call_count = {"value": 0}
    slept = []

    def fake_get_provider(settings, provider_name):
        assert provider_name == "mock"
        return FakeProvider()

    def fake_run_mock_watch_pass(**kwargs):
        call_count["value"] += 1
        if call_count["value"] == 1:
            return [
                {
                    "type": "draft_created",
                    "thread_id": "thread-1",
                    "subject": "First",
                    "classification": "urgent",
                    "provider_draft_id": "draft-1",
                }
            ]
        return [
            {
                "type": "already_handled",
                "thread_id": "thread-1",
                "subject": "First",
                "classification": "urgent",
                "provider_draft_id": "draft-1",
            }
        ]

    monkeypatch.setattr("mailassist.bot_runtime.get_provider_for_settings", fake_get_provider)
    monkeypatch.setattr("mailassist.bot_runtime.run_mock_watch_pass", fake_run_mock_watch_pass)
    monkeypatch.setattr("mailassist.bot_runtime.time.sleep", lambda seconds: slept.append(seconds))

    args = argparse.Namespace(
        command="review-bot",
        action="watch-loop",
        thread_id=None,
        prompt=None,
        base_url=None,
        selected_model=None,
        provider="mock",
        batch_size=1,
        limit=10,
        force=False,
        poll_seconds=0,
        max_passes=2,
    )

    exit_code = command_review_bot(args)

    assert exit_code == 0
    assert slept == [15]
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert lines[0]["type"] == "started"
    assert any(line["type"] == "watch_pass_started" and line["pass_number"] == 1 for line in lines)
    assert any(line["type"] == "sleeping" and line["poll_seconds"] == 15 for line in lines)
    assert lines[-1]["type"] == "completed"
    assert lines[-1]["completed_passes"] == 2
    assert lines[-1]["draft_count"] == 1
    assert lines[-1]["already_handled_count"] == 1


def test_review_bot_watch_loop_emits_failed_and_retry_events(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_BOT_POLL_SECONDS": "9",
        },
    )

    class FakeProvider:
        name = "mock"

    call_count = {"value": 0}
    slept = []

    monkeypatch.setattr(
        "mailassist.bot_runtime.get_provider_for_settings",
        lambda settings, provider_name: FakeProvider(),
    )

    def fake_run_mock_watch_pass(**kwargs):
        call_count["value"] += 1
        if call_count["value"] == 1:
            raise RuntimeError("temporary provider failure")
        return []

    monkeypatch.setattr("mailassist.bot_runtime.run_mock_watch_pass", fake_run_mock_watch_pass)
    monkeypatch.setattr("mailassist.bot_runtime.time.sleep", lambda seconds: slept.append(seconds))

    args = argparse.Namespace(
        command="review-bot",
        action="watch-loop",
        thread_id=None,
        prompt=None,
        base_url=None,
        selected_model=None,
        provider="mock",
        batch_size=1,
        limit=10,
        force=False,
        poll_seconds=0,
        max_passes=2,
    )

    exit_code = command_review_bot(args)

    assert exit_code == 0
    assert slept == [9]
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert any(line["type"] == "failed_pass" and "temporary provider failure" in line["message"] for line in lines)
    assert any(line["type"] == "retry_scheduled" and line["poll_seconds"] == 9 for line in lines)
    assert lines[-1]["failed_pass_count"] == 1
    assert lines[-1]["retry_count"] == 1
