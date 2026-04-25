from __future__ import annotations

import json
import locale
import platform
import re
import subprocess
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

from mailassist.config import Settings
from mailassist.gui.server import (
    SET_ASIDE_CLASSIFICATIONS,
    build_mock_threads,
    fallback_classification_for_thread,
    format_thread_context,
    generate_candidate_for_tone,
    list_available_models,
    merge_classification,
    normalize_classification,
    resolve_generation_model,
    signature_prompt_block,
)
from mailassist.llm.ollama import OllamaClient
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
    prompt = re.sub(r"(?m)^- If classification is `automated`, `no_response`, or `spam`, set `SHOULD_DRAFT: no` and leave `BODY:` empty\.\n", "", prompt)
    return prompt


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
    batch_size: int = 1,
) -> list[dict[str, Any]]:
    state = load_bot_state(settings.root_dir)
    provider_state = state.setdefault("providers", {}).setdefault(provider.name, {})
    events = []
    pending_threads: list[tuple[EmailThread, str]] = []

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

        pending_threads.append((thread, latest_message_id))

    for chunk in _chunks(pending_threads, max(1, batch_size)):
        tone_key = settings.user_tone
        tone, guidance = tone_guidance(tone_key)
        if len(chunk) > 1:
            try:
                generated = generate_batch_candidates_for_tone(
                    [thread for thread, _ in chunk],
                    tone=tone,
                    guidance=guidance,
                    base_url=base_url,
                    selected_model=selected_model,
                    signature=settings.user_signature,
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
                provider_state[thread.thread_id] = _state_record(
                    thread=thread,
                    latest_message_id=latest_message_id,
                    classification="unclassified",
                    action="skipped",
                    generation_error="Batch generation did not include this thread.",
                )
                events.append(
                    {
                        "type": "skipped_email",
                        "thread_id": thread.thread_id,
                        "subject": thread.subject,
                        "classification": "unclassified",
                        "reason": "missing_batch_result",
                        "generation_error": "Batch generation did not include this thread.",
                    }
                )
                continue

            classification = str(item.get("classification", "unclassified"))
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
                body=body_with_review_context(thread, body),
                model=str(generation_model or "fallback"),
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


def generate_batch_candidates_for_tone(
    threads: list[EmailThread],
    *,
    tone: str,
    guidance: str,
    base_url: str,
    selected_model: str,
    signature: str,
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
    )
    response = OllamaClient(base_url, generation_model).compose_reply(prompt)
    parsed = parse_batch_candidate_response(
        response,
        expected_thread_ids=[thread.thread_id for thread in threads],
    )
    results = {}
    for thread in threads:
        item = parsed[thread.thread_id]
        heuristic_classification = fallback_classification_for_thread(thread)
        classification = merge_classification(item["classification"], heuristic_classification)
        body = item["body"].strip() if item["should_draft"] else ""
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
) -> str:
    thread_sections = []
    for thread in threads:
        thread_sections.append(
            f"""INPUT THREAD {thread.thread_id}
{format_thread_context(thread)}
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
- If classification is `automated`, `no_response`, or `spam`, set `SHOULD_DRAFT: no` and leave `BODY:` empty.
- If a reply is appropriate, write as the recipient of that specific thread.
- Stay grounded in that thread only.
- Do not turn email domains into company names unless that company name appears explicitly in the thread.
- If the email asks the user to approve, choose, confirm attendance, accept terms, authorize access, call someone, contact someone, check with another party, or make a business decision, do not invent the user's decision or promise the user will do the requested action. Draft a safe holding response that says the user is reviewing it, asks for missing detail, or leaves the action for the user to complete.
- Do not invent teams, reviewers, calendars, availability, internal processes, vendors, companies, or people that are not explicitly named in the thread.
- For choice requests like `Would you like us to hold an open house Saturday or Sunday?`, do not say the user will check with a team, decide availability, or confirm a future preference. Say the user is reviewing the options and leave the final choice for the user to add.
- Avoid promise-shaped phrases like `I will follow up`, `I will let you know`, `I'll let you know`, `I will call`, `I will check`, `I will contact`, `I will update`, or `I will confirm` unless the user already made that exact commitment in the thread. Prefer current-state language like `I am reviewing this` or `I am looking over the details`.
- If the thread uses relative timing like `today`, `tomorrow`, `this morning`, or `in the morning`, do not repeat that timing as a future promise.
- If classification is `urgent` or `reply_needed`, the body must contain at least one substantive sentence. Never return only a greeting, sign-off, or signature.
- If information is missing, say so plainly instead of guessing.
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
SHOULD_DRAFT: <yes|no>
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
) -> dict[str, dict[str, Any]]:
    text = response.replace("\r\n", "\n").strip()
    parsed: dict[str, dict[str, Any]] = {}
    for thread_id in expected_thread_ids:
        start_marker = f"BEGIN THREAD {thread_id}"
        end_marker = f"-- END THREAD {thread_id} --"
        start = text.find(start_marker)
        end = text.find(end_marker, start + len(start_marker))
        if start < 0 or end < 0:
            raise ValueError(f"Missing packed response block for {thread_id}.")
        block = text[start + len(start_marker) : end].strip()
        parsed[thread_id] = _parse_batch_block(block, thread_id)
    return parsed


def _parse_batch_block(block: str, thread_id: str) -> dict[str, Any]:
    classification_match = re.search(r"^CLASSIFICATION:\s*(.+)$", block, flags=re.MULTILINE)
    should_draft_match = re.search(r"^SHOULD_DRAFT:\s*(.+)$", block, flags=re.MULTILINE)
    body_match = re.search(r"^BODY:\s*\n?(.*)$", block, flags=re.MULTILINE | re.DOTALL)
    if classification_match is None:
        raise ValueError(f"Missing classification for {thread_id}.")
    if should_draft_match is None:
        raise ValueError(f"Missing should-draft flag for {thread_id}.")
    if body_match is None:
        raise ValueError(f"Missing body marker for {thread_id}.")

    classification = normalize_classification(classification_match.group(1))
    if classification == "unclassified":
        raise ValueError(f"Invalid classification for {thread_id}.")
    should_draft_value = should_draft_match.group(1).strip().lower()
    if should_draft_value not in {"yes", "no"}:
        raise ValueError(f"Invalid should-draft flag for {thread_id}.")
    return {
        "classification": classification,
        "should_draft": should_draft_value == "yes",
        "body": body_match.group(1).strip(),
    }


def _chunks(items: list[tuple[EmailThread, str]], size: int) -> list[list[tuple[EmailThread, str]]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _combine_generation_errors(*errors: object) -> str | None:
    cleaned = [str(error).strip() for error in errors if str(error or "").strip()]
    if not cleaned:
        return None
    return "; ".join(cleaned)


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


def ensure_substantive_reply_body(thread: EmailThread, body: str, *, signature: str = "") -> str:
    cleaned = strip_configured_signature(body, signature=signature)
    if has_substantive_reply_text(cleaned, signature=signature) and not has_promise_shaped_language(
        cleaned
    ):
        return append_signature(cleaned, signature=signature)
    return conservative_acknowledgement_body(signature=signature)


def append_signature(body: str, *, signature: str = "") -> str:
    cleaned = strip_configured_signature(body, signature=signature)
    cleaned_signature = signature.strip()
    if cleaned and cleaned_signature:
        return f"{cleaned}\n\n{cleaned_signature}"
    return cleaned


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


def body_with_review_context(thread: EmailThread, body: str) -> str:
    context_messages = review_context_messages(thread)
    if not context_messages:
        return body.strip()
    blocks = []
    for message in context_messages:
        quoted = "\n".join(f"> {line}" if line else ">" for line in message.text.strip().splitlines())
        blocks.append(
            f"{message.sender} wrote {human_review_context_time(message.sent_at)}:\n{quoted}"
        )
    return "Review context - delete before sending:\n" + "\n\n".join(blocks) + f"\n\n---\n\n{body.strip()}"


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
        "classification": classification,
        "action": action,
        "generation_model": generation_model,
        "generation_error": generation_error,
        "provider_draft_id": provider_draft_id,
        "updated_at": utc_now_iso(),
    }
