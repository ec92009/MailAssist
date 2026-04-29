import json
from datetime import datetime, timezone
from pathlib import Path

from mailassist.background_bot import (
    append_draft_attribution,
    append_signature,
    build_draft_body_html,
    body_with_review_context,
    build_batch_candidate_prompt,
    build_prompt_preview,
    ensure_substantive_reply_body,
    has_promise_shaped_language,
    has_substantive_reply_text,
    human_review_context_time,
    load_bot_state,
    parse_batch_candidate_response,
    reply_recipients_for_thread,
    run_watch_pass,
)
from mailassist.config import load_settings, write_env_file
from mailassist.fixtures.mock_threads import build_mock_threads
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

    first_events = run_watch_pass(
        settings=settings,
        provider=provider,
        base_url="http://localhost:11434",
        selected_model="mock-model",
    )
    second_events = run_watch_pass(
        settings=settings,
        provider=provider,
        base_url="http://localhost:11434",
        selected_model="mock-model",
    )

    assert first_events[0]["type"] == "draft_created"
    assert first_events[0]["provider_draft_id"] == "mock-draft-thread-008"
    assert second_events[0]["type"] == "already_handled"
    assert (tmp_path / "data" / "mock-provider-drafts" / "thread-008.json").exists()
    assert (tmp_path / "data" / "live-state.json").exists()
    state = load_bot_state(tmp_path)
    assert state["account_email"] is None
    assert state["providers"]["mock"]["threads"]["thread-008"]["action"] == "draft_created"
    assert state["recent_activity"][-1]["type"] == "already_handled"


def test_watch_pass_dry_run_never_creates_provider_draft(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_USER_SIGNATURE": "Best,\\nTest",
        },
    )

    def fake_build_mock_threads():
        return [item for item in build_mock_threads() if item.thread_id == "thread-008"]

    def fake_generate_candidate_for_tone(*args, **kwargs):
        return (
            {
                "candidate_id": "option-a",
                "body": "I am reviewing this.\n\nBest,\nTest",
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

    events = run_watch_pass(
        settings=settings,
        provider=provider,
        base_url="http://localhost:11434",
        selected_model="mock-model",
        dry_run=True,
    )

    assert events[0]["type"] == "draft_ready"
    assert events[0]["dry_run"] is True
    assert not (tmp_path / "data" / "mock-provider-drafts" / "thread-008.json").exists()
    state = load_bot_state(tmp_path)
    assert "thread-008" not in state["providers"]["mock"]["threads"]
    assert state["recent_activity"][-1]["type"] == "draft_ready"


def test_load_bot_state_migrates_legacy_bot_state_file(tmp_path: Path) -> None:
    legacy_path = tmp_path / "data" / "bot-state.json"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text(
        '{\n'
        '  "schema_version": 1,\n'
        '  "providers": {\n'
        '    "mock": {\n'
        '      "thread-001": {\n'
        '        "action": "draft_created"\n'
        "      }\n"
        "    }\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )

    state = load_bot_state(tmp_path)

    assert state["account_email"] is None
    assert state["providers"]["mock"]["threads"]["thread-001"]["action"] == "draft_created"
    assert state["providers"]["mock"]["cursor"] is None
    assert not legacy_path.exists()
    assert (tmp_path / "data" / "live-state.json").exists()


def test_reply_recipients_for_thread_targets_latest_sender() -> None:
    thread = next(item for item in build_mock_threads() if item.thread_id == "thread-008")

    assert reply_recipients_for_thread(thread) == ["ops@harborhq.com"]


def test_reply_recipients_for_thread_uses_discovered_account_email() -> None:
    thread = next(item for item in build_mock_threads() if item.thread_id == "thread-008")

    assert reply_recipients_for_thread(thread, user_address="magali@example.com") == [
        "ops@harborhq.com"
    ]


def test_body_with_review_context_adds_latest_mock_message() -> None:
    thread = next(item for item in build_mock_threads() if item.thread_id == "thread-001")

    body = body_with_review_context(thread, "I will send the kickoff notes today.")

    assert body.startswith("Review context - delete before sending:")
    assert "alex@example.com wrote" in body
    assert "2026-04-24T08:55:00Z" not in body
    assert "> Perfect. If the timeline has slipped" in body
    assert body.endswith("I will send the kickoff notes today.")


def test_body_with_review_context_includes_recent_incoming_messages() -> None:
    thread = next(item for item in build_mock_threads() if item.thread_id == "thread-009")

    body = body_with_review_context(thread, "I will check and update you.")

    assert "> Can you do me a favor in the morning" in body
    assert "> If the utility cannot answer quickly" in body
    assert body.endswith("I will check and update you.")


def test_body_with_review_context_excludes_user_messages_for_discovered_account_email() -> None:
    thread = next(item for item in build_mock_threads() if item.thread_id == "thread-001")

    body = body_with_review_context(
        thread,
        "I am reviewing this.",
        user_address="alex@example.com",
    )

    assert "you@example.com wrote" in body
    assert "alex@example.com wrote" not in body


def test_signature_only_candidate_gets_conservative_body() -> None:
    thread = next(item for item in build_mock_threads() if item.thread_id == "thread-010")
    signature = "Best,\nElie\ne@example.com"

    body = ensure_substantive_reply_body(thread, f"Best,\n\nElie\ne@example.com", signature=signature)

    assert body.startswith("Thanks for the note. I am reviewing this.")
    assert body.endswith(signature)
    assert not has_substantive_reply_text("Best,\nElie\ne@example.com", signature=signature)


def test_promise_shaped_candidate_gets_conservative_body() -> None:
    thread = next(item for item in build_mock_threads() if item.thread_id == "thread-009")
    signature = "Best,\nElie\ne@example.com"

    body = ensure_substantive_reply_body(
        thread,
        "I will call the utility company and update you.\n\nBest,\nElie\ne@example.com",
        signature=signature,
    )

    assert body == "Thanks for the note. I am reviewing this.\n\nBest,\nElie\ne@example.com"


def test_substantive_candidate_gets_configured_signature_appended() -> None:
    thread = next(item for item in build_mock_threads() if item.thread_id == "thread-010")
    signature = "Best,\nElie\ne@example.com"

    body = ensure_substantive_reply_body(
        thread,
        "I am reviewing the open house options.",
        signature=signature,
    )

    assert body == "I am reviewing the open house options.\n\nBest,\nElie\ne@example.com"


def test_build_draft_body_html_uses_rich_signature_and_attribution() -> None:
    thread = next(item for item in build_mock_threads() if item.thread_id == "thread-010")

    body_html = build_draft_body_html(
        thread,
        "I am reviewing the open house options.\n\nBest,\nElie",
        signature="Best,\nElie",
        signature_html="<b>Best,</b><br><i>Elie</i>",
        model="gemma4:31b",
        include_attribution=True,
    )

    assert body_html is not None
    assert "<b>Best,</b><br><i>Elie</i>" in body_html
    assert body_html.count("<b>Best,</b>") == 1
    assert "I am reviewing the open house options.<br><br>Best" not in body_html
    assert "Draft prepared by MailAssist using Ollama model gemma4:31b." in body_html
    assert "Review context - delete before sending:" in body_html


def test_draft_attribution_can_be_placed_above_signature() -> None:
    body = append_draft_attribution(
        "I am reviewing the open house options.\n\nBest,\nElie",
        model="gemma4:31b",
        placement="above_signature",
        signature="Best,\nElie",
    )

    assert body == (
        "I am reviewing the open house options.\n\n"
        "Draft prepared by MailAssist using Ollama model gemma4:31b.\n\n"
        "Best,\nElie"
    )


def test_build_draft_body_html_places_attribution_above_signature() -> None:
    thread = next(item for item in build_mock_threads() if item.thread_id == "thread-010")

    body_html = build_draft_body_html(
        thread,
        "I am reviewing the open house options.\n\n"
        "Draft prepared by MailAssist using Ollama model gemma4:31b.\n\n"
        "Best,\nElie",
        signature="Best,\nElie",
        signature_html="<b>Best,</b><br><i>Elie</i>",
        model="gemma4:31b",
        attribution_placement="above_signature",
    )

    assert body_html is not None
    assert body_html.index("Draft prepared by MailAssist") < body_html.index("<b>Best,</b>")


def test_build_draft_body_html_falls_back_when_rich_signature_has_no_text() -> None:
    thread = next(item for item in build_mock_threads() if item.thread_id == "thread-010")

    body_html = build_draft_body_html(
        thread,
        "I am reviewing the open house options.",
        signature="Best,\nElie",
        signature_html='<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.0//EN">',
        model="gemma4:31b",
        attribution_placement="below_signature",
    )

    assert body_html is not None
    assert "Best,<br>Elie" in body_html
    assert body_html.index("Best,<br>Elie") < body_html.index("Draft prepared by MailAssist")


def test_append_signature_replaces_model_supplied_copy() -> None:
    signature = "Best,\nElie"

    body = append_signature("I am reviewing this.\n\nBest,\nElie", signature=signature)

    assert body == "I am reviewing this.\n\nBest,\nElie"


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
BODY:
Alex,

I will send the notes today.
-- END THREAD thread-001 --
BEGIN THREAD thread-002
CLASSIFICATION: automated
BODY:
-- END THREAD thread-002 --
"""

    parsed = parse_batch_candidate_response(
        response,
        expected_thread_ids=["thread-001", "thread-002"],
    )

    assert parsed["thread-001"]["classification"] == "urgent"
    assert "send the notes" in parsed["thread-001"]["body"]
    assert parsed["thread-002"]["classification"] == "automated"
    assert parsed["thread-002"]["body"] == ""


def test_build_batch_candidate_prompt_forbids_domain_company_names() -> None:
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
    assert "MailAssist will append the user's saved signature" in prompt
    assert "Best,\nTest" not in prompt
    assert "samira@brightforge.ai" in prompt


def test_build_prompt_preview_uses_current_tone_and_signature() -> None:
    prompt = build_prompt_preview(
        tone_key="formal_polished",
        signature="Regards,\nElie",
        sample_thread_id="thread-010",
    )

    assert "You are MailAssist, a local-first email drafting assistant." in prompt
    assert "INPUT THREAD thread-010" in prompt
    assert "Open house this weekend?" in prompt
    assert "Tone target: Formal and polished." in prompt
    assert "MailAssist will append the user's saved signature" in prompt
    assert "Regards,\nElie" not in prompt


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

    events = run_watch_pass(
        settings=settings,
        provider=provider,
        base_url="http://localhost:11434",
        selected_model="batch-model",
        batch_size=2,
    )

    assert [event["type"] for event in events] == ["draft_created", "draft_created"]
    state = load_bot_state(tmp_path)
    assert state["providers"]["mock"]["threads"]["thread-001"]["generation_model"] == "batch-model"
    assert state["providers"]["mock"]["threads"]["thread-002"]["generation_model"] == "batch-model"
    assert (tmp_path / "data" / "mock-provider-drafts" / "thread-001.json").exists()
    assert (tmp_path / "data" / "mock-provider-drafts" / "thread-002.json").exists()


def test_mock_watch_pass_persists_provider_account_email_and_uses_it(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_USER_TONE": "brief_casual",
            "MAILASSIST_USER_SIGNATURE": "Best,\\nTest",
        },
    )

    def fake_build_mock_threads():
        return [item for item in build_mock_threads() if item.thread_id == "thread-008"]

    def fake_generate_candidate_for_tone(*args, **kwargs):
        return (
            {
                "candidate_id": "option-a",
                "body": "I am reviewing this.\n\nBest,\nTest",
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
    provider = MockProvider(
        settings.mock_provider_drafts_dir,
        account_email="magali@example.com",
    )

    events = run_watch_pass(
        settings=settings,
        provider=provider,
        base_url="http://localhost:11434",
        selected_model="mock-model",
    )

    assert events[0]["type"] == "draft_created"
    state = load_bot_state(tmp_path)
    assert state["account_email"] == "magali@example.com"
    assert state["provider_accounts"]["mock"] == "magali@example.com"
    assert state["recent_activity"][-1]["type"] == "draft_created"
    draft_payload = json.loads(
        (tmp_path / "data" / "mock-provider-drafts" / "thread-008.json").read_text(encoding="utf-8")
    )
    assert draft_payload["to"] == ["ops@harborhq.com"]
    assert "ops@harborhq.com wrote" in draft_payload["body"]
    assert "magali@example.com wrote" not in draft_payload["body"]


def test_mock_watch_pass_skips_threads_when_latest_message_is_from_user(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)

    def fake_build_mock_threads():
        return [
            next(item for item in build_mock_threads() if item.thread_id == "thread-001"),
        ]

    monkeypatch.setattr("mailassist.background_bot.build_mock_threads", fake_build_mock_threads)

    settings = load_settings()
    provider = MockProvider(
        settings.mock_provider_drafts_dir,
        account_email="alex@example.com",
    )

    events = run_watch_pass(
        settings=settings,
        provider=provider,
        base_url="http://localhost:11434",
        selected_model="mock-model",
    )

    assert events == [
        {
            "type": "user_replied",
            "thread_id": "thread-001",
            "subject": "Project kickoff follow-up",
            "classification": "reply_needed",
            "reason": "latest_message_from_user",
        }
    ]
    state = load_bot_state(tmp_path)
    assert state["providers"]["mock"]["threads"]["thread-001"]["action"] == "user_replied"
    assert state["recent_activity"][-1]["type"] == "user_replied"
    assert not (tmp_path / "data" / "mock-provider-drafts" / "thread-001.json").exists()


def test_watch_pass_uses_provider_thread_listing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_USER_TONE": "brief_casual",
            "MAILASSIST_USER_SIGNATURE": "Best,\\nTest",
        },
    )

    thread = next(item for item in build_mock_threads() if item.thread_id == "thread-008")

    def fake_generate_candidate_for_tone(*args, **kwargs):
        return (
            {
                "candidate_id": "option-a",
                "body": "I am reviewing this.\n\nBest,\nTest",
                "generated_by": "mock-model",
            },
            "mock-model",
            None,
            "urgent",
        )

    class ProviderWithThreads(MockProvider):
        name = "gmail"

        def list_candidate_threads(self):
            return [thread]

    monkeypatch.setattr(
        "mailassist.background_bot.build_mock_threads",
        lambda: (_ for _ in ()).throw(AssertionError("fixture fallback should not be used")),
    )
    monkeypatch.setattr(
        "mailassist.background_bot.generate_candidate_for_tone",
        fake_generate_candidate_for_tone,
    )

    settings = load_settings()
    provider = ProviderWithThreads(settings.mock_provider_drafts_dir, account_email="magali@example.com")

    events = run_watch_pass(
        settings=settings,
        provider=provider,
        base_url="http://localhost:11434",
        selected_model="mock-model",
    )

    assert events[0]["type"] == "draft_created"
    state = load_bot_state(tmp_path)
    assert state["providers"]["gmail"]["threads"]["thread-008"]["action"] == "draft_created"


def test_watch_pass_records_filtered_out_threads(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_WATCHER_UNREAD_ONLY": "true",
        },
    )

    thread = next(item for item in build_mock_threads() if item.thread_id == "thread-008")
    thread.unread = False

    class ProviderWithReadThread(MockProvider):
        name = "gmail"

        def list_candidate_threads(self):
            return [thread]

    monkeypatch.setattr(
        "mailassist.background_bot.generate_candidate_for_tone",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("filtered thread should not generate")),
    )

    settings = load_settings()
    provider = ProviderWithReadThread(settings.mock_provider_drafts_dir, account_email="magali@example.com")

    events = run_watch_pass(
        settings=settings,
        provider=provider,
        base_url="http://localhost:11434",
        selected_model="mock-model",
    )

    assert events == [
        {
            "type": "filtered_out",
            "thread_id": "thread-008",
            "subject": thread.subject,
            "classification": "filtered",
            "reason": "unread",
        }
    ]
    state = load_bot_state(tmp_path)
    assert state["providers"]["gmail"]["threads"]["thread-008"]["action"] == "filtered_out"
    assert state["recent_activity"][-1]["type"] == "filtered_out"


def test_watch_pass_can_limit_candidate_count(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(tmp_path / ".env", {})
    threads = [
        next(item for item in build_mock_threads() if item.thread_id == "thread-008"),
        next(item for item in build_mock_threads() if item.thread_id == "thread-010"),
    ]

    class ProviderWithThreads(MockProvider):
        name = "outlook"

        def list_candidate_threads(self):
            return threads

    monkeypatch.setattr(
        "mailassist.background_bot.generate_candidate_for_tone",
        lambda *args, **kwargs: ({"body": "Draft body", "generated_by": "mock-model"}, "mock-model", None, "reply_needed"),
    )

    settings = load_settings()
    provider = ProviderWithThreads(settings.mock_provider_drafts_dir, account_email="magali@example.com")

    events = run_watch_pass(
        settings=settings,
        provider=provider,
        base_url="http://localhost:11434",
        selected_model="mock-model",
        force=True,
        dry_run=True,
        max_candidates=1,
    )

    event_thread_ids = {event["thread_id"] for event in events if "thread_id" in event}
    assert event_thread_ids == {"thread-008"}
