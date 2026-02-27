from __future__ import annotations

from dataclasses import dataclass

from PySide6 import QtCore, QtGui, QtWidgets


DEFAULT_ACCENT = "#2dd4bf"
DEFAULT_MODE = "dark"
TAB_CLOSE_INSET = 8
TAB_CLOSE_BUTTON_SIZE = 22
TAB_CLOSE_TEXT_BUFFER = 12
TAB_PADDING_RIGHT = TAB_CLOSE_BUTTON_SIZE + TAB_CLOSE_INSET + TAB_CLOSE_TEXT_BUFFER


@dataclass(frozen=True)
class ThemeConfig:
    mode: str
    accent: str


def load_theme_settings(settings: QtCore.QSettings) -> ThemeConfig:
    mode = str(settings.value("theme/mode", DEFAULT_MODE))
    accent = settings.value("theme/accent", DEFAULT_ACCENT)
    if mode not in {"dark", "light"}:
        mode = DEFAULT_MODE
    return ThemeConfig(mode=mode, accent=str(accent))


def save_theme_settings(settings: QtCore.QSettings, config: ThemeConfig) -> None:
    settings.setValue("theme/mode", config.mode)
    settings.setValue("theme/accent", config.accent)


def apply_theme(app: QtWidgets.QApplication, config: ThemeConfig) -> None:
    app.setStyle("Fusion")
    palette = QtGui.QPalette()
    accent_color = QtGui.QColor(config.accent)

    if config.mode == "light":
        _apply_light_palette(palette, accent_color)
        stylesheet = _build_stylesheet(accent_color, "#f8fafc", "#0f172a", "#ffffff")
    else:
        _apply_dark_palette(palette, accent_color)
        stylesheet = _build_stylesheet(accent_color, "#0b1220", "#e2e8f0", "#0f172a")

    app.setPalette(palette)
    app.setStyleSheet(stylesheet)


def _apply_dark_palette(palette: QtGui.QPalette, accent: QtGui.QColor) -> None:
    base = QtGui.QColor("#0f172a")
    window = QtGui.QColor("#0b1220")
    text = QtGui.QColor("#e2e8f0")
    muted = QtGui.QColor("#94a3b8")
    highlight = QtGui.QColor(accent)

    palette.setColor(QtGui.QPalette.ColorRole.Window, window)
    palette.setColor(QtGui.QPalette.ColorRole.WindowText, text)
    palette.setColor(QtGui.QPalette.ColorRole.Base, base)
    palette.setColor(QtGui.QPalette.ColorRole.AlternateBase, QtGui.QColor("#111827"))
    palette.setColor(QtGui.QPalette.ColorRole.Text, text)
    palette.setColor(QtGui.QPalette.ColorRole.Button, QtGui.QColor("#111827"))
    palette.setColor(QtGui.QPalette.ColorRole.ButtonText, text)
    palette.setColor(QtGui.QPalette.ColorRole.Highlight, highlight)
    palette.setColor(QtGui.QPalette.ColorRole.HighlightedText, QtGui.QColor("#020617"))
    palette.setColor(QtGui.QPalette.ColorRole.PlaceholderText, muted)


def _apply_light_palette(palette: QtGui.QPalette, accent: QtGui.QColor) -> None:
    window = QtGui.QColor("#f8fafc")
    base = QtGui.QColor("#ffffff")
    text = QtGui.QColor("#0f172a")
    muted = QtGui.QColor("#64748b")
    highlight = QtGui.QColor(accent)

    palette.setColor(QtGui.QPalette.ColorRole.Window, window)
    palette.setColor(QtGui.QPalette.ColorRole.WindowText, text)
    palette.setColor(QtGui.QPalette.ColorRole.Base, base)
    palette.setColor(QtGui.QPalette.ColorRole.AlternateBase, QtGui.QColor("#f1f5f9"))
    palette.setColor(QtGui.QPalette.ColorRole.Text, text)
    palette.setColor(QtGui.QPalette.ColorRole.Button, QtGui.QColor("#f1f5f9"))
    palette.setColor(QtGui.QPalette.ColorRole.ButtonText, text)
    palette.setColor(QtGui.QPalette.ColorRole.Highlight, highlight)
    palette.setColor(QtGui.QPalette.ColorRole.HighlightedText, QtGui.QColor("#0f172a"))
    palette.setColor(QtGui.QPalette.ColorRole.PlaceholderText, muted)


def _build_stylesheet(accent: QtGui.QColor, window: str, text: str, base: str) -> str:
    accent_rgb = f"{accent.red()},{accent.green()},{accent.blue()}"
    accent_soft = f"rgba({accent_rgb}, 40)"
    accent_hover = f"rgba({accent_rgb}, 90)"

    return f"""
    QMainWindow {{
        background: {window};
        color: {text};
    }}
    QToolBar {{
        background: transparent;
        border: none;
        padding: 6px 8px;
        spacing: 6px;
    }}
    QToolButton {{
        border: 1px solid transparent;
        border-radius: 6px;
        padding: 6px 10px;
    }}
    QToolButton:hover {{
        background: {accent_soft};
        border-color: {accent_hover};
    }}
    QToolButton:checked {{
        background: {accent_hover};
    }}
    QLineEdit {{
        border: 1px solid rgba(148, 163, 184, 120);
        border-radius: 8px;
        padding: 6px 10px;
        background: {base};
    }}
    QTreeView {{
        background: transparent;
        border: 1px solid rgba(148, 163, 184, 80);
        border-radius: 10px;
        padding: 6px;
    }}
    QTreeView::item:selected {{
        background: {accent_soft};
        border-radius: 6px;
    }}
    QTabBar::tab {{
        background: transparent;
        border: 1px solid rgba(148, 163, 184, 70);
        padding: 6px 12px;
        padding-right: {TAB_PADDING_RIGHT}px;
        border-radius: 8px;
        margin-right: 6px;
    }}
    QTabBar::tab:selected {{
        border-color: {accent_hover};
        background: {accent_soft};
    }}
    QTabBar::close-button {{
        subcontrol-position: right;
        margin-left: 4px;
    }}
    QToolButton#tabCloseButton {{
        border: none;
        background: transparent;
        padding: 0px;
        margin: 0px;
        margin-right: {TAB_CLOSE_INSET}px;
        border-radius: 6px;
    }}
    QToolButton#tabCloseButton:hover {{
        background: {accent_soft};
    }}
    QToolButton#tabCloseButton:pressed {{
        background: {accent_hover};
    }}
    QPushButton {{
        border: 1px solid rgba(148, 163, 184, 120);
        border-radius: 8px;
        padding: 6px 10px;
        background: {base};
    }}
    QPushButton:hover {{
        border-color: {accent_hover};
        background: {accent_soft};
    }}
    QScrollBar:vertical {{
        width: 8px;
        background: transparent;
    }}
    QScrollBar::handle:vertical {{
        background: rgba(148, 163, 184, 90);
        border-radius: 4px;
    }}
    """
