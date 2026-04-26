from __future__ import annotations

import argparse
from mailassist.bot_runtime import build_review_bot_parser, command_review_bot
from mailassist.config import load_settings
from mailassist.models import DraftRecord
from mailassist.providers.gmail import GmailProvider


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mailassist")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("gmail-auth", help="Run Gmail OAuth setup and save the token.")
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

def command_desktop_gui() -> int:
    from mailassist.gui.desktop import run_desktop_gui

    return run_desktop_gui()


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "gmail-auth":
        return command_gmail_auth()
    if args.command == "desktop-gui":
        return command_desktop_gui()
    if args.command == "review-bot":
        return command_review_bot(args)

    parser.error(f"Unknown command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
