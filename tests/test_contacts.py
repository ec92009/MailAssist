import json

from mailassist.contacts import (
    ElderContact,
    elder_contact_for_thread,
    elder_relationship_guidance_for_thread,
    load_elder_contacts,
    parse_elder_contacts,
    save_elder_contacts,
)
from mailassist.models import EmailMessage, EmailThread


def build_thread(sender: str) -> EmailThread:
    return EmailThread(
        thread_id="thread-1",
        subject="Coucou",
        participants=[sender, "me@example.com"],
        messages=[
            EmailMessage(
                message_id="message-1",
                sender=sender,
                to=["me@example.com"],
                sent_at="2026-04-30T12:00:00+00:00",
                text="Tu vois ce message?",
            )
        ],
    )


def test_parse_elder_contacts_accepts_comments_and_deduplicates() -> None:
    contacts = parse_elder_contacts(
        [
            {"email": "Agnes <agnes@example.com>", "comment": "Family elder"},
            {"email": "agnes@example.com", "comment": "Duplicate"},
            "mentor@example.com",
            {"email": "not-an-email", "comment": "Ignored"},
        ]
    )

    assert contacts == (
        ElderContact(email="agnes@example.com", comment="Family elder"),
        ElderContact(email="mentor@example.com", comment=""),
    )


def test_save_and_load_elder_contacts_round_trip(tmp_path) -> None:
    path = tmp_path / "data" / "elders.json"

    save_elder_contacts(
        path,
        [
            ElderContact(email="agnes@example.com", comment="Family elder"),
        ],
    )

    assert json.loads(path.read_text(encoding="utf-8")) == [
        {"email": "agnes@example.com", "comment": "Family elder"}
    ]
    assert load_elder_contacts(path) == (
        ElderContact(email="agnes@example.com", comment="Family elder"),
    )


def test_elder_relationship_guidance_only_for_matching_latest_sender() -> None:
    contacts = (ElderContact(email="agnes@example.com", comment="Use respectful French."),)

    matching = elder_relationship_guidance_for_thread(build_thread("Agnes <agnes@example.com>"), contacts)
    missing = elder_relationship_guidance_for_thread(build_thread("friend@example.com"), contacts)

    assert "Elders list" in matching
    assert "respectful `vous`" in matching
    assert "Use respectful French." in matching
    assert missing == ""
    assert elder_contact_for_thread(build_thread("friend@example.com"), contacts) is None
