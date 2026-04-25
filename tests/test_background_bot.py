from datetime import datetime, timezone
from pathlib import Path

from mailassist.background_bot import (
    body_with_review_context,
    build_batch_candidate_prompt,
    ensure_substantive_reply_body,
    has_promise_shaped_language,
    has_substantive_reply_text,
    human_review_context_time,
    load_bot_state,
    parse_batch_candidate_response,
    reply_recipients_for_thread,
    run_mock_watch_pass,
)
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


def test_body_with_review_context_adds_latest_mock_message() -> None:
    from mailassist.gui.server import build_mock_threads

    thread = next(item for item in build_mock_threads() if item.thread_id == "thread-001")

    body = body_with_review_context(thread, "I will send the kickoff notes today.")

    assert body.startswith("Review context - delete before sending:")
    assert "alex@example.com wrote" in body
    assert "2026-04-24T08:55:00Z" not in body
    assert "> Perfect. If the timeline has slipped" in body
    assert body.endswith("I will send the kickoff notes today.")


def test_body_with_review_context_includes_recent_incoming_messages() -> None:
    from mailassist.gui.server import build_mock_threads

    thread = next(item for item in build_mock_threads() if item.thread_id == "thread-009")

    body = body_with_review_context(thread, "I will check and update you.")

    assert "> Can you do me a favor in the morning" in body
    assert "> If the utility cannot answer quickly" in body
    assert body.endswith("I will check and update you.")


def test_signature_only_candidate_gets_conservative_body() -> None:
    from mailassist.gui.server import build_mock_threads

    thread = next(item for item in build_mock_threads() if item.thread_id == "thread-010")
    signature = "Best,\nElie\ne@example.com"

    body = ensure_substantive_reply_body(thread, f"Best,\n\nElie\ne@example.com", signature=signature)

    assert body.startswith("Thanks for the note. I am reviewing this.")
    assert body.endswith(signature)
    assert not has_substantive_reply_text("Best,\nElie\ne@example.com", signature=signature)


def test_promise_shaped_candidate_gets_conservative_body() -> None:
    from mailassist.gui.server import build_mock_threads

    thread = next(item for item in build_mock_threads() if item.thread_id == "thread-009")
    signature = "Best,\nElie\ne@example.com"

    body = ensure_substantive_reply_body(
        thread,
        "I will call the utility company and update you.\n\nBest,\nElie\ne@example.com",
        signature=signature,
    )

    assert body == "Thanks for the note. I am reviewing this.\n\nBest,\nElie\ne@example.com"


def test_has_promise_shaped_language_detects_common_commitments() -> None:
    assert has_promise_shaped_language("I will let you know if anything changes.")
    assert has_promise_shaped_language("I'll follow up with details.")
    assert not has_promise_shaped_language("I am reviewing the details.")


def test_human_review_context_time_uses_relative_day_words() -> None:
    now = datetime(2026, 4, 25, 13, 0, tzinfo=timezone.utc)

    assert (
        human_review_context_time("2026-04-25T09:15:00Z", now=now, use_24_hour_clock=True)
        == "this morning at 09:15"
    )
    assert (
        human_review_context_time("2026-04-24T11:31:00Z", now=now, use_24_hour_clock=True)
        == "yesterday morning at 11:31"
    )
    assert (
        human_review_context_time("2026-04-22T18:05:00Z", now=now, use_24_hour_clock=True)
        == "on Wednesday at 18:05"
    )
    assert (
        human_review_context_time("2026-03-15T21:00:00Z", now=now, use_24_hour_clock=True)
        == "on Mar 15, 2026 at 21:00"
    )


def test_human_review_context_time_can_use_12_hour_clock() -> None:
    now = datetime(2026, 4, 25, 13, 0, tzinfo=timezone.utc)

    assert (
        human_review_context_time("2026-04-24T18:15:00Z", now=now, use_24_hour_clock=False)
        == "yesterday evening at 6:15 PM"
    )


def test_parse_batch_candidate_response_unpacks_thread_blocks() -> None:
    response = """
BEGIN THREAD thread-001
CLASSIFICATION: urgent
SHOULD_DRAFT: yes
BODY:
Alex,

I will send the notes today.
-- END THREAD thread-001 --
BEGIN THREAD thread-002
CLASSIFICATION: automated
SHOULD_DRAFT: no
BODY:
-- END THREAD thread-002 --
"""

    parsed = parse_batch_candidate_response(
        response,
        expected_thread_ids=["thread-001", "thread-002"],
    )

    assert parsed["thread-001"]["classification"] == "urgent"
    assert parsed["thread-001"]["should_draft"] is True
    assert "send the notes" in parsed["thread-001"]["body"]
    assert parsed["thread-002"]["classification"] == "automated"
    assert parsed["thread-002"]["should_draft"] is False
    assert parsed["thread-002"]["body"] == ""


def test_build_batch_candidate_prompt_forbids_domain_company_names() -> None:
    from mailassist.gui.server import build_mock_threads

    threads = [item for item in build_mock_threads() if item.thread_id in {"thread-007", "thread-008"}]

    prompt = build_batch_candidate_prompt(
        threads,
        tone="Brief and casual",
        guidance="Keep it short",
        signature="Best,\nTest",
    )

    assert "Do not turn email domains into company names" in prompt
    assert "do not invent the user's decision" in prompt
    assert "Do not invent teams" in prompt
    assert "leave the final choice for the user to add" in prompt
    assert "Avoid promise-shaped phrases" in prompt
    assert "do not repeat that timing as a future promise" in prompt
    assert "Never return only a greeting, sign-off, or signature" in prompt
    assert "samira@brightforge.ai" in prompt


def test_mock_watch_pass_batches_actionable_threads(monkeypatch, tmp_path: Path) -> None:
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

        return [item for item in build_mock_threads() if item.thread_id in {"thread-001", "thread-002"}]

    def fake_generate_batch_candidates_for_tone(threads, **kwargs):
        assert [thread.thread_id for thread in threads] == ["thread-001", "thread-002"]
        return {
            "thread-001": {
                "body": "Alex,\n\nI will send the kickoff notes today.\n\nBest,\nTest",
                "classification": "urgent",
                "generation_model": "batch-model",
                "generation_error": None,
            },
            "thread-002": {
                "body": "Maria,\n\nI will update the pricing draft before Friday.\n\nBest,\nTest",
                "classification": "urgent",
                "generation_model": "batch-model",
                "generation_error": None,
            },
        }

    monkeypatch.setattr("mailassist.background_bot.build_mock_threads", fake_build_mock_threads)
    monkeypatch.setattr(
        "mailassist.background_bot.generate_batch_candidates_for_tone",
        fake_generate_batch_candidates_for_tone,
    )

    settings = load_settings()
    provider = MockProvider(settings.mock_provider_drafts_dir)

    events = run_mock_watch_pass(
        settings=settings,
        provider=provider,
        base_url="http://localhost:11434",
        selected_model="batch-model",
        batch_size=2,
    )

    assert [event["type"] for event in events] == ["draft_created", "draft_created"]
    state = load_bot_state(tmp_path)
    assert state["providers"]["mock"]["thread-001"]["generation_model"] == "batch-model"
    assert state["providers"]["mock"]["thread-002"]["generation_model"] == "batch-model"
    assert (tmp_path / "data" / "mock-provider-drafts" / "thread-001.json").exists()
    assert (tmp_path / "data" / "mock-provider-drafts" / "thread-002.json").exists()
