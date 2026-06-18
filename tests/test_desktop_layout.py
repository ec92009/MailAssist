import os
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QTextOption
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
)

from mailassist.config import read_env_file, write_env_file
from mailassist.gui import bot_process as bot_process_module
from mailassist.gui import desktop as desktop_module
from mailassist.gui.desktop import MailAssistDesktopWindow, _app_icon_path
from mailassist.system_resources import memory_recommendation_message, recommended_model_names


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_settings_pages_are_embedded_without_footer_navigation() -> None:
    app = _app()
    window = MailAssistDesktopWindow()
    window.setup_finished = False
    window.open_settings_wizard()
    app.processEvents()

    assert window.main_stack.currentWidget() is window.settings_wizard
    assert window.settings_step_index == 5
    assert window.nav_buttons["Review"].isChecked()
    assert not window.settings_back_button.isVisible()
    assert not window.settings_next_button.isVisible()
    assert not window.settings_done_button.isVisible()
    assert not window.settings_advanced_button.isVisible()

    window.nav_buttons["Dashboard"].click()
    app.processEvents()

    assert window.main_stack.currentWidget() is window.dashboard_page
    assert window.nav_buttons["Dashboard"].isChecked()
    window.close()


def test_windows_icon_prefers_ico_then_png_then_svg(tmp_path) -> None:
    icon_dir = tmp_path / "assets" / "brand"
    icon_dir.mkdir(parents=True)
    svg = icon_dir / "mailassist_icon.svg"
    png = icon_dir / "mailassist_icon_256.png"
    ico = icon_dir / "mailassist_icon.ico"

    svg.write_text("<svg />", encoding="utf-8")
    assert _app_icon_path(tmp_path, platform="win32") == svg

    png.write_bytes(b"png")
    assert _app_icon_path(tmp_path, platform="win32") == png

    ico.write_bytes(b"ico")
    assert _app_icon_path(tmp_path, platform="win32") == ico


def test_embedded_settings_pages_are_compact() -> None:
    window = MailAssistDesktopWindow()

    assert window.settings_stack.minimumHeight() <= 320
    assert window.settings_step_help.minimumHeight() <= 34

    window.close()


def test_embedded_review_summary_expands_in_main_window() -> None:
    app = _app()
    window = MailAssistDesktopWindow()
    window.resize(1120, 860)
    window.nav_buttons["Review"].click()
    app.processEvents()

    assert window.main_stack.currentWidget() is window.settings_wizard
    assert window.settings_summary.height() > 420
    assert window.settings_overview.height() > 420

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
    assert "Review" in window.nav_buttons
    assert not hasattr(window, "settings_button")
    assert not hasattr(window, "logs_button")

    window.close()


def test_embedded_settings_disable_main_bot_starters_until_dashboard_returns() -> None:
    app = _app()
    window = MailAssistDesktopWindow()
    window.open_settings_wizard()
    app.processEvents()

    assert window.gmail_draft_preview_button.isEnabled() is False
    assert window.outlook_draft_preview_button.isEnabled() is False
    assert window.gmail_label_rescan_button.isEnabled() is False
    assert window.outlook_category_rescan_button.isEnabled() is False
    assert window.start_watch_loop_button.isEnabled() is False
    assert window.gmail_label_days_input.isEnabled() is False
    assert window.outlook_category_days_input.isEnabled() is False
    assert window.test_ollama_button.isEnabled() is True

    window.nav_buttons["Dashboard"].click()
    app.processEvents()

    assert window.gmail_draft_preview_button.isEnabled() is True
    assert window.outlook_draft_preview_button.isEnabled() is True
    assert window.gmail_label_rescan_button.isEnabled() is True
    assert window.outlook_category_rescan_button.isEnabled() is True
    assert window.start_watch_loop_button.isEnabled() is True
    assert window.gmail_label_days_input.isEnabled() is True
    assert window.outlook_category_days_input.isEnabled() is True

    window.close()


def test_appearance_toggle_defaults_to_system_and_persists_override(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    app = _app()
    window = MailAssistDesktopWindow()
    app.processEvents()

    assert window.appearance == "system"
    assert window.system_toggle_button.isChecked()

    window.set_appearance("night")
    app.processEvents()

    assert window.night_toggle_button.isChecked()
    assert read_env_file(tmp_path / ".env")["MAILASSIST_APPEARANCE"] == "night"

    window.set_appearance("system")
    app.processEvents()

    assert window.system_toggle_button.isChecked()
    assert read_env_file(tmp_path / ".env")["MAILASSIST_APPEARANCE"] == "system"
    window.close()


def test_appearance_toggle_is_single_three_way_switch() -> None:
    window = MailAssistDesktopWindow()

    assert window.appearance_toggle.objectName() == "appearanceToggle"
    assert window.appearance_button_group.exclusive() is True
    assert window.appearance_toggle.layout().spacing() == 0
    assert window.system_toggle_button.parent() is window.appearance_toggle
    assert window.day_toggle_button.parent() is window.appearance_toggle
    assert window.night_toggle_button.parent() is window.appearance_toggle
    assert "border-left" not in window.system_toggle_button.styleSheet()
    assert "border-left" not in window.day_toggle_button.styleSheet()
    assert "border-left" not in window.night_toggle_button.styleSheet()
    assert "border-radius: 8px" in window.system_toggle_button.styleSheet()
    assert "border-radius: 8px" in window.day_toggle_button.styleSheet()
    assert "border-radius: 8px" in window.night_toggle_button.styleSheet()

    window.close()


def test_night_mode_controls_own_popup_and_toolbar_contrast() -> None:
    app = _app()
    window = MailAssistDesktopWindow()
    window.set_appearance("night", persist=False)
    app.processEvents()

    for combo in (window.tone_combo, window.attribution_placement_combo, window.bot_log_selector):
        assert combo.view().objectName() == "comboPopup"
        assert "#1c2530" in combo.view().styleSheet()
        assert "#eef3f7" in combo.view().styleSheet()
    assert "#34a6a5" in combo.view().styleSheet()

    assert window.signature_toolbar_buttons
    assert all("#eef3f7" in button.styleSheet() for button in window.signature_toolbar_buttons)
    assert "QDialog" in window.styleSheet()
    assert "QCheckBox" in window.styleSheet()

    window.close()


def test_confirmation_dialog_uses_themed_contrast_without_native_question_icon() -> None:
    app = _app()
    window = MailAssistDesktopWindow()
    window.set_appearance("night", persist=False)
    observed: dict[str, object] = {}

    def inspect_and_close() -> None:
        dialog = QApplication.activeModalWidget()
        assert dialog is not None
        observed["object_name"] = dialog.objectName()
        observed["frameless"] = bool(dialog.windowFlags() & Qt.WindowType.FramelessWindowHint)
        observed["style"] = dialog.styleSheet()
        observed["labels"] = [label.text() for label in dialog.findChildren(QLabel)]
        for button in dialog.findChildren(QPushButton):
            if button.text() == "No":
                button.click()
                return

    QTimer.singleShot(0, inspect_and_close)
    result = window._confirm_action("Organize Outlook", "High-contrast confirmation copy.")

    assert result == QMessageBox.StandardButton.No
    assert observed["object_name"] == "confirmDialog"
    assert observed["frameless"] is True
    assert "#26313f" in str(observed["style"])
    assert "#eef3f7" in str(observed["style"])
    assert "Organize Outlook" in observed["labels"]
    assert "High-contrast confirmation copy." in observed["labels"]
    assert not any(label.strip() == "?" for label in observed["labels"])
    window.close()


def test_settings_pages_leave_room_for_wrapped_status_text() -> None:
    window = MailAssistDesktopWindow()

    assert window.ollama_model_group.minimumHeight() >= 400
    assert window.ollama_result_group.minimumHeight() >= window.ollama_model_group.minimumHeight()
    assert window.ollama_model_hint.minimumHeight() >= 180
    assert window.signature_input.minimumHeight() >= 260
    assert window.signature_attribution_preview.minimumHeight() >= 260
    assert window.writing_style_group.minimumHeight() == window.relationship_guidance_group.minimumHeight()
    assert window.watcher_note.minimumHeight() >= 70

    window.close()


def test_side_nav_items_open_matching_surfaces() -> None:
    app = _app()
    window = MailAssistDesktopWindow()

    window.nav_buttons["Providers"].click()
    app.processEvents()

    assert window.main_stack.currentWidget() is window.settings_wizard
    assert window.settings_step_index == 0
    assert window.nav_buttons["Providers"].isChecked()

    window.nav_buttons["Model"].click()
    app.processEvents()
    assert window.settings_step_index == 1
    assert window.nav_buttons["Model"].isChecked()

    window.nav_buttons["Tone"].click()
    app.processEvents()
    assert window.settings_step_index == 2
    assert window.nav_buttons["Tone"].isChecked()

    window.nav_buttons["Signature"].click()
    app.processEvents()
    assert window.settings_step_index == 3
    assert window.nav_buttons["Signature"].isChecked()

    window.nav_buttons["Advanced"].click()
    app.processEvents()
    assert window.settings_step_index == 4
    assert window.nav_buttons["Advanced"].isChecked()

    window.nav_buttons["Review"].click()
    app.processEvents()
    assert window.settings_step_index == 5
    assert window.nav_buttons["Review"].isChecked()

    window.nav_buttons["Activity"].click()
    app.processEvents()
    assert window.main_stack.currentWidget() is window.activity_page
    assert window.nav_buttons["Activity"].isChecked()
    assert window.bot_logs_dialog is None

    window.nav_buttons["Dashboard"].click()
    app.processEvents()
    assert window.main_stack.currentWidget() is window.dashboard_page
    assert window.nav_buttons["Dashboard"].isChecked()

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
    window.elder_contacts_list.addItem("agnes@example.com | Family elder")
    window.mailassist_category_list.addItem("Travel")
    window.bot_poll_seconds_input.setValue(45)
    window.save_settings(announce=False)

    env_values = read_env_file(tmp_path / ".env")
    assert env_values["MAILASSIST_APPEARANCE"] == "system"
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
    assert json.loads((tmp_path / "data" / "elders.json").read_text(encoding="utf-8")) == [
        {"email": "agnes@example.com", "comment": "Family elder"}
    ]
    assert window.watcher_filter_status_label.text() == "unread only, last 7 days"
    assert "Watcher filter: unread only, last 7 days" in window.settings_overview.toPlainText()
    assert "Elders: 1" in window.settings_overview.toPlainText()
    assert "Attribution: Above Signature" in window.settings_overview.toPlainText()
    assert "Draft prepared by MailAssist" in window.signature_attribution_preview.toPlainText()
    assert window.bot_poll_seconds_input.minimumHeight() >= window.ollama_url_input.sizeHint().height()

    window.close()
    for key in (
        "MAILASSIST_OLLAMA_URL",
        "MAILASSIST_OLLAMA_MODEL",
        "MAILASSIST_USER_SIGNATURE",
        "MAILASSIST_USER_TONE",
        "MAILASSIST_APPEARANCE",
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
        "MAILASSIST_ELDERS_FILE",
        "MAILASSIST_SETUP_COMPLETE",
    ):
        monkeypatch.delenv(key, raising=False)


def test_outlook_provider_status_reflects_saved_token(monkeypatch, tmp_path) -> None:
    token_file = tmp_path / "secrets" / "outlook-token.json"
    token_file.parent.mkdir(parents=True)
    token_file.write_text("{}", encoding="utf-8")

    class Settings:
        default_provider = "outlook"
        outlook_token_file = token_file
        outlook_client_id = "11111111-2222-3333-4444-555555555555"

    class Window:
        settings = Settings()
        provider_health = ("", "warn")

    window = Window()
    MailAssistDesktopWindow._refresh_provider_health(window)

    assert window.provider_health == ("outlook — connected", "ok")


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


def test_elder_editor_adds_updates_and_removes_contacts(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
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

    assert window._upsert_elder_contact("Agnes <agnes@example.com>", "Family elder") is True
    assert window.elder_contacts_list.currentItem().text() == "agnes@example.com | Family elder"
    assert window._upsert_elder_contact("agnes@example.com", "Use vous") is True
    assert window.elder_contacts_list.count() == 1
    assert window.elder_contacts_list.currentItem().text() == "agnes@example.com | Use vous"
    monkeypatch.setattr(window, "_confirm_action", lambda *args, **kwargs: QMessageBox.StandardButton.No)
    window._remove_selected_elder_contact()
    assert window.elder_contacts_list.count() == 1
    assert not window.elder_contacts_undo_button.isEnabled()
    monkeypatch.setattr(window, "_confirm_action", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    window._remove_selected_elder_contact()
    assert window.elder_contacts_list.count() == 0
    assert window.elder_contacts_undo_button.isEnabled()
    window._undo_elder_contact_removal()
    assert window.elder_contacts_list.count() == 1
    assert window.elder_contacts_list.currentItem().text() == "agnes@example.com | Use vous"
    assert not window.elder_contacts_undo_button.isEnabled()

    window.close()


def test_category_editor_confirms_remove_and_can_undo(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
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
    window.mailassist_category_list.addItem("Travel")
    travel_index = window.mailassist_category_list.count() - 1
    window.mailassist_category_list.setCurrentRow(travel_index)

    monkeypatch.setattr(window, "_confirm_action", lambda *args, **kwargs: QMessageBox.StandardButton.No)
    window._remove_selected_mailassist_category()
    assert "Travel" in window._mailassist_category_values()
    assert not window.mailassist_category_undo_button.isEnabled()

    monkeypatch.setattr(window, "_confirm_action", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    window._remove_selected_mailassist_category()
    assert "Travel" not in window._mailassist_category_values()
    assert window.mailassist_category_undo_button.isEnabled()
    window._undo_mailassist_category_removal()
    assert "Travel" in window._mailassist_category_values()
    assert window.mailassist_category_list.currentItem().text() == "Travel"
    assert not window.mailassist_category_undo_button.isEnabled()

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


def test_dashboard_shows_since_reboot_activity_history(monkeypatch, tmp_path: Path) -> None:
    _app()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "mailassist.gui.bot_controller.system_boot_time_utc",
        lambda: datetime(2026, 5, 2, 9, 0, tzinfo=timezone.utc),
    )
    window = MailAssistDesktopWindow()
    log_path = window.settings.bot_logs_dir / "bot-watch-once-sample.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        "\n".join(
            json.dumps(event)
            for event in (
                {
                    "type": "completed",
                    "action": "watch-once",
                    "timestamp": "2026-05-02T08:00:02+00:00",
                    "provider": "gmail",
                    "draft_count": 8,
                    "draft_ready_count": 0,
                    "skipped_count": 0,
                    "already_handled_count": 0,
                },
                {
                    "type": "started",
                    "action": "watch-once",
                    "timestamp": "2026-05-02T10:00:00+00:00",
                },
                {
                    "type": "completed",
                    "action": "watch-once",
                    "timestamp": "2026-05-02T10:00:02+00:00",
                    "provider": "gmail",
                    "draft_count": 2,
                    "draft_ready_count": 1,
                    "skipped_count": 3,
                    "already_handled_count": 0,
                },
            )
        )
        + "\n",
        encoding="utf-8",
    )
    already_log_path = window.settings.bot_logs_dir / "bot-watch-loop-already.jsonl"
    already_log_path.write_text(
        "\n".join(
            json.dumps(event)
            for event in (
                {
                    "type": "started",
                    "action": "watch-loop",
                    "timestamp": "2026-05-02T10:05:00+00:00",
                },
                {
                    "type": "already_handled",
                    "action": "watch-loop",
                    "timestamp": "2026-05-02T10:05:02+00:00",
                    "classification": "automated",
                },
            )
        )
        + "\n",
        encoding="utf-8",
    )

    window.refresh_bot_logs()
    window.refresh_dashboard()

    assert "Since reboot" in [
        label.text() for label in window.findChildren(QLabel)
    ]
    assert "6 scanned" in window.activity_history_label.text()
    assert "3 no reply" in window.activity_history_label.text()
    assert "2 replies drafted" in window.activity_history_label.text()
    assert "1 previews" in window.activity_history_label.text()
    assert "1 already handled" in window.activity_history_label.text()
    assert "8 replies drafted" not in window.activity_history_label.text()
    window.close()


def test_dashboard_since_reboot_uses_unique_live_state_counts(
    monkeypatch, tmp_path: Path
) -> None:
    _app()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "mailassist.gui.bot_controller.system_boot_time_utc",
        lambda: datetime(2026, 6, 17, 9, 0, tzinfo=timezone.utc),
    )
    window = MailAssistDesktopWindow()
    state_path = tmp_path / "data" / "live-state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "account_email": "magali@example.com",
                "provider_accounts": {"outlook": "magali@example.com"},
                "providers": {
                    "outlook": {
                        "cursor": None,
                        "threads": {
                            "conv-1": {
                                "thread_id": "conv-1",
                                "latest_message_id": "msg-1",
                                "classification": "reply_needed",
                                "action": "draft_created",
                                "provider_draft_id": "draft-1",
                                "updated_at": "2026-06-17T10:00:00+00:00",
                            },
                            "conv-2": {
                                "thread_id": "conv-2",
                                "latest_message_id": "msg-2",
                                "classification": "automated",
                                "action": "skipped",
                                "updated_at": "2026-06-17T10:05:00+00:00",
                            },
                            "conv-3": {
                                "thread_id": "conv-3",
                                "latest_message_id": "msg-3",
                                "classification": "reply_needed",
                                "action": "user_replied",
                                "updated_at": "2026-06-17T10:10:00+00:00",
                            },
                            "old-conv": {
                                "thread_id": "old-conv",
                                "latest_message_id": "old-msg",
                                "classification": "reply_needed",
                                "action": "draft_created",
                                "provider_draft_id": "old-draft",
                                "updated_at": "2026-06-17T08:00:00+00:00",
                            },
                        },
                    }
                },
                "recent_activity": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    log_path = window.settings.bot_logs_dir / "bot-watch-loop-noisy.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    repeated = [
        {
            "type": "already_handled",
            "action": "watch-loop",
            "timestamp": "2026-06-17T10:20:00+00:00",
            "provider": "outlook",
            "classification": "reply_needed",
        }
        for _index in range(200)
    ]
    repeated.append(
        {
            "type": "failed_pass",
            "action": "watch-loop",
            "timestamp": "2026-06-17T10:21:00+00:00",
            "provider": "outlook",
        }
    )
    log_path.write_text(
        "\n".join(json.dumps(event) for event in repeated) + "\n",
        encoding="utf-8",
    )

    window.refresh_service_activity_summary()

    activity = window.activity_history_label.text()
    assert "2 scanned" in activity
    assert "1 need reply" in activity
    assert "1 automated" in activity
    assert "1 reply drafted" in activity
    assert "1 already handled" in activity
    assert "1 failed" in activity
    assert "200 already handled" not in activity
    window.close()


def test_service_activity_refresh_updates_dashboard_without_subjects(
    monkeypatch, tmp_path: Path
) -> None:
    _app()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "mailassist.gui.bot_controller.system_boot_time_utc",
        lambda: datetime(2026, 5, 2, 9, 0, tzinfo=timezone.utc),
    )
    window = MailAssistDesktopWindow()
    log_path = window.settings.bot_logs_dir / "bot-watch-loop-service.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        "\n".join(
            json.dumps(event)
            for event in (
                {
                    "type": "started",
                    "action": "watch-loop",
                    "timestamp": "2026-05-02T10:00:00+00:00",
                    "provider": "outlook",
                },
                {
                    "type": "already_handled",
                    "action": "watch-loop",
                    "timestamp": "2026-05-02T10:00:05+00:00",
                    "provider": "outlook",
                    "subject": "Private client tax matter",
                    "classification": "reply_needed",
                },
                {
                    "type": "watch_pass_completed",
                    "action": "watch-loop",
                    "timestamp": "2026-05-02T10:00:07+00:00",
                    "provider": "outlook",
                    "pass_number": 3,
                },
                {
                    "type": "sleeping",
                    "action": "watch-loop",
                    "timestamp": "2026-05-02T10:00:08+00:00",
                    "provider": "outlook",
                    "poll_seconds": 60,
                },
            )
        )
        + "\n",
        encoding="utf-8",
    )

    window.refresh_service_activity_summary()

    assert "0 scanned" in window.activity_history_label.text()
    assert "0 need reply" in window.activity_history_label.text()
    assert "1 already handled" in window.activity_history_label.text()
    assert "Outlook pass 3 completed" in window.last_pass_label.text()
    assert "0 scanned / 0 need reply" in window.last_pass_label.text()
    assert "service agent finished" in window.last_activity_label.text()
    assert "0 scanned / 0 need reply" in window.last_activity_label.text()
    assert "+00:00" not in window.last_activity_label.text()
    assert "Z" not in window.last_activity_label.text()
    assert "Private client tax matter" not in window.last_activity_label.text()
    assert "service agent finished" in window.recent_activity.toPlainText()
    assert "0 scanned / 0 need reply" in window.recent_activity.toPlainText()
    assert "Private client tax matter" not in window.recent_activity.toPlainText()
    window.close()


def test_recent_service_log_marks_bot_as_background_scan() -> None:
    _app()
    window = MailAssistDesktopWindow()
    window.background_scan_last_seen_at = datetime.now(timezone.utc)
    window.refresh_dashboard()

    assert window.bot_status_label.text() == "Background scan"
    window.close()


def test_watch_preview_completion_names_provider() -> None:
    window = MailAssistDesktopWindow()
    stopped = []
    window.bot_heartbeat_timer.start()
    window.bot_timeout_timer.start(120000)
    window.bot_action_started_at = 1000.0
    window._stop_bot_heartbeat = lambda: stopped.append(True)

    window._handle_bot_event(
        {
            "type": "completed",
            "action": "watch-once",
            "provider": "outlook",
            "draft_count": 0,
            "draft_ready_count": 1,
            "skipped_count": 2,
            "already_handled_count": 3,
            "filtered_out_count": 4,
            "dry_run": True,
        }
    )

    activity = window.recent_activity.toPlainText()
    assert "Outlook preview completed: 0 drafts" in activity
    assert "1 dry runs" in activity
    assert "3 already handled" in activity
    assert stopped == [True]
    window.close()


def test_gmail_draft_test_runs_without_confirmation(monkeypatch) -> None:
    window = MailAssistDesktopWindow()
    called: list[tuple[str, str, str, bool, bool]] = []

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("preview should not confirm")),
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
    assert "Previewing Gmail draft" in window.recent_activity.toPlainText()
    window.close()


def test_gmail_draft_test_runs_safe_dry_run(monkeypatch) -> None:
    window = MailAssistDesktopWindow()
    called: list[tuple[str, str, str, bool, bool]] = []

    monkeypatch.setattr(
        window,
        "run_bot_action",
        lambda action, *, thread_id="", prompt="", provider="", force=False, dry_run=False: called.append(
            (action, thread_id, provider, force, dry_run)
        ),
    )

    window.run_gmail_draft_test()

    assert called == [("watch-once", "thread-008", "gmail", True, True)]
    assert "Previewing Gmail draft" in window.recent_activity.toPlainText()
    assert "Heartbeat updates will appear here" in window.recent_activity.toPlainText()
    assert "no Gmail draft will be created" in window.recent_activity.toPlainText()
    assert "auto-stops after 2 minutes" in window.recent_activity.toPlainText()
    window.close()


def test_outlook_draft_preview_runs_without_confirmation(monkeypatch) -> None:
    window = MailAssistDesktopWindow()
    called = []

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("preview should not confirm")),
    )
    monkeypatch.setattr(window, "save_settings", lambda *args, **kwargs: called.append(("save", kwargs)))
    monkeypatch.setattr(window, "run_bot_action", lambda action, **kwargs: called.append((action, kwargs)))

    window.run_outlook_draft_preview()

    assert called == [
        ("save", {"announce": False}),
        (
            "watch-once",
            {
                "provider": "outlook",
                "force": True,
                "dry_run": True,
                "limit": 1,
            },
        ),
    ]
    window.close()


def test_outlook_draft_preview_runs_safe_dry_run(monkeypatch) -> None:
    window = MailAssistDesktopWindow()
    called = []
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
                "limit": 1,
            },
        ),
    ]
    assert "Previewing Outlook draft" in window.recent_activity.toPlainText()
    assert "Heartbeat updates will appear here" in window.recent_activity.toPlainText()
    assert "no Outlook draft will be created" in window.recent_activity.toPlainText()
    assert "auto-stops after 2 minutes" in window.recent_activity.toPlainText()
    window.close()


def test_watch_preview_heartbeat_reports_still_running(monkeypatch) -> None:
    _app()
    window = MailAssistDesktopWindow()
    now = [1000.0]

    monkeypatch.setattr(desktop_module.time, "monotonic", lambda: now[0])
    window.current_bot_action = "watch-once"
    window.current_bot_provider = "outlook"
    window.bot_action_started_at = now[0] - 45
    window.bot_process = object()
    window.bot_progress = {
        "checked": 4,
        "drafts": 1,
        "draft_previews": 2,
        "skipped": 1,
        "already_handled": 0,
        "filtered": 0,
    }

    window._append_bot_heartbeat()

    assert "Outlook preview still running after 45 seconds" in window.recent_activity.toPlainText()
    assert "4 scanned / 0 need reply / 1 no reply / 0 automated" in window.recent_activity.toPlainText()
    assert "1 reply drafted / 2 previews" in window.recent_activity.toPlainText()
    assert "No email will be sent" in window.recent_activity.toPlainText()
    assert "auto-stops after 2 minutes" in window.recent_activity.toPlainText()
    assert "Outlook preview still running after 45 seconds" in window.banner.text()
    window.bot_process = None
    window.close()


def test_watch_progress_reports_last_email_timestamp_without_subject(monkeypatch) -> None:
    _app()
    window = MailAssistDesktopWindow()
    now = [1000.0]

    monkeypatch.setattr(desktop_module.time, "monotonic", lambda: now[0])
    window.current_bot_action = "watch-loop"
    window.current_bot_provider = "outlook"
    window.bot_action_started_at = now[0] - 45
    window.bot_process = object()
    window._reset_bot_progress()

    window._handle_bot_event(
        {
            "type": "email_work_started",
            "provider": "outlook",
            "message_timestamp": "2026-04-24T20:31:00+00:00",
            "subject": "Private tax matter",
            "sender": "client@example.com",
        }
    )
    window._handle_bot_event(
        {
            "type": "email_classified",
            "provider": "outlook",
            "classification": "reply_needed",
            "subject": "Private tax matter",
            "sender": "client@example.com",
        }
    )
    window._append_bot_heartbeat()

    activity = window.recent_activity.toPlainText()
    assert "Manual scan: Outlook working on message dated" in activity
    assert "1 scanned / 1 need reply / 0 no reply / 0 automated" in activity
    assert "0 replies drafted; working on message dated" in activity
    assert "Private tax matter" not in activity
    assert "client@example.com" not in activity
    assert "working on message dated" in window.banner.text()
    window.bot_process = None
    window.close()


def test_watch_loop_outcome_activity_uses_local_time_without_subject() -> None:
    _app()
    window = MailAssistDesktopWindow()
    window.current_bot_action = "watch-loop"
    window.current_bot_provider = "outlook"
    window.bot_process = object()
    window._reset_bot_progress()

    window._handle_bot_event(
        {
            "type": "draft_created",
            "provider": "outlook",
            "timestamp": "2026-06-17T10:02:00+00:00",
            "message_timestamp": "2026-06-17T09:59:00+00:00",
            "classification": "reply_needed",
            "subject": "Private tax matter",
            "sender": "client@example.com",
        }
    )

    activity = window.recent_activity.toPlainText()
    assert "manual agent scanned email dated" in activity
    assert "outcome: Reply Needed; reply drafted." in activity
    assert "2026-06-17T" not in activity
    assert "+00:00" not in activity
    assert "Private tax matter" not in activity
    assert "client@example.com" not in activity
    window.bot_process = None
    window.close()


def test_watch_loop_heartbeat_reports_waiting_after_completed_pass(monkeypatch) -> None:
    _app()
    window = MailAssistDesktopWindow()
    now = [1000.0]

    monkeypatch.setattr(desktop_module.time, "monotonic", lambda: now[0])
    window.current_bot_action = "watch-loop"
    window.current_bot_provider = "gmail"
    window.bot_action_started_at = now[0] - 20
    window.bot_process = object()
    window._reset_bot_progress()
    window.bot_progress["checked"] = 25

    window._handle_bot_event(
        {
            "type": "watch_pass_completed",
            "provider": "gmail",
            "timestamp": "2026-06-17T10:00:00+00:00",
        }
    )
    window._append_bot_heartbeat()

    activity = window.recent_activity.toPlainText()
    assert "manual agent finished: 25 scanned / 0 need reply / 0 no reply / 0 automated" in activity
    assert "Manual scan: Gmail waiting after 20 seconds. Last pass: 25 scanned / 0 need reply" not in activity
    assert "Manual scan: Gmail waiting after 20 seconds. Last pass: 25 scanned / 0 need reply" in window.banner.text()
    assert "auto-check still running" not in activity
    window.bot_process = None
    window.close()


def test_watch_loop_completion_uses_pass_count_payload() -> None:
    _app()
    window = MailAssistDesktopWindow()
    window.current_bot_action = "watch-loop"
    window.current_bot_provider = "outlook"
    window.bot_process = object()
    window._reset_bot_progress()

    window._handle_bot_event(
        {
            "type": "watch_pass_completed",
            "provider": "outlook",
            "timestamp": "2026-06-17T10:00:00+00:00",
            "poll_seconds": 60,
            "scanned_count": 50,
            "need_reply_count": 7,
            "no_reply_count": 13,
            "automated_count": 30,
            "draft_count": 3,
        }
    )

    activity = window.recent_activity.toPlainText()
    assert "manual agent finished" in activity
    assert "50 scanned / 7 need reply / 13 no reply / 30 automated" in activity
    assert "3 replies drafted" in activity
    window.refresh_dashboard()
    assert window.bot_status_label.text() == "Waiting"
    window.bot_process = None
    window.close()


def test_organizer_heartbeat_reports_categorized_progress(monkeypatch) -> None:
    _app()
    window = MailAssistDesktopWindow()
    now = [1000.0]

    monkeypatch.setattr(desktop_module.time, "monotonic", lambda: now[0])
    window.current_bot_action = "gmail-populate-labels"
    window.current_bot_provider = "gmail"
    window.bot_action_started_at = now[0] - 70
    window.bot_process = object()
    window.bot_progress = {"categorized": 12, "total": 40}

    window._append_bot_heartbeat()

    assert "Gmail action still running after 1 min 10 sec" in window.recent_activity.toPlainText()
    assert "12/40 scanned · 12 categorized" in window.recent_activity.toPlainText()
    window.bot_process = None
    window.close()


def test_organizer_heartbeat_reports_current_setup_phase(monkeypatch) -> None:
    _app()
    window = MailAssistDesktopWindow()
    now = [1000.0]

    monkeypatch.setattr(desktop_module.time, "monotonic", lambda: now[0])
    window.current_bot_action = "gmail-populate-labels"
    window.current_bot_provider = "gmail"
    window.bot_action_started_at = now[0] - 30
    window.bot_process = object()
    window._reset_bot_progress()

    window._handle_bot_event(
        {
            "type": "organize_phase",
            "provider": "gmail",
            "phase": "reading_threads",
            "message": "Reading Gmail threads from the last 7 days.",
        }
    )
    window._append_bot_heartbeat()

    activity = window.recent_activity.toPlainText()
    assert "Reading Gmail threads from the last 7 days." in activity
    assert "0 scanned · 0 categorized" in activity
    window.bot_process = None
    window.close()


def test_thread_classification_started_updates_current_progress() -> None:
    window = MailAssistDesktopWindow()
    window.current_bot_action = "gmail-populate-labels"
    window._reset_bot_progress()

    window._handle_bot_event(
        {
            "type": "gmail_thread_classification_started",
            "provider": "gmail",
            "subject": "Security alert",
            "current_index": 1,
            "thread_count": 365,
        }
    )

    assert window.bot_progress["total"] == 365
    assert window.bot_progress["current_index"] == 1
    assert "Security alert" not in window.recent_activity.toPlainText()
    assert window._bot_progress_summary() == "1/365 scanned · 0 categorized"
    window.close()


def test_thread_category_events_update_progress_and_activity() -> None:
    window = MailAssistDesktopWindow()
    window.current_bot_action = "outlook-populate-categories"
    window._reset_bot_progress()

    window._handle_bot_event(
        {
            "type": "outlook_thread_categorized",
            "subject": "Quarterly tax packet",
            "category": "Needs Reply",
            "updated_message_count": 2,
        }
    )

    assert window.bot_progress["categorized"] == 1
    assert window.bot_progress["updated_messages"] == 2
    assert window.recent_activity.toPlainText() == "No bot activity yet."
    assert "Quarterly tax packet" not in window.recent_activity.toPlainText()
    window.close()


def test_organizer_completion_reports_categorized_totals() -> None:
    window = MailAssistDesktopWindow()

    window._handle_bot_event(
        {
            "type": "completed",
            "action": "outlook-populate-categories",
            "provider": "outlook",
            "thread_count": 30,
            "applied_count": 30,
            "message_update_count": 42,
        }
    )

    activity = window.recent_activity.toPlainText()
    assert "Outlook organize completed: 30 emails categorized" in activity
    assert "30 category writes" in activity
    assert "42 messages updated" in activity
    window.close()


def test_outlook_organizer_connection_failure_is_explained() -> None:
    window = MailAssistDesktopWindow()

    window._handle_bot_event(
        {
            "type": "outlook_readiness",
            "provider": "outlook",
            "ready": False,
            "message": "Outlook sign-in expired or was revoked.",
        }
    )
    window._handle_bot_event(
        {
            "type": "completed",
            "action": "outlook-populate-categories",
            "provider": "outlook",
            "ready": False,
            "thread_count": 0,
            "applied_count": 0,
            "message": "Outlook category population stopped because provider is not ready.",
        }
    )

    activity = window.recent_activity.toPlainText()
    assert "Outlook connection failed: Outlook sign-in expired or was revoked." in activity
    assert "Outlook organize stopped before reading mail" in activity
    assert "Outlook sign-in expired or was revoked." in activity
    assert window.last_failure_summary == "Outlook sign-in expired or was revoked."
    window.close()


def test_gmail_organizer_connection_failure_is_explained() -> None:
    window = MailAssistDesktopWindow()
    window.current_bot_action = "gmail-populate-labels"
    window.current_bot_provider = "gmail"
    window._reset_bot_progress()

    window._handle_bot_event(
        {
            "type": "error",
            "action": "gmail-populate-labels",
            "message": "Gmail sign-in expired. Run Gmail setup again.",
        }
    )

    activity = window.recent_activity.toPlainText()
    assert "Gmail organize stopped before the first category" in activity
    assert "Gmail sign-in expired" in activity
    assert window.last_failure_summary == "Gmail sign-in expired. Run Gmail setup again."
    window.close()


def test_gmail_organizer_mid_run_failure_reports_partial_progress() -> None:
    window = MailAssistDesktopWindow()
    window.current_bot_action = "gmail-populate-labels"
    window.current_bot_provider = "gmail"
    window._reset_bot_progress()
    window.bot_progress["categorized"] = 7

    window._handle_bot_event(
        {
            "type": "error",
            "action": "gmail-populate-labels",
            "message": "Gmail quota exceeded.",
        }
    )

    activity = window.recent_activity.toPlainText()
    assert "Gmail organize stopped after 7 emails categorized" in activity
    assert "Gmail quota exceeded" in activity
    window.close()


def test_watch_preview_heartbeat_starts_immediately_and_sets_timeout(monkeypatch) -> None:
    window = MailAssistDesktopWindow()
    now = [1000.0]
    timer_started = []
    timeout_started = []

    monkeypatch.setattr(desktop_module.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(window.bot_heartbeat_timer, "start", lambda: timer_started.append(True))
    monkeypatch.setattr(window.bot_timeout_timer, "start", lambda ms: timeout_started.append(ms))
    window.bot_process = object()
    window.current_bot_action = "watch-once"

    window._start_bot_heartbeat("watch-once", "gmail", dry_run=True)

    assert "Gmail preview still running after 0 seconds" in window.recent_activity.toPlainText()
    assert timer_started == [True]
    assert timeout_started == [120000]
    window.bot_process = None
    window.close()


def test_preview_bot_action_sets_shorter_ollama_timeout(monkeypatch) -> None:
    _app()
    window = MailAssistDesktopWindow()
    monkeypatch.setattr(window, "_start_bot_heartbeat", lambda *args, **kwargs: None)
    monkeypatch.setattr(desktop_module.QProcess, "start", lambda self, *args: None)

    window.run_bot_action("watch-once", provider="outlook", dry_run=True)

    assert window.bot_process.processEnvironment().value("MAILASSIST_OLLAMA_GENERATE_TIMEOUT_SECONDS") == "110"
    window.bot_process = None
    window.close()


def test_gui_bot_action_uses_venv_console_python() -> None:
    _app()
    window = MailAssistDesktopWindow()
    scripts_dir = "Scripts" if os.name == "nt" else "bin"
    executable_name = "python.exe" if os.name == "nt" else "python"
    expected = window.settings.root_dir / ".venv" / scripts_dir / executable_name

    assert window._bot_python_executable() == (str(expected) if expected.exists() else sys.executable)
    window.close()


def test_watch_preview_timeout_stops_bot(monkeypatch) -> None:
    window = MailAssistDesktopWindow()
    stopped = []

    monkeypatch.setattr(window, "stop_bot_action", lambda: stopped.append(True))
    window.bot_process = object()
    window.current_bot_provider = "outlook"

    window._stop_bot_after_timeout()

    assert stopped == [True]
    assert "Outlook preview stopped after 2 minutes" in window.recent_activity.toPlainText()
    assert "Outlook preview stopped after 2 minutes" in window.banner.text()
    window.bot_process = None
    window.close()


def test_watch_preview_error_is_visible_in_recent_activity() -> None:
    window = MailAssistDesktopWindow()
    stopped = []
    window.current_bot_action = "watch-once"
    window.current_bot_provider = "outlook"
    window.current_bot_dry_run = True
    window._stop_bot_heartbeat = lambda: stopped.append(True)

    window._handle_bot_event(
        {
            "type": "error",
            "action": "watch-once",
            "message": "Outlook sign-in expired or was revoked (invalid_grant).",
        }
    )

    assert "Outlook preview failed" in window.recent_activity.toPlainText()
    assert "invalid_grant" in window.recent_activity.toPlainText()
    assert "invalid_grant" in window.banner.text()
    assert window.bot_status_label.text() == "Outlook sign-in expired"
    window.refresh_dashboard()
    assert window.bot_status_label.text() == "Outlook sign-in expired"
    assert stopped == [True]
    window.close()


def test_invalid_grant_error_is_expanded_in_recent_activity() -> None:
    window = MailAssistDesktopWindow()
    window.current_bot_action = "watch-once"
    window.current_bot_provider = "outlook"
    window.current_bot_dry_run = True
    window._stop_bot_heartbeat = lambda: None

    window._handle_bot_event(
        {
            "type": "error",
            "action": "watch-once",
            "message": "invalid_grant",
        }
    )

    activity = window.recent_activity.toPlainText()
    assert "Outlook sign-in expired or was revoked (invalid_grant)" in activity
    assert "Run Outlook setup/auth again" in window.last_failure_summary
    assert window.bot_status_label.text() == "Outlook sign-in expired"
    window.close()


def test_bot_finish_stops_heartbeat_timer(monkeypatch) -> None:
    window = MailAssistDesktopWindow()
    stopped = []

    monkeypatch.setattr(window, "_stop_bot_heartbeat", lambda: stopped.append(True))
    monkeypatch.setattr(window, "refresh_bot_logs", lambda: None)
    window.current_bot_action = "watch-once"
    window.current_bot_provider = "gmail"

    window._handle_bot_finished(0, None)

    assert stopped == [True]
    assert window.current_bot_action == ""
    assert window.current_bot_provider == ""
    assert window.current_bot_dry_run is False
    window.close()


def test_controlled_gmail_draft_runs_after_confirmation(monkeypatch) -> None:
    window = MailAssistDesktopWindow()
    called: list[tuple[str, str, str, bool, bool]] = []

    monkeypatch.setattr(window, "_confirm_action", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
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

    monkeypatch.setattr(window, "_confirm_action", lambda *args, **kwargs: QMessageBox.StandardButton.No)
    monkeypatch.setattr(window, "save_settings", lambda *args, **kwargs: called.append(("save",)))
    monkeypatch.setattr(window, "run_bot_action", lambda *args, **kwargs: called.append(("run",)))

    window.run_gmail_label_rescan()

    assert called == []
    assert window.banner.text() == "Gmail label rescan canceled."
    window.close()


def test_embedded_settings_blocks_bot_confirmation(monkeypatch) -> None:
    window = MailAssistDesktopWindow()
    called = []

    monkeypatch.setattr(
        window,
        "_confirm_action",
        lambda *args, **kwargs: called.append(("question",)) or QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(window, "run_bot_action", lambda *args, **kwargs: called.append(("run",)))

    window.settings_open = True
    window.run_gmail_label_rescan()

    assert called == []
    assert window.banner.text() == "Return to Dashboard before starting a bot action."
    window.close()


def test_gmail_label_rescan_runs_with_limited_horizon(monkeypatch) -> None:
    window = MailAssistDesktopWindow()
    called = []
    confirmation_messages = []
    window.gmail_label_days_input.setValue(3)

    def fake_confirmation(title, message):
        confirmation_messages.append((title, message))
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(window, "_confirm_action", fake_confirmation)
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
    assert "Organizing Gmail for the last 3 days" in window.recent_activity.toPlainText()
    assert "can take a few minutes" in window.recent_activity.toPlainText()
    window.close()


def test_organizer_buttons_do_not_prompt_when_bot_action_is_running(monkeypatch) -> None:
    window = MailAssistDesktopWindow()

    class FakeProcess:
        pass

    window.bot_process = FakeProcess()
    monkeypatch.setattr(
        window,
        "_confirm_action",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("confirmation should not open")),
    )

    window.run_gmail_label_rescan()
    window.run_outlook_category_rescan()

    assert window.banner.text() == "A bot action is already running."
    window.bot_process = None
    window.refresh_dashboard()
    window.close()


def test_outlook_category_rescan_requires_confirmation(monkeypatch) -> None:
    window = MailAssistDesktopWindow()
    called = []

    monkeypatch.setattr(window, "_confirm_action", lambda *args, **kwargs: QMessageBox.StandardButton.No)
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

    def fake_confirmation(title, message):
        confirmation_messages.append((title, message))
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(window, "_confirm_action", fake_confirmation)
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
    assert "Organizing Outlook for the last 12 days" in window.recent_activity.toPlainText()
    assert "can take a few minutes" in window.recent_activity.toPlainText()
    window.close()


def test_start_auto_check_warns_in_recent_activity_before_running(monkeypatch) -> None:
    _app()
    window = MailAssistDesktopWindow()
    called = []

    monkeypatch.setattr(
        window,
        "_suspend_background_scan_for_gui_test",
        lambda: "service-paused",
    )
    monkeypatch.setattr(window, "run_bot_action", lambda action, **kwargs: called.append((action, kwargs)))

    window.start_watch_loop()

    assert called == [("watch-loop", {"provider": window._selected_provider(), "max_passes": 1})]
    assert "service agent suspended; manual agent started" in window.recent_activity.toPlainText()
    assert "Manual scan starting" in window.banner.text()
    assert "drafting can take a minute" in window.banner.text()
    window.close()


def test_suspend_background_scan_treats_killed_child_chain_as_paused(monkeypatch) -> None:
    _app()
    window = MailAssistDesktopWindow()

    class Result:
        returncode = 0
        stdout = "stopped:4\n"
        stderr = ""

    monkeypatch.setattr(desktop_module.sys, "platform", "win32")
    monkeypatch.setattr(window, "_scheduled_task_command", lambda command: Result())

    message = window._suspend_background_scan_for_gui_test()

    assert message == "service-paused"
    assert window.background_scan_task_available is True
    assert window.background_scan_resume_pending is True
    window.close()


def test_suspend_background_scan_timeout_message_is_concise(monkeypatch) -> None:
    _app()
    window = MailAssistDesktopWindow()

    def timeout(_command):
        raise desktop_module.subprocess.TimeoutExpired(
            cmd=["powershell.exe", "-Command", "very long script"],
            timeout=desktop_module.SCHEDULED_TASK_COMMAND_TIMEOUT_SECONDS,
        )

    monkeypatch.setattr(desktop_module.sys, "platform", "win32")
    monkeypatch.setattr(window, "_scheduled_task_command", timeout)

    message = window._suspend_background_scan_for_gui_test()

    assert "Windows did not finish the pause command" in message
    assert "very long script" not in message
    assert "powershell.exe" not in message
    window.close()


def test_resume_background_scan_reports_manual_to_service_transition(monkeypatch) -> None:
    _app()
    window = MailAssistDesktopWindow()

    class Result:
        returncode = 0
        stdout = "started\n"
        stderr = ""

    monkeypatch.setattr(desktop_module.sys, "platform", "win32")
    monkeypatch.setattr(window, "_scheduled_task_command", lambda command: Result())
    window.background_scan_resume_pending = True
    window.background_scan_task_available = True

    window._resume_background_scan_after_gui_test()

    activity = window.recent_activity.toPlainText()
    assert "service agent started" in activity
    window.close()


def test_resume_background_scan_timeout_message_is_concise(monkeypatch) -> None:
    _app()
    window = MailAssistDesktopWindow()

    def timeout(_command):
        raise desktop_module.subprocess.TimeoutExpired(
            cmd=["powershell.exe", "-Command", "very long script"],
            timeout=desktop_module.SCHEDULED_TASK_COMMAND_TIMEOUT_SECONDS,
        )

    monkeypatch.setattr(desktop_module.sys, "platform", "win32")
    monkeypatch.setattr(window, "_scheduled_task_command", timeout)
    window.background_scan_resume_pending = True
    window.background_scan_task_available = True

    window._resume_background_scan_after_gui_test()

    activity = window.recent_activity.toPlainText()
    assert "Windows did not finish the resume command" in activity
    assert "very long script" not in activity
    assert "powershell.exe" not in activity
    window.close()


def test_clear_recent_activity_resets_visible_activity_only() -> None:
    window = MailAssistDesktopWindow()

    window._append_recent_activity("Already handled: noisy thread.")
    window.clear_recent_activity()

    assert window.clear_recent_activity_button.text() == "Clear"
    assert "Saved run logs are not deleted" in window.clear_recent_activity_button.toolTip()
    assert window.recent_activity.toPlainText() == "No bot activity yet."
    assert window.last_activity_summary == "Idle"
    assert window.last_activity_label.text() == "Idle"
    assert window.banner.text() == "Recent Activity cleared."
    window.close()


def test_clear_recent_activity_button_sits_left_of_activity_text() -> None:
    app = _app()
    window = MailAssistDesktopWindow()
    window.resize(1120, 760)
    app.processEvents()

    button_left = window.activity_report_button.mapTo(
        window.activity_group,
        window.activity_report_button.rect().topLeft(),
    )
    text_left = window.recent_activity.mapTo(
        window.activity_group,
        window.recent_activity.rect().topLeft(),
    )

    assert button_left.x() < text_left.x()
    assert abs(button_left.y() - text_left.y()) < 8
    clear_left = window.clear_recent_activity_button.mapTo(
        window.activity_group,
        window.clear_recent_activity_button.rect().topLeft(),
    )
    assert clear_left.x() == button_left.x()
    assert clear_left.y() > button_left.y()
    window.close()


def test_recent_activity_wraps_and_has_report_button() -> None:
    app = _app()
    window = MailAssistDesktopWindow()

    window.activity_report_button.clicked.emit()
    app.processEvents()

    assert window.activity_report_button.text() == "Report"
    assert "detailed activity report" in window.activity_report_button.toolTip()
    assert window.main_stack.currentWidget() is window.activity_page
    assert window.nav_buttons["Activity"].isChecked()
    assert window.bot_logs_dialog is None
    assert window.recent_activity.lineWrapMode() == QPlainTextEdit.LineWrapMode.WidgetWidth
    assert window.recent_activity.wordWrapMode() == QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere
    assert window.recent_activity.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Ignored
    assert window.recent_activity.minimumWidth() == 0
    window.close()


def test_recent_activity_long_lines_do_not_force_window_wide() -> None:
    app = _app()
    window = MailAssistDesktopWindow()
    window.resize(900, 680)

    window._append_recent_activity("Long status " + ("keeps-going " * 80))
    app.processEvents()

    assert window.recent_activity.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Ignored
    assert window.width() <= 900
    assert window.recent_activity.width() < 760
    window.close()


def test_stop_ollama_requires_confirmation(monkeypatch) -> None:
    window = MailAssistDesktopWindow()
    called = []

    monkeypatch.setattr(window, "_confirm_action", lambda *args, **kwargs: QMessageBox.StandardButton.No)
    monkeypatch.setattr(window, "_stop_ollama_process", lambda model: called.append(model))

    window.stop_ollama_action()

    assert called == []
    assert window.banner.text() == "Stop Ollama canceled."
    window.close()


def test_stop_ollama_runs_force_stop_after_confirmation(monkeypatch) -> None:
    window = MailAssistDesktopWindow()
    called = []

    monkeypatch.setattr(window, "_confirm_action", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(
        window,
        "_stop_ollama_process",
        lambda model: called.append(model)
        or (True, "Ollama stop requested. Restart Ollama before running more model actions."),
    )

    window.stop_ollama_action()

    assert called == [window.settings.ollama_model]
    assert "Stopping Ollama" in window.recent_activity.toPlainText()
    assert "Ollama stop requested" in window.recent_activity.toPlainText()
    assert "Ollama stop requested" in window.banner.text()
    window.close()


def test_restart_ollama_starts_server(monkeypatch) -> None:
    window = MailAssistDesktopWindow()
    called = []
    refreshed = []

    monkeypatch.setattr(
        window,
        "_start_ollama_process",
        lambda: called.append(("start",))
        or (True, "Ollama headless start requested. Try the model test again in a few seconds."),
    )
    monkeypatch.setattr(window, "refresh_models", lambda *args, **kwargs: refreshed.append(kwargs))
    monkeypatch.setattr(desktop_module.QTimer, "singleShot", lambda _delay, callback: callback())

    window.restart_ollama_action()

    assert called == [("start",)]
    assert refreshed == [{"silent": True}]
    assert "Starting Ollama server headlessly" in window.recent_activity.toPlainText()
    assert "Ollama headless start requested" in window.recent_activity.toPlainText()
    assert "Ollama headless start requested" in window.banner.text()
    window.close()


def test_restart_ollama_process_runs_ollama_serve(monkeypatch) -> None:
    window = MailAssistDesktopWindow()
    calls = []

    monkeypatch.setattr(desktop_module.shutil, "which", lambda name: "/usr/local/bin/ollama")

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))

    monkeypatch.setattr(desktop_module.subprocess, "Popen", fake_popen)

    ok, message = window._start_ollama_process()

    assert ok is True
    assert "headless start requested" in message
    assert calls[0][0] == ["/usr/local/bin/ollama", "serve"]
    window.close()


def test_stop_ollama_process_runs_model_stop_and_platform_kill(monkeypatch) -> None:
    window = MailAssistDesktopWindow()
    calls = []

    class Result:
        returncode = 0
        stderr = ""

    monkeypatch.setattr(desktop_module.shutil, "which", lambda name: "/usr/local/bin/ollama")
    monkeypatch.setattr(desktop_module.sys, "platform", "darwin")

    def fake_run(command, **kwargs):
        calls.append(command)
        return Result()

    monkeypatch.setattr(desktop_module.subprocess, "run", fake_run)

    ok, message = window._stop_ollama_process("qwen3:8b")

    assert ok is True
    assert "Restart Ollama" in message
    assert calls[0] == ["/usr/local/bin/ollama", "stop", "qwen3:8b"]
    assert ["pkill", "-x", "ollama"] in calls
    assert ["pkill", "-x", "Ollama"] in calls
    window.close()


def test_ollama_force_quit_commands_are_platform_specific() -> None:
    assert ["taskkill", "/IM", "ollama.exe", "/F"] in desktop_module._ollama_force_quit_commands(
        "win32"
    )
    assert ["pkill", "-x", "Ollama"] in desktop_module._ollama_force_quit_commands("darwin")
    assert desktop_module._ollama_force_quit_commands("linux") == [["pkill", "-x", "ollama"]]


def test_bot_control_actions_use_user_centered_labels_tooltips_and_compact_days_input() -> None:
    window = MailAssistDesktopWindow()

    assert window.gmail_draft_preview_button.text() == "Preview Gmail Draft"
    assert window.outlook_draft_preview_button.text() == "Preview Outlook Draft"
    assert window.gmail_label_rescan_button.text() == "Organize Gmail"
    assert window.outlook_category_rescan_button.text() == "Organize Outlook"
    assert window.start_watch_loop_button.text() == "Start Auto-Check"
    assert "dry run" in window.gmail_draft_preview_button.toolTip()
    assert "will not create a Gmail draft" in window.gmail_draft_preview_button.toolTip()
    assert "will not create an Outlook draft" in window.outlook_draft_preview_button.toolTip()
    assert "This can take several minutes" in window.gmail_label_rescan_button.toolTip()
    assert "This can take several minutes" in window.outlook_category_rescan_button.toolTip()
    assert "never sends email" in window.start_watch_loop_button.toolTip()
    assert "pauses it first" in window.start_watch_loop_button.toolTip()
    assert "Stop the currently running" in window.stop_bot_button.toolTip()
    assert window.gmail_label_days_input.maximumWidth() <= 104
    assert window.outlook_category_days_input.maximumWidth() <= 104
    assert window.gmail_label_days_input.height() == window.gmail_label_rescan_button.height()
    assert window.outlook_category_days_input.height() == window.outlook_category_rescan_button.height()
    assert window.gmail_label_days_input.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons
    assert window.outlook_category_days_input.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons
    assert window.bot_poll_seconds_input.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons
    assert "QSpinBox::up-button" not in window.styleSheet()
    window.close()


def test_bot_action_controls_disable_and_wait_cursor_while_running() -> None:
    app = _app()
    window = MailAssistDesktopWindow()
    app.processEvents()

    class FakeProcess:
        pass

    window.bot_process = FakeProcess()
    window.refresh_dashboard()

    assert not window.gmail_draft_preview_button.isEnabled()
    assert not window.outlook_draft_preview_button.isEnabled()
    assert not window.gmail_label_rescan_button.isEnabled()
    assert not window.outlook_category_rescan_button.isEnabled()
    assert not window.start_watch_loop_button.isEnabled()
    assert not window.gmail_label_days_input.isEnabled()
    assert not window.outlook_category_days_input.isEnabled()
    assert window.stop_bot_button.isEnabled()
    assert QApplication.overrideCursor() is not None

    window.bot_process = None
    window.refresh_dashboard()

    assert window.gmail_draft_preview_button.isEnabled()
    assert window.outlook_draft_preview_button.isEnabled()
    assert window.gmail_label_rescan_button.isEnabled()
    assert window.outlook_category_rescan_button.isEnabled()
    assert window.start_watch_loop_button.isEnabled()
    assert window.gmail_label_days_input.isEnabled()
    assert window.outlook_category_days_input.isEnabled()
    assert not window.stop_bot_button.isEnabled()
    assert QApplication.overrideCursor() is None

    window.close()


def test_auto_check_button_becomes_stop_and_resume_during_watch_loop(monkeypatch) -> None:
    _app()
    window = MailAssistDesktopWindow()
    stopped = []

    class FakeProcess:
        pass

    window.bot_process = FakeProcess()
    window.current_bot_action = "watch-loop"
    monkeypatch.setattr(window, "stop_bot_action", lambda: stopped.append(True))

    window.refresh_dashboard()

    assert window.start_watch_loop_button.isEnabled()
    assert window.start_watch_loop_button.text() == "Stop test and resume background scan"
    assert "restart the scheduled MailAssist background scan" in window.start_watch_loop_button.toolTip()

    window.start_watch_loop()

    assert stopped == [True]
    window.bot_process = None
    window.refresh_dashboard()
    window.close()


def test_auto_check_button_ignores_immediate_repeat_click(monkeypatch) -> None:
    _app()
    window = MailAssistDesktopWindow()
    stopped = []

    class FakeProcess:
        pass

    monkeypatch.setattr(desktop_module.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(window, "stop_bot_action", lambda: stopped.append(True))
    window.bot_process = FakeProcess()
    window.current_bot_action = "watch-loop"
    window.watch_loop_stop_guard_until = 103.0

    window.refresh_dashboard()
    window.start_watch_loop()

    assert stopped == []
    assert window.start_watch_loop_button.text() == "Starting Auto-Check"
    assert "Stop will enable shortly" in window.banner.text()
    window.bot_process = None
    window.watch_loop_stop_guard_until = 0.0
    window.refresh_dashboard()
    window.close()


def test_manual_scan_uses_fast_refresh_then_restores_service_interval() -> None:
    _app()
    window = MailAssistDesktopWindow()
    window.bot_process = object()
    window.current_bot_action = "watch-loop"

    assert window.service_activity_timer.interval() == desktop_module.SERVICE_SCAN_REFRESH_INTERVAL_MS

    window._start_bot_heartbeat("watch-loop", "outlook")

    assert window.service_activity_timer.interval() == desktop_module.SERVICE_SCAN_REFRESH_INTERVAL_MS
    assert window.bot_heartbeat_timer.interval() == desktop_module.MANUAL_SCAN_REFRESH_INTERVAL_MS

    window._stop_bot_heartbeat()

    assert window.service_activity_timer.interval() == desktop_module.SERVICE_SCAN_REFRESH_INTERVAL_MS
    assert window.bot_heartbeat_timer.interval() == desktop_module.BOT_HEARTBEAT_INTERVAL_MS
    window.bot_process = None
    window.close()


def test_gui_watch_loop_marks_scan_source_manual() -> None:
    request = bot_process_module.BotActionRequest(
        action="watch-loop",
        base_url="http://localhost:11434",
        selected_model="gemma4:12b-it-qat",
        provider="outlook",
    )

    env = bot_process_module.build_bot_process_environment(request)

    assert env.value("MAILASSIST_SCAN_SOURCE") == "manual"
    assert env.value("MAILASSIST_SCAN_LOCK_WAIT_SECONDS") == "360"


def test_watch_loop_finish_resumes_background_scan(monkeypatch) -> None:
    _app()
    window = MailAssistDesktopWindow()
    resumed = []

    class FakeProcess:
        def readAllStandardOutput(self):
            return b""

    window.bot_process = FakeProcess()
    window.current_bot_action = "watch-loop"
    monkeypatch.setattr(window, "_resume_background_scan_after_gui_test", lambda: resumed.append(True))

    window._handle_bot_finished(0, None)

    assert resumed == [True]
    assert window.current_bot_action == ""
    window.close()


def test_stop_bot_action_kills_gui_process_tree(monkeypatch) -> None:
    _app()
    window = MailAssistDesktopWindow()
    stopped = []

    class FakeProcess:
        def processId(self):
            return 12345

        def terminate(self):
            raise AssertionError("process tree stop should handle Windows GUI tests")

    monkeypatch.setattr(window, "_stop_windows_process_tree", lambda pid: stopped.append(pid))
    window.bot_process = FakeProcess()
    window.current_bot_action = "watch-loop"

    window.stop_bot_action()

    assert stopped == [12345]
    assert window.watch_loop_stop_requested is True
    window.bot_process = None
    window.close()


def test_watch_loop_early_clean_exit_reports_before_resuming(monkeypatch) -> None:
    _app()
    window = MailAssistDesktopWindow()
    resumed = []

    class FakeProcess:
        def readAllStandardOutput(self):
            return b""

    window.bot_process = FakeProcess()
    window.current_bot_action = "watch-loop"
    window.watch_loop_stop_requested = False
    window.watch_loop_pass_completed = False
    monkeypatch.setattr(window, "_resume_background_scan_after_gui_test", lambda: resumed.append(True))

    window._handle_bot_finished(0, None)

    assert resumed == [True]
    assert "manual agent finished before completing a pass" in window.recent_activity.toPlainText()
    assert window.current_bot_action == ""
    window.close()


def test_watch_loop_user_stop_reports_manual_suspended_before_resuming(monkeypatch) -> None:
    _app()
    window = MailAssistDesktopWindow()
    resumed = []

    class FakeProcess:
        def readAllStandardOutput(self):
            return b""

    window.bot_process = FakeProcess()
    window.current_bot_action = "watch-loop"
    window.watch_loop_stop_requested = True
    window.watch_loop_pass_completed = False
    monkeypatch.setattr(window, "_resume_background_scan_after_gui_test", lambda: resumed.append(True))

    window._handle_bot_finished(1, None)

    assert resumed == [True]
    assert "manual agent suspended" in window.recent_activity.toPlainText()
    assert window.current_bot_action == ""
    assert window.last_bot_state != "error"
    window.close()


def test_model_tab_has_stop_and_restart_ollama_controls() -> None:
    window = MailAssistDesktopWindow()

    assert window.stop_ollama_button.text() == "Stop Ollama"
    assert window.restart_ollama_button.text() == "Start Ollama"
    assert "Force quit the local Ollama process" in window.stop_ollama_button.toolTip()
    assert "headlessly" in window.restart_ollama_button.toolTip()

    window.close()


def test_long_control_tooltips_are_wrapped_rich_text() -> None:
    window = MailAssistDesktopWindow()

    for tooltip in (
        window.gmail_draft_preview_button.toolTip(),
        window.outlook_draft_preview_button.toolTip(),
        window.gmail_label_rescan_button.toolTip(),
        window.outlook_category_rescan_button.toolTip(),
        window.start_watch_loop_button.toolTip(),
        window.stop_ollama_button.toolTip(),
        window.restart_ollama_button.toolTip(),
        window.activity_report_button.toolTip(),
        window.clear_recent_activity_button.toolTip(),
    ):
        assert tooltip.startswith("<qt>")
        assert "white-space: normal" in tooltip
        assert "width: 320px" in tooltip

    window.close()


def test_silent_model_refresh_does_not_overwrite_test_result(monkeypatch) -> None:
    window = MailAssistDesktopWindow()

    monkeypatch.setattr(
        window,
        "_list_available_model_state",
        lambda: ([], [], "Unable to reach Ollama."),
    )
    window._set_ollama_result_text("Keep this result visible.")

    window.refresh_models(silent=True)

    assert window.ollama_connection_status.text() == "Not reachable"
    assert "Use Start Ollama" in window.ollama_models_hint.text()
    assert window.ollama_result.toPlainText() == "Keep this result visible."
    window.close()


def test_ollama_test_shows_two_minute_countdown(monkeypatch) -> None:
    window = MailAssistDesktopWindow()
    now = [1000.0]

    monkeypatch.setattr(desktop_module.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(window, "run_bot_action", lambda *args, **kwargs: None)

    window.test_ollama()
    assert "2:00 remaining" in window.ollama_result_label.text()

    now[0] += 31
    window._refresh_ollama_test_countdown()
    assert "1:29 remaining" in window.ollama_result_label.text()

    window.close()


def test_ollama_result_mentions_success_elapsed_seconds(monkeypatch) -> None:
    window = MailAssistDesktopWindow()
    now = [1000.0]

    monkeypatch.setattr(desktop_module.time, "monotonic", lambda: now[0])
    window._start_ollama_test_countdown()
    now[0] += 17

    window._handle_bot_event(
        {
            "type": "ollama_result",
            "action": "ollama-check",
            "prompt": "Say hi.",
            "result": "Hi.",
        }
    )

    assert "Test successful after 17 seconds." in window.ollama_result_label.text()
    assert "Test successful after 17 seconds." in window.ollama_result.toPlainText()
    assert "Test successful after 17 seconds." in window.banner.text()
    assert not window.ollama_test_countdown_timer.isActive()

    window.close()


def test_shared_category_panel_names_gmail_labels_and_outlook_categories() -> None:
    window = MailAssistDesktopWindow()

    labels = [child.text() for child in window.findChildren(QLabel)]

    assert any("Gmail labels and/or Outlook categories" in text for text in labels)
    window.close()
