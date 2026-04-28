import os
import json

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

from mailassist.config import read_env_file, write_env_file
from mailassist.gui.desktop import MailAssistDesktopWindow
from mailassist.system_resources import memory_recommendation_message, recommended_model_names


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _button_metrics(window: MailAssistDesktopWindow) -> tuple[str, int, int, int, int, int]:
    app = _app()
    app.processEvents()
    button = window.settings_next_button if window.settings_next_button.isVisible() else window.settings_done_button
    container = window.settings_dialog or window
    position = button.mapTo(container, button.rect().topLeft())
    geometry = container.geometry()
    return (
        button.text(),
        position.x(),
        position.y(),
        geometry.width(),
        geometry.height(),
        window.settings_stack.geometry().height(),
    )


def test_settings_dialog_navigation_stays_stable() -> None:
    app = _app()
    window = MailAssistDesktopWindow()
    window.settings_dialog.resize(1120, 680)
    window.setup_finished = False
    window.open_settings_wizard()
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
    records.append(_button_metrics(window))

    next_records = [record for record in records if record[0] == "Next"]
    assert {record[1] for record in next_records} == {next_records[0][1]}
    assert {record[2] for record in next_records} == {next_records[0][2]}
    assert {record[3] for record in records} == {records[0][3]}
    assert {record[4] for record in records} == {records[0][4]}
    assert {record[5] for record in records} == {records[0][5]}

    window.settings_dialog.close()
    window.close()


def test_settings_dialog_navigation_sits_near_bottom_in_tall_window() -> None:
    app = _app()
    window = MailAssistDesktopWindow()
    window.settings_dialog.resize(1120, 860)
    window.setup_finished = False
    window.open_settings_wizard()
    app.processEvents()

    window._show_settings_step(0)
    text, _x, y, _width, height, scroll_height = _button_metrics(window)
    assert text == "Next"
    assert height - y < 80
    assert scroll_height > 560

    window.settings_dialog.close()
    window.close()


def test_review_summary_expands_to_available_space_in_tall_window() -> None:
    app = _app()
    window = MailAssistDesktopWindow()
    window.settings_dialog.resize(1120, 860)
    window.setup_finished = False
    window.open_settings_wizard()
    app.processEvents()

    window._show_settings_step(window.settings_stack.count() - 1)
    app.processEvents()

    text, _x, button_y, _width, _height, scroll_height = _button_metrics(window)
    summary_bottom = window.settings_summary.mapTo(
        window.settings_dialog,
        window.settings_summary.rect().bottomLeft(),
    ).y()

    assert text == "Done"
    assert window.settings_summary.height() > 520
    assert scroll_height > 560
    assert button_y - summary_bottom < 100

    window.settings_dialog.close()
    window.close()


def test_bot_control_is_main_page_when_setup_is_incomplete() -> None:
    app = _app()
    window = MailAssistDesktopWindow()
    window.setup_finished = False
    window._refresh_setup_visibility()
    window.show()
    app.processEvents()

    assert window.control_group.isVisible()
    assert window.activity_group.isVisible()
    assert window.settings_button.isVisible()

    window.close()


def test_recent_activity_expands_on_tall_main_window() -> None:
    app = _app()
    window = MailAssistDesktopWindow()
    window.resize(1120, 860)
    window.show()
    app.processEvents()

    activity_bottom = window.activity_group.mapTo(
        window,
        window.activity_group.rect().bottomLeft(),
    ).y()

    assert window.recent_activity.height() > 300
    assert window.height() - activity_bottom < 40

    window.close()


def test_memory_recommendation_prefers_models_that_fit_available_ram() -> None:
    model_details = [
        {"name": "gemma3:4b", "size": 3_000_000_000},
        {"name": "gemma4:31b", "size": 22_000_000_000},
    ]

    recommended, oversized = recommended_model_names(model_details, 8_000_000_000)
    message = memory_recommendation_message(model_details, 8_000_000_000, 16_000_000_000)

    assert recommended == ["gemma3:4b"]
    assert oversized == ["gemma4:31b"]
    assert "8.0 GB available of 16.0 GB RAM" in message
    assert "Recommended installed model(s): gemma3:4b." in message


def test_memory_recommendation_mentions_when_no_model_is_small_enough() -> None:
    model_details = [
        {"name": "gemma4:31b", "size": 22_000_000_000},
        {"name": "qwen3:32b", "size": 20_000_000_000},
    ]

    recommended, oversized = recommended_model_names(model_details, 8_000_000_000)
    message = memory_recommendation_message(model_details, 8_000_000_000, 16_000_000_000)

    assert recommended == []
    assert oversized == ["gemma4:31b", "qwen3:32b"]
    assert "None of the installed models look small enough" in message


def test_memory_recommendation_counts_loaded_model_memory_as_available() -> None:
    model_details = [
        {"name": "gemma3:4b", "size": 3_000_000_000},
        {"name": "gemma4:31b", "size": 19_900_000_000},
    ]
    loaded_model_details = [{"name": "gemma4:31b", "size": 19_900_000_000}]

    recommended, oversized = recommended_model_names(
        model_details,
        1_500_000_000,
        loaded_model_details,
    )
    message = memory_recommendation_message(
        model_details,
        1_500_000_000,
        34_400_000_000,
        loaded_model_details,
    )

    assert "gemma4:31b" in recommended
    assert "gemma4:31b" not in oversized
    assert "1.5 GB available of 34.4 GB RAM" in message
    assert "19.9 GB is already used by loaded Ollama model(s)" in message
    assert "effective model budget is about 21.4 GB" in message


def test_model_picker_recalculates_memory_when_selection_changes(monkeypatch) -> None:
    app = _app()
    snapshots = iter(
        [
            (8_000_000_000, 16_000_000_000),
            (28_000_000_000, 32_000_000_000),
            (28_000_000_000, 32_000_000_000),
        ]
    )

    monkeypatch.setattr(
        MailAssistDesktopWindow,
        "_list_available_model_state",
        lambda self: (
            [
                {"name": "gemma3:4b", "size": 3_000_000_000},
                {"name": "gemma4:31b", "size": 19_900_000_000},
            ],
            [],
            "",
        ),
    )
    monkeypatch.setattr("mailassist.gui.desktop.system_memory_snapshot", lambda: next(snapshots))
    monkeypatch.setattr("mailassist.gui.desktop.OllamaClient.list_loaded_model_details", lambda self: [])

    window = MailAssistDesktopWindow()
    app.processEvents()
    window.ollama_model_picker.setCurrentIndex(window.ollama_model_picker.findData("gemma3:4b"))
    window.ollama_model_picker.setCurrentIndex(window.ollama_model_picker.findData("gemma4:31b"))

    assert "28.0 GB available of 32.0 GB RAM" in window.ollama_model_hint.text()
    assert "This model may be too large" not in window.ollama_model_hint.text()

    window.close()


def test_model_refresh_preserves_current_picker_selection(monkeypatch) -> None:
    app = _app()
    monkeypatch.setattr(
        MailAssistDesktopWindow,
        "_list_available_model_state",
        lambda self: (
            [
                {"name": "wizardcoder:33b", "size": 18_800_000_000},
                {"name": "gemma4:31b", "size": 19_900_000_000},
            ],
            [],
            "",
        ),
    )
    monkeypatch.setattr(
        "mailassist.gui.desktop.system_memory_snapshot",
        lambda: (28_000_000_000, 32_000_000_000),
    )

    window = MailAssistDesktopWindow()
    app.processEvents()
    window.ollama_model_picker.setCurrentIndex(window.ollama_model_picker.findData("gemma4:31b"))
    window.refresh_models()

    assert window.ollama_model_picker.currentData() == "gemma4:31b"

    window.close()


def test_watcher_filter_controls_persist_and_show_on_dashboard(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    write_env_file(
        tmp_path / ".env",
        {
            "MAILASSIST_WATCHER_UNREAD_ONLY": "false",
            "MAILASSIST_WATCHER_TIME_WINDOW": "all",
        },
    )
    monkeypatch.setattr(
        MailAssistDesktopWindow,
        "_list_available_model_state",
        lambda self: ([{"name": "gemma3:4b", "size": 3_000_000_000}], [], ""),
    )
    monkeypatch.setattr(
        "mailassist.gui.desktop.system_memory_snapshot",
        lambda: (8_000_000_000, 16_000_000_000),
    )
    app = _app()

    window = MailAssistDesktopWindow()
    app.processEvents()
    window.gmail_watcher_unread_only_checkbox.setChecked(True)
    window.gmail_watcher_time_window_combo.setCurrentIndex(window.gmail_watcher_time_window_combo.findData("7d"))
    window.outlook_enabled.setChecked(True)
    window.outlook_watcher_unread_only_checkbox.setChecked(False)
    window.outlook_watcher_time_window_combo.setCurrentIndex(
        window.outlook_watcher_time_window_combo.findData("30d")
    )
    window.attribution_placement_combo.setCurrentIndex(
        window.attribution_placement_combo.findData("above_signature")
    )
    window.mailassist_category_list.addItem("Travel")
    window.bot_poll_seconds_input.setValue(45)
    window.save_settings(announce=False)

    env_values = read_env_file(tmp_path / ".env")
    assert env_values["MAILASSIST_BOT_POLL_SECONDS"] == "45"
    assert env_values["MAILASSIST_WATCHER_UNREAD_ONLY"] == "true"
    assert env_values["MAILASSIST_WATCHER_TIME_WINDOW"] == "7d"
    assert env_values["MAILASSIST_GMAIL_WATCHER_UNREAD_ONLY"] == "true"
    assert env_values["MAILASSIST_GMAIL_WATCHER_TIME_WINDOW"] == "7d"
    assert env_values["MAILASSIST_OUTLOOK_WATCHER_UNREAD_ONLY"] == "false"
    assert env_values["MAILASSIST_OUTLOOK_WATCHER_TIME_WINDOW"] == "30d"
    assert env_values["MAILASSIST_DRAFT_ATTRIBUTION"] == "true"
    assert env_values["MAILASSIST_DRAFT_ATTRIBUTION_PLACEMENT"] == "above_signature"
    assert json.loads(env_values["MAILASSIST_CATEGORIES"])[0] == "Needs Reply"
    assert "Travel" in json.loads(env_values["MAILASSIST_CATEGORIES"])
    assert window.watcher_filter_status_label.text() == "unread only, last 7 days"
    assert "Watcher filter: unread only, last 7 days" in window.settings_summary.toPlainText()
    assert "Attribution: Above Signature" in window.settings_summary.toPlainText()
    assert "Draft prepared by MailAssist" in window.signature_attribution_preview.toPlainText()
    assert window.bot_poll_seconds_input.minimumHeight() >= window.ollama_url_input.sizeHint().height()

    window.close()
    for key in (
        "MAILASSIST_OLLAMA_URL",
        "MAILASSIST_OLLAMA_MODEL",
        "MAILASSIST_USER_SIGNATURE",
        "MAILASSIST_USER_TONE",
        "MAILASSIST_BOT_POLL_SECONDS",
        "MAILASSIST_DEFAULT_PROVIDER",
        "MAILASSIST_GMAIL_ENABLED",
        "MAILASSIST_OUTLOOK_ENABLED",
        "MAILASSIST_GMAIL_CREDENTIALS_FILE",
        "MAILASSIST_GMAIL_TOKEN_FILE",
        "MAILASSIST_WATCHER_UNREAD_ONLY",
        "MAILASSIST_WATCHER_TIME_WINDOW",
        "MAILASSIST_GMAIL_WATCHER_UNREAD_ONLY",
        "MAILASSIST_GMAIL_WATCHER_TIME_WINDOW",
        "MAILASSIST_OUTLOOK_WATCHER_UNREAD_ONLY",
        "MAILASSIST_OUTLOOK_WATCHER_TIME_WINDOW",
        "MAILASSIST_OUTLOOK_CLIENT_ID",
        "MAILASSIST_OUTLOOK_TENANT_ID",
        "MAILASSIST_OUTLOOK_REDIRECT_URI",
        "MAILASSIST_DRAFT_ATTRIBUTION",
        "MAILASSIST_DRAFT_ATTRIBUTION_PLACEMENT",
        "MAILASSIST_SETUP_COMPLETE",
    ):
        monkeypatch.delenv(key, raising=False)


def test_provider_page_keeps_at_least_one_provider_checked() -> None:
    app = _app()
    window = MailAssistDesktopWindow()
    app.processEvents()

    window.gmail_enabled.setChecked(False)
    app.processEvents()
    assert window.outlook_enabled.isChecked()

    window.outlook_enabled.setChecked(False)
    app.processEvents()
    assert window.gmail_enabled.isChecked()

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


def test_gmail_draft_test_requires_confirmation(monkeypatch) -> None:
    window = MailAssistDesktopWindow()
    called: list[tuple[str, str, str, bool, bool]] = []

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )
    monkeypatch.setattr(
        window,
        "run_bot_action",
        lambda action, *, thread_id="", prompt="", provider="", force=False, dry_run=False: called.append(
            (action, thread_id, provider, force, dry_run)
        ),
    )

    window.run_gmail_draft_test()

    assert called == []
    assert window.banner.text() == "Gmail draft dry run canceled."
    window.close()


def test_gmail_draft_test_runs_safe_dry_run_after_confirmation(monkeypatch) -> None:
    window = MailAssistDesktopWindow()
    called: list[tuple[str, str, str, bool, bool]] = []

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(
        window,
        "run_bot_action",
        lambda action, *, thread_id="", prompt="", provider="", force=False, dry_run=False: called.append(
            (action, thread_id, provider, force, dry_run)
        ),
    )

    window.run_gmail_draft_test()

    assert called == [("watch-once", "thread-008", "gmail", True, True)]
    window.close()


def test_outlook_draft_preview_requires_confirmation(monkeypatch) -> None:
    window = MailAssistDesktopWindow()
    called = []

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )
    monkeypatch.setattr(window, "save_settings", lambda *args, **kwargs: called.append(("save",)))
    monkeypatch.setattr(window, "run_bot_action", lambda *args, **kwargs: called.append(("run",)))

    window.run_outlook_draft_preview()

    assert called == []
    assert window.banner.text() == "Outlook draft preview canceled."
    window.close()


def test_outlook_draft_preview_runs_safe_dry_run_after_confirmation(monkeypatch) -> None:
    window = MailAssistDesktopWindow()
    called = []
    confirmation_messages = []

    def fake_question(_parent, title, message, *args, **kwargs):
        confirmation_messages.append((title, message))
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", fake_question)
    monkeypatch.setattr(window, "save_settings", lambda *args, **kwargs: called.append(("save", kwargs)))
    monkeypatch.setattr(
        window,
        "run_bot_action",
        lambda action, **kwargs: called.append((action, kwargs)),
    )

    window.run_outlook_draft_preview()

    assert called == [
        ("save", {"announce": False}),
        (
            "watch-once",
            {
                "provider": "outlook",
                "force": True,
                "dry_run": True,
            },
        ),
    ]
    assert confirmation_messages[0][0] == "Preview Outlook Draft"
    assert "without creating real Outlook drafts" in confirmation_messages[0][1]
    assert "Nothing will be sent" in confirmation_messages[0][1]
    window.close()


def test_controlled_gmail_draft_runs_after_confirmation(monkeypatch) -> None:
    window = MailAssistDesktopWindow()
    called: list[tuple[str, str, str, bool, bool]] = []

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(
        window,
        "run_bot_action",
        lambda action, *, thread_id="", prompt="", provider="", force=False, dry_run=False: called.append(
            (action, thread_id, provider, force, dry_run)
        ),
    )

    window.run_controlled_gmail_draft()

    assert called == [("gmail-controlled-draft", "thread-008", "gmail", False, False)]
    window.close()


def test_gmail_label_rescan_requires_confirmation(monkeypatch) -> None:
    window = MailAssistDesktopWindow()
    called = []

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )
    monkeypatch.setattr(window, "save_settings", lambda *args, **kwargs: called.append(("save",)))
    monkeypatch.setattr(window, "run_bot_action", lambda *args, **kwargs: called.append(("run",)))

    window.run_gmail_label_rescan()

    assert called == []
    assert window.banner.text() == "Gmail label rescan canceled."
    window.close()


def test_gmail_label_rescan_runs_with_limited_horizon(monkeypatch) -> None:
    window = MailAssistDesktopWindow()
    called = []
    confirmation_messages = []
    window.gmail_label_days_input.setValue(3)

    def fake_question(_parent, title, message, *args, **kwargs):
        confirmation_messages.append((title, message))
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(
        QMessageBox,
        "question",
        fake_question,
    )
    monkeypatch.setattr(window, "save_settings", lambda *args, **kwargs: called.append(("save", kwargs)))
    monkeypatch.setattr(
        window,
        "run_bot_action",
        lambda action, **kwargs: called.append((action, kwargs)),
    )

    window.run_gmail_label_rescan()

    assert called == [
        ("save", {"announce": False}),
        (
            "gmail-populate-labels",
            {
                "provider": "gmail",
                "days": 3,
                "limit": 500,
                "apply_labels": True,
            },
        ),
    ]
    assert confirmation_messages[0][0] == "Organize Gmail"
    assert "take a few minutes" in confirmation_messages[0][1]
    assert "keep working" in confirmation_messages[0][1]
    window.close()


def test_outlook_category_rescan_requires_confirmation(monkeypatch) -> None:
    window = MailAssistDesktopWindow()
    called = []

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )
    monkeypatch.setattr(window, "save_settings", lambda *args, **kwargs: called.append(("save",)))
    monkeypatch.setattr(window, "run_bot_action", lambda *args, **kwargs: called.append(("run",)))

    window.run_outlook_category_rescan()

    assert called == []
    assert window.banner.text() == "Outlook category rescan canceled."
    window.close()


def test_outlook_category_rescan_runs_with_day_horizon(monkeypatch) -> None:
    window = MailAssistDesktopWindow()
    called = []
    confirmation_messages = []
    window.outlook_category_days_input.setValue(12)

    def fake_question(_parent, title, message, *args, **kwargs):
        confirmation_messages.append((title, message))
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(
        QMessageBox,
        "question",
        fake_question,
    )
    monkeypatch.setattr(window, "save_settings", lambda *args, **kwargs: called.append(("save", kwargs)))
    monkeypatch.setattr(
        window,
        "run_bot_action",
        lambda action, **kwargs: called.append((action, kwargs)),
    )

    window.run_outlook_category_rescan()

    assert called == [
        ("save", {"announce": False}),
        (
            "outlook-populate-categories",
            {
                "provider": "outlook",
                "days": 12,
                "apply_categories": True,
            },
        ),
    ]
    assert confirmation_messages[0][0] == "Organize Outlook"
    assert "last 12 days" in confirmation_messages[0][1]
    assert "keep working" in confirmation_messages[0][1]
    window.close()


def test_bot_control_actions_use_user_centered_labels_and_compact_days_input() -> None:
    window = MailAssistDesktopWindow()

    assert window.demo_inbox_button.text() == "Try Demo Inbox"
    assert window.gmail_draft_preview_button.text() == "Preview Gmail Draft"
    assert window.outlook_draft_preview_button.text() == "Preview Outlook Draft"
    assert window.controlled_gmail_draft_button.text() == "Create Test Draft"
    assert window.gmail_label_rescan_button.text() == "Organize Gmail"
    assert window.outlook_category_rescan_button.text() == "Organize Outlook"
    assert window.start_watch_loop_button.text() == "Start Auto-Check"
    assert window.gmail_label_days_input.maximumWidth() <= 104
    assert window.outlook_category_days_input.maximumWidth() <= 104
    assert window.gmail_label_days_input.height() == window.gmail_label_rescan_button.height()
    assert window.outlook_category_days_input.height() == window.outlook_category_rescan_button.height()
    window.close()


def test_shared_category_panel_names_gmail_labels_and_outlook_categories() -> None:
    window = MailAssistDesktopWindow()

    labels = [child.text() for child in window.findChildren(QLabel)]

    assert any("Gmail labels and/or Outlook categories" in text for text in labels)
    window.close()
