from __future__ import annotations

import json
import textwrap
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from mailassist.config import migrate_legacy_runtime_layout
from mailassist.fixtures.mock_threads import build_mock_threads
from mailassist.llm.ollama import OllamaClient
from mailassist.models import EmailThread, utc_now_iso
from mailassist.version import load_visible_version

REVIEW_STATE_SCHEMA_VERSION = 2
REVIEW_STATE_FILENAME = "review-inbox.json"
CLASSIFICATION_OPTIONS = (
    "urgent",
    "reply_needed",
    "automated",
    "no_response",
    "spam",
    "unclassified",
)
SET_ASIDE_CLASSIFICATIONS = {"automated", "no_response", "spam"}
CLASSIFICATION_PRIORITY = {
    "urgent": 0,
    "reply_needed": 1,
    "automated": 2,
    "no_response": 3,
    "spam": 4,
    "unclassified": 5,
}
STATUS_PRIORITY = {
    "pending_review": 0,
    "use_draft": 1,
    "ignored": 2,
    "user_replied": 3,
}
FILTER_LABELS = {
    "all": "All mail",
    "needs_reply": "Needs reply",
    "set_aside": "Set aside",
    "urgent": "Urgent",
    "reply_needed": "Reply needed",
    "automated": "Automated",
    "no_response": "No response",
    "spam": "Spam",
}
STATUS_FILTER_LABELS = {
    "all": "Any status",
    "pending_review": "Pending review",
    "use_draft": "Draft selected",
    "ignored": "Ignored",
    "user_replied": "User replied",
}
SORT_LABELS = {
    "classification": "Classification",
    "received_at": "Received date",
    "sender": "Sender",
}
CANDIDATE_BLUEPRINTS = [
    (
        "option-a",
        "Option A",
        "direct and executive",
        "Keep it concise, confident, and practical. Confirm what can be done now and name one next step.",
    ),
    (
        "option-b",
        "Option B",
        "warm and collaborative",
        "Sound thoughtful and calm. Acknowledge the ask, explain any nuance briefly, and keep the tone encouraging.",
    ),
]
OPTION_A_SEPARATOR = "-- END OPTION A --"
OPTION_B_SEPARATOR = "-- END OPTION B --"
COMMON_DRAFTING_RULES = """- If a reply is appropriate, write as the recipient of the thread.
- Stay grounded in the thread. Do not invent status updates, dates, approvals, pricing, timelines, or deliverables.
- Match the language and register of the thread. If the sender writes in French, reply in French. If the sender uses informal French with `tu`, reply informally with `tu`; do not switch to formal `vous` unless the thread uses `vous` or a formal business register.
- Mirror the sender's level of formality without becoming sloppy. A short informal question should get a short informal answer.
- Do not turn email domains into company names unless that company name appears explicitly in the thread.
- If the email asks the user to approve, choose, confirm attendance, accept terms, authorize access, call someone, contact someone, check with another party, or make a business decision, do not invent the user's decision or promise the user will do the requested action. Draft a safe holding response that says the user is reviewing it, asks for missing detail, or leaves the action for the user to complete.
- Do not invent teams, reviewers, calendars, availability, internal processes, vendors, companies, or people that are not explicitly named in the thread.
- For choice requests like `Would you like us to hold an open house Saturday or Sunday?`, do not say the user will check with a team, decide availability, or confirm a future preference. Say the user is reviewing the options and leave the final choice for the user to add.
- Avoid promise-shaped phrases like `I will follow up`, `I will let you know`, `I'll let you know`, `I will call`, `I will check`, `I will contact`, `I will update`, or `I will confirm` unless the user already made that exact commitment in the thread. Prefer current-state language like `I am reviewing this` or `I am looking over the details`.
- If the thread uses relative timing like `today`, `tomorrow`, `this morning`, or `in the morning`, do not repeat that timing as a future promise.
- If information is missing, say so plainly instead of guessing."""


def candidate_display_label(tone: str) -> str:
    cleaned = tone.strip()
    if not cleaned:
        return "Draft"
    return cleaned[0].upper() + cleaned[1:]


def signature_prompt_block(signature: str) -> str:
    cleaned = signature.strip()
    if not cleaned:
        return (
            "- Do not include a sign-off, sender name, email address, placeholder, or signature block.\n"
            "- MailAssist will leave the response unsigned unless the user configures a signature."
        )
    return (
        "- Do not include a sign-off, sender name, email address, placeholder, or signature block.\n"
        "- MailAssist will append the user's saved signature after your response.\n"
        "- The saved signature is configured, but it is intentionally not shown to you."
    )


def append_signature_to_body(body: str, *, signature: str = "") -> str:
    cleaned = body.strip()
    cleaned_signature = signature.strip()
    if cleaned_signature and cleaned.lower().endswith(cleaned_signature.lower()):
        cleaned = cleaned[: -len(cleaned_signature)].rstrip()
    if cleaned and cleaned_signature:
        return f"{cleaned}\n\n{cleaned_signature}"
    return cleaned


def thread_to_payload(thread: EmailThread) -> dict[str, Any]:
    return {
        "thread_id": thread.thread_id,
        "subject": thread.subject,
        "participants": list(thread.participants),
        "messages": [
            {
                "message_id": message.message_id,
                "from": message.sender,
                "to": list(message.to),
                "sent_at": message.sent_at,
                "text": message.text,
            }
            for message in thread.messages
        ],
    }


def payload_to_thread(payload: dict[str, Any]) -> EmailThread:
    return EmailThread.from_dict(payload)


def format_thread_context(thread: EmailThread) -> str:
    lines = [
        f"Thread subject: {thread.subject}",
        f"Participants: {', '.join(thread.participants)}",
        "",
        "Messages:",
    ]
    for index, message in enumerate(thread.messages, start=1):
        lines.extend(
            [
                f"Message {index}",
                f"From: {message.sender}",
                f"To: {', '.join(message.to)}",
                f"Sent: {message.sent_at}",
                "Body:",
                message.text,
                "",
            ]
        )
    return "\n".join(lines).strip()


def build_review_candidates_prompt(
    thread: EmailThread,
    *,
    signature: str = "",
) -> str:
    option_instructions = "\n".join(
        [
            f"- {label}: use a {tone} style. {guidance}"
            for _, label, tone, guidance in CANDIDATE_BLUEPRINTS
        ]
    )
    return f"""You are MailAssist, a local-first email drafting assistant.

You have no hidden context beyond the thread shown below. Do not assume facts, attachments, commitments, permissions, or prior conversations that are not explicitly present in the provided thread.

Your job for this single thread:
1. Classify the thread for review triage.
2. Draft 2 candidate replies only if a reply is actually appropriate.

Classification rules:
- Use `urgent` when the sender is asking for a quick turnaround, a deadline is near, or the message clearly needs immediate attention.
- Use `reply_needed` when a human reply is appropriate but the thread is not obviously urgent.
- Use `automated` when the message is clearly machine-generated, newsletter-like, digest-like, or from a no-reply workflow.
- Use `no_response` when a human technically could respond but no response is actually appropriate.
- Use `spam` when the message is junk, deceptive, or obviously irrelevant.

Drafting rules:
- If classification is `automated`, `no_response`, or `spam`, return an empty email body.
- {COMMON_DRAFTING_RULES.replace(chr(10), chr(10) + "- ")[2:]}
- If classification is `urgent` or `reply_needed`, the body must contain at least one substantive sentence. Never return only a greeting, sign-off, or signature.
- Keep the draft under 140 words.
- Produce both candidate replies in one response so each option uses the full thread context.
- Signature rules:
{signature_prompt_block(signature)}
- Candidate instructions:
{option_instructions}

Output format requirements:
- First line must be exactly: `Classification: <value>`
- `<value>` must be one of: `urgent`, `reply_needed`, `automated`, `no_response`, `spam`
- Second line must be blank.
- After the blank line, write only the Option A body.
- End Option A with a line that is exactly: `{OPTION_A_SEPARATOR}`
- Then write only the Option B body.
- End Option B with a line that is exactly: `{OPTION_B_SEPARATOR}`
- If classification is `automated`, `no_response`, or `spam`, keep both option bodies empty but still include both separator lines.
- Do not use markdown fences.
- Do not add analysis, explanations, bullets, labels, or alternative options beyond the required separators.

Thread context:
{format_thread_context(thread)}
""".strip()


def build_single_review_candidate_prompt(
    thread: EmailThread,
    *,
    tone: str,
    guidance: str,
    existing_body: str = "",
    signature: str = "",
) -> str:
    alternative_instruction = ""
    if existing_body.strip():
        alternative_instruction = f"""

Existing draft in this same tone:
{existing_body.strip()}

Write a meaningfully different alternative. Do not copy phrases or sentence structure from the existing draft unless the thread requires it.
""".rstrip()

    return f"""You are MailAssist, a local-first email drafting assistant.

You have no hidden context beyond the thread shown below. Do not assume facts, attachments, commitments, permissions, or prior conversations that are not explicitly present in the provided thread.

Your job for this single thread:
1. Classify the thread for review triage.
2. Draft 1 candidate reply only if a reply is actually appropriate.

Classification rules:
- Use `urgent` when the sender is asking for a quick turnaround, a deadline is near, or the message clearly needs immediate attention.
- Use `reply_needed` when a human reply is appropriate but the thread is not obviously urgent.
- Use `automated` when the message is clearly machine-generated, newsletter-like, digest-like, or from a no-reply workflow.
- Use `no_response` when a human technically could respond but no response is actually appropriate.
- Use `spam` when the message is junk, deceptive, or obviously irrelevant.

Drafting rules:
- If classification is `automated`, `no_response`, or `spam`, return an empty email body.
- {COMMON_DRAFTING_RULES.replace(chr(10), chr(10) + "- ")[2:]}
- If classification is `urgent` or `reply_needed`, the body must contain at least one substantive sentence. Never return only a greeting, sign-off, or signature.
- Keep the draft under 140 words.
- Signature rules:
{signature_prompt_block(signature)}
- Tone target: {tone}.
- Additional style guidance: {guidance}.{alternative_instruction}

Output format requirements:
- First line must be exactly: `Classification: <value>`
- `<value>` must be one of: `urgent`, `reply_needed`, `automated`, `no_response`, `spam`
- Second line must be blank.
- After the blank line, write only the candidate email body.
- Do not use markdown fences.
- Do not add analysis, explanations, bullets, or alternative options.

Thread context:
{format_thread_context(thread)}
""".strip()


def build_single_review_candidate_body_prompt(
    thread: EmailThread,
    *,
    tone: str,
    guidance: str,
    existing_body: str = "",
    signature: str = "",
) -> str:
    alternative_instruction = ""
    if existing_body.strip():
        alternative_instruction = f"""

Existing draft in this same tone:
{existing_body.strip()}

Write a meaningfully different alternative. Do not copy phrases or sentence structure from the existing draft unless the thread requires it.
""".rstrip()

    return f"""You are MailAssist, a local-first email drafting assistant.

You have no hidden context beyond the thread shown below. Do not assume facts, attachments, commitments, permissions, or prior conversations that are not explicitly present in the provided thread.

Your job for this single thread:
- Draft 1 replacement candidate reply only.

Drafting rules:
- Write only the email body. Do not include a classification line, heading, bullets, or explanation.
- {COMMON_DRAFTING_RULES.replace(chr(10), chr(10) + "- ")[2:]}
- The body must contain at least one substantive sentence. Never return only a greeting, sign-off, or signature.
- Keep the draft under 140 words.
- Signature rules:
{signature_prompt_block(signature)}
- Tone target: {tone}.
- Additional style guidance: {guidance}.{alternative_instruction}

Output format requirements:
- Return only the candidate email body.
- Do not use markdown fences.
- Do not add analysis or any preamble.

Thread context:
{format_thread_context(thread)}
""".strip()


def review_state_path(root_dir: Path) -> Path:
    return root_dir / "data" / "legacy" / REVIEW_STATE_FILENAME


def normalize_classification(value: str | None) -> str:
    cleaned = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if cleaned in CLASSIFICATION_OPTIONS:
        return cleaned
    if cleaned in {"normal", "reply", "respond", "needs_reply"}:
        return "reply_needed"
    if cleaned in {"auto", "auto_generated", "newsletter"}:
        return "automated"
    if cleaned in {"ignore", "skip"}:
        return "no_response"
    return "unclassified"


def normalize_review_status(value: str | None) -> str:
    cleaned = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if cleaned in {"use_draft", "ready", "green_lit", "approved", "done"}:
        return "use_draft"
    if cleaned in {"ignored", "red_lit"}:
        return "ignored"
    if cleaned == "user_replied":
        return "user_replied"
    return "pending_review"


def fallback_classification_for_thread(thread: EmailThread) -> str:
    haystack = " ".join(
        [thread.subject, *thread.participants, *(message.text for message in thread.messages)]
    ).lower()
    if any(
        token in haystack
        for token in (
            "unsubscribe",
            "no-reply",
            "automated email",
            "automated notification",
            "digest",
        )
    ):
        return "automated"
    if any(token in haystack for token in ("lottery", "crypto", "wire money", "act now")):
        return "spam"
    if any(
        token in haystack
        for token in (
            "action needed",
            "end of day",
            "urgent",
            "asap",
            "friday morning",
            "before 3pm",
            "before tomorrow",
            "this afternoon",
        )
    ):
        return "urgent"
    return "reply_needed"


def merge_classification(model_classification: str, heuristic_classification: str) -> str:
    model_classification = normalize_classification(model_classification)
    heuristic_classification = normalize_classification(heuristic_classification)
    if heuristic_classification in SET_ASIDE_CLASSIFICATIONS and model_classification not in {"urgent", "spam"}:
        return heuristic_classification
    if model_classification == "unclassified":
        return heuristic_classification
    return model_classification


def extract_classification_and_body(response: str) -> tuple[str, str]:
    text = response.strip()
    if not text:
        return "unclassified", ""

    first_line, _, remainder = text.partition("\n")
    if ":" in first_line:
        label, value = first_line.split(":", 1)
        if label.strip().lower() == "classification":
            return normalize_classification(value), remainder.strip()
    return "unclassified", text


def extract_streaming_candidate_body(response: str) -> str:
    normalized = response.replace("\r\n", "\n")
    if not normalized.startswith("Classification:"):
        return ""
    first_break = normalized.find("\n")
    if first_break < 0:
        return ""
    remainder = normalized[first_break + 1 :]
    if not remainder.startswith("\n"):
        return ""
    return remainder[1:]


def extract_classification_and_bodies(response: str) -> tuple[str, list[str]]:
    classification, body = extract_classification_and_body(response)
    option_one, separator, remainder = body.partition(OPTION_A_SEPARATOR)
    if not separator:
        raise ValueError(f"Missing separator: {OPTION_A_SEPARATOR}")
    option_two, separator, trailing = remainder.partition(OPTION_B_SEPARATOR)
    if not separator:
        raise ValueError(f"Missing separator: {OPTION_B_SEPARATOR}")
    if trailing.strip():
        raise ValueError("Unexpected trailing content after the final option separator.")
    return classification, [option_one.strip(), option_two.strip()]


def resolve_thread_classification(candidates: list[dict[str, Any]], thread: EmailThread) -> str:
    classifications = [
        normalize_classification(candidate.get("classification")) for candidate in candidates
    ]
    classifications = [item for item in classifications if item != "unclassified"]
    if not classifications:
        return fallback_classification_for_thread(thread)

    counts = Counter(classifications)
    return min(
        counts,
        key=lambda item: (-counts[item], CLASSIFICATION_PRIORITY.get(item, 99)),
    )


def default_review_state() -> dict[str, Any]:
    threads = []
    for thread in build_mock_threads():
        threads.append(
            {
                "thread_id": thread.thread_id,
                "thread": thread_to_payload(thread),
                "subject": thread.subject,
                "status": "pending_review",
                "selected_candidate_id": None,
                "candidate_generation_error": None,
                "candidate_generation_model": None,
                "classification": "unclassified",
                "classification_source": None,
                "classification_updated_at": None,
                "candidates": [],
            }
        )
    return {
        "schema_version": REVIEW_STATE_SCHEMA_VERSION,
        "generated_at": utc_now_iso(),
        "threads": threads,
    }


def list_available_models(base_url: str, selected_model: str) -> tuple[list[str], str]:
    try:
        return OllamaClient(base_url, selected_model).list_models(), ""
    except RuntimeError as exc:
        return [], str(exc)


def resolve_generation_model(selected_model: str, models: list[str]) -> str:
    if selected_model in models:
        return selected_model
    if models:
        return models[0]
    raise RuntimeError("No Ollama models were available for review draft generation.")


def build_fallback_candidates(
    thread: EmailThread,
    *,
    signature: str = "",
) -> tuple[list[dict[str, Any]], str]:
    classification = fallback_classification_for_thread(thread)
    latest = thread.messages[-1].text
    preview = textwrap.shorten(latest, width=120, placeholder="...")
    fallback = []
    for candidate_id, label, tone, _ in CANDIDATE_BLUEPRINTS:
        if classification in SET_ASIDE_CLASSIFICATIONS:
            body = ""
        elif tone == "direct and executive":
            body = append_signature_to_body(
                f"Thanks for the note. I am reviewing this. The main point I am looking at is: {preview}",
                signature=signature,
            )
        else:
            body = append_signature_to_body(
                f"Thanks for the follow-up. I am looking over the details now. The key item I am reviewing is: {preview}",
                signature=signature,
            )
        fallback.append(
            {
                "candidate_id": candidate_id,
                "label": candidate_display_label(tone),
                "tone": tone,
                "classification": classification,
                "body": body,
                "original_body": body,
                "status": "pending_review",
                "generated_by": "fallback",
                "generated_at": utc_now_iso(),
                "edited_at": None,
            }
        )
    return fallback, classification


def build_fallback_candidate(
    thread: EmailThread,
    *,
    candidate_id: str,
    tone: str,
    signature: str = "",
) -> tuple[dict[str, Any], str]:
    candidates, classification = build_fallback_candidates(thread, signature=signature)
    fallback = next((item for item in candidates if item["candidate_id"] == candidate_id), None)
    if fallback is None:
        raise ValueError("Fallback candidate blueprint not found.")
    fallback["label"] = candidate_display_label(tone)
    fallback["tone"] = tone
    return fallback, classification


def generate_candidates_for_thread(
    thread: EmailThread,
    base_url: str,
    selected_model: str,
    *,
    signature: str = "",
) -> tuple[list[dict[str, Any]], Optional[str], Optional[str], str]:
    models, model_error = list_available_models(base_url, selected_model)
    if model_error:
        fallback_candidates, fallback_classification = build_fallback_candidates(
            thread,
            signature=signature,
        )
        return fallback_candidates, None, model_error, fallback_classification

    generation_model = resolve_generation_model(selected_model, models)
    llm = OllamaClient(base_url, generation_model)
    candidates: list[dict[str, Any]] = []
    heuristic_classification = fallback_classification_for_thread(thread)

    try:
        prompt = build_review_candidates_prompt(thread, signature=signature)
        response = llm.compose_reply(prompt)
        classification, bodies = extract_classification_and_bodies(response)
        classification = merge_classification(classification, heuristic_classification)
        if len(bodies) != len(CANDIDATE_BLUEPRINTS):
            raise RuntimeError("The local model did not return the expected number of draft options.")

        for (candidate_id, label, tone, _), body in zip(CANDIDATE_BLUEPRINTS, bodies):
            body = append_signature_to_body(body, signature=signature)
            candidates.append(
                {
                    "candidate_id": candidate_id,
                    "label": candidate_display_label(tone),
                    "tone": tone,
                    "classification": classification,
                    "body": body,
                    "original_body": body,
                    "status": "pending_review",
                    "generated_by": generation_model,
                    "generated_at": utc_now_iso(),
                    "edited_at": None,
                }
            )
    except (RuntimeError, ValueError) as exc:
        fallback_candidates, fallback_classification = build_fallback_candidates(
            thread,
            signature=signature,
        )
        return fallback_candidates, generation_model, str(exc), fallback_classification

    return candidates, generation_model, None, resolve_thread_classification(candidates, thread)


def generate_candidate_for_tone(
    thread: EmailThread,
    *,
    candidate_id: str,
    tone: str,
    guidance: str,
    base_url: str,
    selected_model: str,
    existing_body: str = "",
    signature: str = "",
) -> tuple[dict[str, Any], Optional[str], Optional[str], str]:
    models, model_error = list_available_models(base_url, selected_model)
    if model_error:
        fallback_candidate, fallback_classification = build_fallback_candidate(
            thread,
            candidate_id=candidate_id,
            tone=tone,
            signature=signature,
        )
        return fallback_candidate, None, model_error, fallback_classification

    generation_model = resolve_generation_model(selected_model, models)
    llm = OllamaClient(base_url, generation_model)
    heuristic_classification = fallback_classification_for_thread(thread)

    try:
        prompt = build_single_review_candidate_prompt(
            thread,
            tone=tone,
            guidance=guidance,
            existing_body=existing_body,
            signature=signature,
        )
        response = llm.compose_reply(prompt)
        classification, body = extract_classification_and_body(response)
        classification = merge_classification(classification, heuristic_classification)
        body = append_signature_to_body(body, signature=signature)
        candidate = {
            "candidate_id": candidate_id,
            "label": candidate_display_label(tone),
            "tone": tone,
            "classification": classification,
            "body": body,
            "original_body": body,
            "status": "pending_review",
            "generated_by": generation_model,
            "generated_at": utc_now_iso(),
            "edited_at": None,
        }
    except (RuntimeError, ValueError) as exc:
        fallback_candidate, fallback_classification = build_fallback_candidate(
            thread,
            candidate_id=candidate_id,
            tone=tone,
            signature=signature,
        )
        return fallback_candidate, generation_model, str(exc), fallback_classification

    return candidate, generation_model, None, classification


def stream_candidate_for_tone(
    thread: EmailThread,
    *,
    candidate_id: str,
    tone: str,
    guidance: str,
    base_url: str,
    selected_model: str,
    existing_body: str = "",
    on_body_update=None,
    signature: str = "",
) -> tuple[dict[str, Any], Optional[str], Optional[str], str]:
    models, model_error = list_available_models(base_url, selected_model)
    if model_error:
        fallback_candidate, fallback_classification = build_fallback_candidate(
            thread,
            candidate_id=candidate_id,
            tone=tone,
            signature=signature,
        )
        return fallback_candidate, None, model_error, fallback_classification

    generation_model = resolve_generation_model(selected_model, models)
    llm = OllamaClient(base_url, generation_model)
    classification = fallback_classification_for_thread(thread)

    try:
        prompt = build_single_review_candidate_body_prompt(
            thread,
            tone=tone,
            guidance=guidance,
            existing_body=existing_body,
            signature=signature,
        )
        raw_response = ""
        for chunk in llm.compose_reply_stream(prompt):
            raw_response += chunk
            if on_body_update is not None:
                on_body_update(chunk)
        body = append_signature_to_body(raw_response.strip(), signature=signature)
        candidate = {
            "candidate_id": candidate_id,
            "label": candidate_display_label(tone),
            "tone": tone,
            "classification": classification,
            "body": body,
            "original_body": body,
            "status": "pending_review",
            "generated_by": generation_model,
            "generated_at": utc_now_iso(),
            "edited_at": None,
        }
    except (RuntimeError, ValueError) as exc:
        fallback_candidate, fallback_classification = build_fallback_candidate(
            thread,
            candidate_id=candidate_id,
            tone=tone,
            signature=signature,
        )
        return fallback_candidate, generation_model, str(exc), fallback_classification

    return candidate, generation_model, None, classification


def load_review_state(root_dir: Path) -> dict[str, Any]:
    migrate_legacy_runtime_layout(root_dir)
    path = review_state_path(root_dir)
    if not path.exists():
        state = default_review_state()
        save_review_state(root_dir, state)
        return state

    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != REVIEW_STATE_SCHEMA_VERSION:
        state = default_review_state()
        save_review_state(root_dir, state)
        return state
    for thread_state in payload.get("threads", []):
        thread_state["status"] = normalize_review_status(thread_state.get("status"))
        thread_state["archived"] = bool(thread_state.get("archived", False))
        if "archive_selected" not in thread_state:
            thread_state["archive_selected"] = thread_state["status"] in {
                "use_draft",
                "ignored",
                "user_replied",
            }
        for candidate in thread_state.get("candidates", []):
            candidate["label"] = candidate_display_label(candidate.get("tone", candidate.get("label", "")))
            candidate_status = normalize_review_status(candidate.get("status"))
            if candidate_status == "use_draft":
                candidate["status"] = "use_draft"
            elif candidate.get("status") == "edited":
                candidate["status"] = "edited"
            elif candidate_status == "ignored":
                candidate["status"] = "ignored"
            else:
                candidate["status"] = "pending_review"
    return payload


def save_review_state(root_dir: Path, state: dict[str, Any]) -> None:
    path = review_state_path(root_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(state, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def find_thread_state(
    state: dict[str, Any], thread_id: str | None = None
) -> tuple[dict[str, Any], int]:
    threads = state.get("threads", [])
    if not threads:
        raise ValueError("Review inbox is empty.")

    if thread_id:
        for index, thread_state in enumerate(threads):
            if thread_state["thread_id"] == thread_id:
                return thread_state, index

    return threads[0], 0


def thread_last_sent_at(thread_state: dict[str, Any]) -> str:
    messages = thread_state.get("thread", {}).get("messages", [])
    if not messages:
        return ""
    return max(message.get("sent_at", "") for message in messages)


def thread_latest_sender(thread_state: dict[str, Any]) -> str:
    messages = thread_state.get("thread", {}).get("messages", [])
    if not messages:
        return ""
    latest = max(messages, key=lambda message: message.get("sent_at", ""))
    return str(latest.get("from", "")).lower()


def matches_classification_filter(thread_state: dict[str, Any], filter_classification: str) -> bool:
    classification = normalize_classification(thread_state.get("classification"))
    if filter_classification == "all":
        return True
    if filter_classification == "needs_reply":
        return classification in {"urgent", "reply_needed"}
    if filter_classification == "set_aside":
        return classification in SET_ASIDE_CLASSIFICATIONS
    return classification == filter_classification


def matches_status_filter(thread_state: dict[str, Any], filter_status: str) -> bool:
    if filter_status == "all":
        return True
    return normalize_review_status(thread_state.get("status")) == normalize_review_status(filter_status)


def filtered_and_sorted_threads(
    threads: list[dict[str, Any]],
    *,
    filter_classification: str,
    filter_status: str,
    sort_order: str,
    show_archived: bool = False,
) -> list[dict[str, Any]]:
    filtered = [
        item
        for item in threads
        if (show_archived or not item.get("archived", False))
        if matches_classification_filter(item, filter_classification)
        and matches_status_filter(item, filter_status)
    ]

    if sort_order == "received_at":
        return sorted(
            filtered,
            key=lambda item: (
                thread_last_sent_at(item),
                item["subject"].lower(),
            ),
            reverse=True,
        )
    if sort_order == "sender":
        return sorted(
            filtered,
            key=lambda item: (
                thread_latest_sender(item),
                item["subject"].lower(),
            ),
        )
    return sorted(
        filtered,
        key=lambda item: (
            CLASSIFICATION_PRIORITY.get(normalize_classification(item.get("classification")), 99),
            item["subject"].lower(),
        ),
    )


def regenerate_thread_candidates(
    state: dict[str, Any],
    thread_id: str,
    *,
    base_url: str,
    selected_model: str,
    signature: str = "",
) -> dict[str, Any]:
    thread_state, _ = find_thread_state(state, thread_id)
    thread = payload_to_thread(thread_state["thread"])
    candidates, generation_model, generation_error, classification = generate_candidates_for_thread(
        thread,
        base_url=base_url,
        selected_model=selected_model,
        signature=signature,
    )
    thread_state["candidates"] = candidates
    thread_state["candidate_generation_model"] = generation_model
    thread_state["candidate_generation_error"] = generation_error
    thread_state["classification"] = classification
    thread_state["classification_source"] = generation_model or "fallback"
    thread_state["classification_updated_at"] = utc_now_iso()
    thread_state["selected_candidate_id"] = None
    thread_state["status"] = "pending_review"
    state["generated_at"] = utc_now_iso()
    return thread_state


def regenerate_candidate_for_thread(
    state: dict[str, Any],
    thread_id: str,
    candidate_id: str,
    *,
    base_url: str,
    selected_model: str,
    signature: str = "",
) -> dict[str, Any]:
    thread_state, _ = find_thread_state(state, thread_id)
    thread = payload_to_thread(thread_state["thread"])
    blueprint = next((item for item in CANDIDATE_BLUEPRINTS if item[0] == candidate_id), None)
    if blueprint is None:
        raise ValueError("Candidate blueprint not found.")

    _, _, tone, guidance = blueprint
    existing_candidate = next(
        (item for item in thread_state.get("candidates", []) if item.get("candidate_id") == candidate_id),
        None,
    )
    existing_body = ""
    if existing_candidate is not None:
        existing_body = str(existing_candidate.get("body", ""))

    candidate, generation_model, generation_error, classification = generate_candidate_for_tone(
        thread,
        candidate_id=candidate_id,
        tone=tone,
        guidance=guidance,
        base_url=base_url,
        selected_model=selected_model,
        existing_body=existing_body,
        signature=signature,
    )

    replaced = False
    for index, current in enumerate(thread_state.get("candidates", [])):
        if current.get("candidate_id") == candidate_id:
            thread_state["candidates"][index] = candidate
            replaced = True
            break
    if not replaced:
        thread_state.setdefault("candidates", []).append(candidate)

    thread_state["candidate_generation_model"] = generation_model
    thread_state["candidate_generation_error"] = generation_error
    thread_state["classification"] = classification
    thread_state["classification_source"] = generation_model or "fallback"
    thread_state["classification_updated_at"] = utc_now_iso()
    if thread_state.get("status") != "ignored":
        if thread_state.get("selected_candidate_id") == candidate_id:
            thread_state["selected_candidate_id"] = None
        for item in thread_state.get("candidates", []):
            if item.get("candidate_id") != candidate_id and normalize_review_status(item.get("status")) != "ignored":
                item["status"] = "pending_review"
        thread_state["status"] = "pending_review"
    state["generated_at"] = utc_now_iso()
    return thread_state


def ensure_review_state(
    root_dir: Path,
    *,
    base_url: str,
    selected_model: str,
    signature: str = "",
) -> dict[str, Any]:
    state = load_review_state(root_dir)
    dirty = False
    for thread_state in state.get("threads", []):
        if not thread_state.get("candidates"):
            regenerate_thread_candidates(
                state,
                thread_state["thread_id"],
                base_url=base_url,
                selected_model=selected_model,
                signature=signature,
            )
            dirty = True
    if dirty:
        save_review_state(root_dir, state)
    return state


def update_candidate(
    thread_state: dict[str, Any],
    candidate_id: str,
    body: str,
    action: str,
) -> dict[str, Any]:
    candidate = next(
        (item for item in thread_state.get("candidates", []) if item["candidate_id"] == candidate_id),
        None,
    )
    if candidate is None:
        raise ValueError("Candidate not found.")

    cleaned = body.strip()

    if action == "save":
        candidate["body"] = cleaned
        candidate["edited_at"] = utc_now_iso()
        if normalize_review_status(candidate["status"]) != "use_draft":
            candidate["status"] = "edited"
        return candidate

    if action == "reset":
        candidate["body"] = candidate.get("original_body", "")
        candidate["edited_at"] = None
        if thread_state.get("selected_candidate_id") == candidate_id:
            candidate["status"] = "use_draft"
        else:
            candidate["status"] = "pending_review"
        return candidate

    if action in {"green_light", "use_this"}:
        candidate["body"] = cleaned
        candidate["edited_at"] = utc_now_iso()
        thread_state["selected_candidate_id"] = candidate_id
        thread_state["status"] = "use_draft"
        thread_state["archive_selected"] = True
        for item in thread_state.get("candidates", []):
            item["status"] = "use_draft" if item["candidate_id"] == candidate_id else "pending_review"
        return candidate

    if action in {"red_light", "ignore"}:
        candidate["body"] = cleaned
        candidate["edited_at"] = utc_now_iso()
        candidate["status"] = "ignored"
        thread_state["selected_candidate_id"] = None
        thread_state["status"] = "ignored"
        thread_state["archive_selected"] = True
        for item in thread_state.get("candidates", []):
            item["status"] = "ignored" if item["candidate_id"] == candidate_id else "pending_review"
        return candidate

    raise ValueError("Unsupported candidate action.")


def update_thread_status(thread_state: dict[str, Any], action: str) -> dict[str, Any]:
    if action == "ignore":
        thread_state["status"] = "ignored"
        thread_state["selected_candidate_id"] = None
        thread_state["archive_selected"] = True
        for candidate in thread_state.get("candidates", []):
            candidate["status"] = "pending_review"
        return thread_state

    if action == "close":
        return thread_state

    if action == "mark_user_replied":
        thread_state["status"] = "user_replied"
        thread_state["archive_selected"] = True
        return thread_state

    if action == "archive":
        thread_state["archived"] = True
        thread_state["archive_selected"] = True
        return thread_state

    if action == "unarchive":
        thread_state["archived"] = False
        return thread_state

    raise ValueError("Unsupported thread action.")
