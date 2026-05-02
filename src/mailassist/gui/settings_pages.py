from __future__ import annotations

import html
import json
from functools import partial

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
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
    QListWidget,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from mailassist.background_bot import TONE_OPTIONS, build_prompt_preview, tone_label
from mailassist.config import (
    ATTRIBUTION_ABOVE_SIGNATURE,
    ATTRIBUTION_BELOW_SIGNATURE,
    ATTRIBUTION_HIDE,
    LOCKED_NEEDS_REPLY_CATEGORY,
    load_settings,
    read_env_file,
    write_env_file,
)
from mailassist.contacts import ElderContact, parse_elder_contacts, save_elder_contacts
from mailassist.llm.ollama import OllamaClient
from mailassist.rich_text import attribution_html, html_to_plain_text, sanitize_html_fragment
from mailassist.system_resources import (
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


class SettingsPagesMixin:
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
