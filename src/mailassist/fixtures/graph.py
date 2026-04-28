from __future__ import annotations

from typing import Any

from mailassist.providers.outlook import InMemoryOutlookGraphClient, OutlookGraphAuthError


def graph_me_fixture() -> dict[str, Any]:
    return {
        "id": "user-magali-example",
        "displayName": "Magali Example",
        "mail": "magali@example-cpa.com",
        "userPrincipalName": "magali@example-cpa.com",
    }


def graph_messages_fixture() -> list[dict[str, Any]]:
    return [
        {
            "id": "msg-action-1",
            "conversationId": "conv-action",
            "subject": "Vendor W-9 confirmation",
            "from": {"emailAddress": {"address": "vendor@example.com", "name": "Vendor Ops"}},
            "toRecipients": [_recipient("magali@example-cpa.com")],
            "ccRecipients": [],
            "bccRecipients": [],
            "receivedDateTime": "2026-04-28T15:05:00Z",
            "isRead": False,
            "body": {
                "contentType": "html",
                "content": "<p>Can you confirm whether we should use the new W-9 for May invoices?</p>",
            },
            "bodyPreview": "Can you confirm whether we should use the new W-9 for May invoices?",
        },
        {
            "id": "msg-action-2",
            "conversationId": "conv-action",
            "subject": "Vendor W-9 confirmation",
            "from": {"emailAddress": {"address": "vendor@example.com", "name": "Vendor Ops"}},
            "toRecipients": [_recipient("magali@example-cpa.com")],
            "ccRecipients": [_recipient("bookkeeper@example-cpa.com")],
            "bccRecipients": [],
            "receivedDateTime": "2026-04-28T15:09:00Z",
            "isRead": False,
            "body": {
                "contentType": "text",
                "content": "Following up so we can close this before payroll.",
            },
            "bodyPreview": "Following up so we can close this before payroll.",
        },
        {
            "id": "msg-newsletter",
            "conversationId": "conv-newsletter",
            "subject": "Weekly tax update",
            "from": {"emailAddress": {"address": "updates@example.com", "name": "Updates"}},
            "toRecipients": [_recipient("magali@example-cpa.com")],
            "ccRecipients": [],
            "bccRecipients": [],
            "receivedDateTime": "2026-04-28T14:50:00Z",
            "isRead": True,
            "body": {
                "contentType": "html",
                "content": "<p>This week's tax news digest.</p>",
            },
            "bodyPreview": "This week's tax news digest.",
        },
    ]


def build_graph_fixture_client() -> InMemoryOutlookGraphClient:
    return InMemoryOutlookGraphClient(
        me=graph_me_fixture(),
        messages=graph_messages_fixture(),
    )


def build_graph_admin_consent_blocked_client() -> InMemoryOutlookGraphClient:
    return InMemoryOutlookGraphClient(
        me=graph_me_fixture(),
        messages=graph_messages_fixture(),
        auth_error=OutlookGraphAuthError(
            "Microsoft Graph authorization requires tenant admin consent.",
            requires_admin_consent=True,
        ),
    )


def _recipient(address: str) -> dict[str, Any]:
    return {"emailAddress": {"address": address}}
