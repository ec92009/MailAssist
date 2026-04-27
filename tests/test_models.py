from mailassist.models import EmailThread


def test_email_thread_default_unread_true() -> None:
    thread = EmailThread(
        thread_id="t1",
        subject="Hello",
        participants=["a@example.com"],
        messages=[],
    )
    assert thread.unread is True


def test_email_thread_from_dict_reads_unread() -> None:
    payload = {
        "thread_id": "t1",
        "subject": "Hello",
        "participants": [],
        "messages": [],
        "unread": False,
    }
    thread = EmailThread.from_dict(payload)
    assert thread.unread is False


def test_email_thread_from_dict_defaults_unread_true_when_missing() -> None:
    payload = {
        "thread_id": "t1",
        "subject": "Hello",
        "participants": [],
        "messages": [],
    }
    thread = EmailThread.from_dict(payload)
    assert thread.unread is True
