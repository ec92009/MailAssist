import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from mailassist.fixtures.graph import (
    build_graph_admin_consent_blocked_client,
    build_graph_fixture_client,
)
from mailassist.live_filters import WatcherFilter
from mailassist.models import DraftRecord
from mailassist.providers.outlook import (
    MicrosoftGraphClient,
    OUTLOOK_GRAPH_SCOPES,
    OutlookGraphAuthError,
    OutlookGraphTokenStore,
    OutlookProvider,
)


def _provider(graph_client=None) -> OutlookProvider:
    return OutlookProvider(
        client_id="client-123",
        tenant_id="tenant-456",
        redirect_uri="http://localhost:8765/outlook/callback",
        graph_client=graph_client or build_graph_fixture_client(),
    )


def test_outlook_graph_readiness_uses_me_account_email() -> None:
    provider = _provider()

    readiness = provider.readiness_check()

    assert readiness.ready is True
    assert readiness.status == "ready"
    assert readiness.account_email == "magali@example-cpa.com"
    assert readiness.can_authenticate is True
    assert readiness.can_read is True
    assert readiness.can_create_drafts is True
    assert readiness.requires_admin_consent is False


def test_outlook_graph_readiness_reports_admin_consent_blocker() -> None:
    provider = _provider(build_graph_admin_consent_blocked_client())

    readiness = provider.readiness_check()

    assert readiness.ready is False
    assert readiness.status == "auth_blocked"
    assert readiness.requires_admin_consent is True
    assert "admin consent" in readiness.message.lower()


def test_outlook_graph_messages_group_into_email_threads() -> None:
    provider = _provider()

    threads = provider.list_candidate_threads()

    assert [thread.thread_id for thread in threads] == ["conv-action", "conv-newsletter"]
    action = threads[0]
    assert action.subject == "Vendor W-9 confirmation"
    assert action.unread is True
    assert action.participants == [
        "vendor@example.com",
        "magali@example-cpa.com",
        "bookkeeper@example-cpa.com",
    ]
    assert len(action.messages) == 2
    assert action.messages[0].text == "Can you confirm whether we should use the new W-9 for May invoices?"
    assert action.messages[1].text == "Following up so we can close this before payroll."


def test_outlook_actionable_threads_apply_watcher_filter() -> None:
    provider = _provider()

    threads = provider.list_actionable_threads(
        WatcherFilter(unread_only=True, max_age_seconds=None)
    )

    assert [thread.thread_id for thread in threads] == ["conv-action"]


def test_outlook_create_draft_maps_to_graph_reply_payload() -> None:
    graph_client = build_graph_fixture_client()
    provider = _provider(graph_client)
    draft = DraftRecord(
        draft_id="draft-1",
        thread_id="conv-action",
        provider="outlook",
        subject="Re: Vendor W-9 confirmation",
        body="I am reviewing this.",
        body_html="<p>I am reviewing this.</p>",
        model="gemma4:31b",
        to=["vendor@example.com"],
        cc=["bookkeeper@example-cpa.com"],
    )

    reference = provider.create_draft(draft)

    assert reference.draft_id == "outlook-draft-1"
    assert reference.thread_id == "conv-action"
    assert reference.message_id == "msg-action-2"
    created = graph_client.created_drafts[0]
    assert created["replyToMessageId"] == "msg-action-2"
    assert created["body"]["contentType"] == "HTML"
    assert created["body"]["content"] == "<p>I am reviewing this.</p>"
    assert created["toRecipients"] == [{"emailAddress": {"address": "vendor@example.com"}}]
    assert created["ccRecipients"] == [
        {"emailAddress": {"address": "bookkeeper@example-cpa.com"}}
    ]


def test_outlook_replace_thread_categories_preserves_non_mailassist_categories() -> None:
    graph_client = build_graph_fixture_client()
    graph_client.messages[0]["categories"] = ["Pinned", "MailAssist - Needs Action"]
    graph_client.messages[1]["categories"] = ["MailAssist - Needs Reply"]
    provider = _provider(graph_client)

    updated_count = provider.replace_thread_categories(
        "conv-action",
        add_categories=["MailAssist - Receipts & Finance"],
        remove_categories=["MailAssist - Needs Action", "MailAssist - Needs Reply"],
    )

    assert updated_count == 2
    assert graph_client.messages[0]["categories"] == ["Pinned", "MailAssist - Receipts & Finance"]
    assert graph_client.messages[1]["categories"] == ["MailAssist - Receipts & Finance"]


def test_outlook_graph_scopes_do_not_request_send_permission() -> None:
    assert "Mail.ReadWrite" in OUTLOOK_GRAPH_SCOPES
    assert "Mail.Send" not in OUTLOOK_GRAPH_SCOPES


def test_graph_token_store_saves_expiry_metadata(tmp_path: Path) -> None:
    token_file = tmp_path / "secrets" / "outlook-token.json"
    saved = OutlookGraphTokenStore(token_file).save(
        {"access_token": "access-1", "refresh_token": "refresh-1", "expires_in": 3600}
    )

    payload = json.loads(token_file.read_text(encoding="utf-8"))
    assert payload["access_token"] == "access-1"
    assert payload["refresh_token"] == "refresh-1"
    assert payload["expires_at"] == saved["expires_at"]


def test_real_graph_client_device_flow_persists_token(tmp_path: Path) -> None:
    requests: list[tuple[str, str, dict[str, str], bytes | None]] = []
    prompts: list[str] = []

    def transport(method: str, url: str, headers: dict[str, str], data: bytes | None):
        requests.append((method, url, headers, data))
        if url.endswith("/devicecode"):
            form = parse_qs((data or b"").decode("utf-8"))
            assert form["client_id"] == ["client-123"]
            assert "Mail.ReadWrite" in form["scope"][0]
            assert "offline_access" in form["scope"][0]
            return {
                "device_code": "device-123",
                "message": "Open https://microsoft.com/devicelogin and enter ABCD.",
                "interval": 1,
                "expires_in": 60,
            }
        if url.endswith("/token"):
            form = parse_qs((data or b"").decode("utf-8"))
            assert form["grant_type"] == ["urn:ietf:params:oauth:grant-type:device_code"]
            assert form["device_code"] == ["device-123"]
            return {
                "access_token": "access-123",
                "refresh_token": "refresh-123",
                "expires_in": 3600,
            }
        raise AssertionError(url)

    client = MicrosoftGraphClient(
        client_id="client-123",
        tenant_id="tenant-456",
        token_file=tmp_path / "outlook-token.json",
        auth_prompt=prompts.append,
        transport=transport,
        sleep=lambda _seconds: None,
    )

    assert client.authenticate() == "ok"

    assert prompts == ["Open https://microsoft.com/devicelogin and enter ABCD."]
    token = json.loads((tmp_path / "outlook-token.json").read_text(encoding="utf-8"))
    assert token["access_token"] == "access-123"
    assert token["refresh_token"] == "refresh-123"
    assert [urlparse(request[1]).path for request in requests] == [
        "/tenant-456/oauth2/v2.0/devicecode",
        "/tenant-456/oauth2/v2.0/token",
    ]


def test_real_graph_client_uses_refresh_token_for_me_request(tmp_path: Path) -> None:
    token_file = tmp_path / "outlook-token.json"
    token_file.write_text(
        json.dumps({"refresh_token": "refresh-123", "expires_at": 1}),
        encoding="utf-8",
    )

    def transport(method: str, url: str, headers: dict[str, str], data: bytes | None):
        if url.endswith("/token"):
            form = parse_qs((data or b"").decode("utf-8"))
            assert form["grant_type"] == ["refresh_token"]
            assert form["refresh_token"] == ["refresh-123"]
            return {
                "access_token": "access-new",
                "refresh_token": "refresh-new",
                "expires_in": 3600,
            }
        if url.endswith("/me"):
            assert headers["Authorization"] == "Bearer access-new"
            return {"mail": "magali@example-cpa.com"}
        raise AssertionError(url)

    client = MicrosoftGraphClient(
        client_id="client-123",
        tenant_id="tenant-456",
        token_file=token_file,
        transport=transport,
    )

    assert client.get_me()["mail"] == "magali@example-cpa.com"


def test_real_graph_client_explains_invalid_grant_refresh_failure(tmp_path: Path) -> None:
    token_file = tmp_path / "outlook-token.json"
    token_file.write_text(
        json.dumps({"refresh_token": "refresh-123", "expires_at": 1}),
        encoding="utf-8",
    )

    def transport(method: str, url: str, headers: dict[str, str], data: bytes | None):
        if url.endswith("/token"):
            return {"error": "invalid_grant"}
        raise AssertionError(url)

    client = MicrosoftGraphClient(
        client_id="client-123",
        tenant_id="tenant-456",
        token_file=token_file,
        transport=transport,
    )

    try:
        client.get_me()
    except OutlookGraphAuthError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected invalid_grant to require Outlook re-auth.")

    assert "Outlook sign-in expired or was revoked" in message
    assert "Run Outlook setup/auth again" in message
