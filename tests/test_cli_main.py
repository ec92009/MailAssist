from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from mailassist.cli import main as cli_main
from mailassist.config import write_env_file
from mailassist.models import EmailMessage, EmailThread
from mailassist.providers.base import ProviderReadiness
from mailassist.providers.outlook import OutlookGraphAuthError


class FakeOutlookProvider:
    def __init__(self, *args, **kwargs) -> None:
        self.authenticated = False

    def authenticate(self) -> str:
        self.authenticated = True
        return "ok"

    def get_account_email(self) -> str:
        return "magalidomingue@goldenyearstaxstrategy.com"

    def readiness_check(self) -> ProviderReadiness:
        return ProviderReadiness(
            provider="outlook",
            status="ready",
            message="Outlook Graph provider is ready.",
            account_email="magalidomingue@goldenyearstaxstrategy.com",
            can_authenticate=True,
            can_read=True,
            can_create_drafts=True,
            requires_admin_consent=False,
            details={},
        )

    def list_candidate_threads(self) -> list[EmailThread]:
        return [
            EmailThread(
                thread_id="thread-1",
                subject="Client follow-up",
                participants=["client@example.com"],
                unread=True,
                messages=[
                    EmailMessage(
                        message_id="msg-1",
                        sender="client@example.com",
                        to=["magalidomingue@goldenyearstaxstrategy.com"],
                        sent_at="2026-04-28T18:00:00Z",
                        text="Private body should not print.",
                    )
                ],
            )
        ]


class AdminBlockedOutlookProvider(FakeOutlookProvider):
    def authenticate(self) -> str:
        raise OutlookGraphAuthError(
            "Need admin approval.",
            requires_admin_consent=True,
        )


class FakeOllamaClient:
    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url
        self.model = model

    def list_models(self) -> list[str]:
        return ["qwen3:8b"]

    def compose_reply(self, prompt: str) -> str:
        assert "MailAssist model check passed" in prompt
        return "MailAssist model check passed."


class MissingModelOllamaClient(FakeOllamaClient):
    def list_models(self) -> list[str]:
        return ["llama3.1:8b"]


class FakeReadyProvider:
    def __init__(self) -> None:
        self.authenticated = False

    def authenticate(self) -> str:
        self.authenticated = True
        return "ok"

    def readiness_check(self) -> ProviderReadiness:
        return ProviderReadiness(
            provider="outlook",
            status="ready",
            message="Provider is ready.",
            account_email="magalidomingue@goldenyearstaxstrategy.com",
            can_authenticate=True,
            can_read=True,
            can_create_drafts=True,
            requires_admin_consent=False,
        )


def test_outlook_setup_check_is_read_only_and_prints_mailbox_summary(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_OUTLOOK_ENABLED": "true",
            "MAILASSIST_OUTLOOK_CLIENT_ID": "client-123",
            "MAILASSIST_OUTLOOK_TENANT_ID": "organizations",
        },
    )
    monkeypatch.setattr(cli_main, "OutlookProvider", FakeOutlookProvider)

    exit_code = cli_main.command_outlook_setup_check(
        argparse.Namespace(
            expected_email="MagaliDomingue@GoldenYearsTaxStrategy.com",
            limit=5,
        )
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "This is read-only" in output
    assert "MailAssist does not request Mail.Send" in output
    assert "Mailbox: magalidomingue@goldenyearstaxstrategy.com" in output
    assert "Client follow-up" in output
    assert "Private body should not print" not in output
    assert "No drafts were created and no email was sent" in output


def test_outlook_setup_check_stops_on_wrong_account(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_OUTLOOK_ENABLED": "true",
            "MAILASSIST_OUTLOOK_CLIENT_ID": "client-123",
        },
    )
    monkeypatch.setattr(cli_main, "OutlookProvider", FakeOutlookProvider)

    exit_code = cli_main.command_outlook_setup_check(
        argparse.Namespace(expected_email="other@example.com", limit=5)
    )

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "does not match the expected account" in output
    assert "other@example.com" in output
    assert "magalidomingue@goldenyearstaxstrategy.com" in output


def test_outlook_setup_check_reports_admin_consent_blocker(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_OUTLOOK_ENABLED": "true",
            "MAILASSIST_OUTLOOK_CLIENT_ID": "client-123",
        },
    )
    monkeypatch.setattr(cli_main, "OutlookProvider", AdminBlockedOutlookProvider)

    exit_code = cli_main.command_outlook_setup_check(
        argparse.Namespace(expected_email="", limit=5)
    )

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Outlook authorization failed" in output
    assert "tenant admin approval is required" in output


def test_ollama_setup_check_uses_mailassist_client_and_reports_success(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_OLLAMA_MODEL": "qwen3:8b",
            "MAILASSIST_OLLAMA_URL": "http://localhost:11434",
        },
    )
    monkeypatch.setattr(cli_main, "OllamaClient", FakeOllamaClient)

    exit_code = cli_main.command_ollama_setup_check(
        argparse.Namespace(model="", base_url="", prompt="")
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "think:false" in output
    assert "Model: qwen3:8b" in output
    assert "Response: MailAssist model check passed." in output
    assert "Ollama setup check completed" in output


def test_ollama_setup_check_stops_when_model_is_not_installed(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_OLLAMA_MODEL": "qwen3:8b",
        },
    )
    monkeypatch.setattr(cli_main, "OllamaClient", MissingModelOllamaClient)

    exit_code = cli_main.command_ollama_setup_check(
        argparse.Namespace(model="", base_url="", prompt="")
    )

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Configured model is not installed: qwen3:8b" in output
    assert "ollama pull qwen3:8b" in output


def test_parser_prints_machine_readable_version(capsys) -> None:
    parser = cli_main.build_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--version"])

    output = capsys.readouterr().out
    assert exc.value.code == 0
    assert output.startswith("mailassist ")
    assert cli_main.__version__ in output


def test_doctor_runs_model_and_provider_checks_without_mail_writes(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_DEFAULT_PROVIDER": "outlook",
            "MAILASSIST_OLLAMA_MODEL": "qwen3:8b",
        },
    )
    provider = FakeReadyProvider()
    monkeypatch.setattr(cli_main, "OllamaClient", FakeOllamaClient)
    monkeypatch.setattr(
        cli_main,
        "get_provider_for_settings",
        lambda settings, provider_name: provider,
    )

    exit_code = cli_main.command_doctor(
        argparse.Namespace(
            provider="",
            authorize=False,
            expected_email="MagaliDomingue@GoldenYearsTaxStrategy.com",
            model="",
            base_url="",
            skip_model=False,
        )
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "MailAssist doctor" in output
    assert "This report does not create drafts or send email" in output
    assert "Ollama setup check completed" in output
    assert "Provider: outlook" in output
    assert "Provider is ready" in output
    assert "Doctor completed. MailAssist readiness checks passed" in output
    assert provider.authenticated is False


def test_doctor_reports_expected_account_mismatch(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_DEFAULT_PROVIDER": "outlook",
        },
    )
    monkeypatch.setattr(
        cli_main,
        "get_provider_for_settings",
        lambda settings, provider_name: FakeReadyProvider(),
    )

    exit_code = cli_main.command_doctor(
        argparse.Namespace(
            provider="",
            authorize=False,
            expected_email="other@example.com",
            model="",
            base_url="",
            skip_model=True,
        )
    )

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Ollama: skipped" in output
    assert "does not match the expected account" in output
    assert "Doctor completed with issues" in output
