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

from PySide6.QtCore import QProcess, Qt, QTimer
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
from mailassist.gui.bot_activity import short_duration_label
from mailassist.gui.bot_controller import BotControllerMixin
from mailassist.gui.confirmations import confirm_action
from mailassist.gui.recent_activity import RecentActivityPanel
from mailassist.gui.settings_pages import SettingsPagesMixin
from mailassist.gui.theme import (
    app_stylesheet,
    combo_popup_style,
    resolved_appearance,
    theme_colors,
    tool_button_style,
)
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


def _app_icon_path(root_dir: Path, *, platform: str = sys.platform) -> Path | None:
    icon_dir = root_dir / "assets" / "brand"
    if platform == "win32":
        candidates = (
            icon_dir / "mailassist_icon.ico",
            icon_dir / "mailassist_icon_256.png",
            icon_dir / "mailassist_icon.svg",
        )
    else:
        candidates = (
            icon_dir / "mailassist_icon.svg",
            icon_dir / "mailassist_icon_256.png",
            icon_dir / "mailassist_icon.ico",
        )
    return next((path for path in candidates if path.exists()), None)


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


class MailAssistDesktopWindow(SettingsPagesMixin, BotControllerMixin, QMainWindow):
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
        self.activity_history_summary = "No recent runs"
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
        icon_path = _app_icon_path(self.settings.root_dir)
        if icon_path is not None:
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
        return resolved_appearance(self.appearance)

    def _theme_colors(self) -> dict[str, str]:
        return theme_colors(self.appearance)

    def _apply_app_theme(self) -> None:
        self.setStyleSheet(app_stylesheet(self._theme_colors()))
        self._refresh_theme_dependent_widgets()

    def _combo_popup_style(self) -> str:
        return combo_popup_style(self._theme_colors())

    def _tool_button_style(self) -> str:
        return tool_button_style(self._theme_colors())

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
        return confirm_action(self, title=title, message=message, colors=self._theme_colors())

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
            "activity_history_label",
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
        self.activity_history_label = QLabel(self.activity_history_summary)
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
                ("7-day activity", self.activity_history_label),
            )
        ):
            status_cards.addWidget(self._build_dashboard_card(label_text, widget), index // 4, index % 4)
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
        self.activity_history_label.setText(self.activity_history_summary)

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
            self.ollama_models_hint.setText(
                "No installed Ollama models were detected. Start Ollama or install a model, then refresh."
            )
            self.ollama_health = ("no models", "warn")
        if model_error:
            self.ollama_connection_status.setText("Not reachable")
            self.ollama_health = ("not reachable", "error")
            self.ollama_models_hint.setText(
                "Ollama is not reachable. Use Start Ollama, then refresh the model list."
            )
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
        return short_duration_label(time.monotonic() - self.ollama_test_started_at)

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



def run_desktop_gui() -> int:
    app = QApplication.instance() or QApplication([])
    window = MailAssistDesktopWindow()
    window.show()
    return app.exec()
