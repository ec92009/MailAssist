from __future__ import annotations

import json
from pathlib import Path
from typing import Any

LIVE_STATE_FILENAME = "live-state.json"
LEGACY_BOT_STATE_FILENAME = "bot-state.json"
LIVE_STATE_SCHEMA_VERSION = 1


def live_state_path(root_dir: Path) -> Path:
    return root_dir / "data" / LIVE_STATE_FILENAME


def legacy_bot_state_path(root_dir: Path) -> Path:
    return root_dir / "data" / LEGACY_BOT_STATE_FILENAME


def default_live_state() -> dict[str, Any]:
    return {
        "schema_version": LIVE_STATE_SCHEMA_VERSION,
        "account_email": None,
        "provider_accounts": {},
        "providers": {},
        "recent_activity": [],
    }


def load_live_state(root_dir: Path) -> dict[str, Any]:
    migrate_live_state(root_dir)
    path = live_state_path(root_dir)
    if not path.exists():
        return default_live_state()

    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != LIVE_STATE_SCHEMA_VERSION:
        return default_live_state()

    payload.setdefault("account_email", None)
    payload.setdefault("provider_accounts", {})
    payload["providers"] = _normalize_provider_slots(payload.get("providers", {}))
    payload.setdefault("recent_activity", [])
    return payload


def save_live_state(root_dir: Path, state: dict[str, Any]) -> Path:
    path = live_state_path(root_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(state, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)
    return path


def migrate_live_state(root_dir: Path) -> Path:
    path = live_state_path(root_dir)
    legacy_path = legacy_bot_state_path(root_dir)
    if path.exists() or not legacy_path.exists():
        return path

    payload = json.loads(legacy_path.read_text(encoding="utf-8"))
    if "account_email" not in payload:
        payload["account_email"] = None
    if payload.get("schema_version") != LIVE_STATE_SCHEMA_VERSION:
        payload["schema_version"] = LIVE_STATE_SCHEMA_VERSION
    payload["providers"] = _normalize_provider_slots(payload.get("providers", {}))
    save_live_state(root_dir, payload)
    legacy_path.unlink()
    return path


def _normalize_provider_slots(providers: Any) -> dict[str, Any]:
    if not isinstance(providers, dict):
        return {}

    normalized: dict[str, Any] = {}
    for provider_name, provider_payload in providers.items():
        if isinstance(provider_payload, dict) and "threads" in provider_payload:
            slot = dict(provider_payload)
            slot["threads"] = dict(slot.get("threads", {}))
            slot.setdefault("cursor", None)
            normalized[str(provider_name)] = slot
            continue

        threads = dict(provider_payload) if isinstance(provider_payload, dict) else {}
        normalized[str(provider_name)] = {
            "cursor": None,
            "threads": threads,
        }
    return normalized
