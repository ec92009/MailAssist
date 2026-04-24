from pathlib import Path

from mailassist.background_bot import load_bot_state, reply_recipients_for_thread, run_mock_watch_pass
from mailassist.config import load_settings, write_env_file
from mailassist.providers.mock import MockProvider


def test_mock_watch_pass_creates_one_provider_draft_and_skips_second_run(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_USER_TONE": "brief_casual",
            "MAILASSIST_USER_SIGNATURE": "Best,\\nTest",
        },
    )

    def fake_build_mock_threads():
        from mailassist.gui.server import build_mock_threads

        return [item for item in build_mock_threads() if item.thread_id == "thread-008"]

    def fake_generate_candidate_for_tone(*args, **kwargs):
        return (
            {
                "candidate_id": "option-a",
                "body": "Approved. Please limit access to the shared project folder only.\n\nBest,\nTest",
                "generated_by": "mock-model",
            },
            "mock-model",
            None,
            "urgent",
        )

    monkeypatch.setattr("mailassist.background_bot.build_mock_threads", fake_build_mock_threads)
    monkeypatch.setattr(
        "mailassist.background_bot.generate_candidate_for_tone",
        fake_generate_candidate_for_tone,
    )

    settings = load_settings()
    provider = MockProvider(settings.mock_provider_drafts_dir)

    first_events = run_mock_watch_pass(
        settings=settings,
        provider=provider,
        base_url="http://localhost:11434",
        selected_model="mock-model",
    )
    second_events = run_mock_watch_pass(
        settings=settings,
        provider=provider,
        base_url="http://localhost:11434",
        selected_model="mock-model",
    )

    assert first_events[0]["type"] == "draft_created"
    assert first_events[0]["provider_draft_id"] == "mock-draft-thread-008"
    assert second_events[0]["type"] == "already_handled"
    assert (tmp_path / "data" / "mock-provider-drafts" / "thread-008.json").exists()
    state = load_bot_state(tmp_path)
    assert state["providers"]["mock"]["thread-008"]["action"] == "draft_created"


def test_reply_recipients_for_thread_targets_latest_sender() -> None:
    from mailassist.gui.server import build_mock_threads

    thread = next(item for item in build_mock_threads() if item.thread_id == "thread-008")

    assert reply_recipients_for_thread(thread) == ["ops@harborhq.com"]
