from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QProcess, QThread, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont
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
    QGridLayout,
    QProgressBar,
    QPushButton,
    QPlainTextEdit,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from mailassist.config import load_settings, read_env_file, write_env_file
from mailassist.gui.server import (
    FILTER_LABELS,
    SET_ASIDE_CLASSIFICATIONS,
    STATUS_FILTER_LABELS,
    filtered_and_sorted_threads,
    find_thread_state,
    list_available_models,
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
        layout.setSpacing(10)

        meta = QLabel(
            f"{candidate['tone']} | {_humanize(candidate.get('classification', 'unclassified'))}"
        )
        meta.setStyleSheet("color: #5e6978; font-size: 13px;")
        layout.addWidget(meta)

        hint = QLabel("Changes auto-save. Reset returns to the original proposal.")
        hint.setStyleSheet("color: #8a7666; font-size: 12px;")
        layout.addWidget(hint)

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
        self.progress_timer = QTimer(self)
        self.progress_timer.setInterval(180)
        self.progress_timer.timeout.connect(self._advance_fake_progress)
        self.fake_progress_value = 0
        self.table_sort_column = RECEIVED_COLUMN
        self.table_sort_order = Qt.SortOrder.DescendingOrder

        self.setWindowTitle(f"MailAssist v{load_visible_version(self.settings.root_dir)}")
        self.resize(1440, 980)

        self._build_ui()
        self.refresh_models()
        self.refresh_bot_logs()
        self.refresh_queue()
        if self._review_state_needs_sync():
            self.run_bot_action("sync-review-state")

    def _build_ui(self) -> None:
        root = QWidget()
        shell = QVBoxLayout(root)
        shell.setContentsMargins(18, 18, 18, 18)
        shell.setSpacing(14)

        hero = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("MailAssist Desktop Review")
        title.setStyleSheet("font-size: 34px; font-weight: 700; color: #1d2430;")
        subtitle = QLabel(
            "One inbox list, color-coded triage, and side-by-side review when you open a thread."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("font-size: 15px; color: #5e6978;")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        hero.addLayout(title_box, 1)

        self.version_label = QLabel(f"v{load_visible_version(self.settings.root_dir)}")
        self.version_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.version_label.setStyleSheet(
            "border: 1px solid #dccbbb; border-radius: 16px; padding: 8px 12px; color: #5e6978;"
        )
        settings_button = QPushButton("\u2699")
        settings_button.setFixedSize(42, 42)
        settings_button.setStyleSheet(
            "font-size: 20px; border: 1px solid #dccbbb; border-radius: 21px; background: #fffaf4; color: #5e6978;"
        )
        settings_button.clicked.connect(self.open_settings_dialog)
        logs_button = QPushButton("Logs")
        logs_button.setStyleSheet(
            "border: 1px solid #dccbbb; border-radius: 18px; padding: 8px 14px; background: #fffaf4; color: #5e6978;"
        )
        logs_button.clicked.connect(self.open_bot_logs_dialog)
        hero.addWidget(logs_button)
        hero.addWidget(settings_button)
        hero.addWidget(self.version_label)
        shell.addLayout(hero)

        self.status_overlay = QWidget()
        self.status_overlay.hide()
        status_layout = QGridLayout(self.status_overlay)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(0)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        self.progress_bar.setMinimumHeight(44)
        self.progress_bar.setStyleSheet(
            "QProgressBar { border: 1px solid #dccbbb; border-radius: 12px; background: #fffaf4; padding: 2px; }"
            "QProgressBar::chunk { background: #2f6da3; border-radius: 10px; }"
        )
        status_layout.addWidget(self.progress_bar, 0, 0)

        self.banner = QLabel("")
        self.banner.hide()
        self.banner.setStyleSheet(
            "padding: 10px 12px; border-radius: 12px; background: rgba(33,95,74,0.12); color: #215f4a;"
        )
        status_layout.addWidget(self.banner, 0, 0)
        shell.addWidget(self.status_overlay)

        controls = QHBoxLayout()
        inbox_label = QLabel("Inbox")
        inbox_label.setStyleSheet("font-size: 22px; font-weight: 700; color: #1d2430;")
        controls.addWidget(inbox_label)
        archive_checked_button = QPushButton("Archive Checked")
        archive_checked_button.clicked.connect(self.archive_checked_threads)
        controls.addWidget(archive_checked_button)
        controls.addStretch(1)

        self.classification_filter = QComboBox()
        for value, label in FILTER_LABELS.items():
            self.classification_filter.addItem(label, value)
        self.classification_filter.currentIndexChanged.connect(self.refresh_queue)

        self.status_filter = QComboBox()
        for value, label in STATUS_FILTER_LABELS.items():
            self.status_filter.addItem(label, value)
        self.status_filter.currentIndexChanged.connect(self.refresh_queue)

        self.show_archived = QCheckBox("Show archived")
        self.show_archived.stateChanged.connect(self.refresh_queue)

        for label_text, widget in (
            ("Filter", self.classification_filter),
            ("Status", self.status_filter),
        ):
            label = QLabel(label_text)
            label.setStyleSheet("color: #5e6978; font-size: 12px;")
            controls.addWidget(label)
            controls.addWidget(widget)
        controls.addWidget(self.show_archived)
        shell.addLayout(controls)

        self.thread_table = QTableWidget(0, 5)
        self.thread_table.setHorizontalHeaderLabels(
            ["", "Subject", "Classification", "Received", "Sender"]
        )
        self.thread_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.thread_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.thread_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.thread_table.setWordWrap(False)
        self.thread_table.setShowGrid(True)
        self.thread_table.setAlternatingRowColors(True)
        self.thread_table.verticalHeader().setVisible(False)
        self.thread_table.setSortingEnabled(True)
        self.thread_table.itemSelectionChanged.connect(self._handle_thread_selection)
        self.thread_table.itemChanged.connect(self._handle_thread_item_changed)
        self.thread_table.horizontalHeader().sortIndicatorChanged.connect(self._handle_table_sort_changed)
        header = self.thread_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        header.setSectionResizeMode(CHECK_COLUMN, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(SUBJECT_COLUMN, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(CLASSIFICATION_COLUMN, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(RECEIVED_COLUMN, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(SENDER_COLUMN, QHeaderView.ResizeMode.Stretch)
        self.thread_table.setStyleSheet(
            "QTableWidget { border: 1px solid #dccbbb; border-radius: 14px; background: #fffaf4; "
            "alternate-background-color: #ecdcca; gridline-color: #dccbbb; }"
            "QTableWidget::item { padding: 8px 10px; }"
            "QTableWidget::item:selected { background: #dbe7f2; color: #1d2430; }"
            "QTableWidget::indicator { width: 21px; height: 21px; }"
            "QHeaderView::section { background: #efe4d6; color: #5e6978; padding: 8px 10px; "
            "border: 0; border-bottom: 1px solid #dccbbb; font-weight: 700; }"
        )
        self.queue_detail_splitter = QSplitter(Qt.Vertical)
        self.queue_detail_splitter.setChildrenCollapsible(True)
        self.queue_detail_splitter.addWidget(self.thread_table)
        self.thread_table.setMinimumHeight(150)

        self.detail_container = QWidget()
        self.detail_container.setMinimumHeight(140)
        detail_container_layout = QVBoxLayout(self.detail_container)
        detail_container_layout.setContentsMargins(0, 0, 0, 0)
        detail_container_layout.setSpacing(0)

        self.detail_placeholder = QLabel("Select an email to review.")
        self.detail_placeholder.setAlignment(Qt.AlignCenter)
        self.detail_placeholder.setStyleSheet(
            "border: 1px dashed #dccbbb; border-radius: 16px; padding: 28px; color: #7b6e63; font-size: 15px;"
        )
        self.detail_placeholder.setMinimumHeight(100)
        detail_container_layout.addWidget(self.detail_placeholder)

        self.detail_panel = QWidget()
        self.detail_panel.setMinimumHeight(120)
        detail_layout = QVBoxLayout(self.detail_panel)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(12)

        header = QHBoxLayout()
        header_text = QVBoxLayout()
        self.thread_title = QLabel("")
        self.thread_title.setStyleSheet("font-size: 28px; font-weight: 700; color: #1d2430;")
        self.thread_guidance = QLabel("")
        self.thread_guidance.setWordWrap(True)
        self.thread_guidance.setStyleSheet("font-size: 13px; color: #7b6e63;")
        header_text.addWidget(self.thread_title)
        header_text.addWidget(self.thread_guidance)
        header.addLayout(header_text, 1)
        detail_layout.addLayout(header)

        review_splitter = QSplitter(Qt.Horizontal)
        review_splitter.setChildrenCollapsible(False)

        original_group = QGroupBox("Original Message")
        original_layout = QVBoxLayout(original_group)
        self.thread_body = QPlainTextEdit()
        self.thread_body.setReadOnly(True)
        self.thread_body.setMinimumHeight(120)
        original_layout.addWidget(self.thread_body)
        review_splitter.addWidget(original_group)

        self.candidates_group = QGroupBox("Candidate Replies")
        candidates_layout = QVBoxLayout(self.candidates_group)
        self.candidate_tabs = QTabWidget()
        self.candidate_tabs.setMinimumHeight(140)
        candidates_layout.addWidget(self.candidate_tabs)

        self.candidate_actions_panel = QWidget()
        candidate_actions_layout = QVBoxLayout(self.candidate_actions_panel)
        candidate_actions_layout.setContentsMargins(0, 0, 0, 0)
        candidate_actions_layout.setSpacing(10)

        self.reset_candidate_button = QPushButton("Reset")
        self.reset_candidate_button.clicked.connect(self.reset_selected_candidate)
        self.regenerate_candidate_button = QPushButton("Regenerate with Ollama")
        self.regenerate_candidate_button.clicked.connect(self.regenerate_selected_candidate)
        self.use_candidate_button = QPushButton("Use this")
        self.use_candidate_button.clicked.connect(self.use_selected_candidate)
        self.use_candidate_button.setStyleSheet(
            "background: #215f4a; color: white; border: 1px solid #215f4a; padding: 8px 16px;"
        )
        self.ignore_thread_button = QPushButton("Ignore")
        self.ignore_thread_button.clicked.connect(self.ignore_current_thread)
        self.ignore_thread_button.setStyleSheet(
            "background: #8c4029; color: white; border: 1px solid #8c4029; padding: 8px 16px;"
        )
        self.close_thread_button = QPushButton("Close")
        self.close_thread_button.clicked.connect(self.close_current_thread)
        self.close_thread_button.setStyleSheet(
            "background: #2f6da3; color: white; border: 1px solid #2f6da3; padding: 8px 16px;"
        )

        for button in (
            self.reset_candidate_button,
            self.regenerate_candidate_button,
            self.use_candidate_button,
            self.ignore_thread_button,
            self.close_thread_button,
        ):
            button.setMinimumWidth(190)
            button.setMinimumHeight(44)
            candidate_actions_layout.addWidget(button)
        candidate_actions_layout.addStretch(1)

        candidate_area = QWidget()
        candidate_area_layout = QHBoxLayout(candidate_area)
        candidate_area_layout.setContentsMargins(0, 0, 0, 0)
        candidate_area_layout.setSpacing(14)
        candidate_area_layout.addWidget(self.candidates_group, 1)
        candidate_area_layout.addWidget(self.candidate_actions_panel, 0)

        review_splitter.addWidget(candidate_area)
        review_splitter.setStretchFactor(0, 1)
        review_splitter.setStretchFactor(1, 1)
        review_splitter.setSizes([520, 520])
        detail_layout.addWidget(review_splitter, 1)

        detail_container_layout.addWidget(self.detail_panel)
        self.queue_detail_splitter.addWidget(self.detail_container)
        self.queue_detail_splitter.setStretchFactor(0, 1)
        self.queue_detail_splitter.setStretchFactor(1, 1)
        self.queue_detail_splitter.setSizes([460, 380])
        shell.addWidget(self.queue_detail_splitter, 1)
        self.detail_panel.hide()

        self._build_settings_dialog()
        self._build_bot_logs_dialog()

        self.setCentralWidget(root)

    def _build_settings_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setModal(True)
        dialog.setWindowTitle("MailAssist Settings")
        dialog.resize(760, 620)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        intro = QLabel("Adjust Ollama and provider settings without leaving the review queue.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #5e6978; font-size: 14px;")
        layout.addWidget(intro)

        settings_tabs = QTabWidget()
        settings_tabs.addTab(self._build_ollama_settings_panel(), "Ollama")
        settings_tabs.addTab(self._build_provider_settings_panel(), "Providers")
        settings_tabs.addTab(self._build_signature_settings_panel(), "Signature")
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
        self.bot_console.setMinimumHeight(140)
        layout.addWidget(self.bot_console)

        log_label = QLabel("Selected log")
        log_label.setStyleSheet("font-size: 13px; color: #5e6978;")
        layout.addWidget(log_label)
        self.bot_log_viewer = QPlainTextEdit()
        self.bot_log_viewer.setReadOnly(True)
        self.bot_log_viewer.setMinimumHeight(140)
        layout.addWidget(self.bot_log_viewer)
        return widget

    def open_settings_dialog(self) -> None:
        if self.settings_dialog is None:
            self._build_settings_dialog()
        self.refresh_models()
        self.settings_dialog.exec()

    def open_bot_logs_dialog(self) -> None:
        if self.bot_logs_dialog is None:
            self._build_bot_logs_dialog()
        self.refresh_bot_logs()
        self.bot_logs_dialog.show()
        self.bot_logs_dialog.raise_()
        self.bot_logs_dialog.activateWindow()

    def _build_ollama_settings_panel(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        form = QFormLayout()
        self.ollama_url_input = QLineEdit(self.settings.ollama_url)
        self.ollama_model_picker = QComboBox()
        form.addRow("Ollama URL", self.ollama_url_input)
        form.addRow("Chosen model", self.ollama_model_picker)
        layout.addLayout(form)

        self.ollama_models_hint = QLabel("")
        self.ollama_models_hint.setWordWrap(True)
        self.ollama_models_hint.setStyleSheet("color: #5e6978; font-size: 13px;")
        layout.addWidget(self.ollama_models_hint)

        self.ollama_test_prompt = QPlainTextEdit("Say hello and confirm which model answered.")
        self.ollama_test_prompt.setMinimumHeight(100)
        layout.addWidget(self.ollama_test_prompt)

        actions = QHBoxLayout()
        save_button = QPushButton("Save settings")
        save_button.clicked.connect(self.save_settings)
        refresh_models_button = QPushButton("Refresh model list")
        refresh_models_button.clicked.connect(self.refresh_models)
        test_button = QPushButton("Run Ollama check")
        test_button.clicked.connect(self.test_ollama)
        actions.addWidget(save_button)
        actions.addWidget(refresh_models_button)
        actions.addWidget(test_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.ollama_result = QPlainTextEdit()
        self.ollama_result.setReadOnly(True)
        self.ollama_result.setMinimumHeight(110)
        layout.addWidget(self.ollama_result)
        return widget

    def _build_provider_settings_panel(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        form = QFormLayout()

        self.default_provider_combo = QComboBox()
        self.default_provider_combo.addItem("Gmail", "gmail")
        self.default_provider_combo.addItem("Outlook", "outlook")
        self.default_provider_combo.setCurrentIndex(0 if self.settings.default_provider == "gmail" else 1)

        self.gmail_enabled = QCheckBox("Enable Gmail")
        self.gmail_enabled.setChecked(self.settings.gmail_enabled)
        self.outlook_enabled = QCheckBox("Enable Outlook")
        self.outlook_enabled.setChecked(self.settings.outlook_enabled)
        self.gmail_credentials_input = QLineEdit(str(self.settings.gmail_credentials_file))
        self.gmail_token_input = QLineEdit(str(self.settings.gmail_token_file))

        form.addRow("Default provider", self.default_provider_combo)
        form.addRow("", self.gmail_enabled)
        form.addRow("", self.outlook_enabled)
        form.addRow("Gmail credentials", self.gmail_credentials_input)
        form.addRow("Gmail token", self.gmail_token_input)
        layout.addLayout(form)

        save_button = QPushButton("Save provider settings")
        save_button.clicked.connect(self.save_settings)
        layout.addWidget(save_button)
        layout.addStretch(1)
        return widget

    def _build_signature_settings_panel(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)

        intro = QLabel("Use this exact block when MailAssist signs off a generated email.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #5e6978; font-size: 13px;")
        layout.addWidget(intro)

        self.signature_input = QPlainTextEdit(self.settings.user_signature)
        self.signature_input.setPlaceholderText("Best regards,\nYour Name")
        self.signature_input.setMinimumHeight(180)
        layout.addWidget(self.signature_input)

        save_button = QPushButton("Save signature")
        save_button.clicked.connect(self.save_settings)
        layout.addWidget(save_button)
        layout.addStretch(1)
        return widget

    def _refresh_status_overlay_visibility(self) -> None:
        visible = self.banner.isVisible() or self.progress_bar.isVisible()
        self.status_overlay.setVisible(visible)
        if self.banner.isVisible():
            self.banner.raise_()

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
        self.banner.show()
        self._refresh_status_overlay_visibility()

    def _append_bot_console(self, line: str) -> None:
        self.bot_console.appendPlainText(line)
        cursor = self.bot_console.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.bot_console.setTextCursor(cursor)

    def _start_fake_progress(self, label: str) -> None:
        self.fake_progress_value = 6
        self.progress_bar.setValue(self.fake_progress_value)
        self.progress_bar.show()
        self._refresh_status_overlay_visibility()
        self.progress_timer.start()

    def _advance_fake_progress(self) -> None:
        if self.fake_progress_value < 88:
            self.fake_progress_value += 4
        elif self.fake_progress_value < 96:
            self.fake_progress_value += 1
        self.progress_bar.setValue(self.fake_progress_value)

    def _finish_fake_progress(self) -> None:
        self.progress_timer.stop()
        self.fake_progress_value = 100
        self.progress_bar.setValue(100)
        self.progress_bar.hide()
        self._refresh_status_overlay_visibility()

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

    def refresh_bot_logs(self) -> None:
        self.bot_log_selector.blockSignals(True)
        self.bot_log_selector.clear()
        log_paths = sorted(
            self.settings.bot_logs_dir.glob("*.jsonl"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in log_paths:
            self.bot_log_selector.addItem(path.name, str(path))
        self.bot_log_selector.blockSignals(False)

        if self.latest_bot_log_path is not None:
            index = self.bot_log_selector.findData(str(self.latest_bot_log_path))
            if index >= 0:
                self.bot_log_selector.setCurrentIndex(index)
                return
        if self.bot_log_selector.count():
            self.bot_log_selector.setCurrentIndex(0)
        else:
            self.bot_log_viewer.clear()

    def refresh_models(self) -> None:
        models, model_error = list_available_models(
            self.ollama_url_input.text().strip(),
            self.settings.ollama_model,
        )
        self.ollama_model_picker.blockSignals(True)
        self.ollama_model_picker.clear()
        if models:
            for model in models:
                self.ollama_model_picker.addItem(model, model)
            picker_index = self.ollama_model_picker.findData(self.settings.ollama_model)
            if picker_index >= 0:
                self.ollama_model_picker.setCurrentIndex(picker_index)
        else:
            self.ollama_model_picker.addItem("No local models found", "")
        self.ollama_model_picker.blockSignals(False)
        if models:
            self.ollama_models_hint.setText("Available models: " + ", ".join(models))
        else:
            self.ollama_models_hint.setText("Available models: none detected yet.")
        if model_error:
            self.ollama_result.setPlainText(model_error)
        elif models:
            self.ollama_result.setPlainText(f"Found {len(models)} available model(s).")
        else:
            self.ollama_result.clear()

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
            self.thread_table.setRowHeight(index, 38)
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
            self.thread_guidance.setText(
                f"{_humanize(classification)} means this message is set aside. Review the original email, then ignore or archive it if that still looks right."
            )
            self.candidates_group.hide()
            self.candidate_actions_panel.hide()
        else:
            if classification == "urgent":
                self.thread_guidance.setText(
                    "Urgent means the sender is asking for a quick turnaround or there is a near deadline."
                )
            elif classification == "reply_needed":
                self.thread_guidance.setText(
                    "Reply needed means a human response is appropriate, but it is not obviously time-critical."
                )
            else:
                self.thread_guidance.setText("")
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
                self.candidate_tabs.addTab(editor, candidate["label"])
                if candidate["candidate_id"] == selected_candidate_id:
                    selected_index = index
            if self.candidate_tabs.count():
                self.candidate_tabs.setCurrentIndex(selected_index)

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

        try:
            QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
        except Exception:
            pass
        self._set_banner(
            "Generating a new alternate with Ollama. This can take 1-2 minutes, but the window should stay responsive.",
            level="info",
        )
        self._start_fake_progress("Generating a new alternate with Ollama")
        self.candidate_regeneration_thread.start()

    def _handle_candidate_regeneration_stream(
        self,
        thread_id: str,
        candidate_id: str,
        chunk: str,
    ) -> None:
        if (
            self.active_regeneration_editor is None
            or thread_id != self.active_regeneration_thread_id
            or candidate_id != self.active_regeneration_candidate_id
        ):
            return
        self.active_regeneration_editor.append_text(chunk)
        QApplication.processEvents()

    def _handle_candidate_regeneration_finished(
        self,
        thread_id: str,
        candidate_id: str,
        label: str,
    ) -> None:
        self._finish_fake_progress()
        if self.active_regeneration_editor is not None:
            self.active_regeneration_editor.setEnabled(True)
        self.settings = load_settings()
        self.review_state = load_review_state(self.settings.root_dir)
        self.current_thread_id = thread_id
        self.refresh_models()
        self.refresh_queue()
        self.render_current_thread()
        self._set_banner(f"Generated a new {label.lower()} draft option.", level="info")

    def _handle_candidate_regeneration_failed(self, message: str) -> None:
        self._finish_fake_progress()
        if self.active_regeneration_editor is not None:
            self.active_regeneration_editor.setEnabled(True)
        self.review_state = load_review_state(self.settings.root_dir)
        self.refresh_queue()
        self.render_current_thread()
        self._set_banner(message, level="error")

    def _cleanup_candidate_regeneration(self) -> None:
        try:
            QApplication.restoreOverrideCursor()
        except Exception:
            pass
        if self.candidate_regeneration_worker is not None:
            self.candidate_regeneration_worker.deleteLater()
        if self.candidate_regeneration_thread is not None:
            self.candidate_regeneration_thread.deleteLater()
        self.candidate_regeneration_worker = None
        self.candidate_regeneration_thread = None
        self.active_regeneration_editor = None
        self.active_regeneration_thread_id = ""
        self.active_regeneration_candidate_id = ""

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

    def save_settings(self) -> None:
        env_file = self.settings.root_dir / ".env"
        current = read_env_file(env_file)
        selected_model = str(self.ollama_model_picker.currentData() or self.settings.ollama_model).strip()
        current.update(
            {
                "MAILASSIST_OLLAMA_URL": self.ollama_url_input.text().strip() or "http://localhost:11434",
                "MAILASSIST_OLLAMA_MODEL": selected_model,
                "MAILASSIST_USER_SIGNATURE": self.signature_input.toPlainText().strip().replace("\n", "\\n"),
                "MAILASSIST_DEFAULT_PROVIDER": str(self.default_provider_combo.currentData()),
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
            }
        )
        write_env_file(env_file, current)
        self.settings = load_settings()
        self.refresh_models()
        self._set_banner("Settings saved.", level="info")

    def test_ollama(self) -> None:
        prompt = self.ollama_test_prompt.toPlainText().strip()
        if not prompt:
            self._set_banner("Enter a prompt before testing Ollama.", level="error")
            return
        self.run_bot_action("ollama-check", prompt=prompt)

    def run_bot_action(self, action: str, *, thread_id: str = "", prompt: str = "") -> None:
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

        self._append_bot_console(f"$ {sys.executable} {' '.join(args)}")
        self._set_banner(
            f"Starting bot action: {action}. Ollama work can take 1-2 minutes.",
            level="info",
        )
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
            self.ollama_result.setPlainText(str(event.get("result", "")))
        elif event_type == "completed":
            self._set_banner(str(event.get("message", "Bot action completed.")), level="info")
            self.settings = load_settings()
            self.review_state = load_review_state(self.settings.root_dir)
            self.refresh_models()
            self.refresh_bot_logs()
            self.refresh_queue()
            if self.current_thread_id:
                self.render_current_thread()
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
        self.bot_log_viewer.setPlainText(log_path.read_text(encoding="utf-8"))


def run_desktop_gui() -> int:
    app = QApplication.instance() or QApplication([])
    window = MailAssistDesktopWindow()
    window.show()
    return app.exec()
