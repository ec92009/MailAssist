import json
from email import message_from_bytes
from email.policy import default
from types import ModuleType
from pathlib import Path

from mailassist.live_filters import WatcherFilter
from mailassist.models import DraftRecord
from mailassist.providers.gmail import (
    GMAIL_SCOPES,
    GmailProvider,
    _build_gmail_thread_query,
    _gmail_signature_to_text,
    _has_child_label,
    _is_label_cleanup_excluded,
    _select_send_as_entry,
)


def test_gmail_provider_includes_recipients_in_raw_draft(monkeypatch, tmp_path: Path) -> None:
    created_body = {}

    class FakeDrafts:
        def create(self, *, userId, body):
            created_body.update(body)
            return self

        def execute(self):
            return {"id": "draft-1", "message": {"id": "msg-1", "threadId": "thread-1"}}

    class FakeUsers:
        def drafts(self):
            return FakeDrafts()

    class FakeService:
        def users(self):
            return FakeUsers()

    class FakeCreds:
        valid = True
        def has_scopes(self, scopes):
            return set(scopes).issubset(set(GMAIL_SCOPES))

    def fake_credentials_from_file(path, scopes):
        return FakeCreds()

    def fake_build(*args, **kwargs):
        return FakeService()

    import sys

    module_names = (
        "google",
        "google.auth",
        "google.auth.transport",
        "google.oauth2",
        "google_auth_oauthlib",
        "googleapiclient",
    )
    for name in module_names:
        monkeypatch.setitem(sys.modules, name, ModuleType(name))

    requests_module = ModuleType("google.auth.transport.requests")
    requests_module.Request = object
    credentials_module = ModuleType("google.oauth2.credentials")
    credentials_module.Credentials = type(
        "Credentials",
        (),
        {"from_authorized_user_file": staticmethod(fake_credentials_from_file)},
    )
    flow_module = ModuleType("google_auth_oauthlib.flow")
    flow_module.InstalledAppFlow = object
    discovery_module = ModuleType("googleapiclient.discovery")
    discovery_module.build = fake_build

    monkeypatch.setitem(sys.modules, "google.auth.transport.requests", requests_module)
    monkeypatch.setitem(sys.modules, "google.oauth2.credentials", credentials_module)
    monkeypatch.setitem(sys.modules, "google_auth_oauthlib.flow", flow_module)
    monkeypatch.setitem(sys.modules, "googleapiclient.discovery", discovery_module)

    token_file = tmp_path / "token.json"
    token_file.write_text(json.dumps({"scopes": GMAIL_SCOPES}), encoding="utf-8")
    provider = GmailProvider(tmp_path / "credentials.json", token_file)

    provider.create_draft(
        DraftRecord(
            draft_id="draft-local",
            thread_id="thread-local",
            provider="gmail",
            subject="Re: Test",
            body="Draft body",
            model="mock",
            to=["sender@example.com"],
            cc=["cc@example.com"],
            bcc=["bcc@example.com"],
        )
    )

    raw = created_body["message"]["raw"]
    import base64

    parsed = message_from_bytes(base64.urlsafe_b64decode(raw.encode("utf-8")))
    assert parsed["to"] == "sender@example.com"
    assert parsed["cc"] == "cc@example.com"
    assert parsed["bcc"] == "bcc@example.com"
    assert parsed["subject"] == "Re: Test"


def test_gmail_label_cleanup_excludes_archive_labels() -> None:
    assert _is_label_cleanup_excluded("[Mailbox]/Archive") is True
    assert _is_label_cleanup_excluded("Archive") is True
    assert _is_label_cleanup_excluded("[Mailbox]/Receipts") is False


def test_unused_label_cleanup_preserves_container_labels() -> None:
    names = {"[Mailbox]", "[Mailbox]/Receipts", "Old Empty"}
    assert _has_child_label("[Mailbox]", names) is True
    assert _has_child_label("[Mailbox]/Receipts", names) is False
    assert _has_child_label("Old Empty", names) is False


def test_unused_label_cleanup_uses_archive_exclusion() -> None:
    assert _is_label_cleanup_excluded("[Mailbox]/Archive") is True


def test_gmail_provider_creates_multipart_draft_when_html_body_present(
    monkeypatch, tmp_path: Path
) -> None:
    created_body = {}

    class FakeDrafts:
        def create(self, *, userId, body):
            created_body.update(body)
            return self

        def execute(self):
            return {"id": "draft-1", "message": {"id": "msg-1", "threadId": "thread-1"}}

    class FakeUsers:
        def drafts(self):
            return FakeDrafts()

    class FakeService:
        def users(self):
            return FakeUsers()

    provider = GmailProvider(tmp_path / "credentials.json", tmp_path / "token.json")
    monkeypatch.setattr(provider, "_credentials", lambda **kwargs: object())
    monkeypatch.setattr(
        provider,
        "_load_google_modules",
        lambda: (object, object, object, lambda *args, **kwargs: FakeService()),
    )

    provider.create_draft(
        DraftRecord(
            draft_id="draft-local",
            thread_id="thread-local",
            provider="gmail",
            subject="Re: Test",
            body="Plain body",
            body_html="<p><b>Rich</b> body</p><script>alert(1)</script>",
            model="mock",
            to=["sender@example.com"],
        )
    )

    import base64

    parsed = message_from_bytes(
        base64.urlsafe_b64decode(created_body["message"]["raw"].encode("utf-8")),
        policy=default,
    )
    assert parsed.is_multipart()
    parts = list(parsed.iter_parts())
    assert [part.get_content_type() for part in parts] == ["text/plain", "text/html"]
    assert parts[0].get_content().strip() == "Plain body"
    assert "<b>Rich</b>" in parts[1].get_content()
    assert "script" not in parts[1].get_content()


def test_gmail_scopes_include_compose_and_readonly() -> None:
    assert "https://www.googleapis.com/auth/gmail.compose" in GMAIL_SCOPES
    assert "https://www.googleapis.com/auth/gmail.readonly" in GMAIL_SCOPES
    assert "https://www.googleapis.com/auth/gmail.settings.basic" in GMAIL_SCOPES


def test_gmail_provider_can_replace_thread_labels(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    class FakeThreads:
        def modify(self, *, userId, id, body):
            captured.update({"userId": userId, "id": id, "body": body})
            return self

        def execute(self):
            return {}

    class FakeUsers:
        def threads(self):
            return FakeThreads()

    class FakeService:
        def users(self):
            return FakeUsers()

    provider = GmailProvider(tmp_path / "credentials.json", tmp_path / "token.json")
    monkeypatch.setattr(provider, "_credentials", lambda **kwargs: object())
    monkeypatch.setattr(
        provider,
        "_load_google_modules",
        lambda: (object, object, object, lambda *args, **kwargs: FakeService()),
    )

    provider.replace_thread_labels("thread-1", ["label-new"], ["label-old"])

    assert captured == {
        "userId": "me",
        "id": "thread-1",
        "body": {"addLabelIds": ["label-new"], "removeLabelIds": ["label-old"]},
    }


def test_gmail_signature_html_is_sanitized_to_plain_text() -> None:
    html = "<div>Best regards,<br>Example&nbsp;User</div><div>user@example.com</div>"

    assert _gmail_signature_to_text(html) == "Best regards,\nExample User\nuser@example.com"


def test_gmail_signature_prefers_default_send_as_entry() -> None:
    selected = _select_send_as_entry(
        [
            {"sendAsEmail": "alias@example.com", "signature": "Alias"},
            {"sendAsEmail": "main@example.com", "signature": "Main", "isDefault": True},
        ]
    )

    assert selected["sendAsEmail"] == "main@example.com"


def test_gmail_thread_query_reflects_unread_and_time_window() -> None:
    query = _build_gmail_thread_query(
        WatcherFilter(unread_only=True, max_age_seconds=7 * 24 * 60 * 60)
    )

    assert query == "is:unread newer_than:7d"


def test_gmail_provider_lists_actionable_threads(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    class FakeThreadsApi:
        def list(self, **kwargs):
            captured["list_kwargs"] = kwargs
            return self

        def get(self, *, userId, id, format):
            assert userId == "me"
            assert id == "thread-1"
            assert format == "full"
            return self

        def execute(self):
            if "list_kwargs" in captured and "thread_payload" not in captured:
                captured["thread_payload"] = True
                return {"threads": [{"id": "thread-1"}]}
            return {
                "id": "thread-1",
                "messages": [
                    {
                        "id": "msg-1",
                        "internalDate": "1777284000000",
                        "labelIds": ["INBOX", "UNREAD"],
                        "snippet": "Can you review this?",
                        "payload": {
                            "headers": [
                                {"name": "From", "value": "Sender <sender@example.com>"},
                                {"name": "To", "value": "You <you@example.com>"},
                                {"name": "Subject", "value": "Need review"},
                            ],
                            "mimeType": "text/plain",
                            "body": {"data": "Q2FuIHlvdSByZXZpZXcgdGhpcz8="},
                        },
                    }
                ],
            }

    class FakeUsers:
        def threads(self):
            return FakeThreadsApi()

    class FakeService:
        def users(self):
            return FakeUsers()

    provider = GmailProvider(tmp_path / "credentials.json", tmp_path / "token.json")
    monkeypatch.setattr(provider, "_credentials", lambda **kwargs: object())
    monkeypatch.setattr(
        provider,
        "_load_google_modules",
        lambda: (object, object, object, lambda *args, **kwargs: FakeService()),
    )

    threads = provider.list_actionable_threads(
        WatcherFilter(unread_only=True, max_age_seconds=7 * 24 * 60 * 60)
    )

    assert captured["list_kwargs"]["labelIds"] == ["INBOX"]
    assert captured["list_kwargs"]["q"] == "is:unread newer_than:7d"
    assert len(threads) == 1
    assert threads[0].thread_id == "thread-1"
    assert threads[0].subject == "Need review"
    assert threads[0].unread is True
    assert threads[0].participants == ["sender@example.com", "you@example.com"]
    assert threads[0].messages[0].text == "Can you review this?"
