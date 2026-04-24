from pathlib import Path

from mailassist.config import parse_bool, read_env_file, write_env_file
from mailassist.gui.server import (
    build_review_candidate_prompt,
    default_review_state,
    extract_classification_and_body,
    merge_classification,
    payload_to_thread,
    render_page,
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


def test_read_and_write_env_file_round_trip(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    write_env_file(env_file, {"B": "2", "A": "1"})

    assert env_file.read_text(encoding="utf-8") == "A=1\nB=2\n"
    assert read_env_file(env_file) == {"A": "1", "B": "2"}


def test_extract_classification_and_body_parses_prefix() -> None:
    classification, body = extract_classification_and_body(
        "Classification: urgent\n\nPlease send the notes today."
    )

    assert classification == "urgent"
    assert body == "Please send the notes today."


def test_merge_classification_prefers_set_aside_heuristics_for_obvious_automation() -> None:
    assert merge_classification("reply_needed", "automated") == "automated"


def test_build_review_candidate_prompt_includes_full_contract() -> None:
    thread = populated_state()["threads"][0]["thread"]
    prompt = build_review_candidate_prompt(
        payload_to_thread(thread),
        option_label="Option A",
        tone="direct and executive",
        guidance="Keep it concise and practical.",
    )

    assert "You are MailAssist, a local-first email drafting assistant." in prompt
    assert "Classification rules:" in prompt
    assert "Drafting rules:" in prompt
    assert "Output format requirements:" in prompt
    assert "First line must be exactly: `Classification: <value>`" in prompt
    assert "Thread context:" in prompt
    assert "Project kickoff follow-up" in prompt


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


def test_update_candidate_green_lights_selected_draft() -> None:
    state = populated_state()
    thread = state["threads"][0]

    update_candidate(thread, "option-b", "Edited second draft", "green_light")

    assert thread["selected_candidate_id"] == "option-b"
    assert thread["status"] == "green_lit"
    assert thread["candidates"][1]["status"] == "green_lit"
    assert thread["candidates"][1]["body"] == "Edited second draft"
    assert thread["candidates"][0]["status"] == "pending_review"


def test_update_candidate_red_lights_all_candidates_when_needed() -> None:
    state = populated_state()
    thread = state["threads"][0]

    update_candidate(thread, "option-a", "First draft", "red_light")
    update_candidate(thread, "option-b", "Second draft", "red_light")

    assert thread["status"] == "red_lit"
    assert thread["selected_candidate_id"] is None
    assert [item["status"] for item in thread["candidates"]] == ["red_lit", "red_lit"]
