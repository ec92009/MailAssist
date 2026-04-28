from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from mailassist.live_filters import WatcherFilter, thread_passes_filter
from mailassist.models import DraftRecord, EmailMessage, EmailThread, ProviderDraftReference
from mailassist.providers.base import DraftProvider, ProviderReadiness
from mailassist.rich_text import html_to_plain_text


class OutlookGraphAuthError(RuntimeError):
    def __init__(self, message: str, *, requires_admin_consent: bool = False) -> None:
        super().__init__(message)
        self.requires_admin_consent = requires_admin_consent


class OutlookGraphClient(Protocol):
    def authenticate(self) -> str:
        ...

    def get_me(self) -> dict[str, Any]:
        ...

    def list_messages(self) -> list[dict[str, Any]]:
        ...

    def create_reply_draft(self, *, message_id: str, draft: DraftRecord) -> dict[str, Any]:
        ...


@dataclass
class InMemoryOutlookGraphClient:
    me: dict[str, Any]
    messages: list[dict[str, Any]]
    auth_error: OutlookGraphAuthError | None = None
    created_drafts: list[dict[str, Any]] = field(default_factory=list)

    def authenticate(self) -> str:
        if self.auth_error is not None:
            raise self.auth_error
        return "ok"

    def get_me(self) -> dict[str, Any]:
        self.authenticate()
        return self.me

    def list_messages(self) -> list[dict[str, Any]]:
        self.authenticate()
        return list(self.messages)

    def create_reply_draft(self, *, message_id: str, draft: DraftRecord) -> dict[str, Any]:
        self.authenticate()
        content = draft.body_html or draft.body
        created = {
            "id": f"outlook-draft-{len(self.created_drafts) + 1}",
            "conversationId": draft.thread_id,
            "replyToMessageId": message_id,
            "subject": draft.subject,
            "body": {
                "contentType": "HTML" if draft.body_html else "Text",
                "content": content,
            },
            "toRecipients": [_graph_recipient(address) for address in draft.to],
            "ccRecipients": [_graph_recipient(address) for address in draft.cc],
            "bccRecipients": [_graph_recipient(address) for address in draft.bcc],
            "isDraft": True,
        }
        self.created_drafts.append(created)
        return created


class OutlookProvider(DraftProvider):
    name = "outlook"

    def __init__(
        self,
        *,
        client_id: str = "",
        tenant_id: str = "",
        redirect_uri: str = "",
        graph_client: OutlookGraphClient | None = None,
    ) -> None:
        self.client_id = client_id.strip()
        self.tenant_id = tenant_id.strip()
        self.redirect_uri = redirect_uri.strip()
        self.graph_client = graph_client

    def authenticate(self) -> str:
        if self.graph_client is None:
            raise NotImplementedError(
                "Outlook authentication is not implemented yet. The provider contract is ready for Microsoft Graph."
            )
        return self.graph_client.authenticate()

    def get_account_email(self) -> str | None:
        if self.graph_client is None:
            return None
        return _account_email_from_me(self.graph_client.get_me())

    def readiness_check(self) -> ProviderReadiness:
        if not self.client_id:
            return ProviderReadiness(
                provider=self.name,
                status="not_configured",
                message="Outlook is missing a Microsoft Graph client id.",
                can_authenticate=False,
                can_read=False,
                can_create_drafts=False,
                details={
                    "tenant_id": self.tenant_id,
                    "redirect_uri": self.redirect_uri,
                },
            )

        if self.graph_client is not None:
            return self._graph_readiness_check()

        return ProviderReadiness(
            provider=self.name,
            status="blocked",
            message=(
                "Outlook Graph support is not implemented yet. The next step is Microsoft Graph auth, "
                "mailbox read, and draft creation against mocks or a developer tenant."
            ),
            can_authenticate=False,
            can_read=False,
            can_create_drafts=False,
            requires_admin_consent=True,
            details=self._graph_details(),
        )

    def _graph_readiness_check(self) -> ProviderReadiness:
        try:
            account_email = self.get_account_email()
            self.graph_client.list_messages()
        except OutlookGraphAuthError as exc:
            return ProviderReadiness(
                provider=self.name,
                status="auth_blocked" if exc.requires_admin_consent else "auth_failed",
                message=str(exc),
                can_authenticate=False,
                can_read=False,
                can_create_drafts=False,
                requires_admin_consent=exc.requires_admin_consent,
                details=self._graph_details(),
            )
        except Exception as exc:
            return ProviderReadiness(
                provider=self.name,
                status="blocked",
                message=str(exc),
                can_authenticate=False,
                can_read=False,
                can_create_drafts=False,
                details=self._graph_details(),
            )

        return ProviderReadiness(
            provider=self.name,
            status="ready",
            message="Outlook Graph provider is ready.",
            account_email=account_email,
            can_authenticate=True,
            can_read=True,
            can_create_drafts=True,
            requires_admin_consent=False,
            details=self._graph_details(),
        )

    def _graph_details(self) -> dict[str, str]:
        return {
            "client_id": self.client_id,
            "tenant_id": self.tenant_id,
            "redirect_uri": self.redirect_uri,
        }

    def list_actionable_threads(self, watcher_filter: WatcherFilter) -> list[EmailThread]:
        now = datetime.now(timezone.utc)
        return [
            thread
            for thread in self.list_candidate_threads(watcher_filter)
            if thread_passes_filter(thread, watcher_filter, now=now)[0]
        ]

    def list_candidate_threads(self, watcher_filter: WatcherFilter | None = None) -> list[EmailThread]:
        if self.graph_client is None:
            raise NotImplementedError(
                "Outlook thread listing is planned next. The provider contract is ready for Microsoft Graph."
            )
        return _graph_messages_to_email_threads(self.graph_client.list_messages())

    def create_draft(self, draft: DraftRecord) -> ProviderDraftReference:
        if self.graph_client is None:
            raise NotImplementedError(
                "Outlook support is planned next. The provider interface is ready for it."
            )
        source_message_id = _latest_message_id_for_conversation(
            self.graph_client.list_messages(),
            draft.thread_id,
        )
        if not source_message_id:
            raise RuntimeError(f"Outlook source message not found for conversation {draft.thread_id}")
        created = self.graph_client.create_reply_draft(message_id=source_message_id, draft=draft)
        return ProviderDraftReference(
            draft_id=str(created.get("id", "")),
            thread_id=str(created.get("conversationId", draft.thread_id)),
            message_id=str(created.get("replyToMessageId", source_message_id)),
        )


def _account_email_from_me(payload: dict[str, Any]) -> str | None:
    for key in ("mail", "userPrincipalName"):
        value = str(payload.get(key, "")).strip().lower()
        if value and "@" in value:
            return value
    return None


def _graph_messages_to_email_threads(messages: list[dict[str, Any]]) -> list[EmailThread]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for message in messages:
        conversation_id = str(message.get("conversationId") or message.get("id") or "").strip()
        if conversation_id:
            grouped.setdefault(conversation_id, []).append(message)

    threads: list[EmailThread] = []
    for conversation_id, raw_messages in grouped.items():
        ordered = sorted(raw_messages, key=_message_sort_key)
        email_messages: list[EmailMessage] = []
        participants: list[str] = []
        subject = ""
        for raw in ordered:
            sender = _recipient_address(raw.get("from", {}))
            recipients = [
                address
                for address in [
                    *_recipient_addresses(raw.get("toRecipients", [])),
                    *_recipient_addresses(raw.get("ccRecipients", [])),
                    *_recipient_addresses(raw.get("bccRecipients", [])),
                ]
                if address
            ]
            for participant in [sender, *recipients]:
                if participant and participant not in participants:
                    participants.append(participant)
            if not subject:
                subject = str(raw.get("subject", "")).strip()
            email_messages.append(
                EmailMessage(
                    message_id=str(raw.get("id", "")),
                    sender=sender,
                    to=recipients,
                    sent_at=str(raw.get("receivedDateTime", "") or raw.get("sentDateTime", "")),
                    text=_message_text(raw),
                )
            )
        latest = ordered[-1]
        threads.append(
            EmailThread(
                thread_id=conversation_id,
                subject=subject or "(no subject)",
                participants=participants,
                messages=email_messages,
                unread=not bool(latest.get("isRead", False)),
            )
        )
    return threads


def _message_sort_key(message: dict[str, Any]) -> str:
    return str(message.get("receivedDateTime", "") or message.get("sentDateTime", "") or "")


def _message_text(message: dict[str, Any]) -> str:
    body = message.get("body", {})
    content = str(body.get("content", ""))
    content_type = str(body.get("contentType", "")).lower()
    if content.strip():
        if content_type == "html":
            return html_to_plain_text(content)
        return content.strip()
    return str(message.get("bodyPreview", "")).strip()


def _recipient_address(recipient: dict[str, Any]) -> str:
    email_address = recipient.get("emailAddress", {}) if isinstance(recipient, dict) else {}
    return str(email_address.get("address", "")).strip().lower()


def _recipient_addresses(recipients: list[dict[str, Any]]) -> list[str]:
    return [address for recipient in recipients if (address := _recipient_address(recipient))]


def _graph_recipient(address: str) -> dict[str, Any]:
    return {"emailAddress": {"address": address}}


def _latest_message_id_for_conversation(messages: list[dict[str, Any]], conversation_id: str) -> str:
    matching = [
        message
        for message in messages
        if str(message.get("conversationId", "")).strip() == conversation_id
    ]
    if not matching:
        return ""
    latest = sorted(matching, key=_message_sort_key)[-1]
    return str(latest.get("id", "")).strip()
