from __future__ import annotations

from functools import partial
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from mailassist.config import load_settings, read_env_file, write_env_file
from mailassist.gui.server import (
    FILTER_LABELS,
    SORT_LABELS,
    STATUS_FILTER_LABELS,
    ensure_review_state,
    filtered_and_sorted_threads,
    find_thread_state,
    list_available_models,
    load_visible_version,
    normalize_classification,
    payload_to_thread,
    regenerate_thread_candidates,
    save_review_state,
    update_candidate,
)
from mailassist.llm.ollama import OllamaClient


def _humanize(token: str) -> str:
    return token.replace("_", " ").title()


class CandidateEditor(QWidget):
    def __init__(
        self,
        thread_state: dict[str, Any],
        candidate: dict[str, Any],
        save_callback,
        green_callback,
        red_callback,
    ) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        meta = QLabel(
            f"{candidate['tone']} | {_humanize(candidate.get('classification', 'unclassified'))}"
        )
        meta.setStyleSheet("color: #5e6978;")
        layout.addWidget(meta)

        self.editor = QPlainTextEdit(candidate.get("body", ""))
        self.editor.setPlaceholderText("No response recommended for this classification.")
        self.editor.setMinimumHeight(220)
        layout.addWidget(self.editor)

        actions = QHBoxLayout()
        save_button = QPushButton("Save edits")
        save_button.clicked.connect(partial(save_callback, thread_state["thread_id"], candidate["candidate_id"], self))
        green_button = QPushButton("Green light")
        green_button.clicked.connect(partial(green_callback, thread_state["thread_id"], candidate["candidate_id"], self))
        red_button = QPushButton("Red light")
        red_button.clicked.connect(partial(red_callback, thread_state["thread_id"], candidate["candidate_id"], self))

        actions.addWidget(save_button)
        actions.addWidget(green_button)
        actions.addWidget(red_button)
        actions.addStretch(1)
        layout.addLayout(actions)


class MailAssistDesktopWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = load_settings()
        self.review_state = ensure_review_state(
            self.settings.root_dir,
            base_url=self.settings.ollama_url,
            selected_model=self.settings.ollama_model,
        )
        self.current_thread_id = ""

        self.setWindowTitle(f"MailAssist v{load_visible_version(self.settings.root_dir)}")
        self.resize(1380, 920)

        self._build_ui()
        self.refresh_models()
        self.refresh_queue()

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
            "Native mac-first review workspace for triage, candidate editing, and Gmail-first operator approval."
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
        hero.addWidget(self.version_label)
        shell.addLayout(hero)

        self.banner = QLabel("")
        self.banner.hide()
        self.banner.setStyleSheet(
            "padding: 10px 12px; border-radius: 12px; background: rgba(33,95,74,0.12); color: #215f4a;"
        )
        shell.addWidget(self.banner)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        shell.addWidget(splitter, 1)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        queue_title = QLabel("Review Queue")
        queue_title.setStyleSheet("font-size: 22px; font-weight: 700; color: #1d2430;")
        left_layout.addWidget(queue_title)

        filter_form = QFormLayout()
        self.classification_filter = QComboBox()
        for value, label in FILTER_LABELS.items():
            self.classification_filter.addItem(label, value)
        self.classification_filter.currentIndexChanged.connect(self.refresh_queue)

        self.status_filter = QComboBox()
        for value, label in STATUS_FILTER_LABELS.items():
            self.status_filter.addItem(label, value)
        self.status_filter.currentIndexChanged.connect(self.refresh_queue)

        self.sort_order = QComboBox()
        for value, label in SORT_LABELS.items():
            self.sort_order.addItem(label, value)
        self.sort_order.currentIndexChanged.connect(self.refresh_queue)

        filter_form.addRow("Filter", self.classification_filter)
        filter_form.addRow("Review status", self.status_filter)
        filter_form.addRow("Order", self.sort_order)
        left_layout.addLayout(filter_form)

        self.thread_list = QListWidget()
        self.thread_list.currentItemChanged.connect(self._handle_thread_selection)
        left_layout.addWidget(self.thread_list, 1)
        splitter.addWidget(left_panel)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(12)

        summary_group = QGroupBox("Thread Summary")
        summary_layout = QVBoxLayout(summary_group)
        self.thread_title = QLabel("")
        self.thread_title.setStyleSheet("font-size: 28px; font-weight: 700; color: #1d2430;")
        self.thread_meta = QLabel("")
        self.thread_meta.setStyleSheet("font-size: 13px; color: #5e6978;")
        self.thread_badges = QLabel("")
        self.thread_badges.setStyleSheet("font-size: 13px; color: #b95333;")
        summary_actions = QHBoxLayout()
        refresh_button = QPushButton("Refresh draft options with Ollama")
        refresh_button.clicked.connect(self.regenerate_current_thread)
        summary_actions.addWidget(refresh_button)
        summary_actions.addStretch(1)
        summary_layout.addWidget(self.thread_title)
        summary_layout.addWidget(self.thread_meta)
        summary_layout.addWidget(self.thread_badges)
        summary_layout.addLayout(summary_actions)
        right_layout.addWidget(summary_group)

        content_splitter = QSplitter(Qt.Vertical)
        content_splitter.setChildrenCollapsible(False)

        thread_group = QGroupBox("Email Body")
        thread_layout = QVBoxLayout(thread_group)
        self.thread_body = QPlainTextEdit()
        self.thread_body.setReadOnly(True)
        thread_layout.addWidget(self.thread_body)
        content_splitter.addWidget(thread_group)

        candidates_group = QGroupBox("Response Drafts")
        candidates_layout = QVBoxLayout(candidates_group)
        self.candidate_tabs = QTabWidget()
        candidates_layout.addWidget(self.candidate_tabs)
        content_splitter.addWidget(candidates_group)
        content_splitter.setStretchFactor(0, 3)
        content_splitter.setStretchFactor(1, 4)
        right_layout.addWidget(content_splitter, 1)

        settings_group = QGroupBox("Operator Settings")
        settings_layout = QVBoxLayout(settings_group)
        settings_tabs = QTabWidget()
        settings_tabs.addTab(self._build_ollama_settings_panel(), "Ollama")
        settings_tabs.addTab(self._build_provider_settings_panel(), "Providers")
        settings_layout.addWidget(settings_tabs)
        right_layout.addWidget(settings_group)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        self.setCentralWidget(root)

    def _build_ollama_settings_panel(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        form = QFormLayout()
        self.ollama_url_input = QLineEdit(self.settings.ollama_url)
        self.ollama_model_combo = QComboBox()
        form.addRow("Ollama URL", self.ollama_url_input)
        form.addRow("Chosen model", self.ollama_model_combo)
        layout.addLayout(form)

        self.ollama_test_prompt = QPlainTextEdit("Say hello and confirm which model answered.")
        self.ollama_test_prompt.setMinimumHeight(100)
        layout.addWidget(self.ollama_test_prompt)

        actions = QHBoxLayout()
        save_button = QPushButton("Save settings")
        save_button.clicked.connect(self.save_settings)
        test_button = QPushButton("Run Ollama check")
        test_button.clicked.connect(self.test_ollama)
        actions.addWidget(save_button)
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

    def _set_banner(self, message: str, level: str = "info") -> None:
        if not message:
            self.banner.hide()
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

    def refresh_models(self) -> None:
        models, model_error = list_available_models(
            self.ollama_url_input.text().strip(),
            self.settings.ollama_model,
        )
        self.ollama_model_combo.clear()
        if not models and self.settings.ollama_model:
            self.ollama_model_combo.addItem(f"{self.settings.ollama_model} (current)", self.settings.ollama_model)
        for model in models:
            self.ollama_model_combo.addItem(model, model)
        index = max(self.ollama_model_combo.findData(self.settings.ollama_model), 0)
        if self.ollama_model_combo.count():
            self.ollama_model_combo.setCurrentIndex(index)
        if model_error:
            self.ollama_result.setPlainText(model_error)

    def current_context(self) -> dict[str, str]:
        return {
            "filter_classification": str(self.classification_filter.currentData()),
            "filter_status": str(self.status_filter.currentData()),
            "sort_order": str(self.sort_order.currentData()),
        }

    def visible_threads(self) -> list[dict[str, Any]]:
        context = self.current_context()
        return filtered_and_sorted_threads(
            self.review_state["threads"],
            filter_classification=context["filter_classification"],
            filter_status=context["filter_status"],
            sort_order=context["sort_order"],
        )

    def refresh_queue(self) -> None:
        visible = self.visible_threads()
        self.thread_list.blockSignals(True)
        self.thread_list.clear()
        for thread_state in visible:
            classification = _humanize(normalize_classification(thread_state.get("classification")))
            item = QListWidgetItem(
                f"{thread_state['subject']}\n{_humanize(thread_state['status'])} | {classification}"
            )
            item.setData(Qt.UserRole, thread_state["thread_id"])
            self.thread_list.addItem(item)
        self.thread_list.blockSignals(False)

        if visible:
            target_thread_id = self.current_thread_id if any(
                item["thread_id"] == self.current_thread_id for item in visible
            ) else visible[0]["thread_id"]
            for index in range(self.thread_list.count()):
                item = self.thread_list.item(index)
                if item.data(Qt.UserRole) == target_thread_id:
                    self.thread_list.setCurrentItem(item)
                    break
        else:
            self.current_thread_id = ""
            self.thread_title.setText("No emails match the current filters.")
            self.thread_meta.setText("")
            self.thread_badges.setText("")
            self.thread_body.clear()
            self.candidate_tabs.clear()

    def _handle_thread_selection(self, current: QListWidgetItem | None, _: QListWidgetItem | None) -> None:
        if current is None:
            return
        self.current_thread_id = str(current.data(Qt.UserRole))
        self.render_current_thread()

    def render_current_thread(self) -> None:
        if not self.current_thread_id:
            return
        thread_state, _ = find_thread_state(self.review_state, self.current_thread_id)
        thread = payload_to_thread(thread_state["thread"])
        self.thread_title.setText(thread.subject)
        self.thread_meta.setText(", ".join(thread.participants))
        self.thread_badges.setText(
            " | ".join(
                [
                    _humanize(thread_state["status"]),
                    f"{len(thread_state.get('candidates', []))} draft options",
                    _humanize(thread_state.get("classification", "unclassified")),
                    str(thread_state.get("candidate_generation_model") or "fallback"),
                ]
            )
        )

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
        self.thread_body.setPlainText("\n\n" + ("\n\n" + ("-" * 60) + "\n\n").join(message_chunks))

        self.candidate_tabs.clear()
        for candidate in thread_state.get("candidates", []):
            editor = CandidateEditor(
                thread_state,
                candidate,
                self.save_candidate,
                self.green_light_candidate,
                self.red_light_candidate,
            )
            tab_label = f"{candidate['label']} | {_humanize(candidate.get('classification', 'unclassified'))}"
            self.candidate_tabs.addTab(editor, tab_label)

    def save_candidate(self, thread_id: str, candidate_id: str, editor: CandidateEditor) -> None:
        self._apply_candidate_action(thread_id, candidate_id, editor.editor.toPlainText(), "save", "Draft edits saved.")

    def green_light_candidate(self, thread_id: str, candidate_id: str, editor: CandidateEditor) -> None:
        self._apply_candidate_action(
            thread_id,
            candidate_id,
            editor.editor.toPlainText(),
            "green_light",
            "Draft green-lit.",
        )

    def red_light_candidate(self, thread_id: str, candidate_id: str, editor: CandidateEditor) -> None:
        self._apply_candidate_action(
            thread_id,
            candidate_id,
            editor.editor.toPlainText(),
            "red_light",
            "Draft red-lit.",
        )

    def _apply_candidate_action(
        self,
        thread_id: str,
        candidate_id: str,
        body: str,
        action: str,
        success_message: str,
    ) -> None:
        thread_state, _ = find_thread_state(self.review_state, thread_id)
        try:
            update_candidate(thread_state, candidate_id, body, action)
            save_review_state(self.settings.root_dir, self.review_state)
        except ValueError as exc:
            self._set_banner(str(exc), level="error")
            return
        self._set_banner(success_message, level="info")
        self.render_current_thread()
        self.refresh_queue()

    def regenerate_current_thread(self) -> None:
        if not self.current_thread_id:
            return
        self.settings = load_settings()
        try:
            regenerate_thread_candidates(
                self.review_state,
                self.current_thread_id,
                base_url=self.settings.ollama_url,
                selected_model=self.settings.ollama_model,
            )
            save_review_state(self.settings.root_dir, self.review_state)
        except Exception as exc:
            self._set_banner(f"Could not regenerate drafts: {exc}", level="error")
            return
        self._set_banner("Draft options refreshed.", level="info")
        self.render_current_thread()
        self.refresh_queue()

    def save_settings(self) -> None:
        env_file = self.settings.root_dir / ".env"
        current = read_env_file(env_file)
        selected_model = (
            str(self.ollama_model_combo.currentData()) if self.ollama_model_combo.currentData() else self.settings.ollama_model
        )
        current.update(
            {
                "MAILASSIST_OLLAMA_URL": self.ollama_url_input.text().strip() or "http://localhost:11434",
                "MAILASSIST_OLLAMA_MODEL": selected_model,
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
        try:
            result = OllamaClient(
                self.ollama_url_input.text().strip() or self.settings.ollama_url,
                str(self.ollama_model_combo.currentData() or self.settings.ollama_model),
            ).compose_reply(prompt)
        except RuntimeError as exc:
            self.ollama_result.setPlainText(str(exc))
            self._set_banner("Ollama check failed.", level="error")
            return
        self.ollama_result.setPlainText(result or "Ollama responded with an empty body.")
        self._set_banner("Ollama check completed.", level="info")


def run_desktop_gui() -> int:
    app = QApplication.instance() or QApplication([])
    window = MailAssistDesktopWindow()
    window.show()
    return app.exec()
