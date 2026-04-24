from __future__ import annotations

import argparse
import json
from pathlib import Path

from mailassist.config import load_settings
from mailassist.core.orchestrator import DraftOrchestrator
from mailassist.gui.server import serve_config_gui
from mailassist.llm.ollama import OllamaClient
from mailassist.models import DraftRecord
from mailassist.providers.gmail import GmailProvider
from mailassist.storage.filesystem import FileStorage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mailassist")
    subparsers = parser.add_subparsers(dest="command", required=True)

    draft_parser = subparsers.add_parser("draft-thread", help="Draft a reply for a thread JSON file.")
    draft_parser.add_argument("--thread-file", required=True, help="Path to the thread JSON file.")
    draft_parser.add_argument("--provider", default="gmail", help="Draft provider name.")
    draft_parser.add_argument(
        "--submit-provider-draft",
        action="store_true",
        help="Submit the generated draft to the provider in addition to saving locally.",
    )
    draft_parser.add_argument(
        "--revision-notes",
        help="Optional instruction for revising the tone or content.",
    )

    subparsers.add_parser("list-drafts", help="Print saved drafts as JSON.")
    subparsers.add_parser("list-logs", help="Print saved logs as JSON.")
    subparsers.add_parser("gmail-auth", help="Run Gmail OAuth setup and save the token.")
    gui_parser = subparsers.add_parser(
        "serve-config", help="Run the local configuration GUI for providers and Ollama."
    )
    gui_parser.add_argument("--host", default="127.0.0.1", help="Host to bind the GUI server.")
    gui_parser.add_argument("--port", type=int, default=8765, help="Port to bind the GUI server.")
    return parser


def command_draft_thread(args: argparse.Namespace) -> int:
    settings = load_settings()
    storage = FileStorage(settings.drafts_dir, settings.logs_dir)
    thread = storage.load_thread(Path(args.thread_file))
    llm = OllamaClient(settings.ollama_url, settings.ollama_model)
    orchestrator = DraftOrchestrator(storage, llm)

    provider = None
    provider_name = args.provider
    if args.submit_provider_draft:
        if provider_name != "gmail":
            raise SystemExit(f"Provider submission is not implemented yet for {provider_name}.")
        provider = GmailProvider(settings.gmail_credentials_file, settings.gmail_token_file)

    draft = orchestrator.draft_thread(
        thread,
        provider_name=provider_name,
        revision_notes=args.revision_notes,
        provider=provider,
    )
    print(json.dumps(draft.to_dict(), indent=2))
    return 0


def command_list_records(kind: str) -> int:
    settings = load_settings()
    storage = FileStorage(settings.drafts_dir, settings.logs_dir)
    data = storage.list_drafts() if kind == "drafts" else storage.list_logs()
    print(json.dumps(data, indent=2))
    return 0


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


def command_serve_config(args: argparse.Namespace) -> int:
    serve_config_gui(host=args.host, port=args.port)
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "draft-thread":
        return command_draft_thread(args)
    if args.command == "list-drafts":
        return command_list_records("drafts")
    if args.command == "list-logs":
        return command_list_records("logs")
    if args.command == "gmail-auth":
        return command_gmail_auth()
    if args.command == "serve-config":
        return command_serve_config(args)

    parser.error(f"Unknown command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
