from pathlib import Path

from mailassist.config import load_settings, write_env_file
from mailassist.providers.factory import get_provider_for_settings
from mailassist.providers.mock import MockProvider
from mailassist.providers.outlook import OutlookProvider


def test_mock_provider_readiness_is_ready(tmp_path: Path) -> None:
    provider = MockProvider(tmp_path / "drafts", account_email="me@example.com")

    readiness = provider.readiness_check()

    assert readiness.ready is True
    assert readiness.provider == "mock"
    assert readiness.account_email == "me@example.com"
    assert readiness.can_authenticate is True
    assert readiness.can_read is True
    assert readiness.can_create_drafts is True


def test_outlook_provider_readiness_reports_missing_client_id() -> None:
    provider = OutlookProvider()

    readiness = provider.readiness_check()

    assert readiness.ready is False
    assert readiness.provider == "outlook"
    assert readiness.status == "not_configured"
    assert readiness.can_authenticate is False
    assert readiness.can_read is False
    assert readiness.can_create_drafts is False
    assert readiness.requires_admin_consent is False
    assert "client id" in readiness.message.lower()


def test_outlook_provider_readiness_names_graph_blocker() -> None:
    provider = OutlookProvider(
        client_id="client-123",
        tenant_id="tenant-456",
        redirect_uri="http://localhost:8765/outlook/callback",
    )

    readiness = provider.readiness_check()

    assert readiness.ready is False
    assert readiness.status == "blocked"
    assert readiness.requires_admin_consent is True
    assert readiness.details["client_id"] == "client-123"
    assert readiness.details["tenant_id"] == "tenant-456"
    assert "Graph" in readiness.message


def test_factory_passes_outlook_settings_to_provider(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_OUTLOOK_ENABLED": "true",
            "MAILASSIST_OUTLOOK_CLIENT_ID": "client-123",
            "MAILASSIST_OUTLOOK_TENANT_ID": "tenant-456",
            "MAILASSIST_OUTLOOK_REDIRECT_URI": "http://localhost:9999/callback",
        },
    )

    provider = get_provider_for_settings(load_settings(), "outlook")

    assert isinstance(provider, OutlookProvider)
    readiness = provider.readiness_check()
    assert readiness.status == "auth_required"
    assert readiness.details["client_id"] == "client-123"
    assert readiness.details["tenant_id"] == "tenant-456"
    assert readiness.details["redirect_uri"] == "http://localhost:9999/callback"
    assert readiness.details["token_file"].endswith("secrets/outlook-token.json")
