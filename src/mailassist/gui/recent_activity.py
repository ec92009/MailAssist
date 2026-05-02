from __future__ import annotations

import html
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextOption
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)


EMPTY_ACTIVITY_TEXT = "No bot activity yet."


def _wrapped_tooltip(text: str, *, width: int = 320) -> str:
    escaped = html.escape(" ".join(text.split()))
    return f'<qt><div style="white-space: normal; width: {width}px;">{escaped}</div></qt>'


class RecentActivityPanel(QGroupBox):
    def __init__(
        self,
        *,
        on_report: Callable[[], None],
        on_clear: Callable[[], None],
    ) -> None:
        super().__init__("Recent Activity")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        body = QHBoxLayout()
        body.setSpacing(8)

        controls = QVBoxLayout()
        controls.setSpacing(6)

        self.report_button = QPushButton("Report")
        self.report_button.setMaximumWidth(96)
        self.report_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.report_button.setToolTip(_wrapped_tooltip(
            "Open the detailed activity report with the selected run summary and timeline."
        ))
        self.report_button.clicked.connect(on_report)
        controls.addWidget(self.report_button)

        self.clear_button = QPushButton("Clear")
        self.clear_button.setMaximumWidth(96)
        self.clear_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.clear_button.setToolTip(_wrapped_tooltip(
            "Clear the visible Recent Activity list. Saved run logs are not deleted."
        ))
        self.clear_button.clicked.connect(on_clear)
        controls.addWidget(self.clear_button)
        controls.addStretch(1)

        body.addLayout(controls)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.text_edit.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.text_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text_edit.setMinimumWidth(0)
        self.text_edit.setMinimumHeight(80)
        self.text_edit.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.text_edit.setPlainText(EMPTY_ACTIVITY_TEXT)
        body.addWidget(self.text_edit, 1)

        layout.addLayout(body, 1)

    def append_message(self, message: str) -> None:
        if self.text_edit.toPlainText().strip() == EMPTY_ACTIVITY_TEXT:
            self.text_edit.clear()
        self.text_edit.appendPlainText(message)

    def clear_messages(self) -> None:
        self.text_edit.setPlainText(EMPTY_ACTIVITY_TEXT)
