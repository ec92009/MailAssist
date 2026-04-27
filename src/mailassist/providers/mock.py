from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from mailassist.fixtures.mock_threads import build_mock_threads
from mailassist.live_filters import WatcherFilter, thread_passes_filter
from mailassist.models import EmailThread
from mailassist.models import DraftRecord, ProviderDraftReference
from mailassist.providers.base import DraftProvider


class MockProvider(DraftProvider):
    name = "mock"

    def __init__(self, drafts_dir: Path, account_email: str | None = None) -> None:
        self.drafts_dir = drafts_dir
        self.account_email = (account_email or "").strip() or None

    def get_account_email(self) -> str | None:
        return self.account_email

    def list_actionable_threads(self, watcher_filter: WatcherFilter) -> list[EmailThread]:
        now = datetime.now(timezone.utc)
        return [
            thread
            for thread in build_mock_threads()
            if thread_passes_filter(thread, watcher_filter, now=now)[0]
        ]

    def list_candidate_threads(self, watcher_filter: WatcherFilter | None = None) -> list[EmailThread]:
        return build_mock_threads()

    def create_draft(self, draft: DraftRecord) -> ProviderDraftReference:
        self.drafts_dir.mkdir(parents=True, exist_ok=True)
        path = self.drafts_dir / f"{draft.thread_id}.json"
        path.write_text(json.dumps(draft.to_dict(), indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        return ProviderDraftReference(
            draft_id=f"mock-draft-{draft.thread_id}",
            thread_id=draft.thread_id,
            message_id=None,
        )
