from __future__ import annotations

from PySide6 import QtCore, QtWidgets


class GroupDialog(QtWidgets.QDialog):
    def __init__(self, name: str = "", parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Group")
        self.setModal(True)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.setText(name)
        form.addRow("Name", self.name_edit)
        layout.addLayout(form)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self) -> None:
        if not self.name_edit.text().strip():
            QtWidgets.QMessageBox.warning(self, "Missing name", "Name must not be empty.")
            return
        self.accept()

    def group_name(self) -> str:
        return self.name_edit.text().strip()
