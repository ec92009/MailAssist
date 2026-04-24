from __future__ import annotations

from abc import ABC, abstractmethod

from mailassist.models import DraftRecord


class DraftProvider(ABC):
    name: str

    @abstractmethod
    def create_draft(self, draft: DraftRecord) -> str:
        raise NotImplementedError
