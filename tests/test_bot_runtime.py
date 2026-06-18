import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from mailassist.bot_runtime import (
    DEFAULT_MANUAL_SCAN_LOCK_WAIT_SECONDS,
    MAILASSIST_GMAIL_LABELS,
    MAILASSIST_GMAIL_PARENT_LABEL,
    _mailassist_category_for_thread,
    _mailassist_labels_for_thread,
    _scan_lock_wait_seconds,
    command_review_bot,
)
from mailassist.config import write_env_file
from mailassist.models import EmailMessage, EmailThread
from mailassist.providers.base import ProviderReadiness


def test_review_bot_ollama_check_requires_prompt(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_OLLAMA_URL": "http://localhost:11434",
            "MAILASSIST_OLLAMA_MODEL": "llama3.2:latest",
        },
    )
    args = argparse.Namespace(
        command="review-bot",
        action="ollama-check",
        thread_id=None,
        prompt="",
        base_url=None,
        selected_model=None,
    )

    exit_code = command_review_bot(args)

    assert exit_code == 1
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert lines[0]["type"] == "started"
    assert lines[0]["command"] == "review-bot"
    assert lines[0]["arguments"]["action"] == "ollama-check"
    assert lines[0]["arguments"]["base_url"] == "http://localhost:11434"
    assert lines[0]["arguments"]["selected_model"] == "llama3.2:latest"
    assert lines[1]["type"] == "log_file"
    assert Path(lines[1]["path"]).parent == tmp_path / "data" / "bot-logs"
    assert lines[-1]["type"] == "error"
    assert "--prompt is required for ollama-check" in lines[-1]["message"]

def test_review_bot_gmail_inbox_preview_emits_message_metadata(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_GMAIL_ENABLED": "true",
        },
    )

    class FakeProvider:
        def list_recent_inbox_messages(self, limit: int = 10):
            assert limit == 2
            return [
                {
                    "id": "msg-1",
                    "thread_id": "thread-1",
                    "from": "sender@example.com",
                    "to": "you@example.com",
                    "date": "Sat, 25 Apr 2026 08:00:00 +0200",
                    "subject": "Hello",
                    "snippet": "Short preview",
                }
            ]

    monkeypatch.setattr(
        "mailassist.bot_runtime.get_provider_for_settings",
        lambda settings, provider_name: FakeProvider(),
    )

    args = argparse.Namespace(
        command="review-bot",
        action="gmail-inbox-preview",
        thread_id=None,
        prompt=None,
        base_url=None,
        selected_model=None,
        provider="gmail",
        batch_size=1,
        limit=2,
        force=False,
    )

    exit_code = command_review_bot(args)

    assert exit_code == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert any(line["type"] == "gmail_message_preview" for line in lines)
    assert lines[-1]["type"] == "completed"
    assert lines[-1]["message_count"] == 1


def test_review_bot_gmail_prompt_lab_saves_private_prompt_without_printing_bodies(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_GMAIL_ENABLED": "true",
            "MAILASSIST_USER_SIGNATURE": "Best,\\nEthan",
            "MAILASSIST_USER_TONE": "brief_casual",
        },
    )

    private_body = "PRIVATE BODY: please refine this prompt locally"
    thread = EmailThread(
        thread_id="thread-private",
        subject="Prompt sample",
        participants=["sender@example.com", "me@example.com"],
        messages=[
            EmailMessage(
                message_id="msg-private",
                sender="sender@example.com",
                to=["me@example.com"],
                sent_at="2026-05-02T08:00:00+00:00",
                text=private_body,
            )
        ],
        unread=True,
    )

    class FakeProvider:
        def list_candidate_threads(self):
            return [thread]

    monkeypatch.setattr(
        "mailassist.bot_runtime.get_provider_for_settings",
        lambda settings, provider_name: FakeProvider(),
    )

    args = argparse.Namespace(
        command="review-bot",
        action="gmail-prompt-lab",
        thread_id=None,
        prompt=None,
        base_url=None,
        selected_model=None,
        provider="gmail",
        batch_size=1,
        limit=3,
        force=False,
        dry_run=False,
        poll_seconds=0,
        max_passes=0,
    )

    exit_code = command_review_bot(args)

    assert exit_code == 0
    output = capsys.readouterr().out
    assert private_body not in output
    lines = [json.loads(line) for line in output.splitlines() if line.strip()]
    saved = next(line for line in lines if line["type"] == "gmail_prompt_lab_saved")
    prompt_path = Path(saved["path"])
    assert prompt_path.parent == tmp_path / "data" / "prompt-lab"
    prompt_text = prompt_path.read_text(encoding="utf-8")
    assert private_body in prompt_text
    assert "INPUT THREAD thread-private" in prompt_text
    assert lines[-1]["type"] == "completed"
    assert lines[-1]["thread_count"] == 1


def test_review_bot_gmail_controlled_draft_creates_one_safe_draft(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.chdir(tmp_path)

    class FakeProvider:
        name = "gmail"

        def __init__(self) -> None:
            self.drafts = []

        def get_account_email(self):
            return "me@example.com"

        def create_draft(self, draft):
            self.drafts.append(draft)
            assert draft.to == ["me@example.com"]
            assert draft.body_html is not None

            class Reference:
                draft_id = "draft-1"
                thread_id = "thread-1"
                message_id = "message-1"

            return Reference()

    provider = FakeProvider()
    monkeypatch.setattr(
        "mailassist.bot_runtime.get_provider_for_settings",
        lambda settings, provider_name: provider,
    )

    args = argparse.Namespace(
        command="review-bot",
        action="gmail-controlled-draft",
        thread_id="thread-008",
        prompt=None,
        base_url=None,
        selected_model="mock-model",
        provider="gmail",
        batch_size=1,
        limit=10,
        force=False,
        dry_run=False,
        poll_seconds=0,
        max_passes=0,
    )

    exit_code = command_review_bot(args)

    assert exit_code == 0
    assert len(provider.drafts) == 1
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert any(line["type"] == "draft_created" and line["provider_draft_id"] == "draft-1" for line in lines)
    assert lines[-1]["type"] == "completed"
    assert lines[-1]["draft_count"] == 1


def test_review_bot_gmail_label_cleanup_dry_run_lists_candidates(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.chdir(tmp_path)

    class FakeProvider:
        def find_old_labeled_message_groups(self, *, older_than_years: int = 5):
            assert older_than_years == 5
            return [
                {
                    "id": "Label_1",
                    "name": "Old Project",
                    "message_ids": ["msg-1", "msg-2"],
                    "message_count": 2,
                    "limited": False,
                }
            ]

    monkeypatch.setattr(
        "mailassist.bot_runtime.get_provider_for_settings",
        lambda settings, provider_name: FakeProvider(),
    )

    args = argparse.Namespace(
        command="review-bot",
        action="gmail-label-cleanup",
        thread_id=None,
        prompt=None,
        base_url=None,
        selected_model=None,
        provider="gmail",
        batch_size=1,
        limit=10,
        force=False,
        dry_run=False,
        poll_seconds=0,
        max_passes=0,
        create_draft=False,
        older_than_years=5,
        remove_labels=False,
    )

    exit_code = command_review_bot(args)

    assert exit_code == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert any(
        line["type"] == "gmail_label_old_messages" and line["label_name"] == "Old Project"
        for line in lines
    )
    assert lines[-1]["type"] == "completed"
    assert lines[-1]["label_count"] == 1
    assert lines[-1]["removed_count"] == 0
    assert lines[-1]["dry_run"] is True


def test_review_bot_gmail_label_cleanup_delete_requires_explicit_flag(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.chdir(tmp_path)

    class FakeProvider:
        def __init__(self) -> None:
            self.deleted = []

        def find_old_labeled_message_groups(self, *, older_than_years: int = 5):
            return [
                {
                    "id": "Label_1",
                    "name": "Old Project",
                    "message_ids": ["msg-1", "msg-2"],
                    "message_count": 2,
                    "limited": False,
                }
            ]

        def remove_label_from_messages(self, label_id: str, message_ids: list[str]) -> int:
            self.deleted.append((label_id, message_ids))
            return len(message_ids)

    provider = FakeProvider()
    monkeypatch.setattr(
        "mailassist.bot_runtime.get_provider_for_settings",
        lambda settings, provider_name: provider,
    )

    args = argparse.Namespace(
        command="review-bot",
        action="gmail-label-cleanup",
        thread_id=None,
        prompt=None,
        base_url=None,
        selected_model=None,
        provider="gmail",
        batch_size=1,
        limit=10,
        force=False,
        dry_run=False,
        poll_seconds=0,
        max_passes=0,
        create_draft=False,
        older_than_years=5,
        remove_labels=True,
    )

    exit_code = command_review_bot(args)

    assert exit_code == 0
    assert provider.deleted == [("Label_1", ["msg-1", "msg-2"])]
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert any(
        line["type"] == "gmail_label_removed_from_old_messages"
        and line["label_id"] == "Label_1"
        for line in lines
    )
    assert lines[-1]["removed_count"] == 2
    assert lines[-1]["dry_run"] is False


def test_review_bot_gmail_unused_label_cleanup_deletes_empty_labels(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.chdir(tmp_path)

    class FakeProvider:
        def __init__(self) -> None:
            self.deleted = []

        def find_unused_user_labels(self):
            return [
                {
                    "id": "Label_1",
                    "name": "Old Empty",
                    "messages_total": 0,
                    "threads_total": 0,
                }
            ]

        def delete_user_label(self, label_id: str) -> None:
            self.deleted.append(label_id)

    provider = FakeProvider()
    monkeypatch.setattr(
        "mailassist.bot_runtime.get_provider_for_settings",
        lambda settings, provider_name: provider,
    )

    args = argparse.Namespace(
        command="review-bot",
        action="gmail-unused-label-cleanup",
        thread_id=None,
        prompt=None,
        base_url=None,
        selected_model=None,
        provider="gmail",
        batch_size=1,
        limit=10,
        force=False,
        dry_run=False,
        poll_seconds=0,
        max_passes=0,
        create_draft=False,
        older_than_years=5,
        remove_labels=False,
        delete_unused_labels=True,
    )

    exit_code = command_review_bot(args)

    assert exit_code == 0
    assert provider.deleted == ["Label_1"]
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert any(
        line["type"] == "gmail_unused_label_deleted" and line["label_name"] == "Old Empty"
        for line in lines
    )
    assert lines[-1]["deleted_count"] == 1
    assert lines[-1]["dry_run"] is False


def test_mailassist_gmail_label_classifier_assigns_one_best_bin() -> None:
    thread = EmailThread(
        thread_id="thread-1",
        subject="Invoice renewal action needed",
        participants=["sender@example.com", "me@example.com"],
        messages=[
            EmailMessage(
                message_id="msg-1",
                sender="sender@example.com",
                to=["me@example.com"],
                                sent_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                text="Please review and renew your license. Payment is due Friday.",
            )
        ],
    )

    labels = _mailassist_labels_for_thread(thread)

    assert labels == [MAILASSIST_GMAIL_LABELS["needs_reply"]]


def test_mailassist_gmail_label_classifier_accepts_ollama_category() -> None:
    class FakeClassifier:
        def compose_reply(self, prompt: str) -> str:
            assert "Allowed categories" in prompt
            assert "- Needs Reply" in prompt
            return "Receipts & Finance"

    thread = EmailThread(
        thread_id="thread-1",
        subject="Invoice",
        participants=["sender@example.com", "me@example.com"],
        messages=[
            EmailMessage(
                message_id="msg-1",
                sender="sender@example.com",
                to=["me@example.com"],
                sent_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                text="Your invoice is attached.",
            )
        ],
    )

    category, source, error = _mailassist_category_for_thread(
        thread,
        ("Needs Reply", "Needs Action", "Receipts & Finance"),
        classifier=FakeClassifier(),
    )

    assert category == "Receipts & Finance"
    assert source == "ollama"
    assert error is None


def test_mailassist_category_classifier_guards_needs_reply_for_automated_threads() -> None:
    class FakeClassifier:
        def compose_reply(self, prompt: str) -> str:
            return "Needs Reply"

    thread = EmailThread(
        thread_id="thread-automated",
        subject="Optimize performance with Azure Advisor",
        participants=["azure@promomail.microsoft.com", "me@example.com"],
        messages=[
            EmailMessage(
                message_id="msg-1",
                sender="azure@promomail.microsoft.com",
                to=["me@example.com"],
                sent_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                text="Review these automated recommendations for your Azure account.",
            )
        ],
    )

    category, source, error = _mailassist_category_for_thread(
        thread,
        ("Needs Reply", "Needs Action", "Marketing"),
        classifier=FakeClassifier(),
    )

    assert category == "Needs Action"
    assert source == "ollama"
    assert error is None


def test_mailassist_gmail_label_classifier_accepts_ollama_no_category() -> None:
    class FakeClassifier:
        def compose_reply(self, prompt: str) -> str:
            assert "Allowed no-category responses" in prompt
            return "No obvious category"

    thread = EmailThread(
        thread_id="thread-1",
        subject="Random note",
        participants=["sender@example.com", "me@example.com"],
        messages=[
            EmailMessage(
                message_id="msg-1",
                sender="sender@example.com",
                to=["me@example.com"],
                sent_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                text="A thing happened.",
            )
        ],
    )

    category, source, error = _mailassist_category_for_thread(
        thread,
        ("Needs Reply", "Needs Action", "Subscriptions"),
        classifier=FakeClassifier(),
    )

    assert category is None
    assert source == "ollama"
    assert error is None


def test_review_bot_gmail_populate_labels_applies_recent_thread_bins(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.chdir(tmp_path)

    class FakeProvider:
        def __init__(self) -> None:
            self.applied = []

        def ensure_user_labels(self, label_names):
            assert label_names[0] == MAILASSIST_GMAIL_PARENT_LABEL
            return {name: f"id-{index}" for index, name in enumerate(label_names)}

        def list_threads_by_query(self, query: str, *, max_threads: int = 100):
            assert query == "newer_than:7d"
            return [
                EmailThread(
                    thread_id="thread-1",
                    subject="Weekly newsletter",
                    participants=["sender@example.com", "me@example.com"],
                    messages=[
                        EmailMessage(
                            message_id="msg-1",
                            sender="sender@example.com",
                            to=["me@example.com"],
                            sent_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                            text="Unsubscribe from this newsletter",
                        )
                    ],
                )
            ]

        def add_labels_to_thread(self, thread_id: str, label_ids: list[str]) -> None:
            self.applied.append((thread_id, label_ids))

        def replace_thread_labels(
            self,
            thread_id: str,
            add_label_ids: list[str],
            remove_label_ids: list[str],
        ) -> None:
            self.applied.append((thread_id, add_label_ids, remove_label_ids))

    provider = FakeProvider()
    monkeypatch.setattr(
        "mailassist.bot_runtime.get_provider_for_settings",
        lambda settings, provider_name: provider,
    )
    monkeypatch.setattr(
        "mailassist.bot_runtime.OllamaClient",
        lambda base_url, selected_model: type(
            "FakeClassifier",
            (),
            {"compose_reply": lambda self, prompt: "NA"},
        )(),
    )

    args = argparse.Namespace(
        command="review-bot",
        action="gmail-populate-labels",
        thread_id=None,
        prompt=None,
        base_url=None,
        selected_model=None,
        provider="gmail",
        batch_size=1,
        limit=10,
        force=False,
        dry_run=False,
        poll_seconds=0,
        max_passes=0,
        create_draft=False,
        older_than_years=5,
        remove_labels=False,
        delete_unused_labels=False,
        days=7,
        apply_labels=True,
    )

    exit_code = command_review_bot(args)

    assert exit_code == 0
    assert provider.applied
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert any(
        line["type"] == "gmail_thread_labeled"
        and line["category"] == "NA"
        and line["labels"] == []
        for line in lines
    )
    assert any(
        line["type"] == "organize_phase"
        and line["phase"] == "preparing_labels"
        and line["provider"] == "gmail"
        for line in lines
    )
    assert any(
        line["type"] == "gmail_thread_classification_started"
        and line["subject"] == "Weekly newsletter"
        and line["current_index"] == 1
        and line["thread_count"] == 1
        for line in lines
    )
    assert provider.applied[0][2]
    assert lines[-1]["applied_count"] == 1


def test_review_bot_outlook_populate_categories_previews_without_writes(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.chdir(tmp_path)

    class FakeProvider:
        name = "outlook"

        def readiness_check(self):
            return ProviderReadiness(
                provider="outlook",
                status="ready",
                message="ready",
                account_email="me@example.com",
                can_authenticate=True,
                can_read=True,
                can_create_drafts=True,
            )

        def list_recent_threads(self, *, limit: int = 25):
            assert limit == 5
            return [
                EmailThread(
                    thread_id="conv-1",
                    subject="Weekly newsletter",
                    participants=["sender@example.com", "me@example.com"],
                    messages=[
                        EmailMessage(
                            message_id="msg-1",
                            sender="sender@example.com",
                            to=["me@example.com"],
                            sent_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                            text="Unsubscribe from this newsletter",
                        )
                    ],
                )
            ]

        def replace_thread_categories(self, *args, **kwargs):
            raise AssertionError("dry run should not update Outlook categories")

    monkeypatch.setattr(
        "mailassist.bot_runtime.get_provider_for_settings",
        lambda settings, provider_name: FakeProvider(),
    )
    monkeypatch.setattr(
        "mailassist.bot_runtime.OllamaClient",
        lambda base_url, selected_model: type(
            "FakeClassifier",
            (),
            {"compose_reply": lambda self, prompt: "Subscriptions"},
        )(),
    )

    args = argparse.Namespace(
        command="review-bot",
        action="outlook-populate-categories",
        thread_id=None,
        prompt=None,
        base_url=None,
        selected_model=None,
        provider="outlook",
        batch_size=1,
        limit=5,
        force=False,
        dry_run=False,
        poll_seconds=0,
        max_passes=0,
        create_draft=False,
        older_than_years=5,
        remove_labels=False,
        delete_unused_labels=False,
        days=7,
        apply_labels=False,
        apply_categories=False,
    )

    exit_code = command_review_bot(args)

    assert exit_code == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert any(
        line["type"] == "outlook_thread_category_preview"
        and line["categories"] == ["MailAssist - Subscriptions"]
        for line in lines
    )
    assert any(
        line["type"] == "organize_phase"
        and line["phase"] == "reading_threads"
        and line["provider"] == "outlook"
        for line in lines
    )
    assert any(
        line["type"] == "outlook_thread_classification_started"
        and line["subject"] == "Weekly newsletter"
        and line["current_index"] == 1
        and line["thread_count"] == 1
        for line in lines
    )
    assert lines[-1]["dry_run"] is True
    assert lines[-1]["applied_count"] == 0


def test_review_bot_outlook_populate_categories_can_apply(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.chdir(tmp_path)

    class FakeProvider:
        name = "outlook"

        def __init__(self) -> None:
            self.applied = []

        def readiness_check(self):
            return ProviderReadiness(
                provider="outlook",
                status="ready",
                message="ready",
                account_email="me@example.com",
                can_authenticate=True,
                can_read=True,
                can_create_drafts=True,
            )

        def list_recent_threads(self, *, limit: int = 25):
            return [
                EmailThread(
                    thread_id="conv-1",
                    subject="Invoice",
                    participants=["sender@example.com", "me@example.com"],
                    messages=[
                        EmailMessage(
                            message_id="msg-1",
                            sender="sender@example.com",
                            to=["me@example.com"],
                            sent_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                            text="Your invoice is attached.",
                        )
                    ],
                )
            ]

        def replace_thread_categories(self, thread_id, *, add_categories, remove_categories):
            self.applied.append((thread_id, add_categories, remove_categories))
            return 1

    provider = FakeProvider()
    monkeypatch.setattr(
        "mailassist.bot_runtime.get_provider_for_settings",
        lambda settings, provider_name: provider,
    )
    monkeypatch.setattr(
        "mailassist.bot_runtime.OllamaClient",
        lambda base_url, selected_model: type(
            "FakeClassifier",
            (),
            {"compose_reply": lambda self, prompt: "Receipts & Finance"},
        )(),
    )

    args = argparse.Namespace(
        command="review-bot",
        action="outlook-populate-categories",
        thread_id=None,
        prompt=None,
        base_url=None,
        selected_model=None,
        provider="outlook",
        batch_size=1,
        limit=5,
        force=False,
        dry_run=False,
        poll_seconds=0,
        max_passes=0,
        create_draft=False,
        older_than_years=5,
        remove_labels=False,
        delete_unused_labels=False,
        days=7,
        apply_labels=False,
        apply_categories=True,
    )

    exit_code = command_review_bot(args)

    assert exit_code == 0
    assert provider.applied[0][1] == ["MailAssist - Receipts & Finance"]
    assert "MailAssist - Needs Reply" in provider.applied[0][2]
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert any(line["type"] == "outlook_thread_categorized" for line in lines)
    assert lines[-1]["applied_count"] == 1
    assert lines[-1]["message_update_count"] == 1


def test_review_bot_outlook_smoke_test_reads_ready_provider(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.chdir(tmp_path)

    class FakeProvider:
        name = "outlook"

        def readiness_check(self):
            return ProviderReadiness(
                provider="outlook",
                status="ready",
                message="ready",
                account_email="me@example.com",
                can_authenticate=True,
                can_read=True,
                can_create_drafts=True,
            )

        def list_candidate_threads(self):
            return [
                EmailThread(
                    thread_id="conv-1",
                    subject="Question",
                    participants=["sender@example.com", "me@example.com", "client@example.com"],
                    messages=[
                        EmailMessage(
                            message_id="msg-1",
                            sender="sender@example.com",
                            to=["me@example.com", "client@example.com"],
                            sent_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                            text="Can you confirm?",
                        )
                    ],
                    unread=True,
                )
            ]

    monkeypatch.setattr(
        "mailassist.bot_runtime.get_provider_for_settings",
        lambda settings, provider_name: FakeProvider(),
    )

    args = argparse.Namespace(
        command="review-bot",
        action="outlook-smoke-test",
        thread_id=None,
        prompt=None,
        base_url=None,
        selected_model=None,
        provider="outlook",
        batch_size=1,
        limit=5,
        force=False,
        dry_run=False,
        poll_seconds=0,
        max_passes=0,
        create_draft=False,
    )

    exit_code = command_review_bot(args)

    assert exit_code == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert any(line["type"] == "outlook_readiness" and line["ready"] is True for line in lines)
    assert any(line["type"] == "outlook_thread_preview" and line["thread_id"] == "conv-1" for line in lines)
    assert lines[-1]["type"] == "completed"
    assert lines[-1]["thread_count"] == 1
    assert lines[-1]["draft_count"] == 0


def test_review_bot_outlook_smoke_create_draft_requires_thread_id(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.chdir(tmp_path)

    class FakeProvider:
        name = "outlook"

        def readiness_check(self):
            return ProviderReadiness(
                provider="outlook",
                status="ready",
                message="ready",
                account_email="me@example.com",
                can_authenticate=True,
                can_read=True,
                can_create_drafts=True,
            )

        def list_candidate_threads(self):
            return []

    monkeypatch.setattr(
        "mailassist.bot_runtime.get_provider_for_settings",
        lambda settings, provider_name: FakeProvider(),
    )

    args = argparse.Namespace(
        command="review-bot",
        action="outlook-smoke-test",
        thread_id=None,
        prompt=None,
        base_url=None,
        selected_model=None,
        provider="outlook",
        batch_size=1,
        limit=5,
        force=False,
        dry_run=False,
        poll_seconds=0,
        max_passes=0,
        create_draft=True,
    )

    exit_code = command_review_bot(args)

    assert exit_code == 1
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert lines[-1]["type"] == "error"
    assert "--thread-id is required" in lines[-1]["message"]


def test_review_bot_outlook_smoke_can_create_controlled_draft(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.chdir(tmp_path)

    class FakeProvider:
        name = "outlook"

        def __init__(self) -> None:
            self.drafts = []

        def readiness_check(self):
            return ProviderReadiness(
                provider="outlook",
                status="ready",
                message="ready",
                account_email="me@example.com",
                can_authenticate=True,
                can_read=True,
                can_create_drafts=True,
            )

        def list_candidate_threads(self):
            return [
                EmailThread(
                    thread_id="conv-1",
                    subject="Question",
                    participants=["sender@example.com", "me@example.com", "client@example.com"],
                    messages=[
                        EmailMessage(
                            message_id="msg-1",
                            sender="sender@example.com",
                            to=["me@example.com", "client@example.com"],
                            sent_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                            text="Can you confirm?",
                        )
                    ],
                    unread=True,
                )
            ]

        def create_draft(self, draft):
            self.drafts.append(draft)
            assert draft.to == ["sender@example.com"]
            assert draft.cc == ["client@example.com"]
            assert draft.from_address == "me@example.com"
            assert draft.reply_to_message_id == "msg-1"

            class Reference:
                draft_id = "outlook-draft-1"
                thread_id = "conv-1"
                message_id = "msg-1"

            return Reference()

    provider = FakeProvider()
    monkeypatch.setattr(
        "mailassist.bot_runtime.get_provider_for_settings",
        lambda settings, provider_name: provider,
    )

    args = argparse.Namespace(
        command="review-bot",
        action="outlook-smoke-test",
        thread_id="conv-1",
        prompt=None,
        base_url=None,
        selected_model=None,
        provider="outlook",
        batch_size=1,
        limit=5,
        force=False,
        dry_run=False,
        poll_seconds=0,
        max_passes=0,
        create_draft=True,
    )

    exit_code = command_review_bot(args)

    assert exit_code == 0
    assert len(provider.drafts) == 1
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert any(line["type"] == "draft_created" and line["provider_draft_id"] == "outlook-draft-1" for line in lines)
    assert lines[-1]["type"] == "completed"
    assert lines[-1]["draft_count"] == 1


def test_review_bot_watch_loop_uses_polling_settings_and_counts_events(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_BOT_POLL_SECONDS": "15",
        },
    )

    class FakeProvider:
        name = "mock"

    call_count = {"value": 0}
    slept = []

    def fake_get_provider(settings, provider_name):
        assert provider_name == "mock"
        return FakeProvider()

    def fake_run_mock_watch_pass(**kwargs):
        call_count["value"] += 1
        progress_callback = kwargs.get("progress_callback")
        if call_count["value"] == 1 and callable(progress_callback):
            progress_callback(
                {
                    "type": "email_work_started",
                    "provider": "mock",
                    "message_timestamp": "2026-04-24T11:31:00Z",
                }
            )
        if call_count["value"] == 1:
            return [
                {
                    "type": "draft_created",
                    "thread_id": "thread-1",
                    "subject": "First",
                    "classification": "urgent",
                    "provider_draft_id": "draft-1",
                    "message_timestamp": "2026-04-24T11:31:00Z",
                }
            ]
        return [
            {
                "type": "already_handled",
                "thread_id": "thread-1",
                "subject": "First",
                "classification": "urgent",
                "provider_draft_id": "draft-1",
                "message_timestamp": "2026-04-24T11:31:00Z",
            }
        ]

    monkeypatch.setattr("mailassist.bot_runtime.get_provider_for_settings", fake_get_provider)
    monkeypatch.setattr("mailassist.bot_runtime.run_watch_pass", fake_run_mock_watch_pass)
    monkeypatch.setattr("mailassist.bot_runtime.time.sleep", lambda seconds: slept.append(seconds))

    args = argparse.Namespace(
        command="review-bot",
        action="watch-loop",
        thread_id=None,
        prompt=None,
        base_url=None,
        selected_model=None,
        provider="mock",
        batch_size=1,
        limit=10,
        force=False,
        poll_seconds=0,
        max_passes=2,
    )

    exit_code = command_review_bot(args)

    assert exit_code == 0
    assert slept == [15]
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert lines[0]["type"] == "started"
    assert any(line["type"] == "watch_pass_started" and line["pass_number"] == 1 for line in lines)
    completed_pass_lines = [line for line in lines if line["type"] == "watch_pass_completed"]
    assert completed_pass_lines[0]["pass_number"] == 1
    assert completed_pass_lines[0]["poll_seconds"] == 15
    assert completed_pass_lines[0]["scanned_count"] == 1
    assert completed_pass_lines[0]["need_reply_count"] == 1
    assert completed_pass_lines[0]["draft_count"] == 1
    assert completed_pass_lines[0]["caught_up_message_timestamp"] == "2026-04-24T11:31:00Z"
    assert completed_pass_lines[1]["pass_number"] == 2
    assert completed_pass_lines[1]["scanned_count"] == 0
    assert completed_pass_lines[1]["need_reply_count"] == 0
    assert completed_pass_lines[1]["already_handled_count"] == 1
    assert completed_pass_lines[1]["caught_up_message_timestamp"] == "2026-04-24T11:31:00Z"
    progress_lines = [line for line in lines if line["type"] == "email_work_started"]
    assert progress_lines == [
        {
            "type": "email_work_started",
            "action": "watch-loop",
            "run_id": progress_lines[0]["run_id"],
            "timestamp": progress_lines[0]["timestamp"],
            "provider": "mock",
            "message_timestamp": "2026-04-24T11:31:00Z",
        }
    ]
    assert "subject" not in progress_lines[0]
    assert "sender" not in progress_lines[0]
    assert any(line["type"] == "sleeping" and line["poll_seconds"] == 15 for line in lines)
    assert lines[-1]["type"] == "completed"
    assert lines[-1]["completed_passes"] == 2
    assert lines[-1]["draft_count"] == 1
    assert lines[-1]["already_handled_count"] == 1


def test_review_bot_watch_loop_reports_cursor_when_pass_has_no_new_messages(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_BOT_POLL_SECONDS": "15",
        },
    )

    class FakeProvider:
        name = "mock"

    monkeypatch.setattr(
        "mailassist.bot_runtime.get_provider_for_settings",
        lambda settings, provider_name: FakeProvider(),
    )
    monkeypatch.setattr("mailassist.bot_runtime.run_watch_pass", lambda **kwargs: [])
    monkeypatch.setattr(
        "mailassist.bot_runtime.provider_caught_up_message_timestamp",
        lambda root_dir, provider_name: "2026-04-24T11:31:00Z",
    )

    args = argparse.Namespace(
        command="review-bot",
        action="watch-loop",
        thread_id=None,
        prompt=None,
        base_url=None,
        selected_model=None,
        provider="mock",
        batch_size=1,
        limit=10,
        force=False,
        poll_seconds=0,
        max_passes=1,
    )

    exit_code = command_review_bot(args)

    assert exit_code == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    completed_pass = next(line for line in lines if line["type"] == "watch_pass_completed")
    assert completed_pass["scanned_count"] == 0
    assert completed_pass["caught_up_message_timestamp"] == "2026-04-24T11:31:00Z"


def test_scan_lock_wait_seconds_prefers_manual_runs(monkeypatch) -> None:
    monkeypatch.delenv("MAILASSIST_SCAN_LOCK_WAIT_SECONDS", raising=False)

    assert _scan_lock_wait_seconds(scan_source="service") == 0.0
    assert _scan_lock_wait_seconds(scan_source="manual") == float(DEFAULT_MANUAL_SCAN_LOCK_WAIT_SECONDS)

    monkeypatch.setenv("MAILASSIST_SCAN_LOCK_WAIT_SECONDS", "12.5")
    assert _scan_lock_wait_seconds(scan_source="manual") == 12.5
    assert _scan_lock_wait_seconds(scan_source="service") == 12.5


def test_review_bot_service_watch_loop_exits_when_stop_flag_exists(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MAILASSIST_SCAN_SOURCE", "service")
    stop_flag = tmp_path / "data" / "control" / "service-stop.flag"
    stop_flag.parent.mkdir(parents=True)
    stop_flag.write_text("stop requested", encoding="utf-8")

    class FakeProvider:
        name = "mock"

    monkeypatch.setattr(
        "mailassist.bot_runtime.get_provider_for_settings",
        lambda settings, provider_name: FakeProvider(),
    )

    def fail_if_scanned(**kwargs):
        raise AssertionError("service stop flag should prevent scan passes")

    monkeypatch.setattr("mailassist.bot_runtime.run_watch_pass", fail_if_scanned)

    args = argparse.Namespace(
        command="review-bot",
        action="watch-loop",
        thread_id=None,
        prompt=None,
        base_url=None,
        selected_model=None,
        provider="mock",
        batch_size=1,
        limit=10,
        force=False,
        poll_seconds=0,
        max_passes=0,
    )

    exit_code = command_review_bot(args)

    assert exit_code == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert any(line["type"] == "stop_requested" for line in lines)
    assert not any(line["type"] == "watch_pass_started" for line in lines)
    assert lines[-1]["type"] == "completed"
    assert lines[-1]["completed_passes"] == 0


def test_review_bot_watch_loop_counts_generation_failures_without_catching_up(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.chdir(tmp_path)

    class FakeProvider:
        name = "mock"

    monkeypatch.setattr(
        "mailassist.bot_runtime.get_provider_for_settings",
        lambda settings, provider_name: FakeProvider(),
    )
    monkeypatch.setattr(
        "mailassist.bot_runtime.run_watch_pass",
        lambda **kwargs: [
            {
                "type": "generation_failed",
                "provider": "mock",
                "classification": "reply_needed",
                "generation_model": "fallback",
                "generation_error": "Unable to reach Ollama.",
                "message_timestamp": "2026-04-24T11:31:00Z",
            }
        ],
    )
    monkeypatch.setattr(
        "mailassist.bot_runtime.provider_caught_up_message_timestamp",
        lambda root_dir, provider_name: "",
    )

    args = argparse.Namespace(
        command="review-bot",
        action="watch-loop",
        thread_id=None,
        prompt=None,
        base_url=None,
        selected_model=None,
        provider="mock",
        batch_size=1,
        limit=10,
        force=False,
        poll_seconds=1,
        max_passes=1,
    )

    exit_code = command_review_bot(args)

    assert exit_code == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    completed_pass = next(line for line in lines if line["type"] == "watch_pass_completed")
    assert completed_pass["generation_failed_count"] == 1
    assert completed_pass["caught_up_message_timestamp"] == ""


def test_review_bot_watch_loop_emits_failed_and_retry_events(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_BOT_POLL_SECONDS": "9",
        },
    )

    class FakeProvider:
        name = "mock"

    call_count = {"value": 0}
    slept = []

    monkeypatch.setattr(
        "mailassist.bot_runtime.get_provider_for_settings",
        lambda settings, provider_name: FakeProvider(),
    )

    def fake_run_mock_watch_pass(**kwargs):
        call_count["value"] += 1
        if call_count["value"] == 1:
            raise RuntimeError("temporary provider failure")
        return []

    monkeypatch.setattr("mailassist.bot_runtime.run_watch_pass", fake_run_mock_watch_pass)
    monkeypatch.setattr("mailassist.bot_runtime.time.sleep", lambda seconds: slept.append(seconds))

    args = argparse.Namespace(
        command="review-bot",
        action="watch-loop",
        thread_id=None,
        prompt=None,
        base_url=None,
        selected_model=None,
        provider="mock",
        batch_size=1,
        limit=10,
        force=False,
        poll_seconds=0,
        max_passes=2,
    )

    exit_code = command_review_bot(args)

    assert exit_code == 0
    assert slept == [9]
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert any(line["type"] == "failed_pass" and "temporary provider failure" in line["message"] for line in lines)
    assert any(line["type"] == "retry_scheduled" and line["poll_seconds"] == 9 for line in lines)
    assert lines[-1]["failed_pass_count"] == 1
    assert lines[-1]["retry_count"] == 1
