from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.utils import parseaddr, parsedate_to_datetime
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from mailassist.live_filters import WatcherFilter, thread_passes_filter
from mailassist.models import DraftRecord, EmailMessage, EmailThread, ProviderDraftReference
from mailassist.providers.base import DraftProvider, ProviderReadiness
from mailassist.rich_text import html_to_plain_text, sanitize_html_fragment

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.settings.basic",
]
GMAIL_LABEL_CLEANUP_SCOPES = [
    *GMAIL_SCOPES,
    "https://www.googleapis.com/auth/gmail.modify",
]
GMAIL_LABEL_ADMIN_SCOPES = [
    *GMAIL_SCOPES,
    "https://www.googleapis.com/auth/gmail.labels",
]
GMAIL_LABEL_WRITE_SCOPES = [
    *GMAIL_SCOPES,
    "https://www.googleapis.com/auth/gmail.labels",
    "https://www.googleapis.com/auth/gmail.modify",
]


@dataclass(frozen=True)
class GmailSignature:
    signature: str
    send_as_email: str
    signature_html: str = ""


class GmailProvider(DraftProvider):
    name = "gmail"

    def __init__(self, credentials_file: Path, token_file: Path) -> None:
        self.credentials_file = credentials_file
        self.token_file = token_file

    def _load_google_modules(self) -> tuple[Any, Any, Any, Any]:
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError(
                "Gmail dependencies are missing. Refresh the environment with: uv sync"
            ) from exc
        return Request, Credentials, InstalledAppFlow, build

    def _credentials(
        self,
        *,
        allow_interactive_auth: bool = True,
        scopes: list[str] | None = None,
    ) -> Any:
        scopes = scopes or GMAIL_SCOPES
        Request, Credentials, InstalledAppFlow, _ = self._load_google_modules()
        creds = None
        if self.token_file.exists():
            if not _token_file_covers_scopes(self.token_file, scopes):
                if not allow_interactive_auth:
                    raise RuntimeError(
                        "Gmail needs one-time permission to read the saved signature. "
                        "Use Import from Gmail to authorize that access."
                    )
            else:
                creds = Credentials.from_authorized_user_file(str(self.token_file), scopes)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not allow_interactive_auth:
                    raise RuntimeError("Connect Gmail before importing the saved signature.")
                if not self.credentials_file.exists():
                    raise RuntimeError(
                        f"Gmail credentials file not found at {self.credentials_file}"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.credentials_file), scopes
                )
                creds = flow.run_local_server(port=0)
            self.token_file.parent.mkdir(parents=True, exist_ok=True)
            self.token_file.write_text(creds.to_json(), encoding="utf-8")
        return creds

    def create_draft(self, draft: DraftRecord) -> ProviderDraftReference:
        _, _, _, build = self._load_google_modules()
        creds = self._credentials()

        if draft.body_html:
            message = MIMEMultipart("alternative")
            message.attach(MIMEText(draft.body, "plain", "utf-8"))
            message.attach(MIMEText(sanitize_html_fragment(draft.body_html), "html", "utf-8"))
        else:
            message = MIMEText(draft.body, "plain", "utf-8")
        message["subject"] = draft.subject
        if draft.to:
            message["to"] = ", ".join(draft.to)
        if draft.cc:
            message["cc"] = ", ".join(draft.cc)
        if draft.bcc:
            message["bcc"] = ", ".join(draft.bcc)
        in_reply_to = _normalize_message_id(draft.reply_to_rfc_message_id or "")
        if in_reply_to:
            message["In-Reply-To"] = in_reply_to
        references = _draft_references_header(draft, in_reply_to)
        if references:
            message["References"] = references
        encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

        service = build("gmail", "v1", credentials=creds)
        message_body: dict[str, Any] = {"raw": encoded}
        if draft.thread_id and (draft.reply_to_message_id or in_reply_to):
            message_body["threadId"] = draft.thread_id
        created = (
            service.users()
            .drafts()
            .create(userId="me", body={"message": message_body})
            .execute()
        )
        message = created.get("message", {})
        return ProviderDraftReference(
            draft_id=created["id"],
            thread_id=message.get("threadId"),
            message_id=message.get("id"),
        )

    def list_recent_inbox_messages(self, limit: int = 10) -> list[dict[str, str]]:
        _, _, _, build = self._load_google_modules()
        creds = self._credentials()
        service = build("gmail", "v1", credentials=creds)
        listed = (
            service.users()
            .messages()
            .list(userId="me", labelIds=["INBOX"], maxResults=max(1, limit))
            .execute()
        )
        messages = []
        for item in listed.get("messages", []):
            message = (
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=item["id"],
                    format="metadata",
                    metadataHeaders=["From", "To", "Date", "Subject"],
                )
                .execute()
            )
            headers = {
                header["name"].lower(): header.get("value", "")
                for header in message.get("payload", {}).get("headers", [])
            }
            messages.append(
                {
                    "id": message.get("id", ""),
                    "thread_id": message.get("threadId", ""),
                    "from": headers.get("from", ""),
                    "to": headers.get("to", ""),
                    "date": headers.get("date", ""),
                    "subject": headers.get("subject", ""),
                    "snippet": message.get("snippet", ""),
                }
            )
        return messages

    def get_default_signature(self, *, allow_interactive_auth: bool = False) -> GmailSignature | None:
        _, _, _, build = self._load_google_modules()
        creds = self._credentials(allow_interactive_auth=allow_interactive_auth)
        service = build("gmail", "v1", credentials=creds)
        response = service.users().settings().sendAs().list(userId="me").execute()
        send_as_entries = response.get("sendAs", [])
        if not send_as_entries:
            return None

        selected = _select_send_as_entry(send_as_entries)
        signature_html = sanitize_html_fragment(str(selected.get("signature", "")))
        signature = _gmail_signature_to_text(signature_html)
        if not signature:
            return None
        return GmailSignature(
            signature=signature,
            send_as_email=str(selected.get("sendAsEmail", "")).strip(),
            signature_html=signature_html,
        )

    def ensure_authenticated(self) -> str:
        placeholder = DraftRecord(
            draft_id="auth-check",
            thread_id="auth-check",
            provider=self.name,
            subject="Authentication check",
            body="Authentication check",
            model="n/a",
        )
        try:
            self.create_draft(placeholder)
        except Exception as exc:
            message = str(exc)
            if "Authentication check" in message:
                return "ok"
            raise
        return "ok"

    def authenticate(self) -> str:
        self._credentials(allow_interactive_auth=True)
        return "ok"

    def readiness_check(self) -> ProviderReadiness:
        try:
            account_email = self.get_account_email()
        except Exception as exc:
            return ProviderReadiness(
                provider=self.name,
                status="not_configured",
                message=str(exc),
                can_authenticate=False,
                can_read=False,
                can_create_drafts=False,
            )
        return ProviderReadiness(
            provider=self.name,
            status="ready",
            message="Gmail provider is ready.",
            account_email=account_email,
            can_authenticate=True,
            can_read=True,
            can_create_drafts=True,
        )

    def get_account_email(self) -> str | None:
        _, _, _, build = self._load_google_modules()
        creds = self._credentials(allow_interactive_auth=False)
        service = build("gmail", "v1", credentials=creds)
        profile = service.users().getProfile(userId="me").execute()
        email_address = str(profile.get("emailAddress", "")).strip()
        if email_address:
            return email_address

        signature = self.get_default_signature(allow_interactive_auth=False)
        if signature is None:
            return None
        return signature.send_as_email.strip() or None

    def list_actionable_threads(self, watcher_filter: WatcherFilter) -> list[EmailThread]:
        return [
            thread
            for thread in self.list_candidate_threads(watcher_filter)
            if thread_passes_filter(thread, watcher_filter, now=datetime.now(timezone.utc))[0]
        ]

    def list_candidate_threads(self, watcher_filter: WatcherFilter | None = None) -> list[EmailThread]:
        _, _, _, build = self._load_google_modules()
        creds = self._credentials(allow_interactive_auth=False)
        service = build("gmail", "v1", credentials=creds)

        list_kwargs: dict[str, Any] = {
            "userId": "me",
            "labelIds": ["INBOX"],
            "maxResults": 25,
        }
        if watcher_filter is not None:
            query = _build_gmail_thread_query(watcher_filter)
            if query:
                list_kwargs["q"] = query

        listed = service.users().threads().list(**list_kwargs).execute()
        threads: list[EmailThread] = []
        for item in listed.get("threads", []):
            thread_payload = (
                service.users()
                .threads()
                .get(userId="me", id=item["id"], format="full")
                .execute()
            )
            thread = _gmail_thread_to_email_thread(thread_payload)
            if thread is not None:
                threads.append(thread)
        return threads

    def find_old_labeled_message_groups(
        self,
        *,
        older_than_years: int = 5,
        include_mailassist_labels: bool = False,
        max_messages_per_label: int = 500,
    ) -> list[dict[str, Any]]:
        _, _, _, build = self._load_google_modules()
        creds = self._credentials(allow_interactive_auth=False)
        service = build("gmail", "v1", credentials=creds)
        response = service.users().labels().list(userId="me").execute()
        groups: list[dict[str, Any]] = []
        for label in response.get("labels", []):
            label_id = str(label.get("id", "")).strip()
            label_name = str(label.get("name", "")).strip()
            if str(label.get("type", "")).lower() != "user":
                continue
            if not include_mailassist_labels and label_name.startswith("MailAssist/"):
                continue
            if _is_label_cleanup_excluded(label_name):
                continue
            message_ids = _list_message_ids_for_label_query(
                service,
                label_id=label_id,
                query=f"older_than:{max(1, older_than_years)}y",
                max_messages=max(1, max_messages_per_label),
            )
            if not message_ids:
                continue
            groups.append(
                {
                    "id": label_id,
                    "name": label_name,
                    "message_ids": message_ids,
                    "message_count": len(message_ids),
                    "limited": len(message_ids) >= max(1, max_messages_per_label),
                    "older_than_years": older_than_years,
                }
            )
        return groups

    def remove_label_from_messages(self, label_id: str, message_ids: list[str]) -> int:
        if not message_ids:
            return 0
        _, _, _, build = self._load_google_modules()
        creds = self._credentials(allow_interactive_auth=True, scopes=GMAIL_LABEL_CLEANUP_SCOPES)
        service = build("gmail", "v1", credentials=creds)
        removed = 0
        for chunk in _chunks(message_ids, 1000):
            service.users().messages().batchModify(
                userId="me",
                body={"ids": chunk, "removeLabelIds": [label_id]},
            ).execute()
            removed += len(chunk)
        return removed

    def find_unused_user_labels(self, *, include_mailassist_labels: bool = False) -> list[dict[str, Any]]:
        _, _, _, build = self._load_google_modules()
        creds = self._credentials(allow_interactive_auth=False)
        service = build("gmail", "v1", credentials=creds)
        response = service.users().labels().list(userId="me").execute()
        labels = [
            label
            for label in response.get("labels", [])
            if str(label.get("type", "")).lower() == "user"
        ]
        label_names = {str(label.get("name", "")).strip() for label in labels}
        unused: list[dict[str, Any]] = []
        for label in labels:
            label_id = str(label.get("id", "")).strip()
            label_name = str(label.get("name", "")).strip()
            if not include_mailassist_labels and label_name.startswith("MailAssist/"):
                continue
            if _is_label_cleanup_excluded(label_name):
                continue
            if _has_child_label(label_name, label_names):
                continue
            messages_total = int(label.get("messagesTotal") or 0)
            threads_total = int(label.get("threadsTotal") or 0)
            if messages_total or threads_total:
                continue
            unused.append(
                {
                    "id": label_id,
                    "name": label_name,
                    "messages_total": messages_total,
                    "threads_total": threads_total,
                }
            )
        return unused

    def delete_user_label(self, label_id: str) -> None:
        _, _, _, build = self._load_google_modules()
        creds = self._credentials(allow_interactive_auth=True, scopes=GMAIL_LABEL_ADMIN_SCOPES)
        service = build("gmail", "v1", credentials=creds)
        service.users().labels().delete(userId="me", id=label_id).execute()

    def ensure_user_labels(self, label_names: list[str]) -> dict[str, str]:
        _, _, _, build = self._load_google_modules()
        creds = self._credentials(allow_interactive_auth=True, scopes=GMAIL_LABEL_WRITE_SCOPES)
        service = build("gmail", "v1", credentials=creds)
        response = service.users().labels().list(userId="me").execute()
        existing = {
            str(label.get("name", "")).strip(): str(label.get("id", "")).strip()
            for label in response.get("labels", [])
        }
        resolved: dict[str, str] = {}
        for label_name in label_names:
            if label_name in existing:
                resolved[label_name] = existing[label_name]
                continue
            created = (
                service.users()
                .labels()
                .create(
                    userId="me",
                    body={
                        "name": label_name,
                        "labelListVisibility": "labelShow",
                        "messageListVisibility": "show",
                    },
                )
                .execute()
            )
            resolved[label_name] = str(created.get("id", "")).strip()
        return resolved

    def list_threads_by_query(self, query: str, *, max_threads: int = 100) -> list[EmailThread]:
        _, _, _, build = self._load_google_modules()
        creds = self._credentials(allow_interactive_auth=False)
        service = build("gmail", "v1", credentials=creds)
        raw_threads = []
        page_token = None
        while len(raw_threads) < max_threads:
            kwargs: dict[str, Any] = {
                "userId": "me",
                "q": query,
                "maxResults": min(100, max_threads - len(raw_threads)),
            }
            if page_token:
                kwargs["pageToken"] = page_token
            response = service.users().threads().list(**kwargs).execute()
            raw_threads.extend(response.get("threads", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break

        threads: list[EmailThread] = []
        for item in raw_threads:
            thread_payload = (
                service.users()
                .threads()
                .get(userId="me", id=item["id"], format="full")
                .execute()
            )
            thread = _gmail_thread_to_email_thread(thread_payload)
            if thread is not None:
                threads.append(thread)
        return threads

    def add_labels_to_thread(self, thread_id: str, label_ids: list[str]) -> None:
        if not label_ids:
            return
        _, _, _, build = self._load_google_modules()
        creds = self._credentials(allow_interactive_auth=True, scopes=GMAIL_LABEL_WRITE_SCOPES)
        service = build("gmail", "v1", credentials=creds)
        service.users().threads().modify(
            userId="me",
            id=thread_id,
            body={"addLabelIds": label_ids},
        ).execute()

    def replace_thread_labels(
        self,
        thread_id: str,
        add_label_ids: list[str],
        remove_label_ids: list[str],
    ) -> None:
        if not add_label_ids and not remove_label_ids:
            return
        _, _, _, build = self._load_google_modules()
        creds = self._credentials(allow_interactive_auth=True, scopes=GMAIL_LABEL_WRITE_SCOPES)
        service = build("gmail", "v1", credentials=creds)
        service.users().threads().modify(
            userId="me",
            id=thread_id,
            body={
                "addLabelIds": add_label_ids,
                "removeLabelIds": remove_label_ids,
            },
        ).execute()


def _credentials_cover_scopes(creds: Any, scopes: list[str]) -> bool:
    has_scopes = getattr(creds, "has_scopes", None)
    if callable(has_scopes):
        return bool(has_scopes(scopes))
    granted = set(getattr(creds, "granted_scopes", None) or getattr(creds, "scopes", None) or [])
    return set(scopes).issubset(granted)


def _token_file_covers_scopes(token_file: Path, scopes: list[str]) -> bool:
    try:
        payload = json.loads(token_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    granted = set(payload.get("granted_scopes") or payload.get("scopes") or [])
    return set(scopes).issubset(granted)


def _select_send_as_entry(send_as_entries: list[dict[str, Any]]) -> dict[str, Any]:
    with_signature = [entry for entry in send_as_entries if str(entry.get("signature", "")).strip()]
    candidates = with_signature or send_as_entries
    for key in ("isDefault", "isPrimary"):
        for entry in candidates:
            if entry.get(key):
                return entry
    return candidates[0]


def _gmail_signature_to_text(signature_html: str) -> str:
    return html_to_plain_text(signature_html)


def _build_gmail_thread_query(watcher_filter: WatcherFilter) -> str:
    parts: list[str] = []
    if watcher_filter.unread_only:
        parts.append("is:unread")

    if watcher_filter.max_age_seconds == 24 * 60 * 60:
        parts.append("newer_than:1d")
    elif watcher_filter.max_age_seconds == 7 * 24 * 60 * 60:
        parts.append("newer_than:7d")
    elif watcher_filter.max_age_seconds == 30 * 24 * 60 * 60:
        parts.append("newer_than:30d")

    return " ".join(parts)


def _list_message_ids_for_label_query(
    service: Any,
    *,
    label_id: str,
    query: str,
    max_messages: int,
) -> list[str]:
    message_ids: list[str] = []
    page_token = None
    while len(message_ids) < max_messages:
        kwargs: dict[str, Any] = {
            "userId": "me",
            "labelIds": [label_id],
            "q": query,
            "maxResults": min(500, max_messages - len(message_ids)),
        }
        if page_token:
            kwargs["pageToken"] = page_token
        response = service.users().messages().list(**kwargs).execute()
        message_ids.extend(str(item.get("id", "")) for item in response.get("messages", []) if item.get("id"))
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return message_ids


def _is_label_cleanup_excluded(label_name: str) -> bool:
    parts = [part.strip().lower() for part in label_name.split("/") if part.strip()]
    return bool(parts and parts[-1] == "archive")


def _has_child_label(label_name: str, label_names: set[str]) -> bool:
    prefix = f"{label_name}/"
    return any(candidate.startswith(prefix) for candidate in label_names)


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _gmail_thread_to_email_thread(payload: dict[str, Any]) -> EmailThread | None:
    raw_messages = payload.get("messages", [])
    if not raw_messages:
        return None

    messages: list[EmailMessage] = []
    participants: list[str] = []
    subject = ""

    for raw_message in raw_messages:
        headers = _gmail_headers(raw_message)
        sender = _first_email_from_header(headers.get("from", ""))
        recipients = _emails_from_header_values(
            headers.get("to", ""),
            headers.get("cc", ""),
            headers.get("bcc", ""),
        )
        if not subject:
            subject = str(headers.get("subject", "")).strip()
        for participant in [sender, *recipients]:
            if participant and participant not in participants:
                participants.append(participant)
        messages.append(
            EmailMessage(
                message_id=str(raw_message.get("id", "")),
                sender=sender,
                to=recipients,
                sent_at=_gmail_message_sent_at(raw_message, headers.get("date", "")),
                text=_gmail_message_text(raw_message),
                rfc_message_id=_normalize_message_id(headers.get("message-id", "")),
                references=_message_id_references(
                    headers.get("references", ""),
                    headers.get("in-reply-to", ""),
                ),
            )
        )

    latest_labels = raw_messages[-1].get("labelIds", [])
    thread_id = str(payload.get("id") or raw_messages[-1].get("threadId") or "").strip()
    return EmailThread(
        thread_id=thread_id,
        subject=subject or "(no subject)",
        participants=participants,
        messages=messages,
        unread="UNREAD" in latest_labels,
    )


def _gmail_headers(message: dict[str, Any]) -> dict[str, str]:
    return {
        str(header.get("name", "")).lower(): str(header.get("value", ""))
        for header in message.get("payload", {}).get("headers", [])
    }


def _first_email_from_header(value: str) -> str:
    emails = _emails_from_header_values(value)
    if emails:
        return emails[0]
    return value.strip().lower()


def _emails_from_header_values(*values: str) -> list[str]:
    emails: list[str] = []
    for value in values:
        for chunk in value.split(","):
            _, email = parseaddr(chunk.strip())
            cleaned = email.strip().lower()
            if cleaned:
                emails.append(cleaned)
    deduped: list[str] = []
    for email in emails:
        if email not in deduped:
            deduped.append(email)
    return deduped


def _gmail_message_sent_at(message: dict[str, Any], date_header: str) -> str:
    internal_date = str(message.get("internalDate", "")).strip()
    if internal_date.isdigit():
        sent_at = datetime.fromtimestamp(int(internal_date) / 1000, tz=timezone.utc).replace(
            microsecond=0
        )
        return sent_at.isoformat().replace("+00:00", "Z")

    parsed = _parse_date_header(date_header)
    if parsed is None:
        return ""
    return parsed.isoformat().replace("+00:00", "Z")


def _parse_date_header(value: str) -> datetime | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        parsed = parsedate_to_datetime(cleaned)
    except (TypeError, ValueError, IndexError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0)


def _gmail_message_text(message: dict[str, Any]) -> str:
    payload = message.get("payload", {})
    plain = _decode_gmail_body(_find_payload_body(payload, "text/plain"))
    if plain.strip():
        return plain.strip()

    rich = _decode_gmail_body(_find_payload_body(payload, "text/html"))
    if rich.strip():
        return _gmail_signature_to_text(rich)

    return str(message.get("snippet", "")).strip()


def _find_payload_body(payload: dict[str, Any], mime_type: str) -> str:
    if str(payload.get("mimeType", "")).lower() == mime_type.lower():
        return str(payload.get("body", {}).get("data", ""))

    for part in payload.get("parts", []) or []:
        found = _find_payload_body(part, mime_type)
        if found:
            return found
    return ""


def _decode_gmail_body(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return ""
    padding = "=" * (-len(cleaned) % 4)
    try:
        raw = base64.urlsafe_b64decode((cleaned + padding).encode("utf-8"))
    except (ValueError, TypeError):
        return ""
    return raw.decode("utf-8", errors="replace")


def _draft_references_header(draft: DraftRecord, in_reply_to: str) -> str:
    references = [
        _normalize_message_id(value)
        for value in [*draft.reply_references, in_reply_to]
        if _normalize_message_id(value)
    ]
    deduped: list[str] = []
    for reference in references:
        if reference not in deduped:
            deduped.append(reference)
    return " ".join(deduped)


def _message_id_references(*values: str) -> list[str]:
    references: list[str] = []
    for value in values:
        matches = re.findall(r"<[^>]+>", value)
        candidates = matches or value.split()
        for candidate in candidates:
            normalized = _normalize_message_id(candidate)
            if normalized and normalized not in references:
                references.append(normalized)
    return references


def _normalize_message_id(value: str) -> str:
    cleaned = " ".join(str(value or "").strip().split())
    if not cleaned:
        return ""
    match = re.search(r"<[^>]+>", cleaned)
    if match:
        return match.group(0)
    if "@" in cleaned and not (cleaned.startswith("<") and cleaned.endswith(">")):
        return f"<{cleaned.strip('<>')}>"
    return cleaned
