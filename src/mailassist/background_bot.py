from __future__ import annotations

import json
import locale
import os
import platform
import re
import subprocess
import time
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterator, TextIO
from uuid import uuid4

from mailassist.config import (
    ATTRIBUTION_ABOVE_SIGNATURE,
    ATTRIBUTION_BELOW_SIGNATURE,
    ATTRIBUTION_HIDE,
    Settings,
)
from mailassist.fixtures.mock_threads import build_mock_threads
from mailassist.live_filters import WatcherFilter, thread_passes_filter
from mailassist.live_state import load_live_state, save_live_state
from mailassist.drafting import (
    COMMON_DRAFTING_RULES,
    SET_ASIDE_CLASSIFICATIONS,
    append_signature_to_body,
    fallback_classification_for_thread,
    format_thread_context,
    generate_candidate_for_tone,
    list_available_models,
    merge_classification,
    normalize_classification,
    relationship_prompt_block,
    resolve_generation_model,
    signature_prompt_block,
)
from mailassist.contacts import ElderContact
from mailassist.llm.ollama import OllamaClient
from mailassist.models import DraftRecord, EmailMessage, EmailThread, utc_now_iso
from mailassist.providers.base import DraftProvider
from mailassist.rich_text import (
    attribution_html,
    attribution_text,
    html_to_plain_text,
    plain_text_to_html,
    sanitize_html_fragment,
)

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
CURSOR_ADVANCING_EVENT_TYPES = {
    "draft_created",
    "draft_ready",
    "skipped_email",
    "already_handled",
    "user_replied",
    "filtered_out",
}


def tone_label(tone_key: str) -> str:
    return TONE_OPTIONS.get(tone_key, TONE_OPTIONS["direct_concise"])[0]


def tone_guidance(tone_key: str) -> tuple[str, str]:
    return TONE_OPTIONS.get(tone_key, TONE_OPTIONS["direct_concise"])


def build_prompt_preview(
    *,
    tone_key: str,
    signature: str,
    sample_thread_id: str = "thread-010",
    user_facing: bool = False,
) -> str:
    """Build a representative live-draft prompt with sanitized mock mail."""
    tone, guidance = tone_guidance(tone_key)
    threads = build_mock_threads()
    sample_thread = next((thread for thread in threads if thread.thread_id == sample_thread_id), threads[0])
    prompt = build_batch_candidate_prompt(
        [sample_thread],
        tone=tone,
        guidance=guidance,
        signature=signature,
    )
    if not user_facing:
        return prompt
    prompt = re.sub(r"(?ms)^Output format requirements:.*?^Threads:\n", "Example email sent to the local model:\n", prompt)
    prompt = re.sub(
        r"(?m)^- If classification is `automated`, `no_response`, or `spam`, leave `BODY:` empty\.\n",
        "",
        prompt,
    )
    return prompt


def bot_state_path(root_dir: Path) -> Path:
    return root_dir / "data" / "live-state.json"


def load_bot_state(root_dir: Path) -> dict[str, Any]:
    return load_live_state(root_dir)


def save_bot_state(root_dir: Path, state: dict[str, Any]) -> Path:
    return save_live_state(root_dir, state)


def _scan_pass_lock_path(root_dir: Path, provider_name: str) -> Path:
    safe_provider = re.sub(r"[^A-Za-z0-9_.-]+", "_", provider_name.strip().lower() or "provider")
    return root_dir / "data" / "locks" / f"scan-{safe_provider}.lock"


@contextmanager
def _scan_pass_lock(root_dir: Path, provider_name: str) -> Iterator[bool]:
    path = _scan_pass_lock_path(root_dir, provider_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        acquired = _try_lock_file(handle)
        if not acquired:
            yield False
            return
        try:
            handle.seek(0)
            handle.truncate()
            handle.write(
                json.dumps(
                    {
                        "provider": provider_name,
                        "pid": os.getpid(),
                        "locked_at": utc_now_iso(),
                    },
                    ensure_ascii=True,
                )
                + "\n"
            )
            handle.flush()
            yield True
        finally:
            _unlock_file(handle)


def _try_lock_file(handle: TextIO) -> bool:
    handle.seek(0)
    if platform.system() == "Windows":
        try:
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    try:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except (ImportError, OSError, BlockingIOError):
        return False


def _unlock_file(handle: TextIO) -> None:
    handle.seek(0)
    if platform.system() == "Windows":
        try:
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        return
    try:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except (ImportError, OSError):
        pass


def _record_watch_event(
    events: list[dict[str, Any]],
    *,
    settings: Settings,
    state: dict[str, Any],
    provider_slot: dict[str, Any] | None = None,
    provider_name: str,
    event: dict[str, Any],
    advance_cursor: bool = False,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    events.append(event)
    _append_recent_activity(state, provider_name=provider_name, event=event)
    if advance_cursor and provider_slot is not None:
        _advance_provider_cursor(provider_slot, event)
    state["updated_at"] = utc_now_iso()
    save_bot_state(settings.root_dir, state)
    _emit_progress(progress_callback, _safe_progress_event(event, provider_name=provider_name))


def run_watch_pass(
    *,
    settings: Settings,
    provider: DraftProvider,
    base_url: str,
    selected_model: str,
    thread_id: str = "",
    force: bool = False,
    batch_size: int = 1,
    dry_run: bool = False,
    max_candidates: int | None = None,
    scan_lock_wait_seconds: float = 0,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    lock_wait_seconds = max(0.0, float(scan_lock_wait_seconds or 0))
    wait_started_at = time.monotonic()
    waiting_reported = False
    while True:
        with _scan_pass_lock(settings.root_dir, provider.name) as lock_acquired:
            if lock_acquired:
                return _run_watch_pass_unlocked(
                    settings=settings,
                    provider=provider,
                    base_url=base_url,
                    selected_model=selected_model,
                    thread_id=thread_id,
                    force=force,
                    batch_size=batch_size,
                    dry_run=dry_run,
                    max_candidates=max_candidates,
                    progress_callback=progress_callback,
                )
        elapsed = time.monotonic() - wait_started_at
        if elapsed >= lock_wait_seconds:
            event = {
                "type": "scan_lock_busy",
                "provider": provider.name,
                "reason": "another_scan_running",
                "message": "Another MailAssist scan is already running; this pass skipped without drafting.",
                "waited_seconds": int(round(elapsed)),
            }
            return [event]

        remaining = lock_wait_seconds - elapsed
        if not waiting_reported:
            _emit_progress(
                progress_callback,
                _safe_progress_event(
                    {
                        "type": "scan_lock_waiting",
                        "provider": provider.name,
                        "reason": "another_scan_running",
                        "message": "Another MailAssist scan is already running; waiting for it to finish.",
                        "wait_seconds": int(round(lock_wait_seconds)),
                    },
                    provider_name=provider.name,
                ),
            )
            waiting_reported = True
        time.sleep(min(2.0, max(0.1, remaining)))


def _run_watch_pass_unlocked(
    *,
    settings: Settings,
    provider: DraftProvider,
    base_url: str,
    selected_model: str,
    thread_id: str = "",
    force: bool = False,
    batch_size: int = 1,
    dry_run: bool = False,
    max_candidates: int | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    state = load_bot_state(settings.root_dir)
    user_address = _resolve_account_email(state, provider)
    provider_slot = state.setdefault("providers", {}).setdefault(
        provider.name,
        {"cursor": {}, "threads": {}},
    )
    provider_state = provider_slot.setdefault("threads", {})
    use_cursor = not force and not thread_id
    cursor_timestamp = _ensure_provider_cursor(
        state,
        provider_name=provider.name,
        provider_slot=provider_slot,
        settings=settings,
    ) if use_cursor else None
    advance_cursor = use_cursor and not dry_run
    events = []
    pending_threads: list[tuple[EmailThread, str]] = []
    thread_candidates = _watch_thread_candidates_for_provider(
        provider,
        settings,
        received_after=cursor_timestamp,
    )
    if max_candidates is not None:
        thread_candidates = thread_candidates[: max(1, int(max_candidates))]

    for thread, filtered_reason in thread_candidates:
        if thread_id and thread.thread_id != thread_id:
            continue
        if filtered_reason == "caught_up":
            continue
        latest_message_id = _latest_message_id(thread)
        if filtered_reason:
            provider_state[thread.thread_id] = _state_record(
                thread=thread,
                latest_message_id=latest_message_id,
                classification="filtered",
                action="filtered_out",
            )
            _record_watch_event(
                events,
                settings=settings,
                state=state,
                provider_slot=provider_slot,
                provider_name=provider.name,
                advance_cursor=advance_cursor,
                progress_callback=progress_callback,
                event={
                    "type": "filtered_out",
                    "provider": provider.name,
                    "thread_id": thread.thread_id,
                    "subject": thread.subject,
                    "classification": "filtered",
                    "reason": filtered_reason,
                    "message_timestamp": _latest_message_timestamp(thread),
                },
            )
            continue
        if _latest_sender(thread) == user_address:
            provider_state[thread.thread_id] = _state_record(
                thread=thread,
                latest_message_id=latest_message_id,
                classification="reply_needed",
                action="user_replied",
            )
            _record_watch_event(
                events,
                settings=settings,
                state=state,
                provider_slot=provider_slot,
                provider_name=provider.name,
                advance_cursor=advance_cursor,
                progress_callback=progress_callback,
                event={
                    "type": "user_replied",
                    "provider": provider.name,
                    "thread_id": thread.thread_id,
                    "subject": thread.subject,
                    "classification": "reply_needed",
                    "reason": "latest_message_from_user",
                    "message_timestamp": _latest_message_timestamp(thread),
                },
            )
            continue
        previous = provider_state.get(thread.thread_id, {})
        if not force and previous.get("latest_message_id") == latest_message_id:
            _record_watch_event(
                events,
                settings=settings,
                state=state,
                provider_slot=provider_slot,
                provider_name=provider.name,
                advance_cursor=advance_cursor,
                progress_callback=progress_callback,
                event={
                    "type": "already_handled",
                    "provider": provider.name,
                    "thread_id": thread.thread_id,
                    "subject": thread.subject,
                    "classification": previous.get("classification", "unclassified"),
                    "provider_draft_id": previous.get("provider_draft_id"),
                    "message_timestamp": _latest_message_timestamp(thread),
                },
            )
            continue

        classification = fallback_classification_for_thread(thread)
        if classification in SET_ASIDE_CLASSIFICATIONS:
            _emit_classification_progress(
                progress_callback,
                provider_name=provider.name,
                classification=classification,
            )
            provider_state[thread.thread_id] = _state_record(
                thread=thread,
                latest_message_id=latest_message_id,
                classification=classification,
                action="skipped",
            )
            _record_watch_event(
                events,
                settings=settings,
                state=state,
                provider_slot=provider_slot,
                provider_name=provider.name,
                advance_cursor=advance_cursor,
                progress_callback=progress_callback,
                event={
                    "type": "skipped_email",
                    "provider": provider.name,
                    "thread_id": thread.thread_id,
                    "subject": thread.subject,
                    "classification": classification,
                    "reason": "no_response_needed",
                    "message_timestamp": _latest_message_timestamp(thread),
                },
            )
            continue

        pending_threads.append((thread, latest_message_id))

    for chunk in _chunks(pending_threads, max(1, batch_size)):
        tone_key = settings.user_tone
        tone, guidance = tone_guidance(tone_key)
        for thread, _ in chunk:
            _emit_progress(
                progress_callback,
                {
                    "type": "email_work_started",
                    "provider": provider.name,
                    "message_timestamp": _latest_message_timestamp(thread),
                },
            )
        if len(chunk) > 1:
            try:
                generated = generate_batch_candidates_for_tone(
                    [thread for thread, _ in chunk],
                    tone=tone,
                    guidance=guidance,
                    base_url=base_url,
                    selected_model=selected_model,
                    signature=settings.user_signature,
                    elder_contacts=settings.elder_contacts,
                )
            except (RuntimeError, ValueError) as exc:
                generated = {}
                for thread, _ in chunk:
                    candidate, generation_model, generation_error, classification = (
                        generate_candidate_for_tone(
                            thread,
                            candidate_id="option-a",
                            tone=tone,
                            guidance=guidance,
                            base_url=base_url,
                            selected_model=selected_model,
                            signature=settings.user_signature,
                            elder_contacts=settings.elder_contacts,
                        )
                    )
                    generated[thread.thread_id] = {
                        "body": str(candidate.get("body", "")).strip(),
                        "classification": classification,
                        "generation_model": generation_model or candidate.get("generated_by", "fallback"),
                        "generation_error": _combine_generation_errors(
                            f"Batch generation failed: {exc}",
                            generation_error,
                        ),
                    }
        else:
            thread = chunk[0][0]
            candidate, generation_model, generation_error, classification = generate_candidate_for_tone(
                thread,
                candidate_id="option-a",
                tone=tone,
                guidance=guidance,
                base_url=base_url,
                selected_model=selected_model,
                signature=settings.user_signature,
                elder_contacts=settings.elder_contacts,
            )
            generated = {
                thread.thread_id: {
                    "body": str(candidate.get("body", "")).strip(),
                    "classification": classification,
                    "generation_model": generation_model or candidate.get("generated_by", "fallback"),
                    "generation_error": generation_error,
                }
            }

        for thread, latest_message_id in chunk:
            item = generated.get(thread.thread_id)
            if item is None:
                _emit_classification_progress(
                    progress_callback,
                    provider_name=provider.name,
                    classification="unclassified",
                )
                provider_state[thread.thread_id] = _state_record(
                    thread=thread,
                    latest_message_id=latest_message_id,
                    classification="unclassified",
                    action="skipped",
                    generation_error="Batch generation did not include this thread.",
                )
                _record_watch_event(
                    events,
                    settings=settings,
                    state=state,
                    provider_slot=provider_slot,
                    provider_name=provider.name,
                    advance_cursor=advance_cursor,
                    progress_callback=progress_callback,
                    event={
                        "type": "skipped_email",
                        "provider": provider.name,
                        "thread_id": thread.thread_id,
                        "subject": thread.subject,
                        "classification": "unclassified",
                        "reason": "missing_batch_result",
                        "generation_error": "Batch generation did not include this thread.",
                        "message_timestamp": _latest_message_timestamp(thread),
                    },
                )
                continue

            classification = str(item.get("classification", "unclassified"))
            _emit_classification_progress(
                progress_callback,
                provider_name=provider.name,
                classification=classification,
            )
            body = str(item.get("body", "")).strip()
            generation_model = item.get("generation_model")
            generation_error = item.get("generation_error")
            if classification not in SET_ASIDE_CLASSIFICATIONS:
                body = ensure_substantive_reply_body(
                    thread,
                    body,
                    signature=settings.user_signature,
                )

            if classification in SET_ASIDE_CLASSIFICATIONS or not body:
                provider_state[thread.thread_id] = _state_record(
                    thread=thread,
                    latest_message_id=latest_message_id,
                    classification=classification,
                    action="skipped",
                    generation_model=generation_model,
                    generation_error=generation_error,
                )
                _record_watch_event(
                    events,
                    settings=settings,
                    state=state,
                    provider_slot=provider_slot,
                    provider_name=provider.name,
                    advance_cursor=advance_cursor,
                    progress_callback=progress_callback,
                    event={
                        "type": "skipped_email",
                        "provider": provider.name,
                        "thread_id": thread.thread_id,
                        "subject": thread.subject,
                        "classification": classification,
                        "reason": "no_response_needed",
                        "generation_error": generation_error,
                        "message_timestamp": _latest_message_timestamp(thread),
                    },
                )
                continue

            if _fallback_generation_failed(generation_model, generation_error):
                _record_watch_event(
                    events,
                    settings=settings,
                    state=state,
                    provider_slot=provider_slot,
                    provider_name=provider.name,
                    advance_cursor=False,
                    progress_callback=progress_callback,
                    event={
                        "type": "generation_failed",
                        "provider": provider.name,
                        "thread_id": thread.thread_id,
                        "subject": thread.subject,
                        "classification": classification,
                        "reason": "model_unavailable",
                        "generation_model": generation_model,
                        "generation_error": generation_error,
                        "message_timestamp": _latest_message_timestamp(thread),
                    },
                )
                continue

            generation_model_name = str(generation_model or "fallback")
            body = append_draft_attribution(
                body,
                model=generation_model_name,
                placement=settings.draft_attribution_placement,
                signature=settings.user_signature,
            )
            body_html = build_draft_body_html(
                thread,
                body,
                signature=settings.user_signature,
                signature_html=settings.user_signature_html,
                model=generation_model_name,
                attribution_placement=settings.draft_attribution_placement,
                user_address=user_address,
                include_review_context=False,
            )
            draft = DraftRecord(
                draft_id=str(uuid4()),
                thread_id=thread.thread_id,
                provider=provider.name,
                subject=f"Re: {thread.subject}",
                body=body,
                body_html=body_html,
                model=generation_model_name,
                to=reply_recipients_for_thread(thread, user_address=user_address),
                cc=reply_cc_for_thread(thread, user_address=user_address),
                **reply_metadata_for_thread(thread, user_address=user_address),
            )
            if dry_run:
                provider_reference = None
            else:
                provider_reference = provider.create_draft(draft)

            provider_draft_id = provider_reference.draft_id if provider_reference is not None else None
            if not dry_run:
                provider_state[thread.thread_id] = _state_record(
                    thread=thread,
                    latest_message_id=latest_message_id,
                    classification=classification,
                    action="draft_created",
                    generation_model=generation_model,
                    generation_error=generation_error,
                    provider_draft_id=provider_draft_id,
                )
            _record_watch_event(
                events,
                settings=settings,
                state=state,
                provider_slot=provider_slot,
                provider_name=provider.name,
                advance_cursor=advance_cursor,
                progress_callback=progress_callback,
                event={
                    "type": "draft_ready" if dry_run else "draft_created",
                    "thread_id": thread.thread_id,
                    "subject": thread.subject,
                    "classification": classification,
                    "provider": provider.name,
                    "provider_draft_id": provider_draft_id,
                    "generation_model": generation_model,
                    "generation_error": generation_error,
                    "dry_run": dry_run,
                    "message_timestamp": _latest_message_timestamp(thread),
                },
            )

    state["updated_at"] = utc_now_iso()
    save_bot_state(settings.root_dir, state)
    return events


def run_mock_watch_pass(**kwargs: Any) -> list[dict[str, Any]]:
    """Backward-compatible alias for older tests and scripts."""
    return run_watch_pass(**kwargs)


def generate_batch_candidates_for_tone(
    threads: list[EmailThread],
    *,
    tone: str,
    guidance: str,
    base_url: str,
    selected_model: str,
    signature: str,
    elder_contacts: list[ElderContact] | tuple[ElderContact, ...] = (),
) -> dict[str, dict[str, Any]]:
    models, model_error = list_available_models(base_url, selected_model)
    if model_error:
        raise RuntimeError(model_error)
    generation_model = resolve_generation_model(selected_model, models)
    prompt = build_batch_candidate_prompt(
        threads,
        tone=tone,
        guidance=guidance,
        signature=signature,
        elder_contacts=elder_contacts,
    )
    response = OllamaClient(base_url, generation_model).compose_reply(prompt)
    parsed = parse_batch_candidate_response(
        response,
        expected_thread_ids=[thread.thread_id for thread in threads],
        allow_partial=True,
    )
    results = {}
    for thread in threads:
        item = parsed.get(thread.thread_id)
        if item is None or item.get("error"):
            candidate, fallback_model, fallback_error, fallback_classification = generate_candidate_for_tone(
                thread,
                candidate_id="option-a",
                tone=tone,
                guidance=guidance,
                base_url=base_url,
                selected_model=selected_model,
                signature=signature,
                elder_contacts=elder_contacts,
            )
            results[thread.thread_id] = {
                "body": str(candidate.get("body", "")).strip(),
                "classification": fallback_classification,
                "generation_model": fallback_model or candidate.get("generated_by", generation_model),
                "generation_error": _combine_generation_errors(
                    item.get("error") if item else "Batch generation did not include this thread.",
                    fallback_error,
                ),
            }
            continue
        heuristic_classification = fallback_classification_for_thread(thread)
        classification = merge_classification(item["classification"], heuristic_classification)
        body = item["body"].strip() if classification not in SET_ASIDE_CLASSIFICATIONS else ""
        results[thread.thread_id] = {
            "body": body,
            "classification": classification,
            "generation_model": generation_model,
            "generation_error": None,
        }
    return results


def build_batch_candidate_prompt(
    threads: list[EmailThread],
    *,
    tone: str,
    guidance: str,
    signature: str = "",
    elder_contacts: list[ElderContact] | tuple[ElderContact, ...] = (),
) -> str:
    thread_sections = []
    for thread in threads:
        thread_sections.append(
            f"""INPUT THREAD {thread.thread_id}
{format_thread_context(thread)}{relationship_prompt_block(thread, elder_contacts)}
-- END INPUT THREAD {thread.thread_id} --"""
        )

    return f"""You are MailAssist, a local-first email drafting assistant.

You have no hidden context beyond the threads shown below. Treat each thread independently. Do not mix names, facts, dates, approvals, prices, attachments, or commitments between threads.

Your job:
1. Classify each thread.
2. Draft 1 candidate reply only when a reply is appropriate.

Classification rules:
- Use `urgent` when the sender is asking for a quick turnaround, a deadline is near, or the message clearly needs immediate attention.
- Use `reply_needed` when a human reply is appropriate but the thread is not obviously urgent.
- Use `automated` when the message is clearly machine-generated, newsletter-like, digest-like, or from a no-reply workflow.
- Use `no_response` when a human technically could respond but no response is actually appropriate.
- Use `spam` when the message is junk, deceptive, or obviously irrelevant.

Drafting rules:
- If classification is `automated`, `no_response`, or `spam`, leave `BODY:` empty.
- {COMMON_DRAFTING_RULES.replace(chr(10), chr(10) + "- ")[2:]}
- If classification is `urgent` or `reply_needed`, the body must contain at least one substantive sentence. Never return only a greeting, sign-off, or signature.
- Keep each draft under 140 words.
- Signature rules:
{signature_prompt_block(signature)}
- Tone target: {tone}.
- Additional style guidance: {guidance}.

Output format requirements:
- Return one block per input thread, in the same order.
- Use each thread ID exactly as provided.
- Do not use markdown fences.
- Do not add analysis or explanations.
- Each block must exactly follow this shape:

BEGIN THREAD <thread_id>
CLASSIFICATION: <urgent|reply_needed|automated|no_response|spam>
BODY:
<candidate email body, or empty>
-- END THREAD <thread_id> --

Threads:
{chr(10).join(thread_sections)}
""".strip()


def parse_batch_candidate_response(
    response: str,
    *,
    expected_thread_ids: list[str],
    allow_partial: bool = False,
) -> dict[str, dict[str, Any]]:
    text = response.replace("\r\n", "\n").strip()
    parsed: dict[str, dict[str, Any]] = {}
    for thread_id in expected_thread_ids:
        start_marker = f"BEGIN THREAD {thread_id}"
        end_marker = f"-- END THREAD {thread_id} --"
        start = text.find(start_marker)
        end = text.find(end_marker, start + len(start_marker))
        if start < 0 or end < 0:
            if allow_partial:
                parsed[thread_id] = {"error": f"Missing packed response block for {thread_id}."}
                continue
            raise ValueError(f"Missing packed response block for {thread_id}.")
        block = text[start + len(start_marker) : end].strip()
        try:
            parsed[thread_id] = _parse_batch_block(block, thread_id)
        except ValueError as exc:
            if not allow_partial:
                raise
            parsed[thread_id] = {"error": str(exc)}
    return parsed


def sanitized_controlled_thread(thread: EmailThread, *, account_email: str = "") -> EmailThread:
    replacement = account_email.strip() or "mailassist-test-user"

    def sanitize_address(value: str) -> str:
        cleaned = str(value or "").strip()
        if cleaned.lower() == "you@example.com":
            return replacement
        return cleaned

    messages: list[EmailMessage] = []
    for message in thread.messages:
        messages.append(
            replace(
                message,
                sender=sanitize_address(message.sender),
                to=[sanitize_address(item) for item in message.to],
            )
        )
    return replace(
        thread,
        participants=[sanitize_address(item) for item in thread.participants],
        messages=messages,
    )


def _parse_batch_block(block: str, thread_id: str) -> dict[str, Any]:
    classification_match = re.search(r"^CLASSIFICATION:\s*(.+)$", block, flags=re.MULTILINE)
    body_match = re.search(r"^BODY:\s*\n?(.*)$", block, flags=re.MULTILINE | re.DOTALL)
    if classification_match is None:
        raise ValueError(f"Missing classification for {thread_id}.")
    if body_match is None:
        raise ValueError(f"Missing body marker for {thread_id}.")

    classification = normalize_classification(classification_match.group(1))
    if classification == "unclassified":
        raise ValueError(f"Invalid classification for {thread_id}.")
    return {
        "classification": classification,
        "body": body_match.group(1).strip(),
    }


def _chunks(items: list[tuple[EmailThread, str]], size: int) -> list[list[tuple[EmailThread, str]]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _combine_generation_errors(*errors: object) -> str | None:
    cleaned = [str(error).strip() for error in errors if str(error or "").strip()]
    if not cleaned:
        return None
    return "; ".join(cleaned)


def _fallback_generation_failed(generation_model: object, generation_error: object) -> bool:
    return bool(str(generation_error or "").strip()) and str(generation_model or "").strip() == "fallback"


def _latest_message_id(thread: EmailThread) -> str:
    if not thread.messages:
        return ""
    return thread.messages[-1].message_id


def _latest_sender(thread: EmailThread) -> str:
    if not thread.messages:
        return ""
    return thread.messages[-1].sender.strip().lower()


def _latest_message_timestamp(thread: EmailThread) -> str:
    if not thread.messages:
        return ""
    return str(thread.messages[-1].sent_at or "").strip()


def _emit_progress(
    callback: Callable[[dict[str, Any]], None] | None,
    event: dict[str, Any],
) -> None:
    if callback is not None:
        callback(event)


def _safe_progress_event(event: dict[str, Any], *, provider_name: str) -> dict[str, Any]:
    safe: dict[str, Any] = {
        "type": str(event.get("type") or ""),
        "provider": str(event.get("provider") or provider_name),
    }
    for key in (
        "classification",
        "reason",
        "message_timestamp",
        "provider_draft_id",
        "generation_model",
        "generation_error",
        "dry_run",
        "message",
        "wait_seconds",
        "waited_seconds",
    ):
        if key in event and event.get(key) is not None:
            safe[key] = event[key]
    return safe


def _emit_classification_progress(
    callback: Callable[[dict[str, Any]], None] | None,
    *,
    provider_name: str,
    classification: str,
) -> None:
    _emit_progress(
        callback,
        {
            "type": "email_classified",
            "provider": provider_name,
            "classification": normalize_classification(classification),
        },
    )


def provider_caught_up_message_timestamp(root_dir: Path, provider_name: str) -> str:
    state = load_bot_state(root_dir)
    provider_slot = state.get("providers", {}).get(provider_name, {})
    if not isinstance(provider_slot, dict):
        return ""
    return _provider_cursor_timestamp(provider_slot)


def _watch_thread_candidates_for_provider(
    provider: DraftProvider,
    settings: Settings,
    *,
    received_after: datetime | None = None,
) -> list[tuple[EmailThread, str | None]]:
    base_filter = WatcherFilter.from_settings(settings)
    watcher_filter = WatcherFilter(
        unread_only=base_filter.unread_only,
        max_age_seconds=base_filter.max_age_seconds,
        received_after=received_after,
    )
    now = datetime.now(timezone.utc)
    if provider.name == "mock":
        return _oldest_first_candidates([
            (thread, thread_passes_filter(thread, watcher_filter, now=now)[1])
            for thread in build_mock_threads()
        ])

    lister = getattr(provider, "list_candidate_threads", None)
    if callable(lister):
        try:
            try:
                listed = list(lister(watcher_filter))
            except TypeError:
                listed = list(lister())
            return _oldest_first_candidates([
                (thread, thread_passes_filter(thread, watcher_filter, now=now)[1])
                for thread in listed
            ])
        except NotImplementedError:
            pass

    lister = getattr(provider, "list_actionable_threads", None)
    if callable(lister):
        try:
            return _oldest_first_candidates([(thread, None) for thread in list(lister(watcher_filter))])
        except NotImplementedError:
            pass

    return _oldest_first_candidates([
        (thread, thread_passes_filter(thread, watcher_filter, now=now)[1])
        for thread in build_mock_threads()
    ])


def _oldest_first_candidates(
    candidates: list[tuple[EmailThread, str | None]]
) -> list[tuple[EmailThread, str | None]]:
    return sorted(candidates, key=lambda item: _message_sort_timestamp(item[0]))


def _message_sort_timestamp(thread: EmailThread) -> datetime:
    parsed = _parse_message_timestamp(_latest_message_timestamp(thread))
    if parsed is None:
        return datetime.max.replace(tzinfo=timezone.utc)
    return parsed


def _ensure_provider_cursor(
    state: dict[str, Any],
    *,
    provider_name: str,
    provider_slot: dict[str, Any],
    settings: Settings,
) -> datetime | None:
    timestamp = _provider_cursor_timestamp(provider_slot)
    if not timestamp:
        timestamp = _latest_known_provider_timestamp(state, provider_name=provider_name)
        if timestamp:
            _set_provider_cursor(provider_slot, timestamp)
            state["updated_at"] = utc_now_iso()
            save_bot_state(settings.root_dir, state)
    return _parse_message_timestamp(timestamp)


def _provider_cursor_timestamp(provider_slot: dict[str, Any]) -> str:
    cursor = provider_slot.setdefault("cursor", {})
    if not isinstance(cursor, dict):
        cursor = {}
        provider_slot["cursor"] = cursor
    return str(cursor.get("last_scanned_message_timestamp", "") or "").strip()


def _set_provider_cursor(provider_slot: dict[str, Any], timestamp: str) -> None:
    cursor = provider_slot.setdefault("cursor", {})
    if not isinstance(cursor, dict):
        cursor = {}
        provider_slot["cursor"] = cursor
    cursor["last_scanned_message_timestamp"] = timestamp
    cursor["updated_at"] = utc_now_iso()


def _advance_provider_cursor(provider_slot: dict[str, Any], event: dict[str, Any]) -> None:
    if str(event.get("type") or "") not in CURSOR_ADVANCING_EVENT_TYPES:
        return
    timestamp = str(event.get("message_timestamp", "") or "").strip()
    if not timestamp:
        return
    current = _provider_cursor_timestamp(provider_slot)
    if _is_newer_timestamp(timestamp, current):
        _set_provider_cursor(provider_slot, _normalized_message_timestamp(timestamp))


def _latest_known_provider_timestamp(
    state: dict[str, Any],
    *,
    provider_name: str,
) -> str:
    provider_slot = state.get("providers", {}).get(provider_name, {})
    candidates: list[str] = []
    if isinstance(provider_slot, dict):
        threads = provider_slot.get("threads", {})
        if isinstance(threads, dict):
            for record in threads.values():
                if isinstance(record, dict):
                    candidates.append(str(record.get("message_timestamp", "") or ""))
    for event in state.get("recent_activity", []):
        if not isinstance(event, dict):
            continue
        if str(event.get("provider", "") or "") == provider_name:
            if str(event.get("type", "") or "") not in CURSOR_ADVANCING_EVENT_TYPES:
                continue
            candidates.append(str(event.get("message_timestamp", "") or ""))
    newest = ""
    for candidate in candidates:
        if _is_newer_timestamp(candidate, newest):
            newest = _normalized_message_timestamp(candidate)
    return newest


def _is_newer_timestamp(candidate: str, current: str) -> bool:
    parsed_candidate = _parse_message_timestamp(candidate)
    if parsed_candidate is None:
        return False
    parsed_current = _parse_message_timestamp(current)
    if parsed_current is None:
        return True
    return parsed_candidate > parsed_current


def _normalized_message_timestamp(value: str) -> str:
    parsed = _parse_message_timestamp(value)
    if parsed is None:
        return value.strip()
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_message_timestamp(value: str) -> datetime | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    if cleaned.endswith("Z"):
        cleaned = f"{cleaned[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def reply_recipients_for_thread(thread: EmailThread, user_address: str = "you@example.com") -> list[str]:
    if thread.messages:
        latest_sender = _normalized_email_address(thread.messages[-1].sender)
        if latest_sender and latest_sender != _normalized_email_address(user_address):
            return [latest_sender]
    return [
        address
        for address in _unique_email_addresses(thread.participants)
        if address != _normalized_email_address(user_address)
    ]


def reply_cc_for_thread(thread: EmailThread, user_address: str = "you@example.com") -> list[str]:
    if not thread.messages:
        return []
    latest = thread.messages[-1]
    blocked = {
        _normalized_email_address(user_address),
        *reply_recipients_for_thread(thread, user_address=user_address),
    }
    return [
        address
        for address in _unique_email_addresses([*latest.to, *latest.cc])
        if address and address not in blocked
    ]


def _normalized_email_address(address: object) -> str:
    return str(address or "").strip().lower()


def _unique_email_addresses(addresses: list[str] | tuple[str, ...]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for address in addresses:
        normalized = _normalized_email_address(address)
        if normalized and normalized not in seen:
            cleaned.append(normalized)
            seen.add(normalized)
    return cleaned


def ensure_substantive_reply_body(thread: EmailThread, body: str, *, signature: str = "") -> str:
    cleaned = strip_configured_signature(body, signature=signature)
    if has_substantive_reply_text(cleaned, signature=signature) and not has_promise_shaped_language(
        cleaned
    ):
        return append_signature(cleaned, signature=signature)
    return conservative_acknowledgement_body(signature=signature)


def append_signature(body: str, *, signature: str = "") -> str:
    return append_signature_to_body(body, signature=signature)


def append_draft_attribution(
    body: str,
    *,
    model: str,
    placement: str = ATTRIBUTION_HIDE,
    signature: str = "",
) -> str:
    cleaned = body.strip()
    if placement == ATTRIBUTION_HIDE:
        return cleaned
    attribution = attribution_text(model)
    if not attribution:
        return cleaned
    cleaned_signature = signature.strip()
    body_without_signature = strip_configured_signature(cleaned, signature=cleaned_signature)
    has_signature = cleaned_signature and body_without_signature != cleaned
    if has_signature:
        if placement == ATTRIBUTION_ABOVE_SIGNATURE:
            parts = [body_without_signature, attribution, cleaned_signature]
        else:
            parts = [body_without_signature, cleaned_signature, attribution]
        return "\n\n".join(part for part in parts if part.strip())
    return f"{cleaned}\n\n{attribution}" if cleaned else attribution


def build_draft_body_html(
    thread: EmailThread,
    body: str,
    *,
    signature: str = "",
    signature_html: str = "",
    model: str = "",
    include_attribution: bool = False,
    attribution_placement: str | None = None,
    user_address: str = "you@example.com",
    include_review_context: bool = True,
) -> str | None:
    placement = attribution_placement
    if placement is None:
        placement = ATTRIBUTION_BELOW_SIGNATURE if include_attribution else ATTRIBUTION_HIDE
    rich_signature = sanitize_html_fragment(signature_html)
    if rich_signature and not html_to_plain_text(rich_signature):
        rich_signature = ""
    include_attribution = placement != ATTRIBUTION_HIDE
    if not rich_signature and not include_attribution:
        return None
    body_without_plain_signature = body.strip()
    if include_attribution:
        attribution = attribution_text(model)
        if body_without_plain_signature.endswith(attribution):
            body_without_plain_signature = body_without_plain_signature[: -len(attribution)].rstrip()
    body_without_plain_signature = strip_configured_signature(
        body_without_plain_signature,
        signature=signature,
    )
    if include_attribution:
        attribution = attribution_text(model)
        if body_without_plain_signature.endswith(attribution):
            body_without_plain_signature = body_without_plain_signature[: -len(attribution)].rstrip()
    html_body = plain_text_to_html(body_without_plain_signature)
    signature_fragment = rich_signature or (plain_text_to_html(signature) if signature.strip() else "")
    attribution_fragment = attribution_html(model) if include_attribution else ""
    if placement == ATTRIBUTION_ABOVE_SIGNATURE:
        if attribution_fragment:
            html_body = f"{html_body}{attribution_fragment}"
        if signature_fragment:
            html_body = f"{html_body}<br>{signature_fragment}"
    else:
        if signature_fragment:
            html_body = f"{html_body}<br>{signature_fragment}"
        if attribution_fragment:
            html_body = f"{html_body}{attribution_fragment}"
    if not include_review_context:
        return sanitize_html_fragment(html_body)
    return body_with_review_context_html(thread, html_body, user_address=user_address)


def reply_metadata_for_thread(thread: EmailThread, *, user_address: str = "") -> dict[str, Any]:
    if not thread.messages:
        return {}
    latest = thread.messages[-1]
    in_reply_to = str(getattr(latest, "rfc_message_id", "") or "").strip()
    references = [
        str(item).strip()
        for item in getattr(latest, "references", [])
        if str(item).strip()
    ]
    if in_reply_to and in_reply_to not in references:
        references.append(in_reply_to)
    return {
        "from_address": reply_from_address_for_thread(thread, user_address=user_address) or None,
        "reply_to_message_id": latest.message_id or None,
        "reply_to_rfc_message_id": in_reply_to or None,
        "reply_references": references,
        "reply_to_message_unread": thread.unread,
    }


def reply_from_address_for_thread(thread: EmailThread, *, user_address: str = "") -> str:
    if not thread.messages:
        return ""
    latest = thread.messages[-1]
    recipients = [address.strip().lower() for address in latest.to if address.strip()]
    cleaned_user = user_address.strip().lower()
    if cleaned_user and cleaned_user in recipients:
        return cleaned_user
    if len(recipients) == 1:
        return recipients[0]
    return ""


def strip_configured_signature(body: str, *, signature: str = "") -> str:
    cleaned = body.strip()
    cleaned_signature = signature.strip()
    if cleaned_signature and cleaned.lower().endswith(cleaned_signature.lower()):
        return cleaned[: -len(cleaned_signature)].rstrip()
    return cleaned


def has_promise_shaped_language(body: str) -> bool:
    promise_verbs = (
        "call",
        "check",
        "confirm",
        "contact",
        "follow up",
        "get",
        "let you know",
        "provide",
        "send",
        "update",
    )
    alternatives = "|".join(re.escape(verb) for verb in promise_verbs)
    patterns = [
        rf"\bI\s+will\s+({alternatives})\b",
        rf"\bI'll\s+({alternatives})\b",
        rf"\bI\s+am\s+going\s+to\s+({alternatives})\b",
        rf"\bI\b[^.!?\n]{{0,120}}\bwill\s+({alternatives})\b",
    ]
    return any(re.search(pattern, body, flags=re.IGNORECASE) for pattern in patterns)


def has_substantive_reply_text(body: str, *, signature: str = "") -> bool:
    cleaned = body.strip()
    if not cleaned:
        return False
    signature_lines = {line.strip().lower() for line in signature.splitlines() if line.strip()}
    generic_lines = {"best", "best,", "thanks", "thanks,", "thank you", "regards", "regards,"}
    content_lines = []
    for line in cleaned.splitlines():
        normalized = line.strip().lower()
        if not normalized:
            continue
        if normalized in signature_lines or normalized in generic_lines:
            continue
        if "@" in normalized and len(normalized.split()) == 1:
            continue
        content_lines.append(line.strip())
    content = " ".join(content_lines)
    return bool(re.search(r"[A-Za-z].{12,}", content))


def conservative_acknowledgement_body(*, signature: str = "") -> str:
    return append_signature("Thanks for the note. I am reviewing this.", signature=signature)


def body_with_review_context(
    thread: EmailThread,
    body: str,
    *,
    user_address: str = "you@example.com",
) -> str:
    context_messages = review_context_messages(thread, user_address=user_address)
    if not context_messages:
        return body.strip()
    blocks = []
    for message in context_messages:
        quoted = "\n".join(f"> {line}" if line else ">" for line in message.text.strip().splitlines())
        blocks.append(
            f"{message.sender} wrote {human_review_context_time(message.sent_at)}:\n{quoted}"
        )
    return "Review context - delete before sending:\n" + "\n\n".join(blocks) + f"\n\n---\n\n{body.strip()}"


def body_with_review_context_html(
    thread: EmailThread,
    body_html: str,
    *,
    user_address: str = "you@example.com",
) -> str:
    context_messages = review_context_messages(thread, user_address=user_address)
    if not context_messages:
        return sanitize_html_fragment(body_html)
    blocks = []
    for message in context_messages:
        quoted = plain_text_to_html(message.text.strip())
        blocks.append(
            f"<p><strong>{message.sender} wrote {human_review_context_time(message.sent_at)}:</strong></p>"
            f"<blockquote>{quoted}</blockquote>"
        )
    context = (
        "<p><strong>Review context - delete before sending:</strong></p>"
        + "".join(blocks)
        + "<hr>"
    )
    return sanitize_html_fragment(context + body_html)


def review_context_messages(
    thread: EmailThread,
    *,
    user_address: str = "you@example.com",
    max_messages: int = 2,
) -> list[Any]:
    if not thread.messages:
        return []
    incoming = [message for message in thread.messages if message.sender != user_address]
    if incoming:
        return incoming[-max_messages:]
    return thread.messages[-max_messages:]


def _resolve_account_email(state: dict[str, Any], provider: DraftProvider) -> str:
    provider_accounts = state.setdefault("provider_accounts", {})
    discovered = _discover_account_email(provider)
    if discovered:
        provider_accounts[provider.name] = discovered
        state["account_email"] = discovered
        return discovered

    provider_specific = str(provider_accounts.get(provider.name, "")).strip()
    if provider_specific:
        return provider_specific

    fallback = str(state.get("account_email", "")).strip()
    if fallback:
        return fallback
    return "you@example.com"


def _append_recent_activity(
    state: dict[str, Any],
    *,
    provider_name: str,
    event: dict[str, Any],
    limit: int = 50,
) -> None:
    recent_activity = state.setdefault("recent_activity", [])
    recent_activity.append(
        {
            "timestamp": utc_now_iso(),
            "provider": provider_name,
            "type": str(event.get("type", "")),
            "thread_id": str(event.get("thread_id", "")),
            "subject": str(event.get("subject", "")),
            "classification": str(event.get("classification", "")),
            "reason": str(event.get("reason", "")) or None,
            "provider_draft_id": str(event.get("provider_draft_id", "")) or None,
            "message_timestamp": str(event.get("message_timestamp", "")) or None,
        }
    )
    if len(recent_activity) > limit:
        del recent_activity[:-limit]


def _discover_account_email(provider: DraftProvider) -> str | None:
    getter = getattr(provider, "get_account_email", None)
    if not callable(getter):
        return None
    try:
        value = getter()
    except Exception:
        return None
    cleaned = str(value or "").strip().lower()
    return cleaned or None


def human_review_context_time(
    sent_at: str,
    *,
    now: datetime | None = None,
    use_24_hour_clock: bool | None = None,
) -> str:
    sent = _parse_message_datetime(sent_at)
    if now is None:
        local_sent = sent.astimezone()
        local_now = datetime.now().astimezone(local_sent.tzinfo)
    else:
        local_now = now if now.tzinfo is not None else now.astimezone()
        local_sent = sent.astimezone(local_now.tzinfo)
    day_delta = (local_now.date() - local_sent.date()).days
    clock = _format_clock(local_sent, use_24_hour_clock=use_24_hour_clock)
    part_of_day = _part_of_day(local_sent.hour)
    if day_delta == 0:
        return f"this {part_of_day} at {clock}"
    if day_delta == 1:
        return f"yesterday {part_of_day} at {clock}"
    if 1 < day_delta < 7:
        return f"on {local_sent.strftime('%A')} at {clock}"
    return f"on {local_sent.strftime('%b')} {local_sent.day}, {local_sent.year} at {clock}"


def _parse_message_datetime(value: str) -> datetime:
    cleaned = value.strip()
    if cleaned.endswith("Z"):
        cleaned = f"{cleaned[:-1]}+00:00"
    return datetime.fromisoformat(cleaned)


def _format_clock(value: datetime, *, use_24_hour_clock: bool | None = None) -> str:
    if use_24_hour_clock is None:
        use_24_hour_clock = _system_uses_24_hour_clock()
    if use_24_hour_clock:
        return value.strftime("%H:%M")
    return value.strftime("%I:%M %p").lstrip("0")


@lru_cache(maxsize=1)
def _system_uses_24_hour_clock() -> bool:
    if platform.system() == "Darwin":
        try:
            value = subprocess.run(
                ["defaults", "read", "-g", "AppleICUForce24HourTime"],
                check=False,
                capture_output=True,
                text=True,
                timeout=1,
            ).stdout.strip().lower()
        except (OSError, subprocess.SubprocessError):
            value = ""
        if value in {"1", "true", "yes"}:
            return True
        if value in {"0", "false", "no"}:
            return False

    try:
        time_format = locale.nl_langinfo(locale.T_FMT)
    except (AttributeError, ValueError):
        time_format = ""
    normalized = time_format.lower()
    if "%p" in normalized or "%i" in normalized:
        return False
    if "%h" in normalized or "%k" in normalized:
        return True
    return False


def _part_of_day(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 21:
        return "evening"
    return "night"


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
        "message_timestamp": _latest_message_timestamp(thread),
        "classification": classification,
        "action": action,
        "generation_model": generation_model,
        "generation_error": generation_error,
        "provider_draft_id": provider_draft_id,
        "updated_at": utc_now_iso(),
    }
