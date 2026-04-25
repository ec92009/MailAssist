from __future__ import annotations

import base64
import html
import json
import re
from dataclasses import dataclass
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from mailassist.models import DraftRecord, ProviderDraftReference
from mailassist.providers.base import DraftProvider

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.settings.basic",
]


@dataclass(frozen=True)
class GmailSignature:
    signature: str
    send_as_email: str


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
                "Gmail dependencies are missing. Install with: uv pip install -e \".[gmail]\""
            ) from exc
        return Request, Credentials, InstalledAppFlow, build

    def _credentials(self, *, allow_interactive_auth: bool = True) -> Any:
        Request, Credentials, InstalledAppFlow, _ = self._load_google_modules()
        creds = None
        if self.token_file.exists():
            if not _token_file_covers_scopes(self.token_file, GMAIL_SCOPES):
                if not allow_interactive_auth:
                    raise RuntimeError(
                        "Gmail needs one-time permission to read the saved signature. "
                        "Use Import from Gmail to authorize that access."
                    )
            else:
                creds = Credentials.from_authorized_user_file(str(self.token_file), GMAIL_SCOPES)
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
                    str(self.credentials_file), GMAIL_SCOPES
                )
                creds = flow.run_local_server(port=0)
            self.token_file.parent.mkdir(parents=True, exist_ok=True)
            self.token_file.write_text(creds.to_json(), encoding="utf-8")
        return creds

    def create_draft(self, draft: DraftRecord) -> ProviderDraftReference:
        _, _, _, build = self._load_google_modules()
        creds = self._credentials()

        message = MIMEText(draft.body)
        message["subject"] = draft.subject
        if draft.to:
            message["to"] = ", ".join(draft.to)
        if draft.cc:
            message["cc"] = ", ".join(draft.cc)
        if draft.bcc:
            message["bcc"] = ", ".join(draft.bcc)
        encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

        service = build("gmail", "v1", credentials=creds)
        created = (
            service.users()
            .drafts()
            .create(userId="me", body={"message": {"raw": encoded}})
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
        signature = _gmail_signature_to_text(str(selected.get("signature", "")))
        if not signature:
            return None
        return GmailSignature(
            signature=signature,
            send_as_email=str(selected.get("sendAsEmail", "")).strip(),
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
    text = signature_html.strip()
    if not text:
        return ""
    text = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", text)
    text = re.sub(r"(?i)</\s*(p|div|li|tr|h[1-6])\s*>", "\n", text)
    text = re.sub(r"(?i)<\s*li[^>]*>", "- ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    collapsed: list[str] = []
    for line in lines:
        if line or (collapsed and collapsed[-1]):
            collapsed.append(line)
    return "\n".join(collapsed).strip()
