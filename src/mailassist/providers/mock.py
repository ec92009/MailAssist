from __future__ import annotations

import json
from pathlib import Path

from mailassist.models import DraftRecord, ProviderDraftReference
from mailassist.providers.base import DraftProvider


class MockProvider(DraftProvider):
    name = "mock"

    def __init__(self, drafts_dir: Path) -> None:
        self.drafts_dir = drafts_dir

    def create_draft(self, draft: DraftRecord) -> ProviderDraftReference:
        self.drafts_dir.mkdir(parents=True, exist_ok=True)
        path = self.drafts_dir / f"{draft.thread_id}.json"
        path.write_text(json.dumps(draft.to_dict(), indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        return ProviderDraftReference(
            draft_id=f"mock-draft-{draft.thread_id}",
            thread_id=draft.thread_id,
            message_id=None,
        )
