from __future__ import annotations

from abc import ABC, abstractmethod

from mailassist.live_filters import WatcherFilter
from mailassist.models import EmailThread
from mailassist.models import DraftRecord, ProviderDraftReference


class DraftProvider(ABC):
    name: str

    def get_account_email(self) -> str | None:
        return None

    def list_actionable_threads(self, watcher_filter: WatcherFilter) -> list[EmailThread]:
        raise NotImplementedError

    def list_candidate_threads(self, watcher_filter: WatcherFilter | None = None) -> list[EmailThread]:
        return self.list_actionable_threads(WatcherFilter(unread_only=False, max_age_seconds=None))

    @abstractmethod
    def create_draft(self, draft: DraftRecord) -> ProviderDraftReference:
        raise NotImplementedError
