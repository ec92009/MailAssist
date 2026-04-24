from __future__ import annotations

import base64
from email.mime.text import MIMEText
from pathlib import Path

from mailassist.models import DraftRecord
from mailassist.providers.base import DraftProvider


class GmailProvider(DraftProvider):
    name = "gmail"

    def __init__(self, credentials_file: Path, token_file: Path) -> None:
        self.credentials_file = credentials_file
        self.token_file = token_file

    def create_draft(self, draft: DraftRecord) -> str:
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError(
                "Gmail dependencies are missing. Install with: uv pip install -e \".[gmail]\""
            ) from exc

        scopes = ["https://www.googleapis.com/auth/gmail.compose"]
        creds = None
        if self.token_file.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_file), scopes)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
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

        message = MIMEText(draft.body)
        message["subject"] = draft.subject
        encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

        service = build("gmail", "v1", credentials=creds)
        created = (
            service.users()
            .drafts()
            .create(userId="me", body={"message": {"raw": encoded}})
            .execute()
        )
        return created["id"]

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
