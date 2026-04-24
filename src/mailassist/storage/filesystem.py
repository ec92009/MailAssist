from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import List, Optional

from mailassist.models import DraftRecord, EmailThread, ExecutionLog

MISSING = object()


class FileStorage:
    def __init__(self, drafts_dir: Path, logs_dir: Path) -> None:
        self.drafts_dir = drafts_dir
        self.logs_dir = logs_dir
        self.drafts_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def load_thread(thread_file: Path) -> EmailThread:
        payload = json.loads(thread_file.read_text(encoding="utf-8"))
        return EmailThread.from_dict(payload)

    def save_draft(self, draft: DraftRecord) -> Path:
        path = self.drafts_dir / f"{draft.draft_id}.json"
        path.write_text(json.dumps(draft.to_dict(), indent=2), encoding="utf-8")
        return path

    def save_log(self, log: ExecutionLog) -> Path:
        path = self.logs_dir / f"{log.run_id}.json"
        path.write_text(json.dumps(log.to_dict(), indent=2), encoding="utf-8")
        return path

    def load_draft(self, draft_id: str) -> DraftRecord:
        path = self.drafts_dir / f"{draft_id}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        return DraftRecord.from_dict(payload)

    def update_draft(
        self,
        draft_id: str,
        *,
        status: Optional[str] | object = MISSING,
        revision_notes: Optional[str] | object = MISSING,
        provider_submission_status: Optional[str] | object = MISSING,
        provider_draft_id: Optional[str] | object = MISSING,
        provider_thread_id: Optional[str] | object = MISSING,
        provider_message_id: Optional[str] | object = MISSING,
        provider_synced_at: Optional[str] | object = MISSING,
        provider_error: Optional[str] | object = MISSING,
    ) -> Path:
        draft = self.load_draft(draft_id)
        updated = replace(
            draft,
            status=draft.status if status is MISSING else status,
            revision_notes=draft.revision_notes if revision_notes is MISSING else revision_notes,
            provider_submission_status=(
                draft.provider_submission_status
                if provider_submission_status is MISSING
                else provider_submission_status
            ),
            provider_draft_id=draft.provider_draft_id if provider_draft_id is MISSING else provider_draft_id,
            provider_thread_id=(
                draft.provider_thread_id if provider_thread_id is MISSING else provider_thread_id
            ),
            provider_message_id=(
                draft.provider_message_id if provider_message_id is MISSING else provider_message_id
            ),
            provider_synced_at=(
                draft.provider_synced_at if provider_synced_at is MISSING else provider_synced_at
            ),
            provider_error=draft.provider_error if provider_error is MISSING else provider_error,
        )
        return self.save_draft(updated)

    def list_json_records(self, directory: Path) -> List[dict]:
        if not directory.exists():
            return []
        records = []
        for path in sorted(directory.glob("*.json")):
            records.append(json.loads(path.read_text(encoding="utf-8")))
        return records

    def list_drafts(self) -> List[dict]:
        return self.list_json_records(self.drafts_dir)

    def list_logs(self) -> List[dict]:
        return self.list_json_records(self.logs_dir)

    def list_draft_records(self) -> List[DraftRecord]:
        records = []
        for item in self.list_drafts():
            records.append(DraftRecord.from_dict(item))
        return sorted(records, key=lambda item: item.created_at, reverse=True)
