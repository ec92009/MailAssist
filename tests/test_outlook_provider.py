from mailassist.fixtures.graph import (
    build_graph_admin_consent_blocked_client,
    build_graph_fixture_client,
)
from mailassist.live_filters import WatcherFilter
from mailassist.models import DraftRecord
from mailassist.providers.outlook import OutlookProvider


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
