from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from mailassist.gui.server import (
    generate_candidates_for_thread,
    thread_to_payload,
)
from mailassist.models import EmailThread, utc_now_iso

QUEUE_SCHEMA_VERSION = 1
QUEUE_PHASES = (
    "bot_processed",
    "gui_acquired",
    "user_reviewed",
    "provider_drafted",
    "user_replied",
)


def ensure_queue_dirs(root_dir: Path) -> dict[str, Path]:
    paths = {phase: root_dir / "data" / phase for phase in QUEUE_PHASES}
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def queue_filename(provider: str, thread_id: str) -> str:
    cleaned_provider = _safe_name(provider)
    cleaned_thread = _safe_name(thread_id)
    return f"{cleaned_provider}__{cleaned_thread}.json"


def phase_path(root_dir: Path, phase: str, filename: str) -> Path:
    if phase not in QUEUE_PHASES:
        raise ValueError(f"Unknown queue phase: {phase}")
    return root_dir / "data" / phase / filename


def existing_phase_for_thread(root_dir: Path, provider: str, thread_id: str) -> str | None:
    filename = queue_filename(provider, thread_id)
    for phase in QUEUE_PHASES:
        if phase_path(root_dir, phase, filename).exists():
            return phase
    return None


def list_phase_items(root_dir: Path, phase: str) -> list[dict[str, Any]]:
    ensure_queue_dirs(root_dir)
    items = []
    for path in sorted((root_dir / "data" / phase).glob("*.json")):
        items.append(json.loads(path.read_text(encoding="utf-8")))
    return items


def build_bot_processed_item(
    *,
    thread: EmailThread,
    provider: str,
    source: str,
    base_url: str,
    selected_model: str,
) -> dict[str, Any]:
    candidates, generation_model, generation_error, classification = generate_candidates_for_thread(
        thread,
        base_url=base_url,
        selected_model=selected_model,
    )
    now = utc_now_iso()
    return {
        "schema_version": QUEUE_SCHEMA_VERSION,
        "workflow_state": "bot_processed",
        "source": source,
        "provider": provider,
        "provider_thread_id": thread.thread_id,
        "thread_id": thread.thread_id,
        "subject": thread.subject,
        "thread": thread_to_payload(thread),
        "classification": classification,
        "classification_source": generation_model or "fallback",
        "candidate_generation_model": generation_model,
        "candidate_generation_error": generation_error,
        "candidates": candidates,
        "review": {
            "outcome": "pending",
            "selected_candidate_id": None,
            "edited_body": None,
            "reviewed_at": None,
        },
        "provider_draft": None,
        "archive": {
            "selected": False,
            "archived": False,
        },
        "timestamps": {
            "acquired_at": now,
            "processed_at": now,
            "updated_at": now,
        },
    }


def write_queue_item(root_dir: Path, phase: str, item: dict[str, Any]) -> Path:
    ensure_queue_dirs(root_dir)
    filename = queue_filename(str(item["provider"]), str(item["thread_id"]))
    path = phase_path(root_dir, phase, filename)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(item, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)
    return path


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    return cleaned.strip("-") or "unknown"
