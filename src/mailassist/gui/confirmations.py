from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget


def confirm_action(
    parent: QWidget,
    *,
    title: str,
    message: str,
    colors: dict[str, str],
) -> QMessageBox.StandardButton:
    dialog = QDialog(parent)
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
