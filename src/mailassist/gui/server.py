from __future__ import annotations

import html
import json
import textwrap
from collections import Counter
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, quote_plus, urlencode, urlparse

from mailassist.config import load_settings, read_env_file, write_env_file
from mailassist.llm.ollama import OllamaClient
from mailassist.models import EmailMessage, EmailThread, utc_now_iso

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


def candidate_display_label(tone: str) -> str:
    cleaned = tone.strip()
    if not cleaned:
        return "Draft"
    return cleaned[0].upper() + cleaned[1:]


def signature_prompt_block(signature: str) -> str:
    cleaned = signature.strip()
    if not cleaned:
        return (
            "- Do not add placeholders like `[Your Name]`, `[Name]`, or any made-up signature block.\n"
            "- If you include a sign-off, keep it natural and do not invent a sender name."
        )
    return (
        "- End the email body with exactly the signature block shown below.\n"
        "- Preserve the same text, punctuation, and line breaks.\n"
        "- Do not substitute names or invent any alternate sign-off.\n\n"
        "Signature block to use exactly:\n"
        f"{cleaned}"
    )


def build_mock_threads() -> list[EmailThread]:
    return [
        EmailThread(
            thread_id="thread-001",
            subject="Project kickoff follow-up",
            participants=["alex@example.com", "you@example.com"],
            messages=[
                EmailMessage(
                    message_id="msg-001",
                    sender="alex@example.com",
                    to=["you@example.com"],
                    sent_at="2026-04-24T08:30:00Z",
                    text=(
                        "Can you send the kickoff notes by end of day? I also want to confirm "
                        "whether the draft timeline still looks realistic."
                    ),
                ),
                EmailMessage(
                    message_id="msg-002",
                    sender="you@example.com",
                    to=["alex@example.com"],
                    sent_at="2026-04-24T08:42:00Z",
                    text="I can send the notes shortly. I am still reviewing the timeline.",
                ),
                EmailMessage(
                    message_id="msg-003",
                    sender="alex@example.com",
                    to=["you@example.com"],
                    sent_at="2026-04-24T08:55:00Z",
                    text=(
                        "Perfect. If the timeline has slipped, just tell me what changed and "
                        "what you need."
                    ),
                ),
            ],
        ),
        EmailThread(
            thread_id="thread-002",
            subject="Pricing proposal before Friday",
            participants=["maria@northstar.co", "you@example.com"],
            messages=[
                EmailMessage(
                    message_id="msg-101",
                    sender="maria@northstar.co",
                    to=["you@example.com"],
                    sent_at="2026-04-24T07:10:00Z",
                    text=(
                        "Checking in on the pricing proposal. If we can get a revised draft by "
                        "Friday morning, I can bring it into the client readout."
                    ),
                ),
                EmailMessage(
                    message_id="msg-102",
                    sender="maria@northstar.co",
                    to=["you@example.com"],
                    sent_at="2026-04-24T07:18:00Z",
                    text=(
                        "The main concern is whether we should keep the onboarding line item "
                        "separate or bundle it into the first phase."
                    ),
                ),
            ],
        ),
        EmailThread(
            thread_id="thread-003",
            subject="Your weekly analytics digest",
            participants=["no-reply@metrics.example", "you@example.com"],
            messages=[
                EmailMessage(
                    message_id="msg-201",
                    sender="no-reply@metrics.example",
                    to=["you@example.com"],
                    sent_at="2026-04-24T06:45:00Z",
                    text=(
                        "Your weekly analytics digest is ready. Traffic is up 12%. This is an "
                        "automated email. No reply is monitored. Visit the dashboard for details "
                        "or unsubscribe from this alert."
                    ),
                ),
            ],
        ),
        EmailThread(
            thread_id="thread-004",
            subject="Contract redlines before tomorrow",
            participants=["jordan@elmlegal.com", "you@example.com"],
            messages=[
                EmailMessage(
                    message_id="msg-301",
                    sender="jordan@elmlegal.com",
                    to=["you@example.com"],
                    sent_at="2026-04-24T09:12:00Z",
                    text=(
                        "I just sent the latest contract redlines. If we want to get this signed tomorrow, "
                        "I need your call on the indemnity clause by 10am."
                    ),
                ),
                EmailMessage(
                    message_id="msg-302",
                    sender="jordan@elmlegal.com",
                    to=["you@example.com"],
                    sent_at="2026-04-24T09:18:00Z",
                    text=(
                        "If you are okay with the fallback language, I can finalize the clean copy right away."
                    ),
                ),
            ],
        ),
        EmailThread(
            thread_id="thread-005",
            subject="Team lunch headcount",
            participants=["nina@example.com", "you@example.com"],
            messages=[
                EmailMessage(
                    message_id="msg-401",
                    sender="nina@example.com",
                    to=["you@example.com"],
                    sent_at="2026-04-24T10:05:00Z",
                    text=(
                        "Quick one: can you confirm whether you are in for the team lunch on Thursday? "
                        "I am locking the reservation this afternoon."
                    ),
                ),
            ],
        ),
        EmailThread(
            thread_id="thread-006",
            subject="Security awareness training reminder",
            participants=["it-ops@example.com", "you@example.com"],
            messages=[
                EmailMessage(
                    message_id="msg-501",
                    sender="it-ops@example.com",
                    to=["you@example.com"],
                    sent_at="2026-04-24T06:15:00Z",
                    text=(
                        "Reminder: your annual security awareness training is due next week. "
                        "This is an automated notification. Please complete the course in the portal."
                    ),
                ),
            ],
        ),
        EmailThread(
            thread_id="thread-007",
            subject="Customer quote follow-up",
            participants=["samira@brightforge.ai", "you@example.com"],
            messages=[
                EmailMessage(
                    message_id="msg-601",
                    sender="samira@brightforge.ai",
                    to=["you@example.com"],
                    sent_at="2026-04-24T11:02:00Z",
                    text=(
                        "Checking whether you had a chance to look at the updated quote. "
                        "If we can align on scope this week, I can keep the implementation window open."
                    ),
                ),
                EmailMessage(
                    message_id="msg-602",
                    sender="samira@brightforge.ai",
                    to=["you@example.com"],
                    sent_at="2026-04-24T11:09:00Z",
                    text=(
                        "The only item I still need clarity on is whether onboarding stays in phase one "
                        "or moves to a separate workstream."
                    ),
                ),
            ],
        ),
        EmailThread(
            thread_id="thread-008",
            subject="Action needed: approve vendor access",
            participants=["ops@harborhq.com", "you@example.com"],
            messages=[
                EmailMessage(
                    message_id="msg-701",
                    sender="ops@harborhq.com",
                    to=["you@example.com"],
                    sent_at="2026-04-24T11:26:00Z",
                    text=(
                        "Action needed: can you confirm whether BrightForge should receive temporary "
                        "workspace access for next week's onboarding? I need your approval before 3pm "
                        "so I can finish provisioning."
                    ),
                ),
                EmailMessage(
                    message_id="msg-702",
                    sender="ops@harborhq.com",
                    to=["you@example.com"],
                    sent_at="2026-04-24T11:31:00Z",
                    text=(
                        "If you want me to limit access to the shared project folder only, I can set it "
                        "up that way instead."
                    ),
                ),
            ],
        ),
    ]


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
- If a reply is appropriate, write as the recipient of the thread.
- Stay grounded in the thread. Do not invent status updates, dates, approvals, pricing, timelines, or deliverables.
- If information is missing, say so plainly instead of guessing.
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
- If a reply is appropriate, write as the recipient of the thread.
- Stay grounded in the thread. Do not invent status updates, dates, approvals, pricing, timelines, or deliverables.
- If information is missing, say so plainly instead of guessing.
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
- Stay grounded in the thread. Do not invent status updates, dates, approvals, pricing, timelines, or deliverables.
- If information is missing, say so plainly instead of guessing.
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
    return root_dir / "data" / REVIEW_STATE_FILENAME


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
    if any(token in haystack for token in ("unsubscribe", "no-reply", "automated email", "digest")):
        return "automated"
    if any(token in haystack for token in ("lottery", "crypto", "wire money", "act now")):
        return "spam"
    if any(token in haystack for token in ("end of day", "urgent", "asap", "friday morning")):
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
    signature_block = f"\n{signature.strip()}\n" if signature.strip() else ""
    fallback = []
    for candidate_id, label, tone, _ in CANDIDATE_BLUEPRINTS:
        if classification in SET_ASIDE_CLASSIFICATIONS:
            body = ""
        elif tone == "direct and executive":
            body = (
                f"Hi,\n\nI can take this forward. Based on your note, the main point to address is: "
                f"{preview}\n\nI will send a clearer update today with the next steps called out."
                f"{signature_block}"
            )
        else:
            body = (
                f"Hi,\n\nThanks for the follow-up. I am pulling this together now and will send "
                f"an updated reply shortly. The key item I am addressing is: {preview}\n\n"
                f"I will make sure the response is clear on what changed and what happens next."
                f"{signature_block}"
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
) -> tuple[list[dict[str, Any]], Optional[str], Optional[str], str]:
    signature = load_settings().user_signature
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
) -> tuple[dict[str, Any], Optional[str], Optional[str], str]:
    signature = load_settings().user_signature
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
) -> tuple[dict[str, Any], Optional[str], Optional[str], str]:
    signature = load_settings().user_signature
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
        body = raw_response.strip()
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
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


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
) -> dict[str, Any]:
    thread_state, _ = find_thread_state(state, thread_id)
    thread = payload_to_thread(thread_state["thread"])
    candidates, generation_model, generation_error, classification = generate_candidates_for_thread(
        thread,
        base_url=base_url,
        selected_model=selected_model,
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


def ensure_review_state(root_dir: Path, *, base_url: str, selected_model: str) -> dict[str, Any]:
    state = load_review_state(root_dir)
    dirty = False
    for thread_state in state.get("threads", []):
        if not thread_state.get("candidates"):
            regenerate_thread_candidates(
                state,
                thread_state["thread_id"],
                base_url=base_url,
                selected_model=selected_model,
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


def load_visible_version(root_dir: Path) -> str:
    version_file = root_dir / "VERSION"
    if not version_file.exists():
        return "0.0"
    return version_file.read_text(encoding="utf-8").strip()


def request_context_from_params(params: dict[str, list[str]]) -> dict[str, str]:
    return {
        "thread_id": params.get("thread_id", [""])[0],
        "filter_classification": params.get("filter_classification", ["all"])[0] or "all",
        "filter_status": params.get("filter_status", ["all"])[0] or "all",
        "sort_order": params.get("sort_order", ["priority"])[0] or "priority",
    }


def query_string_for_context(
    *,
    thread_id: str,
    filter_classification: str,
    filter_status: str,
    sort_order: str,
    message: str = "",
    level: str = "info",
) -> str:
    params = {
        "thread_id": thread_id,
        "filter_classification": filter_classification,
        "filter_status": filter_status,
        "sort_order": sort_order,
    }
    if message:
        params["message"] = message
        params["level"] = level
    return urlencode(params)


def hidden_context_inputs(context: dict[str, str]) -> str:
    return "\n".join(
        [
            f'<input type="hidden" name="thread_id" value="{html.escape(context["thread_id"])}" />',
            f'<input type="hidden" name="filter_classification" value="{html.escape(context["filter_classification"])}" />',
            f'<input type="hidden" name="filter_status" value="{html.escape(context["filter_status"])}" />',
            f'<input type="hidden" name="sort_order" value="{html.escape(context["sort_order"])}" />',
        ]
    )


def render_page(
    message: str = "",
    level: str = "info",
    selected_thread_id: str = "",
    filter_classification: str = "all",
    filter_status: str = "all",
    sort_order: str = "priority",
    review_state: Optional[dict[str, Any]] = None,
    models: Optional[list[str]] = None,
    model_error: str = "",
    ollama_prompt: str = "",
    ollama_result: str = "",
    ollama_result_level: str = "info",
) -> str:
    settings = load_settings()
    if review_state is None:
        review_state = ensure_review_state(
            settings.root_dir,
            base_url=settings.ollama_url,
            selected_model=settings.ollama_model,
        )

    if models is None:
        models, model_error = list_available_models(settings.ollama_url, settings.ollama_model)

    visible_threads = filtered_and_sorted_threads(
        review_state["threads"],
        filter_classification=filter_classification,
        filter_status=filter_status,
        sort_order=sort_order,
    )
    active_thread_pool = visible_threads or review_state["threads"]
    selected_thread = next(
        (item for item in active_thread_pool if item["thread_id"] == selected_thread_id),
        active_thread_pool[0],
    )
    selected_thread_id = selected_thread["thread_id"]
    visible_version = load_visible_version(settings.root_dir)
    context = {
        "thread_id": selected_thread_id,
        "filter_classification": filter_classification,
        "filter_status": filter_status,
        "sort_order": sort_order,
    }

    message_block = ""
    if message:
        message_block = f'<div class="banner {level}">{html.escape(message)}</div>'

    model_options = []
    if settings.ollama_model and settings.ollama_model not in models:
        model_options.append(
            f'<option value="{html.escape(settings.ollama_model)}" selected>'
            f'{html.escape(settings.ollama_model)} (current)</option>'
        )
    for model_name in models:
        selected = " selected" if model_name == settings.ollama_model else ""
        model_options.append(
            f'<option value="{html.escape(model_name)}"{selected}>{html.escape(model_name)}</option>'
        )

    classification_options = []
    for value, label in FILTER_LABELS.items():
        selected = " selected" if filter_classification == value else ""
        classification_options.append(
            f'<option value="{html.escape(value)}"{selected}>{html.escape(label)}</option>'
        )

    status_options = []
    for value, label in STATUS_FILTER_LABELS.items():
        selected = " selected" if filter_status == value else ""
        status_options.append(f'<option value="{html.escape(value)}"{selected}>{html.escape(label)}</option>')

    sort_options = []
    for value, label in SORT_LABELS.items():
        selected = " selected" if sort_order == value else ""
        sort_options.append(f'<option value="{html.escape(value)}"{selected}>{html.escape(label)}</option>')

    inbox_cards = []
    for thread_state in visible_threads:
        active_class = " active" if thread_state["thread_id"] == selected_thread_id else ""
        classification = normalize_classification(thread_state.get("classification"))
        query = query_string_for_context(
            thread_id=thread_state["thread_id"],
            filter_classification=filter_classification,
            filter_status=filter_status,
            sort_order=sort_order,
        )
        inbox_cards.append(
            f"""
            <a class="thread-link{active_class}" href="/?{query}">
              <span class="thread-subject">{html.escape(thread_state['subject'])}</span>
              <span class="thread-meta-row">
                <span class="thread-status">{html.escape(thread_state['status'].replace('_', ' '))}</span>
                <span class="thread-classification">{html.escape(classification.replace('_', ' '))}</span>
              </span>
            </a>
            """
        )
    if not inbox_cards:
        inbox_cards.append('<p class="hint empty-state">No emails match the current filters.</p>')

    thread = payload_to_thread(selected_thread["thread"])
    message_cards = []
    for index, email in enumerate(thread.messages, start=1):
        message_cards.append(
            f"""
            <details class="mail-card" {'open' if index == len(thread.messages) else ''}>
              <summary>
                <span>Email {index} • {html.escape(email.sender)}</span>
                <span class="summary-meta">{html.escape(email.sent_at)}</span>
              </summary>
              <div class="details-body">
                <p class="meta">To: {html.escape(', '.join(email.to))}</p>
                <pre class="mail-body">{html.escape(email.text)}</pre>
              </div>
            </details>
            """
        )

    candidate_cards = []
    for candidate in selected_thread.get("candidates", []):
        selected_class = (
            " selected" if selected_thread.get("selected_candidate_id") == candidate["candidate_id"] else ""
        )
        generated_by = candidate.get("generated_by") or "unknown"
        edited_meta = ""
        if candidate.get("edited_at"):
            edited_meta = f" • edited {html.escape(candidate['edited_at'])}"
        candidate_cards.append(
            f"""
            <article class="candidate-card{selected_class}">
              <div class="candidate-header">
                <div>
                  <h3>{html.escape(candidate['label'])}</h3>
                  <p class="meta">{html.escape(candidate['tone'])} • {html.escape(generated_by)}{edited_meta}</p>
                  <div class="badge-row compact">
                    <span class="pill classification-pill">{html.escape(candidate.get('classification', 'unclassified').replace('_', ' '))}</span>
                  </div>
                </div>
                <span class="pill">{html.escape(candidate['status'].replace('_', ' '))}</span>
              </div>
              <form method="post" action="/candidate-action">
                {hidden_context_inputs(context)}
                <input type="hidden" name="candidate_id" value="{html.escape(candidate['candidate_id'])}" />
                <label for="{html.escape(candidate['candidate_id'])}">Editable draft</label>
                <textarea id="{html.escape(candidate['candidate_id'])}" name="body" placeholder="No response recommended for this classification.">{html.escape(candidate['body'])}</textarea>
                <div class="actions">
                  <button type="submit" name="action" value="save" class="button secondary">Save edits</button>
                  <button type="submit" name="action" value="green_light">Green light this draft</button>
                  <button type="submit" name="action" value="red_light" class="button warn">Red light this draft</button>
                </div>
              </form>
            </article>
            """
        )

    candidate_error_block = ""
    if selected_thread.get("candidate_generation_error"):
        candidate_error_block = (
            f'<p class="hint error-text">{html.escape(selected_thread["candidate_generation_error"])}</p>'
        )

    classification = normalize_classification(selected_thread.get("classification"))
    classification_guidance = ""
    if classification in SET_ASIDE_CLASSIFICATIONS:
        classification_guidance = (
            f'<p class="hint review-note">Ollama triage marked this thread as '
            f'<strong>{html.escape(classification.replace("_", " "))}</strong>. '
            "That usually means it can be filtered out of the active reply queue.</p>"
        )
    elif classification == "urgent":
        classification_guidance = (
            '<p class="hint review-note">Ollama triage marked this thread as <strong>urgent</strong>, so it will stay near the top when sorting by priority.</p>'
        )

    ollama_result_block = ""
    if ollama_result:
        ollama_result_block = (
            f'<div class="test-result {ollama_result_level}"><pre>{html.escape(ollama_result)}</pre></div>'
        )

    gmail_status = "Connected" if settings.gmail_token_file.exists() else "Not connected"
    gmail_checked = "checked" if settings.gmail_enabled else ""
    outlook_checked = "checked" if settings.outlook_enabled else ""
    gmail_selected = "selected" if settings.default_provider == "gmail" else ""
    outlook_selected = "selected" if settings.default_provider == "outlook" else ""

    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>MailAssist Review</title>
    <style>
      :root {{
        --paper: #f6f0e8;
        --panel: #fffaf3;
        --ink: #1d2430;
        --muted: #5e6978;
        --accent: #b95333;
        --accent-soft: rgba(185, 83, 51, 0.1);
        --line: #dccbbb;
        --green: #215f4a;
        --red: #8c4029;
        --shadow: 0 18px 44px rgba(29, 36, 48, 0.08);
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        font-family: Georgia, "Iowan Old Style", serif;
        color: var(--ink);
        background:
          radial-gradient(circle at 0% 0%, rgba(185, 83, 51, 0.18), transparent 25%),
          linear-gradient(180deg, #fbf6ef 0%, #efe4d7 100%);
      }}
      a {{
        color: inherit;
      }}
      .shell {{
        max-width: 1380px;
        margin: 0 auto;
        padding: 28px 18px 42px;
      }}
      .hero {{
        display: flex;
        align-items: flex-end;
        justify-content: space-between;
        gap: 18px;
        margin-bottom: 24px;
      }}
      .hero h1 {{
        margin: 0;
        font-size: clamp(2.3rem, 6vw, 4.7rem);
        line-height: 0.92;
      }}
      .hero p {{
        margin: 10px 0 0;
        max-width: 860px;
        color: var(--muted);
        font-size: 1.02rem;
      }}
      .version-tag {{
        border: 1px solid var(--line);
        border-radius: 999px;
        padding: 8px 12px;
        background: rgba(255, 250, 243, 0.72);
        font-size: 0.88rem;
        color: var(--muted);
        white-space: nowrap;
      }}
      .banner {{
        margin-bottom: 18px;
        padding: 12px 14px;
        border-radius: 14px;
      }}
      .banner.info {{
        background: rgba(33, 95, 74, 0.12);
        color: var(--green);
      }}
      .banner.error {{
        background: rgba(140, 64, 41, 0.12);
        color: var(--red);
      }}
      .workspace {{
        display: grid;
        grid-template-columns: 320px minmax(0, 1fr);
        gap: 20px;
        align-items: start;
      }}
      .panel {{
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 22px;
        box-shadow: var(--shadow);
      }}
      .panel-body {{
        padding: 18px;
      }}
      .section-title {{
        margin: 0 0 10px;
        font-size: 1.35rem;
      }}
      .hint {{
        margin: 0;
        color: var(--muted);
        font-size: 0.93rem;
      }}
      .error-text {{
        color: var(--red);
      }}
      .review-note {{
        margin-top: 10px;
      }}
      .inbox-panel {{
        position: sticky;
        top: 18px;
        overflow: hidden;
      }}
      .inbox-header {{
        padding: 18px 18px 8px;
      }}
      .filter-form {{
        display: grid;
        gap: 10px;
        margin-top: 14px;
      }}
      .thread-list {{
        display: grid;
        gap: 10px;
        padding: 0 12px 16px;
      }}
      .thread-link {{
        display: grid;
        gap: 7px;
        text-decoration: none;
        padding: 14px;
        border-radius: 16px;
        border: 1px solid transparent;
        background: rgba(255, 255, 255, 0.6);
      }}
      .thread-link.active {{
        border-color: rgba(185, 83, 51, 0.26);
        background: linear-gradient(135deg, rgba(185, 83, 51, 0.12), rgba(255, 250, 243, 0.92));
      }}
      .thread-subject {{
        font-size: 1rem;
        font-weight: 700;
      }}
      .thread-meta-row {{
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        align-items: center;
      }}
      .thread-status, .thread-classification {{
        color: var(--muted);
        font-size: 0.82rem;
        text-transform: capitalize;
      }}
      .thread-classification {{
        border-radius: 999px;
        padding: 3px 8px;
        background: rgba(29, 36, 48, 0.06);
      }}
      .main-stack {{
        display: grid;
        gap: 18px;
      }}
      .review-top {{
        display: grid;
        gap: 18px;
      }}
      .thread-summary {{
        display: flex;
        gap: 12px;
        justify-content: space-between;
        align-items: flex-start;
        margin-bottom: 14px;
      }}
      .thread-summary h2 {{
        margin: 0;
        font-size: clamp(1.8rem, 4vw, 2.7rem);
      }}
      .meta {{
        color: var(--muted);
        font-size: 0.92rem;
      }}
      .badge-row {{
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        margin-top: 8px;
      }}
      .badge-row.compact {{
        margin-top: 6px;
      }}
      .pill {{
        display: inline-block;
        padding: 5px 10px;
        border-radius: 999px;
        background: var(--accent-soft);
        color: var(--accent);
        font-size: 0.8rem;
      }}
      .classification-pill {{
        background: rgba(29, 36, 48, 0.08);
        color: var(--ink);
      }}
      .summary-actions {{
        display: flex;
        gap: 10px;
        flex-wrap: wrap;
        margin-top: 14px;
      }}
      button, .button {{
        display: inline-block;
        border: 0;
        border-radius: 999px;
        padding: 11px 16px;
        background: var(--accent);
        color: #fffaf4;
        text-decoration: none;
        font: inherit;
        cursor: pointer;
      }}
      .button.secondary {{
        background: #eee1d0;
        color: var(--ink);
      }}
      .button.warn {{
        background: var(--red);
      }}
      details {{
        overflow: hidden;
        border: 1px solid var(--line);
        border-radius: 16px;
        background: rgba(255, 255, 255, 0.58);
      }}
      summary {{
        list-style: none;
        cursor: pointer;
        padding: 14px 16px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        font-weight: 600;
      }}
      summary::-webkit-details-marker {{
        display: none;
      }}
      .details-body {{
        padding: 0 16px 16px;
        border-top: 1px solid var(--line);
      }}
      .summary-meta {{
        color: var(--muted);
        font-size: 0.88rem;
        font-weight: 400;
      }}
      .mail-stack, .candidate-stack {{
        display: grid;
        gap: 12px;
      }}
      .mail-body, pre {{
        margin: 0;
        white-space: pre-wrap;
        word-break: break-word;
        font-family: "SFMono-Regular", Menlo, monospace;
      }}
      .candidate-grid {{
        display: grid;
        gap: 14px;
        grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      }}
      .candidate-card {{
        border: 1px solid var(--line);
        border-radius: 18px;
        padding: 16px;
        background: rgba(255, 255, 255, 0.68);
      }}
      .candidate-card.selected {{
        border-color: rgba(33, 95, 74, 0.34);
        box-shadow: inset 0 0 0 1px rgba(33, 95, 74, 0.16);
      }}
      .candidate-header {{
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 12px;
      }}
      h3 {{
        margin: 0;
        font-size: 1.12rem;
      }}
      textarea, input, select {{
        width: 100%;
        padding: 11px 12px;
        border: 1px solid var(--line);
        border-radius: 14px;
        background: #fff;
        font: inherit;
        color: var(--ink);
      }}
      textarea {{
        min-height: 220px;
        resize: vertical;
      }}
      label {{
        display: block;
        margin: 14px 0 6px;
        font-size: 0.95rem;
      }}
      .actions {{
        display: flex;
        gap: 10px;
        flex-wrap: wrap;
        margin-top: 16px;
      }}
      .muted-panel {{
        background: rgba(255, 250, 243, 0.78);
      }}
      .muted-panel summary {{
        color: var(--muted);
      }}
      .settings-grid {{
        display: grid;
        gap: 16px;
        grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      }}
      .settings-card {{
        border: 1px solid var(--line);
        border-radius: 16px;
        padding: 16px;
        background: rgba(255, 255, 255, 0.55);
      }}
      .settings-card h3 {{
        margin-bottom: 8px;
      }}
      .check-row {{
        display: flex;
        gap: 8px;
        align-items: center;
        margin-top: 10px;
      }}
      .check-row input {{
        width: auto;
      }}
      .test-result {{
        margin-top: 14px;
        border-radius: 14px;
        padding: 12px;
      }}
      .test-result.info {{
        background: rgba(33, 95, 74, 0.08);
      }}
      .test-result.error {{
        background: rgba(140, 64, 41, 0.08);
      }}
      .empty-state {{
        padding: 0 10px 10px;
      }}
      @media (max-width: 980px) {{
        .workspace {{
          grid-template-columns: 1fr;
        }}
        .inbox-panel {{
          position: static;
        }}
      }}
    </style>
  </head>
  <body>
    <div class="shell">
      <div class="hero">
        <div>
          <h1>MailAssist Review</h1>
          <p>The operator flow is now centered on green lights and red lights, with queue triage up front. Use Ollama’s classification signal to separate urgent mail from automated or spammy threads before anyone spends time editing a response.</p>
        </div>
        <div class="version-tag">v{html.escape(visible_version)} • triage-first review inbox</div>
      </div>
      {message_block}
      <div class="workspace">
        <aside class="panel inbox-panel">
          <div class="inbox-header">
            <h2 class="section-title">Review Queue</h2>
            <p class="hint">Subjects first, with triage filters and ordering.</p>
            <form class="filter-form" method="get" action="/">
              <input type="hidden" name="thread_id" value="{html.escape(selected_thread_id)}" />
              <label for="filter_classification">Filter</label>
              <select id="filter_classification" name="filter_classification">
                {''.join(classification_options)}
              </select>
              <label for="filter_status">Review status</label>
              <select id="filter_status" name="filter_status">
                {''.join(status_options)}
              </select>
              <label for="sort_order">Order</label>
              <select id="sort_order" name="sort_order">
                {''.join(sort_options)}
              </select>
              <div class="actions">
                <button type="submit">Apply queue view</button>
              </div>
            </form>
          </div>
          <div class="thread-list">
            {''.join(inbox_cards)}
          </div>
        </aside>

        <main class="main-stack">
          <section class="panel review-top">
            <div class="panel-body">
              <div class="thread-summary">
                <div>
                  <h2>{html.escape(thread.subject)}</h2>
                  <p class="meta">{html.escape(', '.join(thread.participants))}</p>
                  <div class="badge-row">
                    <span class="pill">{html.escape(selected_thread['status'].replace('_', ' '))}</span>
                    <span class="pill">{len(selected_thread.get('candidates', []))} draft options</span>
                    <span class="pill classification-pill">classification: {html.escape(classification.replace('_', ' '))}</span>
                    <span class="pill">{html.escape(selected_thread.get('candidate_generation_model') or 'fallback copy')}</span>
                  </div>
                  {classification_guidance}
                </div>
              </div>
              <form method="post" action="/regenerate-thread">
                {hidden_context_inputs(context)}
                <div class="summary-actions">
                  <button type="submit">Refresh draft options with Ollama</button>
                  <a class="button secondary" href="/?{query_string_for_context(**context)}">Reset view</a>
                </div>
              </form>
              {candidate_error_block}
            </div>
          </section>

          <section class="panel">
            <div class="panel-body">
              <h2 class="section-title">Email Body</h2>
              <div class="mail-stack">
                {''.join(message_cards)}
              </div>
            </div>
          </section>

          <section class="panel">
            <div class="panel-body candidate-stack">
              <div>
                <h2 class="section-title">Response Drafts</h2>
                <p class="hint">Each draft now carries an Ollama classification so the queue can separate urgent mail from automated or spammy items.</p>
              </div>
              <div class="candidate-grid">
                {''.join(candidate_cards)}
              </div>
            </div>
          </section>

          <details class="panel muted-panel">
            <summary>
              <span>Operator settings</span>
              <span class="summary-meta">Ollama, providers, and checks live here now</span>
            </summary>
            <div class="details-body">
              <div class="settings-grid">
                <form class="settings-card" method="post" action="/save">
                  <h3>Ollama</h3>
                  {hidden_context_inputs(context)}
                  <label for="ollama_url">Ollama URL</label>
                  <input id="ollama_url" name="MAILASSIST_OLLAMA_URL" value="{html.escape(settings.ollama_url)}" />
                  <label for="ollama_model">Chosen model</label>
                  <select id="ollama_model" name="MAILASSIST_OLLAMA_MODEL">
                    {''.join(model_options) or '<option value="">No models found</option>'}
                  </select>
                  {f'<p class="hint error-text">{html.escape(model_error)}</p>' if model_error else ''}
                  <p class="hint">Queue classification and draft regeneration both use the selected model.</p>
                  <div class="actions">
                    <button type="submit">Save settings</button>
                  </div>
                </form>

                <form class="settings-card" method="post" action="/test-ollama">
                  <h3>Ollama check</h3>
                  {hidden_context_inputs(context)}
                  <label for="ollama_test_prompt">Test prompt</label>
                  <textarea id="ollama_test_prompt" name="prompt" placeholder="Ask the model to confirm it is reachable.">{html.escape(ollama_prompt)}</textarea>
                  <div class="actions">
                    <button type="submit">Run Ollama check</button>
                  </div>
                  {ollama_result_block}
                </form>

                <form class="settings-card" method="post" action="/save">
                  <h3>Providers</h3>
                  {hidden_context_inputs(context)}
                  <label for="default_provider">Default provider</label>
                  <select id="default_provider" name="MAILASSIST_DEFAULT_PROVIDER">
                    <option value="gmail" {gmail_selected}>Gmail</option>
                    <option value="outlook" {outlook_selected}>Outlook</option>
                  </select>
                  <label class="check-row"><input type="checkbox" name="MAILASSIST_GMAIL_ENABLED" value="true" {gmail_checked} />Enable Gmail</label>
                  <label class="check-row"><input type="checkbox" name="MAILASSIST_OUTLOOK_ENABLED" value="true" {outlook_checked} />Enable Outlook</label>
                  <label for="gmail_credentials_file">Gmail credentials file</label>
                  <input id="gmail_credentials_file" name="MAILASSIST_GMAIL_CREDENTIALS_FILE" value="{html.escape(str(settings.gmail_credentials_file))}" />
                  <label for="gmail_token_file">Gmail token file</label>
                  <input id="gmail_token_file" name="MAILASSIST_GMAIL_TOKEN_FILE" value="{html.escape(str(settings.gmail_token_file))}" />
                  <label for="user_signature">Signature</label>
                  <textarea id="user_signature" name="MAILASSIST_USER_SIGNATURE" placeholder="Best regards,&#10;Your Name">{html.escape(settings.user_signature)}</textarea>
                  <p class="hint">Gmail status: {html.escape(gmail_status)}. Provider submission stays separate from review.</p>
                  <div class="actions">
                    <button type="submit">Save provider settings</button>
                  </div>
                </form>
              </div>
            </div>
          </details>
        </main>
      </div>
    </div>
  </body>
</html>
"""


class ConfigRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/test-ollama"}:
            params = parse_qs(parsed.query)
            context = request_context_from_params(params)
            message = params.get("message", [""])[0]
            level = params.get("level", ["info"])[0]
            self._send_html(
                render_page(
                    message=message,
                    level=level,
                    selected_thread_id=context["thread_id"],
                    filter_classification=context["filter_classification"],
                    filter_status=context["filter_status"],
                    sort_order=context["sort_order"],
                )
            )
            return

        if parsed.path == "/api/ollama/models":
            settings = load_settings()
            models, model_error = list_available_models(settings.ollama_url, settings.ollama_model)
            if model_error:
                self._send_json({"models": [], "error": model_error}, status=HTTPStatus.BAD_GATEWAY)
                return
            self._send_json({"models": models})
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path == "/candidate-action":
            self._handle_candidate_action()
            return

        if self.path == "/regenerate-thread":
            self._handle_regenerate_thread()
            return

        if self.path == "/test-ollama":
            self._handle_test_ollama()
            return

        if self.path == "/save":
            self._handle_save_settings()
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def _read_form(self) -> dict[str, list[str]]:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        return parse_qs(body)

    def _redirect_with_context(
        self,
        context: dict[str, str],
        *,
        message: str = "",
        level: str = "info",
    ) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", f"/?{query_string_for_context(message=message, level=level, **context)}")
        self.end_headers()

    def _handle_save_settings(self) -> None:
        form = self._read_form()
        context = request_context_from_params(form)
        settings = load_settings()
        env_file = settings.root_dir / ".env"
        current = read_env_file(env_file)
        updates = {
            "MAILASSIST_OLLAMA_URL": form.get(
                "MAILASSIST_OLLAMA_URL",
                [current.get("MAILASSIST_OLLAMA_URL", "http://localhost:11434")],
            )[0],
            "MAILASSIST_OLLAMA_MODEL": form.get(
                "MAILASSIST_OLLAMA_MODEL",
                [current.get("MAILASSIST_OLLAMA_MODEL", "qwen3.6:latest")],
            )[0],
            "MAILASSIST_USER_SIGNATURE": form.get(
                "MAILASSIST_USER_SIGNATURE",
                [current.get("MAILASSIST_USER_SIGNATURE", "")],
            )[0].replace("\r\n", "\n").replace("\n", "\\n"),
            "MAILASSIST_DEFAULT_PROVIDER": form.get(
                "MAILASSIST_DEFAULT_PROVIDER",
                [current.get("MAILASSIST_DEFAULT_PROVIDER", "gmail")],
            )[0],
            "MAILASSIST_GMAIL_ENABLED": "true" if "MAILASSIST_GMAIL_ENABLED" in form else "false",
            "MAILASSIST_OUTLOOK_ENABLED": "true" if "MAILASSIST_OUTLOOK_ENABLED" in form else "false",
            "MAILASSIST_GMAIL_CREDENTIALS_FILE": form.get(
                "MAILASSIST_GMAIL_CREDENTIALS_FILE",
                [current.get("MAILASSIST_GMAIL_CREDENTIALS_FILE", "secrets/gmail-client-secret.json")],
            )[0],
            "MAILASSIST_GMAIL_TOKEN_FILE": form.get(
                "MAILASSIST_GMAIL_TOKEN_FILE",
                [current.get("MAILASSIST_GMAIL_TOKEN_FILE", "secrets/gmail-token.json")],
            )[0],
            "MAILASSIST_OUTLOOK_CLIENT_ID": form.get(
                "MAILASSIST_OUTLOOK_CLIENT_ID",
                [current.get("MAILASSIST_OUTLOOK_CLIENT_ID", "")],
            )[0],
            "MAILASSIST_OUTLOOK_TENANT_ID": form.get(
                "MAILASSIST_OUTLOOK_TENANT_ID",
                [current.get("MAILASSIST_OUTLOOK_TENANT_ID", "")],
            )[0],
            "MAILASSIST_OUTLOOK_REDIRECT_URI": form.get(
                "MAILASSIST_OUTLOOK_REDIRECT_URI",
                [current.get("MAILASSIST_OUTLOOK_REDIRECT_URI", "http://localhost:8765/outlook/callback")],
            )[0],
        }
        current.update(updates)
        write_env_file(env_file, current)
        self._redirect_with_context(context, message="Settings saved.", level="info")

    def _handle_test_ollama(self) -> None:
        form = self._read_form()
        context = request_context_from_params(form)
        prompt = form.get("prompt", [""])[0].strip()
        settings = load_settings()

        if not prompt:
            self._send_html(
                render_page(
                    message="Enter a prompt before testing Ollama.",
                    level="error",
                    selected_thread_id=context["thread_id"],
                    filter_classification=context["filter_classification"],
                    filter_status=context["filter_status"],
                    sort_order=context["sort_order"],
                ),
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        try:
            result = OllamaClient(settings.ollama_url, settings.ollama_model).compose_reply(prompt)
            if not result:
                result = "Ollama responded, but the model returned an empty body."
            self._send_html(
                render_page(
                    message="Ollama check completed.",
                    level="info",
                    selected_thread_id=context["thread_id"],
                    filter_classification=context["filter_classification"],
                    filter_status=context["filter_status"],
                    sort_order=context["sort_order"],
                    ollama_prompt=prompt,
                    ollama_result=result,
                )
            )
        except RuntimeError as exc:
            self._send_html(
                render_page(
                    message="Ollama check failed.",
                    level="error",
                    selected_thread_id=context["thread_id"],
                    filter_classification=context["filter_classification"],
                    filter_status=context["filter_status"],
                    sort_order=context["sort_order"],
                    ollama_prompt=prompt,
                    ollama_result=str(exc),
                    ollama_result_level="error",
                ),
                status=HTTPStatus.BAD_GATEWAY,
            )

    def _handle_regenerate_thread(self) -> None:
        form = self._read_form()
        context = request_context_from_params(form)
        thread_id = context["thread_id"].strip()
        if not thread_id:
            self._send_html(
                render_page(message="Choose a thread before regenerating drafts.", level="error"),
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        settings = load_settings()
        state = load_review_state(settings.root_dir)
        try:
            regenerate_thread_candidates(
                state,
                thread_id,
                base_url=settings.ollama_url,
                selected_model=settings.ollama_model,
            )
        except (RuntimeError, ValueError) as exc:
            self._redirect_with_context(context, message=str(exc), level="error")
            return

        save_review_state(settings.root_dir, state)
        self._redirect_with_context(context, message="Draft options refreshed.", level="info")

    def _handle_candidate_action(self) -> None:
        form = self._read_form()
        context = request_context_from_params(form)
        candidate_id = form.get("candidate_id", [""])[0].strip()
        action = form.get("action", [""])[0].strip()
        body = form.get("body", [""])[0]

        if action not in {"save", "green_light", "red_light"} or not context["thread_id"] or not candidate_id:
            self._send_html(
                render_page(message="Invalid review action.", level="error"),
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        settings = load_settings()
        state = load_review_state(settings.root_dir)
        try:
            thread_state, _ = find_thread_state(state, context["thread_id"])
            update_candidate(thread_state, candidate_id, body, action)
            save_review_state(settings.root_dir, state)
        except ValueError as exc:
            self._send_html(
                render_page(
                    message=str(exc),
                    level="error",
                    selected_thread_id=context["thread_id"],
                    filter_classification=context["filter_classification"],
                    filter_status=context["filter_status"],
                    sort_order=context["sort_order"],
                ),
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        notices = {
            "save": "Draft edits saved.",
            "green_light": "Draft green-lit.",
            "red_light": "Draft red-lit.",
        }
        self._redirect_with_context(context, message=notices[action], level="info")

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_html(self, content: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve_config_gui(host: str = "127.0.0.1", port: int = 8765) -> None:
    server = ThreadingHTTPServer((host, port), ConfigRequestHandler)
    print(f"MailAssist config GUI available at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
