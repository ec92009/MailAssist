from mailassist.review_state import (
    default_review_state,
    normalize_review_status,
    regenerate_candidate_for_thread,
    update_candidate,
    update_thread_status,
)


def build_thread_state() -> dict:
    return {
        "thread_id": "thread-001",
        "status": "pending_review",
        "selected_candidate_id": None,
        "archive_selected": False,
        "archived": False,
        "candidates": [
            {
                "candidate_id": "option-a",
                "body": "First draft",
                "original_body": "First draft",
                "status": "pending_review",
                "edited_at": None,
            },
            {
                "candidate_id": "option-b",
                "body": "Second draft",
                "original_body": "Second draft",
                "status": "pending_review",
                "edited_at": None,
            },
        ],
    }


def test_update_candidate_reset_restores_original_body() -> None:
    thread_state = build_thread_state()
    update_candidate(thread_state, "option-a", "Changed draft", "save")

    candidate = update_candidate(thread_state, "option-a", "", "reset")

    assert candidate["body"] == "First draft"
    assert candidate["status"] == "pending_review"
    assert candidate["edited_at"] is None


def test_update_candidate_use_this_marks_thread_ready() -> None:
    thread_state = build_thread_state()

    update_candidate(thread_state, "option-b", "Approved draft", "use_this")

    assert normalize_review_status(thread_state["status"]) == "use_draft"
    assert thread_state["selected_candidate_id"] == "option-b"
    assert thread_state["candidates"][0]["status"] == "pending_review"
    assert thread_state["candidates"][1]["status"] == "use_draft"
    assert thread_state["archive_selected"] is True


def test_update_thread_status_ignore_marks_thread_for_archive() -> None:
    thread_state = build_thread_state()

    update_thread_status(thread_state, "ignore")

    assert normalize_review_status(thread_state["status"]) == "ignored"
    assert thread_state["selected_candidate_id"] is None
    assert thread_state["archive_selected"] is True
    assert all(candidate["status"] == "pending_review" for candidate in thread_state["candidates"])


def test_update_thread_status_archive_sets_archived_flag() -> None:
    thread_state = build_thread_state()

    update_thread_status(thread_state, "archive")

    assert thread_state["archived"] is True
    assert thread_state["archive_selected"] is True


def test_regenerate_candidate_for_thread_clears_selected_candidate(monkeypatch) -> None:
    state = default_review_state()
    thread_state = state["threads"][0]
    thread_state["status"] = "use_draft"
    thread_state["selected_candidate_id"] = "option-a"
    thread_state["candidates"] = [
        {
            "candidate_id": "option-a",
            "label": "Option A",
            "tone": "direct and executive",
            "classification": "reply_needed",
            "body": "Old draft",
            "original_body": "Old draft",
            "status": "use_draft",
            "generated_by": "mistral:latest",
            "generated_at": "2026-04-24T10:00:00+00:00",
            "edited_at": None,
        },
        {
            "candidate_id": "option-b",
            "label": "Option B",
            "tone": "warm and collaborative",
            "classification": "reply_needed",
            "body": "Second draft",
            "original_body": "Second draft",
            "status": "pending_review",
            "generated_by": "mistral:latest",
            "generated_at": "2026-04-24T10:00:00+00:00",
            "edited_at": None,
        },
    ]

    def fake_generate_candidate_for_tone(*args, **kwargs):
        return (
            {
                "candidate_id": "option-a",
                "label": "Direct and executive",
                "tone": "direct and executive",
                "classification": "reply_needed",
                "body": "Fresh draft",
                "original_body": "Fresh draft",
                "status": "pending_review",
                "generated_by": "mock-model",
                "generated_at": "2026-04-24T10:01:00+00:00",
                "edited_at": None,
            },
            "mock-model",
            None,
            "reply_needed",
        )

    monkeypatch.setattr("mailassist.review_state.generate_candidate_for_tone", fake_generate_candidate_for_tone)

    regenerate_candidate_for_thread(
        state,
        "thread-001",
        "option-a",
        base_url="http://localhost:11434",
        selected_model="mock-model",
    )

    assert thread_state["selected_candidate_id"] is None
    assert normalize_review_status(thread_state["status"]) == "pending_review"
    assert thread_state["candidates"][0]["body"] == "Fresh draft"
