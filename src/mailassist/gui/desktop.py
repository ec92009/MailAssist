from __future__ import annotations

import html
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any

from PySide6.QtCore import QProcess, QProcessEnvironment, Qt, QTimer
from PySide6.QtGui import QFont, QIcon, QKeySequence, QShortcut, QTextCharFormat, QTextCursor, QTextOption
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QPlainTextEdit,
    QTextEdit,
    QFrame,
    QSizePolicy,
    QGridLayout,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from mailassist.config import (
    APPEARANCE_DAY,
    APPEARANCE_NIGHT,
    APPEARANCE_SYSTEM,
    ATTRIBUTION_ABOVE_SIGNATURE,
    ATTRIBUTION_BELOW_SIGNATURE,
    ATTRIBUTION_HIDE,
    LOCKED_NEEDS_REPLY_CATEGORY,
    load_settings,
    read_env_file,
    write_env_file,
)
from mailassist.contacts import ElderContact, parse_elder_contacts, save_elder_contacts
from mailassist.background_bot import TONE_OPTIONS, build_prompt_preview, tone_label
from mailassist.version import load_visible_version
from mailassist.models import utc_now_iso
from mailassist.llm.ollama import OllamaClient
from mailassist.providers.gmail import GmailProvider
from mailassist.gui.recent_activity import EMPTY_ACTIVITY_TEXT, RecentActivityPanel
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


def _elder_contacts_to_text(contacts: tuple[ElderContact, ...]) -> str:
    lines = []
    for contact in contacts:
        if contact.comment:
            lines.append(f"{contact.email} | {contact.comment}")
        else:
            lines.append(contact.email)
    return "\n".join(lines)


def _elder_contact_display(contact: ElderContact) -> str:
    if contact.comment:
        return f"{contact.email} | {contact.comment}"
    return contact.email


def _elder_contact_text_to_payload(text: str) -> dict[str, str]:
    email, separator, comment = text.strip().partition("|")
    return {
        "email": email.strip(),
        "comment": comment.strip() if separator else "",
    }


def _wide_line_edit(value: str = "", *, min_width: int = 560) -> QLineEdit:
    field = QLineEdit(value)
    field.setMinimumWidth(min_width)
    field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return field


def _wrapped_tooltip(text: str, *, width: int = 320) -> str:
    escaped = html.escape(" ".join(text.split()))
    return f'<qt><div style="white-space: normal; width: {width}px;">{escaped}</div></qt>'


def _user_facing_failure_message(message: str) -> str:
    if message.strip() == "invalid_grant":
        return (
            "Outlook sign-in expired or was revoked (invalid_grant). "
            "Run Outlook setup/auth again before previewing Outlook drafts."
        )
    return message


def _is_organizer_action(action: str) -> bool:
    return action in {"gmail-populate-labels", "outlook-populate-categories"}


def _organizer_stop_message(provider_label: str, reason: str, *, categorized: int, stage: str = "") -> str:
    if categorized > 0:
        return f"{provider_label} organize stopped after {categorized} emails categorized: {reason}"
    if stage:
        return f"{provider_label} organize stopped {stage}: {reason}"
    return f"{provider_label} organize stopped before the first category: {reason}"


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
        self.appearance = self.settings.appearance
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
        self.last_bot_error_label = ""
        self.gmail_signature_import_attempted = False
        self.review_previous_step_index = 3
        setup_value = read_env_file(self.settings.root_dir / ".env").get("MAILASSIST_SETUP_COMPLETE", "false")
        self.setup_finished = setup_value.strip().lower() == "true"
        self.settings_open = False
        self.settings_dialog: QDialog | None = None
        self.current_bot_action = ""
        self.current_bot_provider = ""
        self.current_bot_dry_run = False
        self.current_bot_phase = ""
        self.last_live_progress_summary = ""
        self.current_provider_ready = True
        self.current_provider_readiness_message = ""
        self.bot_progress: dict[str, int] = {}
        self.bot_action_started_at: float | None = None
        self.bot_busy_cursor_active = False
        self.last_removed_mailassist_category: tuple[str, int] | None = None
        self.last_removed_elder_contact: tuple[ElderContact, int] | None = None
        self.bot_heartbeat_timer = QTimer(self)
        self.bot_heartbeat_timer.setInterval(10000)
        self.bot_heartbeat_timer.timeout.connect(self._append_bot_heartbeat)
        self.bot_timeout_timer = QTimer(self)
        self.bot_timeout_timer.setSingleShot(True)
        self.bot_timeout_timer.timeout.connect(self._stop_bot_after_timeout)
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

    def _resolved_appearance(self) -> str:
        if self.appearance != APPEARANCE_SYSTEM:
            return self.appearance
        try:
            color_scheme = QApplication.styleHints().colorScheme()
            if color_scheme == Qt.ColorScheme.Dark:
                return APPEARANCE_NIGHT
            if color_scheme == Qt.ColorScheme.Light:
                return APPEARANCE_DAY
        except Exception:
            pass
        palette = QApplication.palette()
        return APPEARANCE_NIGHT if palette.window().color().lightness() < 128 else APPEARANCE_DAY

    def _theme_colors(self) -> dict[str, str]:
        if self._resolved_appearance() == APPEARANCE_NIGHT:
            return {
                "root_bg": "#18202a",
                "workspace_bg": "#202a36",
                "nav_bg": "#111821",
                "nav_border": "#2f3b49",
                "panel_bg": "#26313f",
                "panel_border": "#3d4b5b",
                "card_bg": "#202b39",
                "card_border": "#4a5b70",
                "field_bg": "#1c2530",
                "field_border": "#4a596b",
                "text": "#eef3f7",
                "muted": "#a9b5c2",
                "button_bg": "#273342",
                "button_hover": "#314156",
                "button_border": "#536274",
                "disabled_bg": "#252d37",
                "disabled_text": "#7b8795",
                "accent": "#34a6a5",
                "accent_hover": "#2b908f",
                "accent_soft": "rgba(52,166,165,0.18)",
                "info_bg": "#223041",
                "info_text": "#c7d2df",
                "info_border": "#43566d",
                "success_bg": "#153a34",
                "success_text": "#7ee2c9",
                "success_border": "#327e70",
                "warn_bg": "#3d321e",
                "warn_text": "#f3c87a",
                "warn_border": "#806334",
                "error_bg": "#472b28",
                "error_text": "#f1aaa0",
                "error_border": "#8e5149",
                "idle_bg": "#2e3846",
                "idle_text": "#b8c3ce",
                "idle_border": "#566373",
            }
        return {
            "root_bg": "#dfe4ea",
                "workspace_bg": "#e8eff4",
                "nav_bg": "#182230",
                "nav_border": "#223044",
                "panel_bg": "#ffffff",
                "panel_border": "#b8c7d5",
                "card_bg": "#f6f9fc",
                "card_border": "#b2c1d0",
                "field_bg": "#ffffff",
                "field_border": "#aebdcc",
            "text": "#172233",
            "muted": "#5d6b7c",
            "button_bg": "#ffffff",
            "button_hover": "#eef6fb",
            "button_border": "#b9c4cf",
            "disabled_bg": "#edf0f2",
            "disabled_text": "#9aa4af",
            "accent": "#137c8b",
            "accent_hover": "#0f6976",
            "accent_soft": "rgba(19,124,139,0.12)",
            "info_bg": "#fff4df",
            "info_text": "#536273",
            "info_border": "#e3c47c",
            "success_bg": "#e5f5ef",
            "success_text": "#04765c",
            "success_border": "#9bd4c4",
            "warn_bg": "#fff4df",
            "warn_text": "#94661b",
            "warn_border": "#e3c47c",
            "error_bg": "#fae8e4",
            "error_text": "#9a4036",
            "error_border": "#e0aaa3",
            "idle_bg": "#eef2f6",
            "idle_text": "#536273",
            "idle_border": "#c7d0da",
        }

    def _apply_app_theme(self) -> None:
        colors = self._theme_colors()
        self.setStyleSheet(
            f"""
            QMainWindow, QWidget#appRoot {{
                background: {colors["root_bg"]};
                color: {colors["text"]};
            }}
            QFrame#navRail {{
                background: {colors["nav_bg"]};
                border-right: 1px solid {colors["nav_border"]};
            }}
            QFrame#dashboardCard {{
                background: {colors["card_bg"]};
                border: 1px solid {colors["card_border"]};
                border-radius: 8px;
            }}
            QWidget#mainWorkspace {{
                background: {colors["workspace_bg"]};
            }}
            QGroupBox {{
                background: {colors["panel_bg"]};
                border: 1px solid {colors["panel_border"]};
                border-radius: 8px;
                margin-top: 10px;
                padding: 10px;
                color: {colors["text"]};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: {colors["muted"]};
                font-weight: 700;
            }}
            QLabel {{
                color: {colors["text"]};
            }}
            QPushButton {{
                background: {colors["button_bg"]};
                border: 1px solid {colors["button_border"]};
                border-radius: 8px;
                color: {colors["text"]};
                padding: 6px 11px;
            }}
            QPushButton:hover {{
                background: {colors["button_hover"]};
            }}
            QPushButton:checked {{
                background: {colors["accent"]};
                border: 1px solid {colors["accent"]};
                color: #ffffff;
                font-weight: 700;
            }}
            QPushButton:disabled {{
                background: {colors["disabled_bg"]};
                color: {colors["disabled_text"]};
            }}
            QPushButton#navButton {{
                background: transparent;
                border: 0;
                border-radius: 8px;
                color: #bdc8d6;
                font-weight: 650;
                padding: 8px 10px;
                text-align: left;
            }}
            QPushButton#navButton:hover {{
                background: rgba(255,255,255,0.08);
            }}
            QPushButton#navButton:checked {{
                background: {colors["accent"]};
                color: #ffffff;
            }}
            QLineEdit, QComboBox, QPlainTextEdit, QTextEdit, QListWidget, QSpinBox {{
                background: {colors["field_bg"]};
                border: 1px solid {colors["field_border"]};
                border-radius: 8px;
                color: {colors["text"]};
                padding: 5px;
                selection-background-color: {colors["accent"]};
            }}
            QComboBox {{
                min-width: 260px;
            }}
            QComboBox QAbstractItemView, QListView#comboPopup {{
                background: {colors["field_bg"]};
                border: 1px solid {colors["field_border"]};
                color: {colors["text"]};
                selection-background-color: {colors["accent"]};
                selection-color: #ffffff;
                outline: 0;
            }}
            QComboBox QAbstractItemView::item, QListView#comboPopup::item {{
                min-height: 28px;
                padding: 4px 10px;
            }}
            QComboBox QAbstractItemView::item:hover, QListView#comboPopup::item:hover {{
                background: {colors["button_hover"]};
                color: {colors["text"]};
            }}
            QComboBox QAbstractItemView::item:selected, QListView#comboPopup::item:selected {{
                background: {colors["accent"]};
                color: #ffffff;
            }}
            QComboBox::drop-down {{
                border: 0;
                width: 30px;
            }}
            QToolButton {{
                background: {colors["button_bg"]};
                border: 1px solid {colors["button_border"]};
                border-radius: 8px;
                color: {colors["text"]};
                padding: 5px 9px;
            }}
            QToolButton:hover {{
                background: {colors["button_hover"]};
            }}
            QToolButton:disabled {{
                background: {colors["disabled_bg"]};
                color: {colors["disabled_text"]};
            }}
            QCheckBox {{
                color: {colors["text"]};
                spacing: 8px;
            }}
            QCheckBox:disabled {{
                color: {colors["disabled_text"]};
            }}
            QDialog {{
                background: {colors["workspace_bg"]};
                color: {colors["text"]};
            }}
            QScrollBar:vertical {{
                background: {colors["field_bg"]};
                border: 0;
                width: 12px;
                margin: 2px;
            }}
            QScrollBar::handle:vertical {{
                background: {colors["button_border"]};
                border-radius: 5px;
                min-height: 28px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
            }}
            QScrollBar:horizontal {{
                background: {colors["field_bg"]};
                border: 0;
                height: 12px;
                margin: 2px;
            }}
            QScrollBar::handle:horizontal {{
                background: {colors["button_border"]};
                border-radius: 5px;
                min-width: 28px;
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0;
            }}
            """
        )
        self._refresh_theme_dependent_widgets()

    def _combo_popup_style(self) -> str:
        colors = self._theme_colors()
        return (
            f"QListView#comboPopup {{ background: {colors['field_bg']}; "
            f"border: 1px solid {colors['field_border']}; color: {colors['text']}; "
            f"selection-background-color: {colors['accent']}; selection-color: #ffffff; outline: 0; }}"
            f"QListView#comboPopup::item {{ min-height: 28px; padding: 4px 10px; }}"
            f"QListView#comboPopup::item:hover {{ background: {colors['button_hover']}; color: {colors['text']}; }}"
            f"QListView#comboPopup::item:selected {{ background: {colors['accent']}; color: #ffffff; }}"
        )

    def _tool_button_style(self) -> str:
        colors = self._theme_colors()
        return (
            f"QToolButton {{ background: {colors['button_bg']}; border: 1px solid {colors['button_border']}; "
            f"border-radius: 8px; color: {colors['text']}; padding: 5px 9px; }}"
            f"QToolButton:hover {{ background: {colors['button_hover']}; }}"
            f"QToolButton:disabled {{ background: {colors['disabled_bg']}; color: {colors['disabled_text']}; }}"
        )

    def _refresh_theme_dependent_widgets(self) -> None:
        popup_style = self._combo_popup_style()
        for combo in self.findChildren(QComboBox):
            if not isinstance(combo.view(), QListView):
                combo.setView(QListView(combo))
            combo.view().setObjectName("comboPopup")
            combo.view().setStyleSheet(popup_style)
            combo.view().viewport().setStyleSheet(f"background: {self._theme_colors()['field_bg']};")
        tool_style = self._tool_button_style()
        for button in self.findChildren(QToolButton):
            button.setAutoRaise(False)
            button.setStyleSheet(tool_style)
        if hasattr(self, "ollama_connection_status"):
            self._style_ollama_connection_status()
        if hasattr(self, "stdout_label"):
            self.stdout_label.setStyleSheet(self._muted_label_style())
        if hasattr(self, "log_label"):
            self.log_label.setStyleSheet(self._muted_label_style())
        self._refresh_dashboard_contrast_styles()

    def _style_number_input(self, spin_box: QSpinBox) -> None:
        spin_box.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        spin_box.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    def _confirm_action(self, title: str, message: str) -> QMessageBox.StandardButton:
        colors = self._theme_colors()
        dialog = QDialog(self)
        dialog.setObjectName("confirmDialog")
        dialog.setModal(True)
        dialog.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        dialog.setStyleSheet(
            f"""
            QDialog#confirmDialog {{
                background: {colors['panel_bg']};
                border: 1px solid {colors['panel_border']};
                border-radius: 10px;
            }}
            QLabel#confirmTitle {{
                color: {colors['text']};
                font-size: 18px;
                font-weight: 800;
            }}
            QLabel#confirmMessage {{
                color: {colors['text']};
                font-size: 15px;
                font-weight: 650;
                line-height: 1.25;
            }}
            """
        )
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(26, 24, 26, 24)
        layout.setSpacing(18)

        title_label = QLabel(title)
        title_label.setObjectName("confirmTitle")
        layout.addWidget(title_label)

        message_label = QLabel(message)
        message_label.setObjectName("confirmMessage")
        message_label.setWordWrap(True)
        message_label.setMinimumWidth(520)
        layout.addWidget(message_label)

        actions = QHBoxLayout()
        actions.addStretch(1)
        no_button = QPushButton("No")
        yes_button = QPushButton("Yes")
        no_button.setMinimumWidth(82)
        yes_button.setMinimumWidth(82)
        result = {"button": QMessageBox.StandardButton.No}

        def choose(button: QMessageBox.StandardButton) -> None:
            result["button"] = button
            dialog.accept()

        no_button.clicked.connect(lambda: choose(QMessageBox.StandardButton.No))
        yes_button.clicked.connect(lambda: choose(QMessageBox.StandardButton.Yes))
        actions.addWidget(no_button)
        actions.addWidget(yes_button)
        layout.addLayout(actions)
        no_button.setDefault(True)
        dialog.exec()
        return result["button"]

    def _info_panel_style(self) -> str:
        colors = self._theme_colors()
        return (
            f"background: {colors['info_bg']}; border: 1px solid {colors['info_border']}; "
            f"border-radius: 8px; padding: 6px; color: {colors['info_text']};"
        )

    def _muted_label_style(self) -> str:
        return f"color: {self._theme_colors()['muted']}; font-size: 13px;"

    def _status_text_style(self, level: str) -> str:
        colors = self._theme_colors()
        color = {
            "ok": colors["success_text"],
            "warn": colors["warn_text"],
            "error": colors["error_text"],
        }.get(level, colors["muted"])
        return f"color: {color}; font-size: 13px;"

    def _style_ollama_connection_status(self) -> None:
        if not hasattr(self, "ollama_connection_status"):
            return
        _text, level = self.ollama_health
        self.ollama_connection_status.setStyleSheet(self._status_text_style(level))

    def _refresh_dashboard_contrast_styles(self) -> None:
        colors = self._theme_colors()
        title_style = f"color: {colors['muted']}; font-size: 12px; font-weight: 700;"
        for label in getattr(self, "dashboard_card_titles", []):
            label.setStyleSheet(title_style)
        plain_style = f"color: {colors['text']}; font-size: 14px;"
        for name in (
            "tone_status_label",
            "signature_status_label",
            "watcher_filter_status_label",
            "last_activity_label",
            "last_pass_label",
            "last_failure_label",
        ):
            widget = getattr(self, name, None)
            if isinstance(widget, QLabel):
                widget.setStyleSheet(plain_style)

    def _style_command_button(self, button: QPushButton) -> None:
        colors = self._theme_colors()
        button.setStyleSheet(
            f"border: 1px solid {colors['button_border']}; border-radius: 8px; "
            f"padding: 7px 11px; background: {colors['button_bg']}; color: {colors['text']};"
        )

    def _refresh_command_chrome(self) -> None:
        if not hasattr(self, "version_label"):
            return
        colors = self._theme_colors()
        self._style_appearance_switch()
        self.version_label.setStyleSheet(
            f"border: 1px solid {colors['button_border']}; border-radius: 8px; "
            f"padding: 7px 11px; color: {colors['muted']}; background: {colors['button_bg']};"
        )
        self.dashboard_subtitle.setStyleSheet(f"font-size: 12px; color: {colors['muted']};")
        self.progress_bar.setStyleSheet(
            f"QProgressBar {{ border: 1px solid {colors['panel_border']}; border-radius: 8px; "
            f"background: {colors['panel_bg']}; padding: 2px; color: {colors['text']}; }}"
            f"QProgressBar::chunk {{ background: {colors['accent']}; border-radius: 6px; }}"
        )

    def _style_appearance_switch(self) -> None:
        if not hasattr(self, "appearance_toggle"):
            return
        colors = self._theme_colors()
        self.appearance_toggle.setStyleSheet(
            f"QFrame#appearanceToggle {{ background: {colors['field_bg']}; "
            f"border: 1px solid {colors['button_border']}; border-radius: 8px; }}"
        )
        segment_base = (
            "border: 0; border-radius: 8px; margin: 2px; padding: 6px 9px; min-width: 58px; "
            f"background: transparent; color: {colors['muted']};"
        )
        checked = (
            f"QPushButton:checked {{ background: {colors['accent']}; color: #ffffff; font-weight: 800; }}"
            f"QPushButton:hover {{ background: {colors['button_hover']}; }}"
            f"QPushButton:checked:hover {{ background: {colors['accent_hover']}; color: #ffffff; }}"
        )
        self.system_toggle_button.setStyleSheet(
            f"QPushButton {{ {segment_base} }}{checked}"
        )
        self.day_toggle_button.setStyleSheet(
            f"QPushButton {{ {segment_base} }}{checked}"
        )
        self.night_toggle_button.setStyleSheet(
            f"QPushButton {{ {segment_base} }}{checked}"
        )

    def _refresh_appearance_toggle(self) -> None:
        if not hasattr(self, "system_toggle_button"):
            return
        self.system_toggle_button.setChecked(self.appearance == APPEARANCE_SYSTEM)
        self.day_toggle_button.setChecked(self.appearance == APPEARANCE_DAY)
        self.night_toggle_button.setChecked(self.appearance == APPEARANCE_NIGHT)

    def set_appearance(self, appearance: str, *, persist: bool = True) -> None:
        cleaned = (
            appearance
            if appearance in {APPEARANCE_SYSTEM, APPEARANCE_DAY, APPEARANCE_NIGHT}
            else APPEARANCE_SYSTEM
        )
        if cleaned == self.appearance and hasattr(self, "day_toggle_button"):
            self._refresh_appearance_toggle()
            return
        self.appearance = cleaned
        self._apply_app_theme()
        self._refresh_command_chrome()
        self._refresh_appearance_toggle()
        if hasattr(self, "banner") and self.banner.isVisible():
            self._set_banner(self.banner.text(), level="info")
        self._refresh_settings_progress_line()
        self.refresh_dashboard()
        if persist:
            env_file = self.settings.root_dir / ".env"
            current = read_env_file(env_file)
            current["MAILASSIST_APPEARANCE"] = self.appearance
            write_env_file(env_file, current)
            self.settings = load_settings()

    def _select_nav_item(self, label: str) -> None:
        if not hasattr(self, "nav_buttons"):
            return
        for item_label, button in self.nav_buttons.items():
            button.setChecked(item_label == label)

    def _open_settings_nav_step(self, label: str, step_index: int) -> None:
        self._show_embedded_settings(label)
        self._show_settings_step(step_index)

    def _handle_nav_click(self, label: str) -> None:
        if label == "Dashboard":
            if self.settings_open:
                self.save_settings(announce=False)
            self.settings_open = False
            self._select_nav_item(label)
            self._set_banner("")
            self.dashboard_title.setText("Dashboard")
            self.dashboard_subtitle.setText("Monitor provider access, local model health, and draft activity.")
            self.main_stack.setCurrentWidget(self.dashboard_page)
            self._refresh_bot_action_controls()
            self.control_group.setFocus(Qt.FocusReason.MouseFocusReason)
            return
        if label == "Activity":
            self._show_activity_page()
            return
        settings_steps = {
            "Providers": 0,
            "Model": 1,
            "Tone": 2,
            "Signature": 3,
            "Advanced": 4,
            "Review": 5,
        }
        step_index = settings_steps.get(label)
        if step_index is not None:
            self._open_settings_nav_step(label, step_index)

    def _show_embedded_settings(self, label: str) -> None:
        self.settings_open = True
        self._select_nav_item(label)
        self.dashboard_title.setText(label)
        self.dashboard_subtitle.setText("Use the left rail to move between setup sections.")
        self.main_stack.setCurrentWidget(self.settings_wizard)
        self._refresh_bot_action_controls()

    def _show_activity_page(self) -> None:
        if self.settings_open:
            self.save_settings(announce=False)
        self.settings_open = False
        self._select_nav_item("Activity")
        self.dashboard_title.setText("Activity")
        self.dashboard_subtitle.setText("Review saved run logs, live stdout, and the selected run timeline.")
        self.main_stack.setCurrentWidget(self.activity_page)
        self.refresh_bot_logs()
        self._refresh_bot_action_controls()

    def _build_dashboard_card(self, title: str, widget: QWidget) -> QFrame:
        card = QFrame()
        card.setObjectName("dashboardCard")
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(5)
        label = QLabel(title)
        self.dashboard_card_titles = getattr(self, "dashboard_card_titles", [])
        self.dashboard_card_titles.append(label)
        label.setStyleSheet(f"color: {self._theme_colors()['muted']}; font-size: 12px; font-weight: 700;")
        layout.addWidget(label)
        if isinstance(widget, QLabel):
            widget.setWordWrap(True)
        layout.addWidget(widget)
        return card

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("appRoot")
        app_layout = QHBoxLayout(root)
        app_layout.setContentsMargins(0, 0, 0, 0)
        app_layout.setSpacing(0)
        self._apply_app_theme()

        self.nav_rail = QFrame()
        self.nav_rail.setObjectName("navRail")
        self.nav_rail.setFixedWidth(176)
        nav_layout = QVBoxLayout(self.nav_rail)
        nav_layout.setContentsMargins(14, 16, 14, 16)
        nav_layout.setSpacing(8)
        nav_title = QLabel("MailAssist")
        nav_title.setStyleSheet("font-size: 22px; font-weight: 850; color: #ffffff;")
        nav_layout.addWidget(nav_title)
        nav_subtitle = QLabel("Local draft ops")
        nav_subtitle.setStyleSheet("font-size: 12px; font-weight: 650; color: #8fa2b8;")
        nav_layout.addWidget(nav_subtitle)
        nav_layout.addSpacing(12)
        self.nav_buttons: dict[str, QPushButton] = {}
        self.nav_button_group = QButtonGroup(self)
        self.nav_button_group.setExclusive(True)
        for label, checked in (
            ("Dashboard", True),
            ("Providers", False),
            ("Model", False),
            ("Tone", False),
            ("Signature", False),
            ("Advanced", False),
            ("Review", False),
            ("Activity", False),
        ):
            button = QPushButton(label)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setChecked(checked)
            button.clicked.connect(partial(self._handle_nav_click, label))
            self.nav_buttons[label] = button
            self.nav_button_group.addButton(button)
            nav_layout.addWidget(button)
        nav_layout.addStretch(1)
        nav_status = QLabel("Drafts only\nNo sending")
        nav_status.setStyleSheet(
            "font-size: 12px; color: #8fa2b8; border-top: 1px solid #2b394a; padding-top: 10px;"
        )
        nav_layout.addWidget(nav_status)
        app_layout.addWidget(self.nav_rail)

        main_workspace = QWidget()
        main_workspace.setObjectName("mainWorkspace")
        shell = QVBoxLayout(main_workspace)
        shell.setContentsMargins(16, 14, 16, 14)
        shell.setSpacing(10)
        app_layout.addWidget(main_workspace, 1)

        command_bar = QHBoxLayout()
        command_bar.setSpacing(8)
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel("Dashboard")
        self.dashboard_title = title
        title.setStyleSheet("font-size: 22px; font-weight: 800;")
        subtitle = QLabel("Monitor provider access, local model health, and draft activity.")
        self.dashboard_subtitle = subtitle
        subtitle.setStyleSheet(f"font-size: 12px; color: {self._theme_colors()['muted']};")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        command_bar.addLayout(title_box, 1)

        self.version_label = QLabel(f"v{load_visible_version(self.settings.root_dir)}")
        self.version_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.appearance_toggle = QFrame()
        self.appearance_toggle.setObjectName("appearanceToggle")
        appearance_layout = QHBoxLayout(self.appearance_toggle)
        appearance_layout.setContentsMargins(0, 0, 0, 0)
        appearance_layout.setSpacing(0)
        self.system_toggle_button = QPushButton("System")
        self.day_toggle_button = QPushButton("Day")
        self.night_toggle_button = QPushButton("Night")
        self.appearance_button_group = QButtonGroup(self)
        self.appearance_button_group.setExclusive(True)
        for button in (self.system_toggle_button, self.day_toggle_button, self.night_toggle_button):
            button.setCheckable(True)
            button.setToolTip("Use the system appearance or choose an explicit Day/Night appearance.")
            self.appearance_button_group.addButton(button)
            appearance_layout.addWidget(button)
        self.system_toggle_button.clicked.connect(lambda: self.set_appearance(APPEARANCE_SYSTEM))
        self.day_toggle_button.clicked.connect(lambda: self.set_appearance(APPEARANCE_DAY))
        self.night_toggle_button.clicked.connect(lambda: self.set_appearance(APPEARANCE_NIGHT))
        self._style_appearance_switch()
        self._refresh_appearance_toggle()
        command_bar.addWidget(self.appearance_toggle)
        command_bar.addWidget(self.version_label)
        shell.addLayout(command_bar)

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
        self._refresh_command_chrome()
        status_layout.addWidget(self.progress_bar)

        self.banner = QLabel("")
        self.banner.hide()
        self.banner.setStyleSheet(
            "padding: 10px 12px; border-radius: 12px; background: rgba(33,95,74,0.12); color: #215f4a;"
        )
        status_layout.addWidget(self.banner)
        shell.addWidget(self.status_overlay)

        self.main_stack = QStackedWidget()
        self.main_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        shell.addWidget(self.main_stack, 1)

        self.dashboard_page = QWidget()
        dashboard_layout = QVBoxLayout(self.dashboard_page)
        dashboard_layout.setContentsMargins(0, 0, 0, 0)
        dashboard_layout.setSpacing(10)

        self.control_group = QGroupBox("Bot Control")
        control_layout = QVBoxLayout(self.control_group)
        control_layout.setContentsMargins(14, 14, 14, 14)
        control_layout.setSpacing(10)

        self.bot_status_label = QLabel("Idle")
        self.provider_status_label = QLabel(self.settings.default_provider)
        self.ollama_status_label = QLabel(self.settings.ollama_model)
        self.tone_status_label = QLabel(tone_label(self.settings.user_tone))
        self.signature_status_label = QLabel("Configured" if self.settings.user_signature.strip() else "Missing")
        self.watcher_filter_status_label = QLabel("")
        self.last_activity_label = QLabel(self.last_activity_summary)
        self.last_pass_label = QLabel("No watch pass yet")
        self.last_failure_label = QLabel("None")
        self._refresh_dashboard_contrast_styles()
        self._set_bot_state("idle")
        status_cards = QGridLayout()
        status_cards.setSpacing(8)
        for index, (label_text, widget) in enumerate(
            (
                ("Bot", self.bot_status_label),
                ("Provider", self.provider_status_label),
                ("Ollama", self.ollama_status_label),
                ("Tone", self.tone_status_label),
                ("Signature", self.signature_status_label),
                ("Watcher filter", self.watcher_filter_status_label),
                ("Last activity", self.last_activity_label),
                ("Last pass", self.last_pass_label),
                ("Last failure", self.last_failure_label),
            )
        ):
            status_cards.addWidget(self._build_dashboard_card(label_text, widget), index // 3, index % 3)
        control_layout.addLayout(status_cards)

        bot_actions = QHBoxLayout()
        bot_actions.setSpacing(6)
        self.gmail_draft_preview_button = QPushButton("Preview Gmail Draft")
        gmail_draft_test_button = self.gmail_draft_preview_button
        gmail_draft_test_button.clicked.connect(self.run_gmail_draft_test)
        gmail_draft_test_button.setToolTip(_wrapped_tooltip(
            "Read recent Gmail messages and ask the local model what it would draft. "
            "This is a dry run: MailAssist will not create a Gmail draft and will not send email. "
            "Use it to check whether Gmail access, filters, and the model are behaving before starting auto-check."
        ))
        self.outlook_draft_preview_button = QPushButton("Preview Outlook Draft")
        outlook_draft_preview_button = self.outlook_draft_preview_button
        outlook_draft_preview_button.clicked.connect(self.run_outlook_draft_preview)
        outlook_draft_preview_button.setToolTip(_wrapped_tooltip(
            "Read recent Outlook messages and ask the local model what it would draft. "
            "This is a dry run: MailAssist will not create an Outlook draft and will not send email. "
            "Use it after Outlook setup to validate classification without writing to the mailbox."
        ))
        self.gmail_label_rescan_button = QPushButton("Organize Gmail")
        gmail_label_rescan_button = self.gmail_label_rescan_button
        gmail_label_rescan_button.clicked.connect(self.run_gmail_label_rescan)
        gmail_label_rescan_button.setToolTip(_wrapped_tooltip(
            "Classify recent Gmail threads into your MailAssist categories and apply MailAssist labels. "
            "This can take several minutes because each thread may use the local model. "
            "It changes MailAssist labels only; it does not delete mail and does not send email."
        ))
        self.outlook_category_rescan_button = QPushButton("Organize Outlook")
        outlook_category_rescan_button = self.outlook_category_rescan_button
        outlook_category_rescan_button.clicked.connect(self.run_outlook_category_rescan)
        outlook_category_rescan_button.setToolTip(_wrapped_tooltip(
            "Classify recent Outlook messages into your MailAssist categories and apply Outlook categories. "
            "This can take several minutes because each message may use the local model. "
            "It changes MailAssist categories only; it does not create drafts and does not send email."
        ))
        self.gmail_label_days_input = QSpinBox()
        self._style_number_input(self.gmail_label_days_input)
        self.gmail_label_days_input.setRange(1, 30)
        self.gmail_label_days_input.setValue(7)
        self.gmail_label_days_input.setSuffix(" days")
        self.gmail_label_days_input.setMinimumWidth(92)
        self.gmail_label_days_input.setMaximumWidth(104)
        self.gmail_label_days_input.setToolTip(_wrapped_tooltip(
            "How far back Organize Gmail should look. Keep this small for quick checks; larger windows take longer."
        ))
        self.outlook_category_days_input = QSpinBox()
        self._style_number_input(self.outlook_category_days_input)
        self.outlook_category_days_input.setRange(1, 30)
        self.outlook_category_days_input.setValue(7)
        self.outlook_category_days_input.setSuffix(" days")
        self.outlook_category_days_input.setMinimumWidth(92)
        self.outlook_category_days_input.setMaximumWidth(104)
        self.outlook_category_days_input.setToolTip(_wrapped_tooltip(
            "How far back Organize Outlook should look. Keep this small for quick checks; larger windows take longer."
        ))
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
        start_watch_loop_button.setToolTip(_wrapped_tooltip(
            "Start continuous background checking for the selected provider. "
            "MailAssist periodically reads matching threads, uses the local model, and creates provider drafts only when needed. "
            "It never sends email. Stop pauses the background process."
        ))
        self.stop_bot_button = QPushButton("Stop")
        self.stop_bot_button.clicked.connect(self.stop_bot_action)
        self.stop_bot_button.setEnabled(False)
        self.stop_bot_button.setToolTip(_wrapped_tooltip(
            "Stop the currently running MailAssist action or auto-check loop. "
            "This does not delete provider drafts or undo labels/categories that were already written."
        ))
        for button in (
            gmail_draft_test_button,
            outlook_draft_preview_button,
            gmail_label_rescan_button,
            outlook_category_rescan_button,
            start_watch_loop_button,
            self.stop_bot_button,
        ):
            button.setFixedHeight(action_height)
        preview_actions = QHBoxLayout()
        preview_actions.setSpacing(6)
        preview_actions.addWidget(gmail_draft_test_button)
        preview_actions.addWidget(outlook_draft_preview_button)
        organize_actions = QHBoxLayout()
        organize_actions.setSpacing(4)
        organize_actions.addWidget(gmail_label_rescan_button)
        organize_actions.addWidget(self.gmail_label_days_input)
        organize_actions.addSpacing(6)
        organize_actions.addWidget(outlook_category_rescan_button)
        organize_actions.addWidget(self.outlook_category_days_input)
        auto_check_actions = QHBoxLayout()
        auto_check_actions.setSpacing(6)
        auto_check_actions.addWidget(start_watch_loop_button)
        auto_check_actions.addWidget(self.stop_bot_button)
        bot_actions.addLayout(preview_actions)
        bot_actions.addSpacing(8)
        bot_actions.addLayout(organize_actions)
        bot_actions.addSpacing(8)
        bot_actions.addLayout(auto_check_actions)
        bot_actions.addStretch(1)
        control_layout.addLayout(bot_actions)
        dashboard_layout.addWidget(self.control_group)

        self.activity_group = RecentActivityPanel(
            on_report=self.open_bot_logs_dialog,
            on_clear=self.clear_recent_activity,
        )
        self.activity_report_button = self.activity_group.report_button
        self.clear_recent_activity_button = self.activity_group.clear_button
        self.recent_activity = self.activity_group.text_edit
        dashboard_layout.addWidget(self.activity_group, 1)

        self.activity_page = self._build_activity_page()

        self.main_stack.addWidget(self.dashboard_page)
        self.main_stack.addWidget(self.activity_page)
        self.main_stack.addWidget(self._build_settings_wizard())
        self.main_stack.setCurrentWidget(self.dashboard_page)

        self.setCentralWidget(root)
        self._refresh_theme_dependent_widgets()
        self._refresh_setup_visibility()

    def _build_activity_page(self) -> QWidget:
        page = QWidget()
        page.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        activity_group = QGroupBox("Activity")
        activity_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        activity_layout = QVBoxLayout(activity_group)
        activity_layout.setContentsMargins(14, 14, 14, 14)
        activity_layout.addWidget(self._build_bot_panel(), 1)
        layout.addWidget(activity_group, 1)
        return page

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

        self.stdout_label = QLabel("Live stdout")
        self.stdout_label.setStyleSheet(self._muted_label_style())
        layout.addWidget(self.stdout_label)
        self.bot_console = QPlainTextEdit()
        self.bot_console.setReadOnly(True)
        self.bot_console.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.bot_console.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.bot_console.setMinimumHeight(90)
        self.bot_console.setMaximumHeight(120)
        layout.addWidget(self.bot_console)

        log_header = QHBoxLayout()
        self.log_label = QLabel("Selected log")
        self.log_label.setStyleSheet(self._muted_label_style())
        log_header.addWidget(self.log_label)
        log_header.addStretch(1)
        self.show_raw_log_checkbox = QCheckBox("Show raw JSON")
        self.show_raw_log_checkbox.toggled.connect(self.load_selected_bot_log)
        log_header.addWidget(self.show_raw_log_checkbox)
        layout.addLayout(log_header)
        self.bot_log_viewer = QPlainTextEdit()
        self.bot_log_viewer.setReadOnly(True)
        self.bot_log_viewer.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.bot_log_viewer.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.bot_log_viewer.setMinimumHeight(360)
        layout.addWidget(self.bot_log_viewer, 1)
        return widget

    def open_settings_wizard(self) -> None:
        self._open_settings_nav_step("Review", 5)

    def _build_settings_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setModal(False)
        dialog.setWindowTitle("MailAssist Settings")
        dialog.resize(900, 560)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(self._build_settings_wizard(), 1)
        dialog.finished.connect(self._settings_dialog_closed)
        self.settings_dialog = dialog

    def _settings_dialog_closed(self, _result: int = 0) -> None:
        self.settings_open = False
        self._refresh_bot_action_controls()
        self._refresh_setup_visibility()

    def open_bot_logs_dialog(self) -> None:
        self._show_activity_page()

    def _build_settings_wizard(self) -> QWidget:
        widget = QWidget()
        self.settings_wizard = widget
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(5)

        self.settings_step_label = QLabel("")
        self.settings_step_label.hide()

        self.settings_step_title = QLabel("")
        self.settings_step_title.setStyleSheet("font-size: 17px; font-weight: 800; color: #1d2430;")
        self.settings_step_title.hide()
        layout.addWidget(self.settings_step_title)

        self.settings_step_help = QLabel("")
        self.settings_step_help.setWordWrap(True)
        self.settings_step_help.setMinimumWidth(0)
        self.settings_step_help.setMinimumHeight(30)
        self.settings_step_help.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Maximum)
        self.settings_step_help.setStyleSheet(self._info_panel_style())
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
        self.settings_stack.setMinimumHeight(300)
        layout.addWidget(self.settings_stack, 1)

        self.settings_back_button = QPushButton("Back")
        self.settings_back_button.setMinimumWidth(120)
        self.settings_back_button.clicked.connect(self._previous_settings_step)
        self.settings_back_button.hide()
        self.settings_next_button = QPushButton("Next")
        self.settings_next_button.setMinimumWidth(120)
        self.settings_next_button.clicked.connect(self._next_settings_step)
        self.settings_next_button.hide()
        self.settings_done_button = QPushButton("Done")
        self.settings_done_button.setMinimumWidth(140)
        self.settings_done_button.clicked.connect(self.finish_settings_wizard)
        self.settings_done_button.hide()
        self.settings_advanced_button = QPushButton("Advanced settings")
        self.settings_advanced_button.setMinimumWidth(160)
        self.settings_advanced_button.clicked.connect(lambda _checked=False: self._open_advanced_settings_step())
        self.settings_advanced_button.hide()

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
            button.setMaximumHeight(36)
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

        provider_row = QHBoxLayout()
        provider_row.setSpacing(10)
        provider_row.addWidget(
            self._build_provider_filter_group(
                "Gmail",
                self.gmail_enabled,
                self.gmail_watcher_unread_only_checkbox,
                self.gmail_watcher_time_window_combo,
            ),
            1,
        )
        provider_row.addWidget(
            self._build_provider_filter_group(
                "Outlook",
                self.outlook_enabled,
                self.outlook_watcher_unread_only_checkbox,
                self.outlook_watcher_time_window_combo,
            ),
            1,
        )
        layout.addLayout(provider_row)
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
        group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        group.setMinimumHeight(138)
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
        confirmation = self._confirm_action(
            "Remove Category",
            f"Remove {category} from MailAssist Categories?",
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return
        self.mailassist_category_list.takeItem(index)
        self.last_removed_mailassist_category = (category, index)
        if hasattr(self, "mailassist_category_undo_button"):
            self.mailassist_category_undo_button.setEnabled(True)
        self._refresh_prompt_preview()

    def _undo_mailassist_category_removal(self) -> None:
        if not hasattr(self, "mailassist_category_list") or self.last_removed_mailassist_category is None:
            return
        category, index = self.last_removed_mailassist_category
        insert_index = min(max(index, 0), self.mailassist_category_list.count())
        self.mailassist_category_list.insertItem(insert_index, category)
        self.mailassist_category_list.setCurrentRow(insert_index)
        self.last_removed_mailassist_category = None
        if hasattr(self, "mailassist_category_undo_button"):
            self.mailassist_category_undo_button.setEnabled(False)
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
        self.mailassist_category_list.setMinimumHeight(96)
        self.mailassist_category_list.setMaximumHeight(124)
        for category in self.settings.mailassist_categories:
            self.mailassist_category_list.addItem(category)
        if self.mailassist_category_list.count():
            self.mailassist_category_list.setCurrentRow(0)

        add_button = QPushButton("Add")
        remove_button = QPushButton("Remove")
        self.mailassist_category_undo_button = QPushButton("Undo")
        add_button.setMinimumWidth(100)
        remove_button.setMinimumWidth(100)
        self.mailassist_category_undo_button.setMinimumWidth(100)
        self.mailassist_category_undo_button.setEnabled(False)
        add_button.clicked.connect(self._add_mailassist_category)
        remove_button.clicked.connect(self._remove_selected_mailassist_category)
        self.mailassist_category_undo_button.clicked.connect(self._undo_mailassist_category_removal)
        actions.addWidget(add_button)
        actions.addWidget(remove_button)
        actions.addWidget(self.mailassist_category_undo_button)
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
        note.setStyleSheet(self._muted_label_style())
        layout.addWidget(note)
        return group

    def _build_wizard_ollama_model_page(self) -> QWidget:
        widget = QWidget()
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QHBoxLayout(widget)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        model_group = QGroupBox("Local AI Model")
        self.ollama_model_group = model_group
        model_group.setMinimumHeight(400)
        model_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        model_layout = QVBoxLayout(model_group)
        model_layout.setSpacing(10)
        model_layout.setContentsMargins(18, 18, 18, 16)
        model_form = _configure_form(QFormLayout())
        self.ollama_model_picker = QComboBox()
        self.ollama_model_picker.setMinimumWidth(520)
        self.ollama_model_picker.currentIndexChanged.connect(self._ollama_model_selection_changed)
        model_form.addRow("Model", self.ollama_model_picker)
        self.ollama_connection_status = QLabel("Checking Ollama...")
        self.ollama_connection_status.setStyleSheet(self._muted_label_style())
        model_form.addRow("Status", self.ollama_connection_status)
        model_layout.addLayout(model_form)
        self.ollama_models_hint = QLabel("")
        self.ollama_models_hint.setWordWrap(True)
        self.ollama_models_hint.setStyleSheet(self._muted_label_style())
        self.ollama_models_hint.hide()
        self.ollama_model_hint = QLabel("")
        self.ollama_model_hint.setWordWrap(True)
        self.ollama_model_hint.setMinimumHeight(184)
        self.ollama_model_hint.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.ollama_model_hint.setStyleSheet(self._info_panel_style())
        model_layout.addWidget(self.ollama_model_hint)
        actions = QHBoxLayout()
        refresh_models_button = QPushButton("Refresh model list")
        refresh_models_button.setMinimumWidth(210)
        refresh_models_button.clicked.connect(self.refresh_models)
        self.test_ollama_button = QPushButton("Send small test prompt")
        test_button = self.test_ollama_button
        test_button.setMinimumWidth(230)
        test_button.clicked.connect(self.test_ollama)
        self.stop_ollama_button = QPushButton("Stop Ollama")
        self.stop_ollama_button.setMinimumWidth(130)
        self.stop_ollama_button.clicked.connect(self.stop_ollama_action)
        self.stop_ollama_button.setToolTip(_wrapped_tooltip(
            "Force quit the local Ollama process if a model is stuck or still using memory. "
            "This interrupts any current model work."
        ))
        self.restart_ollama_button = QPushButton("Start Ollama")
        self.restart_ollama_button.setMinimumWidth(150)
        self.restart_ollama_button.clicked.connect(self.restart_ollama_action)
        self.restart_ollama_button.setToolTip(_wrapped_tooltip(
            "Start the local Ollama server headlessly, then quietly refresh the installed model list."
        ))
        actions.addWidget(refresh_models_button)
        actions.addWidget(test_button)
        model_layout.addLayout(actions)
        recovery_actions = QHBoxLayout()
        recovery_actions.addWidget(self.stop_ollama_button)
        recovery_actions.addWidget(self.restart_ollama_button)
        recovery_actions.addStretch(1)
        model_layout.addLayout(recovery_actions)
        layout.addWidget(model_group, 1, Qt.AlignmentFlag.AlignTop)

        result_group = QGroupBox("Model Check")
        self.ollama_result_group = result_group
        result_group.setMinimumHeight(400)
        result_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        result_layout = QVBoxLayout(result_group)
        result_layout.setContentsMargins(18, 16, 18, 14)
        result_layout.setSpacing(8)
        self.ollama_result_label = QLabel("Model test result")
        self.ollama_result_label.setStyleSheet(self._muted_label_style())
        self.ollama_result_label.setMaximumHeight(22)
        self.ollama_result_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        result_layout.addWidget(self.ollama_result_label)
        self.ollama_result = QPlainTextEdit()
        self.ollama_result.setReadOnly(True)
        self.ollama_result.setPlainText("Send a small test prompt to see the model response here.")
        self.ollama_result.setMinimumHeight(180)
        self.ollama_result.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        result_layout.addWidget(self.ollama_result, 1)
        layout.addWidget(result_group, 1, Qt.AlignmentFlag.AlignTop)
        return widget

    def _build_wizard_writing_style_page(self) -> QWidget:
        widget = QWidget()
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QHBoxLayout(widget)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        style_group = QGroupBox("Writing Style")
        self.writing_style_group = style_group
        style_group.setMinimumHeight(186)
        style_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
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
        layout.addWidget(style_group, 1, Qt.AlignmentFlag.AlignTop)

        elders_group = QGroupBox("Relationship Guidance")
        self.relationship_guidance_group = elders_group
        elders_group.setMinimumHeight(186)
        elders_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        elders_layout = QVBoxLayout(elders_group)
        elders_layout.setContentsMargins(18, 16, 18, 14)
        elders_note = QLabel(
            "Add contacts who should receive special respect or register guidance. "
            "Only matching sender threads get this context."
        )
        elders_note.setWordWrap(True)
        elders_note.setStyleSheet(self._muted_label_style())
        elders_layout.addWidget(elders_note)
        elders_layout.addWidget(self._build_elder_contacts_editor())
        layout.addWidget(elders_group, 2, Qt.AlignmentFlag.AlignTop)
        return widget

    def _build_elder_contacts_editor(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        actions = QVBoxLayout()
        actions.setSpacing(8)
        add_button = QPushButton("Add")
        add_button.setMinimumWidth(120)
        add_button.clicked.connect(self._add_elder_contact)
        remove_button = QPushButton("Remove")
        remove_button.setMinimumWidth(120)
        remove_button.clicked.connect(self._remove_selected_elder_contact)
        self.elder_contacts_undo_button = QPushButton("Undo")
        self.elder_contacts_undo_button.setMinimumWidth(120)
        self.elder_contacts_undo_button.setEnabled(False)
        self.elder_contacts_undo_button.clicked.connect(self._undo_elder_contact_removal)
        actions.addWidget(add_button)
        actions.addWidget(remove_button)
        actions.addWidget(self.elder_contacts_undo_button)
        actions.addStretch(1)
        self.elder_contacts_list = QListWidget()
        self.elder_contacts_list.setMinimumWidth(420)
        self.elder_contacts_list.setMinimumHeight(78)
        self.elder_contacts_list.setMaximumHeight(108)
        for contact in self.settings.elder_contacts:
            self._append_elder_contact_item(contact)
        if self.elder_contacts_list.count():
            self.elder_contacts_list.setCurrentRow(0)
        layout.addLayout(actions)
        layout.addWidget(self.elder_contacts_list, 1)
        return widget

    def _build_wizard_signature_page(self) -> QWidget:
        widget = QWidget()
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QHBoxLayout(widget)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        signature_group = QGroupBox("Signature")
        signature_group.setMinimumHeight(430)
        signature_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        signature_layout = QVBoxLayout(signature_group)
        signature_layout.setContentsMargins(18, 18, 18, 16)
        signature_layout.setSpacing(10)

        self.signature_input = QTextEdit()
        if self.settings.user_signature_html.strip():
            self.signature_input.setHtml(self.settings.user_signature_html)
        else:
            self.signature_input.setPlainText(self.settings.user_signature)
        self.signature_input.setPlaceholderText("Best regards,\nYour Name")
        self.signature_input.setMinimumHeight(260)
        self.signature_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.signature_input.setAcceptRichText(True)
        self.signature_input.textChanged.connect(self._refresh_prompt_preview)

        signature_toolbar = QHBoxLayout()
        signature_toolbar.setSpacing(6)
        self.signature_toolbar_buttons: list[QToolButton] = []
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
            self.signature_toolbar_buttons.append(button)
            signature_toolbar.addWidget(button)
        signature_toolbar.addStretch(1)
        signature_layout.addLayout(signature_toolbar)
        signature_layout.addWidget(self.signature_input, 1)

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

        signature_actions = QHBoxLayout()
        import_button = QPushButton("Import from Gmail")
        import_button.clicked.connect(lambda _checked=False: self._import_gmail_signature(force=True))
        signature_actions.addWidget(import_button)
        signature_actions.addStretch(1)
        signature_layout.addLayout(signature_actions)
        self.gmail_signature_status = QLabel(
            "Import from Gmail can replace this signature."
        )
        self.gmail_signature_status.setWordWrap(True)
        self.gmail_signature_status.setMinimumHeight(34)
        self.gmail_signature_status.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.gmail_signature_status.setStyleSheet(self._muted_label_style())
        signature_layout.addWidget(self.gmail_signature_status)

        preview_group = QGroupBox("Preview")
        preview_group.setMinimumHeight(430)
        preview_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        preview_layout = QVBoxLayout(preview_group)
        preview_layout.setContentsMargins(18, 18, 18, 16)
        preview_layout.setSpacing(10)
        self.signature_attribution_preview = QTextEdit()
        self.signature_attribution_preview.setReadOnly(True)
        self.signature_attribution_preview.setAcceptRichText(True)
        self.signature_attribution_preview.setMinimumHeight(260)
        self.signature_attribution_preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        preview_layout.addWidget(self.signature_attribution_preview, 1)

        self._refresh_prompt_preview()
        layout.addWidget(signature_group, 1)
        layout.addWidget(preview_group, 1)
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
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        local_group = QGroupBox("Local Model Connection")
        local_layout = _configure_form(QFormLayout(local_group))
        self.ollama_url_input = _wide_line_edit(self.settings.ollama_url)
        local_layout.addRow("Ollama URL", self.ollama_url_input)
        refresh_button = QPushButton("Check connection and refresh models")
        refresh_button.clicked.connect(self.refresh_models)
        local_layout.addRow("", refresh_button)

        watcher_group = QGroupBox("Watcher")
        watcher_group.setMinimumHeight(186)
        watcher_layout = _configure_form(QFormLayout(watcher_group))
        self.bot_poll_seconds_input = QSpinBox()
        self._style_number_input(self.bot_poll_seconds_input)
        self.bot_poll_seconds_input.setRange(5, 3600)
        self.bot_poll_seconds_input.setSingleStep(5)
        self.bot_poll_seconds_input.setMinimumHeight(max(34, self.ollama_url_input.sizeHint().height()))
        self.bot_poll_seconds_input.setValue(max(5, int(self.settings.bot_poll_seconds or 30)))
        watcher_layout.addRow("Check frequency", self.bot_poll_seconds_input)
        self.watcher_note = QLabel("Default is 30 seconds. Higher values reduce background activity.")
        self.watcher_note.setWordWrap(True)
        self.watcher_note.setMinimumHeight(72)
        self.watcher_note.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.watcher_note.setStyleSheet(self._muted_label_style())
        watcher_layout.addRow("", self.watcher_note)
        top_row.addWidget(local_group, 2)
        top_row.addWidget(watcher_group, 1)
        layout.addLayout(top_row)

        gmail_group = QGroupBox("Gmail Files")
        gmail_layout = _configure_form(QFormLayout(gmail_group))
        self.gmail_credentials_input = _wide_line_edit(str(self.settings.gmail_credentials_file), min_width=420)
        self.gmail_token_input = _wide_line_edit(str(self.settings.gmail_token_file), min_width=420)
        gmail_layout.addRow("Client secret", self.gmail_credentials_input)
        gmail_layout.addRow("Local token", self.gmail_token_input)
        layout.addWidget(gmail_group)
        return widget

    def _build_wizard_summary_page(self) -> QWidget:
        widget = QWidget()
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QHBoxLayout(widget)
        layout.setSpacing(10)
        overview_group = QGroupBox("Current Settings")
        overview_layout = QVBoxLayout(overview_group)
        overview_layout.setContentsMargins(14, 14, 14, 14)
        self.settings_overview = QPlainTextEdit()
        self.settings_overview.setReadOnly(True)
        self.settings_overview.setMinimumWidth(300)
        self.settings_overview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        overview_layout.addWidget(self.settings_overview)
        layout.addWidget(overview_group, 1)

        prompt_group = QGroupBox("Prompt Preview")
        prompt_layout = QVBoxLayout(prompt_group)
        prompt_layout.setContentsMargins(14, 14, 14, 14)
        self.settings_summary = QPlainTextEdit()
        self.settings_summary.setReadOnly(True)
        self.settings_summary.setMinimumHeight(160)
        self.settings_summary.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        font = QFont("Menlo")
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.settings_summary.setFont(font)
        self.settings_overview.setFont(font)
        prompt_layout.addWidget(self.settings_summary, 1)
        layout.addWidget(prompt_group, 2)
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
            self.settings_step_help.setStyleSheet(self._info_panel_style())
            self.settings_step_help.show()
        else:
            self.settings_step_help.setText(" ")
            self.settings_step_help.hide()
        self.settings_back_button.setEnabled(self.settings_step_index > 0)
        is_last = self._next_visible_settings_index(self.settings_step_index) == self.settings_step_index
        self.settings_next_button.setVisible(False)
        self.settings_done_button.setVisible(False)
        self.settings_advanced_button.setVisible(False)
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
            self.gmail_signature_status.setText("Enable Gmail first to import its saved signature.")
            return
        if not force and self.signature_input.toPlainText().strip():
            self.gmail_signature_status.setText("Using saved MailAssist signature.")
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
            self.gmail_signature_status.setText("No Gmail signature was found.")
            return
        if result.signature_html:
            self.signature_input.setHtml(result.signature_html)
        else:
            self.signature_input.setPlainText(result.signature)
        source = f" from {result.send_as_email}" if result.send_as_email else ""
        self.gmail_signature_status.setText(
            f"Imported Gmail signature{source}."
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
            f"Elders: {len(self._elder_contacts_from_input())}",
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
        overview_lines = lines[: lines.index("Prompt preview (read-only)") - 1]
        prompt_lines = lines[lines.index("Prompt preview (read-only)") :]
        if hasattr(self, "settings_overview"):
            self.settings_overview.setPlainText("\n".join(overview_lines))
        self.settings_summary.setPlainText("\n".join(prompt_lines))

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

    def _append_elder_contact_item(self, contact: ElderContact) -> None:
        self.elder_contacts_list.addItem(_elder_contact_display(contact))

    def _add_elder_contact(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Add Elder")
        layout = QVBoxLayout(dialog)
        form = _configure_form(QFormLayout())
        email_input = QLineEdit()
        email_input.setMinimumWidth(360)
        comment_input = QLineEdit()
        comment_input.setMinimumWidth(360)
        form.addRow("Email", email_input)
        form.addRow("Comment", comment_input)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if not self._upsert_elder_contact(email_input.text(), comment_input.text()):
            QMessageBox.warning(self, "Add Elder", "Enter a valid email address.")
        self._refresh_prompt_preview()

    def _upsert_elder_contact(self, email: str, comment: str) -> bool:
        contacts = parse_elder_contacts([{"email": email, "comment": comment}])
        if not contacts:
            return False
        new_contact = contacts[0]
        existing_contacts = list(self._elder_contacts_from_input())
        for index, contact in enumerate(existing_contacts):
            if contact.email == new_contact.email:
                existing_contacts[index] = new_contact
                self.elder_contacts_list.item(index).setText(_elder_contact_display(new_contact))
                self.elder_contacts_list.setCurrentRow(index)
                return True
        self._append_elder_contact_item(new_contact)
        self.elder_contacts_list.setCurrentRow(self.elder_contacts_list.count() - 1)
        return True

    def _remove_selected_elder_contact(self) -> None:
        if not hasattr(self, "elder_contacts_list"):
            return
        item = self.elder_contacts_list.currentItem()
        if item is None:
            return
        index = self.elder_contacts_list.row(item)
        contacts = parse_elder_contacts([_elder_contact_text_to_payload(item.text())])
        if not contacts:
            return
        contact = contacts[0]
        confirmation = self._confirm_action(
            "Remove Elder",
            f"Remove {contact.email} from the Elders list?",
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return
        self.elder_contacts_list.takeItem(index)
        self.last_removed_elder_contact = (contact, index)
        if hasattr(self, "elder_contacts_undo_button"):
            self.elder_contacts_undo_button.setEnabled(True)
        self._refresh_prompt_preview()

    def _undo_elder_contact_removal(self) -> None:
        if not hasattr(self, "elder_contacts_list") or self.last_removed_elder_contact is None:
            return
        contact, index = self.last_removed_elder_contact
        insert_index = min(max(index, 0), self.elder_contacts_list.count())
        self.elder_contacts_list.insertItem(insert_index, _elder_contact_display(contact))
        self.elder_contacts_list.setCurrentRow(insert_index)
        self.last_removed_elder_contact = None
        if hasattr(self, "elder_contacts_undo_button"):
            self.elder_contacts_undo_button.setEnabled(False)
        self._refresh_prompt_preview()

    def _elder_contacts_from_input(self) -> tuple[ElderContact, ...]:
        if not hasattr(self, "elder_contacts_list"):
            return self.settings.elder_contacts
        items: list[dict[str, str]] = []
        for index in range(self.elder_contacts_list.count()):
            cleaned = self.elder_contacts_list.item(index).text().strip()
            if not cleaned:
                continue
            items.append(_elder_contact_text_to_payload(cleaned))
        return parse_elder_contacts(items)

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
            "padding: 10px 12px; border-radius: 8px; "
            + (
                f"background: {self._theme_colors()['accent_soft']}; color: {self._theme_colors()['accent']};"
                if level == "info"
                else f"background: {self._theme_colors()['error_bg']}; color: {self._theme_colors()['error_text']};"
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
        colors = self._theme_colors()
        dynamic_styles = {
            "ok": (
                f"background: {colors['success_bg']}; color: {colors['success_text']}; "
                f"border: 1px solid {colors['success_border']};"
            ),
            "running": (
                f"background: {colors['warn_bg']}; color: {colors['warn_text']}; "
                f"border: 1px solid {colors['warn_border']};"
            ),
            "warn": (
                f"background: {colors['warn_bg']}; color: {colors['warn_text']}; "
                f"border: 1px solid {colors['warn_border']};"
            ),
            "error": (
                f"background: {colors['error_bg']}; color: {colors['error_text']}; "
                f"border: 1px solid {colors['error_border']};"
            ),
            "idle": (
                f"background: {colors['idle_bg']}; color: {colors['idle_text']}; "
                f"border: 1px solid {colors['idle_border']};"
            ),
        }
        base = dynamic_styles.get(level, dynamic_styles["idle"])
        widget.setStyleSheet(
            f"{base} border-radius: 9px; padding: 3px 10px; font-size: 13px; font-weight: 600;"
        )

    def _set_bot_state(self, state: str, text: str | None = None) -> None:
        labels = {"idle": "Idle", "running": "Running", "error": "Error"}
        if state == "error":
            if text:
                self.last_bot_error_label = text
            display = text or self.last_bot_error_label or labels["error"]
        else:
            self.last_bot_error_label = ""
            display = text if text is not None else labels.get(state, state.title())
        self.bot_status_label.setText(display)
        self._paint_status_pill(self.bot_status_label, "running" if state == "running" else state)
        self.last_bot_state = state

    def _short_bot_error_label(self, failure: str, *, provider: str = "") -> str:
        normalized = " ".join(failure.split()).lower()
        provider_key = provider.strip().lower()
        if "invalid_grant" in normalized or "outlook sign-in expired" in normalized:
            return "Outlook sign-in expired"
        if provider_key == "outlook" and ("sign-in expired" in normalized or "sign in expired" in normalized):
            return "Outlook sign-in expired"
        if "gmail sign-in expired" in normalized:
            return "Gmail sign-in expired"
        if provider_key == "gmail" and ("sign-in expired" in normalized or "sign in expired" in normalized):
            return "Gmail sign-in expired"
        return "Error"

    def _main_bot_start_controls(self) -> list[QWidget]:
        controls: list[QWidget] = []
        for name in (
            "gmail_draft_preview_button",
            "outlook_draft_preview_button",
            "gmail_label_rescan_button",
            "outlook_category_rescan_button",
            "start_watch_loop_button",
        ):
            control = getattr(self, name, None)
            if isinstance(control, QWidget):
                controls.append(control)
        for name in ("gmail_label_days_input", "outlook_category_days_input"):
            control = getattr(self, name, None)
            if isinstance(control, QWidget):
                controls.append(control)
        return controls

    def _bot_start_controls(self) -> list[QWidget]:
        controls = self._main_bot_start_controls()
        control = getattr(self, "test_ollama_button", None)
        if isinstance(control, QWidget):
            controls.append(control)
        return controls

    def _set_bot_busy_cursor(self, busy: bool) -> None:
        if busy and not self.bot_busy_cursor_active:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            self.bot_busy_cursor_active = True
        elif not busy and self.bot_busy_cursor_active:
            while QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()
            self.bot_busy_cursor_active = False

    def _refresh_bot_action_controls(self) -> None:
        busy = self.bot_process is not None
        for control in self._bot_start_controls():
            control.setEnabled(not busy)
        if not busy:
            for control in self._main_bot_start_controls():
                control.setEnabled(not self.settings_open)
        if hasattr(self, "stop_bot_button"):
            self.stop_bot_button.setEnabled(busy)
        self._set_bot_busy_cursor(busy)

    def _bot_action_already_running(self) -> bool:
        if self.bot_process is None:
            return False
        self._set_banner("A bot action is already running.", level="error")
        self._refresh_bot_action_controls()
        return True

    def _bot_action_blocked_by_settings(self) -> bool:
        if not self.settings_open:
            return False
        self._set_banner("Return to Dashboard before starting a bot action.", level="info")
        self._refresh_bot_action_controls()
        return True

    def _main_bot_action_unavailable(self) -> bool:
        return self._bot_action_already_running() or self._bot_action_blocked_by_settings()

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
        self._refresh_bot_action_controls()

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
        if isinstance(self.activity_group, RecentActivityPanel):
            self.activity_group.append_message(message)
        else:
            if self.recent_activity.toPlainText().strip() == EMPTY_ACTIVITY_TEXT:
                self.recent_activity.clear()
            self.recent_activity.appendPlainText(message)
        self.last_activity_summary = message
        self.refresh_dashboard()

    def clear_recent_activity(self) -> None:
        if isinstance(self.activity_group, RecentActivityPanel):
            self.activity_group.clear_messages()
        else:
            self.recent_activity.setPlainText(EMPTY_ACTIVITY_TEXT)
        self.last_activity_summary = "Idle"
        self.refresh_dashboard()
        self._set_banner("Recent Activity cleared.", level="info")

    def _announce_long_action(self, message: str) -> None:
        self._append_recent_activity(message)
        self._set_banner(message, level="info")

    def _reset_bot_progress(self) -> None:
        self.bot_progress = {
            "total": 0,
            "categorized": 0,
            "checked": 0,
            "drafts": 0,
            "draft_previews": 0,
            "skipped": 0,
            "already_handled": 0,
            "filtered": 0,
            "updated_messages": 0,
            "current_index": 0,
        }
        self.bot_progress["current_detail"] = ""

    def _bot_progress_summary(self) -> str:
        total = self.bot_progress.get("total", 0)
        categorized = self.bot_progress.get("categorized", 0)
        checked = self.bot_progress.get("checked", 0)
        drafts = self.bot_progress.get("drafts", 0)
        draft_previews = self.bot_progress.get("draft_previews", 0)
        skipped = self.bot_progress.get("skipped", 0)
        already_handled = self.bot_progress.get("already_handled", 0)
        filtered = self.bot_progress.get("filtered", 0)
        if self.current_bot_action in {"gmail-populate-labels", "outlook-populate-categories"}:
            current_index = int(self.bot_progress.get("current_index") or categorized or 0)
            if total:
                return f"{current_index}/{total} scanned · {categorized} categorized"
            return f"{categorized} scanned · {categorized} categorized"
        draft_total = drafts + draft_previews
        return f"{checked} scanned / {draft_total} drafts"

    def _start_bot_heartbeat(self, action: str, provider: str, *, dry_run: bool = False) -> None:
        self.bot_action_started_at = time.monotonic()
        self.current_bot_provider = provider
        self.current_bot_dry_run = dry_run
        self.current_bot_phase = "running"
        self.last_live_progress_summary = ""
        self._reset_bot_progress()
        if action in {"watch-once", "watch-loop", "gmail-populate-labels", "outlook-populate-categories"}:
            self._append_bot_heartbeat()
            self.bot_heartbeat_timer.start()
            if action == "watch-once" and dry_run:
                self.bot_timeout_timer.start(120000)

    def _stop_bot_heartbeat(self) -> None:
        self.bot_heartbeat_timer.stop()
        self.bot_timeout_timer.stop()
        self.bot_action_started_at = None

    def _append_bot_heartbeat(self) -> None:
        if self.bot_process is None or self.bot_action_started_at is None:
            self._stop_bot_heartbeat()
            return
        elapsed = _short_duration_label(time.monotonic() - self.bot_action_started_at)
        provider = self.current_bot_provider.title() if self.current_bot_provider else "MailAssist"
        if self.current_bot_action == "watch-once":
            message = (
                f"{provider} preview still running after {elapsed}. "
                f"{self._bot_progress_summary()}. "
                "No email will be sent; auto-stops after 2 minutes."
            )
        elif self.current_bot_action == "watch-loop":
            if self.current_bot_phase == "waiting":
                summary = self.last_live_progress_summary or self._bot_progress_summary()
                message = f"{provider} auto-check idle for {elapsed}. Last pass: {summary}."
                self._set_banner(message, level="info")
                return
            else:
                message = f"{provider} auto-check checking after {elapsed}. {self._bot_progress_summary()}."
        else:
            message = f"{provider} action still running after {elapsed}. {self._bot_progress_summary()}."
        self._append_recent_activity(message)
        self._set_banner(message, level="info")

    def _stop_bot_after_timeout(self) -> None:
        if self.bot_process is None:
            self._stop_bot_heartbeat()
            return
        provider = self.current_bot_provider.title() if self.current_bot_provider else "MailAssist"
        self._append_recent_activity(
            f"{provider} preview stopped after 2 minutes. No email was sent."
        )
        self._set_banner(f"{provider} preview stopped after 2 minutes.", level="error")
        self.stop_bot_action()

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
                    message = _user_facing_failure_message(str(err.get("message") or "Bot error.").strip())
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
            self.ollama_models_hint.setText(f"Found {len(models)} installed model(s).")
            self.ollama_health = (f"connected ({len(models)})", "ok")
        else:
            self.ollama_connection_status.setText("No models found")
            self.ollama_models_hint.setText("No installed Ollama models were detected.")
            self.ollama_health = ("no models", "warn")
        if model_error:
            self.ollama_connection_status.setText("Not reachable")
            self.ollama_health = ("not reachable", "error")
            if (
                not silent
                and not self.ollama_result.toPlainText().startswith("Sending a tiny test prompt")
            ):
                self._set_ollama_result_text(model_error)
        elif not silent and not models and not self.ollama_result.toPlainText().strip():
            self.ollama_result.clear()
        self._style_ollama_connection_status()
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
        save_elder_contacts(self.settings.elder_contacts_file, self._elder_contacts_from_input())
        current.update(
            {
                "MAILASSIST_OLLAMA_URL": self.ollama_url_input.text().strip() or "http://localhost:11434",
                "MAILASSIST_OLLAMA_MODEL": selected_model,
                "MAILASSIST_USER_SIGNATURE": self.signature_input.toPlainText().strip().replace("\n", "\\n"),
                "MAILASSIST_USER_SIGNATURE_HTML": self.signature_input.toHtml().strip().replace("\n", "\\n"),
                "MAILASSIST_USER_TONE": str(self.tone_combo.currentData() or "direct_concise"),
                "MAILASSIST_APPEARANCE": self.appearance,
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
            self.main_stack.setCurrentWidget(self.dashboard_page)
            self._select_nav_item("Dashboard")
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
        if self._bot_action_already_running():
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
        if self._main_bot_action_unavailable():
            return
        self.run_bot_action("watch-once", provider="mock")

    def start_watch_loop(self) -> None:
        if self._main_bot_action_unavailable():
            return
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
        confirmation = self._confirm_action(
            "Stop Ollama",
            (
                "MailAssist will force quit the local Ollama process. This can interrupt any model work "
                "currently running, and draft previews or auto-checks will fail until Ollama starts again.\n\n"
                "Continue?"
            ),
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
        if self._main_bot_action_unavailable():
            return
        self._announce_long_action(
            "Previewing Gmail draft. Dry run only; no Gmail draft will be created. "
            "Heartbeat updates will appear here and the preview auto-stops after 2 minutes."
        )
        self.run_bot_action(
            "watch-once",
            provider="gmail",
            thread_id="thread-008",
            force=True,
            dry_run=True,
        )

    def run_controlled_gmail_draft(self) -> None:
        if self._main_bot_action_unavailable():
            return
        confirmation = self._confirm_action(
            "Create Controlled Gmail Draft",
            (
                "MailAssist will create one real Gmail draft addressed to your own Gmail account "
                "using sanitized mock content. Nothing will be sent. Continue?"
            ),
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            self._set_banner("Controlled Gmail draft canceled.", level="info")
            return
        self._announce_long_action(
            "Creating one controlled Gmail test draft. This may take a minute; nothing will be sent."
        )
        self.run_bot_action("gmail-controlled-draft", provider="gmail", thread_id="thread-008")

    def run_outlook_draft_preview(self) -> None:
        if self._main_bot_action_unavailable():
            return
        self.save_settings(announce=False)
        self._announce_long_action(
            "Previewing Outlook draft. Dry run only; no Outlook draft will be created. "
            "Heartbeat updates will appear here and the preview auto-stops after 2 minutes."
        )
        self.run_bot_action(
            "watch-once",
            provider="outlook",
            force=True,
            dry_run=True,
            limit=1,
        )

    def run_gmail_label_rescan(self) -> None:
        if self._main_bot_action_unavailable():
            return
        days = int(self.gmail_label_days_input.value()) if hasattr(self, "gmail_label_days_input") else 7
        confirmation = self._confirm_action(
            "Organize Gmail",
            (
                f"MailAssist will reclassify Gmail threads from the last {days} day"
                f"{'' if days == 1 else 's'} using the current category list. "
                "It may add, replace, or remove MailAssist labels.\n\n"
                "This can take a few minutes, but you can keep working while it runs. "
                "Continue?"
            ),
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
        if self._main_bot_action_unavailable():
            return
        days = (
            int(self.outlook_category_days_input.value())
            if hasattr(self, "outlook_category_days_input")
            else 25
        )
        confirmation = self._confirm_action(
            "Organize Outlook",
            (
                f"MailAssist will classify Outlook messages from the last {days} day"
                f"{'' if days == 1 else 's'} using the current category list. "
                "It may add, replace, or remove MailAssist Outlook categories.\n\n"
                "This can take a few minutes, but you can keep working while it runs. "
                "Continue?"
            ),
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
        if self._bot_action_already_running():
            return
        if action != "ollama-check" and self._bot_action_blocked_by_settings():
            return

        base_url, selected_model = self._current_bot_ollama_settings()
        self.bot_stdout_buffer = ""
        self.current_bot_action = action
        self.current_bot_provider = provider
        self.current_bot_dry_run = dry_run
        self._reset_bot_progress()
        self.bot_process = QProcess(self)
        self.bot_process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.bot_process.setWorkingDirectory(str(self.settings.root_dir))
        process_env = QProcessEnvironment.systemEnvironment()
        if action == "watch-once" and dry_run:
            process_env.insert("MAILASSIST_OLLAMA_GENERATE_TIMEOUT_SECONDS", "110")
        self.bot_process.setProcessEnvironment(process_env)
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
        self._refresh_bot_action_controls()
        self._start_bot_heartbeat(action, provider, dry_run=dry_run)
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
            self.bot_progress["checked"] = self.bot_progress.get("checked", 0) + 1
            self.bot_progress["drafts"] = self.bot_progress.get("drafts", 0) + 1
        elif event_type == "draft_ready":
            self.bot_progress["checked"] = self.bot_progress.get("checked", 0) + 1
            self.bot_progress["draft_previews"] = self.bot_progress.get("draft_previews", 0) + 1
        elif event_type == "skipped_email":
            self.bot_progress["checked"] = self.bot_progress.get("checked", 0) + 1
            self.bot_progress["skipped"] = self.bot_progress.get("skipped", 0) + 1
        elif event_type == "already_handled":
            self.bot_progress["checked"] = self.bot_progress.get("checked", 0) + 1
            self.bot_progress["already_handled"] = self.bot_progress.get("already_handled", 0) + 1
        elif event_type == "filtered_out":
            self.bot_progress["checked"] = self.bot_progress.get("checked", 0) + 1
            self.bot_progress["filtered"] = self.bot_progress.get("filtered", 0) + 1
        elif event_type in {
            "gmail_thread_labeled",
            "gmail_thread_label_preview",
            "outlook_thread_categorized",
            "outlook_thread_category_preview",
        }:
            self.bot_progress["categorized"] = self.bot_progress.get("categorized", 0) + 1
            self.bot_progress["updated_messages"] = (
                self.bot_progress.get("updated_messages", 0) + int(event.get("updated_message_count") or 0)
            )
        elif event_type in {
            "organize_phase",
            "gmail_thread_classification_started",
            "outlook_thread_classification_started",
        }:
            if "thread_count" in event:
                self.bot_progress["total"] = int(event.get("thread_count") or 0)
            if "current_index" in event:
                self.bot_progress["current_index"] = int(event.get("current_index") or 0)
            message = str(event.get("message") or "").strip()
            if event_type == "organize_phase":
                detail = message or "Preparing organizer run."
                self.bot_progress["current_detail"] = detail
                self._append_recent_activity(detail)
        elif event_type == "watch_pass_started":
            self.current_bot_phase = "running"
            self._reset_bot_progress()
            provider = str(event.get("provider") or self.current_bot_provider or "provider").title()
            self._append_recent_activity(f"{provider} auto-check pass started.")
        elif event_type == "watch_pass_completed":
            self.current_bot_phase = "waiting"
            self.last_live_progress_summary = self._bot_progress_summary()
            provider = str(event.get("provider") or self.current_bot_provider or "provider").title()
            self._append_recent_activity(
                f"{provider} auto-check pass completed: {self.last_live_progress_summary}. "
                "Idle until next check; Ollama is not drafting."
            )
        elif event_type == "failed_pass":
            self._append_recent_activity(f"Watch pass failed: {event.get('message', 'Unknown error')}")
        elif event_type == "sleeping":
            self.current_bot_phase = "waiting"
        elif event_type == "outlook_readiness":
            ready = bool(event.get("ready"))
            self.current_provider_ready = ready
            self.current_provider_readiness_message = str(event.get("message") or "").strip()
            if not ready:
                message = self.current_provider_readiness_message or "Outlook connection is not ready."
                self._append_recent_activity(f"Outlook connection failed: {message}")
                self.last_failure_summary = message
                self._set_banner(message, level="error")
        elif event_type == "completed":
            self._stop_bot_heartbeat()
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
                provider = str(event.get("provider") or "").strip()
                provider_label = provider.title() if provider else "Provider"
                prefix = (
                    f"{provider_label} preview completed"
                    if event.get("dry_run")
                    else f"{provider_label} watch pass completed"
                )
                self._append_recent_activity(f"{prefix}: {self.last_pass_summary}.")
            elif "thread_count" in event:
                provider = str(event.get("provider") or "").strip()
                provider_label = provider.title() if provider else "Provider"
                thread_count = int(event.get("thread_count") or 0)
                applied_count = int(event.get("applied_count") or 0)
                updated_messages = int(event.get("message_update_count") or 0)
                if event.get("ready") is False:
                    reason = str(self.current_provider_readiness_message or event.get("message") or "").strip()
                    if reason:
                        detail = _organizer_stop_message(
                            provider_label,
                            reason,
                            categorized=0,
                            stage="before reading mail",
                        )
                    else:
                        detail = f"{provider_label} organize stopped before reading mail because the provider is not connected."
                    self.last_failure_summary = reason or "Provider is not connected."
                elif updated_messages:
                    detail = (
                        f"{provider_label} organize completed: {thread_count} emails categorized · "
                        f"{applied_count} category writes · {updated_messages} messages updated."
                    )
                else:
                    detail = (
                        f"{provider_label} organize completed: {thread_count} emails categorized · "
                        f"{applied_count} updates applied."
                    )
                self._append_recent_activity(detail)
            self.refresh_dashboard()
        elif event_type == "error":
            self._stop_bot_heartbeat()
            failure = _user_facing_failure_message(str(event.get("message", "Bot action failed.")))
            provider = str(event.get("provider") or self.current_bot_provider or "").strip()
            provider_label = provider.title() if provider else "MailAssist"
            if self.current_bot_action == "watch-once" and self.current_bot_dry_run:
                self._append_recent_activity(f"{provider_label} preview failed: {failure}")
            elif _is_organizer_action(str(event.get("action") or self.current_bot_action or "")):
                categorized = int(self.bot_progress.get("categorized", 0) or 0)
                self._append_recent_activity(
                    _organizer_stop_message(provider_label, failure, categorized=categorized)
                )
            else:
                self._append_recent_activity(f"{provider_label} action failed: {failure}")
            if event.get("action") == "ollama-check":
                self._stop_ollama_test_countdown()
                self.ollama_result_label.setText(
                    f"Model test failed after {self._ollama_test_elapsed_label()}."
                )
            self.last_failure_summary = failure
            self._set_banner(failure, level="error")
            self._set_bot_state("error", self._short_bot_error_label(failure, provider=provider))
        elif event_type == "info":
            if "thread_count" in event:
                self.bot_progress["total"] = int(event.get("thread_count") or 0)
            self._set_banner(str(event.get("message", "")), level="info")

    def _handle_bot_finished(self, exit_code: int, _exit_status) -> None:
        if self.bot_stdout_buffer.strip():
            self._append_bot_console(self.bot_stdout_buffer.strip())
            self.bot_stdout_buffer = ""
        self._stop_bot_heartbeat()
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
        self.current_bot_provider = ""
        self.current_bot_dry_run = False
        self.current_bot_phase = ""
        self.last_live_progress_summary = ""
        self.current_provider_ready = True
        self.current_provider_readiness_message = ""
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
