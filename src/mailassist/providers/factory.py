from __future__ import annotations

from mailassist.config import Settings
from mailassist.providers.base import DraftProvider
from mailassist.providers.gmail import GmailProvider
from mailassist.providers.outlook import OutlookProvider


def get_provider_for_settings(settings: Settings, provider_name: str) -> DraftProvider:
    if provider_name == "gmail":
        if not settings.gmail_enabled:
            raise RuntimeError("Gmail is disabled in the current MailAssist settings.")
        return GmailProvider(settings.gmail_credentials_file, settings.gmail_token_file)

    if provider_name == "outlook":
        if not settings.outlook_enabled:
            raise RuntimeError("Outlook is disabled in the current MailAssist settings.")
        return OutlookProvider()

    raise RuntimeError(f"Unknown provider: {provider_name}")
