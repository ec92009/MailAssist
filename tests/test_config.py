import json
from pathlib import Path

from mailassist.config import default_root_dir, load_settings, parse_bool, parse_int, read_env_file, write_env_file
from mailassist.gui.server import (
    OPTION_A_SEPARATOR,
    OPTION_B_SEPARATOR,
    build_single_review_candidate_prompt,
    build_review_candidates_prompt,
    candidate_display_label,
    default_review_state,
    extract_classification_and_bodies,
    extract_classification_and_body,
    extract_streaming_candidate_body,
    fallback_classification_for_thread,
    filtered_and_sorted_threads,
    load_review_state,
    merge_classification,
    payload_to_thread,
    render_page,
    stream_candidate_for_tone,
    update_candidate,
)


def populated_state() -> dict:
    state = default_review_state()
    state["threads"][0]["classification"] = "urgent"
    state["threads"][0]["candidate_generation_model"] = "mistral:latest"
    state["threads"][0]["candidates"] = [
        {
            "candidate_id": "option-a",
            "label": "Option A",
            "tone": "direct and executive",
            "classification": "urgent",
            "body": "Hello Alex",
            "original_body": "Hello Alex",
            "status": "pending_review",
            "generated_by": "mistral:latest",
            "generated_at": "2026-04-24T10:00:00+00:00",
            "edited_at": None,
        },
        {
            "candidate_id": "option-b",
            "label": "Option B",
            "tone": "warm and collaborative",
            "classification": "urgent",
            "body": "Hi Alex",
            "original_body": "Hi Alex",
            "status": "pending_review",
            "generated_by": "mistral:latest",
            "generated_at": "2026-04-24T10:00:00+00:00",
            "edited_at": None,
        },
    ]
    state["threads"][1]["classification"] = "reply_needed"
    state["threads"][1]["candidate_generation_model"] = "mistral:latest"
    state["threads"][1]["candidates"] = [
        {
            "candidate_id": "option-a",
            "label": "Option A",
            "tone": "direct and executive",
            "classification": "reply_needed",
            "body": "Hello Maria",
            "original_body": "Hello Maria",
            "status": "pending_review",
            "generated_by": "mistral:latest",
            "generated_at": "2026-04-24T10:00:00+00:00",
            "edited_at": None,
        }
    ]
    state["threads"][2]["classification"] = "automated"
    state["threads"][2]["candidate_generation_model"] = "mistral:latest"
    state["threads"][2]["candidates"] = [
        {
            "candidate_id": "option-a",
            "label": "Option A",
            "tone": "direct and executive",
            "classification": "automated",
            "body": "",
            "original_body": "",
            "status": "pending_review",
            "generated_by": "mistral:latest",
            "generated_at": "2026-04-24T10:00:00+00:00",
            "edited_at": None,
        }
    ]
    return state


def test_parse_bool_handles_common_values() -> None:
    assert parse_bool("true") is True
    assert parse_bool("YES") is True
    assert parse_bool("0") is False
    assert parse_bool(None, default=True) is True


def test_parse_int_falls_back_for_invalid_values() -> None:
    assert parse_int("90", 60) == 90
    assert parse_int("not-a-number", 60) == 60
    assert parse_int(None, 60) == 60


def test_read_and_write_env_file_round_trip(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    write_env_file(env_file, {"B": "2", "A": "1"})

    assert env_file.read_text(encoding="utf-8") == "A=1\nB=2\n"
    assert read_env_file(env_file) == {"A": "1", "B": "2"}


def test_load_settings_decodes_multiline_signature(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_USER_SIGNATURE": "Best regards,\\nEthan",
            "MAILASSIST_USER_TONE": "formal_polished",
            "MAILASSIST_BOT_POLL_SECONDS": "120",
        },
    )

    settings = load_settings()

    assert settings.user_signature == "Best regards,\nEthan"
    assert settings.user_tone == "formal_polished"
    assert settings.bot_poll_seconds == 120


def test_default_root_dir_uses_explicit_env(monkeypatch, tmp_path: Path) -> None:
    configured = tmp_path / "MailAssist Data"
    monkeypatch.setenv("MAILASSIST_ROOT_DIR", str(configured))

    assert default_root_dir() == configured


def test_load_settings_uses_application_root_from_env(monkeypatch, tmp_path: Path) -> None:
    configured = tmp_path / "MailAssist Data"
    monkeypatch.setenv("MAILASSIST_ROOT_DIR", str(configured))

    settings = load_settings()

    assert settings.root_dir == configured
    assert settings.data_dir == configured / "data"
    assert settings.gmail_credentials_file == configured / "secrets" / "gmail-client-secret.json"


def test_extract_classification_and_body_parses_prefix() -> None:
    classification, body = extract_classification_and_body(
        "Classification: urgent\n\nPlease send the notes today."
    )

    assert classification == "urgent"
    assert body == "Please send the notes today."


def test_extract_classification_and_bodies_splits_both_options() -> None:
    classification, bodies = extract_classification_and_bodies(
        "Classification: reply_needed\n\nFirst option body\n"
        f"{OPTION_A_SEPARATOR}\n"
        "Second option body\n"
        f"{OPTION_B_SEPARATOR}\n"
    )

    assert classification == "reply_needed"
    assert bodies == ["First option body", "Second option body"]


def test_extract_streaming_candidate_body_waits_for_blank_line() -> None:
    assert extract_streaming_candidate_body("Classification: urgent\n") == ""
    assert (
        extract_streaming_candidate_body("Classification: urgent\n\nHello there")
        == "Hello there"
    )


def test_merge_classification_prefers_set_aside_heuristics_for_obvious_automation() -> None:
    assert merge_classification("reply_needed", "automated") == "automated"


def test_fallback_classification_marks_action_needed_deadline_as_urgent() -> None:
    thread = next(item for item in default_review_state()["threads"] if item["thread_id"] == "thread-008")

    assert fallback_classification_for_thread(payload_to_thread(thread["thread"])) == "urgent"


def test_fallback_classification_marks_automated_notifications_as_automated() -> None:
    thread = next(item for item in default_review_state()["threads"] if item["thread_id"] == "thread-006")

    assert fallback_classification_for_thread(payload_to_thread(thread["thread"])) == "automated"


def test_build_review_candidates_prompt_includes_full_contract() -> None:
    thread = populated_state()["threads"][0]["thread"]
    prompt = build_review_candidates_prompt(
        payload_to_thread(thread),
        signature="Best regards,\nEthan",
    )

    assert "You are MailAssist, a local-first email drafting assistant." in prompt
    assert "Classification rules:" in prompt
    assert "Drafting rules:" in prompt
    assert "Output format requirements:" in prompt
    assert "First line must be exactly: `Classification: <value>`" in prompt
    assert OPTION_A_SEPARATOR in prompt
    assert OPTION_B_SEPARATOR in prompt
    assert "Draft 2 candidate replies" in prompt
    assert "Thread context:" in prompt
    assert "Project kickoff follow-up" in prompt
    assert "MailAssist will append the user's saved signature" in prompt
    assert "Best regards,\nEthan" not in prompt
    assert "Do not turn email domains into company names" in prompt
    assert "do not invent the user's decision" in prompt
    assert "Do not invent teams" in prompt
    assert "leave the final choice for the user to add" in prompt
    assert "Avoid promise-shaped phrases" in prompt
    assert "do not repeat that timing as a future promise" in prompt
    assert "Never return only a greeting, sign-off, or signature" in prompt


def test_build_single_review_candidate_prompt_requests_one_alternative() -> None:
    thread = populated_state()["threads"][0]["thread"]
    prompt = build_single_review_candidate_prompt(
        payload_to_thread(thread),
        tone="direct and executive",
        guidance="Keep it concise and practical",
        existing_body="Please send the notes today.",
        signature="Best regards,\nEthan",
    )

    assert "Draft 1 candidate reply only" in prompt
    assert "Tone target: direct and executive." in prompt
    assert "Existing draft in this same tone:" in prompt
    assert "Write a meaningfully different alternative." in prompt
    assert "MailAssist will append the user's saved signature" in prompt
    assert "Best regards,\nEthan" not in prompt
    assert "Do not turn email domains into company names" in prompt
    assert "do not invent the user's decision" in prompt
    assert "Do not invent teams" in prompt
    assert "leave the final choice for the user to add" in prompt
    assert "Avoid promise-shaped phrases" in prompt
    assert "do not repeat that timing as a future promise" in prompt
    assert "Never return only a greeting, sign-off, or signature" in prompt
    assert OPTION_A_SEPARATOR not in prompt
    assert OPTION_B_SEPARATOR not in prompt


def test_load_review_state_normalizes_tone_labels(tmp_path: Path) -> None:
    state = default_review_state()
    state["threads"][0]["candidates"] = [
        {
            "candidate_id": "option-a",
            "label": "Option A",
            "tone": "direct and executive",
            "classification": "urgent",
            "body": "Hello Alex",
            "original_body": "Hello Alex",
            "status": "pending_review",
            "generated_by": "mistral:latest",
            "generated_at": "2026-04-24T10:00:00+00:00",
            "edited_at": None,
        }
    ]
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "review-inbox.json").write_text(json.dumps(state), encoding="utf-8")

    loaded = load_review_state(tmp_path)

    assert loaded["threads"][0]["candidates"][0]["label"] == candidate_display_label(
        "direct and executive"
    )


def test_render_page_includes_queue_filters_and_classification(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_OLLAMA_URL": "http://localhost:11434",
            "MAILASSIST_OLLAMA_MODEL": "mistral:latest",
        },
    )

    page = render_page(review_state=populated_state(), models=["mistral:latest"])

    assert "Apply queue view" in page
    assert "classification: urgent" in page
    assert "Set aside" in page
    assert "Order" in page


def test_render_page_can_filter_to_set_aside_queue(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_OLLAMA_URL": "http://localhost:11434",
            "MAILASSIST_OLLAMA_MODEL": "mistral:latest",
        },
    )

    page = render_page(
        review_state=populated_state(),
        models=["mistral:latest"],
        filter_classification="set_aside",
        selected_thread_id="thread-003",
    )

    assert "Your weekly analytics digest" in page
    assert "Project kickoff follow-up" not in page


def test_render_page_shows_editable_candidates_and_actions(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_OLLAMA_URL": "http://localhost:11434",
            "MAILASSIST_OLLAMA_MODEL": "mistral:latest",
        },
    )

    page = render_page(review_state=populated_state(), models=["mistral:latest"])

    assert "Response Drafts" in page
    assert "Editable draft" in page
    assert "Green light this draft" in page
    assert "Red light this draft" in page
    assert "Save edits" in page


def test_filtered_and_sorted_threads_can_sort_by_received_date() -> None:
    state = populated_state()
    threads = state["threads"][:3]

    ordered = filtered_and_sorted_threads(
        threads,
        filter_classification="all",
        filter_status="all",
        sort_order="received_at",
    )

    assert [item["thread_id"] for item in ordered[:3]] == ["thread-001", "thread-002", "thread-003"]


def test_filtered_and_sorted_threads_can_sort_by_sender() -> None:
    state = populated_state()
    threads = state["threads"][:3]

    ordered = filtered_and_sorted_threads(
        threads,
        filter_classification="all",
        filter_status="all",
        sort_order="sender",
    )

    assert [item["thread_id"] for item in ordered[:3]] == ["thread-001", "thread-002", "thread-003"]


def test_update_candidate_green_lights_selected_draft() -> None:
    state = populated_state()
    thread = state["threads"][0]

    update_candidate(thread, "option-b", "Edited second draft", "green_light")

    assert thread["selected_candidate_id"] == "option-b"
    assert thread["status"] == "use_draft"
    assert thread["candidates"][1]["status"] == "use_draft"
    assert thread["candidates"][1]["body"] == "Edited second draft"
    assert thread["candidates"][0]["status"] == "pending_review"
    assert thread["archive_selected"] is True


def test_update_candidate_red_lights_map_to_ignored_thread_state() -> None:
    state = populated_state()
    thread = state["threads"][0]

    update_candidate(thread, "option-a", "First draft", "red_light")

    assert thread["status"] == "ignored"
    assert thread["selected_candidate_id"] is None
    assert thread["archive_selected"] is True
    assert [item["status"] for item in thread["candidates"]] == ["ignored", "pending_review"]


def test_stream_candidate_for_tone_emits_incremental_chunks(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)

    class FakeOllamaClient:
        def __init__(self, base_url: str, model: str) -> None:
            self.base_url = base_url
            self.model = model

        def compose_reply_stream(self, prompt: str):
            assert "Return only the candidate email body." in prompt
            yield "Hello"
            yield " there"

    monkeypatch.setattr(
        "mailassist.gui.server.list_available_models",
        lambda base_url, selected_model: (["mistral:latest"], ""),
    )
    monkeypatch.setattr(
        "mailassist.gui.server.resolve_generation_model",
        lambda selected_model, models: "mistral:latest",
    )
    monkeypatch.setattr("mailassist.gui.server.OllamaClient", FakeOllamaClient)

    updates: list[str] = []
    candidate, generation_model, generation_error, classification = stream_candidate_for_tone(
        payload_to_thread(populated_state()["threads"][0]["thread"]),
        candidate_id="option-a",
        tone="direct and executive",
        guidance="Keep it concise and practical.",
        base_url="http://localhost:11434",
        selected_model="mistral:latest",
        on_body_update=updates.append,
    )

    assert updates == ["Hello", " there"]
    assert candidate["body"] == "Hello there\n\nBest regards,\nEthan"
    assert generation_model == "mistral:latest"
    assert generation_error is None
    assert classification == "urgent"
