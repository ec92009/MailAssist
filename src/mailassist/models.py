from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class EmailMessage:
    message_id: str
    sender: str
    to: List[str]
    sent_at: str
    text: str

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "EmailMessage":
        return cls(
            message_id=payload["message_id"],
            sender=payload["from"],
            to=list(payload.get("to", [])),
            sent_at=payload["sent_at"],
            text=payload["text"],
        )


@dataclass
class EmailThread:
    thread_id: str
    subject: str
    participants: List[str]
    messages: List[EmailMessage]

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "EmailThread":
        return cls(
            thread_id=payload["thread_id"],
            subject=payload["subject"],
            participants=list(payload.get("participants", [])),
            messages=[EmailMessage.from_dict(item) for item in payload.get("messages", [])],
        )


@dataclass
class ProviderDraftReference:
    draft_id: str
    thread_id: Optional[str] = None
    message_id: Optional[str] = None


@dataclass
class DraftRecord:
    draft_id: str
    thread_id: str
    provider: str
    subject: str
    body: str
    model: str
    to: List[str] = field(default_factory=list)
    cc: List[str] = field(default_factory=list)
    bcc: List[str] = field(default_factory=list)
    status: str = "pending_review"
    created_at: str = field(default_factory=utc_now_iso)
    provider_submission_status: str = "not_submitted"
    provider_draft_id: Optional[str] = None
    provider_thread_id: Optional[str] = None
    provider_message_id: Optional[str] = None
    provider_synced_at: Optional[str] = None
    provider_error: Optional[str] = None
    revision_notes: Optional[str] = None

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "DraftRecord":
        return cls(
            draft_id=payload["draft_id"],
            thread_id=payload["thread_id"],
            provider=payload["provider"],
            subject=payload["subject"],
            body=payload["body"],
            model=payload["model"],
            to=list(payload.get("to", [])),
            cc=list(payload.get("cc", [])),
            bcc=list(payload.get("bcc", [])),
            status=payload.get("status", "pending_review"),
            created_at=payload.get("created_at", utc_now_iso()),
            provider_submission_status=payload.get("provider_submission_status", "not_submitted"),
            provider_draft_id=payload.get("provider_draft_id"),
            provider_thread_id=payload.get("provider_thread_id"),
            provider_message_id=payload.get("provider_message_id"),
            provider_synced_at=payload.get("provider_synced_at"),
            provider_error=payload.get("provider_error"),
            revision_notes=payload.get("revision_notes"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
