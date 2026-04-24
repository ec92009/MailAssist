from __future__ import annotations

from mailassist.models import DraftRecord
from mailassist.providers.base import DraftProvider


class OutlookProvider(DraftProvider):
    name = "outlook"

    def create_draft(self, draft: DraftRecord) -> str:
        raise NotImplementedError(
            "Outlook support is planned next. The provider interface is ready for it."
        )
