from mailassist.core.orchestrator import build_prompt
from mailassist.models import EmailMessage, EmailThread


def test_build_prompt_includes_revision_notes() -> None:
    thread = EmailThread(
        thread_id="t1",
        subject="Hello",
        participants=["a@example.com", "b@example.com"],
        messages=[
            EmailMessage(
                message_id="m1",
                sender="a@example.com",
                to=["b@example.com"],
                sent_at="2026-04-24T00:00:00Z",
                text="Need an update.",
            )
        ],
    )

    prompt = build_prompt(thread, revision_notes="Be warmer.")

    assert "Be warmer." in prompt
    assert "Need an update." in prompt
