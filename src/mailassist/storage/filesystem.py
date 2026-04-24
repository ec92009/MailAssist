from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List

from mailassist.models import DraftRecord, EmailThread, ExecutionLog


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
