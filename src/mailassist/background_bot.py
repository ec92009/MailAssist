from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from mailassist.config import Settings
from mailassist.gui.server import (
    SET_ASIDE_CLASSIFICATIONS,
    build_mock_threads,
    fallback_classification_for_thread,
    generate_candidate_for_tone,
)
from mailassist.models import DraftRecord, EmailThread, utc_now_iso
from mailassist.providers.base import DraftProvider

BOT_STATE_FILENAME = "bot-state.json"

TONE_OPTIONS = {
    "direct_concise": (
        "Direct and concise",
        "Keep it short, clear, practical, and direct. Avoid extra warmth or filler.",
    ),
    "warm_collaborative": (
        "Warm and collaborative",
        "Sound thoughtful and calm. Acknowledge the ask and keep the tone helpful.",
    ),
    "formal_polished": (
        "Formal and polished",
        "Use a professional, polished tone with complete sentences and restrained warmth.",
    ),
    "brief_casual": (
        "Brief and casual",
        "Keep it friendly, plainspoken, and brief without becoming sloppy.",
    ),
}


def tone_label(tone_key: str) -> str:
    return TONE_OPTIONS.get(tone_key, TONE_OPTIONS["direct_concise"])[0]


def tone_guidance(tone_key: str) -> tuple[str, str]:
    return TONE_OPTIONS.get(tone_key, TONE_OPTIONS["direct_concise"])


def bot_state_path(root_dir: Path) -> Path:
    return root_dir / "data" / BOT_STATE_FILENAME


def load_bot_state(root_dir: Path) -> dict[str, Any]:
    path = bot_state_path(root_dir)
    if not path.exists():
        return {"schema_version": 1, "providers": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save_bot_state(root_dir: Path, state: dict[str, Any]) -> Path:
    path = bot_state_path(root_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(state, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)
    return path


def run_mock_watch_pass(
    *,
    settings: Settings,
    provider: DraftProvider,
    base_url: str,
    selected_model: str,
    thread_id: str = "",
    force: bool = False,
) -> list[dict[str, Any]]:
    state = load_bot_state(settings.root_dir)
    provider_state = state.setdefault("providers", {}).setdefault(provider.name, {})
    events = []

    for thread in build_mock_threads():
        if thread_id and thread.thread_id != thread_id:
            continue
        latest_message_id = _latest_message_id(thread)
        previous = provider_state.get(thread.thread_id, {})
        if not force and previous.get("latest_message_id") == latest_message_id:
            events.append(
                {
                    "type": "already_handled",
                    "thread_id": thread.thread_id,
                    "subject": thread.subject,
                    "classification": previous.get("classification", "unclassified"),
                    "provider_draft_id": previous.get("provider_draft_id"),
                }
            )
            continue

        classification = fallback_classification_for_thread(thread)
        if classification in SET_ASIDE_CLASSIFICATIONS:
            provider_state[thread.thread_id] = _state_record(
                thread=thread,
                latest_message_id=latest_message_id,
                classification=classification,
                action="skipped",
            )
            events.append(
                {
                    "type": "skipped_email",
                    "thread_id": thread.thread_id,
                    "subject": thread.subject,
                    "classification": classification,
                    "reason": "no_response_needed",
                }
            )
            continue

        tone_key = settings.user_tone
        tone, guidance = tone_guidance(tone_key)
        candidate, generation_model, generation_error, classification = generate_candidate_for_tone(
            thread,
            candidate_id="option-a",
            tone=tone,
            guidance=guidance,
            base_url=base_url,
            selected_model=selected_model,
        )
        if classification in SET_ASIDE_CLASSIFICATIONS or not candidate.get("body", "").strip():
            provider_state[thread.thread_id] = _state_record(
                thread=thread,
                latest_message_id=latest_message_id,
                classification=classification,
                action="skipped",
                generation_model=generation_model,
                generation_error=generation_error,
            )
            events.append(
                {
                    "type": "skipped_email",
                    "thread_id": thread.thread_id,
                    "subject": thread.subject,
                    "classification": classification,
                    "reason": "no_response_needed",
                    "generation_error": generation_error,
                }
            )
            continue

        draft = DraftRecord(
            draft_id=str(uuid4()),
            thread_id=thread.thread_id,
            provider=provider.name,
            subject=f"Re: {thread.subject}",
            body=str(candidate["body"]).strip(),
            model=generation_model or candidate.get("generated_by", "fallback"),
            to=reply_recipients_for_thread(thread),
        )
        provider_reference = provider.create_draft(draft)

        provider_state[thread.thread_id] = _state_record(
            thread=thread,
            latest_message_id=latest_message_id,
            classification=classification,
            action="draft_created",
            generation_model=generation_model,
            generation_error=generation_error,
            provider_draft_id=provider_reference.draft_id,
        )
        events.append(
            {
                "type": "draft_created",
                "thread_id": thread.thread_id,
                "subject": thread.subject,
                "classification": classification,
                "provider": provider.name,
                "provider_draft_id": provider_reference.draft_id,
                "generation_model": generation_model,
                "generation_error": generation_error,
            }
        )

    state["updated_at"] = utc_now_iso()
    save_bot_state(settings.root_dir, state)
    return events


def _latest_message_id(thread: EmailThread) -> str:
    if not thread.messages:
        return ""
    return thread.messages[-1].message_id


def reply_recipients_for_thread(thread: EmailThread, user_address: str = "you@example.com") -> list[str]:
    if thread.messages:
        latest_sender = thread.messages[-1].sender
        if latest_sender and latest_sender != user_address:
            return [latest_sender]
    return [item for item in thread.participants if item != user_address]


def _state_record(
    *,
    thread: EmailThread,
    latest_message_id: str,
    classification: str,
    action: str,
    generation_model: str | None = None,
    generation_error: str | None = None,
    provider_draft_id: str | None = None,
) -> dict[str, Any]:
    return {
        "thread_id": thread.thread_id,
        "subject": thread.subject,
        "latest_message_id": latest_message_id,
        "classification": classification,
        "action": action,
        "generation_model": generation_model,
        "generation_error": generation_error,
        "provider_draft_id": provider_draft_id,
        "updated_at": utc_now_iso(),
    }
