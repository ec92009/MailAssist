from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from mailassist.config import APPEARANCE_DAY, APPEARANCE_NIGHT, APPEARANCE_SYSTEM


def resolved_appearance(appearance: str) -> str:
    if appearance != APPEARANCE_SYSTEM:
        return appearance
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


def theme_colors(appearance: str) -> dict[str, str]:
    if resolved_appearance(appearance) == APPEARANCE_NIGHT:
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


def app_stylesheet(colors: dict[str, str]) -> str:
    return f"""
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


def combo_popup_style(colors: dict[str, str]) -> str:
    return (
        f"QListView#comboPopup {{ background: {colors['field_bg']}; "
        f"border: 1px solid {colors['field_border']}; color: {colors['text']}; "
        f"selection-background-color: {colors['accent']}; selection-color: #ffffff; outline: 0; }}"
        f"QListView#comboPopup::item {{ min-height: 28px; padding: 4px 10px; }}"
        f"QListView#comboPopup::item:hover {{ background: {colors['button_hover']}; color: {colors['text']}; }}"
        f"QListView#comboPopup::item:selected {{ background: {colors['accent']}; color: #ffffff; }}"
    )


def tool_button_style(colors: dict[str, str]) -> str:
    return (
        f"QToolButton {{ background: {colors['button_bg']}; border: 1px solid {colors['button_border']}; "
        f"border-radius: 8px; color: {colors['text']}; padding: 5px 9px; }}"
        f"QToolButton:hover {{ background: {colors['button_hover']}; }}"
        f"QToolButton:disabled {{ background: {colors['disabled_bg']}; color: {colors['disabled_text']}; }}"
    )
