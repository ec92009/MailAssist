from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    data_dir: Path
    drafts_dir: Path
    logs_dir: Path
    bot_logs_dir: Path
    mock_provider_drafts_dir: Path
    ollama_url: str
    ollama_model: str
    user_signature: str
    user_tone: str
    bot_poll_seconds: int
    default_provider: str
    gmail_enabled: bool
    outlook_enabled: bool
    gmail_credentials_file: Path
    gmail_token_file: Path
    outlook_client_id: str
    outlook_tenant_id: str
    outlook_redirect_uri: str


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value.strip())
    except ValueError:
        return default


def load_dotenv(env_file: Path) -> None:
    if not env_file.exists():
        return

    for line in env_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ[key.strip()] = value.strip()


def read_env_file(env_file: Path) -> Dict[str, str]:
    data: Dict[str, str] = {}
    if not env_file.exists():
        return data

    for line in env_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def write_env_file(env_file: Path, values: Dict[str, str]) -> None:
    env_file.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key}={value}" for key, value in sorted(values.items())]
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def default_root_dir() -> Path:
    configured_root = os.getenv("MAILASSIST_ROOT_DIR", "").strip()
    if configured_root:
        return Path(configured_root).expanduser()
    if getattr(sys, "frozen", False):
        return Path.home() / "Library" / "Application Support" / "MailAssist"
    return Path.cwd()


def load_settings() -> Settings:
    root_dir = default_root_dir()
    load_dotenv(root_dir / ".env")

    data_dir = root_dir / "data"
    drafts_dir = data_dir / "drafts"
    logs_dir = data_dir / "logs"
    bot_logs_dir = data_dir / "bot-logs"
    mock_provider_drafts_dir = data_dir / "mock-provider-drafts"

    return Settings(
        root_dir=root_dir,
        data_dir=data_dir,
        drafts_dir=drafts_dir,
        logs_dir=logs_dir,
        bot_logs_dir=bot_logs_dir,
        mock_provider_drafts_dir=mock_provider_drafts_dir,
        ollama_url=os.getenv("MAILASSIST_OLLAMA_URL", "http://localhost:11434"),
        ollama_model=os.getenv("MAILASSIST_OLLAMA_MODEL", "llama3.1:8b"),
        user_signature=os.getenv("MAILASSIST_USER_SIGNATURE", "").replace("\\n", "\n"),
        user_tone=os.getenv("MAILASSIST_USER_TONE", "direct_concise"),
        bot_poll_seconds=parse_int(os.getenv("MAILASSIST_BOT_POLL_SECONDS"), 60),
        default_provider=os.getenv("MAILASSIST_DEFAULT_PROVIDER", "gmail"),
        gmail_enabled=parse_bool(os.getenv("MAILASSIST_GMAIL_ENABLED"), default=True),
        outlook_enabled=parse_bool(os.getenv("MAILASSIST_OUTLOOK_ENABLED"), default=False),
        gmail_credentials_file=Path(
            os.getenv(
                "MAILASSIST_GMAIL_CREDENTIALS_FILE",
                str(root_dir / "secrets" / "gmail-client-secret.json"),
            )
        ),
        gmail_token_file=Path(
            os.getenv(
                "MAILASSIST_GMAIL_TOKEN_FILE",
                str(root_dir / "secrets" / "gmail-token.json"),
            )
        ),
        outlook_client_id=os.getenv("MAILASSIST_OUTLOOK_CLIENT_ID", ""),
        outlook_tenant_id=os.getenv("MAILASSIST_OUTLOOK_TENANT_ID", ""),
        outlook_redirect_uri=os.getenv(
            "MAILASSIST_OUTLOOK_REDIRECT_URI", "http://localhost:8765/outlook/callback"
        ),
    )
