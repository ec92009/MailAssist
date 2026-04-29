from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any

from PySide6.QtCore import QProcess, Qt, QTimer
from PySide6.QtGui import QFont, QIcon, QKeySequence, QShortcut, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QPlainTextEdit,
    QTextEdit,
    QFrame,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from mailassist.config import (
    ATTRIBUTION_ABOVE_SIGNATURE,
    ATTRIBUTION_BELOW_SIGNATURE,
    ATTRIBUTION_HIDE,
    LOCKED_NEEDS_REPLY_CATEGORY,
    load_settings,
    read_env_file,
    write_env_file,
)
from mailassist.background_bot import TONE_OPTIONS, build_prompt_preview, tone_label
from mailassist.version import load_visible_version
from mailassist.models import utc_now_iso
from mailassist.llm.ollama import OllamaClient
from mailassist.providers.gmail import GmailProvider
from mailassist.rich_text import attribution_html, html_to_plain_text, sanitize_html_fragment
from mailassist.system_resources import (
    format_size,
    effective_available_memory_bytes,
    memory_recommendation_message,
    model_name,
    model_size_bytes,
    system_memory_snapshot,
)


def _configure_form(form: QFormLayout) -> QFormLayout:
    form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
    form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    return form


def _wide_line_edit(value: str = "", *, min_width: int = 560) -> QLineEdit:
    field = QLineEdit(value)
    field.setMinimumWidth(min_width)
    field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return field


def _time_window_combo(current_value: str) -> QComboBox:
    combo = QComboBox()
    for label, value in (
        ("All inbox mail", "all"),
        ("Last 24 hours", "24h"),
        ("Last 7 days", "7d"),
        ("Last 30 days", "30d"),
    ):
        combo.addItem(label, value)
    current_index = combo.findData(current_value)
    if current_index >= 0:
        combo.setCurrentIndex(current_index)
    return combo


def _humanize(token: str) -> str:
    return token.replace("_", " ").title()


def _format_model_size(size_value: object) -> str:
    return format_size(size_value)


def _format_model_age(modified_at: object) -> str:
    value = str(modified_at or "").strip()
    if not value:
        return ""
    if "." in value:
        head, tail = value.split(".", 1)
        suffix = ""
        if "+" in tail:
            fraction, suffix = tail.split("+", 1)
            suffix = f"+{suffix}"
        elif "-" in tail:
            fraction, suffix = tail.split("-", 1)
            suffix = f"-{suffix}"
        elif tail.endswith("Z"):
            fraction, suffix = tail[:-1], "Z"
        else:
            fraction = tail
        value = f"{head}.{fraction[:6]}{suffix}"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    days = max(0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).days)
    if days == 0:
        return "today"
    if days < 14:
        unit_value = days
        unit = "day"
    elif days < 70:
        unit_value = max(1, round(days / 7))
        unit = "week"
    elif days < 730:
        unit_value = max(1, round(days / 30))
        unit = "month"
    else:
        unit_value = max(1, round(days / 365))
        unit = "year"
    suffix = "" if unit_value == 1 else "s"
    return f"{unit_value} {unit}{suffix}"


def _ollama_force_quit_commands(platform: str) -> list[list[str]]:
    if platform == "win32":
        return [
            ["taskkill", "/IM", "ollama.exe", "/F"],
            ["taskkill", "/IM", "Ollama.exe", "/F"],
        ]
    if platform == "darwin":
        return [["pkill", "-x", "ollama"], ["pkill", "-x", "Ollama"]]
    return [["pkill", "-x", "ollama"]]


def _detached_process_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    return kwargs


def _model_display_label(model_detail: dict[str, Any]) -> str:
    name = str(model_detail.get("name", "")).strip()
    age = _format_model_age(model_detail.get("modified_at"))
    detail_parts = [
        value
        for value in (
            _format_model_size(model_detail.get("size")),
            f"updated {age}" if age == "today" else f"updated {age} ago" if age else "",
        )
        if value
    ]
    if not name or not detail_parts:
        return name
    return f"{name} ({', '.join(detail_parts)})"


def _parse_event_timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone()


def _event_time_label(value: object) -> str:
    parsed = _parse_event_timestamp(value)
    if parsed is None:
        return "--:--"
    return parsed.strftime("%H:%M:%S")


def _event_day_time_label(value: object) -> str:
    parsed = _parse_event_timestamp(value)
    if parsed is None:
        return "Unknown time"
    today = datetime.now(parsed.tzinfo).date()
    if parsed.date() == today:
        prefix = "Today"
    elif (today - parsed.date()).days == 1:
        prefix = "Yesterday"
    else:
        prefix = parsed.strftime("%b %-d")
    return f"{prefix} {parsed.strftime('%H:%M')}"


def _short_duration_label(seconds: float) -> str:
    whole_seconds = max(0, int(round(seconds)))
    if whole_seconds < 60:
        return f"{whole_seconds} second{'s' if whole_seconds != 1 else ''}"
    minutes, remainder = divmod(whole_seconds, 60)
    if remainder:
        return f"{minutes} min {remainder} sec"
    return f"{minutes} min"


def _log_action_label(action: str) -> str:
    labels = {
        "gmail-controlled-draft": "Controlled Gmail draft",
        "gmail-inbox-preview": "Gmail inbox preview",
        "ollama-check": "Ollama check",
        "watch-once": "Watch pass",
        "watch-loop": "Watch loop",
    }
    return labels.get(action, _humanize(action))


class MailAssistDesktopWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = load_settings()
        self.bot_process: QProcess | None = None
        self.bot_stdout_buffer = ""
        self.latest_bot_log_path: Path | None = None
        self.bot_logs_dialog: QDialog | None = None
        self.active_progress_label = ""
        self.last_activity_summary = "Idle"
        self.last_pass_summary = ""
        self.last_failure_summary = ""
        self.ollama_health: tuple[str, str] = ("Checking...", "warn")
        self.provider_health: tuple[str, str] = ("", "warn")
        self.ollama_model_details: dict[str, dict[str, Any]] = {}
        self.loaded_ollama_model_details: dict[str, dict[str, Any]] = {}
        self.available_memory_bytes: int | None = None
        self.total_memory_bytes: int | None = None
        self.model_memory_recommendation = ""
        self.last_bot_state = "idle"
        self.gmail_signature_import_attempted = False
        self.review_previous_step_index = 3
        setup_value = read_env_file(self.settings.root_dir / ".env").get("MAILASSIST_SETUP_COMPLETE", "false")
        self.setup_finished = setup_value.strip().lower() == "true"
        self.settings_open = False
        self.settings_dialog: QDialog | None = None
        self.current_bot_action = ""
        self.ollama_test_started_at: float | None = None
        self.ollama_test_deadline_at: float | None = None
        self.ollama_test_countdown_timer = QTimer(self)
        self.ollama_test_countdown_timer.setInterval(1000)
        self.ollama_test_countdown_timer.timeout.connect(self._refresh_ollama_test_countdown)

        self.setWindowTitle(f"MailAssist v{load_visible_version(self.settings.root_dir)}")
        icon_path = self.settings.root_dir / "assets" / "brand" / "mailassist_icon.svg"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(*self._initial_window_size())

        self._build_ui()
        self._install_shortcuts()
        self.refresh_models()
        self.refresh_bot_logs()
        self.refresh_dashboard()

    def _install_shortcuts(self) -> None:
        shortcuts = (
            ("Ctrl+,", self.open_settings_wizard),
            ("Ctrl+L", self.open_bot_logs_dialog),
            ("Esc", lambda: self._set_banner("")),
        )
        for sequence, slot in shortcuts:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(slot)

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("appRoot")
        shell = QVBoxLayout(root)
        shell.setContentsMargins(10, 10, 10, 10)
        shell.setSpacing(8)
        self.setStyleSheet(
            """
            QMainWindow, QWidget#appRoot {
                background: #f7efe6;
            }
            QGroupBox {
                background: #fffaf4;
                border: 1px solid #dfc7ad;
                border-radius: 14px;
                margin-top: 8px;
                padding: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 14px;
                padding: 0 6px;
                color: #8a5d2b;
                font-weight: 700;
            }
            QPushButton {
                background: #ffffff;
                border: 1px solid #cfb89f;
                border-radius: 9px;
                color: #1d2430;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background: #f5e5d1;
            }
            QPushButton:disabled {
                background: #eee9e2;
                color: #9c948b;
            }
            QLineEdit, QComboBox, QPlainTextEdit {
                background: #ffffff;
                border: 1px solid #cfb89f;
                border-radius: 8px;
                color: #1d2430;
                padding: 5px;
                selection-background-color: #2f6da3;
            }
            QComboBox {
                min-width: 260px;
            }
            QCheckBox {
                color: #1d2430;
                spacing: 8px;
            }
            """
        )

        hero = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("MailAssist")
        title.setStyleSheet("font-size: 26px; font-weight: 800; color: #1d2430;")
        title_box.addWidget(title)
        hero.addLayout(title_box, 1)

        self.version_label = QLabel(f"v{load_visible_version(self.settings.root_dir)}")
        self.version_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.version_label.setStyleSheet(
            "border: 1px solid #dccbbb; border-radius: 16px; padding: 8px 12px; color: #5e6978;"
        )
        logs_button = QPushButton("View logs")
        logs_button.setStyleSheet(
            "border: 1px solid #dccbbb; border-radius: 18px; padding: 8px 14px; background: #fffaf4; color: #5e6978;"
        )
        logs_button.clicked.connect(self.open_bot_logs_dialog)
        self.settings_button = QPushButton("Settings")
        self.settings_button.setStyleSheet(
            "border: 1px solid #dccbbb; border-radius: 18px; padding: 8px 14px; background: #fffaf4; color: #5e6978;"
        )
        self.settings_button.clicked.connect(self.open_settings_wizard)
        hero.addWidget(self.settings_button)
        hero.addWidget(logs_button)
        hero.addWidget(self.version_label)
        shell.addLayout(hero)

        self.status_overlay = QWidget()
        self.status_overlay.hide()
        status_layout = QVBoxLayout(self.status_overlay)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(0)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.hide()
        self.progress_bar.setMinimumHeight(44)
        self.progress_bar.setStyleSheet(
            "QProgressBar { border: 1px solid #dccbbb; border-radius: 12px; background: #fffaf4; padding: 2px; }"
            "QProgressBar::chunk { background: #2f6da3; border-radius: 10px; }"
        )
        status_layout.addWidget(self.progress_bar)

        self.banner = QLabel("")
        self.banner.hide()
        self.banner.setStyleSheet(
            "padding: 10px 12px; border-radius: 12px; background: rgba(33,95,74,0.12); color: #215f4a;"
        )
        status_layout.addWidget(self.banner)
        shell.addWidget(self.status_overlay)

        self._build_settings_dialog()

        self.control_group = QGroupBox("Bot Control")
        control_layout = QVBoxLayout(self.control_group)
        control_layout.setContentsMargins(14, 14, 14, 14)
        control_layout.setSpacing(10)

        status_grid = _configure_form(QFormLayout())
        self.bot_status_label = QLabel("Idle")
        self.provider_status_label = QLabel(self.settings.default_provider)
        self.ollama_status_label = QLabel(self.settings.ollama_model)
        self.tone_status_label = QLabel(tone_label(self.settings.user_tone))
        self.signature_status_label = QLabel("Configured" if self.settings.user_signature.strip() else "Missing")
        self.watcher_filter_status_label = QLabel("")
        self.last_activity_label = QLabel(self.last_activity_summary)
        self.last_pass_label = QLabel("No watch pass yet")
        self.last_failure_label = QLabel("None")
        plain_style = "color: #1d2430; font-size: 14px;"
        for label_text, widget, style in (
            ("Bot", self.bot_status_label, ""),
            ("Provider", self.provider_status_label, ""),
            ("Ollama", self.ollama_status_label, ""),
            ("Tone", self.tone_status_label, plain_style),
            ("Signature", self.signature_status_label, plain_style),
            ("Watcher filter", self.watcher_filter_status_label, plain_style),
            ("Last activity", self.last_activity_label, plain_style),
            ("Last pass", self.last_pass_label, plain_style),
            ("Last failure", self.last_failure_label, plain_style),
        ):
            label = QLabel(label_text)
            label.setStyleSheet("color: #5e6978; font-size: 12px;")
            if style:
                widget.setStyleSheet(style)
            status_grid.addRow(label, widget)
        self._set_bot_state("idle")
        control_layout.addLayout(status_grid)

        bot_actions = QHBoxLayout()
        bot_actions.setSpacing(6)
        self.gmail_draft_preview_button = QPushButton("Preview Gmail Draft")
        gmail_draft_test_button = self.gmail_draft_preview_button
        gmail_draft_test_button.clicked.connect(self.run_gmail_draft_test)
        gmail_draft_test_button.setToolTip(
            "Read recent Gmail messages and ask the local model what it would draft. "
            "This is a dry run: MailAssist will not create a Gmail draft and will not send email. "
            "Use it to check whether Gmail access, filters, and the model are behaving before starting auto-check."
        )
        self.outlook_draft_preview_button = QPushButton("Preview Outlook Draft")
        outlook_draft_preview_button = self.outlook_draft_preview_button
        outlook_draft_preview_button.clicked.connect(self.run_outlook_draft_preview)
        outlook_draft_preview_button.setToolTip(
            "Read recent Outlook messages and ask the local model what it would draft. "
            "This is a dry run: MailAssist will not create an Outlook draft and will not send email. "
            "Use it after Outlook setup to validate classification without writing to the mailbox."
        )
        self.gmail_label_rescan_button = QPushButton("Organize Gmail")
        gmail_label_rescan_button = self.gmail_label_rescan_button
        gmail_label_rescan_button.clicked.connect(self.run_gmail_label_rescan)
        gmail_label_rescan_button.setToolTip(
            "Classify recent Gmail threads into your MailAssist categories and apply MailAssist labels. "
            "This can take several minutes because each thread may use the local model. "
            "It changes MailAssist labels only; it does not delete mail and does not send email."
        )
        self.outlook_category_rescan_button = QPushButton("Organize Outlook")
        outlook_category_rescan_button = self.outlook_category_rescan_button
        outlook_category_rescan_button.clicked.connect(self.run_outlook_category_rescan)
        outlook_category_rescan_button.setToolTip(
            "Classify recent Outlook messages into your MailAssist categories and apply Outlook categories. "
            "This can take several minutes because each message may use the local model. "
            "It changes MailAssist categories only; it does not create drafts and does not send email."
        )
        self.gmail_label_days_input = QSpinBox()
        self.gmail_label_days_input.setRange(1, 30)
        self.gmail_label_days_input.setValue(7)
        self.gmail_label_days_input.setSuffix(" days")
        self.gmail_label_days_input.setMinimumWidth(92)
        self.gmail_label_days_input.setMaximumWidth(104)
        self.gmail_label_days_input.setToolTip(
            "How far back Organize Gmail should look. Keep this small for quick checks; larger windows take longer."
        )
        self.outlook_category_days_input = QSpinBox()
        self.outlook_category_days_input.setRange(1, 30)
        self.outlook_category_days_input.setValue(7)
        self.outlook_category_days_input.setSuffix(" days")
        self.outlook_category_days_input.setMinimumWidth(92)
        self.outlook_category_days_input.setMaximumWidth(104)
        self.outlook_category_days_input.setToolTip(
            "How far back Organize Outlook should look. Keep this small for quick checks; larger windows take longer."
        )
        action_height = max(
            gmail_label_rescan_button.sizeHint().height(),
            outlook_category_rescan_button.sizeHint().height(),
            self.gmail_label_days_input.sizeHint().height(),
            self.outlook_category_days_input.sizeHint().height(),
        )
        self.gmail_label_days_input.setFixedHeight(action_height)
        self.outlook_category_days_input.setFixedHeight(action_height)
        self.start_watch_loop_button = QPushButton("Start Auto-Check")
        start_watch_loop_button = self.start_watch_loop_button
        start_watch_loop_button.clicked.connect(self.start_watch_loop)
        start_watch_loop_button.setToolTip(
            "Start continuous background checking for the selected provider. "
            "MailAssist periodically reads matching threads, uses the local model, and creates provider drafts only when needed. "
            "It never sends email. Stop pauses the background process."
        )
        self.stop_bot_button = QPushButton("Stop")
        self.stop_bot_button.clicked.connect(self.stop_bot_action)
        self.stop_bot_button.setEnabled(False)
        self.stop_bot_button.setToolTip(
            "Stop the currently running MailAssist action or auto-check loop. "
            "This does not delete provider drafts or undo labels/categories that were already written."
        )
        for button in (
            gmail_draft_test_button,
            outlook_draft_preview_button,
            gmail_label_rescan_button,
            outlook_category_rescan_button,
            start_watch_loop_button,
            self.stop_bot_button,
        ):
            button.setFixedHeight(action_height)
        label_scan_actions = QHBoxLayout()
        label_scan_actions.setSpacing(4)
        label_scan_actions.addWidget(gmail_label_rescan_button)
        label_scan_actions.addWidget(self.gmail_label_days_input)
        label_scan_actions.addSpacing(6)
        label_scan_actions.addWidget(outlook_category_rescan_button)
        label_scan_actions.addWidget(self.outlook_category_days_input)
        bot_actions.addWidget(gmail_draft_test_button)
        bot_actions.addWidget(outlook_draft_preview_button)
        bot_actions.addLayout(label_scan_actions)
        bot_actions.addWidget(start_watch_loop_button)
        bot_actions.addWidget(self.stop_bot_button)
        bot_actions.addStretch(1)
        control_layout.addLayout(bot_actions)
        shell.addWidget(self.control_group)

        self.activity_group = QGroupBox("Recent Activity")
        activity_layout = QVBoxLayout(self.activity_group)
        activity_layout.setContentsMargins(10, 10, 10, 10)
        self.recent_activity = QPlainTextEdit()
        self.recent_activity.setReadOnly(True)
        self.recent_activity.setMinimumHeight(80)
        self.recent_activity.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.recent_activity.setPlainText("No bot activity yet.")
        activity_layout.addWidget(self.recent_activity, 1)
        shell.addWidget(self.activity_group, 1)

        self._build_bot_logs_dialog()

        self.setCentralWidget(root)
        self._refresh_setup_visibility()

    def _build_bot_logs_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setModal(False)
        dialog.setWindowTitle("MailAssist Bot Logs")
        dialog.resize(980, 760)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        layout.addWidget(self._build_bot_panel(), 1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        close_button = QPushButton("Done")
        close_button.clicked.connect(dialog.close)
        footer.addWidget(close_button)
        layout.addLayout(footer)

        self.bot_logs_dialog = dialog

    def _build_bot_panel(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        bot_actions = QHBoxLayout()
        refresh_logs_button = QPushButton("Refresh log list")
        refresh_logs_button.clicked.connect(self.refresh_bot_logs)
        bot_actions.addWidget(refresh_logs_button)
        self.bot_log_selector = QComboBox()
        self.bot_log_selector.currentIndexChanged.connect(self.load_selected_bot_log)
        bot_actions.addWidget(self.bot_log_selector, 1)
        layout.addLayout(bot_actions)

        stdout_label = QLabel("Live stdout")
        stdout_label.setStyleSheet("font-size: 13px; color: #5e6978;")
        layout.addWidget(stdout_label)
        self.bot_console = QPlainTextEdit()
        self.bot_console.setReadOnly(True)
        self.bot_console.setMinimumHeight(90)
        self.bot_console.setMaximumHeight(120)
        layout.addWidget(self.bot_console)

        log_header = QHBoxLayout()
        log_label = QLabel("Selected log")
        log_label.setStyleSheet("font-size: 13px; color: #5e6978;")
        log_header.addWidget(log_label)
        log_header.addStretch(1)
        self.show_raw_log_checkbox = QCheckBox("Show raw JSON")
        self.show_raw_log_checkbox.toggled.connect(self.load_selected_bot_log)
        log_header.addWidget(self.show_raw_log_checkbox)
        layout.addLayout(log_header)
        self.bot_log_viewer = QPlainTextEdit()
        self.bot_log_viewer.setReadOnly(True)
        self.bot_log_viewer.setMinimumHeight(360)
        layout.addWidget(self.bot_log_viewer, 1)
        return widget

    def open_settings_wizard(self) -> None:
        if self.settings_dialog is None:
            self._build_settings_dialog()
        self.settings_open = True
        self._refresh_setup_visibility()
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()
        self._set_banner("Settings are open in a separate window.", level="info")

    def _build_settings_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setModal(False)
        dialog.setWindowTitle("MailAssist Settings")
        dialog.resize(1120, 720)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        layout.addWidget(self._build_settings_wizard(), 1)
        dialog.finished.connect(self._settings_dialog_closed)
        self.settings_dialog = dialog

    def _settings_dialog_closed(self, _result: int = 0) -> None:
        self.settings_open = False
        self._refresh_setup_visibility()

    def open_bot_logs_dialog(self) -> None:
        if self.bot_logs_dialog is None:
            self._build_bot_logs_dialog()
        self.refresh_bot_logs()
        self.bot_logs_dialog.show()
        self.bot_logs_dialog.raise_()
        self.bot_logs_dialog.activateWindow()

    def _build_settings_wizard(self) -> QWidget:
        widget = QWidget()
        self.settings_wizard = widget
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        self.settings_step_label = QLabel("")
        self.settings_step_label.hide()

        self.settings_step_title = QLabel("")
        self.settings_step_title.setStyleSheet("font-size: 19px; font-weight: 800; color: #1d2430;")
        layout.addWidget(self.settings_step_title)

        self.settings_step_help = QLabel("")
        self.settings_step_help.setWordWrap(True)
        self.settings_step_help.setMinimumWidth(0)
        self.settings_step_help.setMinimumHeight(46)
        self.settings_step_help.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Maximum)
        self.settings_step_help.setStyleSheet(
            "background: #fff3df; border: 1px solid #dfc7ad; border-radius: 10px; padding: 6px; color: #5e6978;"
        )
        layout.addWidget(self.settings_step_help)

        self.settings_stack = QStackedWidget()
        self.settings_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.settings_steps: list[tuple[str, str, bool]] = []
        self.advanced_settings_enabled = False
        self._add_settings_step(
            "Choose Email Provider",
            "",
            self._build_wizard_provider_page(),
        )
        self._add_settings_step(
            "Pick The Local AI Model",
            "This is the model that classifies emails and drafts replies. Larger models are usually better, but slower; background drafting makes that acceptable.",
            self._build_wizard_ollama_model_page(),
        )
        self._add_settings_step(
            "Choose Writing Style",
            "This is the default style the bot asks the local model to use. You can still edit drafts in Gmail before sending.",
            self._build_wizard_writing_style_page(),
        )
        self._add_settings_step(
            "Set Signature",
            "Add the sign-off you want MailAssist to place at the end of each draft.",
            self._build_wizard_signature_page(),
        )
        self._add_settings_step(
            "Advanced Settings?",
            "Optional knobs for connection paths and how often MailAssist checks for new mail.",
            self._build_wizard_advanced_choice_page(),
        )
        self._add_settings_step(
            "Review Choices",
            "Here is the global view of what MailAssist will do. The prompt preview is read-only and uses a sanitized sample email.",
            self._build_wizard_summary_page(),
        )
        layout.insertWidget(0, self._build_settings_progress_line())
        self.settings_stack.setMinimumHeight(420)
        layout.addWidget(self.settings_stack, 1)

        nav = QHBoxLayout()
        nav.setSpacing(10)
        self.settings_back_button = QPushButton("Back")
        self.settings_back_button.setMinimumWidth(120)
        self.settings_back_button.clicked.connect(self._previous_settings_step)
        self.settings_next_button = QPushButton("Next")
        self.settings_next_button.setMinimumWidth(120)
        self.settings_next_button.clicked.connect(self._next_settings_step)
        self.settings_done_button = QPushButton("Done")
        self.settings_done_button.setMinimumWidth(140)
        self.settings_done_button.clicked.connect(self.finish_settings_wizard)
        self.settings_advanced_button = QPushButton("Advanced settings")
        self.settings_advanced_button.setMinimumWidth(160)
        self.settings_advanced_button.clicked.connect(lambda _checked=False: self._open_advanced_settings_step())
        nav.addWidget(self.settings_back_button)
        nav.addStretch(1)
        nav.addWidget(self.settings_advanced_button)
        nav.addWidget(self.settings_next_button)
        nav.addWidget(self.settings_done_button)
        layout.addLayout(nav)

        self.settings_step_index = 0
        self._show_settings_step(0)
        return widget

    def _build_settings_progress_line(self) -> QWidget:
        widget = QWidget()
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(2, 0, 2, 2)
        layout.setSpacing(4)
        self.settings_progress_buttons: list[tuple[QPushButton, int]] = []
        self.settings_progress_segments: list[QFrame] = []
        for stop_index, (label, step_index) in enumerate(self._settings_progress_stops()):
            button = QPushButton(f"●\n{label}")
            button.setFlat(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setMinimumWidth(64)
            button.setMaximumHeight(42)
            button.clicked.connect(partial(self._jump_to_settings_step, step_index))
            self.settings_progress_buttons.append((button, step_index))
            layout.addWidget(button)
            if stop_index < len(self._settings_progress_stops()) - 1:
                segment = QFrame()
                segment.setFixedHeight(3)
                segment.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                self.settings_progress_segments.append(segment)
                layout.addWidget(segment, 1)
        return widget

    def _settings_progress_stops(self) -> tuple[tuple[str, int], ...]:
        return (
            ("Provider", 0),
            ("Model", 1),
            ("Tone", 2),
            ("Signature", 3),
            ("Advanced", 4),
            ("Review", 5),
        )

    def _settings_progress_route_index(self, step_index: int) -> int:
        return step_index

    def _jump_to_settings_step(self, step_index: int) -> None:
        self.save_settings(announce=False)
        if self.settings_steps[self.settings_step_index][0] == "Advanced Settings?":
            self.advanced_settings_enabled = self.advanced_settings_checkbox.isChecked()
        self._show_settings_step(step_index)

    def _toggle_advanced_settings_details(self, checked: bool) -> None:
        self.advanced_settings_enabled = checked
        if hasattr(self, "advanced_settings_details"):
            self.advanced_settings_details.setVisible(checked)
        self._refresh_settings_progress_line()

    def _provider_settings_changed(self, _checked: bool = False) -> None:
        if not hasattr(self, "gmail_enabled") or not hasattr(self, "outlook_enabled"):
            return
        sender = self.sender()
        if not self.gmail_enabled.isChecked() and not self.outlook_enabled.isChecked():
            if sender is self.outlook_enabled:
                self.gmail_enabled.setChecked(True)
            else:
                self.outlook_enabled.setChecked(True)
        self._refresh_prompt_preview()

    def _add_settings_step(
        self,
        title: str,
        help_text: str,
        page: QWidget,
        *,
        advanced: bool = False,
    ) -> None:
        self.settings_steps.append((title, help_text, advanced))
        self.settings_stack.addWidget(page)

    def _build_wizard_provider_page(self) -> QWidget:
        widget = QWidget()
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(widget)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.gmail_enabled = QCheckBox("Gmail")
        self.outlook_enabled = QCheckBox("Outlook")

        gmail_checked = self.settings.gmail_enabled or (
            not self.settings.gmail_enabled and not self.settings.outlook_enabled
        )
        self.gmail_enabled.setChecked(gmail_checked)
        self.outlook_enabled.setChecked(self.settings.outlook_enabled)

        self.gmail_watcher_unread_only_checkbox = QCheckBox("Only process unread threads")
        self.gmail_watcher_unread_only_checkbox.setChecked(self.settings.gmail_watcher_unread_only)
        self.gmail_watcher_time_window_combo = _time_window_combo(self.settings.gmail_watcher_time_window)

        self.outlook_watcher_unread_only_checkbox = QCheckBox("Only process unread threads")
        self.outlook_watcher_unread_only_checkbox.setChecked(self.settings.outlook_watcher_unread_only)
        self.outlook_watcher_time_window_combo = _time_window_combo(self.settings.outlook_watcher_time_window)

        for control in (
            self.gmail_enabled,
            self.outlook_enabled,
            self.gmail_watcher_unread_only_checkbox,
            self.gmail_watcher_time_window_combo,
            self.outlook_watcher_unread_only_checkbox,
            self.outlook_watcher_time_window_combo,
        ):
            if isinstance(control, QCheckBox):
                control.toggled.connect(self._provider_settings_changed)
            else:
                control.currentIndexChanged.connect(self._refresh_prompt_preview)

        self.watcher_unread_only_checkbox = self.gmail_watcher_unread_only_checkbox
        self.watcher_time_window_combo = self.gmail_watcher_time_window_combo

        layout.addWidget(
            self._build_provider_filter_group(
                "Gmail",
                self.gmail_enabled,
                self.gmail_watcher_unread_only_checkbox,
                self.gmail_watcher_time_window_combo,
            )
        )
        layout.addWidget(
            self._build_provider_filter_group(
                "Outlook",
                self.outlook_enabled,
                self.outlook_watcher_unread_only_checkbox,
                self.outlook_watcher_time_window_combo,
            )
        )
        layout.addWidget(self._build_category_settings_group())
        layout.addStretch(1)
        return widget

    def _build_provider_filter_group(
        self,
        title: str,
        enabled_checkbox: QCheckBox,
        unread_checkbox: QCheckBox,
        time_window_combo: QComboBox,
    ) -> QGroupBox:
        group = QGroupBox(title)
        group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(group)
        layout.setSpacing(8)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.addWidget(enabled_checkbox)
        form = _configure_form(QFormLayout())
        form.addRow("Unread", unread_checkbox)
        form.addRow("Time window", time_window_combo)
        layout.addLayout(form)
        return group

    def _mailassist_category_values(self) -> list[str]:
        if not hasattr(self, "mailassist_category_list"):
            return list(self.settings.mailassist_categories)
        values: list[str] = []
        for index in range(self.mailassist_category_list.count()):
            category = str(self.mailassist_category_list.item(index).text()).strip()
            if category:
                values.append(category)
        return values

    def _add_mailassist_category(self) -> None:
        value, ok = QInputDialog.getText(self, "Add Category", "Category name")
        if not ok:
            return
        category = value.replace("/", " ").strip()
        if not category:
            return
        existing = {item.lower() for item in self._mailassist_category_values()}
        if category.lower() in existing:
            for index in range(self.mailassist_category_list.count()):
                if self.mailassist_category_list.item(index).text().lower() == category.lower():
                    self.mailassist_category_list.setCurrentRow(index)
                    break
            return
        self.mailassist_category_list.addItem(category)
        self.mailassist_category_list.setCurrentRow(self.mailassist_category_list.count() - 1)
        self._refresh_prompt_preview()

    def _remove_selected_mailassist_category(self) -> None:
        if not hasattr(self, "mailassist_category_list"):
            return
        item = self.mailassist_category_list.currentItem()
        if item is None:
            return
        index = self.mailassist_category_list.row(item)
        category = item.text().strip()
        if category.lower() == LOCKED_NEEDS_REPLY_CATEGORY.lower():
            self._set_banner("Needs Reply is locked because it drives draft generation.", level="info")
            return
        self.mailassist_category_list.takeItem(index)
        self._refresh_prompt_preview()

    def _build_category_settings_group(self) -> QGroupBox:
        group = QGroupBox("MailAssist Categories")
        group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(group)
        layout.setSpacing(8)
        layout.setContentsMargins(18, 16, 18, 16)

        content = QHBoxLayout()
        content.setSpacing(12)
        actions = QVBoxLayout()
        actions.setSpacing(6)
        self.mailassist_category_list = QListWidget()
        self.mailassist_category_list.setMinimumWidth(420)
        self.mailassist_category_list.setMinimumHeight(128)
        self.mailassist_category_list.setMaximumHeight(170)
        for category in self.settings.mailassist_categories:
            self.mailassist_category_list.addItem(category)
        if self.mailassist_category_list.count():
            self.mailassist_category_list.setCurrentRow(0)

        add_button = QPushButton("Add")
        remove_button = QPushButton("Remove")
        add_button.setMinimumWidth(100)
        remove_button.setMinimumWidth(100)
        add_button.clicked.connect(self._add_mailassist_category)
        remove_button.clicked.connect(self._remove_selected_mailassist_category)
        actions.addWidget(add_button)
        actions.addWidget(remove_button)
        actions.addStretch(1)
        content.addLayout(actions)
        content.addWidget(self.mailassist_category_list, 1)
        layout.addLayout(content)

        note = QLabel(
            "MailAssist uses these categories to create or update Gmail labels and/or "
            "Outlook categories. Needs Reply is locked because MailAssist uses it for "
            "draft generation."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #5e6978; font-size: 13px;")
        layout.addWidget(note)
        return group

    def _build_wizard_ollama_model_page(self) -> QWidget:
        widget = QWidget()
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        model_group = QGroupBox("Local AI Model")
        self.ollama_model_group = model_group
        model_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        model_group.setMaximumHeight(410)
        model_layout = QVBoxLayout(model_group)
        model_layout.setSpacing(6)
        model_layout.setContentsMargins(18, 16, 18, 14)
        model_form = _configure_form(QFormLayout())
        self.ollama_model_picker = QComboBox()
        self.ollama_model_picker.setMinimumWidth(520)
        self.ollama_model_picker.currentIndexChanged.connect(self._ollama_model_selection_changed)
        model_form.addRow("Model", self.ollama_model_picker)
        self.ollama_connection_status = QLabel("Checking Ollama...")
        self.ollama_connection_status.setStyleSheet("color: #5e6978; font-size: 13px;")
        model_form.addRow("Status", self.ollama_connection_status)
        model_layout.addLayout(model_form)
        self.ollama_models_hint = QLabel("")
        self.ollama_models_hint.setWordWrap(True)
        self.ollama_models_hint.setStyleSheet("color: #5e6978; font-size: 13px;")
        self.ollama_models_hint.hide()
        self.ollama_model_hint = QLabel("")
        self.ollama_model_hint.setWordWrap(True)
        self.ollama_model_hint.setStyleSheet(
            "background: #fffaf4; border: 1px solid #dccbbb; border-radius: 10px; padding: 8px; color: #1d2430;"
        )
        model_layout.addWidget(self.ollama_model_hint)
        actions = QHBoxLayout()
        refresh_models_button = QPushButton("Refresh model list")
        refresh_models_button.setMinimumWidth(210)
        refresh_models_button.clicked.connect(self.refresh_models)
        test_button = QPushButton("Send small test prompt")
        test_button.setMinimumWidth(230)
        test_button.clicked.connect(self.test_ollama)
        self.stop_ollama_button = QPushButton("Stop Ollama")
        self.stop_ollama_button.setMinimumWidth(130)
        self.stop_ollama_button.clicked.connect(self.stop_ollama_action)
        self.stop_ollama_button.setToolTip(
            "Force quit the local Ollama process if a model is stuck or still using memory. "
            "This interrupts any current model work."
        )
        self.restart_ollama_button = QPushButton("Start Ollama")
        self.restart_ollama_button.setMinimumWidth(150)
        self.restart_ollama_button.clicked.connect(self.restart_ollama_action)
        self.restart_ollama_button.setToolTip(
            "Start the local Ollama server headlessly, then quietly refresh the installed model list."
        )
        actions.addWidget(refresh_models_button)
        actions.addWidget(test_button)
        actions.addWidget(self.stop_ollama_button)
        actions.addWidget(self.restart_ollama_button)
        actions.addStretch(1)
        model_layout.addLayout(actions)
        self.ollama_result_label = QLabel("Model test result")
        self.ollama_result_label.setStyleSheet("font-size: 13px; color: #5e6978;")
        self.ollama_result_label.setMaximumHeight(22)
        self.ollama_result_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        model_layout.addWidget(self.ollama_result_label)
        self.ollama_result = QPlainTextEdit()
        self.ollama_result.setReadOnly(True)
        self.ollama_result.setPlainText("Send a small test prompt to see the model response here.")
        self.ollama_result.setMinimumHeight(104)
        self.ollama_result.setMaximumHeight(124)
        model_layout.addWidget(self.ollama_result)
        layout.addWidget(model_group, 0, Qt.AlignmentFlag.AlignTop)
        return widget

    def _build_wizard_writing_style_page(self) -> QWidget:
        widget = QWidget()
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)
        style_group = QGroupBox("Writing Style")
        style_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        style_layout = _configure_form(QFormLayout(style_group))
        self.tone_combo = QComboBox()
        self.tone_combo.setMinimumWidth(420)
        for value, (label, _guidance) in TONE_OPTIONS.items():
            self.tone_combo.addItem(label, value)
        tone_index = self.tone_combo.findData(self.settings.user_tone)
        if tone_index >= 0:
            self.tone_combo.setCurrentIndex(tone_index)
        self.tone_combo.currentIndexChanged.connect(self._refresh_prompt_preview)
        style_layout.addRow("Default tone", self.tone_combo)
        layout.addWidget(style_group, 0, Qt.AlignmentFlag.AlignTop)
        return widget

    def _build_wizard_signature_page(self) -> QWidget:
        widget = QWidget()
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)
        signature_group = QGroupBox("Signature")
        signature_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        signature_layout = QVBoxLayout(signature_group)
        signature_layout.setSpacing(8)
        self.signature_input = QTextEdit()
        if self.settings.user_signature_html.strip():
            self.signature_input.setHtml(self.settings.user_signature_html)
        else:
            self.signature_input.setPlainText(self.settings.user_signature)
        self.signature_input.setPlaceholderText("Best regards,\nYour Name")
        self.signature_input.setMinimumHeight(110)
        self.signature_input.setMaximumHeight(140)
        self.signature_input.setAcceptRichText(True)
        self.signature_input.textChanged.connect(self._refresh_prompt_preview)
        signature_toolbar = QHBoxLayout()
        signature_toolbar.setSpacing(6)
        for label, callback in (
            ("B", self._toggle_signature_bold),
            ("I", self._toggle_signature_italic),
            ("U", self._toggle_signature_underline),
            ("Link", self._insert_signature_link),
        ):
            button = QToolButton()
            button.setText(label)
            button.setToolTip(
                {
                    "B": "Bold",
                    "I": "Italic",
                    "U": "Underline",
                    "Link": "Add link",
                }[label]
            )
            button.setAutoRaise(True)
            button.clicked.connect(callback)
            signature_toolbar.addWidget(button)
        signature_toolbar.addStretch(1)
        signature_layout.addLayout(signature_toolbar)
        signature_layout.addWidget(self.signature_input)
        attribution_row = QHBoxLayout()
        attribution_label = QLabel("Attribution")
        self.attribution_placement_combo = QComboBox()
        for label, value in (
            ("Hide", ATTRIBUTION_HIDE),
            ("Above Signature", ATTRIBUTION_ABOVE_SIGNATURE),
            ("Below Signature", ATTRIBUTION_BELOW_SIGNATURE),
        ):
            self.attribution_placement_combo.addItem(label, value)
        attribution_index = self.attribution_placement_combo.findData(
            self.settings.draft_attribution_placement
        )
        if attribution_index >= 0:
            self.attribution_placement_combo.setCurrentIndex(attribution_index)
        self.attribution_placement_combo.currentIndexChanged.connect(self._refresh_prompt_preview)
        attribution_row.addWidget(attribution_label)
        attribution_row.addWidget(self.attribution_placement_combo)
        attribution_row.addStretch(1)
        signature_layout.addLayout(attribution_row)
        self.signature_attribution_preview = QTextEdit()
        self.signature_attribution_preview.setReadOnly(True)
        self.signature_attribution_preview.setAcceptRichText(True)
        self.signature_attribution_preview.setMinimumHeight(110)
        self.signature_attribution_preview.setMaximumHeight(150)
        signature_layout.addWidget(self.signature_attribution_preview)
        signature_actions = QHBoxLayout()
        import_button = QPushButton("Import from Gmail")
        import_button.clicked.connect(lambda _checked=False: self._import_gmail_signature(force=True))
        signature_actions.addWidget(import_button)
        signature_actions.addStretch(1)
        signature_layout.addLayout(signature_actions)
        self.gmail_signature_status = QLabel(
            "MailAssist can start from your Gmail signature if Gmail exposes one."
        )
        self.gmail_signature_status.setWordWrap(True)
        self.gmail_signature_status.setStyleSheet("color: #5e6978; font-size: 13px;")
        signature_layout.addWidget(self.gmail_signature_status)
        self._refresh_prompt_preview()
        layout.addWidget(signature_group, 0, Qt.AlignmentFlag.AlignTop)
        return widget

    def _build_wizard_advanced_choice_page(self) -> QWidget:
        widget = QWidget()
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)
        self.advanced_settings_checkbox = QCheckBox()
        self.advanced_settings_checkbox.setChecked(True)
        self.advanced_settings_checkbox.hide()
        self.advanced_settings_details = self._build_wizard_advanced_page()
        layout.addWidget(self.advanced_settings_details, 0, Qt.AlignmentFlag.AlignTop)
        return widget

    def _build_wizard_advanced_page(self) -> QWidget:
        widget = QWidget()
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        advanced_group = QGroupBox("Advanced Settings")
        advanced_layout = _configure_form(QFormLayout(advanced_group))
        self.ollama_url_input = _wide_line_edit(self.settings.ollama_url)
        self.gmail_credentials_input = _wide_line_edit(str(self.settings.gmail_credentials_file), min_width=620)
        self.gmail_token_input = _wide_line_edit(str(self.settings.gmail_token_file), min_width=620)
        advanced_layout.addRow("Ollama URL", self.ollama_url_input)
        advanced_layout.addRow("Client secret", self.gmail_credentials_input)
        advanced_layout.addRow("Local token", self.gmail_token_input)
        self.bot_poll_seconds_input = QSpinBox()
        self.bot_poll_seconds_input.setRange(5, 3600)
        self.bot_poll_seconds_input.setSingleStep(5)
        self.bot_poll_seconds_input.setMinimumHeight(max(34, self.ollama_url_input.sizeHint().height()))
        self.bot_poll_seconds_input.setValue(max(5, int(self.settings.bot_poll_seconds or 30)))
        advanced_layout.addRow("Check frequency (default 30 seconds)", self.bot_poll_seconds_input)
        layout.addWidget(advanced_group)

        refresh_button = QPushButton("Check connection and refresh models")
        refresh_button.clicked.connect(self.refresh_models)
        layout.addWidget(refresh_button)
        return widget

    def _build_wizard_summary_page(self) -> QWidget:
        widget = QWidget()
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(widget)
        layout.setSpacing(0)
        self.settings_summary = QPlainTextEdit()
        self.settings_summary.setReadOnly(True)
        self.settings_summary.setMinimumHeight(240)
        self.settings_summary.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        font = QFont("Menlo")
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.settings_summary.setFont(font)
        layout.addWidget(self.settings_summary, 1)
        return widget

    def _show_settings_step(self, index: int) -> None:
        self.settings_step_index = max(0, min(index, self.settings_stack.count() - 1))
        self.settings_stack.setCurrentIndex(self.settings_step_index)
        title, help_text, _advanced = self.settings_steps[self.settings_step_index]
        visible_indices = self._visible_settings_indices()
        visible_position = visible_indices.index(self.settings_step_index) + 1
        self.settings_step_label.setText(f"Step {visible_position} of {len(visible_indices)}")
        self.settings_step_title.setText(title)
        if help_text.strip():
            self.settings_step_help.setText(help_text)
        else:
            self.settings_step_help.setText(" ")
        self.settings_back_button.setEnabled(self.settings_step_index > 0)
        is_last = self._next_visible_settings_index(self.settings_step_index) == self.settings_step_index
        self.settings_next_button.setVisible(not is_last)
        self.settings_done_button.setVisible(True)
        self.settings_advanced_button.setVisible(self.settings_step_index == 3)
        self._refresh_settings_progress_line()
        if title == "Review Choices":
            self._refresh_prompt_preview()
            self._refresh_settings_summary()
        elif title == "Set Signature" and not self.gmail_signature_import_attempted:
            self.gmail_signature_import_attempted = True
            QTimer.singleShot(0, lambda: self._import_gmail_signature(force=False))

    def _import_gmail_signature(self, *, force: bool) -> None:
        if not hasattr(self, "signature_input") or not hasattr(self, "gmail_signature_status"):
            return
        if not self.gmail_enabled.isChecked():
            self.gmail_signature_status.setText("Enable Gmail first, then MailAssist can try importing its saved signature.")
            return
        if not force and self.signature_input.toPlainText().strip():
            self.gmail_signature_status.setText("Using your saved MailAssist signature. Use Import from Gmail to replace it.")
            return
        self.gmail_signature_status.setText("Checking Gmail for a saved signature...")
        provider = GmailProvider(
            Path(self.gmail_credentials_input.text().strip()),
            Path(self.gmail_token_input.text().strip()),
        )
        try:
            result = provider.get_default_signature(allow_interactive_auth=force)
        except Exception as exc:
            self.gmail_signature_status.setText(str(exc))
            return
        if result is None:
            self.gmail_signature_status.setText("No Gmail signature was found. You can type one here.")
            return
        if result.signature_html:
            self.signature_input.setHtml(result.signature_html)
        else:
            self.signature_input.setPlainText(result.signature)
        source = f" from {result.send_as_email}" if result.send_as_email else ""
        self.gmail_signature_status.setText(
            f"Imported Gmail signature{source}. You can edit it before continuing."
        )

    def _refresh_settings_progress_line(self) -> None:
        if not hasattr(self, "settings_progress_buttons"):
            return
        stops = self._settings_progress_stops()
        routes = [step_index for _label, step_index in stops]
        current_route = self._settings_progress_route_index(self.settings_step_index)
        try:
            current_position = routes.index(current_route)
        except ValueError:
            current_position = 0
        for position, (button, _step_index) in enumerate(self.settings_progress_buttons):
            if position < current_position:
                button.setStyleSheet(
                    "QPushButton { background: #e6f1ec; border: 1px solid #a9cfc0; border-radius: 13px; "
                    "color: #215f4a; font-weight: 700; padding: 3px 5px; }"
                    "QPushButton:hover { background: #d5eadf; }"
                )
            elif position == current_position:
                button.setStyleSheet(
                    "QPushButton { background: #1e7a61; border: 1px solid #1e7a61; border-radius: 13px; "
                    "color: #ffffff; font-weight: 800; padding: 3px 5px; }"
                    "QPushButton:hover { background: #17664f; }"
                )
            else:
                button.setStyleSheet(
                    "QPushButton { background: #fffaf4; border: 1px solid #dfc7ad; border-radius: 13px; "
                    "color: #8a7461; font-weight: 650; padding: 3px 5px; }"
                    "QPushButton:hover { background: #f5e5d1; }"
                )
        for position, segment in enumerate(self.settings_progress_segments):
            color = "#1e7a61" if position < current_position else "#dfc7ad"
            segment.setStyleSheet(f"background: {color}; border-radius: 1px;")

    def _refresh_setup_visibility(self) -> None:
        if not hasattr(self, "control_group"):
            return
        self.settings_button.setVisible(True)
        self.control_group.setVisible(True)
        self.activity_group.setVisible(True)

    def _next_settings_step(self) -> None:
        self.save_settings(announce=False)
        if self.settings_steps[self.settings_step_index][0] == "Advanced Settings?":
            self.advanced_settings_enabled = self.advanced_settings_checkbox.isChecked()
        if self.settings_step_index == 3:
            self.review_previous_step_index = 3
            self._show_settings_step(5)
            return
        if self.settings_step_index == 4:
            self.review_previous_step_index = 4
        self._show_settings_step(self._next_visible_settings_index(self.settings_step_index))

    def _previous_settings_step(self) -> None:
        self.save_settings(announce=False)
        if self.settings_step_index == 5:
            self._show_settings_step(self.review_previous_step_index)
            return
        self._show_settings_step(self._previous_visible_settings_index(self.settings_step_index))

    def _open_advanced_settings_step(self) -> None:
        self.save_settings(announce=False)
        self.review_previous_step_index = 4
        self._show_settings_step(4)

    def _next_visible_settings_index(self, current_index: int) -> int:
        index = current_index + 1
        while index < len(self.settings_steps):
            if self.advanced_settings_enabled or not self.settings_steps[index][2]:
                return index
            index += 1
        return len(self.settings_steps) - 1

    def _previous_visible_settings_index(self, current_index: int) -> int:
        index = current_index - 1
        while index >= 0:
            if self.advanced_settings_enabled or not self.settings_steps[index][2]:
                return index
            index -= 1
        return 0

    def _visible_settings_indices(self) -> list[int]:
        return [
            index
            for index, (_title, _help_text, advanced) in enumerate(self.settings_steps)
            if self.advanced_settings_enabled or not advanced
        ]

    def _refresh_settings_summary(self) -> None:
        if not hasattr(self, "settings_summary"):
            return
        selected_model = str(self.ollama_model_picker.currentData() or self.settings.ollama_model)
        provider = self._selected_provider()
        enabled_providers = self._enabled_provider_label()
        signature_state = "Configured" if self.signature_input.toPlainText().strip() else "Missing"
        attribution_label = (
            self.attribution_placement_combo.currentText()
            if hasattr(self, "attribution_placement_combo")
            else "Hide"
        )
        lines = [
            "MailAssist will use these settings:",
            "",
            f"Email providers: {enabled_providers}",
            f"Active provider: {provider.title()}",
            f"Local AI model: {selected_model}",
            f"Default tone: {self.tone_combo.currentText()}",
            f"Signature: {signature_state}",
            f"Attribution: {attribution_label}",
            f"Watcher filter: {self._watcher_filter_label()}",
            "",
            "MailAssist will watch for new mail and prepare drafts for messages that need a reply.",
            "",
            "Prompt preview (read-only)",
            "",
            self._prompt_preview_text(),
        ]
        self.settings_summary.setPlainText("\n".join(lines))

    def _refresh_ollama_model_hint(self) -> None:
        if not hasattr(self, "ollama_model_hint"):
            return
        model = str(self.ollama_model_picker.currentData() or self.settings.ollama_model)
        detail = self.ollama_model_details.get(model, {})
        size = model_size_bytes(detail)
        loaded_detail = self.loaded_ollama_model_details.get(model)
        loaded_model_names = sorted(self.loaded_ollama_model_details)
        if model.startswith("gemma4:31b"):
            message = "High quality, slower. Good for background drafting and careful wording."
        elif model.startswith("gemma3:12b"):
            message = "Fast and lightweight. Useful for quick tests, but draft quality has been less reliable."
        elif "qwen" in model.lower():
            message = "General-purpose local model. Good for experiments; compare draft quality before using live."
        elif model:
            message = "Installed local model. Use the model check before relying on it for drafts."
        else:
            message = "No model selected."
        if size and self.available_memory_bytes:
            effective_memory = effective_available_memory_bytes(
                self.available_memory_bytes,
                list(self.loaded_ollama_model_details.values()),
                list(self.ollama_model_details.values()),
                self.total_memory_bytes,
            ) or self.available_memory_bytes
            memory_budget = effective_memory * 0.75
            if loaded_detail:
                selected_memory = "This model is already loaded in Ollama, so low free RAM is expected."
            elif size <= memory_budget:
                selected_memory = "This model fits the current memory guidance."
            else:
                selected_memory = "This model may be too large for the RAM currently available."
            message = f"{message}\n\n{selected_memory}"
        if loaded_model_names:
            message = f"{message}\n\nLoaded now: {', '.join(loaded_model_names[:3])}."
        if self.model_memory_recommendation:
            message = f"{message}\n\n{self.model_memory_recommendation}"
        self.ollama_model_hint.setText(message)

    def _ollama_model_selection_changed(self) -> None:
        if not hasattr(self, "ollama_model_picker"):
            return
        self.available_memory_bytes, self.total_memory_bytes = system_memory_snapshot()
        try:
            loaded_model_details = OllamaClient(
                self.ollama_url_input.text().strip(),
                str(self.ollama_model_picker.currentData() or self.settings.ollama_model),
            ).list_loaded_model_details()
        except RuntimeError:
            loaded_model_details = list(self.loaded_ollama_model_details.values())
        self.loaded_ollama_model_details = {
            name: item for item in loaded_model_details if (name := model_name(item))
        }
        self.model_memory_recommendation = memory_recommendation_message(
            list(self.ollama_model_details.values()),
            self.available_memory_bytes,
            self.total_memory_bytes,
            loaded_model_details,
        )
        self._refresh_ollama_model_hint()
        self._refresh_settings_summary()


    def _refresh_prompt_preview(self) -> None:
        preview_text = self._prompt_preview_text()
        if hasattr(self, "prompt_preview"):
            self.prompt_preview.setPlainText(preview_text)
        if hasattr(self, "signature_attribution_preview"):
            self.signature_attribution_preview.setHtml(self._signature_attribution_preview_html())
        if hasattr(self, "settings_summary"):
            self._refresh_settings_summary()

    def _attribution_placement(self) -> str:
        if not hasattr(self, "attribution_placement_combo"):
            return self.settings.draft_attribution_placement
        return str(self.attribution_placement_combo.currentData() or ATTRIBUTION_HIDE)

    def _signature_attribution_preview_html(self) -> str:
        body = "<p>Your draft text will appear above this preview.</p>"
        signature_html = sanitize_html_fragment(self.signature_input.toHtml().strip())
        if signature_html and not html_to_plain_text(signature_html):
            signature_html = ""
        if not self.signature_input.toPlainText().strip():
            signature_html = "<p>No signature configured.</p>"
        placement = self._attribution_placement()
        attribution = attribution_html(str(self.ollama_model_picker.currentData() or self.settings.ollama_model))
        pieces = [body]
        if placement == ATTRIBUTION_ABOVE_SIGNATURE:
            pieces.append(attribution)
            pieces.append(signature_html)
        elif placement == ATTRIBUTION_BELOW_SIGNATURE:
            pieces.append(signature_html)
            pieces.append(attribution)
        else:
            pieces.append(signature_html)
        return "".join(pieces)

    def _prompt_preview_text(self) -> str:
        tone_key = str(self.tone_combo.currentData() or self.settings.user_tone)
        signature = self.signature_input.toPlainText().strip()
        return build_prompt_preview(
            tone_key=tone_key,
            signature=signature,
            user_facing=True,
        )

    def _merge_signature_format(self, fmt: QTextCharFormat) -> None:
        if not hasattr(self, "signature_input"):
            return
        cursor = self.signature_input.textCursor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        cursor.mergeCharFormat(fmt)
        self.signature_input.mergeCurrentCharFormat(fmt)
        self.signature_input.setTextCursor(cursor)
        self._refresh_prompt_preview()

    def _toggle_signature_bold(self) -> None:
        fmt = QTextCharFormat()
        weight = self.signature_input.fontWeight()
        fmt.setFontWeight(QFont.Weight.Normal if weight >= QFont.Weight.Bold else QFont.Weight.Bold)
        self._merge_signature_format(fmt)

    def _toggle_signature_italic(self) -> None:
        fmt = QTextCharFormat()
        fmt.setFontItalic(not self.signature_input.fontItalic())
        self._merge_signature_format(fmt)

    def _toggle_signature_underline(self) -> None:
        fmt = QTextCharFormat()
        fmt.setFontUnderline(not self.signature_input.fontUnderline())
        self._merge_signature_format(fmt)

    def _insert_signature_link(self) -> None:
        cursor = self.signature_input.textCursor()
        selected = cursor.selectedText().strip()
        url, accepted = QInputDialog.getText(self, "Add Link", "URL")
        cleaned_url = url.strip()
        if not accepted or not cleaned_url:
            return
        if "://" not in cleaned_url and not cleaned_url.startswith("mailto:"):
            cleaned_url = f"https://{cleaned_url}"
        link_text = selected or cleaned_url
        fmt = QTextCharFormat()
        fmt.setAnchor(True)
        fmt.setAnchorHref(cleaned_url)
        fmt.setForeground(Qt.GlobalColor.blue)
        fmt.setFontUnderline(True)
        cursor.insertText(link_text, fmt)
        self.signature_input.setTextCursor(cursor)
        self._refresh_prompt_preview()

    def _refresh_status_overlay_visibility(self) -> None:
        visible = self.banner.isVisible() or self.progress_bar.isVisible()
        self.status_overlay.setVisible(visible)

    def _set_banner(self, message: str, level: str = "info") -> None:
        if not message:
            self.banner.hide()
            self._refresh_status_overlay_visibility()
            return
        style = (
            "padding: 10px 12px; border-radius: 12px; "
            + (
                "background: rgba(33,95,74,0.12); color: #215f4a;"
                if level == "info"
                else "background: rgba(140,64,41,0.12); color: #8c4029;"
            )
        )
        self.banner.setStyleSheet(style)
        self.banner.setText(message)
        self.progress_bar.hide()
        self.active_progress_label = ""
        self.banner.show()
        self._refresh_status_overlay_visibility()

    def _append_bot_console(self, line: str) -> None:
        self.bot_console.appendPlainText(line)
        cursor = self.bot_console.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.bot_console.setTextCursor(cursor)

    def _start_indeterminate_progress(self, label: str) -> None:
        self.active_progress_label = label
        self.banner.hide()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFormat(self.active_progress_label)
        self.progress_bar.show()
        self._refresh_status_overlay_visibility()

    def _finish_indeterminate_progress(self) -> None:
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat("")
        self.progress_bar.hide()
        self.active_progress_label = ""
        self._refresh_status_overlay_visibility()

    _PILL_STYLES = {
        "ok": "background: #e6f1ec; color: #1e7a61; border: 1px solid #a9cfc0;",
        "running": "background: #fff3df; color: #8a5d2b; border: 1px solid #dfc7ad;",
        "warn": "background: #fdf3e7; color: #8a5d2b; border: 1px solid #dfc7ad;",
        "error": "background: #fbe6dd; color: #8c4029; border: 1px solid #e7b9a4;",
        "idle": "background: #eef0f4; color: #5e6978; border: 1px solid #cfd5dd;",
    }

    def _paint_status_pill(self, widget: QLabel, level: str) -> None:
        base = self._PILL_STYLES.get(level, self._PILL_STYLES["idle"])
        widget.setStyleSheet(
            f"{base} border-radius: 10px; padding: 3px 10px; font-size: 13px; font-weight: 600;"
        )

    def _set_bot_state(self, state: str, text: str | None = None) -> None:
        labels = {"idle": "Idle", "running": "Running", "error": "Error"}
        display = text if text is not None else labels.get(state, state.title())
        self.bot_status_label.setText(display)
        self._paint_status_pill(self.bot_status_label, "running" if state == "running" else state)
        self.last_bot_state = state

    def _current_bot_ollama_settings(self) -> tuple[str, str]:
        base_url = self.ollama_url_input.text().strip() or self.settings.ollama_url
        selected_model = str(self.ollama_model_picker.currentData() or self.settings.ollama_model).strip()
        return base_url, selected_model

    def _initial_window_size(self) -> tuple[int, int]:
        fallback_width, fallback_height = 1120, 680
        screen = QApplication.primaryScreen()
        if screen is None:
            return fallback_width, fallback_height
        available = screen.availableGeometry()
        width = min(fallback_width, max(900, available.width() - 120))
        height = min(fallback_height, max(620, available.height() - 120))
        return width, height

    def refresh_dashboard(self) -> None:
        if not hasattr(self, "provider_status_label"):
            return
        self._refresh_provider_health()
        provider_text, provider_level = self.provider_health
        self.provider_status_label.setText(provider_text or self.settings.default_provider)
        self._paint_status_pill(self.provider_status_label, provider_level)

        ollama_text, ollama_level = self.ollama_health
        model = self.settings.ollama_model or "no model"
        self.ollama_status_label.setText(f"{model} — {ollama_text}" if ollama_text else model)
        self._paint_status_pill(self.ollama_status_label, ollama_level)

        self.tone_status_label.setText(tone_label(self.settings.user_tone))
        self.signature_status_label.setText(
            "Configured" if self.settings.user_signature.strip() else "Missing"
        )
        self.watcher_filter_status_label.setText(self._watcher_filter_label())
        self.last_activity_label.setText(self.last_activity_summary)
        self.last_pass_label.setText(self.last_pass_summary or "No watch pass yet")
        self.last_failure_label.setText(self.last_failure_summary or "None")

        if self.bot_process is not None:
            self._set_bot_state("running")
        elif self.last_bot_state == "error":
            self._set_bot_state("error")
        else:
            self._set_bot_state("idle")

    def _watcher_filter_label(self) -> str:
        provider = self._selected_provider()
        unread_only, time_window = self._watcher_filter_values(provider)
        pieces = ["unread only" if unread_only else "read and unread"]
        window_labels = {
            "24h": "last 24 hours",
            "7d": "last 7 days",
            "30d": "last 30 days",
            "all": "all time",
        }
        pieces.append(window_labels.get(time_window, "all time"))
        return ", ".join(pieces)

    def _selected_provider(self) -> str:
        if hasattr(self, "gmail_enabled") and self.gmail_enabled.isChecked():
            return "gmail"
        if hasattr(self, "outlook_enabled") and self.outlook_enabled.isChecked():
            return "outlook"
        return self.settings.default_provider if self.settings.default_provider in {"gmail", "outlook"} else "gmail"

    def _enabled_provider_label(self) -> str:
        if not hasattr(self, "gmail_enabled") or not hasattr(self, "outlook_enabled"):
            return self.settings.default_provider.title()
        enabled = []
        if self.gmail_enabled.isChecked():
            enabled.append("Gmail")
        if self.outlook_enabled.isChecked():
            enabled.append("Outlook")
        return " and ".join(enabled) if enabled else "Gmail"

    def _watcher_filter_values(self, provider: str) -> tuple[bool, str]:
        if provider == "outlook":
            unread_widget = getattr(self, "outlook_watcher_unread_only_checkbox", None)
            window_widget = getattr(self, "outlook_watcher_time_window_combo", None)
            unread_default = self.settings.outlook_watcher_unread_only
            window_default = self.settings.outlook_watcher_time_window
        else:
            unread_widget = getattr(self, "gmail_watcher_unread_only_checkbox", None)
            window_widget = getattr(self, "gmail_watcher_time_window_combo", None)
            unread_default = self.settings.gmail_watcher_unread_only
            window_default = self.settings.gmail_watcher_time_window
        unread_only = unread_widget.isChecked() if unread_widget is not None else unread_default
        time_window = (
            str(window_widget.currentData() or "all")
            if window_widget is not None
            else window_default
        )
        return unread_only, time_window

    def _refresh_provider_health(self) -> None:
        provider = self.settings.default_provider
        if provider == "gmail":
            token_path = self.settings.gmail_token_file
            if token_path and Path(token_path).exists():
                self.provider_health = (f"gmail — connected", "ok")
            elif self.settings.gmail_credentials_file and Path(self.settings.gmail_credentials_file).exists():
                self.provider_health = ("gmail — sign-in pending", "warn")
            else:
                self.provider_health = ("gmail — not configured", "warn")
        else:
            self.provider_health = (f"{provider} — not yet supported", "warn")

    def _append_recent_activity(self, message: str) -> None:
        if not hasattr(self, "recent_activity"):
            return
        if self.recent_activity.toPlainText().strip() == "No bot activity yet.":
            self.recent_activity.clear()
        self.recent_activity.appendPlainText(message)
        self.last_activity_summary = message
        self.refresh_dashboard()

    def _announce_long_action(self, message: str) -> None:
        self._append_recent_activity(message)
        self._set_banner(message, level="info")

    def refresh_bot_logs(self) -> None:
        self.bot_log_selector.blockSignals(True)
        self.bot_log_selector.clear()
        log_paths = sorted(
            self.settings.bot_logs_dir.glob("*.jsonl"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in log_paths:
            self.bot_log_selector.addItem(self._bot_log_selector_label(path), str(path))
        self.bot_log_selector.blockSignals(False)
        self._refresh_summary_from_logs(log_paths)

        if self.latest_bot_log_path is not None:
            index = self.bot_log_selector.findData(str(self.latest_bot_log_path))
            if index >= 0:
                self.bot_log_selector.setCurrentIndex(index)
                self.load_selected_bot_log()
                return
        if self.bot_log_selector.count():
            self.bot_log_selector.setCurrentIndex(0)
            self.load_selected_bot_log()
        else:
            self.bot_log_viewer.clear()

    def _refresh_summary_from_logs(self, log_paths: list[Path]) -> None:
        latest_pass = ""
        latest_failure = ""
        for path in log_paths:
            events = self._read_bot_log_events(path)
            if not latest_pass:
                completed = next(
                    (event for event in reversed(events)
                     if event.get("type") == "completed" and "draft_count" in event),
                    None,
                )
                if completed:
                    when = _event_day_time_label(completed.get("timestamp"))
                    latest_pass = (
                        f"{when} · {completed.get('draft_count', 0)} drafts · "
                        f"{completed.get('skipped_count', 0)} skipped · "
                        f"{completed.get('already_handled_count', 0)} already handled"
                    )
            if not latest_failure:
                err = next(
                    (event for event in reversed(events) if event.get("type") == "error"),
                    None,
                )
                if err:
                    when = _event_day_time_label(err.get("timestamp"))
                    message = str(err.get("message") or "Bot error.").strip()
                    latest_failure = f"{when} · {message}"
            if latest_pass and latest_failure:
                break
        if latest_pass:
            self.last_pass_summary = latest_pass
        if latest_failure:
            self.last_failure_summary = latest_failure

    def _bot_log_selector_label(self, path: Path) -> str:
        events = self._read_bot_log_events(path)
        if not events:
            return path.name
        first = events[0]
        completed = next((event for event in reversed(events) if event.get("type") == "completed"), {})
        action = str(first.get("action") or path.name.removeprefix("bot-").split("-", 1)[0])
        pieces = [_event_day_time_label(first.get("timestamp")), _log_action_label(action)]
        provider = completed.get("provider")
        if provider:
            pieces.append(str(provider).title())
        if action == "watch-once" and completed:
            draft_count = int(completed.get("draft_count") or 0)
            skipped_count = int(completed.get("skipped_count") or 0)
            already_count = int(completed.get("already_handled_count") or 0)
            pieces.append(f"{draft_count} draft{'s' if draft_count != 1 else ''}")
            draft_ready_count = int(completed.get("draft_ready_count") or 0)
            if draft_ready_count:
                pieces.append(f"{draft_ready_count} dry run{'s' if draft_ready_count != 1 else ''}")
            if skipped_count:
                pieces.append(f"{skipped_count} skipped")
            if already_count:
                pieces.append(f"{already_count} already handled")
        elif action == "ollama-check":
            pieces.append("success" if completed else "running")
        elif completed and "message_count" in completed:
            pieces.append(f"{completed.get('message_count')} messages")
        elif completed and "processed_count" in completed:
            pieces.append(f"{completed.get('processed_count')} processed")
        if any(event.get("type") == "error" for event in events):
            pieces.append("error")
        return " - ".join(pieces)

    def refresh_models(self, _checked: bool = False, *, silent: bool = False) -> None:
        previous_selection = ""
        if hasattr(self, "ollama_model_picker"):
            previous_selection = str(self.ollama_model_picker.currentData() or "").strip()
        model_details, loaded_model_details, model_error = self._list_available_model_state()
        models = [str(item.get("name", "")).strip() for item in model_details if item.get("name")]
        self.ollama_model_details = {
            str(item.get("name", "")).strip(): item for item in model_details if item.get("name")
        }
        self.loaded_ollama_model_details = {
            name: item for item in loaded_model_details if (name := model_name(item))
        }
        self.available_memory_bytes, self.total_memory_bytes = system_memory_snapshot()
        self.model_memory_recommendation = ""
        if not model_error:
            self.model_memory_recommendation = memory_recommendation_message(
                model_details,
                self.available_memory_bytes,
                self.total_memory_bytes,
                loaded_model_details,
            )
        self.ollama_model_picker.blockSignals(True)
        self.ollama_model_picker.clear()
        if models:
            for model_detail in model_details:
                model = str(model_detail.get("name", "")).strip()
                if model:
                    self.ollama_model_picker.addItem(_model_display_label(model_detail), model)
            desired_model = previous_selection or self.settings.ollama_model
            picker_index = self.ollama_model_picker.findData(desired_model)
            if picker_index >= 0:
                self.ollama_model_picker.setCurrentIndex(picker_index)
        else:
            self.ollama_model_picker.addItem("No local models found", "")
        self.ollama_model_picker.blockSignals(False)
        if models:
            self.ollama_connection_status.setText(f"Connected, {len(models)} installed")
            self.ollama_connection_status.setStyleSheet("color: #215f4a; font-size: 13px;")
            self.ollama_models_hint.setText(f"Found {len(models)} installed model(s).")
            self.ollama_health = (f"connected ({len(models)})", "ok")
        else:
            self.ollama_connection_status.setText("No models found")
            self.ollama_connection_status.setStyleSheet("color: #8c4029; font-size: 13px;")
            self.ollama_models_hint.setText("No installed Ollama models were detected.")
            self.ollama_health = ("no models", "warn")
        if model_error:
            self.ollama_connection_status.setText("Not reachable")
            self.ollama_connection_status.setStyleSheet("color: #8c4029; font-size: 13px;")
            self.ollama_health = ("not reachable", "error")
            if (
                not silent
                and not self.ollama_result.toPlainText().startswith("Sending a tiny test prompt")
            ):
                self._set_ollama_result_text(model_error)
        elif not silent and not models and not self.ollama_result.toPlainText().strip():
            self.ollama_result.clear()
        self._refresh_ollama_model_hint()
        if hasattr(self, "provider_status_label"):
            ollama_text, ollama_level = self.ollama_health
            model = self.settings.ollama_model or "no model"
            self.ollama_status_label.setText(f"{model} — {ollama_text}" if ollama_text else model)
            self._paint_status_pill(self.ollama_status_label, ollama_level)

    def _list_available_model_state(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
        base_url = self.ollama_url_input.text().strip()
        selected_model = self.settings.ollama_model
        client = OllamaClient(base_url, selected_model)
        try:
            model_details = client.list_model_details()
        except RuntimeError as exc:
            return [], [], str(exc)
        try:
            loaded_model_details = client.list_loaded_model_details()
        except RuntimeError:
            loaded_model_details = []
        return model_details, loaded_model_details, ""

    def _set_ollama_result_text(self, text: str) -> None:
        self.ollama_result.setPlainText(text)
        self.ollama_result_label.show()
        self.ollama_result.show()

    def _start_ollama_test_countdown(self) -> None:
        now = time.monotonic()
        self.ollama_test_started_at = now
        self.ollama_test_deadline_at = now + 120
        self.ollama_test_countdown_timer.start()
        self._refresh_ollama_test_countdown()

    def _stop_ollama_test_countdown(self) -> None:
        self.ollama_test_countdown_timer.stop()
        self.ollama_test_deadline_at = None

    def _refresh_ollama_test_countdown(self) -> None:
        if self.ollama_test_deadline_at is None:
            return
        remaining = max(0, int(round(self.ollama_test_deadline_at - time.monotonic())))
        minutes, seconds = divmod(remaining, 60)
        if remaining:
            self.ollama_result_label.setText(
                f"Model test result - waiting, {minutes}:{seconds:02d} remaining"
            )
        else:
            self.ollama_result_label.setText("Model test result - still waiting after 2:00")

    def _ollama_test_elapsed_label(self) -> str:
        if self.ollama_test_started_at is None:
            return "0 seconds"
        return _short_duration_label(time.monotonic() - self.ollama_test_started_at)

    def save_settings(
        self,
        _checked: bool = False,
        *,
        announce: bool = True,
        mark_complete: bool = False,
    ) -> None:
        env_file = self.settings.root_dir / ".env"
        current = read_env_file(env_file)
        selected_model = str(self.ollama_model_picker.currentData() or self.settings.ollama_model).strip()
        setup_complete = "true" if mark_complete else ("true" if self.setup_finished else "false")
        provider = self._selected_provider()
        gmail_unread, gmail_window = self._watcher_filter_values("gmail")
        outlook_unread, outlook_window = self._watcher_filter_values("outlook")
        active_unread, active_window = self._watcher_filter_values(provider)
        categories = self._mailassist_category_values()
        current.update(
            {
                "MAILASSIST_OLLAMA_URL": self.ollama_url_input.text().strip() or "http://localhost:11434",
                "MAILASSIST_OLLAMA_MODEL": selected_model,
                "MAILASSIST_USER_SIGNATURE": self.signature_input.toPlainText().strip().replace("\n", "\\n"),
                "MAILASSIST_USER_SIGNATURE_HTML": self.signature_input.toHtml().strip().replace("\n", "\\n"),
                "MAILASSIST_USER_TONE": str(self.tone_combo.currentData() or "direct_concise"),
                "MAILASSIST_BOT_POLL_SECONDS": str(self.bot_poll_seconds_input.value()),
                "MAILASSIST_DEFAULT_PROVIDER": provider,
                "MAILASSIST_GMAIL_ENABLED": "true" if self.gmail_enabled.isChecked() else "false",
                "MAILASSIST_OUTLOOK_ENABLED": "true" if self.outlook_enabled.isChecked() else "false",
                "MAILASSIST_GMAIL_CREDENTIALS_FILE": self.gmail_credentials_input.text().strip(),
                "MAILASSIST_GMAIL_TOKEN_FILE": self.gmail_token_input.text().strip(),
                "MAILASSIST_GMAIL_WATCHER_UNREAD_ONLY": "true" if gmail_unread else "false",
                "MAILASSIST_GMAIL_WATCHER_TIME_WINDOW": gmail_window,
                "MAILASSIST_OUTLOOK_WATCHER_UNREAD_ONLY": "true" if outlook_unread else "false",
                "MAILASSIST_OUTLOOK_WATCHER_TIME_WINDOW": outlook_window,
                "MAILASSIST_WATCHER_UNREAD_ONLY": "true" if active_unread else "false",
                "MAILASSIST_WATCHER_TIME_WINDOW": active_window,
                "MAILASSIST_DRAFT_ATTRIBUTION": (
                    "true" if self._attribution_placement() != ATTRIBUTION_HIDE else "false"
                ),
                "MAILASSIST_DRAFT_ATTRIBUTION_PLACEMENT": self._attribution_placement(),
                "MAILASSIST_CATEGORIES": json.dumps(categories),
                "MAILASSIST_OUTLOOK_CLIENT_ID": current.get("MAILASSIST_OUTLOOK_CLIENT_ID", ""),
                "MAILASSIST_OUTLOOK_TENANT_ID": current.get("MAILASSIST_OUTLOOK_TENANT_ID", ""),
                "MAILASSIST_OUTLOOK_REDIRECT_URI": current.get(
                    "MAILASSIST_OUTLOOK_REDIRECT_URI",
                    "http://localhost:8765/outlook/callback",
                ),
                "MAILASSIST_OUTLOOK_TOKEN_FILE": current.get(
                    "MAILASSIST_OUTLOOK_TOKEN_FILE",
                    str(self.settings.outlook_token_file),
                ),
                "MAILASSIST_SETUP_COMPLETE": setup_complete,
            }
        )
        write_env_file(env_file, current)
        self.settings = load_settings()
        if mark_complete:
            self.setup_finished = True
            self.settings_open = False
        self.refresh_models()
        self.refresh_dashboard()
        self._refresh_prompt_preview()
        self._refresh_setup_visibility()
        if announce:
            self._set_banner("Settings saved.", level="info")

    def finish_settings_wizard(self) -> None:
        self.save_settings(announce=True, mark_complete=True)
        if self.settings_dialog is not None:
            self.settings_dialog.close()
        self._set_banner("Settings saved. Bot controls are available.", level="info")

    def test_ollama(self) -> None:
        if self.bot_process is not None:
            self._set_banner("A bot action is already running.", level="error")
            return
        prompt = "Reply with one short sentence confirming MailAssist can use this model."
        model = str(self.ollama_model_picker.currentData() or self.settings.ollama_model)
        self._start_ollama_test_countdown()
        self._set_ollama_result_text(
            f"Sending a tiny test prompt to {model}...\n\nPrompt: {prompt}\n\nResponse: waiting..."
        )
        self._set_banner("Sending a small test prompt to Ollama. This can take a moment.", level="info")
        self.run_bot_action("ollama-check", prompt=prompt)

    def run_mock_watch_once(self) -> None:
        self.run_bot_action("watch-once", provider="mock")

    def start_watch_loop(self) -> None:
        self._announce_long_action(
            "Starting auto-check. MailAssist will keep checking in the background; "
            "drafting can take a minute when the local model is needed."
        )
        self.run_bot_action("watch-loop", provider=self._selected_provider())

    def stop_bot_action(self) -> None:
        if self.bot_process is None:
            return
        self._set_banner("Stopping bot action...", level="info")
        self.bot_process.terminate()
        if not self.bot_process.waitForFinished(1500):
            self.bot_process.kill()

    def stop_ollama_action(self) -> None:
        confirmation = QMessageBox.question(
            self,
            "Stop Ollama",
            (
                "MailAssist will force quit the local Ollama process. This can interrupt any model work "
                "currently running, and draft previews or auto-checks will fail until Ollama starts again.\n\n"
                "Continue?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            self._set_banner("Stop Ollama canceled.", level="info")
            return

        if self.bot_process is not None:
            self.stop_bot_action()
        model = str(self.settings.ollama_model or "").strip()
        if hasattr(self, "ollama_model_picker"):
            model = str(self.ollama_model_picker.currentData() or model).strip()
        self._append_recent_activity("Stopping Ollama. Any running local model work will be interrupted.")
        ok, message = self._stop_ollama_process(model)
        self._append_recent_activity(message)
        self.ollama_health = ("stopped" if ok else "stop failed", "warn" if ok else "error")
        self.refresh_dashboard()
        self._set_banner(message, level="info" if ok else "error")

    def restart_ollama_action(self) -> None:
        self._append_recent_activity("Starting Ollama server headlessly.")
        ok, message = self._start_ollama_process()
        self._append_recent_activity(message)
        self.ollama_health = ("starting" if ok else "restart failed", "warn" if ok else "error")
        self.refresh_dashboard()
        self._set_banner(message, level="info" if ok else "error")
        if ok:
            QTimer.singleShot(2500, lambda: self.refresh_models(silent=True))

    def _start_ollama_process(self) -> tuple[bool, str]:
        ollama_bin = shutil.which("ollama")
        if ollama_bin:
            try:
                subprocess.Popen([ollama_bin, "serve"], **_detached_process_kwargs())
                return True, "Ollama headless start requested. Try the model test again in a few seconds."
            except Exception as exc:
                return False, f"Could not restart Ollama automatically: {exc}"
        if sys.platform == "darwin":
            try:
                subprocess.Popen(["open", "-a", "Ollama"], **_detached_process_kwargs())
                return True, "Ollama app restart requested. Try the model test again in a few seconds."
            except Exception as exc:
                return False, f"Could not open the Ollama app automatically: {exc}"
        return False, "Could not restart Ollama automatically because the ollama command was not found."

    def _stop_ollama_process(self, model: str) -> tuple[bool, str]:
        commands_run: list[str] = []
        had_success = False
        errors: list[str] = []

        ollama_bin = shutil.which("ollama")
        if ollama_bin and model:
            commands_run.append(f"ollama stop {model}")
            try:
                result = subprocess.run(
                    [ollama_bin, "stop", model],
                    capture_output=True,
                    text=True,
                    timeout=8,
                    check=False,
                )
                if result.returncode == 0:
                    had_success = True
                elif result.stderr.strip():
                    errors.append(result.stderr.strip())
            except Exception as exc:
                errors.append(f"ollama stop failed: {exc}")

        for command in _ollama_force_quit_commands(sys.platform):
            commands_run.append(" ".join(command))
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                if result.returncode == 0:
                    had_success = True
                elif result.returncode not in {1, 128} and result.stderr.strip():
                    errors.append(result.stderr.strip())
            except FileNotFoundError:
                continue
            except Exception as exc:
                errors.append(f"{command[0]} failed: {exc}")

        if had_success:
            return True, "Ollama stop requested. Restart Ollama before running more model actions."
        if commands_run and not errors:
            return True, "No running Ollama process was found."
        if errors:
            return False, f"Could not stop Ollama automatically: {errors[-1]}"
        return False, "Could not stop Ollama automatically because no stop command was available."

    def run_gmail_draft_test(self) -> None:
        confirmation = QMessageBox.question(
            self,
            "Run Gmail Draft Dry Run",
            (
                "MailAssist will read Gmail and prepare one draft result without creating a real Gmail draft. "
                "Continue?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            self._set_banner("Gmail draft dry run canceled.", level="info")
            return
        self._announce_long_action(
            "Previewing a Gmail draft. MailAssist will read recent Gmail threads and ask the local model; "
            "this may take a minute, and no Gmail draft will be created."
        )
        self.run_bot_action(
            "watch-once",
            provider="gmail",
            thread_id="thread-008",
            force=True,
            dry_run=True,
        )

    def run_controlled_gmail_draft(self) -> None:
        confirmation = QMessageBox.question(
            self,
            "Create Controlled Gmail Draft",
            (
                "MailAssist will create one real Gmail draft addressed to your own Gmail account "
                "using sanitized mock content. Nothing will be sent. Continue?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            self._set_banner("Controlled Gmail draft canceled.", level="info")
            return
        self._announce_long_action(
            "Creating one controlled Gmail test draft. This may take a minute; nothing will be sent."
        )
        self.run_bot_action("gmail-controlled-draft", provider="gmail", thread_id="thread-008")

    def run_outlook_draft_preview(self) -> None:
        confirmation = QMessageBox.question(
            self,
            "Preview Outlook Draft",
            (
                "MailAssist will read recent Outlook threads and prepare draft results without "
                "creating real Outlook drafts. Nothing will be sent. Continue?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            self._set_banner("Outlook draft preview canceled.", level="info")
            return
        self.save_settings(announce=False)
        self._announce_long_action(
            "Previewing an Outlook draft. MailAssist will read recent Outlook threads and ask the local model; "
            "this may take a minute, and no Outlook draft will be created."
        )
        self.run_bot_action(
            "watch-once",
            provider="outlook",
            force=True,
            dry_run=True,
        )

    def run_gmail_label_rescan(self) -> None:
        days = int(self.gmail_label_days_input.value()) if hasattr(self, "gmail_label_days_input") else 7
        confirmation = QMessageBox.question(
            self,
            "Organize Gmail",
            (
                f"MailAssist will reclassify Gmail threads from the last {days} day"
                f"{'' if days == 1 else 's'} using the current category list. "
                "It may add, replace, or remove MailAssist labels.\n\n"
                "This can take a few minutes, but you can keep working while it runs. "
                "Continue?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            self._set_banner("Gmail label rescan canceled.", level="info")
            return
        self.save_settings(announce=False)
        self._announce_long_action(
            f"Organizing Gmail for the last {days} day{'' if days == 1 else 's'}. "
            "This can take a few minutes while the local model classifies messages."
        )
        self.run_bot_action(
            "gmail-populate-labels",
            provider="gmail",
            days=days,
            limit=500,
            apply_labels=True,
        )

    def run_outlook_category_rescan(self) -> None:
        days = (
            int(self.outlook_category_days_input.value())
            if hasattr(self, "outlook_category_days_input")
            else 25
        )
        confirmation = QMessageBox.question(
            self,
            "Organize Outlook",
            (
                f"MailAssist will classify Outlook messages from the last {days} day"
                f"{'' if days == 1 else 's'} using the current category list. "
                "It may add, replace, or remove MailAssist Outlook categories.\n\n"
                "This can take a few minutes, but you can keep working while it runs. "
                "Continue?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            self._set_banner("Outlook category rescan canceled.", level="info")
            return
        self.save_settings(announce=False)
        self._announce_long_action(
            f"Organizing Outlook for the last {days} day{'' if days == 1 else 's'}. "
            "This can take a few minutes while the local model classifies messages."
        )
        self.run_bot_action(
            "outlook-populate-categories",
            provider="outlook",
            days=days,
            apply_categories=True,
        )

    def run_bot_action(
        self,
        action: str,
        *,
        thread_id: str = "",
        prompt: str = "",
        provider: str = "",
        force: bool = False,
        dry_run: bool = False,
        days: int | None = None,
        limit: int | None = None,
        apply_labels: bool = False,
        apply_categories: bool = False,
    ) -> None:
        if self.bot_process is not None:
            self._set_banner("A bot action is already running.", level="error")
            return

        base_url, selected_model = self._current_bot_ollama_settings()
        self.bot_stdout_buffer = ""
        self.current_bot_action = action
        self.bot_process = QProcess(self)
        self.bot_process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.bot_process.setWorkingDirectory(str(self.settings.root_dir))
        self.bot_process.readyReadStandardOutput.connect(self._handle_bot_stdout)
        self.bot_process.finished.connect(self._handle_bot_finished)

        args = [
            "-u",
            "-m",
            "mailassist.cli.main",
            "review-bot",
            "--action",
            action,
            "--base-url",
            base_url,
            "--selected-model",
            selected_model,
        ]
        if thread_id:
            args.extend(["--thread-id", thread_id])
        if prompt:
            args.extend(["--prompt", prompt])
        if provider:
            args.extend(["--provider", provider])
        if force:
            args.append("--force")
        if dry_run:
            args.append("--dry-run")
        if days is not None:
            args.extend(["--days", str(max(1, int(days)))])
        if limit is not None:
            args.extend(["--limit", str(max(1, int(limit)))])
        if apply_labels:
            args.append("--apply-labels")
        if apply_categories:
            args.append("--apply-categories")

        self._append_bot_console(f"$ {sys.executable} {' '.join(args)}")
        self._set_banner(
            f"Starting bot action: {action}. Ollama work can take 1-2 minutes.",
            level="info",
        )
        self._set_bot_state("running")
        if hasattr(self, "stop_bot_button"):
            self.stop_bot_button.setEnabled(True)
        self.bot_process.start(sys.executable, args)

    def _handle_bot_stdout(self) -> None:
        if self.bot_process is None:
            return
        chunk = bytes(self.bot_process.readAllStandardOutput()).decode("utf-8", errors="replace")
        self.bot_stdout_buffer += chunk
        while "\n" in self.bot_stdout_buffer:
            line, self.bot_stdout_buffer = self.bot_stdout_buffer.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            self._append_bot_console(line)
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._handle_bot_event(event)

    def _handle_bot_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        if event_type == "log_file":
            self.latest_bot_log_path = Path(str(event.get("path")))
            self.refresh_bot_logs()
        elif event_type == "ollama_result":
            prompt = str(event.get("prompt", "")).strip()
            result = str(event.get("result", "")).strip()
            success = f"Test successful after {self._ollama_test_elapsed_label()}."
            self._stop_ollama_test_countdown()
            self.ollama_result_label.setText(success)
            if prompt:
                self._set_ollama_result_text(f"{success}\n\nPrompt: {prompt}\n\nResponse: {result}")
            else:
                self._set_ollama_result_text(f"{success}\n\nResponse: {result}")
            self._set_banner(success, level="info")
        elif event_type == "draft_created":
            self._append_recent_activity(
                f"Draft created: {event.get('subject', 'Unknown subject')} ({event.get('classification', 'unclassified')})"
            )
        elif event_type == "draft_ready":
            self._append_recent_activity(
                f"Draft dry run ready: {event.get('subject', 'Unknown subject')} ({event.get('classification', 'unclassified')})"
            )
        elif event_type == "skipped_email":
            self._append_recent_activity(
                f"Skipped: {event.get('subject', 'Unknown subject')} ({event.get('classification', 'unclassified')})"
            )
        elif event_type == "already_handled":
            self._append_recent_activity(
                f"Already handled: {event.get('subject', 'Unknown subject')}"
            )
        elif event_type == "filtered_out":
            self._append_recent_activity(
                f"Filtered out: {event.get('subject', 'Unknown subject')} ({event.get('reason', 'filter')})"
            )
        elif event_type == "watch_pass_started":
            self._append_recent_activity(f"Watch pass started for {event.get('provider', 'provider')}.")
        elif event_type == "watch_pass_completed":
            self._append_recent_activity(f"Watch pass completed for {event.get('provider', 'provider')}.")
        elif event_type == "failed_pass":
            self._append_recent_activity(f"Watch pass failed: {event.get('message', 'Unknown error')}")
        elif event_type == "completed":
            if event.get("action") != "ollama-check":
                self._set_banner(str(event.get("message", "Bot action completed.")), level="info")
            self.settings = load_settings()
            self.refresh_models()
            self.refresh_bot_logs()
            if "draft_count" in event:
                draft_count = event.get("draft_count", 0)
                draft_ready_count = event.get("draft_ready_count", 0)
                skipped_count = event.get("skipped_count", 0)
                already_count = event.get("already_handled_count", 0)
                filtered_count = event.get("filtered_out_count", 0)
                self.last_pass_summary = (
                    f"{draft_count} drafts · {draft_ready_count} dry runs · {skipped_count} skipped · "
                    f"{already_count} already handled · {filtered_count} filtered"
                )
                self._append_recent_activity(f"Watch pass: {self.last_pass_summary}.")
            self.refresh_dashboard()
        elif event_type == "error":
            failure = str(event.get("message", "Bot action failed."))
            if event.get("action") == "ollama-check":
                self._stop_ollama_test_countdown()
                self.ollama_result_label.setText(
                    f"Model test failed after {self._ollama_test_elapsed_label()}."
                )
            self.last_failure_summary = failure
            self._set_banner(failure, level="error")
            self._set_bot_state("error")
        elif event_type == "info":
            self._set_banner(str(event.get("message", "")), level="info")

    def _handle_bot_finished(self, exit_code: int, _exit_status) -> None:
        if self.bot_stdout_buffer.strip():
            self._append_bot_console(self.bot_stdout_buffer.strip())
            self.bot_stdout_buffer = ""
        finished_action = self.current_bot_action
        self.bot_process = None
        if hasattr(self, "stop_bot_button"):
            self.stop_bot_button.setEnabled(False)
        if exit_code != 0:
            if finished_action == "ollama-check":
                self._stop_ollama_test_countdown()
                self.ollama_result_label.setText(
                    f"Model test failed after {self._ollama_test_elapsed_label()}."
                )
            failure = f"Bot exited with code {exit_code}."
            self.last_failure_summary = failure
            self._set_banner(failure, level="error")
            self._set_bot_state("error")
        elif self.last_bot_state != "error":
            if finished_action == "ollama-check":
                self._stop_ollama_test_countdown()
            self._set_bot_state("idle")
        self.current_bot_action = ""
        self.refresh_dashboard()
        self.refresh_bot_logs()

    def load_selected_bot_log(self, *_args: object) -> None:
        log_path_value = self.bot_log_selector.currentData()
        if not log_path_value:
            self.bot_log_viewer.clear()
            return
        log_path = Path(str(log_path_value))
        if not log_path.exists():
            self.bot_log_viewer.clear()
            self._set_banner("The selected bot log no longer exists.", level="error")
            return
        raw_text = log_path.read_text(encoding="utf-8")
        if self.show_raw_log_checkbox.isChecked():
            self.bot_log_viewer.setPlainText(raw_text)
            return
        self.bot_log_viewer.setPlainText(self._format_bot_log_for_humans(log_path, raw_text))

    def _read_bot_log_events(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        return self._parse_bot_log_events(path.read_text(encoding="utf-8"))

    def _parse_bot_log_events(self, raw_text: str) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for line in raw_text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                events.append(parsed)
        return events

    def _format_bot_log_for_humans(self, path: Path, raw_text: str) -> str:
        events = self._parse_bot_log_events(raw_text)
        if not events:
            return f"No readable events were found in {path.name}."

        first = events[0]
        completed = next((event for event in reversed(events) if event.get("type") == "completed"), None)
        errors = [event for event in events if event.get("type") == "error" or event.get("generation_error")]
        action = str(first.get("action") or "")
        title = _log_action_label(action)
        started_at = first.get("timestamp")
        finished_at = completed.get("timestamp") if completed else None
        duration = self._log_duration_label(started_at, finished_at)

        lines = [
            f"{_event_day_time_label(started_at)} - {title}",
            "",
            "Summary",
            f"Started: {_event_time_label(started_at)}",
        ]
        if completed:
            lines.append(f"Finished: {_event_time_label(finished_at)}{f' ({duration})' if duration else ''}")
        else:
            lines.append("Finished: not yet")
        lines.extend(self._bot_log_summary_lines(action, events, completed, errors))
        if errors:
            lines.extend(["", "Needs Attention"])
            lines.extend(f"- {self._event_human_message(event)}" for event in errors)
        lines.extend(["", "Timeline"])
        for event in events:
            if event.get("type") == "log_file":
                continue
            lines.append(f"{_event_time_label(event.get('timestamp'))}  {self._event_human_message(event)}")
        lines.extend(["", f"Raw log file: {path}"])
        return "\n".join(lines)

    def _log_duration_label(self, started_at: object, finished_at: object) -> str:
        start = _parse_event_timestamp(started_at)
        finish = _parse_event_timestamp(finished_at)
        if start is None or finish is None:
            return ""
        seconds = max(0, int((finish - start).total_seconds()))
        if seconds < 60:
            return f"{seconds} seconds"
        minutes, remainder = divmod(seconds, 60)
        return f"{minutes} min {remainder} sec" if remainder else f"{minutes} min"

    def _bot_log_summary_lines(
        self,
        action: str,
        events: list[dict[str, Any]],
        completed: dict[str, Any] | None,
        errors: list[dict[str, Any]],
    ) -> list[str]:
        lines: list[str] = []
        started = events[0]
        arguments = started.get("arguments") if isinstance(started.get("arguments"), dict) else {}
        provider = (completed or {}).get("provider") or arguments.get("provider")
        model = (completed or {}).get("selected_model") or arguments.get("selected_model")
        if provider and action != "ollama-check":
            lines.append(f"Provider: {str(provider).title()}")
        if model:
            lines.append(f"Model: {model}")
        if completed:
            for key, label in (
                ("draft_count", "Drafts created"),
                ("skipped_count", "Skipped"),
                ("already_handled_count", "Already handled"),
                ("filtered_out_count", "Filtered out"),
                ("message_count", "Messages read"),
            ):
                if key in completed:
                    lines.append(f"{label}: {completed.get(key)}")
        lines.append(f"Result: {'Error' if errors else 'OK'}")
        return lines

    def _event_human_message(self, event: dict[str, Any]) -> str:
        event_type = str(event.get("type") or "")
        message = str(event.get("message") or "").strip()
        subject = str(event.get("subject") or "").strip()
        classification = str(event.get("classification") or "").strip()
        if event_type == "started":
            return f"Started {_log_action_label(str(event.get('action') or 'bot action'))}."
        if event_type == "log_file":
            return "Opened the run log file."
        if event_type == "info":
            return message or "Information event."
        if event_type == "draft_created":
            detail = f'Created draft for "{subject}".' if subject else "Created draft."
            if classification:
                detail += f" Classification: {_humanize(classification)}."
            provider_draft_id = event.get("provider_draft_id")
            if provider_draft_id:
                detail += f" Draft ID: {provider_draft_id}."
            return detail
        if event_type == "already_handled":
            return f'Already handled "{subject}".' if subject else "Already handled an email."
        if event_type == "skipped_email":
            return message or (f'Skipped "{subject}".' if subject else "Skipped an email.")
        if event_type == "filtered_out":
            reason = str(event.get("reason") or "filter")
            return f'Filtered out "{subject}" by {reason}.' if subject else f"Filtered out an email by {reason}."
        if event_type == "gmail_message_preview":
            sender = event.get("sender") or event.get("from") or "unknown sender"
            return f'Previewed Gmail message "{subject or event.get("snippet", "")}" from {sender}.'
        if event_type == "ollama_result":
            result = str(event.get("result") or "").strip()
            return f"Ollama replied: {result}" if result else "Ollama returned an empty reply."
        if event_type == "completed":
            return message or "Completed."
        if event_type == "error":
            return message or "Error."
        if event.get("generation_error"):
            return f"Draft generation error: {event.get('generation_error')}"
        return message or _humanize(event_type)


def run_desktop_gui() -> int:
    app = QApplication.instance() or QApplication([])
    window = MailAssistDesktopWindow()
    window.show()
    return app.exec()
