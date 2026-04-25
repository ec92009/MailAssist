import os
import json

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from mailassist.gui.desktop import MailAssistDesktopWindow


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _button_metrics(window: MailAssistDesktopWindow) -> tuple[str, int, int, int, int, int]:
    app = _app()
    app.processEvents()
    button = window.settings_next_button if window.settings_next_button.isVisible() else window.settings_save_button
    position = button.mapTo(window, button.rect().topLeft())
    geometry = window.geometry()
    return (
        button.text(),
        position.x(),
        position.y(),
        geometry.width(),
        geometry.height(),
        window.settings_stack.geometry().height(),
    )


def test_settings_wizard_navigation_stays_stable() -> None:
    app = _app()
    window = MailAssistDesktopWindow()
    window.resize(1120, 680)
    window.settings_open = True
    window.setup_finished = False
    window._refresh_setup_visibility()
    window.show()
    app.processEvents()

    records = []
    for index in range(window.settings_stack.count()):
        window._show_settings_step(index)
        records.append(_button_metrics(window))

    window._show_settings_step(1)
    window._set_ollama_result_text(
        "Prompt: Reply with one short sentence confirming MailAssist can use this model.\n\n"
        "Response: MailAssist can use this model."
    )
    records.append(_button_metrics(window))

    window._show_settings_step(3)
    window.gmail_signature_status.setText(
        "Imported Gmail signature from example@example.com. You can edit it before continuing."
    )
    window._sync_settings_stack_height()
    records.append(_button_metrics(window))

    next_records = [record for record in records if record[0] == "Next"]
    assert {record[1] for record in next_records} == {next_records[0][1]}
    assert {record[2] for record in next_records} == {next_records[0][2]}
    assert {record[3] for record in records} == {records[0][3]}
    assert {record[4] for record in records} == {records[0][4]}
    assert {record[5] for record in records} == {records[0][5]}

    window.close()


def test_bot_log_formatter_shows_summary_and_timeline() -> None:
    window = MailAssistDesktopWindow()
    raw_text = "\n".join(
        json.dumps(event)
        for event in (
            {
                "type": "started",
                "action": "watch-once",
                "timestamp": "2026-04-25T19:20:30+00:00",
                "arguments": {
                    "provider": "gmail",
                    "selected_model": "gemma4:31b",
                },
            },
            {
                "type": "draft_created",
                "action": "watch-once",
                "timestamp": "2026-04-25T19:20:56+00:00",
                "subject": "Action needed: approve vendor access",
                "classification": "urgent",
                "provider_draft_id": "draft-123",
            },
            {
                "type": "completed",
                "action": "watch-once",
                "timestamp": "2026-04-25T19:20:56+00:00",
                "provider": "gmail",
                "draft_count": 1,
                "skipped_count": 0,
                "already_handled_count": 0,
            },
        )
    )

    formatted = window._format_bot_log_for_humans(window.settings.bot_logs_dir / "sample.jsonl", raw_text)

    assert "Summary" in formatted
    assert "Timeline" in formatted
    assert "Provider: Gmail" in formatted
    assert "Model: gemma4:31b" in formatted
    assert "Drafts created: 1" in formatted
    assert 'Created draft for "Action needed: approve vendor access". Classification: Urgent.' in formatted
    assert '"type": "draft_created"' not in formatted

    window.close()
