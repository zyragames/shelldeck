from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from ...data import Repository, export_json, import_json
from ...data.models import Host
from ...ssh_config import list_ssh_config_entries
from ..ssh_agent_status import AgentState, KeyInfo, SshAgentStatus, StatusSnapshot
from ..theme import DEFAULT_ACCENT, DEFAULT_MODE, ThemeConfig
from .ssh_import_dialog import SshImportDialog


class SettingsDialog(QtWidgets.QDialog):
    theme_changed = QtCore.Signal(ThemeConfig)
    data_changed = QtCore.Signal()
    layout_reset_requested = QtCore.Signal()

    def __init__(
        self,
        current: ThemeConfig,
        repository: Repository,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.setMinimumSize(760, 540)
        self.resize(820, 620)

        self._accent = QtGui.QColor(current.accent)
        self._repo = repository
        self._ssh_agent_tooltip = ""
        self._ssh_agent_status = SshAgentStatus(self)
        self._ssh_agent_status.status_changed.connect(self._apply_ssh_agent_status)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        tabs = QtWidgets.QTabWidget(self)
        tabs.setDocumentMode(True)
        tabs.setTabPosition(QtWidgets.QTabWidget.TabPosition.North)
        tabs.setToolTip("Navigate settings categories")
        tabs.addTab(self._build_appearance_tab(current), "Appearance")
        tabs.addTab(self._build_ssh_agent_tab(), "SSH Agent")
        tabs.addTab(self._build_data_tab(), "Data")
        tabs.addTab(self._build_layout_tab(), "Layout")
        layout.addWidget(tabs, 1)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setToolTip(
            "Keep settings changes"
        )
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel).setToolTip(
            "Discard settings changes"
        )
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        QtCore.QTimer.singleShot(0, self._refresh_ssh_agent)

    def _build_appearance_tab(self, current: ThemeConfig) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget(self)
        page_layout = QtWidgets.QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(12)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItems(["dark", "light"])
        self.mode_combo.setCurrentText(current.mode)
        self.mode_combo.setToolTip("Switch between dark and light mode")
        self.mode_combo.currentTextChanged.connect(self._emit_theme_change)

        self.accent_button = QtWidgets.QPushButton("Pick accent")
        self.accent_button.setToolTip("Choose the accent color used across the app")
        self.accent_button.clicked.connect(self._pick_accent)
        self._update_accent_button()

        form.addRow("Theme mode", self.mode_combo)
        form.addRow("Accent color", self.accent_button)
        page_layout.addLayout(form)
        page_layout.addStretch(1)
        return page

    def _build_ssh_agent_tab(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget(self)
        page_layout = QtWidgets.QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(12)

        status_group = QtWidgets.QGroupBox("Current status")
        status_group_layout = QtWidgets.QVBoxLayout(status_group)
        status_group_layout.setSpacing(8)

        status_row = QtWidgets.QHBoxLayout()
        status_row.setSpacing(8)

        self.ssh_status_dot = QtWidgets.QLabel()
        self.ssh_status_dot.setFixedSize(10, 10)
        self.ssh_status_dot.setStyleSheet("background: #64748b; border-radius: 5px;")

        self.ssh_status_label = QtWidgets.QLabel("Checking SSH agent status...")
        self.ssh_status_label.setToolTip("Live SSH agent health overview")

        self.refresh_agent_button = QtWidgets.QPushButton("Refresh")
        self.refresh_agent_button.setToolTip("Run SSH agent check now")
        self.refresh_agent_button.clicked.connect(self._refresh_ssh_agent)

        self.copy_agent_button = QtWidgets.QPushButton("Copy details")
        self.copy_agent_button.setToolTip("Copy full SSH agent diagnostics to clipboard")
        self.copy_agent_button.clicked.connect(self._copy_ssh_agent_details)

        status_row.addWidget(self.ssh_status_dot)
        status_row.addWidget(self.ssh_status_label, 1)
        status_row.addWidget(self.refresh_agent_button)
        status_row.addWidget(self.copy_agent_button)
        status_group_layout.addLayout(status_row)

        self.ssh_details = QtWidgets.QPlainTextEdit()
        self.ssh_details.setReadOnly(True)
        self.ssh_details.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        self.ssh_details.setPlaceholderText("SSH agent details are shown here.")
        self.ssh_details.setToolTip("Detailed SSH agent diagnostics and key list")
        status_group_layout.addWidget(self.ssh_details, 1)

        page_layout.addWidget(status_group, 1)
        return page

    def _build_data_tab(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget(self)
        page_layout = QtWidgets.QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(12)

        data_group = QtWidgets.QGroupBox("Import / Export")
        data_layout = QtWidgets.QVBoxLayout(data_group)
        data_layout.setSpacing(8)

        self.import_ssh_button = QtWidgets.QPushButton("Import from SSH config...")
        self.import_ssh_button.setToolTip("Import hosts from ~/.ssh/config")
        self.import_json_button = QtWidgets.QPushButton("Import JSON...")
        self.import_json_button.setToolTip("Import groups and hosts from a JSON export")
        self.export_json_button = QtWidgets.QPushButton("Export JSON...")
        self.export_json_button.setToolTip("Export all groups and hosts to JSON")

        self.import_ssh_button.clicked.connect(self._import_from_ssh_config)
        self.import_json_button.clicked.connect(self._import_json)
        self.export_json_button.clicked.connect(self._export_json)

        data_layout.addWidget(self.import_ssh_button)
        data_layout.addWidget(self.import_json_button)
        data_layout.addWidget(self.export_json_button)
        data_layout.addStretch(1)

        page_layout.addWidget(data_group)
        page_layout.addStretch(1)
        return page

    def _build_layout_tab(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget(self)
        page_layout = QtWidgets.QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(12)

        layout_group = QtWidgets.QGroupBox("Window layout")
        layout_group_layout = QtWidgets.QVBoxLayout(layout_group)
        layout_group_layout.setSpacing(8)

        self.reset_layout_button = QtWidgets.QPushButton("Reset layout")
        self.reset_layout_button.setToolTip(
            "Reset window size, sidebar state, splitter positions and panel layout"
        )
        self.reset_layout_button.clicked.connect(self._confirm_layout_reset)
        layout_group_layout.addWidget(self.reset_layout_button)
        layout_group_layout.addStretch(1)

        page_layout.addWidget(layout_group)
        page_layout.addStretch(1)
        return page

    def _pick_accent(self) -> None:
        color = QtWidgets.QColorDialog.getColor(self._accent, self, "Pick accent color")
        if not color.isValid():
            return
        self._accent = color
        self._update_accent_button()
        self._emit_theme_change()

    def _update_accent_button(self) -> None:
        self.accent_button.setStyleSheet(f"background: {self._accent.name()}; color: #0f172a;")

    def _apply(self) -> None:
        self.accept()

    def _confirm_layout_reset(self) -> None:
        confirm = QtWidgets.QMessageBox(self)
        confirm.setWindowTitle("Reset layout")
        confirm.setText(
            "This resets window size/position, sidebar state, splitter sizes and panel views."
        )
        confirm.setStandardButtons(
            QtWidgets.QMessageBox.StandardButton.Reset | QtWidgets.QMessageBox.StandardButton.Cancel
        )
        confirm.setButtonText(QtWidgets.QMessageBox.StandardButton.Reset, "Reset")
        confirm.setButtonText(QtWidgets.QMessageBox.StandardButton.Cancel, "Cancel")
        if confirm.exec() != QtWidgets.QMessageBox.StandardButton.Reset:
            return
        self.layout_reset_requested.emit()

    def _emit_theme_change(self) -> None:
        mode = self.mode_combo.currentText() or DEFAULT_MODE
        accent = self._accent.name() or DEFAULT_ACCENT
        self.theme_changed.emit(ThemeConfig(mode=mode, accent=accent))

    def _refresh_ssh_agent(self) -> None:
        self._ssh_agent_status.refresh()

    def _copy_ssh_agent_details(self) -> None:
        if not self._ssh_agent_tooltip:
            return
        QtGui.QGuiApplication.clipboard().setText(self._ssh_agent_tooltip)

    def _apply_ssh_agent_status(self, snapshot: StatusSnapshot) -> None:
        color_map = {
            AgentState.OFF: "#64748b",
            AgentState.OK_KEYS: "#22c55e",
            AgentState.OK_NO_KEYS: "#facc15",
            AgentState.ERROR: "#ef4444",
        }
        dot_color = color_map.get(snapshot.state, "#64748b")
        self.ssh_status_dot.setStyleSheet(f"background: {dot_color}; border-radius: 5px;")

        if snapshot.state is AgentState.OK_KEYS:
            headline = "SSH agent reachable, keys loaded"
        elif snapshot.state is AgentState.OK_NO_KEYS:
            headline = "SSH agent reachable, no keys loaded"
        elif snapshot.state is AgentState.OFF:
            headline = "SSH agent usage disabled"
        else:
            headline = "SSH agent issue detected"
        self.ssh_status_label.setText(headline)

        tooltip = self._build_ssh_agent_tooltip(snapshot)
        self._ssh_agent_tooltip = tooltip
        self.ssh_status_label.setToolTip(tooltip)
        self.ssh_status_dot.setToolTip(tooltip)
        self.ssh_details.setPlainText(tooltip)

    def _build_ssh_agent_tooltip(self, snapshot: StatusSnapshot) -> str:
        use_state = "ON" if snapshot.use_agent_enabled else "OFF"
        reachable = "Yes" if snapshot.agent_reachable else "No"
        keys_loaded = str(snapshot.keys_loaded) if snapshot.keys_loaded is not None else "n/a"
        sock_value = snapshot.ssh_auth_sock or "not set"
        lines = [
            "SSH Agent",
            "--------",
            f"Use agent: {use_state}",
            f"SSH_AUTH_SOCK: {sock_value}",
            f"Reachable: {reachable}",
            f"Keys loaded: {keys_loaded}",
        ]

        if snapshot.detected_while_off:
            lines.append("Detected while off: yes")

        if snapshot.keys:
            lines.append("Fingerprints:")
            lines.extend(self._format_key_lines(snapshot.keys))

        last_check = snapshot.last_checked.strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"Last check: {last_check}")
        lines.append(f"Error: {snapshot.last_error or '(none)'}")
        return "\n".join(lines)

    def _format_key_lines(self, keys: tuple[KeyInfo, ...]) -> list[str]:
        max_keys = 12
        lines: list[str] = []
        for key in keys[:max_keys]:
            if key.comment:
                lines.append(f"  {key.fingerprint} ({key.comment})")
            else:
                lines.append(f"  {key.fingerprint}")
        remaining = len(keys) - max_keys
        if remaining > 0:
            lines.append(f"  ... ({remaining} more)")
        return lines

    def _export_json(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export JSON",
            "shelldeck-export.json",
            "JSON Files (*.json)",
        )
        if not path:
            return
        settings = {
            "theme": {
                "mode": self.mode_combo.currentText() or DEFAULT_MODE,
                "accent": self._accent.name() or DEFAULT_ACCENT,
            }
        }
        export_json(self._repo, path, settings=settings)
        QtWidgets.QMessageBox.information(self, "Export complete", "JSON export saved.")

    def _import_json(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Import JSON",
            "",
            "JSON Files (*.json)",
        )
        if not path:
            return
        result = import_json(self._repo, path)
        QtWidgets.QMessageBox.information(
            self,
            "Import complete",
            f"Groups added: {result.groups_added}\n"
            f"Hosts inserted: {result.hosts_inserted}\n"
            f"Hosts updated: {result.hosts_updated}",
        )
        self.data_changed.emit()

    def _import_from_ssh_config(self) -> None:
        entries = list_ssh_config_entries()
        if not entries:
            QtWidgets.QMessageBox.information(self, "No entries", "No SSH config entries found.")
            return
        dialog = SshImportDialog(entries, self)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        selected = dialog.selected_entries()
        if not selected:
            return
        group = self._repo.get_or_create_group("Imported")
        inserted = 0
        updated = 0
        for entry in selected:
            existing = self._repo.find_host_for_merge(group.id, entry.hostname, entry.alias)
            if existing:
                updated_host = Host(
                    id=existing.id,
                    group_id=group.id,
                    name=entry.alias,
                    hostname=entry.hostname,
                    port=entry.port or existing.port,
                    user=entry.user or existing.user,
                    identity_file=entry.identity_file or existing.identity_file,
                    ssh_config_host_alias=entry.alias,
                    notes=existing.notes,
                    tags=existing.tags,
                    favorite=existing.favorite,
                    color=existing.color,
                    tag=existing.tag,
                )
                self._repo.update_host(updated_host)
                updated += 1
            else:
                host = Host(
                    id=0,
                    group_id=group.id,
                    name=entry.alias,
                    hostname=entry.hostname,
                    port=entry.port,
                    user=entry.user,
                    identity_file=entry.identity_file,
                    ssh_config_host_alias=entry.alias,
                    notes=None,
                    tags=[],
                    favorite=False,
                    color=None,
                    tag=None,
                )
                self._repo.create_host(host)
                inserted += 1
        QtWidgets.QMessageBox.information(
            self,
            "Import complete",
            f"Imported: {inserted}\nUpdated: {updated}",
        )
        self.data_changed.emit()
