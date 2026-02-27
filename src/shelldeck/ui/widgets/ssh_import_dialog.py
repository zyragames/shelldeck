from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from ...ssh_config import SshConfigEntry


class SshImportDialog(QtWidgets.QDialog):
    def __init__(
        self,
        entries: list[SshConfigEntry],
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import from SSH config")
        self.setModal(True)
        self._entries = entries

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.table = QtWidgets.QTableWidget(len(entries), 7, self)
        self.table.setHorizontalHeaderLabels(
            ["Import", "Alias", "Hostname", "User", "Port", "Identity", "ProxyJump"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)

        for row, entry in enumerate(entries):
            checkbox_item = QtWidgets.QTableWidgetItem()
            checkbox_item.setCheckState(QtCore.Qt.CheckState.Checked)
            self.table.setItem(row, 0, checkbox_item)
            self.table.setItem(row, 1, QtWidgets.QTableWidgetItem(entry.alias))
            self.table.setItem(row, 2, QtWidgets.QTableWidgetItem(entry.hostname))
            self.table.setItem(row, 3, QtWidgets.QTableWidgetItem(entry.user or ""))
            self.table.setItem(row, 4, QtWidgets.QTableWidgetItem(str(entry.port or "")))
            self.table.setItem(row, 5, QtWidgets.QTableWidgetItem(entry.identity_file or ""))
            self.table.setItem(row, 6, QtWidgets.QTableWidgetItem(entry.proxy_jump or ""))

        self.table.resizeColumnsToContents()
        layout.addWidget(self.table, 1)

        toggle_bar = QtWidgets.QHBoxLayout()
        select_all = QtWidgets.QPushButton("Select all")
        select_none = QtWidgets.QPushButton("Select none")
        select_all.clicked.connect(lambda: self._set_all(QtCore.Qt.CheckState.Checked))
        select_none.clicked.connect(lambda: self._set_all(QtCore.Qt.CheckState.Unchecked))
        toggle_bar.addWidget(select_all)
        toggle_bar.addWidget(select_none)
        toggle_bar.addStretch(1)
        layout.addLayout(toggle_bar)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _set_all(self, state: QtCore.Qt.CheckState) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                item.setCheckState(state)

    def selected_entries(self) -> list[SshConfigEntry]:
        selected: list[SshConfigEntry] = []
        for row, entry in enumerate(self._entries):
            item = self.table.item(row, 0)
            if item and item.checkState() == QtCore.Qt.CheckState.Checked:
                selected.append(entry)
        return selected
