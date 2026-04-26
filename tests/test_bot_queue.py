import argparse
import json
from pathlib import Path

from mailassist.bot_queue import (
    QUEUE_PHASES,
    build_bot_processed_item,
    ensure_queue_dirs,
    existing_phase_for_thread,
    list_phase_items,
    queue_filename,
    write_queue_item,
)
from mailassist.bot_runtime import command_review_bot
from mailassist.config import write_env_file
from mailassist.fixtures.mock_threads import build_mock_threads


def test_queue_filename_sanitizes_provider_and_thread_id() -> None:
    assert queue_filename("mock provider", "thread/001") == "mock-provider__thread-001.json"


def test_ensure_queue_dirs_creates_lifecycle_folders(tmp_path: Path) -> None:
    paths = ensure_queue_dirs(tmp_path)

    assert tuple(paths) == QUEUE_PHASES
    assert all(path.exists() for path in paths.values())


def test_write_queue_item_uses_bot_processed_contract(monkeypatch, tmp_path: Path) -> None:
    def fake_generate_candidates_for_thread(*args, **kwargs):
        return (
            [{"candidate_id": "option-a", "body": "Draft"}],
            "mock-model",
            None,
            "reply_needed",
        )

    monkeypatch.setattr(
        "mailassist.bot_queue.generate_candidates_for_thread",
        fake_generate_candidates_for_thread,
    )
    item = build_bot_processed_item(
        thread=build_mock_threads()[0],
        provider="mock",
        source="mock",
        base_url="http://localhost:11434",
        selected_model="mock-model",
    )
    path = write_queue_item(tmp_path, "bot_processed", item)

    assert path == tmp_path / "data" / "bot_processed" / "mock__thread-001.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["workflow_state"] == "bot_processed"
    assert payload["review"]["outcome"] == "pending"
    assert payload["provider_draft"] is None
    assert payload["classification"] == "reply_needed"
    assert existing_phase_for_thread(tmp_path, "mock", "thread-001") == "bot_processed"
    assert list_phase_items(tmp_path, "bot_processed")[0]["thread_id"] == "thread-001"


def test_review_bot_process_mock_inbox_writes_queue_files(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_OLLAMA_URL": "http://env-only:11434",
            "MAILASSIST_OLLAMA_MODEL": "env-model:latest",
        },
    )

    def fake_build_mock_threads():
        return build_mock_threads()[:2]

    def fake_build_bot_processed_item(*, thread, provider, source, base_url, selected_model):
        return {
            "schema_version": 1,
            "workflow_state": "bot_processed",
            "source": source,
            "provider": provider,
            "thread_id": thread.thread_id,
            "provider_thread_id": thread.thread_id,
            "subject": thread.subject,
            "thread": {"thread_id": thread.thread_id},
            "classification": "reply_needed",
            "classification_source": selected_model,
            "candidate_generation_model": selected_model,
            "candidate_generation_error": None,
            "candidates": [{"candidate_id": "option-a", "body": "Draft"}],
            "review": {
                "outcome": "pending",
                "selected_candidate_id": None,
                "edited_body": None,
                "reviewed_at": None,
            },
            "provider_draft": None,
            "archive": {"selected": False, "archived": False},
            "timestamps": {},
        }

    monkeypatch.setattr("mailassist.bot_runtime.build_mock_threads", fake_build_mock_threads)
    monkeypatch.setattr(
        "mailassist.bot_runtime.build_bot_processed_item",
        fake_build_bot_processed_item,
    )

    args = argparse.Namespace(
        command="review-bot",
        action="process-mock-inbox",
        thread_id=None,
        prompt=None,
        base_url="http://cli-example:11434",
        selected_model="cli-model:latest",
        force=False,
    )

    exit_code = command_review_bot(args)

    assert exit_code == 0
    assert (tmp_path / "data" / "bot_processed" / "mock__thread-001.json").exists()
    assert (tmp_path / "data" / "bot_processed" / "mock__thread-002.json").exists()

    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert lines[0]["type"] == "started"
    assert lines[0]["arguments"]["action"] == "process-mock-inbox"
    assert any(line["type"] == "queue_ready" for line in lines)
    processed = [line for line in lines if line["type"] == "processed_email"]
    assert [line["thread_id"] for line in processed] == ["thread-001", "thread-002"]
    assert lines[-1]["type"] == "completed"
    assert lines[-1]["processed_count"] == 2
    assert lines[-1]["skipped_count"] == 0


def test_review_bot_process_mock_inbox_can_target_one_thread(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.chdir(tmp_path)

    def fake_build_bot_processed_item(*, thread, provider, source, base_url, selected_model):
        return {
            "schema_version": 1,
            "workflow_state": "bot_processed",
            "source": source,
            "provider": provider,
            "thread_id": thread.thread_id,
            "provider_thread_id": thread.thread_id,
            "subject": thread.subject,
            "thread": {"thread_id": thread.thread_id},
            "classification": "reply_needed",
            "classification_source": selected_model,
            "candidate_generation_model": selected_model,
            "candidate_generation_error": None,
            "candidates": [],
            "review": {
                "outcome": "pending",
                "selected_candidate_id": None,
                "edited_body": None,
                "reviewed_at": None,
            },
            "provider_draft": None,
            "archive": {"selected": False, "archived": False},
            "timestamps": {},
        }

    monkeypatch.setattr(
        "mailassist.bot_runtime.build_bot_processed_item",
        fake_build_bot_processed_item,
    )
    args = argparse.Namespace(
        command="review-bot",
        action="process-mock-inbox",
        thread_id="thread-002",
        prompt=None,
        base_url="http://cli-example:11434",
        selected_model="cli-model:latest",
        force=False,
    )

    exit_code = command_review_bot(args)

    assert exit_code == 0
    assert not (tmp_path / "data" / "bot_processed" / "mock__thread-001.json").exists()
    assert (tmp_path / "data" / "bot_processed" / "mock__thread-002.json").exists()
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert lines[-1]["processed_count"] == 1
