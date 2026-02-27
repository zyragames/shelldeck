from __future__ import annotations

from PySide6 import QtGui, QtWidgets


class HostItemWidget(QtWidgets.QWidget):
    def __init__(self, host: str, detail: str, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        title = QtWidgets.QLabel(host)
        title_font = QtGui.QFont()
        title_font.setPointSize(10)
        title_font.setWeight(QtGui.QFont.Weight.Medium)
        title.setFont(title_font)

        subtitle = QtWidgets.QLabel(detail)
        subtitle_font = QtGui.QFont()
        subtitle_font.setPointSize(8)
        subtitle.setFont(subtitle_font)
        subtitle.setStyleSheet("color: #94a3b8;")

        layout.addWidget(title)
        layout.addWidget(subtitle)
