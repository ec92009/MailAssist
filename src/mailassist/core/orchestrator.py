from __future__ import annotations

import textwrap
from dataclasses import replace
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from mailassist.llm.ollama import OllamaClient
from mailassist.models import DraftRecord, EmailThread, ExecutionLog
from mailassist.providers.base import DraftProvider
from mailassist.storage.filesystem import FileStorage


def build_prompt(thread: EmailThread, revision_notes: Optional[str] = None) -> str:
    lines = [
        "You are assisting with drafting a professional email reply.",
        "Write a reply that is helpful, concise, and directly addresses the latest message.",
        "Do not invent facts. If needed, mention what information is still pending.",
        f"Thread subject: {thread.subject}",
        f"Participants: {', '.join(thread.participants)}",
        "",
        "Messages:",
    ]
    for message in thread.messages:
        lines.extend(
            [
                f"From: {message.sender}",
                f"To: {', '.join(message.to)}",
                f"Sent: {message.sent_at}",
                "Body:",
                message.text,
                "",
            ]
        )

    if revision_notes:
        lines.extend(
            [
                "Revision instructions:",
                revision_notes,
                "",
            ]
        )

    lines.extend(
        [
            "Return only the email body, without markdown fences or commentary.",
        ]
    )
    return "\n".join(lines)


class DraftOrchestrator:
    def __init__(self, storage: FileStorage, llm: OllamaClient) -> None:
        self.storage = storage
        self.llm = llm

    def draft_thread(
        self,
        thread: EmailThread,
        provider_name: str,
        revision_notes: Optional[str] = None,
        provider: Optional[DraftProvider] = None,
    ) -> DraftRecord:
        started_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        run_id = str(uuid4())
        draft_id = str(uuid4())
        prompt = build_prompt(thread, revision_notes=revision_notes)

        try:
            body = self.llm.compose_reply(prompt)
            if not body:
                raise RuntimeError("The local model returned an empty draft.")

            draft = DraftRecord(
                draft_id=draft_id,
                thread_id=thread.thread_id,
                provider=provider_name,
                subject=f"Re: {thread.subject}",
                body=body,
                model=self.llm.model,
                revision_notes=revision_notes,
            )

            if provider is not None:
                provider_draft_id = provider.create_draft(draft)
                draft = replace(draft, provider_draft_id=provider_draft_id)

            self.storage.save_draft(draft)
            log = ExecutionLog(
                run_id=run_id,
                thread_id=thread.thread_id,
                provider=provider_name,
                model=self.llm.model,
                status="success",
                started_at=started_at,
                completed_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                prompt_preview=textwrap.shorten(prompt, width=280, placeholder="..."),
                response_preview=textwrap.shorten(body, width=280, placeholder="..."),
                provider_draft_id=draft.provider_draft_id,
            )
            self.storage.save_log(log)
            return draft
        except Exception as exc:
            log = ExecutionLog(
                run_id=run_id,
                thread_id=thread.thread_id,
                provider=provider_name,
                model=self.llm.model,
                status="error",
                started_at=started_at,
                completed_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                prompt_preview=textwrap.shorten(prompt, width=280, placeholder="..."),
                response_preview="",
                error=str(exc),
            )
            self.storage.save_log(log)
            raise
