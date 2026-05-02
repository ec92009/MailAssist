from __future__ import annotations

import os
import json
import logging
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from mailassist.contacts import ElderContact, load_elder_contacts
from mailassist.rich_text import html_to_plain_text, sanitize_html_fragment


ATTRIBUTION_HIDE = "hide"
ATTRIBUTION_ABOVE_SIGNATURE = "above_signature"
ATTRIBUTION_BELOW_SIGNATURE = "below_signature"
ATTRIBUTION_PLACEMENTS = {
    ATTRIBUTION_HIDE,
    ATTRIBUTION_ABOVE_SIGNATURE,
    ATTRIBUTION_BELOW_SIGNATURE,
}
LOCKED_NEEDS_REPLY_CATEGORY = "Needs Reply"
DEFAULT_MAILASSIST_CATEGORIES = (
    LOCKED_NEEDS_REPLY_CATEGORY,
    "Needs Action",
    "Subscriptions",
    "Licenses & Accounts",
    "Receipts & Finance",
    "Appointments",
    "FYI",
    "Suspicious",
)
APPEARANCE_SYSTEM = "system"
APPEARANCE_DAY = "day"
APPEARANCE_NIGHT = "night"
APPEARANCES = {APPEARANCE_SYSTEM, APPEARANCE_DAY, APPEARANCE_NIGHT}
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    data_dir: Path
    legacy_data_dir: Path
    drafts_dir: Path
    logs_dir: Path
    bot_logs_dir: Path
    mock_provider_drafts_dir: Path
    ollama_url: str
    ollama_model: str
    user_signature: str
    user_signature_html: str
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
    outlook_token_file: Path
    gmail_watcher_unread_only: bool
    gmail_watcher_time_window: str
    outlook_watcher_unread_only: bool
    outlook_watcher_time_window: str
    watcher_unread_only: bool
    watcher_time_window: str
    draft_attribution: bool
    draft_attribution_placement: str
    mailassist_categories: tuple[str, ...]
    elder_contacts_file: Path
    elder_contacts: tuple[ElderContact, ...]
    appearance: str


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


def parse_attribution_placement(value: str | None, *, fallback_enabled: bool = False) -> str:
    cleaned = (value or "").strip().lower().replace("-", "_")
    if cleaned in ATTRIBUTION_PLACEMENTS:
        return cleaned
    return ATTRIBUTION_BELOW_SIGNATURE if fallback_enabled else ATTRIBUTION_HIDE


def parse_mailassist_categories(value: str | None) -> tuple[str, ...]:
    raw = (value or "").strip()
    items: list[str] = []
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = [part.strip() for part in raw.split(",")]
        if isinstance(parsed, list):
            items = [str(item).strip() for item in parsed]

    categories: list[str] = [LOCKED_NEEDS_REPLY_CATEGORY]
    for item in items or list(DEFAULT_MAILASSIST_CATEGORIES):
        cleaned = item.replace("/", " ").strip()
        if not cleaned or cleaned.lower() == LOCKED_NEEDS_REPLY_CATEGORY.lower():
            continue
        if cleaned.lower() not in {category.lower() for category in categories}:
            categories.append(cleaned)
    return tuple(categories)


def parse_appearance(value: str | None) -> str:
    cleaned = (value or "").strip().lower()
    if cleaned in APPEARANCES:
        return cleaned
    return APPEARANCE_SYSTEM


def path_from_env(value: str | None, default: Path, *, root_dir: Path) -> Path:
    raw = (value or "").strip()
    path = Path(raw).expanduser() if raw else default
    if path.is_absolute():
        return path
    return root_dir / path


def load_dotenv(env_file: Path) -> None:
    if not env_file.exists():
        return

    for line in env_file.read_text(encoding="utf-8").splitlines():
        parsed = _parse_env_assignment(line)
        if parsed is None:
            continue
        key, value = parsed
        os.environ[key] = value


def read_env_file(env_file: Path) -> Dict[str, str]:
    data: Dict[str, str] = {}
    if not env_file.exists():
        return data

    for line in env_file.read_text(encoding="utf-8").splitlines():
        parsed = _parse_env_assignment(line)
        if parsed is None:
            continue
        key, value = parsed
        data[key] = value
    return data


def write_env_file(env_file: Path, values: Dict[str, str]) -> None:
    env_file.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key}={_format_env_value(value)}" for key, value in sorted(values.items())]
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _parse_env_assignment(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export ") :].lstrip()
    key, value = stripped.split("=", 1)
    key = key.strip()
    if not key:
        return None
    return key, _parse_env_value(value)


def _parse_env_value(value: str) -> str:
    lexer = shlex.shlex(value, posix=True)
    lexer.whitespace_split = False
    lexer.commenters = "#"
    lexer.whitespace = ""
    try:
        tokens = list(lexer)
    except ValueError:
        return value.strip()
    return "".join(tokens).strip()


def _format_env_value(value: str) -> str:
    text = str(value)
    if not text:
        return ""
    if any(char.isspace() for char in text) or any(char in text for char in "\"'#$\\"):
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text


def default_root_dir() -> Path:
    configured_root = os.getenv("MAILASSIST_ROOT_DIR", "").strip()
    if configured_root:
        return Path(configured_root).expanduser()
    if getattr(sys, "frozen", False):
        return Path.home() / "Library" / "Application Support" / "MailAssist"
    LOGGER.warning(
        "MAILASSIST_ROOT_DIR is not set; using the current working directory as the MailAssist root."
    )
    return Path.cwd()


def _move_file_if_needed(source: Path, destination: Path) -> None:
    if not source.exists() or destination.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    source.replace(destination)


def _merge_directory_if_needed(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    destination.mkdir(parents=True, exist_ok=True)
    for child in sorted(source.iterdir()):
        target = destination / child.name
        if child.is_dir():
            _merge_directory_if_needed(child, target)
        elif not target.exists():
            child.replace(target)
    try:
        source.rmdir()
    except OSError:
        pass


def migrate_legacy_runtime_layout(root_dir: Path) -> None:
    data_dir = root_dir / "data"
    legacy_dir = data_dir / "legacy"
    queue_dir = legacy_dir / "queue"

    _move_file_if_needed(data_dir / "review-inbox.json", legacy_dir / "review-inbox.json")
    _merge_directory_if_needed(data_dir / "drafts", legacy_dir / "drafts")
    _merge_directory_if_needed(data_dir / "logs", legacy_dir / "logs")

    for phase in (
        "bot_processed",
        "gui_acquired",
        "user_reviewed",
        "provider_drafted",
        "user_replied",
    ):
        _merge_directory_if_needed(data_dir / phase, queue_dir / phase)


def load_settings() -> Settings:
    root_dir = default_root_dir()
    env_values = read_env_file(root_dir / ".env")
    migrate_legacy_runtime_layout(root_dir)

    data_dir = root_dir / "data"
    legacy_data_dir = data_dir / "legacy"
    drafts_dir = legacy_data_dir / "drafts"
    logs_dir = legacy_data_dir / "logs"
    bot_logs_dir = data_dir / "bot-logs"
    mock_provider_drafts_dir = data_dir / "mock-provider-drafts"

    def env(name: str, default: str = "") -> str:
        return env_values.get(name, os.getenv(name, default))

    def optional_env(name: str) -> str | None:
        if name in env_values:
            return env_values[name]
        return os.environ.get(name)

    default_provider = env("MAILASSIST_DEFAULT_PROVIDER", "gmail")
    global_watcher_unread_only = parse_bool(env("MAILASSIST_WATCHER_UNREAD_ONLY"), default=False)
    global_watcher_time_window = env("MAILASSIST_WATCHER_TIME_WINDOW", "all")
    gmail_watcher_unread_only = parse_bool(
        optional_env("MAILASSIST_GMAIL_WATCHER_UNREAD_ONLY"),
        default=global_watcher_unread_only,
    )
    gmail_watcher_time_window = env(
        "MAILASSIST_GMAIL_WATCHER_TIME_WINDOW",
        global_watcher_time_window,
    )
    outlook_watcher_unread_only = parse_bool(
        optional_env("MAILASSIST_OUTLOOK_WATCHER_UNREAD_ONLY"),
        default=global_watcher_unread_only,
    )
    outlook_watcher_time_window = env(
        "MAILASSIST_OUTLOOK_WATCHER_TIME_WINDOW",
        global_watcher_time_window,
    )
    if default_provider == "outlook":
        watcher_unread_only = outlook_watcher_unread_only
        watcher_time_window = outlook_watcher_time_window
    else:
        watcher_unread_only = gmail_watcher_unread_only
        watcher_time_window = gmail_watcher_time_window

    draft_attribution = parse_bool(env("MAILASSIST_DRAFT_ATTRIBUTION"), default=False)
    draft_attribution_placement = parse_attribution_placement(
        env("MAILASSIST_DRAFT_ATTRIBUTION_PLACEMENT"),
        fallback_enabled=draft_attribution,
    )

    user_signature = env("MAILASSIST_USER_SIGNATURE").replace("\\n", "\n")
    user_signature_html = sanitize_html_fragment(
        env("MAILASSIST_USER_SIGNATURE_HTML").replace("\\n", "\n")
    )
    if user_signature_html and not user_signature.strip():
        user_signature = html_to_plain_text(user_signature_html)

    return Settings(
        root_dir=root_dir,
        data_dir=data_dir,
        legacy_data_dir=legacy_data_dir,
        drafts_dir=drafts_dir,
        logs_dir=logs_dir,
        bot_logs_dir=bot_logs_dir,
        mock_provider_drafts_dir=mock_provider_drafts_dir,
        ollama_url=env("MAILASSIST_OLLAMA_URL", "http://localhost:11434"),
        ollama_model=env("MAILASSIST_OLLAMA_MODEL", "llama3.1:8b"),
        user_signature=user_signature,
        user_signature_html=user_signature_html,
        user_tone=env("MAILASSIST_USER_TONE", "direct_concise"),
        bot_poll_seconds=parse_int(env("MAILASSIST_BOT_POLL_SECONDS"), 30),
        default_provider=default_provider,
        gmail_enabled=parse_bool(env("MAILASSIST_GMAIL_ENABLED"), default=True),
        outlook_enabled=parse_bool(env("MAILASSIST_OUTLOOK_ENABLED"), default=False),
        gmail_credentials_file=path_from_env(
            env("MAILASSIST_GMAIL_CREDENTIALS_FILE"),
            root_dir / "secrets" / "gmail-client-secret.json",
            root_dir=root_dir,
        ),
        gmail_token_file=path_from_env(
            env("MAILASSIST_GMAIL_TOKEN_FILE"),
            root_dir / "secrets" / "gmail-token.json",
            root_dir=root_dir,
        ),
        outlook_client_id=env("MAILASSIST_OUTLOOK_CLIENT_ID"),
        outlook_tenant_id=env("MAILASSIST_OUTLOOK_TENANT_ID"),
        outlook_redirect_uri=env(
            "MAILASSIST_OUTLOOK_REDIRECT_URI", "http://localhost:8765/outlook/callback"
        ),
        outlook_token_file=path_from_env(
            env("MAILASSIST_OUTLOOK_TOKEN_FILE"),
            root_dir / "secrets" / "outlook-token.json",
            root_dir=root_dir,
        ),
        gmail_watcher_unread_only=gmail_watcher_unread_only,
        gmail_watcher_time_window=gmail_watcher_time_window,
        outlook_watcher_unread_only=outlook_watcher_unread_only,
        outlook_watcher_time_window=outlook_watcher_time_window,
        watcher_unread_only=watcher_unread_only,
        watcher_time_window=watcher_time_window,
        draft_attribution=draft_attribution_placement != ATTRIBUTION_HIDE,
        draft_attribution_placement=draft_attribution_placement,
        mailassist_categories=parse_mailassist_categories(env("MAILASSIST_CATEGORIES")),
        elder_contacts_file=path_from_env(
            env("MAILASSIST_ELDERS_FILE"),
            data_dir / "elders.json",
            root_dir=root_dir,
        ),
        elder_contacts=load_elder_contacts(
            path_from_env(
                env("MAILASSIST_ELDERS_FILE"),
                data_dir / "elders.json",
                root_dir=root_dir,
            )
        ),
        appearance=parse_appearance(env("MAILASSIST_APPEARANCE", APPEARANCE_SYSTEM)),
    )
