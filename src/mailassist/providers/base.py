from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from mailassist.live_filters import WatcherFilter
from mailassist.models import EmailThread
from mailassist.models import DraftRecord, ProviderDraftReference


@dataclass(frozen=True)
class ProviderReadiness:
    provider: str
    status: str
    message: str
    account_email: str | None = None
    can_authenticate: bool = False
    can_read: bool = False
    can_create_drafts: bool = False
    requires_admin_consent: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return (
            self.status == "ready"
            and self.can_authenticate
            and self.can_read
            and self.can_create_drafts
        )


class DraftProvider(ABC):
    name: str

    def authenticate(self) -> str:
        return "not_required"

    def get_account_email(self) -> str | None:
        return None

    def readiness_check(self) -> ProviderReadiness:
        account_email = self.get_account_email()
        return ProviderReadiness(
            provider=self.name,
            status="ready",
            message=f"{self.name} provider is available.",
            account_email=account_email,
            can_authenticate=True,
            can_read=True,
            can_create_drafts=True,
        )

    def list_actionable_threads(self, watcher_filter: WatcherFilter) -> list[EmailThread]:
        raise NotImplementedError

    def list_candidate_threads(self, watcher_filter: WatcherFilter | None = None) -> list[EmailThread]:
        return self.list_actionable_threads(WatcherFilter(unread_only=False, max_age_seconds=None))

    @abstractmethod
    def create_draft(self, draft: DraftRecord) -> ProviderDraftReference:
        raise NotImplementedError
