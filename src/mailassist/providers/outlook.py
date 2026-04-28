from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.error import HTTPError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

from mailassist.live_filters import WatcherFilter, thread_passes_filter
from mailassist.models import DraftRecord, EmailMessage, EmailThread, ProviderDraftReference
from mailassist.providers.base import DraftProvider, ProviderReadiness
from mailassist.rich_text import html_to_plain_text

OUTLOOK_GRAPH_SCOPES = [
    "offline_access",
    "User.Read",
    "Mail.ReadWrite",
]


class OutlookGraphAuthError(RuntimeError):
    def __init__(self, message: str, *, requires_admin_consent: bool = False) -> None:
        super().__init__(message)
        self.requires_admin_consent = requires_admin_consent


class OutlookGraphHttpError(RuntimeError):
    pass


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


@dataclass
class OutlookGraphTokenStore:
    token_file: Path

    def load(self) -> dict[str, Any]:
        if not self.token_file.exists():
            return {}
        try:
            payload = json.loads(self.token_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def save(self, token: dict[str, Any]) -> dict[str, Any]:
        payload = dict(token)
        expires_in = int(payload.get("expires_in") or 0)
        if expires_in and not payload.get("expires_at"):
            payload["expires_at"] = int(time.time()) + expires_in
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return payload


class MicrosoftGraphClient:
    def __init__(
        self,
        *,
        client_id: str,
        tenant_id: str = "",
        token_file: Path,
        scopes: list[str] | None = None,
        auth_prompt: Callable[[str], None] | None = None,
        transport: Callable[[str, str, dict[str, str], bytes | None], dict[str, Any]]
        | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client_id = client_id.strip()
        self.tenant_id = tenant_id.strip() or "common"
        self.scopes = scopes or OUTLOOK_GRAPH_SCOPES
        self.token_store = OutlookGraphTokenStore(token_file)
        self.auth_prompt = auth_prompt or print
        self.transport = transport or _json_http_request
        self.sleep = sleep

    def authenticate(self) -> str:
        self._access_token(allow_interactive=True)
        return "ok"

    def get_me(self) -> dict[str, Any]:
        return self._graph_request("GET", "/me")

    def list_messages(self) -> list[dict[str, Any]]:
        params = urlencode(
            {
                "$top": "25",
                "$orderby": "receivedDateTime desc",
                "$select": (
                    "id,conversationId,subject,from,toRecipients,ccRecipients,bccRecipients,"
                    "receivedDateTime,sentDateTime,body,bodyPreview,isRead"
                ),
            }
        )
        payload = self._graph_request("GET", f"/me/mailFolders/inbox/messages?{params}")
        return list(payload.get("value", []))

    def create_reply_draft(self, *, message_id: str, draft: DraftRecord) -> dict[str, Any]:
        content = draft.body_html or draft.body
        payload = {
            "message": {
                "subject": draft.subject,
                "body": {
                    "contentType": "HTML" if draft.body_html else "Text",
                    "content": content,
                },
                "toRecipients": [_graph_recipient(address) for address in draft.to],
                "ccRecipients": [_graph_recipient(address) for address in draft.cc],
                "bccRecipients": [_graph_recipient(address) for address in draft.bcc],
            }
        }
        return self._graph_request(
            "POST",
            f"/me/messages/{quote(message_id, safe='')}/createReply",
            payload,
        )

    def has_saved_token(self) -> bool:
        token = self.token_store.load()
        return bool(token.get("access_token") or token.get("refresh_token"))

    def _access_token(self, *, allow_interactive: bool = False) -> str:
        token = self.token_store.load()
        access_token = str(token.get("access_token", ""))
        if access_token and int(token.get("expires_at") or 0) > int(time.time()) + 60:
            return access_token
        refresh_token = str(token.get("refresh_token", ""))
        if refresh_token:
            refreshed = self._token_request(
                {
                    "grant_type": "refresh_token",
                    "client_id": self.client_id,
                    "refresh_token": refresh_token,
                    "scope": self._scope_text(),
                }
            )
            return str(self.token_store.save(refreshed).get("access_token", ""))
        if not allow_interactive:
            raise OutlookGraphAuthError(
                "Outlook needs one-time Microsoft Graph authorization. Run `mailassist outlook-auth`."
            )
        device = self._device_code_request()
        message = str(device.get("message", "")).strip()
        if message:
            self.auth_prompt(message)
        return self._poll_device_code(device)

    def _device_code_request(self) -> dict[str, Any]:
        return self._identity_request(
            "devicecode",
            {
                "client_id": self.client_id,
                "scope": self._scope_text(),
            },
        )

    def _poll_device_code(self, device: dict[str, Any]) -> str:
        device_code = str(device.get("device_code", "")).strip()
        if not device_code:
            raise OutlookGraphAuthError("Microsoft Graph did not return a device code.")
        interval = max(1, int(device.get("interval") or 5))
        deadline = time.time() + max(60, int(device.get("expires_in") or 900))
        while time.time() < deadline:
            try:
                token = self._token_request(
                    {
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                        "client_id": self.client_id,
                        "device_code": device_code,
                    }
                )
            except OutlookGraphAuthError as exc:
                error = str(exc)
                if error == "authorization_pending":
                    self.sleep(interval)
                    continue
                if error == "slow_down":
                    interval += 5
                    self.sleep(interval)
                    continue
                raise
            return str(self.token_store.save(token).get("access_token", ""))
        raise OutlookGraphAuthError("Microsoft Graph device authorization expired.")

    def _token_request(self, values: dict[str, str]) -> dict[str, Any]:
        return self._identity_request("token", values)

    def _identity_request(self, endpoint: str, values: dict[str, str]) -> dict[str, Any]:
        url = (
            "https://login.microsoftonline.com/"
            f"{quote(self.tenant_id, safe='')}/oauth2/v2.0/{endpoint}"
        )
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        payload = urlencode(values).encode("utf-8")
        response = self.transport("POST", url, headers, payload)
        error = str(response.get("error", "")).strip()
        if error:
            description = str(response.get("error_description", error))
            if error in {"authorization_pending", "slow_down"}:
                raise OutlookGraphAuthError(error)
            raise OutlookGraphAuthError(
                description or error,
                requires_admin_consent=_looks_like_admin_consent_error(description),
            )
        return response

    def _graph_request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {
            "Authorization": f"Bearer {self._access_token(allow_interactive=False)}",
            "Accept": "application/json",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
        return self.transport(method, f"https://graph.microsoft.com/v1.0{path}", headers, data)

    def _scope_text(self) -> str:
        return " ".join(self.scopes)


class OutlookProvider(DraftProvider):
    name = "outlook"

    def __init__(
        self,
        *,
        client_id: str = "",
        tenant_id: str = "",
        redirect_uri: str = "",
        token_file: Path | None = None,
        graph_client: OutlookGraphClient | None = None,
    ) -> None:
        self.client_id = client_id.strip()
        self.tenant_id = tenant_id.strip()
        self.redirect_uri = redirect_uri.strip()
        self.token_file = token_file
        self.graph_client = graph_client
        if self.graph_client is None and self.client_id and self.token_file is not None:
            self.graph_client = MicrosoftGraphClient(
                client_id=self.client_id,
                tenant_id=self.tenant_id,
                token_file=self.token_file,
            )

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
        if isinstance(self.graph_client, MicrosoftGraphClient) and not self.graph_client.has_saved_token():
            return ProviderReadiness(
                provider=self.name,
                status="auth_required",
                message="Outlook needs one-time Microsoft Graph authorization.",
                can_authenticate=False,
                can_read=False,
                can_create_drafts=False,
                requires_admin_consent=False,
                details=self._graph_details(),
            )
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
            "token_file": str(self.token_file or ""),
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


def _json_http_request(
    method: str,
    url: str,
    headers: dict[str, str],
    data: bytes | None,
) -> dict[str, Any]:
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            raise OutlookGraphHttpError(f"Microsoft Graph HTTP {exc.code}: {body}") from exc
        error = payload.get("error", {})
        message = error.get("message") if isinstance(error, dict) else str(error)
        raise OutlookGraphAuthError(
            str(message or body),
            requires_admin_consent=_looks_like_admin_consent_error(str(message or body)),
        ) from exc
    if not body.strip():
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise OutlookGraphHttpError(f"Microsoft Graph returned non-JSON response: {body}") from exc


def _looks_like_admin_consent_error(message: str) -> bool:
    lowered = message.lower()
    return "admin consent" in lowered or "aadsts65001" in lowered or "aadsts90094" in lowered
