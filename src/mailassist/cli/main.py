from __future__ import annotations

import argparse
from mailassist.bot_runtime import build_review_bot_parser, command_review_bot
from mailassist.config import load_settings
from mailassist.models import DraftRecord, EmailThread
from mailassist.providers.base import ProviderReadiness
from mailassist.providers.gmail import GmailProvider
from mailassist.providers.outlook import OutlookGraphAuthError, OutlookProvider


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mailassist")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("gmail-auth", help="Run Gmail OAuth setup and save the token.")
    subparsers.add_parser(
        "outlook-auth",
        help="Run Outlook Microsoft Graph OAuth setup and save the token.",
    )
    outlook_setup = subparsers.add_parser(
        "outlook-setup-check",
        help="Authorize Outlook and run read-only Microsoft Graph readiness checks.",
    )
    outlook_setup.add_argument(
        "--expected-email",
        default="",
        help="Optional mailbox email that must match the signed-in Outlook account.",
    )
    outlook_setup.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum number of inbox thread subjects to preview.",
    )
    subparsers.add_parser(
        "desktop-gui", help="Run the native PySide6 desktop bot control panel."
    )
    build_review_bot_parser(subparsers)
    return parser


def command_gmail_auth() -> int:
    settings = load_settings()
    provider = GmailProvider(settings.gmail_credentials_file, settings.gmail_token_file)
    provider.create_draft(
        DraftRecord(
            draft_id="gmail-auth-check",
            thread_id="gmail-auth-check",
            provider="gmail",
            subject="MailAssist auth check",
            body="This temporary draft verifies Gmail authentication. Delete it if created.",
            model="n/a",
        )
    )
    print("Authentication succeeded and a temporary Gmail draft was created.")
    return 0


def command_outlook_auth() -> int:
    settings = load_settings()
    provider = _outlook_provider_for_settings(settings)
    provider.authenticate()
    account_email = provider.get_account_email()
    suffix = f" for {account_email}" if account_email else ""
    print(f"Outlook authentication succeeded{suffix}.")
    return 0


def command_outlook_setup_check(args: argparse.Namespace) -> int:
    settings = load_settings()
    provider = _outlook_provider_for_settings(settings)
    expected_email = str(getattr(args, "expected_email", "") or "").strip().lower()
    limit = max(1, int(getattr(args, "limit", 5) or 5))

    print("MailAssist Outlook setup check")
    print("This is read-only. It will not create drafts or send email.")
    print("Requested Graph scopes: offline_access, User.Read, Mail.ReadWrite.")
    print("MailAssist does not request Mail.Send.")
    print()

    try:
        provider.authenticate()
    except OutlookGraphAuthError as exc:
        _print_outlook_auth_failure(exc)
        return 1

    readiness = provider.readiness_check()
    _print_outlook_readiness(readiness)
    if not readiness.ready:
        return 1

    account_email = (readiness.account_email or provider.get_account_email() or "").lower()
    if expected_email and account_email != expected_email:
        print()
        print("Signed-in mailbox does not match the expected account.")
        print(f"Expected: {expected_email}")
        print(f"Actual:   {account_email or '(unknown)'}")
        print("Stop here and sign in with the intended Outlook account.")
        return 1

    try:
        threads = provider.list_candidate_threads()[:limit]
    except Exception as exc:
        print()
        print(f"Outlook inbox preview failed: {exc}")
        return 1

    print()
    print(f"Inbox preview: {len(threads)} thread{'s' if len(threads) != 1 else ''}")
    for index, thread in enumerate(threads, start=1):
        print(f"{index}. {_safe_thread_subject(thread)}")
    print()
    print("Setup check completed. No drafts were created and no email was sent.")
    return 0


def command_desktop_gui() -> int:
    from mailassist.gui.desktop import run_desktop_gui

    return run_desktop_gui()


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "gmail-auth":
        return command_gmail_auth()
    if args.command == "outlook-auth":
        return command_outlook_auth()
    if args.command == "outlook-setup-check":
        return command_outlook_setup_check(args)
    if args.command == "desktop-gui":
        return command_desktop_gui()
    if args.command == "review-bot":
        return command_review_bot(args)

    parser.error(f"Unknown command {args.command}")
    return 2


def _outlook_provider_for_settings(settings) -> OutlookProvider:
    return OutlookProvider(
        client_id=settings.outlook_client_id,
        tenant_id=settings.outlook_tenant_id,
        redirect_uri=settings.outlook_redirect_uri,
        token_file=settings.outlook_token_file,
    )


def _print_outlook_auth_failure(exc: OutlookGraphAuthError) -> None:
    print()
    print(f"Outlook authorization failed: {exc}")
    if exc.requires_admin_consent:
        print("Microsoft says tenant admin approval is required.")
        print("Use docs/outlook-m365-admin-consent.md before trying again.")


def _print_outlook_readiness(readiness: ProviderReadiness) -> None:
    print()
    print(f"Outlook readiness: {readiness.status}")
    print(f"Message: {readiness.message}")
    if readiness.account_email:
        print(f"Mailbox: {readiness.account_email}")
    print(f"Can read mailbox: {'yes' if readiness.can_read else 'no'}")
    print(f"Can create drafts later: {'yes' if readiness.can_create_drafts else 'no'}")
    print(f"Admin consent required: {'yes' if readiness.requires_admin_consent else 'no'}")


def _safe_thread_subject(thread: EmailThread) -> str:
    subject = " ".join(thread.subject.split()) or "(no subject)"
    if len(subject) > 80:
        subject = f"{subject[:77]}..."
    unread = "unread" if thread.unread else "read"
    return f"{subject} ({unread}, {len(thread.messages)} message{'s' if len(thread.messages) != 1 else ''})"


if __name__ == "__main__":
    raise SystemExit(main())
