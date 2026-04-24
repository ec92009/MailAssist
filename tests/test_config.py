from pathlib import Path

import pytest

from mailassist.config import parse_bool, read_env_file, write_env_file
from mailassist.gui.server import render_page


def test_parse_bool_handles_common_values() -> None:
    assert parse_bool("true") is True
    assert parse_bool("YES") is True
    assert parse_bool("0") is False
    assert parse_bool(None, default=True) is True


def test_read_and_write_env_file_round_trip(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    write_env_file(env_file, {"B": "2", "A": "1"})

    assert env_file.read_text(encoding="utf-8") == "A=1\nB=2\n"
    assert read_env_file(env_file) == {"A": "1", "B": "2"}


def test_render_page_shows_provider_sections_inside_providers_card(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_OLLAMA_URL": "http://localhost:11434",
            "MAILASSIST_OLLAMA_MODEL": "llama3.1:8b",
            "MAILASSIST_GMAIL_ENABLED": "false",
            "MAILASSIST_OUTLOOK_ENABLED": "true",
        },
    )

    page = render_page()

    assert "<h2>Providers</h2>" in page
    assert "<span>Gmail</span>" in page
    assert "<span>Outlook</span>" in page
    assert "Disabled" in page
    assert "Enabled" in page


def test_render_page_includes_ollama_prompt_tester(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    page = render_page(ollama_prompt="hello", ollama_result="world")

    assert "<h2>Ollama Check</h2>" in page
    assert "Send test prompt" in page
    assert "hello" in page
    assert "world" in page


def test_render_page_includes_draft_review_panel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    drafts_dir = tmp_path / "data" / "drafts"
    logs_dir = tmp_path / "data" / "logs"
    write_env_file(tmp_path / ".env", {})
    drafts_dir.mkdir(parents=True)
    logs_dir.mkdir(parents=True)
    (drafts_dir / "draft-1.json").write_text(
        """
{
  "draft_id": "draft-1",
  "thread_id": "thread-1",
  "provider": "gmail",
  "subject": "Re: Hello",
  "body": "Draft body",
  "model": "llama3.1:8b",
  "status": "pending_review",
  "created_at": "2026-04-24T10:00:00+00:00"
}
""".strip(),
        encoding="utf-8",
    )

    page = render_page()

    assert "<h2>Draft Review</h2>" in page
    assert "Green light" in page
    assert "Red light" in page
    assert "Draft body" in page
