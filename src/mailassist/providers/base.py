from __future__ import annotations

from abc import ABC, abstractmethod

from mailassist.models import DraftRecord, ProviderDraftReference


class DraftProvider(ABC):
    name: str

    def get_account_email(self) -> str | None:
        return None

    @abstractmethod
    def create_draft(self, draft: DraftRecord) -> ProviderDraftReference:
        raise NotImplementedError
