from __future__ import annotations

import argparse
import getpass
import re
from pathlib import Path


CLIENT_ID_KEY = "MAILASSIST_OUTLOOK_CLIENT_ID"
GUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{12}$"
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def update_env_text(text: str, key: str, value: str) -> str:
    assignment = f"{key}={value}"
    lines = text.splitlines()
    replaced = False
    updated: list[str] = []

    for line in lines:
        stripped = line.lstrip()
        if not stripped.startswith("#") and re.match(rf"^\s*{re.escape(key)}\s*=", line):
            updated.append(assignment)
            replaced = True
        else:
            updated.append(line)

    if not replaced:
        if updated and updated[-1].strip():
            updated.append("")
        updated.append(assignment)

    return "\n".join(updated) + "\n"


def store_client_id(env_file: Path, client_id: str) -> None:
    existing = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text(
        update_env_text(existing, CLIENT_ID_KEY, client_id),
        encoding="utf-8",
    )


def prompt_client_id() -> str:
    return getpass.getpass("Outlook Application (client) ID: ").strip()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Store the Outlook Microsoft Entra Application (client) ID in the local .env file."
        )
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=repo_root() / ".env",
        help="Path to the .env file to update. Defaults to the repo-local .env.",
    )
    args = parser.parse_args()

    client_id = prompt_client_id()
    if not client_id or client_id.startswith("<"):
        print("No client id stored: the value is empty or still a placeholder.")
        return 1
    if not GUID_PATTERN.match(client_id):
        print("No client id stored: Microsoft Entra Application (client) IDs are GUIDs.")
        return 1

    store_client_id(args.env_file, client_id)
    print(f"Stored {CLIENT_ID_KEY} in {args.env_file}.")
    print(f"Loaded client id ending: {client_id[-3:]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
