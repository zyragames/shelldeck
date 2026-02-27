from __future__ import annotations

from dataclasses import dataclass
import os

from PySide6 import QtCore, QtWidgets

from ...data.models import Group, Host


@dataclass(frozen=True)
class HostFormData:
    host: Host
    tags: list[str]


class HostDialog(QtWidgets.QDialog):
    def __init__(
        self,
        groups: list[Group],
        host: Host | None = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Host")
        self.setModal(True)
        self._host = host
        self._groups = groups

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)

        self.name_edit = QtWidgets.QLineEdit()
        self.hostname_edit = QtWidgets.QLineEdit()
        self.port_spin = QtWidgets.QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(22)
        self.user_edit = QtWidgets.QLineEdit()
        self.identity_file_edit = QtWidgets.QLineEdit()
        self.identity_file_button = QtWidgets.QPushButton("Browse...")
        self.identity_file_button.clicked.connect(self._select_identity_file)
        self.ssh_alias_edit = QtWidgets.QLineEdit()
        self.tags_edit = QtWidgets.QLineEdit()
        self.notes_edit = QtWidgets.QPlainTextEdit()
        self.notes_edit.setFixedHeight(90)

        self.group_combo = QtWidgets.QComboBox()
        for group in groups:
            self.group_combo.addItem(group.name, userData=group.id)

        form.addRow("Name", self.name_edit)
        form.addRow("Host", self.hostname_edit)
        form.addRow("Port", self.port_spin)
        form.addRow("User", self.user_edit)
        identity_file_row = QtWidgets.QHBoxLayout()
        identity_file_row.setContentsMargins(0, 0, 0, 0)
        identity_file_row.addWidget(self.identity_file_edit, 1)
        identity_file_row.addWidget(self.identity_file_button)
        identity_file_widget = QtWidgets.QWidget()
        identity_file_widget.setLayout(identity_file_row)

        form.addRow("Identity file", identity_file_widget)
        form.addRow("SSH config alias", self.ssh_alias_edit)
        form.addRow("Tags", self.tags_edit)
        form.addRow("Group", self.group_combo)
        form.addRow("Notes", self.notes_edit)

        layout.addLayout(form)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if host:
            self._populate(host)

    def _populate(self, host: Host) -> None:
        self.name_edit.setText(host.name)
        self.hostname_edit.setText(host.hostname)
        if host.port:
            self.port_spin.setValue(host.port)
        self.user_edit.setText(host.user or "")
        self.identity_file_edit.setText(host.identity_file or "")
        self.ssh_alias_edit.setText(host.ssh_config_host_alias or "")
        self.tags_edit.setText(", ".join(host.tags) if host.tags else "")
        self.notes_edit.setPlainText(host.notes or "")
        index = self.group_combo.findData(host.group_id)
        if index >= 0:
            self.group_combo.setCurrentIndex(index)

    def _accept(self) -> None:
        name = self.name_edit.text().strip()
        hostname = self.hostname_edit.text().strip()
        if not name:
            QtWidgets.QMessageBox.warning(self, "Missing name", "Name must not be empty.")
            return
        if not hostname:
            QtWidgets.QMessageBox.warning(self, "Missing host", "Host must not be empty.")
            return
        self.accept()

    def _select_identity_file(self) -> None:
        current_value = self.identity_file_edit.text().strip()
        start_dir = os.path.dirname(current_value) if current_value else os.path.expanduser("~")
        selected, _filter = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select identity file",
            start_dir,
            "All files (*)",
        )
        if selected:
            self.identity_file_edit.setText(selected)

    def form_data(self) -> HostFormData:
        name = self.name_edit.text().strip()
        hostname = self.hostname_edit.text().strip()
        user = self.user_edit.text().strip() or None
        identity_file = self.identity_file_edit.text().strip() or None
        ssh_alias = self.ssh_alias_edit.text().strip() or None
        notes = self.notes_edit.toPlainText().strip() or None
        tags = [tag.strip() for tag in self.tags_edit.text().split(",") if tag.strip()]
        group_id = int(self.group_combo.currentData())
        host_id = self._host.id if self._host else 0
        favorite = self._host.favorite if self._host else False
        color = self._host.color if self._host else None
        tag = self._host.tag if self._host else None
        port = int(self.port_spin.value())
        host = Host(
            id=host_id,
            group_id=group_id,
            name=name,
            hostname=hostname,
            port=port,
            user=user,
            identity_file=identity_file,
            ssh_config_host_alias=ssh_alias,
            notes=notes,
            tags=tags,
            favorite=favorite,
            color=color,
            tag=tag,
        )
        return HostFormData(host=host, tags=tags)
