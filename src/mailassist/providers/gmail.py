from __future__ import annotations

import base64
import json
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from mailassist.models import DraftRecord, ProviderDraftReference
from mailassist.providers.base import DraftProvider

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.readonly",
]


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

    def _credentials(self) -> Any:
        Request, Credentials, InstalledAppFlow, _ = self._load_google_modules()
        creds = None
        if self.token_file.exists():
            if not _token_file_covers_scopes(self.token_file, GMAIL_SCOPES):
                creds = None
            else:
                creds = Credentials.from_authorized_user_file(str(self.token_file), GMAIL_SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
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
