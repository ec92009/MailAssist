from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QProcess, QThread, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QPlainTextEdit,
    QFrame,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from mailassist.config import load_settings, read_env_file, write_env_file
from mailassist.background_bot import TONE_OPTIONS, build_prompt_preview, tone_label
from mailassist.gui.server import (
    FILTER_LABELS,
    SET_ASIDE_CLASSIFICATIONS,
    STATUS_FILTER_LABELS,
    filtered_and_sorted_threads,
    find_thread_state,
    load_review_state,
    load_visible_version,
    normalize_classification,
    normalize_review_status,
    payload_to_thread,
    save_review_state,
    stream_candidate_for_tone,
    update_thread_status,
    update_candidate,
)
from mailassist.models import utc_now_iso
from mailassist.llm.ollama import OllamaClient
from mailassist.providers.gmail import GmailProvider

CLASSIFICATION_TINTS = {
    "urgent": ("#ffe3db", "#973522"),
    "reply_needed": ("#e0f0ff", "#1e5f94"),
    "automated": ("#fff0bf", "#8a6112"),
    "no_response": ("#eaedf2", "#556170"),
    "spam": ("#ffdce9", "#95244b"),
    "unclassified": ("#f4ede6", "#5e6978"),
}
ROW_BACKGROUNDS = ("#fffaf4", "#ecdcca")
SORT_VALUE_ROLE = Qt.ItemDataRole.UserRole + 1
THREAD_ID_ROLE = Qt.ItemDataRole.UserRole + 2
CHECK_COLUMN = 0
SUBJECT_COLUMN = 1
CLASSIFICATION_COLUMN = 2
RECEIVED_COLUMN = 3
SENDER_COLUMN = 4
INBOX_ROW_HEIGHT = 30
INBOX_INITIAL_VISIBLE_ROWS = 6
INBOX_INITIAL_HEIGHT = 34 + (INBOX_ROW_HEIGHT * INBOX_INITIAL_VISIBLE_ROWS)


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


def _humanize(token: str) -> str:
    return token.replace("_", " ").title()


def _status_label(status: str) -> str:
    normalized = normalize_review_status(status)
    if normalized == "use_draft":
        return "Draft selected"
    if normalized == "ignored":
        return "Ignored"
    if normalized == "user_replied":
        return "User replied"
    return "Needs review"


def _latest_message(thread_state: dict[str, Any]) -> dict[str, Any]:
    messages = thread_state.get("thread", {}).get("messages", [])
    if not messages:
        return {}
    return max(messages, key=lambda message: message.get("sent_at", ""))


def _received_label(thread_state: dict[str, Any]) -> str:
    sent_at = str(_latest_message(thread_state).get("sent_at", "")).strip()
    if not sent_at:
        return "Unknown date"
    try:
        parsed = datetime.fromisoformat(sent_at.replace("Z", "+00:00"))
    except ValueError:
        return sent_at
    return parsed.strftime("%b %d, %H:%M")


def _sender_label(thread_state: dict[str, Any]) -> str:
    return str(_latest_message(thread_state).get("from", "")).strip() or "Unknown sender"


def _format_model_size(size_value: object) -> str:
    try:
        size = float(size_value)
    except (TypeError, ValueError):
        return ""
    if size <= 0:
        return ""
    units = ("B", "KB", "MB", "GB", "TB")
    unit_index = 0
    while size >= 1000 and unit_index < len(units) - 1:
        size /= 1000
        unit_index += 1
    if unit_index == 0:
        return f"{int(size)} {units[unit_index]}"
    return f"{size:.1f} {units[unit_index]}"


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


def _log_action_label(action: str) -> str:
    labels = {
        "gmail-inbox-preview": "Gmail inbox preview",
        "ollama-check": "Ollama check",
        "process-mock-inbox": "Mock inbox pass",
        "queue-status": "Queue status",
        "regenerate-thread": "Regenerate draft",
        "sync-review-state": "Review sync",
        "watch-once": "Watch pass",
    }
    return labels.get(action, _humanize(action))


class SortableTableItem(QTableWidgetItem):
    def __lt__(self, other: QTableWidgetItem) -> bool:
        mine = self.data(SORT_VALUE_ROLE)
        theirs = other.data(SORT_VALUE_ROLE)
        if mine is not None and theirs is not None:
            return mine < theirs
        return super().__lt__(other)


class CandidateRegenerationWorker(QObject):
    partial_body = Signal(str, str, str)
    finished = Signal(str, str, str)
    failed = Signal(str)

    def __init__(
        self,
        *,
        root_dir: Path,
        thread_id: str,
        candidate_id: str,
        base_url: str,
        selected_model: str,
    ) -> None:
        super().__init__()
        self.root_dir = root_dir
        self.thread_id = thread_id
        self.candidate_id = candidate_id
        self.base_url = base_url
        self.selected_model = selected_model

    def run(self) -> None:
        try:
            state = load_review_state(self.root_dir)
            thread_state, _ = find_thread_state(state, self.thread_id)
            thread = payload_to_thread(thread_state["thread"])
            candidate = next(
                (item for item in thread_state.get("candidates", []) if item.get("candidate_id") == self.candidate_id),
                None,
            )
            if candidate is None:
                raise ValueError("Candidate not found.")
            tone = str(candidate.get("tone", ""))
            guidance = ""
            if tone == "direct and executive":
                guidance = "Keep it concise, confident, and practical. Confirm what can be done now and name one next step."
            elif tone == "warm and collaborative":
                guidance = "Sound thoughtful and calm. Acknowledge the ask, explain any nuance briefly, and keep the tone encouraging."
            updated_candidate, generation_model, generation_error, classification = stream_candidate_for_tone(
                thread,
                candidate_id=self.candidate_id,
                tone=tone,
                guidance=guidance,
                base_url=self.base_url,
                selected_model=self.selected_model,
                existing_body=str(candidate.get("body", "")),
                on_body_update=lambda chunk: self._emit_partial_chunk(chunk),
            )
            for index, current in enumerate(thread_state.get("candidates", [])):
                if current.get("candidate_id") == self.candidate_id:
                    thread_state["candidates"][index] = updated_candidate
                    break
            thread_state["candidate_generation_model"] = generation_model
            thread_state["candidate_generation_error"] = generation_error
            thread_state["classification"] = classification
            thread_state["classification_source"] = generation_model or "fallback"
            thread_state["classification_updated_at"] = utc_now_iso()
            if thread_state.get("selected_candidate_id") == self.candidate_id:
                thread_state["selected_candidate_id"] = None
            if thread_state.get("status") != "ignored":
                thread_state["status"] = "pending_review"
            for item in thread_state.get("candidates", []):
                if item.get("candidate_id") != self.candidate_id and normalize_review_status(item.get("status")) != "ignored":
                    item["status"] = "pending_review"
            state["generated_at"] = utc_now_iso()
            save_review_state(self.root_dir, state)
            label = next(
                (
                    str(item.get("label", "draft"))
                    for item in thread_state.get("candidates", [])
                    if item.get("candidate_id") == self.candidate_id
                ),
                "draft",
            )
            self.finished.emit(self.thread_id, self.candidate_id, label)
        except Exception as exc:
            self.failed.emit(str(exc))

    def _emit_partial_chunk(self, chunk: str) -> None:
        if not chunk:
            return
        self.partial_body.emit(self.thread_id, self.candidate_id, chunk)
        # Give the main thread a chance to paint the streamed chunk before more arrive.
        time.sleep(0.01)


class CandidateEditor(QWidget):
    def __init__(
        self,
        thread_state: dict[str, Any],
        candidate: dict[str, Any],
        autosave_callback,
        reset_callback,
        use_callback,
        ignore_callback,
        close_callback,
        refresh_callback,
    ) -> None:
        super().__init__()
        self.thread_id = thread_state["thread_id"]
        self.candidate_id = candidate["candidate_id"]
        self.last_saved_text = candidate.get("body", "").strip()
        self.autosave_callback = autosave_callback

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.editor = QPlainTextEdit(candidate.get("body", ""))
        self.editor.setPlaceholderText("No response recommended for this classification.")
        self.editor.setMinimumHeight(120)
        layout.addWidget(self.editor, 1)

        self.autosave_timer = QTimer(self)
        self.autosave_timer.setInterval(450)
        self.autosave_timer.setSingleShot(True)
        self.autosave_timer.timeout.connect(self._emit_autosave)
        self.editor.textChanged.connect(self._schedule_autosave)

    def _schedule_autosave(self) -> None:
        self.autosave_timer.start()

    def _emit_autosave(self) -> None:
        if self.current_text() == self.last_saved_text:
            return
        self.autosave_callback(self.thread_id, self.candidate_id, self)

    def current_text(self) -> str:
        return self.editor.toPlainText().strip()

    def mark_saved_text(self, text: str) -> None:
        self.last_saved_text = text.strip()

    def replace_text(self, text: str) -> None:
        self.autosave_timer.stop()
        self.editor.blockSignals(True)
        self.editor.setPlainText(text)
        self.editor.blockSignals(False)
        self.mark_saved_text(text)

    def append_text(self, chunk: str) -> None:
        if not chunk:
            return
        self.autosave_timer.stop()
        self.editor.blockSignals(True)
        cursor = self.editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(chunk)
        self.editor.setTextCursor(cursor)
        self.editor.ensureCursorVisible()
        self.editor.blockSignals(False)


class MailAssistDesktopWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = load_settings()
        self.review_state = load_review_state(self.settings.root_dir)
        self.current_thread_id = ""
        self.bot_process: QProcess | None = None
        self.bot_stdout_buffer = ""
        self.latest_bot_log_path: Path | None = None
        self.settings_dialog: QDialog | None = None
        self.bot_logs_dialog: QDialog | None = None
        self.candidate_regeneration_thread: QThread | None = None
        self.candidate_regeneration_worker: CandidateRegenerationWorker | None = None
        self.active_regeneration_editor: CandidateEditor | None = None
        self.active_regeneration_thread_id = ""
        self.active_regeneration_candidate_id = ""
        self.active_progress_label = ""
        self.candidate_regeneration_active = False
        self.candidate_regeneration_seen_chunk = False
        self.candidate_regeneration_char_count = 0
        self.candidate_regeneration_body = ""
        self.progress_timer = QTimer(self)
        self.progress_timer.setInterval(180)
        self.progress_timer.timeout.connect(self._advance_fake_progress)
        self.fake_progress_value = 0
        self.table_sort_column = RECEIVED_COLUMN
        self.table_sort_order = Qt.SortOrder.DescendingOrder
        self.last_activity_summary = "Idle"
        self.gmail_signature_import_attempted = False
        self.review_previous_step_index = 3
        self.settings_group_stable_height = 0
        self.settings_wizard_stable_height = 0
        setup_value = read_env_file(self.settings.root_dir / ".env").get("MAILASSIST_SETUP_COMPLETE", "false")
        self.setup_finished = setup_value.strip().lower() == "true"
        self.settings_open = not self.setup_finished

        self.setWindowTitle(f"MailAssist v{load_visible_version(self.settings.root_dir)}")
        icon_path = self.settings.root_dir / "assets" / "brand" / "mailassist_icon.svg"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(1120, 680)

        self._build_ui()
        self.refresh_models()
        self.refresh_bot_logs()
        self.refresh_dashboard()

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

        self.settings_group = QGroupBox("Settings")
        self.settings_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        settings_layout = QVBoxLayout(self.settings_group)
        settings_layout.setContentsMargins(8, 8, 8, 8)
        settings_layout.setSpacing(6)
        settings_layout.addWidget(self._build_settings_wizard())
        shell.addWidget(self.settings_group)

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
        self.last_activity_label = QLabel(self.last_activity_summary)
        for label_text, widget in (
            ("Bot", self.bot_status_label),
            ("Provider", self.provider_status_label),
            ("Ollama", self.ollama_status_label),
            ("Tone", self.tone_status_label),
            ("Signature", self.signature_status_label),
            ("Last activity", self.last_activity_label),
        ):
            label = QLabel(label_text)
            label.setStyleSheet("color: #5e6978; font-size: 12px;")
            widget.setStyleSheet("color: #1d2430; font-size: 14px;")
            status_grid.addRow(label, widget)
        control_layout.addLayout(status_grid)

        bot_actions = QHBoxLayout()
        run_mock_pass_button = QPushButton("Run Mock Pass")
        run_mock_pass_button.clicked.connect(self.run_mock_watch_once)
        gmail_draft_test_button = QPushButton("Create Gmail Test Draft")
        gmail_draft_test_button.clicked.connect(self.run_gmail_draft_test)
        queue_status_button = QPushButton("Queue Status")
        queue_status_button.clicked.connect(self.run_queue_status)
        bot_actions.addWidget(run_mock_pass_button)
        bot_actions.addWidget(gmail_draft_test_button)
        bot_actions.addWidget(queue_status_button)
        bot_actions.addStretch(1)
        control_layout.addLayout(bot_actions)
        shell.addWidget(self.control_group)

        self.activity_group = QGroupBox("Recent Activity")
        activity_layout = QVBoxLayout(self.activity_group)
        activity_layout.setContentsMargins(10, 10, 10, 10)
        self.recent_activity = QPlainTextEdit()
        self.recent_activity.setReadOnly(True)
        self.recent_activity.setMinimumHeight(80)
        self.recent_activity.setPlainText("No bot activity yet.")
        activity_layout.addWidget(self.recent_activity)
        shell.addWidget(self.activity_group, 1)
        shell.addStretch(1)

        self._build_bot_logs_dialog()

        self.setCentralWidget(root)
        self._refresh_setup_visibility()

    def _build_settings_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setModal(True)
        dialog.setWindowTitle("MailAssist Settings")
        dialog.resize(760, 620)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        intro = QLabel("Configure the background draft bot.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #5e6978; font-size: 14px;")
        layout.addWidget(intro)

        settings_tabs = QTabWidget()
        settings_tabs.addTab(self._build_ollama_settings_panel(), "Ollama")
        settings_tabs.addTab(self._build_provider_settings_panel(), "Providers")
        settings_tabs.addTab(self._build_signature_settings_panel(), "Signature")
        settings_tabs.addTab(self._build_prompt_preview_panel(), "Prompt")
        layout.addWidget(settings_tabs, 1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        close_button = QPushButton("Done")
        close_button.clicked.connect(dialog.accept)
        footer.addWidget(close_button)
        layout.addLayout(footer)

        self.settings_dialog = dialog

    def _build_bot_logs_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setModal(False)
        dialog.setWindowTitle("MailAssist Bot Logs")
        dialog.resize(980, 760)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        intro = QLabel("Inspect live stdout and recent bot log files without crowding the review workspace.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #5e6978; font-size: 14px;")
        layout.addWidget(intro)
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

    def open_settings_dialog(self) -> None:
        if hasattr(self, "settings_tabs"):
            self.settings_tabs.setCurrentIndex(0)
            self._set_banner("Settings are available in the main window.", level="info")
        self.refresh_models()

    def open_settings_wizard(self) -> None:
        geometry = self.geometry()
        self.settings_open = True
        self._refresh_setup_visibility()
        self._restore_geometry_after_layout(geometry)
        self._set_banner("Settings are open. Press Finish when you are done.", level="info")

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
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
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
        self.settings_step_help.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Maximum)
        self.settings_step_help.setStyleSheet(
            "background: #fff3df; border: 1px solid #dfc7ad; border-radius: 10px; padding: 6px; color: #5e6978;"
        )
        layout.addWidget(self.settings_step_help)

        self.settings_stack = QStackedWidget()
        self.settings_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
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
        layout.addWidget(self.settings_stack, 0, Qt.AlignmentFlag.AlignTop)

        nav = QHBoxLayout()
        nav.setSpacing(10)
        self.settings_back_button = QPushButton("Back")
        self.settings_back_button.setMinimumWidth(120)
        self.settings_back_button.clicked.connect(self._previous_settings_step)
        self.settings_next_button = QPushButton("Next")
        self.settings_next_button.setMinimumWidth(120)
        self.settings_next_button.clicked.connect(self._next_settings_step)
        self.settings_save_button = QPushButton("Finish")
        self.settings_save_button.setMinimumWidth(140)
        self.settings_save_button.clicked.connect(self.finish_settings_wizard)
        self.settings_advanced_button = QPushButton("Advanced settings")
        self.settings_advanced_button.setMinimumWidth(160)
        self.settings_advanced_button.clicked.connect(lambda _checked=False: self._open_advanced_settings_step())
        nav.addWidget(self.settings_back_button)
        nav.addStretch(1)
        nav.addWidget(self.settings_advanced_button)
        nav.addWidget(self.settings_next_button)
        nav.addWidget(self.settings_save_button)
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
        self._sync_settings_stack_height()

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
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        provider_group = QGroupBox("Email Provider")
        provider_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        provider_group.setMaximumHeight(128)
        provider_layout = QVBoxLayout(provider_group)
        provider_layout.setSpacing(8)
        provider_layout.setContentsMargins(18, 16, 18, 16)
        self.gmail_enabled = QCheckBox("Gmail")
        self.gmail_enabled.setChecked(self.settings.gmail_enabled or self.settings.default_provider == "gmail")
        self.outlook_enabled = QCheckBox("Outlook (coming later)")
        self.outlook_enabled.setChecked(False)
        self.outlook_enabled.setEnabled(False)
        provider_layout.addWidget(self.gmail_enabled)
        provider_layout.addWidget(self.outlook_enabled)
        layout.addWidget(provider_group, 0, Qt.AlignmentFlag.AlignTop)
        return widget

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
        self.ollama_model_picker.currentIndexChanged.connect(self._refresh_ollama_model_hint)
        model_form.addRow("Model", self.ollama_model_picker)
        self.ollama_connection_status = QLabel("Checking Ollama...")
        self.ollama_connection_status.setStyleSheet("color: #5e6978; font-size: 13px;")
        model_form.addRow("Status", self.ollama_connection_status)
        model_layout.addLayout(model_form)
        self.ollama_models_hint = QLabel("")
        self.ollama_models_hint.setWordWrap(True)
        self.ollama_models_hint.setStyleSheet("color: #5e6978; font-size: 13px;")
        self.ollama_models_hint.hide()
        self.ollama_metadata_hint = QLabel(
            "The dropdown shows local model size and when Ollama last modified/downloaded the local copy."
        )
        self.ollama_metadata_hint.setWordWrap(True)
        self.ollama_metadata_hint.setStyleSheet("color: #5e6978; font-size: 13px;")
        model_layout.addWidget(self.ollama_metadata_hint)
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
        actions.addWidget(refresh_models_button)
        actions.addWidget(test_button)
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
        self.signature_input = QPlainTextEdit(self.settings.user_signature)
        self.signature_input.setPlaceholderText("Best regards,\nYour Name")
        self.signature_input.setMinimumHeight(110)
        self.signature_input.setMaximumHeight(140)
        self.signature_input.textChanged.connect(self._refresh_prompt_preview)
        signature_layout.addWidget(self.signature_input)
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
        self.poll_seconds_input = _wide_line_edit(str(self.settings.bot_poll_seconds), min_width=160)
        advanced_layout.addRow("Ollama URL", self.ollama_url_input)
        advanced_layout.addRow("Client secret", self.gmail_credentials_input)
        advanced_layout.addRow("Local token", self.gmail_token_input)
        advanced_layout.addRow("Poll interval (seconds)", self.poll_seconds_input)
        layout.addWidget(advanced_group)

        refresh_button = QPushButton("Check connection and refresh models")
        refresh_button.clicked.connect(self.refresh_models)
        layout.addWidget(refresh_button)
        return widget

    def _build_wizard_summary_page(self) -> QWidget:
        widget = QWidget()
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(widget)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.settings_summary = QPlainTextEdit()
        self.settings_summary.setReadOnly(True)
        self.settings_summary.setMinimumHeight(360)
        self.settings_summary.setMaximumHeight(360)
        self.settings_summary.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        font = QFont("Menlo")
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.settings_summary.setFont(font)
        layout.addWidget(self.settings_summary)
        return widget

    def _show_settings_step(self, index: int) -> None:
        self.settings_step_index = max(0, min(index, self.settings_stack.count() - 1))
        self.settings_stack.setCurrentIndex(self.settings_step_index)
        title, help_text, _advanced = self.settings_steps[self.settings_step_index]
        visible_indices = self._visible_settings_indices()
        visible_position = visible_indices.index(self.settings_step_index) + 1
        self.settings_step_label.setText(f"Step {visible_position} of {len(visible_indices)}")
        self.settings_step_title.setText(title)
        self.settings_step_help.setText(help_text)
        self.settings_step_help.setVisible(bool(help_text.strip()))
        self.settings_back_button.setEnabled(self.settings_step_index > 0)
        is_last = self._next_visible_settings_index(self.settings_step_index) == self.settings_step_index
        self.settings_next_button.setVisible(not is_last)
        self.settings_save_button.setVisible(is_last)
        self.settings_advanced_button.setVisible(self.settings_step_index == 3)
        self._refresh_settings_progress_line()
        if title == "Review Choices":
            self._refresh_prompt_preview()
            self._refresh_settings_summary()
        elif title == "Set Signature" and not self.gmail_signature_import_attempted:
            self.gmail_signature_import_attempted = True
            QTimer.singleShot(0, lambda: self._import_gmail_signature(force=False))
        self._sync_settings_stack_height()

    def _sync_settings_stack_height(self) -> None:
        if not hasattr(self, "settings_stack"):
            return
        if self.settings_stack.currentWidget() is None:
            return
        target_height = max(
            max(
                (self.settings_stack.widget(index).sizeHint().height() for index in range(self.settings_stack.count())),
                default=24,
            )
            + 8,
            397,
        )
        self.settings_stack.setMinimumHeight(target_height)
        self.settings_stack.setMaximumHeight(target_height)
        if hasattr(self, "settings_wizard"):
            self.settings_wizard.adjustSize()
            wizard_height = max(
                self.settings_wizard.sizeHint().height(),
                self.settings_wizard_stable_height,
                target_height + 96,
                569,
            )
            self.settings_wizard_stable_height = wizard_height
            self.settings_wizard.setMinimumHeight(wizard_height)
            self.settings_wizard.setMaximumHeight(wizard_height)
            self.settings_wizard.updateGeometry()
        if hasattr(self, "settings_group"):
            self.settings_group.adjustSize()
            group_height = max(
                self.settings_group.sizeHint().height(),
                self.settings_group_stable_height,
                self.settings_wizard_stable_height + 42,
                611,
            )
            self.settings_group_stable_height = group_height
            self.settings_group.setMinimumHeight(group_height)
            self.settings_group.setMaximumHeight(group_height)
            self.settings_group.updateGeometry()

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
        QApplication.processEvents()
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
        self.settings_group.setVisible(self.settings_open)
        self.settings_button.setVisible(not self.settings_open)
        self.control_group.setVisible(self.setup_finished and not self.settings_open)
        self.activity_group.setVisible(self.setup_finished and not self.settings_open)
        if self.settings_open:
            self._sync_settings_stack_height()

    def _restore_geometry_after_layout(self, geometry) -> None:
        self.setGeometry(geometry)
        QTimer.singleShot(0, lambda saved=geometry: self.setGeometry(saved))
        QTimer.singleShot(60, lambda saved=geometry: self.setGeometry(saved))

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
        provider = "gmail" if self.gmail_enabled.isChecked() else "outlook"
        signature_state = "Configured" if self.signature_input.toPlainText().strip() else "Missing"
        lines = [
            "MailAssist will use these settings:",
            "",
            f"Email provider: {provider.title()}",
            f"Local AI model: {selected_model}",
            f"Default tone: {self.tone_combo.currentText()}",
            f"Signature: {signature_state}",
            f"Check interval: every {self.poll_seconds_input.text().strip() or '60'} seconds",
            "",
            "MailAssist will watch for new mail and prepare drafts for messages that need a reply.",
            "",
            "Prompt preview (read-only)",
            "",
            self._prompt_preview_text(),
        ]
        self.settings_summary.setPlainText("\n".join(lines))

    def _build_ollama_settings_panel(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)

        model_group = QGroupBox("Local AI Model")
        model_layout = QVBoxLayout(model_group)
        model_layout.setSpacing(8)
        model_form = _configure_form(QFormLayout())
        self.ollama_model_picker = QComboBox()
        self.ollama_model_picker.currentIndexChanged.connect(self._refresh_ollama_model_hint)
        model_form.addRow("Model", self.ollama_model_picker)
        self.ollama_connection_status = QLabel("Checking Ollama...")
        self.ollama_connection_status.setStyleSheet("color: #5e6978; font-size: 13px;")
        model_form.addRow("Status", self.ollama_connection_status)
        model_layout.addLayout(model_form)

        self.ollama_models_hint = QLabel("")
        self.ollama_models_hint.setWordWrap(True)
        self.ollama_models_hint.setStyleSheet("color: #5e6978; font-size: 13px;")
        model_layout.addWidget(self.ollama_models_hint)

        self.ollama_model_hint = QLabel("")
        self.ollama_model_hint.setWordWrap(True)
        self.ollama_model_hint.setStyleSheet(
            "background: #fffaf4; border: 1px solid #dccbbb; border-radius: 10px; padding: 8px; color: #1d2430;"
        )
        model_layout.addWidget(self.ollama_model_hint)

        actions = QHBoxLayout()
        save_button = QPushButton("Save settings")
        save_button.clicked.connect(self.save_settings)
        refresh_models_button = QPushButton("Refresh model list")
        refresh_models_button.clicked.connect(self.refresh_models)
        test_button = QPushButton("Test selected model")
        test_button.clicked.connect(self.test_ollama)
        actions.addWidget(save_button)
        actions.addWidget(refresh_models_button)
        actions.addWidget(test_button)
        actions.addStretch(1)
        model_layout.addLayout(actions)
        layout.addWidget(model_group)

        advanced_group = QGroupBox("Advanced Connection")
        advanced_layout = _configure_form(QFormLayout(advanced_group))
        self.ollama_url_input = _wide_line_edit(self.settings.ollama_url)
        advanced_layout.addRow("Ollama URL", self.ollama_url_input)
        layout.addWidget(advanced_group)

        result_label = QLabel("Model check result")
        result_label.setStyleSheet("font-size: 13px; color: #5e6978;")
        layout.addWidget(result_label)
        self.ollama_result = QPlainTextEdit()
        self.ollama_result.setReadOnly(True)
        self.ollama_result.setMinimumHeight(90)
        layout.addWidget(self.ollama_result, 1)
        return widget

    def _refresh_ollama_model_hint(self) -> None:
        if not hasattr(self, "ollama_model_hint"):
            return
        model = str(self.ollama_model_picker.currentData() or self.settings.ollama_model)
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
        self.ollama_model_hint.setText(message)

    def _build_provider_settings_panel(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)

        provider_group = QGroupBox("Email Provider")
        provider_layout = _configure_form(QFormLayout(provider_group))
        self.default_provider_combo = QComboBox()
        self.default_provider_combo.addItem("Gmail", "gmail")
        self.default_provider_combo.addItem("Outlook", "outlook")
        self.default_provider_combo.setCurrentIndex(0 if self.settings.default_provider == "gmail" else 1)

        self.gmail_enabled = QCheckBox("Enable Gmail")
        self.gmail_enabled.setChecked(self.settings.gmail_enabled)
        self.outlook_enabled = QCheckBox("Enable Outlook (coming later)")
        self.outlook_enabled.setChecked(self.settings.outlook_enabled)
        self.outlook_enabled.setEnabled(False)
        provider_layout.addRow("Draft provider", self.default_provider_combo)
        provider_layout.addRow("", self.gmail_enabled)
        provider_layout.addRow("", self.outlook_enabled)
        layout.addWidget(provider_group)

        advanced_group = QGroupBox("Gmail OAuth Files")
        advanced_layout = _configure_form(QFormLayout(advanced_group))
        self.gmail_credentials_input = _wide_line_edit(str(self.settings.gmail_credentials_file), min_width=720)
        self.gmail_token_input = _wide_line_edit(str(self.settings.gmail_token_file), min_width=720)
        advanced_layout.addRow("Client secret", self.gmail_credentials_input)
        advanced_layout.addRow("Local token", self.gmail_token_input)
        layout.addWidget(advanced_group)

        save_button = QPushButton("Save provider settings")
        save_button.clicked.connect(self.save_settings)
        layout.addWidget(save_button)
        layout.addStretch(1)
        return widget

    def _build_signature_settings_panel(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)

        style_group = QGroupBox("Writing Style")
        style_layout = _configure_form(QFormLayout(style_group))
        self.tone_combo = QComboBox()
        for value, (label, _guidance) in TONE_OPTIONS.items():
            self.tone_combo.addItem(label, value)
        tone_index = self.tone_combo.findData(self.settings.user_tone)
        if tone_index >= 0:
            self.tone_combo.setCurrentIndex(tone_index)
        self.tone_combo.currentIndexChanged.connect(self._refresh_prompt_preview)
        self.poll_seconds_input = _wide_line_edit(str(self.settings.bot_poll_seconds), min_width=160)
        style_layout.addRow("Default tone", self.tone_combo)
        style_layout.addRow("Poll interval (seconds)", self.poll_seconds_input)
        layout.addWidget(style_group)

        intro = QLabel(
            "MailAssist appends this signature itself after the local model drafts the body. "
            "The model is asked not to write or modify the signature."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #5e6978; font-size: 13px;")
        layout.addWidget(intro)

        self.signature_input = QPlainTextEdit(self.settings.user_signature)
        self.signature_input.setPlaceholderText("Best regards,\nYour Name")
        self.signature_input.setMinimumHeight(120)
        self.signature_input.textChanged.connect(self._refresh_prompt_preview)
        layout.addWidget(self.signature_input)

        save_button = QPushButton("Save writing settings")
        save_button.clicked.connect(self.save_settings)
        layout.addWidget(save_button)
        layout.addStretch(1)
        return widget

    def _build_prompt_preview_panel(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)

        intro = QLabel(
            "Read-only preview of the bot drafting prompt. Real Gmail prompts use the actual "
            "incoming thread; this preview uses a sanitized sample email with your current tone. "
            "The saved signature is not included in the prompt because MailAssist appends it after drafting."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #5e6978; font-size: 13px;")
        layout.addWidget(intro)

        self.prompt_preview = QPlainTextEdit()
        self.prompt_preview.setReadOnly(True)
        self.prompt_preview.setMinimumHeight(360)
        font = QFont("Menlo")
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.prompt_preview.setFont(font)
        layout.addWidget(self.prompt_preview, 1)

        actions = QHBoxLayout()
        refresh_button = QPushButton("Refresh preview")
        refresh_button.clicked.connect(self._refresh_prompt_preview)
        actions.addWidget(refresh_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        self._refresh_prompt_preview()
        return widget

    def _refresh_prompt_preview(self) -> None:
        preview_text = self._prompt_preview_text()
        if hasattr(self, "prompt_preview"):
            self.prompt_preview.setPlainText(preview_text)
        if hasattr(self, "settings_summary"):
            self._refresh_settings_summary()

    def _prompt_preview_text(self) -> str:
        tone_key = str(self.tone_combo.currentData() or self.settings.user_tone)
        signature = self.signature_input.toPlainText().strip()
        return build_prompt_preview(
            tone_key=tone_key,
            signature=signature,
            user_facing=True,
        )

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

    def _current_view_is_regenerating_candidate(self) -> bool:
        editor = self._current_candidate_editor()
        return (
            self.candidate_regeneration_active
            and editor is not None
            and editor.thread_id == self.active_regeneration_thread_id
            and editor.candidate_id == self.active_regeneration_candidate_id
        )

    def _refresh_candidate_action_state(self) -> None:
        editor = self._current_candidate_editor()
        running = self._current_view_is_regenerating_candidate()
        if editor is not None:
            editor.setEnabled(not running)
        self.reset_candidate_button.setEnabled(not running)
        self.use_candidate_button.setEnabled(not running)
        self.ignore_thread_button.setEnabled(not running)
        self.close_thread_button.setEnabled(not running)
        self.regenerate_candidate_button.setEnabled(not self.candidate_regeneration_active or running)
        self.use_candidate_button.setVisible(not running)
        self.ignore_thread_button.setVisible(not running)
        self.close_thread_button.setVisible(not running)
        if running:
            if self.candidate_regeneration_seen_chunk:
                self.regenerate_candidate_button.setText("Streaming from Ollama...")
                self.candidate_action_status.setText(
                    "Streaming response from Ollama.\n"
                    f"{self.candidate_regeneration_char_count} characters received. "
                    "You can click another email and keep working while this finishes."
                )
            else:
                self.regenerate_candidate_button.setText("Waiting for Ollama...")
                self.candidate_action_status.setText(
                    "Waiting for Ollama to return the first chunk.\n"
                    "This can take a couple of minutes. You can click another email and keep working."
                )
            self.regenerate_candidate_button.setStyleSheet(
                "background: #d7e6f4; color: #1d2430; border: 1px solid #9fbad3; padding: 8px 16px;"
            )
            self.candidate_action_status.show()
        else:
            self.regenerate_candidate_button.setText("Regenerate with Ollama")
            self.regenerate_candidate_button.setStyleSheet("")
            self.candidate_action_status.hide()
            self.candidate_action_status.setText("")

    def _start_fake_progress(self, label: str) -> None:
        self.active_progress_label = label
        self.fake_progress_value = 0
        self.candidate_regeneration_active = True
        self.candidate_regeneration_seen_chunk = False
        self.candidate_regeneration_char_count = 0
        self.candidate_regeneration_body = ""
        self.banner.hide()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFormat(self.active_progress_label)
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self._refresh_status_overlay_visibility()
        self._refresh_candidate_action_state()
        self.progress_timer.start()

    def _advance_fake_progress(self) -> None:
        if self.candidate_regeneration_seen_chunk:
            self.progress_bar.setFormat(
                f"{self.active_progress_label} Streaming... {self.candidate_regeneration_char_count} chars"
            )
        else:
            self.progress_bar.setFormat(
                f"{self.active_progress_label} Waiting for first chunk..."
            )
        self._refresh_candidate_action_state()

    def _finish_fake_progress(self) -> None:
        self.progress_timer.stop()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setFormat(self.active_progress_label)
        self.progress_bar.setValue(100)
        self.progress_bar.hide()
        self.active_progress_label = ""
        self.candidate_regeneration_active = False
        self.candidate_regeneration_seen_chunk = False
        self.candidate_regeneration_char_count = 0
        self.candidate_regeneration_body = ""
        self._refresh_status_overlay_visibility()
        self._refresh_candidate_action_state()

    def _review_state_needs_sync(self) -> bool:
        return any(not thread_state.get("candidates") for thread_state in self.review_state.get("threads", []))

    def _current_bot_ollama_settings(self) -> tuple[str, str]:
        base_url = self.ollama_url_input.text().strip() or self.settings.ollama_url
        selected_model = str(self.ollama_model_picker.currentData() or self.settings.ollama_model).strip()
        return base_url, selected_model

    def _hide_detail_panel(self, message: str) -> None:
        self.detail_panel.hide()
        self.detail_placeholder.setText(message)
        self.detail_placeholder.show()

    def _show_detail_panel(self) -> None:
        self.detail_placeholder.hide()
        self.detail_panel.show()

    def refresh_dashboard(self) -> None:
        if hasattr(self, "provider_status_label"):
            self.provider_status_label.setText(self.settings.default_provider)
            self.ollama_status_label.setText(self.settings.ollama_model)
            self.tone_status_label.setText(tone_label(self.settings.user_tone))
            self.signature_status_label.setText(
                "Configured" if self.settings.user_signature.strip() else "Missing"
            )
            self.last_activity_label.setText(self.last_activity_summary)
            self.bot_status_label.setText("Running" if self.bot_process is not None else "Idle")

    def _append_recent_activity(self, message: str) -> None:
        if not hasattr(self, "recent_activity"):
            return
        if self.recent_activity.toPlainText().strip() == "No bot activity yet.":
            self.recent_activity.clear()
        self.recent_activity.appendPlainText(message)
        self.last_activity_summary = message
        self.refresh_dashboard()

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

    def refresh_models(self) -> None:
        model_details, model_error = self._list_available_model_details()
        models = [str(item.get("name", "")).strip() for item in model_details if item.get("name")]
        self.ollama_model_details = {
            str(item.get("name", "")).strip(): item for item in model_details if item.get("name")
        }
        self.ollama_model_picker.blockSignals(True)
        self.ollama_model_picker.clear()
        if models:
            for model_detail in model_details:
                model = str(model_detail.get("name", "")).strip()
                if model:
                    self.ollama_model_picker.addItem(_model_display_label(model_detail), model)
            picker_index = self.ollama_model_picker.findData(self.settings.ollama_model)
            if picker_index >= 0:
                self.ollama_model_picker.setCurrentIndex(picker_index)
        else:
            self.ollama_model_picker.addItem("No local models found", "")
        self.ollama_model_picker.blockSignals(False)
        if models:
            self.ollama_connection_status.setText(f"Connected, {len(models)} installed")
            self.ollama_connection_status.setStyleSheet("color: #215f4a; font-size: 13px;")
            self.ollama_models_hint.setText(f"Found {len(models)} installed model(s).")
        else:
            self.ollama_connection_status.setText("No models found")
            self.ollama_connection_status.setStyleSheet("color: #8c4029; font-size: 13px;")
            self.ollama_models_hint.setText("No installed Ollama models were detected.")
        if model_error:
            self.ollama_connection_status.setText("Not reachable")
            self.ollama_connection_status.setStyleSheet("color: #8c4029; font-size: 13px;")
            if not self.ollama_result.toPlainText().startswith("Sending a tiny test prompt"):
                self._set_ollama_result_text(model_error)
        elif not models and not self.ollama_result.toPlainText().strip():
            self.ollama_result.clear()
        self._refresh_ollama_model_hint()

    def _list_available_model_details(self) -> tuple[list[dict[str, Any]], str]:
        base_url = self.ollama_url_input.text().strip()
        selected_model = self.settings.ollama_model
        try:
            return OllamaClient(base_url, selected_model).list_model_details(), ""
        except RuntimeError as exc:
            return [], str(exc)

    def _set_ollama_result_text(self, text: str) -> None:
        self.ollama_result.setPlainText(text)
        self.ollama_result_label.show()
        self.ollama_result.show()
        self._sync_settings_stack_height()

    def current_context(self) -> dict[str, str]:
        return {
            "filter_classification": str(self.classification_filter.currentData()),
            "filter_status": str(self.status_filter.currentData()),
            "show_archived": "true" if self.show_archived.isChecked() else "false",
        }

    def visible_threads(self) -> list[dict[str, Any]]:
        context = self.current_context()
        return filtered_and_sorted_threads(
            self.review_state["threads"],
            filter_classification=context["filter_classification"],
            filter_status=context["filter_status"],
            sort_order="received_at",
            show_archived=context["show_archived"] == "true",
        )

    def _populate_thread_row(self, row_index: int, thread_state: dict[str, Any]) -> None:
        classification = normalize_classification(thread_state.get("classification"))
        status = normalize_review_status(thread_state.get("status"))
        _, foreground = CLASSIFICATION_TINTS.get(
            classification,
            CLASSIFICATION_TINTS["unclassified"],
        )
        row_background = QColor(ROW_BACKGROUNDS[row_index % len(ROW_BACKGROUNDS)])
        row_foreground = QColor(foreground)
        if status == "use_draft":
            row_foreground = QColor("#215f4a")
        elif status == "ignored":
            row_foreground = QColor("#8c4029")
        elif status == "user_replied":
            row_foreground = QColor("#2f6da3")

        font = QFont()
        font.setBold(status == "pending_review")

        status_suffix = ""
        if status == "use_draft":
            status_suffix = " [Draft selected]"
        elif status == "ignored":
            status_suffix = " [Ignored]"
        elif status == "user_replied":
            status_suffix = " [User replied]"
        if thread_state.get("archived"):
            status_suffix += " [Archived]"
        sender = _sender_label(thread_state)
        received_at = _received_label(thread_state)
        classification_label = _humanize(classification)
        tooltip = "\n".join(
            [
                f"Classification: {classification_label}",
                f"Received: {received_at}",
                f"Sender: {sender}",
                f"Status: {_status_label(status)}",
            ]
        )
        checked = bool(
            thread_state.get(
                "archive_selected",
                normalize_review_status(thread_state.get("status")) in {
                    "use_draft",
                    "ignored",
                    "user_replied",
                },
            )
        )

        check_item = SortableTableItem("")
        check_item.setData(THREAD_ID_ROLE, thread_state["thread_id"])
        check_item.setData(SORT_VALUE_ROLE, 1 if checked else 0)
        check_item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsUserCheckable
        )
        check_item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

        subject_item = SortableTableItem(f"{thread_state['subject']}{status_suffix}")
        subject_item.setData(THREAD_ID_ROLE, thread_state["thread_id"])
        subject_item.setData(SORT_VALUE_ROLE, thread_state["subject"].lower())

        classification_item = SortableTableItem(classification_label)
        classification_item.setData(THREAD_ID_ROLE, thread_state["thread_id"])
        classification_item.setData(SORT_VALUE_ROLE, classification_label.lower())

        received_item = SortableTableItem(received_at)
        received_item.setData(THREAD_ID_ROLE, thread_state["thread_id"])
        received_item.setData(SORT_VALUE_ROLE, str(_latest_message(thread_state).get("sent_at", "")))

        sender_item = SortableTableItem(sender)
        sender_item.setData(THREAD_ID_ROLE, thread_state["thread_id"])
        sender_item.setData(SORT_VALUE_ROLE, sender.lower())

        for column, item in (
            (CHECK_COLUMN, check_item),
            (SUBJECT_COLUMN, subject_item),
            (CLASSIFICATION_COLUMN, classification_item),
            (RECEIVED_COLUMN, received_item),
            (SENDER_COLUMN, sender_item),
        ):
            item.setBackground(row_background)
            item.setForeground(row_foreground)
            item.setFont(font)
            item.setToolTip(tooltip)
            self.thread_table.setItem(row_index, column, item)

    def refresh_queue(self) -> None:
        visible = self.visible_threads()
        selected_thread_id = self.current_thread_id

        self.thread_table.blockSignals(True)
        self.thread_table.setSortingEnabled(False)
        self.thread_table.clearContents()
        self.thread_table.setRowCount(len(visible))
        for index, thread_state in enumerate(visible):
            self._populate_thread_row(index, thread_state)
            self.thread_table.setRowHeight(index, INBOX_ROW_HEIGHT)
        self.thread_table.setSortingEnabled(True)
        self.thread_table.sortByColumn(self.table_sort_column, self.table_sort_order)
        self.thread_table.blockSignals(False)

        if not visible:
            self.current_thread_id = ""
            self._hide_detail_panel("No emails match the current filters.")
            return

        if not selected_thread_id:
            self.thread_table.clearSelection()
            self._hide_detail_panel("Select an email to review.")
            return

        for row_index in range(self.thread_table.rowCount()):
            item = self.thread_table.item(row_index, SUBJECT_COLUMN)
            if item is not None and item.data(THREAD_ID_ROLE) == selected_thread_id:
                self.thread_table.selectRow(row_index)
                return

        self.current_thread_id = ""
        self.thread_table.clearSelection()
        self._hide_detail_panel("Select an email to review.")

    def _handle_thread_selection(self) -> None:
        selected_rows = self.thread_table.selectionModel().selectedRows() if self.thread_table.selectionModel() else []
        if not selected_rows:
            self.current_thread_id = ""
            self._hide_detail_panel("Select an email to review.")
            return
        current = self.thread_table.item(selected_rows[0].row(), SUBJECT_COLUMN)
        if current is None:
            self.current_thread_id = ""
            self._hide_detail_panel("Select an email to review.")
            return
        self.current_thread_id = str(current.data(THREAD_ID_ROLE))
        self.render_current_thread()

    def _handle_thread_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != CHECK_COLUMN:
            return
        thread_id = item.data(THREAD_ID_ROLE)
        if not thread_id:
            return
        thread_state, _ = find_thread_state(self.review_state, str(thread_id))
        thread_state["archive_selected"] = item.checkState() == Qt.CheckState.Checked
        save_review_state(self.settings.root_dir, self.review_state)

    def _handle_table_sort_changed(self, section: int, order: Qt.SortOrder) -> None:
        self.table_sort_column = section
        self.table_sort_order = order

    def render_current_thread(self) -> None:
        if not self.current_thread_id:
            self._hide_detail_panel("Select an email to review.")
            return

        thread_state, _ = find_thread_state(self.review_state, self.current_thread_id)
        thread = payload_to_thread(thread_state["thread"])
        classification = normalize_classification(thread_state.get("classification"))

        self.thread_title.setText(thread.subject)
        if classification in SET_ASIDE_CLASSIFICATIONS:
            self.candidates_group.hide()
            self.candidate_actions_panel.hide()
        else:
            self.candidates_group.show()
            self.candidate_actions_panel.show()

        message_chunks = []
        for index, message in enumerate(thread.messages, start=1):
            message_chunks.append(
                "\n".join(
                    [
                        f"Message {index}",
                        f"From: {message.sender}",
                        f"To: {', '.join(message.to)}",
                        f"Sent: {message.sent_at}",
                        "",
                        message.text,
                    ]
                )
            )
        self.thread_body.setPlainText(("\n\n" + ("-" * 60) + "\n\n").join(message_chunks))

        self.candidate_tabs.clear()
        if classification not in SET_ASIDE_CLASSIFICATIONS:
            selected_candidate_id = thread_state.get("selected_candidate_id")
            selected_index = 0
            for index, candidate in enumerate(thread_state.get("candidates", [])):
                editor = CandidateEditor(
                    thread_state,
                    candidate,
                    self.autosave_candidate,
                    self.reset_candidate,
                    self.use_candidate,
                    self.ignore_current_thread,
                    self.close_current_thread,
                    self.regenerate_candidate_from_editor,
                )
                if (
                    self.candidate_regeneration_active
                    and self.current_thread_id == self.active_regeneration_thread_id
                    and candidate["candidate_id"] == self.active_regeneration_candidate_id
                ):
                    editor.replace_text(self.candidate_regeneration_body)
                self.candidate_tabs.addTab(editor, candidate["label"])
                if candidate["candidate_id"] == selected_candidate_id:
                    selected_index = index
            if self.candidate_tabs.count():
                self.candidate_tabs.setCurrentIndex(selected_index)
            self._refresh_candidate_action_state()

        self._show_detail_panel()

    def autosave_candidate(self, thread_id: str, candidate_id: str, editor: CandidateEditor) -> None:
        thread_state, _ = find_thread_state(self.review_state, thread_id)
        try:
            candidate = update_candidate(thread_state, candidate_id, editor.current_text(), "save")
            save_review_state(self.settings.root_dir, self.review_state)
        except ValueError as exc:
            self._set_banner(str(exc), level="error")
            return
        editor.mark_saved_text(candidate["body"])

    def _current_candidate_editor(self) -> CandidateEditor | None:
        widget = self.candidate_tabs.currentWidget()
        if isinstance(widget, CandidateEditor):
            return widget
        return None

    def reset_selected_candidate(self) -> None:
        editor = self._current_candidate_editor()
        if editor is None:
            self._set_banner("Select a draft before resetting it.", level="error")
            return
        self.reset_candidate(editor.thread_id, editor.candidate_id, editor)

    def use_selected_candidate(self) -> None:
        editor = self._current_candidate_editor()
        if editor is None:
            self._set_banner("Select a draft before using it.", level="error")
            return
        self.use_candidate(editor.thread_id, editor.candidate_id, editor)

    def regenerate_selected_candidate(self) -> None:
        editor = self._current_candidate_editor()
        if editor is None:
            self._set_banner("Select a draft before regenerating it.", level="error")
            return
        self.regenerate_candidate_from_editor(editor.thread_id, editor.candidate_id, editor)

    def reset_candidate(self, thread_id: str, candidate_id: str, editor: CandidateEditor) -> None:
        thread_state, _ = find_thread_state(self.review_state, thread_id)
        candidate = next(
            (item for item in thread_state.get("candidates", []) if item["candidate_id"] == candidate_id),
            None,
        )
        if candidate is None:
            self._set_banner("Candidate not found.", level="error")
            return

        try:
            updated = update_candidate(
                thread_state,
                candidate_id,
                candidate.get("original_body", ""),
                "reset",
            )
            save_review_state(self.settings.root_dir, self.review_state)
        except ValueError as exc:
            self._set_banner(str(exc), level="error")
            return

        editor.replace_text(updated["body"])
        self._set_banner("Draft reset to the original proposal.", level="info")

    def use_candidate(self, thread_id: str, candidate_id: str, editor: CandidateEditor) -> None:
        thread_state, _ = find_thread_state(self.review_state, thread_id)
        try:
            update_candidate(thread_state, candidate_id, editor.current_text(), "use_this")
            save_review_state(self.settings.root_dir, self.review_state)
        except ValueError as exc:
            self._set_banner(str(exc), level="error")
            return

        self._set_banner("Draft selected.", level="info")
        self.current_thread_id = ""
        self.thread_table.blockSignals(True)
        self.thread_table.clearSelection()
        self.thread_table.blockSignals(False)
        self.refresh_queue()

    def regenerate_candidate_from_editor(
        self,
        thread_id: str,
        candidate_id: str,
        editor: CandidateEditor,
    ) -> None:
        if self.candidate_regeneration_thread is not None:
            self._set_banner(
                "An Ollama draft refresh is already running. These can take 1-2 minutes.",
                level="error",
            )
            return

        self.current_thread_id = thread_id
        self.active_regeneration_editor = editor
        self.active_regeneration_thread_id = thread_id
        self.active_regeneration_candidate_id = candidate_id
        self.candidate_regeneration_body = ""
        self.active_regeneration_editor.setEnabled(False)
        self.active_regeneration_editor.replace_text("")
        save_review_state(self.settings.root_dir, self.review_state)
        base_url, selected_model = self._current_bot_ollama_settings()
        self.candidate_regeneration_thread = QThread(self)
        self.candidate_regeneration_worker = CandidateRegenerationWorker(
            root_dir=self.settings.root_dir,
            thread_id=thread_id,
            candidate_id=candidate_id,
            base_url=base_url,
            selected_model=selected_model,
        )
        self.candidate_regeneration_worker.moveToThread(self.candidate_regeneration_thread)
        self.candidate_regeneration_thread.started.connect(self.candidate_regeneration_worker.run)
        self.candidate_regeneration_worker.partial_body.connect(self._handle_candidate_regeneration_stream)
        self.candidate_regeneration_worker.finished.connect(self._handle_candidate_regeneration_finished)
        self.candidate_regeneration_worker.failed.connect(self._handle_candidate_regeneration_failed)
        self.candidate_regeneration_worker.finished.connect(self.candidate_regeneration_thread.quit)
        self.candidate_regeneration_worker.failed.connect(self.candidate_regeneration_thread.quit)
        self.candidate_regeneration_thread.finished.connect(self._cleanup_candidate_regeneration)

        self._start_fake_progress(
            "Generating a new alternate with Ollama. This can take 1-2 minutes, but the window should stay responsive."
        )
        self.candidate_regeneration_thread.start()

    def _handle_candidate_regeneration_stream(
        self,
        thread_id: str,
        candidate_id: str,
        chunk: str,
    ) -> None:
        if (
            thread_id != self.active_regeneration_thread_id
            or candidate_id != self.active_regeneration_candidate_id
        ):
            return
        self.candidate_regeneration_seen_chunk = True
        self.candidate_regeneration_char_count += len(chunk)
        self.candidate_regeneration_body += chunk
        self._refresh_candidate_action_state()
        editor = self._current_candidate_editor()
        if self._current_view_is_regenerating_candidate() and editor is not None:
            editor.append_text(chunk)
        QApplication.processEvents()

    def _handle_candidate_regeneration_finished(
        self,
        thread_id: str,
        candidate_id: str,
        label: str,
    ) -> None:
        self._finish_fake_progress()
        self.settings = load_settings()
        self.review_state = load_review_state(self.settings.root_dir)
        self.current_thread_id = thread_id
        self.refresh_models()
        self.refresh_queue()
        self.render_current_thread()
        self._set_banner(f"Generated a new {label.lower()} draft option.", level="info")

    def _handle_candidate_regeneration_failed(self, message: str) -> None:
        self._finish_fake_progress()
        self.review_state = load_review_state(self.settings.root_dir)
        self.refresh_queue()
        self.render_current_thread()
        self._set_banner(message, level="error")

    def _cleanup_candidate_regeneration(self) -> None:
        if self.candidate_regeneration_worker is not None:
            self.candidate_regeneration_worker.deleteLater()
        if self.candidate_regeneration_thread is not None:
            self.candidate_regeneration_thread.deleteLater()
        self.candidate_regeneration_worker = None
        self.candidate_regeneration_thread = None
        self.active_regeneration_editor = None
        self.active_regeneration_thread_id = ""
        self.active_regeneration_candidate_id = ""
        self.candidate_regeneration_active = False
        self.candidate_regeneration_body = ""
        self._refresh_candidate_action_state()

    def close_current_thread(self) -> None:
        self.current_thread_id = ""
        self.thread_table.blockSignals(True)
        self.thread_table.clearSelection()
        self.thread_table.blockSignals(False)
        self._hide_detail_panel("Select an email to review.")

    def ignore_current_thread(self, thread_id: str | None = None) -> None:
        if thread_id:
            self.current_thread_id = thread_id
        if not self.current_thread_id:
            self._set_banner("Select an email before ignoring it.", level="error")
            return
        thread_state, _ = find_thread_state(self.review_state, self.current_thread_id)
        try:
            update_thread_status(thread_state, "ignore")
            save_review_state(self.settings.root_dir, self.review_state)
        except ValueError as exc:
            self._set_banner(str(exc), level="error")
            return
        self._set_banner("Email marked ignored.", level="info")
        self.close_current_thread()
        self.refresh_queue()

    def archive_checked_threads(self) -> None:
        archived_subjects = []
        for thread_state in self.review_state.get("threads", []):
            if thread_state.get("archived"):
                continue
            if not thread_state.get("archive_selected"):
                continue
            update_thread_status(thread_state, "archive")
            archived_subjects.append(thread_state["subject"])

        if not archived_subjects:
            self._set_banner("No checked emails were ready to archive.", level="error")
            return

        save_review_state(self.settings.root_dir, self.review_state)
        if self.current_thread_id and any(
            item["thread_id"] == self.current_thread_id and item.get("archived")
            for item in self.review_state.get("threads", [])
        ):
            self.close_current_thread()
        self.refresh_queue()
        self._set_banner(f"Archived {len(archived_subjects)} email(s).", level="info")

    def regenerate_current_thread(self) -> None:
        if not self.current_thread_id:
            self._set_banner("Select an email before refreshing candidates.", level="error")
            return
        self.run_bot_action("regenerate-thread", thread_id=self.current_thread_id)

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
        poll_seconds = self.poll_seconds_input.text().strip() or "60"
        setup_complete = "true" if mark_complete else ("true" if self.setup_finished else "false")
        provider = "gmail" if self.gmail_enabled.isChecked() else "outlook"
        current.update(
            {
                "MAILASSIST_OLLAMA_URL": self.ollama_url_input.text().strip() or "http://localhost:11434",
                "MAILASSIST_OLLAMA_MODEL": selected_model,
                "MAILASSIST_USER_SIGNATURE": self.signature_input.toPlainText().strip().replace("\n", "\\n"),
                "MAILASSIST_USER_TONE": str(self.tone_combo.currentData() or "direct_concise"),
                "MAILASSIST_BOT_POLL_SECONDS": poll_seconds,
                "MAILASSIST_DEFAULT_PROVIDER": provider,
                "MAILASSIST_GMAIL_ENABLED": "true" if self.gmail_enabled.isChecked() else "false",
                "MAILASSIST_OUTLOOK_ENABLED": "true" if self.outlook_enabled.isChecked() else "false",
                "MAILASSIST_GMAIL_CREDENTIALS_FILE": self.gmail_credentials_input.text().strip(),
                "MAILASSIST_GMAIL_TOKEN_FILE": self.gmail_token_input.text().strip(),
                "MAILASSIST_OUTLOOK_CLIENT_ID": current.get("MAILASSIST_OUTLOOK_CLIENT_ID", ""),
                "MAILASSIST_OUTLOOK_TENANT_ID": current.get("MAILASSIST_OUTLOOK_TENANT_ID", ""),
                "MAILASSIST_OUTLOOK_REDIRECT_URI": current.get(
                    "MAILASSIST_OUTLOOK_REDIRECT_URI",
                    "http://localhost:8765/outlook/callback",
                ),
                "MAILASSIST_SETUP_COMPLETE": setup_complete,
            }
        )
        write_env_file(env_file, current)
        self.settings = load_settings()
        if mark_complete:
            geometry = self.geometry()
            self.setup_finished = True
            self.settings_open = False
        self.refresh_models()
        self.refresh_dashboard()
        self._refresh_prompt_preview()
        self._refresh_setup_visibility()
        if mark_complete:
            self._restore_geometry_after_layout(geometry)
        if announce:
            self._set_banner("Settings saved.", level="info")

    def finish_settings_wizard(self) -> None:
        self.save_settings(announce=True, mark_complete=True)
        self._set_banner("Settings finished. Bot controls are now available.", level="info")

    def test_ollama(self) -> None:
        prompt = "Reply with one short sentence confirming MailAssist can use this model."
        model = str(self.ollama_model_picker.currentData() or self.settings.ollama_model)
        self._set_ollama_result_text(
            f"Sending a tiny test prompt to {model}...\n\nPrompt: {prompt}\n\nResponse: waiting..."
        )
        self._set_banner("Sending a small test prompt to Ollama. This can take a moment.", level="info")
        QApplication.processEvents()
        self.run_bot_action("ollama-check", prompt=prompt)

    def run_mock_watch_once(self) -> None:
        self.run_bot_action("watch-once", provider="mock")

    def run_gmail_draft_test(self) -> None:
        self.run_bot_action("watch-once", provider="gmail", thread_id="thread-008", force=True)

    def run_queue_status(self) -> None:
        self.run_bot_action("queue-status")

    def run_bot_action(
        self,
        action: str,
        *,
        thread_id: str = "",
        prompt: str = "",
        provider: str = "",
        force: bool = False,
    ) -> None:
        if self.bot_process is not None:
            self._set_banner("A bot action is already running.", level="error")
            return

        base_url, selected_model = self._current_bot_ollama_settings()
        self.bot_stdout_buffer = ""
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

        self._append_bot_console(f"$ {sys.executable} {' '.join(args)}")
        self._set_banner(
            f"Starting bot action: {action}. Ollama work can take 1-2 minutes.",
            level="info",
        )
        self.bot_status_label.setText("Running")
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
            if prompt:
                self._set_ollama_result_text(f"Prompt: {prompt}\n\nResponse: {result}")
            else:
                self._set_ollama_result_text(f"Response: {result}")
        elif event_type == "draft_created":
            self._append_recent_activity(
                f"Draft created: {event.get('subject', 'Unknown subject')} ({event.get('classification', 'unclassified')})"
            )
        elif event_type == "skipped_email":
            self._append_recent_activity(
                f"Skipped: {event.get('subject', 'Unknown subject')} ({event.get('classification', 'unclassified')})"
            )
        elif event_type == "already_handled":
            self._append_recent_activity(
                f"Already handled: {event.get('subject', 'Unknown subject')}"
            )
        elif event_type == "queue_status":
            counts = event.get("counts", {})
            self._append_recent_activity(f"Queue status: {counts}")
        elif event_type == "completed":
            self._set_banner(str(event.get("message", "Bot action completed.")), level="info")
            self.settings = load_settings()
            self.refresh_models()
            self.refresh_bot_logs()
            self.refresh_dashboard()
            if "draft_count" in event:
                self._append_recent_activity(
                    f"Watch pass: {event.get('draft_count', 0)} drafts, "
                    f"{event.get('skipped_count', 0)} skipped, "
                    f"{event.get('already_handled_count', 0)} already handled."
                )
        elif event_type == "error":
            self._set_banner(str(event.get("message", "Bot action failed.")), level="error")
        elif event_type == "info":
            self._set_banner(str(event.get("message", "")), level="info")

    def _handle_bot_finished(self, exit_code: int, _exit_status) -> None:
        if self.bot_stdout_buffer.strip():
            self._append_bot_console(self.bot_stdout_buffer.strip())
            self.bot_stdout_buffer = ""
        if exit_code != 0:
            self._set_banner(f"Bot action exited with code {exit_code}.", level="error")
        self.bot_process = None
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
                ("processed_count", "Processed"),
                ("message_count", "Messages read"),
                ("generated_threads", "Drafts refreshed"),
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
        if event_type == "processed_email":
            detail = f'Processed "{subject}" for GUI review.' if subject else "Processed an email for GUI review."
            if classification:
                detail += f" Classification: {_humanize(classification)}."
            return detail
        if event_type == "gmail_message_preview":
            sender = event.get("sender") or event.get("from") or "unknown sender"
            return f'Previewed Gmail message "{subject or event.get("snippet", "")}" from {sender}.'
        if event_type == "queue_status":
            counts = event.get("counts")
            if isinstance(counts, dict):
                readable = ", ".join(f"{_humanize(str(key))}: {value}" for key, value in counts.items())
                return f"Queue status: {readable}."
            return "Read queue status."
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
