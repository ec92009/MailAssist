from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from mailassist.background_bot import (
    append_draft_attribution,
    body_with_review_context,
    build_draft_body_html,
    reply_metadata_for_thread,
    run_watch_pass,
)
from mailassist.config import (
    ATTRIBUTION_BELOW_SIGNATURE,
    ATTRIBUTION_HIDE,
    DEFAULT_MAILASSIST_CATEGORIES,
    LOCKED_NEEDS_REPLY_CATEGORY,
    load_settings,
)
from mailassist.drafting import fallback_classification_for_thread
from mailassist.fixtures.mock_threads import build_mock_threads
from mailassist.llm.ollama import OllamaClient
from mailassist.models import DraftRecord, utc_now_iso
from mailassist.providers.factory import get_provider_for_settings

MAILASSIST_GMAIL_PARENT_LABEL = "MailAssist"
MAILASSIST_NO_CATEGORY = "NA"


def _category_key(category: str) -> str:
    return category.lower().replace("&", "and").replace(" ", "_")


def _gmail_label_for_category(category: str) -> str:
    return f"{MAILASSIST_GMAIL_PARENT_LABEL}/{category}"


def _outlook_category_for_category(category: str) -> str:
    return f"{MAILASSIST_GMAIL_PARENT_LABEL} - {category}"


MAILASSIST_GMAIL_LABELS = {
    _category_key(category): _gmail_label_for_category(category)
    for category in DEFAULT_MAILASSIST_CATEGORIES
}
MAILASSIST_GMAIL_LABELS["licenses_accounts"] = _gmail_label_for_category("Licenses & Accounts")
MAILASSIST_GMAIL_LABELS["receipts_finance"] = _gmail_label_for_category("Receipts & Finance")


def _mailassist_gmail_label_names(categories: tuple[str, ...] | list[str] | None = None) -> list[str]:
    selected = list(categories or DEFAULT_MAILASSIST_CATEGORIES)
    return [MAILASSIST_GMAIL_PARENT_LABEL, *[_gmail_label_for_category(category) for category in selected]]


class BotEventReporter:
    def __init__(self, logs_dir: Path, action: str) -> None:
        self.run_id = str(uuid4())
        self.action = action
        self.log_path = logs_dir / f"bot-{action}-{self.run_id}.jsonl"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event_type: str, **payload: object) -> None:
        event = {
            "type": event_type,
            "action": self.action,
            "run_id": self.run_id,
            "timestamp": utc_now_iso(),
            **payload,
        }
        line = json.dumps(event, ensure_ascii=True)
        print(line, flush=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def build_review_bot_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "review-bot",
        help="Run a bot/debug action and emit JSONL events on stdout.",
    )
    parser.add_argument(
        "--action",
        required=True,
        choices=(
            "ollama-check",
            "watch-once",
            "watch-loop",
            "gmail-inbox-preview",
            "gmail-controlled-draft",
            "gmail-label-cleanup",
            "gmail-unused-label-cleanup",
            "gmail-populate-labels",
            "outlook-smoke-test",
            "outlook-populate-categories",
        ),
        help="Bot action to run.",
    )
    parser.add_argument("--thread-id", help="Optional thread ID for targeted watch passes.")
    parser.add_argument("--prompt", help="Prompt for Ollama check actions.")
    parser.add_argument("--base-url", help="Ollama base URL for bot actions.")
    parser.add_argument("--selected-model", help="Ollama model for bot actions.")
    parser.add_argument("--provider", default="mock", help="Provider to watch for watch-once.")
    parser.add_argument("--limit", type=int, default=10, help="Maximum Gmail messages for preview actions.")
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=0,
        help="Seconds to wait between watch-loop polling passes. Defaults to MAILASSIST_BOT_POLL_SECONDS.",
    )
    parser.add_argument(
        "--max-passes",
        type=int,
        default=0,
        help="Maximum passes for watch-loop. Use 0 to keep polling until stopped.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1,
        help="Number of actionable emails to submit to Ollama per prompt during watch-once.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reprocess inbox items even if they already exist in live state.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run watch-once/watch-loop without creating provider drafts.",
    )
    parser.add_argument(
        "--create-draft",
        action="store_true",
        help="For outlook-smoke-test only: create one controlled Outlook reply draft for --thread-id.",
    )
    parser.add_argument(
        "--older-than-years",
        type=int,
        default=5,
        help="For gmail-label-cleanup only: labels with no newer messages than this are candidates.",
    )
    parser.add_argument(
        "--remove-labels",
        action="store_true",
        help="For gmail-label-cleanup only: remove matching labels from old messages.",
    )
    parser.add_argument(
        "--delete-unused-labels",
        action="store_true",
        help="For gmail-unused-label-cleanup only: delete empty user-created labels.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="For gmail-populate-labels only: number of recent days to label.",
    )
    parser.add_argument(
        "--apply-labels",
        action="store_true",
        help="For gmail-populate-labels only: apply labels after the dry-run preview.",
    )
    parser.add_argument(
        "--apply-categories",
        action="store_true",
        help="For outlook-populate-categories only: apply categories after the dry-run preview.",
    )


def command_review_bot(args: argparse.Namespace) -> int:
    settings = load_settings()
    base_url = (getattr(args, "base_url", None) or settings.ollama_url).strip()
    selected_model = (getattr(args, "selected_model", None) or settings.ollama_model).strip()
    reporter = BotEventReporter(settings.bot_logs_dir, args.action)
    reporter.emit(
        "started",
        command="review-bot",
        arguments={
            "action": args.action,
            "thread_id": args.thread_id,
            "prompt": args.prompt,
            "base_url": base_url,
            "selected_model": selected_model,
            "force": bool(getattr(args, "force", False)),
            "provider": getattr(args, "provider", "mock"),
            "poll_seconds": int(getattr(args, "poll_seconds", 0) or 0),
            "max_passes": int(getattr(args, "max_passes", 0) or 0),
            "batch_size": max(1, int(getattr(args, "batch_size", 1) or 1)),
            "dry_run": bool(getattr(args, "dry_run", False)),
            "create_draft": bool(getattr(args, "create_draft", False)),
            "older_than_years": int(getattr(args, "older_than_years", 5) or 5),
            "remove_labels": bool(getattr(args, "remove_labels", False)),
            "delete_unused_labels": bool(getattr(args, "delete_unused_labels", False)),
            "days": int(getattr(args, "days", 7) or 7),
            "apply_labels": bool(getattr(args, "apply_labels", False)),
            "apply_categories": bool(getattr(args, "apply_categories", False)),
        },
    )
    reporter.emit("log_file", path=str(reporter.log_path))

    try:
        if args.action == "gmail-inbox-preview":
            provider = get_provider_for_settings(settings, "gmail")
            reader = getattr(provider, "list_recent_inbox_messages", None)
            if not callable(reader):
                raise RuntimeError("The configured Gmail provider cannot list inbox messages.")
            limit = max(1, int(getattr(args, "limit", 10) or 10))
            reporter.emit(
                "info",
                message=f"Reading metadata for the latest {limit} Gmail inbox message(s).",
                provider="gmail",
                limit=limit,
            )
            messages = reader(limit=limit)
            for message in messages:
                reporter.emit("gmail_message_preview", **message)
            reporter.emit(
                "completed",
                message="Gmail inbox preview completed.",
                provider="gmail",
                message_count=len(messages),
            )
            return 0

        if args.action == "gmail-label-cleanup":
            provider = get_provider_for_settings(settings, "gmail")
            finder = getattr(provider, "find_old_labeled_message_groups", None)
            if not callable(finder):
                raise RuntimeError("The configured Gmail provider cannot inspect labels.")
            older_than_years = max(1, int(getattr(args, "older_than_years", 5) or 5))
            remove_labels = bool(getattr(args, "remove_labels", False))
            reporter.emit(
                "info",
                message="Inspecting Gmail labels for old messages.",
                provider="gmail",
                older_than_years=older_than_years,
                remove_labels=remove_labels,
            )
            groups = finder(older_than_years=older_than_years)
            for group in groups:
                reporter.emit(
                    "gmail_label_old_messages",
                    provider="gmail",
                    label_id=group["id"],
                    label_name=group["name"],
                    message_count=group["message_count"],
                    limited=group["limited"],
                    older_than_years=older_than_years,
                )
            removed_count = 0
            if remove_labels:
                remover = getattr(provider, "remove_label_from_messages", None)
                if not callable(remover):
                    raise RuntimeError("The configured Gmail provider cannot remove labels from messages.")
                for group in groups:
                    removed = remover(group["id"], group["message_ids"])
                    removed_count += removed
                    reporter.emit(
                        "gmail_label_removed_from_old_messages",
                        provider="gmail",
                        label_id=group["id"],
                        label_name=group["name"],
                        removed_count=removed,
                    )
            reporter.emit(
                "completed",
                message=(
                    "Gmail old-message label cleanup completed."
                    if remove_labels
                    else "Gmail old-message label cleanup dry run completed."
                ),
                provider="gmail",
                label_count=len(groups),
                removed_count=removed_count,
                dry_run=not remove_labels,
            )
            return 0

        if args.action == "gmail-unused-label-cleanup":
            provider = get_provider_for_settings(settings, "gmail")
            finder = getattr(provider, "find_unused_user_labels", None)
            if not callable(finder):
                raise RuntimeError("The configured Gmail provider cannot inspect labels.")
            delete_unused_labels = bool(getattr(args, "delete_unused_labels", False))
            reporter.emit(
                "info",
                message="Inspecting Gmail for unused user labels.",
                provider="gmail",
                delete_unused_labels=delete_unused_labels,
            )
            labels = finder()
            for label in labels:
                reporter.emit(
                    "gmail_unused_label",
                    provider="gmail",
                    label_id=label["id"],
                    label_name=label["name"],
                    messages_total=label["messages_total"],
                    threads_total=label["threads_total"],
                )
            deleted_count = 0
            if delete_unused_labels:
                deleter = getattr(provider, "delete_user_label", None)
                if not callable(deleter):
                    raise RuntimeError("The configured Gmail provider cannot delete labels.")
                for label in labels:
                    deleter(label["id"])
                    deleted_count += 1
                    reporter.emit(
                        "gmail_unused_label_deleted",
                        provider="gmail",
                        label_id=label["id"],
                        label_name=label["name"],
                    )
            reporter.emit(
                "completed",
                message=(
                    "Gmail unused label cleanup completed."
                    if delete_unused_labels
                    else "Gmail unused label cleanup dry run completed."
                ),
                provider="gmail",
                label_count=len(labels),
                deleted_count=deleted_count,
                dry_run=not delete_unused_labels,
            )
            return 0

        if args.action == "gmail-populate-labels":
            provider = get_provider_for_settings(settings, "gmail")
            ensure_labels = getattr(provider, "ensure_user_labels", None)
            list_threads = getattr(provider, "list_threads_by_query", None)
            add_labels = getattr(provider, "add_labels_to_thread", None)
            replace_labels = getattr(provider, "replace_thread_labels", None)
            if not callable(ensure_labels) or not callable(list_threads) or not callable(add_labels):
                raise RuntimeError("The configured Gmail provider cannot populate labels.")
            days = max(1, int(getattr(args, "days", 7) or 7))
            apply_labels = bool(getattr(args, "apply_labels", False))
            categories = settings.mailassist_categories
            reporter.emit(
                "organize_phase",
                message="Preparing Gmail MailAssist labels.",
                provider="gmail",
                phase="preparing_labels",
                days=days,
                apply_labels=apply_labels,
                categories=list(categories),
            )
            label_ids = ensure_labels(_mailassist_gmail_label_names(categories))
            category_label_names = [_gmail_label_for_category(category) for category in categories]
            limit = max(1, int(getattr(args, "limit", 100) or 100))
            reporter.emit(
                "organize_phase",
                message=f"Reading Gmail threads from the last {days} days.",
                provider="gmail",
                phase="reading_threads",
                days=days,
                limit=limit,
            )
            threads = list_threads(f"newer_than:{days}d", max_threads=limit)
            classifier = OllamaClient(base_url, selected_model)
            applied_count = 0
            reporter.emit(
                "info",
                message="Classifying recent Gmail threads into MailAssist labels.",
                provider="gmail",
                days=days,
                thread_count=len(threads),
                apply_labels=apply_labels,
                categories=list(categories),
            )
            for index, thread in enumerate(threads, start=1):
                reporter.emit(
                    "gmail_thread_classification_started",
                    provider="gmail",
                    thread_id=thread.thread_id,
                    subject=thread.subject,
                    current_index=index,
                    thread_count=len(threads),
                    message_count=len(thread.messages),
                )
                category, classification_source, classification_error = _mailassist_category_for_thread(
                    thread,
                    categories,
                    classifier=classifier,
                )
                label_names = [_gmail_label_for_category(category)] if category else []
                if apply_labels:
                    add_label_ids = [label_ids[name] for name in label_names if name in label_ids]
                    remove_label_ids = [
                        label_ids[name]
                        for name in category_label_names
                        if name in label_ids and name not in label_names
                    ]
                    if callable(replace_labels):
                        replace_labels(thread.thread_id, add_label_ids, remove_label_ids)
                    else:
                        add_labels(thread.thread_id, add_label_ids)
                    applied_count += 1
                reporter.emit(
                    "gmail_thread_labeled" if apply_labels else "gmail_thread_label_preview",
                    provider="gmail",
                    thread_id=thread.thread_id,
                    subject=thread.subject,
                    classification=fallback_classification_for_thread(thread),
                    category=category or MAILASSIST_NO_CATEGORY,
                    classification_source=classification_source,
                    classification_error=classification_error,
                    labels=label_names,
                    message_count=len(thread.messages),
                )
            reporter.emit(
                "completed",
                message=(
                    "Gmail MailAssist label population completed."
                    if apply_labels
                    else "Gmail MailAssist label population dry run completed."
                ),
                provider="gmail",
                days=days,
                thread_count=len(threads),
                applied_count=applied_count,
                dry_run=not apply_labels,
            )
            return 0

        if args.action == "outlook-smoke-test":
            provider = get_provider_for_settings(settings, "outlook")
            reporter.emit(
                "info",
                message="Running Outlook Microsoft Graph smoke test.",
                provider="outlook",
                create_draft=bool(getattr(args, "create_draft", False)),
            )
            readiness = provider.readiness_check()
            reporter.emit(
                "outlook_readiness",
                provider="outlook",
                status=readiness.status,
                ready=readiness.ready,
                message=readiness.message,
                account_email=readiness.account_email,
                can_authenticate=readiness.can_authenticate,
                can_read=readiness.can_read,
                can_create_drafts=readiness.can_create_drafts,
                requires_admin_consent=readiness.requires_admin_consent,
                details=readiness.details,
            )
            if not readiness.ready:
                reporter.emit(
                    "completed",
                    message="Outlook smoke test stopped before mailbox reads because provider is not ready.",
                    provider="outlook",
                    ready=False,
                    thread_count=0,
                    draft_count=0,
                )
                return 0

            threads = provider.list_candidate_threads()
            limit = max(1, int(getattr(args, "limit", 10) or 10))
            selected_thread_id = str(getattr(args, "thread_id", "") or "").strip()
            visible_threads = threads[:limit]
            for thread in visible_threads:
                reporter.emit(
                    "outlook_thread_preview",
                    provider="outlook",
                    thread_id=thread.thread_id,
                    subject=thread.subject,
                    unread=thread.unread,
                    message_count=len(thread.messages),
                    latest_message_id=thread.messages[-1].message_id if thread.messages else "",
                    latest_sender=thread.messages[-1].sender if thread.messages else "",
                )

            draft_count = 0
            if bool(getattr(args, "create_draft", False)):
                if not selected_thread_id:
                    raise RuntimeError("--thread-id is required with outlook-smoke-test --create-draft")
                thread = next((item for item in threads if item.thread_id == selected_thread_id), None)
                if thread is None:
                    raise RuntimeError(f"Outlook thread not found for controlled draft: {selected_thread_id}")
                recipient = _safe_reply_recipient(thread, readiness.account_email)
                draft = DraftRecord(
                    draft_id=f"controlled-outlook-{thread.thread_id}",
                    thread_id=thread.thread_id,
                    provider="outlook",
                    subject=f"Re: {thread.subject}",
                    body=(
                        "MailAssist controlled Outlook draft test. "
                        "This draft validates Microsoft Graph write access and should be deleted."
                    ),
                    model="controlled-test",
                    to=[recipient] if recipient else [],
                    **reply_metadata_for_thread(thread, user_address=readiness.account_email or ""),
                )
                reference = provider.create_draft(draft)
                draft_count = 1
                reporter.emit(
                    "draft_created",
                    provider="outlook",
                    thread_id=thread.thread_id,
                    subject=draft.subject,
                    classification="controlled_test",
                    provider_draft_id=reference.draft_id,
                    provider_thread_id=reference.thread_id,
                    provider_message_id=reference.message_id,
                    generation_model=draft.model,
                )

            reporter.emit(
                "completed",
                message="Outlook smoke test completed.",
                provider="outlook",
                ready=True,
                thread_count=len(threads),
                preview_count=len(visible_threads),
                draft_count=draft_count,
            )
            return 0

        if args.action == "outlook-populate-categories":
            provider = get_provider_for_settings(settings, "outlook")
            readiness = provider.readiness_check()
            reporter.emit(
                "outlook_readiness",
                provider="outlook",
                status=readiness.status,
                ready=readiness.ready,
                message=readiness.message,
                account_email=readiness.account_email,
                can_authenticate=readiness.can_authenticate,
                can_read=readiness.can_read,
                can_create_drafts=readiness.can_create_drafts,
                requires_admin_consent=readiness.requires_admin_consent,
                details=readiness.details,
            )
            if not readiness.ready:
                reporter.emit(
                    "completed",
                    message="Outlook category population stopped because provider is not ready.",
                    provider="outlook",
                    ready=False,
                    thread_count=0,
                    applied_count=0,
                    dry_run=True,
                )
                return 0

            list_threads = getattr(provider, "list_recent_threads", None)
            replace_categories = getattr(provider, "replace_thread_categories", None)
            if not callable(list_threads):
                raise RuntimeError("The configured Outlook provider cannot list recent threads.")
            apply_categories = bool(getattr(args, "apply_categories", False))
            if apply_categories and not callable(replace_categories):
                raise RuntimeError("The configured Outlook provider cannot update categories.")

            categories = settings.mailassist_categories
            outlook_category_names = [_outlook_category_for_category(category) for category in categories]
            days = max(1, int(getattr(args, "days", 7) or 7))
            limit = max(1, int(getattr(args, "limit", 100) or 100))
            reporter.emit(
                "organize_phase",
                message=f"Reading Outlook threads from the last {days} days.",
                provider="outlook",
                phase="reading_threads",
                days=days,
                limit=limit,
                apply_categories=apply_categories,
                categories=list(categories),
            )
            threads = [
                thread
                for thread in list_threads(limit=limit)
                if _thread_within_days(thread, days)
            ]
            classifier = OllamaClient(base_url, selected_model)
            applied_count = 0
            message_update_count = 0
            reporter.emit(
                "info",
                message="Classifying Outlook threads into MailAssist categories.",
                provider="outlook",
                days=days,
                thread_count=len(threads),
                apply_categories=apply_categories,
                categories=list(categories),
            )
            for index, thread in enumerate(threads, start=1):
                reporter.emit(
                    "outlook_thread_classification_started",
                    provider="outlook",
                    thread_id=thread.thread_id,
                    subject=thread.subject,
                    current_index=index,
                    thread_count=len(threads),
                    message_count=len(thread.messages),
                )
                category, classification_source, classification_error = _mailassist_category_for_thread(
                    thread,
                    categories,
                    classifier=classifier,
                )
                category_names = [_outlook_category_for_category(category)] if category else []
                updated_messages = 0
                if apply_categories:
                    updated_messages = replace_categories(
                        thread.thread_id,
                        add_categories=category_names,
                        remove_categories=outlook_category_names,
                    )
                    applied_count += 1
                    message_update_count += updated_messages
                reporter.emit(
                    "outlook_thread_categorized"
                    if apply_categories
                    else "outlook_thread_category_preview",
                    provider="outlook",
                    thread_id=thread.thread_id,
                    subject=thread.subject,
                    classification=fallback_classification_for_thread(thread),
                    category=category or MAILASSIST_NO_CATEGORY,
                    classification_source=classification_source,
                    classification_error=classification_error,
                    categories=category_names,
                    message_count=len(thread.messages),
                    updated_message_count=updated_messages,
                )
            reporter.emit(
                "completed",
                message=(
                    "Outlook MailAssist category population completed."
                    if apply_categories
                    else "Outlook MailAssist category population dry run completed."
                ),
                provider="outlook",
                days=days,
                thread_count=len(threads),
                applied_count=applied_count,
                message_update_count=message_update_count,
                dry_run=not apply_categories,
            )
            return 0

        if args.action == "gmail-controlled-draft":
            provider = get_provider_for_settings(settings, "gmail")
            thread_id = args.thread_id or "thread-008"
            thread = next(
                (item for item in build_mock_threads() if item.thread_id == thread_id),
                None,
            )
            if thread is None:
                raise RuntimeError(f"Controlled test thread not found: {thread_id}")
            body = "Thanks for the note. I am reviewing this. Final decision/details to add before sending."
            generation_model = selected_model or "controlled-test"
            attribution_placement = (
                settings.draft_attribution_placement
                if settings.draft_attribution_placement != ATTRIBUTION_HIDE
                else ATTRIBUTION_BELOW_SIGNATURE
            )
            body = append_draft_attribution(
                body,
                model=generation_model,
                placement=attribution_placement,
                signature=settings.user_signature,
            )
            account_getter = getattr(provider, "get_account_email", None)
            account_email = account_getter() if callable(account_getter) else None
            draft = DraftRecord(
                draft_id=f"controlled-gmail-{thread.thread_id}",
                thread_id=thread.thread_id,
                provider="gmail",
                subject=f"MailAssist controlled draft test - Re: {thread.subject}",
                body=body_with_review_context(
                    thread,
                    body,
                    user_address="you@example.com",
                ),
                body_html=build_draft_body_html(
                    thread,
                    body,
                    signature=settings.user_signature,
                    signature_html=settings.user_signature_html,
                    model=generation_model,
                    attribution_placement=attribution_placement,
                    user_address="you@example.com",
                ),
                model=generation_model,
                to=[str(account_email).strip()] if str(account_email or "").strip() else [],
            )
            reporter.emit(
                "info",
                message="Creating one controlled Gmail draft with sanitized mock content.",
                provider="gmail",
                thread_id=thread.thread_id,
            )
            reference = provider.create_draft(draft)
            reporter.emit(
                "draft_created",
                provider="gmail",
                thread_id=thread.thread_id,
                subject=draft.subject,
                classification="controlled_test",
                provider_draft_id=reference.draft_id,
                provider_thread_id=reference.thread_id,
                provider_message_id=reference.message_id,
                generation_model=generation_model,
            )
            reporter.emit(
                "completed",
                message="Controlled Gmail draft created.",
                provider="gmail",
                draft_count=1,
                draft_ready_count=0,
                skipped_count=0,
                already_handled_count=0,
                user_replied_count=0,
                filtered_out_count=0,
            )
            return 0

        if args.action == "watch-once":
            provider_name = getattr(args, "provider", "mock") or "mock"
            provider = get_provider_for_settings(settings, provider_name)
            reporter.emit(
                "info",
                message=f"Running one watch pass for {provider_name}.",
                provider=provider_name,
            )
            events = run_watch_pass(
                settings=settings,
                provider=provider,
                base_url=base_url,
                selected_model=selected_model,
                thread_id=args.thread_id or "",
                force=bool(getattr(args, "force", False)),
                batch_size=max(1, int(getattr(args, "batch_size", 1) or 1)),
                dry_run=bool(getattr(args, "dry_run", False)),
                max_candidates=max(1, int(getattr(args, "limit", 10) or 10)),
            )
            draft_count = 0
            draft_ready_count = 0
            skipped_count = 0
            already_handled_count = 0
            user_replied_count = 0
            filtered_out_count = 0
            for event in events:
                event_type = str(event.pop("type"))
                if event_type == "draft_created":
                    draft_count += 1
                elif event_type == "draft_ready":
                    draft_ready_count += 1
                elif event_type == "skipped_email":
                    skipped_count += 1
                elif event_type == "already_handled":
                    already_handled_count += 1
                elif event_type == "user_replied":
                    user_replied_count += 1
                elif event_type == "filtered_out":
                    filtered_out_count += 1
                reporter.emit(event_type, **event)
            reporter.emit(
                "completed",
                message="Watch pass completed.",
                provider=provider_name,
                draft_count=draft_count,
                draft_ready_count=draft_ready_count,
                skipped_count=skipped_count,
                already_handled_count=already_handled_count,
                user_replied_count=user_replied_count,
                filtered_out_count=filtered_out_count,
                dry_run=bool(getattr(args, "dry_run", False)),
            )
            return 0

        if args.action == "watch-loop":
            provider_name = getattr(args, "provider", "mock") or "mock"
            provider = get_provider_for_settings(settings, provider_name)
            poll_seconds = max(1, int(getattr(args, "poll_seconds", 0) or settings.bot_poll_seconds or 30))
            max_passes = max(0, int(getattr(args, "max_passes", 0) or 0))
            completed_passes = 0
            total_draft_count = 0
            total_draft_ready_count = 0
            total_skipped_count = 0
            total_already_handled_count = 0
            total_user_replied_count = 0
            total_filtered_out_count = 0
            failed_pass_count = 0
            retry_count = 0
            reporter.emit(
                "info",
                message=f"Starting polling watch loop for {provider_name}.",
                provider=provider_name,
                poll_seconds=poll_seconds,
                max_passes=max_passes,
            )

            while True:
                completed_passes += 1
                pass_failed = False
                reporter.emit(
                    "watch_pass_started",
                    provider=provider_name,
                    pass_number=completed_passes,
                )
                try:
                    events = run_watch_pass(
                        settings=settings,
                        provider=provider,
                        base_url=base_url,
                        selected_model=selected_model,
                        thread_id=args.thread_id or "",
                        force=bool(getattr(args, "force", False)),
                        batch_size=max(1, int(getattr(args, "batch_size", 1) or 1)),
                        dry_run=bool(getattr(args, "dry_run", False)),
                    )
                    for event in events:
                        event_type = str(event.pop("type"))
                        if event_type == "draft_created":
                            total_draft_count += 1
                        elif event_type == "draft_ready":
                            total_draft_ready_count += 1
                        elif event_type == "skipped_email":
                            total_skipped_count += 1
                        elif event_type == "already_handled":
                            total_already_handled_count += 1
                        elif event_type == "user_replied":
                            total_user_replied_count += 1
                        elif event_type == "filtered_out":
                            total_filtered_out_count += 1
                        reporter.emit(event_type, **event)
                    reporter.emit(
                        "watch_pass_completed",
                        provider=provider_name,
                        pass_number=completed_passes,
                    )
                except Exception as exc:
                    pass_failed = True
                    failed_pass_count += 1
                    reporter.emit(
                        "failed_pass",
                        provider=provider_name,
                        pass_number=completed_passes,
                        message=str(exc),
                    )
                if max_passes and completed_passes >= max_passes:
                    break
                if pass_failed:
                    retry_count += 1
                    reporter.emit(
                        "retry_scheduled",
                        provider=provider_name,
                        pass_number=completed_passes + 1,
                        poll_seconds=poll_seconds,
                    )
                reporter.emit(
                    "sleeping",
                    provider=provider_name,
                    poll_seconds=poll_seconds,
                )
                time.sleep(poll_seconds)

            reporter.emit(
                "completed",
                message="Watch loop completed.",
                provider=provider_name,
                completed_passes=completed_passes,
                draft_count=total_draft_count,
                draft_ready_count=total_draft_ready_count,
                skipped_count=total_skipped_count,
                already_handled_count=total_already_handled_count,
                user_replied_count=total_user_replied_count,
                filtered_out_count=total_filtered_out_count,
                failed_pass_count=failed_pass_count,
                retry_count=retry_count,
                dry_run=bool(getattr(args, "dry_run", False)),
            )
            return 0

        if args.action == "ollama-check":
            prompt = (args.prompt or "").strip()
            if not prompt:
                raise ValueError("--prompt is required for ollama-check")
            reporter.emit("info", message="Running Ollama check.")
            result = OllamaClient(base_url, selected_model).compose_reply(prompt)
            reporter.emit("ollama_result", prompt=prompt, result=result or "")
            reporter.emit(
                "completed",
                message="Ollama check completed.",
                base_url=base_url,
                selected_model=selected_model,
            )
            return 0

        raise ValueError(f"Unsupported bot action: {args.action}")
    except Exception as exc:
        reporter.emit("error", message=str(exc))
        return 1


def _safe_reply_recipient(thread, account_email: str | None) -> str:
    account = str(account_email or "").strip().lower()
    for message in reversed(thread.messages):
        sender = str(message.sender or "").strip().lower()
        if sender and sender != account:
            return sender
    for participant in thread.participants:
        address = str(participant or "").strip().lower()
        if address and address != account:
            return address
    return ""


def _mailassist_labels_for_thread(thread) -> list[str]:
    category, _source, _error = _mailassist_category_for_thread(
        thread,
        DEFAULT_MAILASSIST_CATEGORIES,
        classifier=None,
    )
    return [_gmail_label_for_category(category)]


def _mailassist_category_for_thread(
    thread,
    categories: tuple[str, ...] | list[str],
    *,
    classifier: OllamaClient | None,
) -> tuple[str | None, str, str | None]:
    normalized_categories = _normalized_categories(categories)
    if classifier is not None:
        prompt = _mailassist_category_prompt(thread, normalized_categories)
        try:
            response = classifier.compose_reply(prompt)
            parsed = _parse_mailassist_category_response(response, normalized_categories)
            if parsed != "":
                guarded = _guard_mailassist_category(thread, parsed, normalized_categories)
                return guarded, "ollama", None
            return (
                _fallback_mailassist_category(thread, normalized_categories),
                "fallback",
                f"Ollama returned an unknown category: {response[:120]}",
            )
        except RuntimeError as exc:
            return _fallback_mailassist_category(thread, normalized_categories), "fallback", str(exc)
    return _fallback_mailassist_category(thread, normalized_categories), "fallback", None


def _normalized_categories(categories: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    resolved = [LOCKED_NEEDS_REPLY_CATEGORY]
    for category in categories:
        cleaned = str(category).replace("/", " ").strip()
        if not cleaned or cleaned.lower() == LOCKED_NEEDS_REPLY_CATEGORY.lower():
            continue
        if cleaned.lower() not in {item.lower() for item in resolved}:
            resolved.append(cleaned)
    return tuple(resolved)


def _mailassist_category_prompt(thread, categories: tuple[str, ...]) -> str:
    messages = "\n\n".join(
        f"From: {message.sender}\nTo: {', '.join(message.to)}\nDate: {message.sent_at}\nBody:\n{message.text[:4000]}"
        for message in thread.messages[-3:]
    )
    category_lines = "\n".join(f"- {category}" for category in categories)
    return f"""You classify email threads for MailAssist email organization.

Choose exactly one category from the allowed list, or return NA when there is no obvious fit.
Return only the category name, exactly as written, or NA. Do not explain.

Allowed categories:
{category_lines}
Allowed no-category responses:
- NA
- No obvious category

Decision rules:
- {LOCKED_NEEDS_REPLY_CATEGORY}: choose this only when the sender likely expects a human reply from the user. This category drives draft generation.
- Needs Action: choose this when the user must do something but a reply is not the primary next step, such as pay, approve, confirm, review, upload, renew, sign, schedule, or fix an account issue.
- For all other categories, choose the single best fit from the user's allowed list.
- If multiple categories seem possible, choose the one that represents the user's most likely next action.
- If none of the allowed categories clearly apply, return NA.

Thread:
Subject: {thread.subject}
Participants: {", ".join(thread.participants)}

Messages:
{messages}
"""


def _parse_mailassist_category_response(response: str, categories: tuple[str, ...]) -> str | None:
    cleaned = response.strip().strip("`").strip()
    if "\n" in cleaned:
        cleaned = cleaned.splitlines()[0].strip()
    cleaned = cleaned.strip('"').strip("'").strip()
    if cleaned.lower() in {"na", "n/a", "no obvious category", "no category", "none"}:
        return None
    for category in categories:
        if cleaned.lower() == category.lower():
            return category
    return ""


def _fallback_mailassist_category(thread, categories: tuple[str, ...]) -> str | None:
    haystack = " ".join(
        [thread.subject, *thread.participants, *(message.text for message in thread.messages)]
    ).lower()
    classification = fallback_classification_for_thread(thread)

    if classification in {"urgent", "reply_needed"}:
        needs_reply = _category_if_enabled(LOCKED_NEEDS_REPLY_CATEGORY, categories)
        if needs_reply:
            return needs_reply

    if _contains_any(
        haystack,
        (
            "action needed",
            "approve",
            "approval",
            "sign",
            "signature",
            "upload",
            "complete",
            "review",
            "renew",
            "pay",
            "payment due",
            "confirm",
            "verification required",
        ),
    ):
        return _category_if_enabled("Needs Action", categories)

    if _contains_any(haystack, ("unsubscribe", "newsletter", "digest", "webinar", "promotion")):
        return _category_if_enabled("Subscriptions", categories)

    if _contains_any(
        haystack,
        (
            "license",
            "licenses",
            "subscription",
            "account",
            "login",
            "password",
            "security alert",
            "domain",
            "hosting",
            "api key",
            "renewal",
        ),
    ):
        return _category_if_enabled("Licenses & Accounts", categories)

    if _contains_any(
        haystack,
        ("receipt", "invoice", "order", "payment", "paid", "bank", "credit card", "statement", "refund"),
    ):
        return _category_if_enabled("Receipts & Finance", categories)

    if _contains_any(
        haystack,
        ("appointment", "calendar", "meeting", "reservation", "booking", "schedule", "scheduled"),
    ):
        return _category_if_enabled("Appointments", categories)

    if classification == "spam" or _contains_any(haystack, ("phishing", "wire money", "lottery", "crypto")):
        return _category_if_enabled("Suspicious", categories)

    return _category_if_enabled("FYI", categories)


def _guard_mailassist_category(thread, category: str | None, categories: tuple[str, ...]) -> str | None:
    if category is None:
        return None
    if category.lower() != LOCKED_NEEDS_REPLY_CATEGORY.lower():
        return category
    if _looks_automated_for_needs_reply(thread):
        return _fallback_mailassist_category(
            thread,
            tuple(item for item in categories if item.lower() != LOCKED_NEEDS_REPLY_CATEGORY.lower()),
        )
    classification = fallback_classification_for_thread(thread)
    if classification in {"urgent", "reply_needed"}:
        return category
    fallback = _fallback_mailassist_category(
        thread,
        tuple(item for item in categories if item.lower() != LOCKED_NEEDS_REPLY_CATEGORY.lower()),
    )
    return fallback


def _looks_automated_for_needs_reply(thread) -> bool:
    haystack = " ".join(
        [thread.subject, *thread.participants, *(message.text for message in thread.messages)]
    ).lower()
    return _contains_any(
        haystack,
        (
            "unsubscribe",
            "no-reply",
            "noreply",
            "do not reply",
            "automated notification",
            "automated email",
            "newsletter",
            "digest",
            "notificationmail",
            "promomail",
        ),
    )


def _thread_within_days(thread, days: int) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, days))
    for message in thread.messages:
        parsed = _parse_message_datetime(str(message.sent_at or ""))
        if parsed is not None and parsed >= cutoff:
            return True
    return False


def _parse_message_datetime(value: str) -> datetime | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _category_if_enabled(category: str, categories: tuple[str, ...]) -> str | None:
    for item in categories:
        if item.lower() == category.lower():
            return item
    return None


def _contains_any(haystack: str, needles: tuple[str, ...]) -> bool:
    return any(needle in haystack for needle in needles)
