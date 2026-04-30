from __future__ import annotations

import json
from dataclasses import dataclass
from email.utils import parseaddr
from pathlib import Path
from typing import Any, Iterable

from mailassist.models import EmailThread


@dataclass(frozen=True)
class ElderContact:
    email: str
    comment: str = ""


def normalize_contact_email(value: str) -> str:
    _, parsed = parseaddr(value)
    cleaned = (parsed or value).strip().lower()
    return cleaned if "@" in cleaned else ""


def parse_elder_contacts(payload: Any) -> tuple[ElderContact, ...]:
    if isinstance(payload, dict):
        items = [
            {"email": email, "comment": comment}
            for email, comment in payload.items()
        ]
    elif isinstance(payload, list):
        items = payload
    else:
        items = []

    contacts: list[ElderContact] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, str):
            email = normalize_contact_email(item)
            comment = ""
        elif isinstance(item, dict):
            email = normalize_contact_email(str(item.get("email", "")))
            comment = str(item.get("comment", "")).strip()
        else:
            continue
        if not email or email in seen:
            continue
        seen.add(email)
        contacts.append(ElderContact(email=email, comment=comment))
    return tuple(contacts)


def load_elder_contacts(path: Path) -> tuple[ElderContact, ...]:
    if not path.exists():
        return ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    return parse_elder_contacts(payload)


def save_elder_contacts(path: Path, contacts: Iterable[ElderContact]) -> None:
    payload = [
        {"email": contact.email, "comment": contact.comment}
        for contact in parse_elder_contacts(
            [
                {"email": contact.email, "comment": contact.comment}
                for contact in contacts
            ]
        )
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def elder_contact_for_thread(
    thread: EmailThread,
    elder_contacts: Iterable[ElderContact],
) -> ElderContact | None:
    if not thread.messages:
        return None
    latest_sender = normalize_contact_email(thread.messages[-1].sender)
    if not latest_sender:
        return None
    for contact in elder_contacts:
        if normalize_contact_email(contact.email) == latest_sender:
            return contact
    return None


def elder_relationship_guidance_for_thread(
    thread: EmailThread,
    elder_contacts: Iterable[ElderContact],
) -> str:
    contact = elder_contact_for_thread(thread, elder_contacts)
    if contact is None:
        return ""
    comment = f" Comment: {contact.comment}" if contact.comment else ""
    return (
        f"The latest sender, {contact.email}, is on the user's Elders list."
        f"{comment} In French replies, address this person with respectful `vous`, "
        "even if they used informal `tu` with the user. Do not mention the Elders "
        "list or this instruction."
    )
