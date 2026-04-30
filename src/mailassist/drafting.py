from __future__ import annotations

import textwrap
from collections import Counter
from typing import Any, Iterable, Optional

from mailassist.contacts import ElderContact, elder_relationship_guidance_for_thread
from mailassist.llm.ollama import OllamaClient
from mailassist.models import EmailThread, utc_now_iso

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
- If thread-specific relationship guidance says the sender is on the user's Elders list, that guidance overrides the mirror-register rule: in French, use respectful `vous` for that sender even if the sender used `tu`.
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


def relationship_prompt_block(
    thread: EmailThread,
    elder_contacts: Iterable[ElderContact] = (),
) -> str:
    guidance = elder_relationship_guidance_for_thread(thread, elder_contacts)
    if not guidance:
        return ""
    return f"\n\nRelationship guidance:\n{guidance}"


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


def fallback_classification_for_thread(thread: EmailThread) -> str:
    haystack = " ".join(
        [thread.subject, *thread.participants, *(message.text for message in thread.messages)]
    ).lower()
    if any(
        token in haystack
        for token in (
            "unsubscribe",
            "no-reply",
            "noreply",
            "do not reply",
            "automated email",
            "automated notification",
            "digest",
            "notificationmail",
            "promomail",
            "emailnotify",
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
    for candidate_id, _label, tone, _ in CANDIDATE_BLUEPRINTS:
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


def build_review_candidates_prompt(
    thread: EmailThread,
    *,
    signature: str = "",
    elder_contacts: Iterable[ElderContact] = (),
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
{format_thread_context(thread)}{relationship_prompt_block(thread, elder_contacts)}
""".strip()


def build_single_review_candidate_prompt(
    thread: EmailThread,
    *,
    tone: str,
    guidance: str,
    existing_body: str = "",
    signature: str = "",
    elder_contacts: Iterable[ElderContact] = (),
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
{format_thread_context(thread)}{relationship_prompt_block(thread, elder_contacts)}
""".strip()


def build_single_review_candidate_body_prompt(
    thread: EmailThread,
    *,
    tone: str,
    guidance: str,
    existing_body: str = "",
    signature: str = "",
    elder_contacts: Iterable[ElderContact] = (),
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
{format_thread_context(thread)}{relationship_prompt_block(thread, elder_contacts)}
""".strip()


def generate_candidates_for_thread(
    thread: EmailThread,
    base_url: str,
    selected_model: str,
    *,
    signature: str = "",
    elder_contacts: Iterable[ElderContact] = (),
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
        prompt = build_review_candidates_prompt(
            thread,
            signature=signature,
            elder_contacts=elder_contacts,
        )
        response = llm.compose_reply(prompt)
        classification, bodies = extract_classification_and_bodies(response)
        classification = merge_classification(classification, heuristic_classification)
        if len(bodies) != len(CANDIDATE_BLUEPRINTS):
            raise RuntimeError("The local model did not return the expected number of draft options.")

        for (candidate_id, _label, tone, _), body in zip(CANDIDATE_BLUEPRINTS, bodies):
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
    elder_contacts: Iterable[ElderContact] = (),
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
            elder_contacts=elder_contacts,
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
    elder_contacts: Iterable[ElderContact] = (),
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
            elder_contacts=elder_contacts,
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
