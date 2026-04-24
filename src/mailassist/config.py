from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    data_dir: Path
    drafts_dir: Path
    logs_dir: Path
    site_dir: Path
    ollama_url: str
    ollama_model: str
    gmail_credentials_file: Path
    gmail_token_file: Path


def load_dotenv(env_file: Path) -> None:
    if not env_file.exists():
        return

    for line in env_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def load_settings() -> Settings:
    root_dir = Path.cwd()
    load_dotenv(root_dir / ".env")

    data_dir = root_dir / "data"
    drafts_dir = data_dir / "drafts"
    logs_dir = data_dir / "logs"
    site_dir = root_dir / "site"

    return Settings(
        root_dir=root_dir,
        data_dir=data_dir,
        drafts_dir=drafts_dir,
        logs_dir=logs_dir,
        site_dir=site_dir,
        ollama_url=os.getenv("MAILASSIST_OLLAMA_URL", "http://localhost:11434"),
        ollama_model=os.getenv("MAILASSIST_OLLAMA_MODEL", "llama3.1:8b"),
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
    )
