import json
from email import message_from_bytes
from types import ModuleType
from pathlib import Path

from mailassist.models import DraftRecord
from mailassist.providers.gmail import (
    GMAIL_SCOPES,
    GmailProvider,
    _gmail_signature_to_text,
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


def test_gmail_scopes_include_compose_and_readonly() -> None:
    assert "https://www.googleapis.com/auth/gmail.compose" in GMAIL_SCOPES
    assert "https://www.googleapis.com/auth/gmail.readonly" in GMAIL_SCOPES
    assert "https://www.googleapis.com/auth/gmail.settings.basic" in GMAIL_SCOPES


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
